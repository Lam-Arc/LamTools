"""Task-scoped conversation and workspace checkpoints.

The public coordinator deliberately hides storage details.  Callers create a
checkpoint before a main- or sub-agent turn, then restore or undo through the
same interface.  Workspace content is stored outside the workspace in a small
content-addressed store, so this module never commits, resets, or touches a
user's Git index.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any, Literal, Protocol, cast
import uuid
from weakref import WeakValueDictionary

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from lamtools_core.app.core_db import (
    CoreAppEvent,
    CoreCheckpoint,
    CoreCheckpointAttachmentRef,
    CoreCheckpointBlob,
    CoreCheckpointBlobRef,
    CoreCheckpointV2,
    CoreCheckpointV2Materialized,
    CoreCheckpointV2SessionHistory,
    CoreCheckpointV2SessionMessages,
    CoreHistoryEntry,
    CoreDbBase,
    CoreRestoreOperation,
    CoreRuntimeSession,
    CoreThreadSnapshot,
    CoreThreadSnapshotItem,
    CoreWorkspaceManifest,
)
from lamtools_core.app.event_store import SqlAlchemyAppEventStore
from lamtools_core.app.snapshot_store import CoreAppSnapshotProjector, SqlAlchemyThreadSnapshotStore
from lamtools_core.app.sqlite_write import SQLiteWriteCoordinator
from lamtools_core.app.operation_catalog import OperationCatalog, OperationRequest, OperationResult


ActorKind = Literal["main", "sub_agent", "tool", "hook", "restore", "fork"]
CheckpointEdgeKind = Literal["checkpoint", "hook", "rollback", "session_fork"]
RestoreScope = Literal["conversation", "workspace", "all"]
_RESTORE_SCOPES = frozenset({"conversation", "workspace", "all"})


@dataclass(frozen=True)
class CheckpointRef:
    id: str
    graph_id: str
    root_session_id: str
    session_id: str
    parent_checkpoint_id: str
    edge_kind: str
    turn_id: str
    actor_kind: str
    reason: str
    label: str
    work_root: str
    manifest_hash: str
    created_at: datetime
    session_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RestoreResult:
    operation_id: str
    checkpoint_id: str
    undo_checkpoint_id: str
    derived_checkpoint_id: str
    scope: RestoreScope
    status: str
    restored_paths: tuple[str, ...]


@dataclass(frozen=True)
class CheckpointEdge:
    parent_checkpoint_id: str
    checkpoint_id: str
    kind: str


@dataclass(frozen=True)
class CheckpointGraph:
    graph_id: str
    nodes: tuple[CheckpointRef, ...]
    edges: tuple[CheckpointEdge, ...]
    heads: dict[str, str]


class TurnCheckpointCoordinator(Protocol):
    async def begin_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        actor_kind: str = "main",
    ) -> CheckpointRef: ...

    async def save(
        self,
        *,
        session_id: str,
        turn_id: str,
        actor_kind: str = "main",
        reason: str = "manual",
        label: str = "",
        edge_kind: str = "checkpoint",
    ) -> CheckpointRef: ...


@dataclass(frozen=True)
class ForkConversationResult:
    conversation: dict[str, Any]
    session_payload: dict[str, Any] = field(default_factory=dict)


class CheckpointConversationBackend(Protocol):
    """Member seam for capturing and restoring conversation-owned state."""

    async def capture(self, session_id: str, *, exclude_turn_id: str = "") -> dict[str, Any]: ...

    async def restore(self, db: Any, session_id: str, payload: dict[str, Any]) -> None: ...

    async def require_inactive(self, session_id: str) -> None: ...

    async def fork(
        self,
        db: Any,
        *,
        source_session_id: str,
        new_session_id: str,
        payload: dict[str, Any],
        title: str,
        options: dict[str, Any],
    ) -> ForkConversationResult: ...

_WORKSPACE_LOCKS: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_SKIPPED_DIRECTORIES = {".git", ".hg", ".svn", "node_modules", "__pycache__"}

_logger = logging.getLogger(__name__)
# Files larger than this are never copied into checkpoint blob storage (full
# copies of huge files on every tool edit would balloon disk usage).
MAX_BACKUP_FILE_BYTES = 200 * 1024 * 1024  # 200 MB
# Each session keeps only this many most-recent TURNS on its main line
# (nodes with actor_kind == "main"). Restore bookkeeping (undo/derived) and
# fork markers never consume the window, so the pool of rollback targets is
# always MAX_CHECKPOINTS_PER_SESSION — rolling back can't shrink it.
# Checkpoints created by branching (rolling back then continuing) fall off
# the main line and are pruned together with older turns — a branch cannot be
# revisited once a newer turn has been accepted.
MAX_CHECKPOINTS_PER_SESSION = 6
CHECKPOINT_OPERATION_NAMES = (
    "session.checkpoints.create",
    "session.checkpoints.graph",
    "session.checkpoints.list",
    "session.checkpoints.restore",
    "session.rollback",
    "session.fork",
)


class CoreCheckpointCoordinator:
    """Deep module that owns checkpoint capture, restore, and restore undo."""

    def __init__(
        self,
        work_root: str | Path,
        session_factory: async_sessionmaker,
        write_coordinator: SQLiteWriteCoordinator | None = None,
        storage_root: str | Path | None = None,
        conversation_backend: CheckpointConversationBackend | None = None,
    ) -> None:
        self.work_root = Path(work_root).resolve()
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator or SQLiteWriteCoordinator(session_factory)
        self.database_path = _database_path(session_factory)
        self.storage_root = (
            Path(storage_root).resolve()
            if storage_root is not None
            else _default_storage_root(session_factory)
        )
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.conversation_backend = conversation_backend or CoreCheckpointConversationBackend(session_factory)
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()
        key = os.path.normcase(str(self.work_root))
        lock = _WORKSPACE_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _WORKSPACE_LOCKS[key] = lock
        self._workspace_lock = lock
        # Most-recent checkpoint ref for this workspace, so backup_file can
        # append to its manifest. Initialised to None so the `if ref is None`
        # early-return in backup_file works before any save() has run.
        self._latest_checkpoint: CheckpointRef | None = None

    async def begin_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        actor_kind: str = "main",
    ) -> CheckpointRef:
        return await self.save(
            session_id=session_id,
            turn_id=turn_id,
            actor_kind=actor_kind,
            reason="before_user_prompt",
            label="用户指令前自动存档",
        )

    async def save(
        self,
        *,
        session_id: str,
        turn_id: str,
        actor_kind: str = "main",
        reason: str = "manual",
        label: str = "",
        edge_kind: str = "checkpoint",
        parent_checkpoint_id: str | None = None,
    ) -> CheckpointRef:
        await self._ensure_schema()
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("session_id is required")
        async with self._workspace_lock:
            ref = await self._capture(
                session_id=normalized_session_id,
                turn_id=str(turn_id or "manual").strip() or "manual",
                actor_kind=str(actor_kind or "main"),
                reason=str(reason or "manual"),
                label=str(label or ""),
                edge_kind=str(edge_kind or "checkpoint"),
                parent_checkpoint_id=parent_checkpoint_id,
            )
            self._latest_checkpoint = ref
            return ref

    async def backup_file(self, *, session_id: str, path: str | Path) -> None:
        """Back up a single file before it is modified by a tool.

        Reads the current content, writes a blob, and appends the file entry
        to the latest checkpoint's workspace manifest. Files larger than
        ``MAX_BACKUP_FILE_BYTES`` are skipped so a huge file being touched by
        a tool cannot balloon blob storage (full copies of a multi-GB file on
        every edit).
        """
        await self._ensure_schema()
        file_path = Path(path).resolve()
        if not file_path.is_file():
            return
        if not _is_within(file_path, self.work_root):
            # Outside the workspace (allow_access_outside_workdir or a symlink
            # escape): skip backing up instead of recording an absolute-path
            # manifest key — _apply_manifest rejects absolute paths, so one
            # such entry would permanently break every later rollback
            # (audit 08 S2).
            _logger.warning("checkpoint backup skipped (outside workspace): %s", file_path)
            return
        relative = str(file_path.relative_to(self.work_root).as_posix())
        # No checkpoint yet — writing a blob now would create an unreferenced
        # orphan (audit 08 S3). Skip before any storage I/O.
        async with self._workspace_lock:
            if self._latest_checkpoint is None:
                return
        try:
            size = file_path.stat().st_size
        except OSError:
            return
        if size > MAX_BACKUP_FILE_BYTES:
            _logger.warning(
                "checkpoint backup skipped (file too large: %.1f MB > %d MB): %s",
                size / 1e6,
                MAX_BACKUP_FILE_BYTES / 1e6,
                relative,
            )
            return
        data = file_path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        blob_path = await self._write_blob(digest, data)
        mode = stat.S_IMODE(file_path.stat().st_mode)
        entry = {"hash": digest, "size": len(data), "mode": mode}
        async with self._workspace_lock:
            ref = self._latest_checkpoint
            if ref is None:
                return
            await self._append_file_to_manifest(
                checkpoint_id=ref.id,
                relative=relative,
                entry=entry,
                digest=digest,
                blob_path=blob_path,
                size=len(data),
            )

    async def _write_blob(self, digest: str, data: bytes) -> Path:
        """Persist a content-addressed blob, returning its storage path."""
        blob_root = self.storage_root / "blobs"
        blob_path = blob_root / digest[:2] / digest
        if not blob_path.exists():
            blob_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=f"{digest}.", dir=blob_path.parent)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.replace(temp_name, blob_path)
                except FileExistsError:
                    os.unlink(temp_name)
            except BaseException:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
                raise
        return blob_path

    async def _backup_manifest_files(self, checkpoint_id: str, manifest_hash: str) -> None:
        """Back up the *current* content of every file the target manifest
        touches, appended to the given (undo) checkpoint's manifest.

        A rollback replaces files with target content; if it fails mid-way,
        the already-replaced files must be reversible. The undo node is a
        lazy capture with an empty manifest, so without this real backup a
        failed rollback leaves the workspace in a mixed state with no way to
        compensate (audit 08 S3).
        """
        target = await self._manifest(manifest_hash)
        if not target:
            return
        for relative in sorted(target):
            destination = _safe_workspace_path(self.work_root, relative)
            if not destination.is_file():
                continue
            try:
                size = destination.stat().st_size
                if size > MAX_BACKUP_FILE_BYTES:
                    continue
                data = destination.read_bytes()
            except OSError:
                continue
            digest = hashlib.sha256(data).hexdigest()
            blob_path = await self._write_blob(digest, data)
            entry = {"hash": digest, "size": len(data), "mode": stat.S_IMODE(destination.stat().st_mode)}
            await self._append_file_to_manifest(
                checkpoint_id=checkpoint_id,
                relative=relative,
                entry=entry,
                digest=digest,
                blob_path=blob_path,
                size=len(data),
            )

    async def _append_file_to_manifest(
        self,
        *,
        checkpoint_id: str,
        relative: str,
        entry: dict[str, Any],
        digest: str,
        blob_path: Path,
        size: int,
    ) -> None:
        async def write(db: Any) -> None:
            cp = await db.get(CoreCheckpoint, checkpoint_id)
            if cp is None:
                return
            old_hash = cp.manifest_hash
            if old_hash:
                manifest_row = await db.get(CoreWorkspaceManifest, old_hash)
                merged = dict(manifest_row.entries_json or {}) if manifest_row is not None else {}
            else:
                merged = {}
            if relative in merged:
                return  # already backed up
            merged[relative] = entry
            new_hash = hashlib.sha256(
                json.dumps(merged, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if await db.get(CoreWorkspaceManifest, new_hash) is None:
                db.add(CoreWorkspaceManifest(hash=new_hash, entries_json=merged))
            if await db.get(CoreCheckpointBlob, digest) is None:
                db.add(CoreCheckpointBlob(hash=digest, size=size, storage_path=str(blob_path)))
            cp.manifest_hash = new_hash
            db.add(cp)
        await self.write_coordinator.run(write)

    async def list(self, session_id: str) -> list[CheckpointRef]:
        await self._ensure_schema()
        graph = await self.graph(session_id)
        return list(reversed(graph.nodes))

    async def graph(self, session_id: str) -> CheckpointGraph:
        await self._ensure_schema()
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("session_id is required")
        root_session_id = _root_session_id(normalized_session_id)
        async with self.session_factory() as db:
            head = (await db.execute(
                select(CoreCheckpoint)
                .where(CoreCheckpoint.session_id == normalized_session_id)
                .where(CoreCheckpoint.status == "ready")
                .order_by(CoreCheckpoint.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if head is None and normalized_session_id != root_session_id:
                head = (await db.execute(
                    select(CoreCheckpoint)
                    .where(CoreCheckpoint.session_id == root_session_id)
                    .where(CoreCheckpoint.status == "ready")
                    .order_by(CoreCheckpoint.created_at.desc())
                    .limit(1)
                )).scalar_one_or_none()
            graph_id = str(head.graph_id or head.root_session_id) if head is not None else root_session_id
            rows = list((await db.execute(
                select(CoreCheckpoint)
                .where(CoreCheckpoint.graph_id == graph_id)
                .where(CoreCheckpoint.status == "ready")
                .order_by(CoreCheckpoint.created_at.asc(), CoreCheckpoint.id.asc())
            )).scalars())
        refs = tuple(_checkpoint_ref(row) for row in rows)
        heads: dict[str, str] = {}
        for row in refs:
            heads[row.session_id] = row.id
        return CheckpointGraph(
            graph_id=graph_id,
            nodes=refs,
            edges=tuple(
                CheckpointEdge(
                    parent_checkpoint_id=row.parent_checkpoint_id,
                    checkpoint_id=row.id,
                    kind=row.edge_kind,
                )
                for row in refs
                if row.parent_checkpoint_id
            ),
            heads=heads,
        )

    async def load(
        self,
        checkpoint_id: str,
        *,
        scope: RestoreScope | str = "all",
        requesting_session_id: str = "",
    ) -> RestoreResult:
        await self._ensure_schema()
        restore_scope = _normalize_restore_scope(scope)
        async with self._workspace_lock:
            target = await self._checkpoint(checkpoint_id)
            if requesting_session_id and target.root_session_id != _root_session_id(requesting_session_id):
                raise ValueError("Checkpoint does not belong to this session family")
            if Path(target.work_root).resolve() != self.work_root:
                raise ValueError("Checkpoint belongs to a different workspace")
            if restore_scope != "workspace":
                await self.conversation_backend.require_inactive(target.session_id)
            undo = await self._capture(
                session_id=target.session_id,
                turn_id=f"restore:{checkpoint_id}",
                actor_kind="restore",
                reason="before_rollback",
                label="回滚前自动存档",
                edge_kind="checkpoint",
                # Attach the pre-rollback snapshot to the target node: the
                # mainline prune keeps only the newest 6 nodes per session, and
                # a tail-attached undo would push the rollback target out of
                # the window before the derived node can link to it.
                parent_checkpoint_id=target.id,
            )
            operation_id = uuid.uuid4().hex
            await self._create_operation(operation_id, target, undo.id, restore_scope)
            undo_row = await self._checkpoint(undo.id)
            restored_paths: tuple[str, ...] = ()
            workspace_touched = False
            conversation_touched = False
            try:
                if restore_scope in {"workspace", "all"}:
                    workspace_touched = True
                    # Real backup of every file the rollback will touch, so a
                    # mid-rollback failure stays fully reversible (audit 08 S3).
                    await self._backup_manifest_files(undo.id, target.manifest_hash)
                    restored_paths = tuple(await self._apply_manifest(target.manifest_hash))
                if restore_scope in {"conversation", "all"}:
                    conversation_touched = True
                    await self._restore_conversation(target, operation_id)
                derived = await self._capture(
                    session_id=target.session_id,
                    turn_id=f"rollback:{operation_id}",
                    actor_kind="restore",
                    reason=f"rollback_{restore_scope}",
                    label=_restore_label(restore_scope),
                    edge_kind="rollback",
                    # Link the post-rollback node under the pre-rollback undo
                    # node so the mainline chain reads derived -> undo -> target.
                    # (A sibling link straight to target would let the prune
                    # drop the undo node, along with the restore operation that
                    # references it.)
                    parent_checkpoint_id=undo.id,
                )
                await self._complete_operation(operation_id, derived.id)
            except BaseException as exc:
                try:
                    if conversation_touched:
                        await self._restore_conversation(undo_row, operation_id)
                    if workspace_touched:
                        await self._apply_manifest(undo_row.manifest_hash)
                finally:
                    await self._fail_operation(operation_id, str(exc))
                raise
            return RestoreResult(
                operation_id=operation_id,
                checkpoint_id=target.id,
                undo_checkpoint_id=undo.id,
                derived_checkpoint_id=derived.id,
                scope=restore_scope,
                status="committed",
                restored_paths=restored_paths,
            )

    async def restore(
        self,
        checkpoint_id: str,
        *,
        scope: RestoreScope | str = "all",
        requesting_session_id: str = "",
    ) -> RestoreResult:
        return await self.load(
            checkpoint_id,
            scope=scope,
            requesting_session_id=requesting_session_id,
        )

    async def fork(
        self,
        checkpoint_id: str,
        *,
        new_session_id: str | None = None,
        title: str = "",
        options: dict[str, Any] | None = None,
    ) -> CheckpointRef:
        """Branch stored conversation history into a new session.

        Like Codex thread/fork, this does not mutate the source session or the
        shared workspace.  The graph node keeps the source workspace manifest,
        and the new session's next automatic checkpoint captures its live
        workspace state.
        """
        await self._ensure_schema()
        async with self._workspace_lock:
            target = await self._checkpoint(checkpoint_id)
            if target.session_id != target.root_session_id:
                raise ValueError("Only a main-session checkpoint can be forked")
            fork_session_id = str(new_session_id or uuid.uuid4().hex).strip()
            if not fork_session_id or _root_session_id(fork_session_id) != fork_session_id:
                raise ValueError("new_session_id must identify a main session")
            conversation = await self._conversation_payload_for_fork(target)
            now = datetime.now()
            fork_checkpoint_id = uuid.uuid4().hex
            source_session_id = target.session_id

            async def write(db: Any) -> CheckpointRef:
                forked = await self.conversation_backend.fork(
                    db,
                    source_session_id=source_session_id,
                    new_session_id=fork_session_id,
                    payload=conversation,
                    title=title,
                    options={**dict(options or {}), "checkpoint_id": target.id},
                )
                row = CoreCheckpoint(
                    id=fork_checkpoint_id,
                    graph_id=str(target.graph_id or target.root_session_id),
                    root_session_id=fork_session_id,
                    session_id=fork_session_id,
                    parent_checkpoint_id=target.id,
                    edge_kind="session_fork",
                    turn_id=f"fork:{target.id}",
                    actor_kind="fork",
                    reason="session_fork",
                    label="分叉到新会话",
                    work_root=target.work_root,
                    manifest_hash=target.manifest_hash,
                    conversation_json={},
                    status="ready",
                    created_at=now,
                )
                db.add(row)
                await db.flush()
                fork_snapshot = await db.get(CoreThreadSnapshot, fork_session_id)
                fork_state = dict(fork_snapshot.snapshot_json or {}) if fork_snapshot is not None else {}
                db.add(CoreCheckpointV2SessionMessages(
                    checkpoint_id=fork_checkpoint_id,
                    messages_json=list(fork_state.get("messages") or []),
                    created_at=now,
                ))
                runtime = await db.get(CoreRuntimeSession, fork_session_id)
                db.add(CoreCheckpointV2SessionHistory(
                    checkpoint_id=fork_checkpoint_id,
                    history_json=list(runtime.history_json or []) if runtime is not None else [],
                    created_at=now,
                ))
                event_seq = int((await db.execute(
                    select(func.coalesce(func.max(CoreAppEvent.seq), 0)).where(
                        CoreAppEvent.thread_id == fork_session_id,
                    )
                )).scalar_one())
                history_seq = int((await db.execute(
                    select(func.coalesce(func.max(CoreHistoryEntry.seq), 0)).where(
                        CoreHistoryEntry.thread_id == fork_session_id,
                    )
                )).scalar_one())
                db.add(CoreCheckpointV2(
                    id=fork_checkpoint_id,
                    root_session_id=fork_session_id,
                    session_id=fork_session_id,
                    parent_checkpoint_id=target.id,
                    turn_id=f"fork:{target.id}",
                    actor_kind="fork",
                    reason="session_fork",
                    status="ready",
                    event_seq=event_seq,
                    history_seq=history_seq,
                    runtime_state_json=dict(runtime.runtime_state_json or {}) if runtime is not None else {},
                    workspace_manifest_id=target.manifest_hash,
                    metadata_json={"v2_only": True},
                    created_at=now,
                ))
                return replace(_checkpoint_ref(row), session_payload=dict(forked.session_payload))

            return await self.write_coordinator.run(write)

    async def _conversation_payload_for_fork(self, target: CoreCheckpoint) -> dict[str, Any]:
        """Build the temporary fork input without persisting a legacy blob."""
        if target.conversation_json:
            return copy.deepcopy(dict(target.conversation_json))
        async with self.session_factory() as db:
            checkpoint = await db.get(CoreCheckpointV2, target.id)
            if checkpoint is None:
                raise LookupError("V2 checkpoint not found")
            materialized = await db.get(CoreCheckpointV2Materialized, target.id)
            if materialized is not None:
                runtime_payload = copy.deepcopy(dict(materialized.runtime_json or {})) if materialized.runtime_present else None
                projection_payload = copy.deepcopy(dict(materialized.projection_json or {})) if materialized.projection_present else None
                if materialized.events_json is not None:
                    events_payload = copy.deepcopy(list(materialized.events_json or []))
                else:
                    events_payload = await self._event_payloads_until(db, target.session_id, checkpoint.event_seq)
                session_messages = await db.get(CoreCheckpointV2SessionMessages, target.id)
                if session_messages is not None:
                    if projection_payload is None:
                        projection_payload = {
                            "snapshot_seq": 0,
                            "snapshot_json": CoreAppSnapshotProjector().empty(target.session_id),
                        }
                    projection_state = dict(projection_payload.get("snapshot_json") or {})
                    projection_state["messages"] = copy.deepcopy(list(session_messages.messages_json or []))
                    projection_payload["snapshot_json"] = projection_state
                history_payload = list(materialized.history_json or [])
                if isinstance(runtime_payload, dict):
                    runtime_payload["history_json"] = copy.deepcopy(history_payload)
                return {
                    "session_id": target.session_id,
                    "runtime": runtime_payload,
                    "projection": projection_payload,
                    "events": events_payload,
                }

            runtime = await db.get(CoreRuntimeSession, target.session_id)
            runtime_payload = _runtime_payload(runtime)
            boundary_history = await db.get(CoreCheckpointV2SessionHistory, target.id)
            if boundary_history is not None:
                history_payload = [dict(item) for item in list(boundary_history.history_json or []) if isinstance(item, dict)]
            else:
                history_rows = list((await db.execute(
                    select(CoreHistoryEntry).where(
                        CoreHistoryEntry.thread_id == target.session_id,
                        CoreHistoryEntry.seq <= checkpoint.history_seq,
                    ).order_by(CoreHistoryEntry.seq.asc())
                )).scalars())
                history_payload = [dict(row.message_json or {}) for row in history_rows]
            if isinstance(runtime_payload, dict):
                runtime_payload["history_json"] = history_payload
            snapshot = await SqlAlchemyThreadSnapshotStore(
                CoreThreadSnapshot,
                item_model=CoreThreadSnapshotItem,
            ).load(db, target.session_id)
            session_messages = await db.get(CoreCheckpointV2SessionMessages, target.id)
            projection_payload = _projection_payload(snapshot)
            if session_messages is not None:
                projection_state = dict(projection_payload.get("snapshot_json") or {})
                projection_state["messages"] = copy.deepcopy(list(session_messages.messages_json or []))
                projection_payload["snapshot_json"] = projection_state
            return {
                "session_id": target.session_id,
                "runtime": runtime_payload,
                "projection": projection_payload,
                "events": await self._event_payloads_until(db, target.session_id, checkpoint.event_seq),
            }

    @staticmethod
    async def _event_payloads_until(db: Any, session_id: str, event_seq: int) -> list[dict[str, Any]]:
        rows = list((await db.execute(
            select(CoreAppEvent).where(
                CoreAppEvent.thread_id == session_id,
                CoreAppEvent.seq <= int(event_seq or 0),
            ).order_by(CoreAppEvent.seq.asc())
        )).scalars())
        store = SqlAlchemyAppEventStore(CoreAppEvent)
        return [store._to_envelope(row).to_dict() for row in rows]

    async def _capture(
        self,
        *,
        session_id: str,
        turn_id: str,
        actor_kind: str,
        reason: str,
        label: str,
        edge_kind: str,
        parent_checkpoint_id: str | None = None,
    ) -> CheckpointRef:
        # Lazy workspace capture only: files are snapshotted individually by
        # backup_file() right before a tool modifies them. There is no full
        # workspace scan anywhere — a huge work_root (e.g. a game-save
        # directory) can never stall the app. See _apply_manifest for rollback
        # semantics (only tool-backed files are restored).
        manifest_hash = ""
        entries: dict[str, Any] = {}
        blobs: list[tuple[str, int, str]] = []
        root_session_id = _root_session_id(session_id)
        checkpoint_id = uuid.uuid4().hex
        created_at = datetime.now()

        async def write(db: Any) -> CheckpointRef:
            parent = await self._resolve_parent(
                db,
                session_id=session_id,
                root_session_id=root_session_id,
                parent_checkpoint_id=parent_checkpoint_id,
            )
            graph_id = str(parent.graph_id or parent.root_session_id) if parent is not None else root_session_id
            manifest = await db.get(CoreWorkspaceManifest, manifest_hash)
            if manifest is None:
                db.add(CoreWorkspaceManifest(hash=manifest_hash, entries_json=entries))
            for blob_hash, size, storage_path in blobs:
                if await db.get(CoreCheckpointBlob, blob_hash) is None:
                    db.add(CoreCheckpointBlob(hash=blob_hash, size=size, storage_path=storage_path))
            row = CoreCheckpoint(
                id=checkpoint_id,
                graph_id=graph_id,
                root_session_id=root_session_id,
                session_id=session_id,
                parent_checkpoint_id=parent.id if parent is not None else "",
                edge_kind=edge_kind,
                turn_id=turn_id,
                actor_kind=actor_kind,
                reason=reason,
                label=label,
                work_root=str(self.work_root),
                manifest_hash=manifest_hash,
                conversation_json={},
                status="ready",
                created_at=created_at,
            )
            db.add(row)
            # V2 checkpoints are metadata-only.  Exclude the turn currently
            # being opened, matching the old capture semantics without ever
            # materializing the conversation/event/snapshot payload.
            event_seq = int((await db.execute(
                select(func.coalesce(func.max(CoreAppEvent.seq), 0)).where(
                    CoreAppEvent.thread_id == session_id,
                    or_(CoreAppEvent.turn_id.is_(None), CoreAppEvent.turn_id != turn_id),
                )
            )).scalar_one())
            runtime = await db.get(CoreRuntimeSession, session_id)
            history_rows = list((await db.execute(
                select(CoreHistoryEntry).where(
                    CoreHistoryEntry.thread_id == session_id,
                ).order_by(CoreHistoryEntry.seq.asc())
            )).scalars())
            history_seq = max((int(item.seq or 0) for item in history_rows), default=0)
            if history_rows:
                history_payload = [dict(item.message_json or {}) for item in history_rows]
            else:
                history_payload = [
                    copy.deepcopy(message)
                    for message in list(runtime.history_json or [])
                    if isinstance(message, dict)
                ] if runtime is not None and isinstance(runtime.history_json, list) else []
            db.add(CoreCheckpointV2SessionHistory(
                checkpoint_id=checkpoint_id,
                history_json=history_payload,
                created_at=created_at,
            ))
            if session_id == root_session_id:
                snapshot_row = await db.get(CoreThreadSnapshot, session_id)
                snapshot_state = dict(snapshot_row.snapshot_json or {}) if snapshot_row is not None else {}
                db.add(CoreCheckpointV2SessionMessages(
                    checkpoint_id=checkpoint_id,
                    messages_json=list(snapshot_state.get("messages") or []),
                    created_at=created_at,
                ))
            db.add(CoreCheckpointV2(
                id=checkpoint_id,
                root_session_id=root_session_id,
                session_id=session_id,
                parent_checkpoint_id=parent.id if parent is not None else "",
                turn_id=turn_id,
                actor_kind=actor_kind,
                reason=reason,
                status="ready",
                event_seq=event_seq,
                history_seq=history_seq,
                runtime_state_json=dict(runtime.runtime_state_json or {}) if runtime is not None else {},
                workspace_manifest_id=manifest_hash,
                metadata_json={"v2_only": True},
                created_at=created_at,
            ))
            await db.flush()
            await self._prune_mainline(db, root_session_id=root_session_id, latest_id=checkpoint_id)
            return _checkpoint_ref(row)

        return await self.write_coordinator.run(write)

    async def _prune_mainline(
        self,
        db: Any,
        *,
        root_session_id: str,
        latest_id: str,
    ) -> None:
        """Keep only the most recent ``MAX_CHECKPOINTS_PER_SESSION`` turns.

        Only real conversation turns consume the window — nodes whose
        ``actor_kind == "main"`` (the automatic ``before_user_prompt`` saves
        plus manual main-line saves). Restore bookkeeping (the ``undo`` /
        ``derived`` nodes each rollback creates) never counts against it, so
        rolling back cannot shrink the pool of rollback targets: 6 turns in
        the window means 6 rollbacks available, guaranteed.

        The main line is the chain ``latest -> parent -> ...``. Everything
        below the 6th turn checkpoint (older turns and their bookkeeping) is
        deleted; surviving nodes whose parent was pruned are re-linked to the
        nearest surviving ancestor. Restore operations referencing pruned
        checkpoints are deleted too.
        """
        rows = list((await db.execute(
            select(CoreCheckpoint).where(CoreCheckpoint.root_session_id == root_session_id)
        )).scalars())
        if not rows:
            return
        by_id = {row.id: row for row in rows}

        # Walk the main line from the newest node backwards, counting turns.
        chain: list[str] = []
        seen: set[str] = set()
        node_id = latest_id
        turn_count = 0
        while node_id and node_id not in seen:
            row = by_id.get(node_id)
            if row is None:
                break
            seen.add(node_id)
            chain.append(node_id)
            if row.actor_kind == "main":
                turn_count += 1
                if turn_count == MAX_CHECKPOINTS_PER_SESSION:
                    break  # everything below the 6th turn is pruned
            node_id = row.parent_checkpoint_id
        keep = set(chain)
        deleted = {row.id for row in rows if row.id not in keep}
        if not deleted:
            return
        deleted_sorted = sorted(deleted)

        # Re-link surviving nodes (in this group or referencing pruned nodes
        # across groups, e.g. a fork whose parent got pruned) to the nearest
        # surviving ancestor on their parent chain.
        def nearest_surviving_ancestor(from_id: str) -> str:
            guard = 0
            cursor = from_id
            while cursor and guard < 1024:
                guard += 1
                if cursor in keep:
                    return cursor
                cursor = by_id[cursor].parent_checkpoint_id if cursor in by_id else ""
            return ""

        orphans = list((await db.execute(
            select(CoreCheckpoint).where(CoreCheckpoint.parent_checkpoint_id.in_(deleted_sorted))
        )).scalars())
        for row in orphans:
            row.parent_checkpoint_id = nearest_surviving_ancestor(row.parent_checkpoint_id)

        await db.execute(
            delete(CoreCheckpoint).where(CoreCheckpoint.id.in_(deleted_sorted))
        )
        await db.execute(
            delete(CoreCheckpointV2).where(CoreCheckpointV2.id.in_(deleted_sorted))
        )
        await db.execute(
            delete(CoreCheckpointV2SessionMessages).where(
                CoreCheckpointV2SessionMessages.checkpoint_id.in_(deleted_sorted)
            )
        )
        await db.execute(
            delete(CoreCheckpointV2SessionHistory).where(
                CoreCheckpointV2SessionHistory.checkpoint_id.in_(deleted_sorted)
            )
        )
        # Drop restore operations that reference pruned checkpoints (their
        # undo/redo targets no longer exist).
        await db.execute(
            delete(CoreRestoreOperation).where(
                CoreRestoreOperation.target_checkpoint_id.in_(deleted_sorted)
                | CoreRestoreOperation.undo_checkpoint_id.in_(deleted_sorted)
                | CoreRestoreOperation.derived_checkpoint_id.in_(deleted_sorted)
            )
        )

    async def _resolve_parent(
        self,
        db: Any,
        *,
        session_id: str,
        root_session_id: str,
        parent_checkpoint_id: str | None,
    ) -> CoreCheckpoint | None:
        if parent_checkpoint_id:
            parent = await db.get(CoreCheckpoint, parent_checkpoint_id)
            if parent is None or parent.status != "ready":
                raise LookupError("Parent checkpoint not found")
            return parent
        parent = (await db.execute(
            select(CoreCheckpoint)
            .where(CoreCheckpoint.session_id == session_id)
            .where(CoreCheckpoint.status == "ready")
            .order_by(CoreCheckpoint.created_at.desc(), CoreCheckpoint.id.desc())
            .limit(1)
        )).scalar_one_or_none()
        if parent is None and session_id != root_session_id:
            parent = (await db.execute(
                select(CoreCheckpoint)
                .where(CoreCheckpoint.session_id == root_session_id)
                .where(CoreCheckpoint.status == "ready")
                .order_by(CoreCheckpoint.created_at.desc(), CoreCheckpoint.id.desc())
                .limit(1)
            )).scalar_one_or_none()
        return parent

    async def _checkpoint(self, checkpoint_id: str) -> CoreCheckpoint:
        async with self.session_factory() as db:
            row = await db.get(CoreCheckpoint, checkpoint_id)
            if row is None or row.status != "ready":
                raise LookupError("Checkpoint not found")
            db.expunge(row)
            return row

    async def _manifest(self, manifest_hash: str) -> dict[str, Any]:
        if not manifest_hash:
            return {}
        async with self.session_factory() as db:
            row = await db.get(CoreWorkspaceManifest, manifest_hash)
            if row is None:
                raise LookupError("Workspace manifest not found")
            return dict(row.entries_json or {})

    async def _apply_manifest(self, manifest_hash: str) -> list[str]:
        if not manifest_hash:
            return []  # lazy checkpoint — no files to restore
        target = await self._manifest(manifest_hash)
        # Lazy manifests only contain tool-backed files; restore just those —
        # never scan the workspace and never delete anything else.
        changed = sorted(target)
        stage_root = Path(tempfile.mkdtemp(prefix="restore-", dir=self.storage_root))
        applied: list[str] = []
        try:
            for relative in changed:
                target_entry = target.get(relative)
                if target_entry is None:
                    continue  # lazy manifest — nothing to delete
                destination = _safe_workspace_path(self.work_root, relative)
                blob_hash = str(target_entry.get("hash") or "")
                source = await self._blob_path(blob_hash)
                if not source.is_file():
                    raise FileNotFoundError(f"Checkpoint blob is missing: {blob_hash}")
                staged = stage_root / relative
                staged.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, staged)
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, destination)
                try:
                    os.chmod(destination, int(target_entry.get("mode") or 0o644))
                except OSError:
                    pass
                applied.append(relative)
            _remove_empty_directories(
                self.work_root,
                self.storage_root,
                [destination.parent for destination in (
                    _safe_workspace_path(self.work_root, relative) for relative in applied
                )],
            )
            return applied
        finally:
            shutil.rmtree(stage_root, ignore_errors=True)

    async def _blob_path(self, blob_hash: str) -> Path:
        async with self.session_factory() as db:
            row = await db.get(CoreCheckpointBlob, blob_hash)
            if row is None:
                raise LookupError(f"Checkpoint blob is not registered: {blob_hash}")
            return Path(row.storage_path)

    async def _create_operation(
        self,
        operation_id: str,
        target: CoreCheckpoint,
        undo_id: str,
        scope: RestoreScope,
    ) -> None:
        async def write(db: Any) -> None:
            db.add(CoreRestoreOperation(
                id=operation_id,
                root_session_id=target.root_session_id,
                target_checkpoint_id=target.id,
                undo_checkpoint_id=undo_id,
                scope=scope,
                status="prepared",
            ))
        await self.write_coordinator.run(write)

    async def _restore_conversation(self, target: CoreCheckpoint, operation_id: str) -> None:
        async with self.session_factory() as db:
            v2 = await db.get(CoreCheckpointV2, target.id)
        # During compatibility, prefer the legacy payload while it exists:
        # it still carries session-store messages that have not yet been
        # promoted to the event/history fact streams.  V2 becomes authoritative
        # automatically after the migration removes that payload.
        if v2 is not None and not target.conversation_json:
            async def write_v2(db: Any) -> None:
                restore_v2 = getattr(self.conversation_backend, "restore_v2", None)
                if restore_v2 is None:
                    raise RuntimeError("Checkpoint V2 restore backend is not available")
                await restore_v2(db, target.session_id, v2)
                operation = await db.get(CoreRestoreOperation, operation_id)
                if operation is None:
                    raise LookupError("Restore operation disappeared")
                operation.updated_at = datetime.now()
            await self.write_coordinator.run(write_v2)
            return
        conversation = dict(target.conversation_json or {})
        conversation_session_id = str(conversation.get("session_id") or target.session_id)
        if conversation_session_id != target.session_id:
            raise ValueError("Checkpoint conversation belongs to a different session")

        async def write(db: Any) -> None:
            await self.conversation_backend.restore(db, target.session_id, conversation)

            operation = await db.get(CoreRestoreOperation, operation_id)
            if operation is None:
                raise LookupError("Restore operation disappeared")
            operation.updated_at = datetime.now()

        await self.write_coordinator.run(write)

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._schema_lock:
            if self._schema_ready:
                return
            bind = getattr(self.session_factory, "kw", {}).get("bind")
            if bind is None:
                raise RuntimeError("Checkpoint storage requires a bound async session factory")
            tables = [
                CoreCheckpoint.__table__,
                CoreCheckpointV2.__table__,
                CoreCheckpointV2Materialized.__table__,
                CoreCheckpointV2SessionHistory.__table__,
                CoreCheckpointV2SessionMessages.__table__,
                CoreCheckpointAttachmentRef.__table__,
                CoreCheckpointBlobRef.__table__,
                CoreWorkspaceManifest.__table__,
                CoreCheckpointBlob.__table__,
                CoreRestoreOperation.__table__,
            ]
            async with bind.begin() as connection:
                await connection.run_sync(
                    lambda sync_connection: CoreDbBase.metadata.create_all(
                        sync_connection,
                        tables=tables,
                        checkfirst=True,
                    )
                )
            self._schema_ready = True

    async def _complete_operation(self, operation_id: str, derived_checkpoint_id: str) -> None:
        async def write(db: Any) -> None:
            operation = await db.get(CoreRestoreOperation, operation_id)
            if operation is None:
                raise LookupError("Restore operation disappeared")
            operation.derived_checkpoint_id = derived_checkpoint_id
            operation.status = "committed"
            operation.updated_at = datetime.now()
        await self.write_coordinator.run(write)

    async def _fail_operation(self, operation_id: str, error: str) -> None:
        async def write(db: Any) -> None:
            operation = await db.get(CoreRestoreOperation, operation_id)
            if operation is not None:
                operation.status = "failed"
                operation.error = error[:2048]
                operation.updated_at = datetime.now()
        await self.write_coordinator.run(write)


class CoreCheckpointConversationBackend:
    """Standalone Core conversation persistence behind the shared checkpoint graph."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.session_factory = session_factory

    async def capture(self, session_id: str, *, exclude_turn_id: str = "") -> dict[str, Any]:
        root_session_id = _root_session_id(session_id)
        is_root_session = session_id == root_session_id
        async with self.session_factory() as db:
            runtime = await db.get(CoreRuntimeSession, session_id)
            snapshot = (
                await SqlAlchemyThreadSnapshotStore(
                    CoreThreadSnapshot, item_model=CoreThreadSnapshotItem
                ).load(db, session_id)
                if is_root_session
                else None
            )
            events = (
                await SqlAlchemyAppEventStore(CoreAppEvent).list_thread(db, thread_id=session_id)
                if is_root_session
                else []
            )
        kept_events = [
            event
            for event in events
            if not exclude_turn_id or str(event.turn_id or "") != exclude_turn_id
        ]
        return {
            "session_id": session_id,
            "runtime": _runtime_payload(runtime),
            "projection": _projection_payload_without_turn(
                snapshot,
                excluded_turn_id=exclude_turn_id,
                kept_events=kept_events,
            ),
            "events": [event.to_dict() for event in kept_events],
        }

    async def conversation_payload_through_turn(
        self,
        db: Any,
        *,
        session_id: str,
        turn_id: str,
    ) -> tuple[dict[str, Any], int]:
        """Build the durable conversation prefix ending with ``turn_id``.

        A checkpoint is an optional, richer recovery mechanism.  Fork and the
        conversation-only rollback path instead use the event log as their
        boundary, which keeps the selected user/assistant turn itself.
        """
        if session_id != _root_session_id(session_id):
            raise ValueError("Turn-based fork and rollback support main sessions only")
        normalized_turn_id = str(turn_id or "").strip()
        if not normalized_turn_id:
            raise ValueError("turn_id is required")
        event_store = SqlAlchemyAppEventStore(CoreAppEvent)
        events = await event_store.list_thread(db, thread_id=session_id)
        boundary = max(
            (index for index, event in enumerate(events) if str(event.turn_id or "") == normalized_turn_id),
            default=-1,
        )
        if boundary < 0:
            raise LookupError(f"Turn not found: {normalized_turn_id}")
        kept_events = events[: boundary + 1]
        boundary_seq = int(kept_events[-1].seq or 0)
        projection = CoreAppSnapshotProjector().reduce(session_id, kept_events)
        runtime = await db.get(CoreRuntimeSession, session_id)
        history = _conversation_history_from_events(kept_events)
        return {
            "session_id": session_id,
            "runtime": _conversation_runtime_payload(
                runtime,
                session_id=session_id,
                history=history,
                boundary_seq=boundary_seq,
                turn_id=normalized_turn_id,
            ),
            "projection": {
                "snapshot_seq": boundary_seq,
                "snapshot_json": projection,
            },
            "events": [event.to_dict() for event in kept_events],
        }, boundary_seq

    async def rollback_conversation_through_turn(
        self,
        db: Any,
        *,
        session_id: str,
        turn_id: str,
    ) -> int:
        """Discard only events after ``turn_id`` and rebuild its projection.

        This intentionally does not touch workspace files, tool side effects,
        or external systems.  The caller must have checked that the runtime is
        inactive before entering this transaction.
        """
        payload, boundary_seq = await self.conversation_payload_through_turn(
            db,
            session_id=session_id,
            turn_id=turn_id,
        )
        await db.execute(delete(CoreAppEvent).where(
            CoreAppEvent.thread_id == session_id,
            CoreAppEvent.seq > boundary_seq,
        ))
        await db.execute(delete(CoreHistoryEntry).where(CoreHistoryEntry.thread_id == session_id))
        runtime_payload = dict(payload["runtime"])
        runtime = await db.get(CoreRuntimeSession, session_id)
        if runtime is None:
            runtime = CoreRuntimeSession(thread_id=session_id)
            db.add(runtime)
        runtime.revision = max(int(runtime.revision or 0) + 1, int(runtime_payload["revision"] or 0))
        runtime.runtime_state_json = dict(runtime_payload["runtime_state_json"])
        # Keep the reconstructed history in the legacy field for this path.
        # The empty fact table makes get_history use it until the next normal
        # kernel run appends durable history entries.
        runtime.history_json = list(runtime_payload["history_json"])
        runtime.pending_approval_json = {}
        runtime.last_event_seq = boundary_seq
        runtime.updated_at = datetime.now()
        kept_events = [
            event for event in payload["events"]
            if isinstance(event, dict)
        ]
        envelopes = [
            SqlAlchemyAppEventStore(CoreAppEvent)._to_envelope(_app_event_row(event, thread_id=session_id))
            for event in kept_events
        ]
        await SqlAlchemyThreadSnapshotStore(
            CoreThreadSnapshot,
            item_model=CoreThreadSnapshotItem,
        ).rebuild(db, session_id, envelopes)
        return boundary_seq

    async def restore(self, db: Any, session_id: str, payload: dict[str, Any]) -> None:
        runtime_payload = payload.get("runtime")
        projection_payload = payload.get("projection")
        events_payload = payload.get("events")
        runtime = await db.get(CoreRuntimeSession, session_id)
        if isinstance(runtime_payload, dict):
            if runtime is None:
                runtime = CoreRuntimeSession(thread_id=session_id)
                db.add(runtime)
            runtime.revision = max(int(runtime.revision or 0) + 1, int(runtime_payload.get("revision") or 0) + 1)
            runtime.runtime_state_json = dict(runtime_payload.get("runtime_state_json") or {})
            runtime.history_json = list(runtime_payload.get("history_json") or [])
            runtime.pending_approval_json = dict(runtime_payload.get("pending_approval_json") or {})
            runtime.last_event_seq = int(runtime_payload.get("last_event_seq") or 0)
            runtime.updated_at = datetime.now()
        elif runtime is not None:
            await db.delete(runtime)

        is_root_session = session_id == _root_session_id(session_id)
        projection = await db.get(CoreThreadSnapshot, session_id) if is_root_session else None
        if isinstance(projection_payload, dict):
            # Split the captured full snapshot back into item rows + metadata
            # row (the snapshot store's write_full_projection replaces the
            # thread's existing rows).
            await SqlAlchemyThreadSnapshotStore(
                CoreThreadSnapshot, item_model=CoreThreadSnapshotItem
            ).write_full_projection(db, session_id, projection_payload)
        elif projection is not None:
            await db.delete(projection)
            await db.execute(
                delete(CoreThreadSnapshotItem).where(CoreThreadSnapshotItem.thread_id == session_id)
            )

        if is_root_session and isinstance(events_payload, list):
            await db.execute(delete(CoreAppEvent).where(CoreAppEvent.thread_id == session_id))
            for event_payload in events_payload:
                if isinstance(event_payload, dict):
                    db.add(_app_event_row(event_payload, thread_id=session_id))

    async def restore_v2(self, db: Any, session_id: str, checkpoint: CoreCheckpointV2) -> None:
        """Restore a V2 checkpoint from facts or migrated base material."""
        if checkpoint.session_id != session_id:
            raise ValueError("Checkpoint belongs to a different session")

        # Legacy checkpoints were captured from mutable event/history tables.
        # A later fork, rollback, or compact can therefore make the current
        # rows at a given sequence belong to another branch.  The migration
        # stores the exact legacy branch only when needed (and stores the
        # captured projection as a base snapshot), so clearing the old blob
        # does not silently restore another conversation.
        materialized = await db.get(CoreCheckpointV2Materialized, checkpoint.id)
        if materialized is not None:
            await self._restore_materialized(
                db,
                session_id,
                materialized,
                event_seq=int(checkpoint.event_seq or 0),
            )
            return

        boundary_history = await db.get(CoreCheckpointV2SessionHistory, checkpoint.id)
        if boundary_history is not None:
            history = [dict(item) for item in list(boundary_history.history_json or []) if isinstance(item, dict)]
            await db.execute(delete(CoreHistoryEntry).where(CoreHistoryEntry.thread_id == session_id))
            for seq, message in enumerate(history, 1):
                db.add(CoreHistoryEntry(thread_id=session_id, seq=seq, message_json=message))
        else:
            history_rows = list((await db.execute(
                select(CoreHistoryEntry).where(
                    CoreHistoryEntry.thread_id == session_id,
                    CoreHistoryEntry.seq <= checkpoint.history_seq,
                ).order_by(CoreHistoryEntry.seq.asc())
            )).scalars())
            history = [dict(row.message_json or {}) for row in history_rows]
            await db.execute(delete(CoreHistoryEntry).where(
                CoreHistoryEntry.thread_id == session_id,
                CoreHistoryEntry.seq > checkpoint.history_seq,
            ))
        runtime = await db.get(CoreRuntimeSession, session_id)
        if runtime is not None:
            runtime.runtime_state_json = dict(checkpoint.runtime_state_json or {})
            runtime.history_json = history
            runtime.last_event_seq = checkpoint.event_seq
        await db.execute(delete(CoreAppEvent).where(
            CoreAppEvent.thread_id == session_id,
            CoreAppEvent.seq > checkpoint.event_seq,
        ))
        if session_id == _root_session_id(session_id):
            events = list((await db.execute(
                select(CoreAppEvent).where(
                    CoreAppEvent.thread_id == session_id,
                    CoreAppEvent.seq <= checkpoint.event_seq,
                ).order_by(CoreAppEvent.seq.asc())
            )).scalars())
            event_store = SqlAlchemyAppEventStore(CoreAppEvent)
            envelopes = [event_store._to_envelope(row) for row in events]
            await SqlAlchemyThreadSnapshotStore(
                CoreThreadSnapshot, item_model=CoreThreadSnapshotItem
            ).rebuild(db, session_id, envelopes)
            session_messages = await db.get(CoreCheckpointV2SessionMessages, checkpoint.id)
            if session_messages is not None:
                projection = await db.get(CoreThreadSnapshot, session_id)
                if projection is None:
                    projection = CoreThreadSnapshot(thread_id=session_id)
                    db.add(projection)
                state = dict(projection.snapshot_json or {})
                state["messages"] = copy.deepcopy(list(session_messages.messages_json or []))
                projection.snapshot_json = state
                projection.updated_at = datetime.now()

    async def _restore_materialized(
        self,
        db: Any,
        session_id: str,
        materialized: CoreCheckpointV2Materialized,
        *,
        event_seq: int,
    ) -> None:
        history = [dict(item) for item in list(materialized.history_json or []) if isinstance(item, dict)]

        # The history table is the runtime state's durable source after the
        # lazy migration.  Replace it, rather than only trimming by a global
        # watermark, because an old checkpoint can point at a different
        # branch or at an explicitly empty history.
        await db.execute(delete(CoreHistoryEntry).where(CoreHistoryEntry.thread_id == session_id))
        for seq, message in enumerate(history, 1):
            if isinstance(message.get("metadata"), dict):
                metadata = dict(message["metadata"])
                metadata["history_seq"] = seq
                message["metadata"] = metadata
            db.add(CoreHistoryEntry(thread_id=session_id, seq=seq, message_json=message))

        runtime = await db.get(CoreRuntimeSession, session_id)
        if materialized.runtime_present:
            payload = dict(materialized.runtime_json or {})
            if runtime is None:
                runtime = CoreRuntimeSession(thread_id=session_id)
                db.add(runtime)
            runtime.revision = max(
                int(runtime.revision or 0) + 1,
                int(payload.get("revision") or 0) + 1,
            )
            runtime.runtime_state_json = dict(payload.get("runtime_state_json") or {})
            runtime.history_json = history
            runtime.pending_approval_json = dict(payload.get("pending_approval_json") or {})
            runtime.last_event_seq = int(payload.get("last_event_seq") or 0)
            runtime.updated_at = datetime.now()
        elif runtime is not None:
            await db.delete(runtime)

        is_root_session = session_id == _root_session_id(session_id)
        if is_root_session and materialized.events_present:
            if materialized.events_json is None:
                # The current fact log was proven to be the same branch during
                # migration.  Keep its prefix and discard only later events.
                await db.execute(delete(CoreAppEvent).where(
                    CoreAppEvent.thread_id == session_id,
                    CoreAppEvent.seq > event_seq,
                ))
            else:
                await db.execute(delete(CoreAppEvent).where(CoreAppEvent.thread_id == session_id))
                for event_payload in list(materialized.events_json or []):
                    if isinstance(event_payload, dict):
                        db.add(_app_event_row(event_payload, thread_id=session_id))

        if not is_root_session:
            return
        projection_store = SqlAlchemyThreadSnapshotStore(
            CoreThreadSnapshot,
            item_model=CoreThreadSnapshotItem,
        )
        if materialized.projection_present and isinstance(materialized.projection_json, dict):
            await projection_store.write_full_projection(
                db,
                session_id,
                dict(materialized.projection_json),
            )
        else:
            projection = await db.get(CoreThreadSnapshot, session_id)
            if projection is not None:
                await db.delete(projection)
            await db.execute(
                delete(CoreThreadSnapshotItem).where(CoreThreadSnapshotItem.thread_id == session_id)
            )

    async def require_inactive(self, session_id: str) -> None:
        await _require_inactive_session(self.session_factory, session_id)

    async def fork(
        self,
        db: Any,
        *,
        source_session_id: str,
        new_session_id: str,
        payload: dict[str, Any],
        title: str,
        options: dict[str, Any],
    ) -> ForkConversationResult:
        if await db.get(CoreRuntimeSession, new_session_id) is not None:
            raise ValueError("Fork session already exists")
        if await db.get(CoreThreadSnapshot, new_session_id) is not None:
            raise ValueError("Fork session already exists")
        runtime_payload = payload.get("runtime")
        projection_payload = payload.get("projection")
        events_payload = payload.get("events")
        checkpoint_id = str(options.get("checkpoint_id") or "") if options else ""
        runtime = _fork_runtime_payload(
            runtime_payload if isinstance(runtime_payload, dict) else None,
            source_session_id=source_session_id,
            fork_session_id=new_session_id,
            checkpoint_id=checkpoint_id,
        )
        db.add(CoreRuntimeSession(
            thread_id=new_session_id,
            revision=1,
            runtime_state_json=runtime["runtime_state_json"],
            history_json=runtime["history_json"],
            pending_approval_json={},
            last_event_seq=runtime["last_event_seq"],
            updated_at=datetime.now(),
        ))
        projection = _fork_projection_payload(
            projection_payload if isinstance(projection_payload, dict) else None,
            source_session_id=source_session_id,
            fork_session_id=new_session_id,
            checkpoint_id=checkpoint_id,
            title=title,
        )
        # Split the forked full projection into item rows + metadata row.
        await SqlAlchemyThreadSnapshotStore(
            CoreThreadSnapshot, item_model=CoreThreadSnapshotItem
        ).write_full_projection(db, new_session_id, projection)
        # Write captured events to the new session's event stream so the
        # projector can rebuild the projection correctly instead of relying
        # on a frozen inherited snapshot.  Session-id fields (turn_id etc.)
        # are remapped from source to fork session.
        forked_events: list[dict[str, Any]] = []
        if isinstance(events_payload, list):
            for event_payload in events_payload:
                if isinstance(event_payload, dict):
                    remapped = _replace_session_id(
                        dict(event_payload), source_session_id, new_session_id
                    )
                    # event_id is a GLOBAL primary key — the source session's
                    # rows already own these ids, so regenerate them for the
                    # forked stream or the insert violates the PK constraint.
                    remapped.pop("event_id", None)
                    row = _app_event_row(remapped, thread_id=new_session_id)
                    db.add(row)
        await db.flush()
        return ForkConversationResult(
            conversation={
                "session_id": new_session_id,
                "runtime": runtime,
                "projection": projection,
                "events": [],
            }
        )


