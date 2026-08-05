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
from collections.abc import Awaitable, Callable
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

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from lamtools_core.app.core_db import (
    CoreAppEvent,
    CoreCheckpoint,
    CoreCheckpointBlob,
    CoreDbBase,
    CoreRestoreOperation,
    CoreRuntimeSession,
    CoreThreadSnapshot,
    CoreWorkspaceManifest,
)
from lamtools_core.app.event_store import SqlAlchemyAppEventStore
from lamtools_core.app.snapshot_store import CoreAppSnapshotProjector
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
CHECKPOINT_OPERATION_NAMES = (
    "session.checkpoints.create",
    "session.checkpoints.graph",
    "session.checkpoints.list",
    "session.checkpoints.restore",
    "session.rollback",
    "session.rollback.undo",
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
        to the latest checkpoint's workspace manifest.
        """
        await self._ensure_schema()
        file_path = Path(path).resolve()
        if not file_path.is_file():
            return
        relative = str(file_path.relative_to(self.work_root).as_posix()) if _is_within(file_path, self.work_root) else file_path.as_posix()
        data = file_path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
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
                    parent_checkpoint_id=target.id,
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

    async def undo(self, operation_id: str) -> RestoreResult:
        await self._ensure_schema()
        async with self.session_factory() as db:
            operation = await db.get(CoreRestoreOperation, operation_id)
            if operation is None:
                raise LookupError("Restore operation not found")
            if operation.status != "committed":
                raise ValueError("Only a committed restore can be undone")
            undo_checkpoint_id = operation.undo_checkpoint_id
            scope = _normalize_restore_scope(operation.scope)
        return await self.load(undo_checkpoint_id, scope=scope)

    async def undo_restore(self, operation_id: str) -> RestoreResult:
        return await self.undo(operation_id)

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
            conversation = copy.deepcopy(dict(target.conversation_json or {}))
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
                    conversation_json=forked.conversation,
                    status="ready",
                    created_at=now,
                )
                db.add(row)
                await db.flush()
                return replace(_checkpoint_ref(row), session_payload=dict(forked.session_payload))

            return await self.write_coordinator.run(write)

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
        manifest_hash, entries, blobs = self._capture_workspace()
        root_session_id = _root_session_id(session_id)
        conversation = await self.conversation_backend.capture(session_id, exclude_turn_id=turn_id)
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
                conversation_json=conversation,
                status="ready",
                created_at=created_at,
            )
            db.add(row)
            await db.flush()
            return _checkpoint_ref(row)

        return await self.write_coordinator.run(write)

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

    def _capture_workspace(self) -> tuple[str, dict[str, Any], list[tuple[str, int, str]]]:
        entries: dict[str, Any] = {}
        blobs: list[tuple[str, int, str]] = []
        blob_root = self.storage_root / "blobs"
        blob_root.mkdir(parents=True, exist_ok=True)
        if not self.work_root.exists():
            raise FileNotFoundError(f"Workspace does not exist: {self.work_root}")

        for path in self._workspace_files():
            relative = path.relative_to(self.work_root).as_posix()
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
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
            mode = stat.S_IMODE(path.stat().st_mode)
            entries[relative] = {"hash": digest, "size": len(data), "mode": mode}
            blobs.append((digest, len(data), str(blob_path)))

        manifest_bytes = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(manifest_bytes).hexdigest(), entries, blobs

    def _workspace_files(self) -> list[Path]:
        files: list[Path] = []
        for root, directories, names in os.walk(self.work_root, topdown=True, followlinks=False):
            root_path = Path(root)
            directories[:] = [
                name for name in directories
                if name not in _SKIPPED_DIRECTORIES
                and not self._is_internal_path((root_path / name).resolve())
            ]
            for name in names:
                path = root_path / name
                if path.is_file() and not path.is_symlink() and not self._is_internal_path(path.resolve()):
                    files.append(path)
        files.sort(key=lambda item: os.path.normcase(item.relative_to(self.work_root).as_posix()))
        return files

    def _is_internal_path(self, path: Path) -> bool:
        if _is_within(path, self.storage_root):
            return True
        if self.database_path is None:
            return False
        database_names = {
            self.database_path.name,
            f"{self.database_path.name}-wal",
            f"{self.database_path.name}-shm",
            f"{self.database_path.name}-journal",
        }
        return path.parent == self.database_path.parent and path.name in database_names

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
        current_hash, current, _ = await asyncio.to_thread(self._capture_workspace)
        if current_hash == manifest_hash:
            return []
        changed = sorted(set(target) | set(current))
        stage_root = Path(tempfile.mkdtemp(prefix="restore-", dir=self.storage_root))
        applied: list[str] = []
        try:
            for relative in changed:
                target_entry = target.get(relative)
                current_entry = current.get(relative)
                if target_entry == current_entry:
                    continue
                destination = _safe_workspace_path(self.work_root, relative)
                if target_entry is None:
                    if destination.exists() and destination.is_file():
                        destination.unlink()
                        applied.append(relative)
                    continue
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
            _remove_empty_directories(self.work_root, self.storage_root)
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
            snapshot = await db.get(CoreThreadSnapshot, session_id) if is_root_session else None
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
            if projection is None:
                projection = CoreThreadSnapshot(thread_id=session_id)
                db.add(projection)
            projection.snapshot_seq = int(projection_payload.get("snapshot_seq") or 0)
            projection.snapshot_json = dict(projection_payload.get("snapshot_json") or {})
            projection.updated_at = datetime.now()
        elif projection is not None:
            await db.delete(projection)

        if is_root_session and isinstance(events_payload, list):
            await db.execute(delete(CoreAppEvent).where(CoreAppEvent.thread_id == session_id))
            for event_payload in events_payload:
                if isinstance(event_payload, dict):
                    db.add(_app_event_row(event_payload, thread_id=session_id))

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
            last_event_seq=0,
            updated_at=datetime.now(),
        ))
        projection = _fork_projection_payload(
            projection_payload if isinstance(projection_payload, dict) else None,
            source_session_id=source_session_id,
            fork_session_id=new_session_id,
            checkpoint_id=checkpoint_id,
            title=title,
        )
        db.add(CoreThreadSnapshot(
            thread_id=new_session_id,
            snapshot_seq=0,
            snapshot_json=projection["snapshot_json"],
            updated_at=datetime.now(),
        ))
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

    async def fork_session(request: OperationRequest) -> OperationResult:
        session_id = str(request.payload.get("session_id") or request.payload.get("thread_id") or "").strip()
        checkpoint_id = str(request.payload.get("checkpoint_id") or "").strip()
        new_session_id = str(request.payload.get("new_session_id") or "").strip() or None
        title = str(request.payload.get("title") or "").strip()
        if not session_id:
            return _operation_error(request, "session_id is required")
        try:
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

    async def rollback_undo(request: OperationRequest) -> OperationResult:
        session_id = str(request.payload.get("session_id") or request.payload.get("thread_id") or "").strip()
        operation_id = str(request.payload.get("operation_id") or "").strip()
        if not session_id or not operation_id:
            return _operation_error(request, "session_id and operation_id are required")
        try:
            schema_coordinator = coordinator(default_work_root)
            await schema_coordinator._ensure_schema()
            work_root = await _undo_work_root(session_factory, session_id, operation_id)
            result = await coordinator(work_root).undo(operation_id)
        except (LookupError, ValueError, OSError) as exc:
            return _operation_error(request, str(exc))
        return OperationResult(name=request.name, payload=_restore_payload(result))

    catalog.register("session.checkpoints.create", checkpoint_create)
    catalog.register("session.checkpoints.graph", checkpoints_graph)
    catalog.register("session.checkpoints.list", checkpoints_list)
    catalog.register("session.checkpoints.restore", restore_checkpoint)
    catalog.register("session.rollback", restore_checkpoint)
    catalog.register("session.rollback.undo", rollback_undo)
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


async def _undo_work_root(
    session_factory: async_sessionmaker,
    session_id: str,
    operation_id: str,
) -> str:
    root_session_id = _root_session_id(session_id)
    async with session_factory() as db:
        operation = await db.get(CoreRestoreOperation, operation_id)
        if operation is None:
            raise LookupError("Restore operation not found")
        if operation.root_session_id != root_session_id:
            raise ValueError("Restore operation does not belong to this session")
        if operation.status != "committed":
            raise ValueError("Only a committed restore can be undone")
        checkpoint = await db.get(CoreCheckpoint, operation.undo_checkpoint_id)
        if checkpoint is None:
            raise LookupError("Undo checkpoint not found")
        return checkpoint.work_root


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
        "last_event_seq": 0,
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
    state["snapshot_seq"] = 0
    state["seen_event_ids"] = []
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
    core = state.get("core")
    if isinstance(core, dict):
        core["snapshot_seq"] = 0
        core["seen_event_ids"] = []
    return {"snapshot_seq": 0, "snapshot_json": state}


def _replace_session_id(value: Any, source_session_id: str, fork_session_id: str) -> Any:
    if isinstance(value, dict):
        return {
            key: _replace_session_id(item, source_session_id, fork_session_id)
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


def _projection_payload(row: CoreThreadSnapshot | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "snapshot_seq": int(row.snapshot_seq or 0),
        "snapshot_json": dict(row.snapshot_json or {}),
    }


def _projection_payload_without_turn(
    row: CoreThreadSnapshot | None,
    *,
    excluded_turn_id: str,
    kept_events: list[Any],
) -> dict[str, Any] | None:
    payload = _projection_payload(row)
    if payload is None or not excluded_turn_id:
        return payload
    state = copy.deepcopy(payload.get("snapshot_json") or {})
    CoreAppSnapshotProjector().remove_turns(state, {excluded_turn_id})
    kept_event_ids = {str(event.event_id) for event in kept_events}
    state["seen_event_ids"] = [
        event_id for event_id in list(state.get("seen_event_ids") or []) if str(event_id) in kept_event_ids
    ]
    snapshot_seq = max((int(event.seq or 0) for event in kept_events), default=0)
    state["snapshot_seq"] = snapshot_seq
    core = state.get("core")
    if isinstance(core, dict):
        core["seen_event_ids"] = [
            event_id for event_id in list(core.get("seen_event_ids") or []) if str(event_id) in kept_event_ids
        ]
        core["snapshot_seq"] = snapshot_seq
    return {
        "snapshot_seq": snapshot_seq,
        "snapshot_json": state,
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


def _remove_empty_directories(work_root: Path, storage_root: Path) -> None:
    directories = [path for path in work_root.rglob("*") if path.is_dir()]
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        if path.name in _SKIPPED_DIRECTORIES or _is_within(path.resolve(), storage_root):
            continue
        try:
            path.rmdir()
        except OSError:
            pass


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