def register_checkpoint_operations(
    catalog: OperationCatalog,
    *,
    session_factory: async_sessionmaker,
    data_dir: str | Path,
    default_work_root: str | Path,
    conversation_backend: CheckpointConversationBackend | None = None,
    work_root_resolver: Callable[[str], Awaitable[str | Path]] | None = None,
) -> None:
    """Register the one public operation surface used by RPC and CLI."""

    storage_root = Path(data_dir).resolve() / "checkpoints"
    coordinators: dict[str, CoreCheckpointCoordinator] = {}

    def coordinator(work_root: str | Path) -> CoreCheckpointCoordinator:
        normalized = str(Path(work_root).resolve())
        existing = coordinators.get(normalized)
        if existing is not None:
            return existing
        created = CoreCheckpointCoordinator(
            work_root=work_root,
            session_factory=session_factory,
            storage_root=storage_root,
            conversation_backend=conversation_backend,
        )
        coordinators[normalized] = created
        return created

    async def session_work_root(session_id: str) -> str:
        if work_root_resolver is not None:
            return str(Path(await work_root_resolver(session_id)).resolve())
        return await _session_work_root(session_factory, session_id, default_work_root)

    async def checkpoint_create(request: OperationRequest) -> OperationResult:
        session_id = str(request.payload.get("session_id") or request.payload.get("thread_id") or "").strip()
        if not session_id:
            return _operation_error(request, "session_id is required")
        reason = str(request.payload.get("reason") or "manual").strip() or "manual"
        label = str(request.payload.get("label") or "").strip()
        turn_id = str(request.payload.get("turn_id") or f"manual:{uuid.uuid4().hex}").strip()
        actor_kind = str(request.payload.get("actor_kind") or "tool").strip() or "tool"
        try:
            work_root = await session_work_root(session_id)
            row = await coordinator(work_root).save(
                session_id=session_id,
                turn_id=turn_id,
                actor_kind=actor_kind,
                reason=reason,
                label=label,
            )
        except (LookupError, ValueError, OSError) as exc:
            return _operation_error(request, str(exc))
        return OperationResult(name=request.name, payload={"checkpoint": _checkpoint_payload(row)})

    async def checkpoints_graph(request: OperationRequest) -> OperationResult:
        session_id = str(request.payload.get("session_id") or request.payload.get("thread_id") or "").strip()
        if not session_id:
            return _operation_error(request, "session_id is required")
        try:
            graph = await coordinator(default_work_root).graph(session_id)
        except (LookupError, ValueError, OSError) as exc:
            return _operation_error(request, str(exc))
        return OperationResult(name=request.name, payload=_graph_payload(graph))

    async def checkpoints_list(request: OperationRequest) -> OperationResult:
        session_id = str(request.payload.get("session_id") or request.payload.get("thread_id") or "").strip()
        if not session_id:
            return _operation_error(request, "session_id is required")
        try:
            rows = await coordinator(default_work_root).list(session_id)
        except (LookupError, ValueError, OSError) as exc:
            return _operation_error(request, str(exc))
        return OperationResult(
            name=request.name,
            payload={"checkpoints": [_checkpoint_payload(row) for row in rows]},
        )

    async def restore_checkpoint(request: OperationRequest) -> OperationResult:
        session_id = str(request.payload.get("session_id") or request.payload.get("thread_id") or "").strip()
        checkpoint_id = str(request.payload.get("checkpoint_id") or "").strip()
        if not session_id or not checkpoint_id:
            return _operation_error(request, "session_id and checkpoint_id are required")
        try:
            scope = "all" if request.name == "session.rollback" else _normalize_restore_scope(
                request.payload.get("scope") or "all"
            )
            schema_coordinator = coordinator(default_work_root)
            await schema_coordinator._ensure_schema()
            checkpoint = await _checkpoint_for_session(session_factory, session_id, checkpoint_id)
            result = await coordinator(checkpoint.work_root).load(
                checkpoint_id,
                scope=scope,
                requesting_session_id=session_id,
            )
        except (LookupError, ValueError, OSError) as exc:
            return _operation_error(request, str(exc))
        return OperationResult(name=request.name, payload=_restore_payload(result))

    async def rollback_to_turn(request: OperationRequest, *, session_id: str, turn_id: str) -> OperationResult:
        work_root = await session_work_root(session_id)
        turn_backend = CoreCheckpointConversationBackend(session_factory)
        try:
            await turn_backend.require_inactive(session_id)
            checkpoint_id = await _checkpoint_id_at_turn_boundary(
                session_factory,
                session_id=session_id,
                turn_id=turn_id,
                conversation_backend=turn_backend,
            )
            if checkpoint_id:
                result = await coordinator(work_root).load(
                    checkpoint_id,
                    scope="all",
                    requesting_session_id=session_id,
                )
                return OperationResult(name=request.name, payload={
                    "mode": "checkpoint",
                    "turn_id": turn_id,
                    "checkpoint_id": checkpoint_id,
                    "operation_id": result.operation_id,
                    "restored": {
                        "conversation": True,
                        "runtime": True,
                        "workspace": True,
                        "external_effects": False,
                    },
                    "restored_paths": list(result.restored_paths),
                })
            boundary_seq = await coordinator(work_root).write_coordinator.run(
                lambda db: turn_backend.rollback_conversation_through_turn(
                    db,
                    session_id=session_id,
                    turn_id=turn_id,
                )
            )
        except (LookupError, ValueError, OSError) as exc:
            return _operation_error(request, str(exc))
        return OperationResult(name=request.name, payload={
            "mode": "conversation_only",
            "turn_id": turn_id,
            "event_seq": boundary_seq,
            "restored": {
                "conversation": True,
                "runtime": False,
                "workspace": False,
                "external_effects": False,
            },
        })

    async def fork_session(request: OperationRequest) -> OperationResult:
        session_id = str(request.payload.get("session_id") or request.payload.get("thread_id") or "").strip()
        checkpoint_id = str(request.payload.get("checkpoint_id") or "").strip()
        turn_id = str(request.payload.get("turn_id") or "").strip()
        new_session_id = str(request.payload.get("new_session_id") or "").strip() or None
        title = str(request.payload.get("title") or "").strip()
        if not session_id:
            return _operation_error(request, "session_id is required")
        try:
            if turn_id:
                work_root = await session_work_root(session_id)
                turn_backend = CoreCheckpointConversationBackend(session_factory)
                await turn_backend.require_inactive(session_id)
                fork_session_id = str(new_session_id or uuid.uuid4().hex).strip()
                if not fork_session_id or _root_session_id(fork_session_id) != fork_session_id:
                    return _operation_error(request, "new_session_id must identify a main session")

                async def write_turn_fork(db: Any) -> tuple[ForkConversationResult, int]:
                    payload, boundary_seq = await turn_backend.conversation_payload_through_turn(
                        db,
                        session_id=session_id,
                        turn_id=turn_id,
                    )
                    forked = await turn_backend.fork(
                        db,
                        source_session_id=session_id,
                        new_session_id=fork_session_id,
                        payload=payload,
                        title=title,
                        options={"turn_id": turn_id, "mode": "conversation_only"},
                    )
                    return forked, boundary_seq

                forked, boundary_seq = await coordinator(work_root).write_coordinator.run(write_turn_fork)
                return OperationResult(name=request.name, payload={
                    "session_id": fork_session_id,
                    "session": forked.session_payload,
                    "mode": "conversation_only",
                    "turn_id": turn_id,
                    "event_seq": boundary_seq,
                    "restored": {
                        "conversation": True,
                        "runtime": False,
                        "workspace": False,
                        "external_effects": False,
                    },
                })
            if checkpoint_id:
                schema_coordinator = coordinator(default_work_root)
                await schema_coordinator._ensure_schema()
                checkpoint = await _checkpoint_for_session(session_factory, session_id, checkpoint_id)
                work_root = checkpoint.work_root
            else:
                work_root = await session_work_root(session_id)
                checkpoint = await coordinator(work_root).save(
                    session_id=session_id,
                    turn_id=f"fork:{uuid.uuid4().hex}",
                    actor_kind="fork",
                    reason="before_session_fork",
                    label="分叉前自动存档",
                )
                checkpoint_id = checkpoint.id
            row = await coordinator(work_root).fork(
                checkpoint_id,
                new_session_id=new_session_id,
                title=title,
                options=dict(request.payload),
            )
        except (LookupError, ValueError, OSError) as exc:
            return _operation_error(request, str(exc))
        return OperationResult(name=request.name, payload={
            "session_id": row.session_id,
            "checkpoint": _checkpoint_payload(row),
            **({"session": row.session_payload} if row.session_payload else {}),
        })

    async def rollback_session(request: OperationRequest) -> OperationResult:
        session_id = str(request.payload.get("session_id") or request.payload.get("thread_id") or "").strip()
        turn_id = str(request.payload.get("turn_id") or "").strip()
        if turn_id:
            if not session_id:
                return _operation_error(request, "session_id is required")
            return await rollback_to_turn(request, session_id=session_id, turn_id=turn_id)
        return await restore_checkpoint(request)

    catalog.register("session.checkpoints.create", checkpoint_create)
    catalog.register("session.checkpoints.graph", checkpoints_graph)
    catalog.register("session.checkpoints.list", checkpoints_list)
    catalog.register("session.checkpoints.restore", restore_checkpoint)
    catalog.register("session.rollback", rollback_session)
    catalog.register("session.fork", fork_session)


def _default_storage_root(session_factory: async_sessionmaker) -> Path:
    database_path = _database_path(session_factory)
    if database_path is not None:
        return database_path.parent / "core-checkpoints"
    bind = getattr(session_factory, "kw", {}).get("bind")
    return Path(tempfile.gettempdir()) / f"lamtools-core-checkpoints-{id(bind)}"


def _database_path(session_factory: async_sessionmaker) -> Path | None:
    bind = getattr(session_factory, "kw", {}).get("bind")
    database = getattr(getattr(bind, "url", None), "database", None)
    if not database or database == ":memory:":
        return None
    return Path(database).resolve()


def _root_session_id(session_id: str) -> str:
    return str(session_id).split(":sub:", 1)[0]


def _normalize_restore_scope(value: object) -> RestoreScope:
    scope = str(value or "all").strip().lower()
    if scope not in _RESTORE_SCOPES:
        raise ValueError("scope must be one of: conversation, workspace, all")
    return cast(RestoreScope, scope)


def _restore_label(scope: RestoreScope) -> str:
    return {
        "conversation": "仅回退对话",
        "workspace": "仅回退文件",
        "all": "全部回退",
    }[scope]


async def _require_inactive_session(session_factory: async_sessionmaker, session_id: str) -> None:
    async with session_factory() as db:
        runtime = await db.get(CoreRuntimeSession, session_id)
        projection = await db.get(CoreThreadSnapshot, session_id)
    runtime_status = str((runtime.runtime_state_json or {}).get("status") or "") if runtime is not None else ""
    projection_status = str((projection.snapshot_json or {}).get("status") or "") if projection is not None else ""
    if runtime_status in {"running", "waiting"} or projection_status in {"running", "waiting"}:
        raise ValueError("Session has an active turn; cancel or finish it before rollback")


async def _session_work_root(
    session_factory: async_sessionmaker,
    session_id: str,
    default_work_root: str | Path,
) -> str:
    root_session_id = _root_session_id(session_id)
    async with session_factory() as db:
        snapshot = await db.get(CoreThreadSnapshot, root_session_id)
    if snapshot is None:
        return str(Path(default_work_root).resolve())
    state = dict(snapshot.snapshot_json or {})
    session = state.get("session") if isinstance(state.get("session"), dict) else {}
    metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    return str(Path(str(metadata.get("work_root") or default_work_root)).resolve())


async def _checkpoint_for_session(
    session_factory: async_sessionmaker,
    session_id: str,
    checkpoint_id: str,
) -> CoreCheckpoint:
    root_session_id = _root_session_id(session_id)
    async with session_factory() as db:
        row = await db.get(CoreCheckpoint, checkpoint_id)
        if row is None:
            raise LookupError("Checkpoint not found")
        if row.root_session_id != root_session_id:
            raise ValueError("Checkpoint does not belong to this session")
        db.expunge(row)
        return row


def _checkpoint_payload(row: CheckpointRef) -> dict[str, Any]:
    return {
        "id": row.id,
        "graph_id": row.graph_id,
        "root_session_id": row.root_session_id,
        "session_id": row.session_id,
        "parent_checkpoint_id": row.parent_checkpoint_id,
        "edge_kind": row.edge_kind,
        "turn_id": row.turn_id,
        "actor_kind": row.actor_kind,
        "reason": row.reason,
        "label": row.label,
        "work_root": row.work_root,
        "manifest_hash": row.manifest_hash,
        "status": "ready",
        "created_at": row.created_at.isoformat(),
    }


def _restore_payload(result: RestoreResult) -> dict[str, Any]:
    return {
        "operation_id": result.operation_id,
        "checkpoint_id": result.checkpoint_id,
        "undo_checkpoint_id": result.undo_checkpoint_id,
        "derived_checkpoint_id": result.derived_checkpoint_id,
        "scope": result.scope,
        "status": result.status,
        "restored_paths": list(result.restored_paths),
    }


def _operation_error(request: OperationRequest, message: str) -> OperationResult:
    return OperationResult(name=request.name, status="error", payload={"error": message})


def _checkpoint_ref(row: CoreCheckpoint) -> CheckpointRef:
    return CheckpointRef(
        id=row.id,
        graph_id=str(row.graph_id or row.root_session_id),
        root_session_id=row.root_session_id,
        session_id=row.session_id,
        parent_checkpoint_id=str(row.parent_checkpoint_id or ""),
        edge_kind=str(row.edge_kind or "checkpoint"),
        turn_id=row.turn_id,
        actor_kind=row.actor_kind,
        reason=str(row.reason or ""),
        label=str(row.label or ""),
        work_root=row.work_root,
        manifest_hash=row.manifest_hash,
        created_at=row.created_at,
    )


def _graph_payload(graph: CheckpointGraph) -> dict[str, Any]:
    return {
        "graph_id": graph.graph_id,
        "nodes": [_checkpoint_payload(row) for row in graph.nodes],
        "edges": [
            {
                "parent_checkpoint_id": edge.parent_checkpoint_id,
                "checkpoint_id": edge.checkpoint_id,
                "kind": edge.kind,
            }
            for edge in graph.edges
        ],
        "heads": dict(graph.heads),
    }


def _fork_runtime_payload(
    payload: dict[str, Any] | None,
    *,
    source_session_id: str,
    fork_session_id: str,
    checkpoint_id: str,
) -> dict[str, Any]:
    source = copy.deepcopy(payload or {})
    state = _replace_session_id(
        dict(source.get("runtime_state_json") or {}),
        source_session_id,
        fork_session_id,
    )
    state["session_id"] = fork_session_id
    state["run_id"] = ""
    state["status"] = "idle"
    metadata = dict(state.get("metadata") or {})
    metadata["forked_from"] = {
        "session_id": source_session_id,
        "checkpoint_id": checkpoint_id,
    }
    state["metadata"] = metadata
    history = _replace_session_id(
        list(source.get("history_json") or []),
        source_session_id,
        fork_session_id,
    )
    return {
        "revision": 1,
        "runtime_state_json": state,
        "history_json": history,
        "pending_approval_json": {},
        "last_event_seq": int(source.get("last_event_seq") or 0),
    }


def _fork_projection_payload(
    payload: dict[str, Any] | None,
    *,
    source_session_id: str,
    fork_session_id: str,
    checkpoint_id: str,
    title: str,
) -> dict[str, Any]:
    source_state = dict((payload or {}).get("snapshot_json") or {})
    if source_state:
        state = _replace_session_id(source_state, source_session_id, fork_session_id)
    else:
        state = CoreAppSnapshotProjector().empty(fork_session_id)
    state["thread_id"] = fork_session_id
    state["status"] = "idle"
    # Keep the original snapshot_seq and seen_event_ids — the checkpoint
    # capture already filtered them to the correct range (the excluded turn
    # is removed).  Resetting them to 0 / [] tells the projector that no
    # events have been applied, which causes items to be projected twice
    # and leads to duplicate / misordered messages in the forked session.
    session = dict(state.get("session") or {})
    source_title = str(session.get("title") or source_session_id)
    session["title"] = str(title or f"{source_title} fork")
    metadata = dict(session.get("metadata") or {})
    metadata.update({
        "forked_from_session_id": source_session_id,
        "forked_from_checkpoint_id": checkpoint_id,
    })
    session["metadata"] = metadata
    state["session"] = session
    return {"snapshot_seq": int(payload.get("snapshot_seq") or 0) if payload else 0, "snapshot_json": state}


def _replace_session_id(value: Any, source_session_id: str, fork_session_id: str) -> Any:
    if isinstance(value, dict):
        # Remap keys too — item ids live in dict keys (items / turns maps) as
        # well as in list values (item_order), and leaving keys stale breaks
        # the frontend lookup that joins the two.
        return {
            _replace_session_id(key, source_session_id, fork_session_id): _replace_session_id(
                item, source_session_id, fork_session_id
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_session_id(item, source_session_id, fork_session_id) for item in value]
    if isinstance(value, str):
        if value == source_session_id:
            return fork_session_id
        if value.startswith(f"{source_session_id}:"):
            return f"{fork_session_id}{value[len(source_session_id):]}"
    return value


def _runtime_payload(row: CoreRuntimeSession | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "revision": int(row.revision or 0),
        "runtime_state_json": dict(row.runtime_state_json or {}),
        "history_json": list(row.history_json or []),
        "pending_approval_json": dict(row.pending_approval_json or {}),
        "last_event_seq": int(row.last_event_seq or 0),
    }


def _conversation_history_from_events(events: list[Any]) -> list[dict[str, Any]]:
    """Reconstruct the model-visible transcript from durable message events.

    Tool/runtime state is deliberately excluded: this is the safe fallback
    used when there is no checkpoint capable of restoring those side effects.
    Later updates to an item replace its earlier event while retaining its
    original position in the transcript.
    """
    messages: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for event in events:
        if str(getattr(event, "method", "")) != "core/runItem":
            continue
        run_item = getattr(event, "payload", None)
        if not isinstance(run_item, dict) or str(run_item.get("kind") or "") != "message":
            continue
        payload = run_item.get("payload")
        if not isinstance(payload, dict):
            continue
        role = str(payload.get("role") or "").strip()
        content = payload.get("content")
        if role not in {"user", "assistant", "system"} or not isinstance(content, str):
            continue
        item_id = str(getattr(event, "item_id", "") or run_item.get("item_id") or getattr(event, "event_id", ""))
        if not item_id:
            continue
        if item_id not in messages:
            order.append(item_id)
        message: dict[str, Any] = {"role": role, "content": content}
        if isinstance(payload.get("name"), str) and payload["name"]:
            message["name"] = payload["name"]
        messages[item_id] = message
    return [messages[item_id] for item_id in order]


def _conversation_runtime_payload(
    runtime: CoreRuntimeSession | None,
    *,
    session_id: str,
    history: list[dict[str, Any]],
    boundary_seq: int,
    turn_id: str,
) -> dict[str, Any]:
    """Return an idle runtime shell without claiming runtime restoration."""
    source_state = dict((runtime.runtime_state_json if runtime is not None else {}) or {})
    source_metadata = dict(source_state.get("metadata") or {})
    # These values describe an in-flight or already-completed execution, not
    # reusable conversation state.  Keeping them would falsely revive a tool
    # call, approval, or last-turn bookkeeping after a fallback rollback.
    for key in (
        "turn_id",
        "original_user_message",
        "pending_approval",
        "pending_waiting_request",
        "kernel_steps",
        "tool_progress",
        "failure_diagnosis",
    ):
        source_metadata.pop(key, None)
    source_metadata["conversation_boundary"] = {
        "turn_id": turn_id,
        "mode": "conversation_only",
    }
    return {
        "revision": max(int(getattr(runtime, "revision", 0) or 0) + 1, 1),
        "runtime_state_json": {
            "session_id": session_id,
            "run_id": "",
            "status": "idle",
            "position": str(source_state.get("position") or "idle"),
            "loop_state": "idle",
            "turn_count": int(source_state.get("turn_count") or 0),
            "metadata": source_metadata,
        },
        "history_json": copy.deepcopy(history),
        "pending_approval_json": {},
        "last_event_seq": boundary_seq,
    }


async def _checkpoint_id_at_turn_boundary(
    session_factory: async_sessionmaker,
    *,
    session_id: str,
    turn_id: str,
    conversation_backend: CoreCheckpointConversationBackend,
) -> str:
    """Return a checkpoint only when it represents this exact event prefix.

    Automatic checkpoints are taken *before* a user turn, so matching on
    ``turn_id`` alone is incorrect and would drop the turn the user clicked.
    The event sequence makes the full-recovery path safe to select.
    """
    async with session_factory() as db:
        _, boundary_seq = await conversation_backend.conversation_payload_through_turn(
            db,
            session_id=session_id,
            turn_id=turn_id,
        )
        row = (await db.execute(
            select(CoreCheckpoint.id)
            .join(CoreCheckpointV2, CoreCheckpointV2.id == CoreCheckpoint.id)
            .where(
                CoreCheckpoint.session_id == session_id,
                CoreCheckpoint.status == "ready",
                CoreCheckpointV2.status == "ready",
                CoreCheckpointV2.event_seq == boundary_seq,
            )
            .order_by(CoreCheckpoint.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
    return str(row or "")


def _projection_payload(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(state, dict):
        return None
    return {
        "snapshot_seq": int(state.get("snapshot_seq") or 0),
        "snapshot_json": dict(state),
    }


def _projection_payload_without_turn(
    state: dict[str, Any] | None,
    *,
    excluded_turn_id: str,
    kept_events: list[Any],
) -> dict[str, Any] | None:
    payload = _projection_payload(state)
    if payload is None or not excluded_turn_id:
        return payload
    snapshot = copy.deepcopy(payload.get("snapshot_json") or {})
    CoreAppSnapshotProjector().remove_turns(snapshot, {excluded_turn_id})
    kept_event_ids = {str(event.event_id) for event in kept_events}
    snapshot["seen_event_ids"] = [
        event_id for event_id in list(snapshot.get("seen_event_ids") or []) if str(event_id) in kept_event_ids
    ]
    snapshot_seq = max((int(event.seq or 0) for event in kept_events), default=0)
    snapshot["snapshot_seq"] = snapshot_seq
    core = snapshot.get("core")
    if isinstance(core, dict):
        core["seen_event_ids"] = [
            event_id for event_id in list(core.get("seen_event_ids") or []) if str(event_id) in kept_event_ids
        ]
        core["snapshot_seq"] = snapshot_seq
    return {
        "snapshot_seq": snapshot_seq,
        "snapshot_json": snapshot,
    }


def _app_event_row(payload: dict[str, Any], *, thread_id: str) -> CoreAppEvent:
    created_at_value = payload.get("created_at")
    try:
        created_at = datetime.fromisoformat(str(created_at_value)) if created_at_value else datetime.now()
    except ValueError:
        created_at = datetime.now()
    return CoreAppEvent(
        event_id=str(payload.get("event_id") or uuid.uuid4().hex[:16]),
        thread_id=thread_id,
        seq=int(payload.get("seq") or 0),
        turn_id=str(payload.get("turn_id") or "") or None,
        item_id=str(payload.get("item_id") or "") or None,
        parent_item_id=str(payload.get("parent_item_id") or "") or None,
        client_message_id=str(payload.get("client_message_id") or "") or None,
        method=str(payload.get("method") or ""),
        payload_json=dict(payload.get("payload") or {}),
        created_at=created_at,
    )


def _safe_workspace_path(work_root: Path, relative: str) -> Path:
    candidate = (work_root / relative).resolve()
    if not _is_within(candidate, work_root):
        raise ValueError(f"Checkpoint path escapes workspace: {relative}")
    return candidate


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _remove_empty_directories(work_root: Path, storage_root: Path, roots: Iterable[Path]) -> None:
    """Remove directories left empty by a restore, walking only *upward*
    from each restored file's parent directory.

    Never scans the workspace: on a huge work_root (e.g. a game-save
    directory) a full walk would stall the app, and the rollback contract is
    to touch only the files it restored.
    """
    work_root = work_root.resolve()
    storage_root = storage_root.resolve()
    seen: set[Path] = set()
    for root in roots:
        cursor = Path(root).resolve()
        while _is_within(cursor, work_root) and cursor != work_root and cursor not in seen:
            seen.add(cursor)
            if cursor.name in _SKIPPED_DIRECTORIES or _is_within(cursor, storage_root):
                break
            try:
                cursor.rmdir()
            except OSError:
                break  # not empty (or locked) — stop walking up
            cursor = cursor.parent


__all__ = [
    "CheckpointEdge",
    "CheckpointGraph",
    "CheckpointRef",
    "CheckpointConversationBackend",
    "CHECKPOINT_OPERATION_NAMES",
    "CoreCheckpointCoordinator",
    "CoreCheckpointConversationBackend",
    "ForkConversationResult",
    "RestoreResult",
    "TurnCheckpointCoordinator",
    "register_checkpoint_operations",
]
