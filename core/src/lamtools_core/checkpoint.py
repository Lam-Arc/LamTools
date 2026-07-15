"""Task-scoped conversation and workspace checkpoints.

The public coordinator deliberately hides storage details.  Callers create a
checkpoint before a main- or sub-agent turn, then restore or undo through the
same interface.  Workspace content is stored outside the workspace in a small
content-addressed store, so this module never commits, resets, or touches a
user's Git index.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any, Literal, Protocol
import uuid
from weakref import WeakValueDictionary

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from lamtools_core.app.core_db import (
    CoreCheckpoint,
    CoreCheckpointBlob,
    CoreRestoreOperation,
    CoreRuntimeSession,
    CoreThreadSnapshot,
    CoreWorkspaceManifest,
)
from lamtools_core.app.sqlite_write import SQLiteWriteCoordinator
from lamtools_core.app.operation_catalog import OperationCatalog, OperationRequest, OperationResult


ActorKind = Literal["main", "sub_agent", "restore"]


@dataclass(frozen=True)
class CheckpointRef:
    id: str
    session_id: str
    turn_id: str
    actor_kind: str
    work_root: str
    manifest_hash: str
    created_at: datetime


@dataclass(frozen=True)
class RestoreResult:
    operation_id: str
    checkpoint_id: str
    undo_checkpoint_id: str
    status: str
    restored_paths: tuple[str, ...]


class TurnCheckpointCoordinator(Protocol):
    async def begin_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        actor_kind: str = "main",
    ) -> CheckpointRef: ...


_WORKSPACE_LOCKS: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_SKIPPED_DIRECTORIES = {".git", ".hg", ".svn", "node_modules", "__pycache__"}
CHECKPOINT_OPERATION_NAMES = (
    "session.checkpoints.list",
    "session.rollback",
    "session.rollback.undo",
)


class CoreCheckpointCoordinator:
    """Deep module that owns checkpoint capture, restore, and restore undo."""

    def __init__(
        self,
        work_root: str | Path,
        session_factory: async_sessionmaker,
        write_coordinator: SQLiteWriteCoordinator | None = None,
        storage_root: str | Path | None = None,
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
        async with self._workspace_lock:
            return await self._capture(
                session_id=session_id,
                turn_id=turn_id,
                actor_kind=actor_kind,
            )

    async def list(self, session_id: str) -> list[CheckpointRef]:
        root_session_id = _root_session_id(session_id)
        async with self.session_factory() as db:
            rows = list((await db.execute(
                select(CoreCheckpoint)
                .where(CoreCheckpoint.root_session_id == root_session_id)
                .where(CoreCheckpoint.status == "ready")
                .order_by(CoreCheckpoint.created_at.desc())
            )).scalars())
        return [_checkpoint_ref(row) for row in rows]

    async def restore(self, checkpoint_id: str) -> RestoreResult:
        async with self._workspace_lock:
            target = await self._checkpoint(checkpoint_id)
            if Path(target.work_root).resolve() != self.work_root:
                raise ValueError("Checkpoint belongs to a different workspace")
            undo = await self._capture(
                session_id=target.session_id,
                turn_id=f"restore:{checkpoint_id}",
                actor_kind="restore",
            )
            operation_id = uuid.uuid4().hex
            await self._create_operation(operation_id, target, undo.id)
            undo_row = await self._checkpoint(undo.id)
            restored_paths: tuple[str, ...] = ()
            try:
                restored_paths = tuple(await self._apply_manifest(target.manifest_hash))
                await self._restore_conversation(target, operation_id)
            except BaseException as exc:
                try:
                    await self._apply_manifest(undo_row.manifest_hash)
                finally:
                    await self._fail_operation(operation_id, str(exc))
                raise
            return RestoreResult(
                operation_id=operation_id,
                checkpoint_id=target.id,
                undo_checkpoint_id=undo.id,
                status="committed",
                restored_paths=restored_paths,
            )

    async def undo(self, operation_id: str) -> RestoreResult:
        async with self.session_factory() as db:
            operation = await db.get(CoreRestoreOperation, operation_id)
            if operation is None:
                raise LookupError("Restore operation not found")
            if operation.status != "committed":
                raise ValueError("Only a committed restore can be undone")
            undo_checkpoint_id = operation.undo_checkpoint_id
        return await self.restore(undo_checkpoint_id)

    async def undo_restore(self, operation_id: str) -> RestoreResult:
        return await self.undo(operation_id)

    async def _capture(self, *, session_id: str, turn_id: str, actor_kind: str) -> CheckpointRef:
        manifest_hash, entries, blobs = await asyncio.to_thread(self._capture_workspace)
        root_session_id = _root_session_id(session_id)
        conversation = await self._read_conversation(root_session_id)
        checkpoint_id = uuid.uuid4().hex
        created_at = datetime.now()

        async def write(db: Any) -> CheckpointRef:
            manifest = await db.get(CoreWorkspaceManifest, manifest_hash)
            if manifest is None:
                db.add(CoreWorkspaceManifest(hash=manifest_hash, entries_json=entries))
            for blob_hash, size, storage_path in blobs:
                if await db.get(CoreCheckpointBlob, blob_hash) is None:
                    db.add(CoreCheckpointBlob(hash=blob_hash, size=size, storage_path=storage_path))
            row = CoreCheckpoint(
                id=checkpoint_id,
                root_session_id=root_session_id,
                session_id=session_id,
                turn_id=turn_id,
                actor_kind=actor_kind,
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

    async def _read_conversation(self, root_session_id: str) -> dict[str, Any]:
        async with self.session_factory() as db:
            runtime = await db.get(CoreRuntimeSession, root_session_id)
            snapshot = await db.get(CoreThreadSnapshot, root_session_id)
        return {
            "runtime": _runtime_payload(runtime),
            "projection": _projection_payload(snapshot),
        }

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
        async with self.session_factory() as db:
            row = await db.get(CoreWorkspaceManifest, manifest_hash)
            if row is None:
                raise LookupError("Workspace manifest not found")
            return dict(row.entries_json or {})

    async def _apply_manifest(self, manifest_hash: str) -> list[str]:
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

    async def _create_operation(self, operation_id: str, target: CoreCheckpoint, undo_id: str) -> None:
        async def write(db: Any) -> None:
            db.add(CoreRestoreOperation(
                id=operation_id,
                root_session_id=target.root_session_id,
                target_checkpoint_id=target.id,
                undo_checkpoint_id=undo_id,
                status="prepared",
            ))
        await self.write_coordinator.run(write)

    async def _restore_conversation(self, target: CoreCheckpoint, operation_id: str) -> None:
        conversation = dict(target.conversation_json or {})
        runtime_payload = conversation.get("runtime")
        projection_payload = conversation.get("projection")

        async def write(db: Any) -> None:
            runtime = await db.get(CoreRuntimeSession, target.root_session_id)
            if isinstance(runtime_payload, dict):
                if runtime is None:
                    runtime = CoreRuntimeSession(thread_id=target.root_session_id)
                    db.add(runtime)
                runtime.revision = max(int(runtime.revision or 0) + 1, int(runtime_payload.get("revision") or 0) + 1)
                runtime.runtime_state_json = dict(runtime_payload.get("runtime_state_json") or {})
                runtime.history_json = list(runtime_payload.get("history_json") or [])
                runtime.pending_approval_json = dict(runtime_payload.get("pending_approval_json") or {})
                runtime.last_event_seq = int(runtime_payload.get("last_event_seq") or 0)
                runtime.updated_at = datetime.now()
            elif runtime is not None:
                await db.delete(runtime)

            projection = await db.get(CoreThreadSnapshot, target.root_session_id)
            if isinstance(projection_payload, dict):
                if projection is None:
                    projection = CoreThreadSnapshot(thread_id=target.root_session_id)
                    db.add(projection)
                projection.snapshot_seq = int(projection_payload.get("snapshot_seq") or 0)
                projection.snapshot_json = dict(projection_payload.get("snapshot_json") or {})
                projection.updated_at = datetime.now()
            elif projection is not None:
                await db.delete(projection)

            operation = await db.get(CoreRestoreOperation, operation_id)
            if operation is None:
                raise LookupError("Restore operation disappeared")
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


def register_checkpoint_operations(
    catalog: OperationCatalog,
    *,
    session_factory: async_sessionmaker,
    data_dir: str | Path,
    default_work_root: str | Path,
) -> None:
    """Register the one public operation surface used by RPC and CLI."""

    storage_root = Path(data_dir).resolve() / "checkpoints"

    def coordinator(work_root: str | Path) -> CoreCheckpointCoordinator:
        return CoreCheckpointCoordinator(
            work_root=work_root,
            session_factory=session_factory,
            storage_root=storage_root,
        )

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

    async def rollback(request: OperationRequest) -> OperationResult:
        session_id = str(request.payload.get("session_id") or request.payload.get("thread_id") or "").strip()
        checkpoint_id = str(request.payload.get("checkpoint_id") or "").strip()
        if not session_id or not checkpoint_id:
            return _operation_error(request, "session_id and checkpoint_id are required")
        try:
            await _require_inactive_session(session_factory, session_id)
            checkpoint = await _checkpoint_for_session(session_factory, session_id, checkpoint_id)
            result = await coordinator(checkpoint.work_root).restore(checkpoint_id)
        except (LookupError, ValueError, OSError) as exc:
            return _operation_error(request, str(exc))
        return OperationResult(name=request.name, payload=_restore_payload(result))

    async def rollback_undo(request: OperationRequest) -> OperationResult:
        session_id = str(request.payload.get("session_id") or request.payload.get("thread_id") or "").strip()
        operation_id = str(request.payload.get("operation_id") or "").strip()
        if not session_id or not operation_id:
            return _operation_error(request, "session_id and operation_id are required")
        try:
            await _require_inactive_session(session_factory, session_id)
            work_root = await _undo_work_root(session_factory, session_id, operation_id)
            result = await coordinator(work_root).undo(operation_id)
        except (LookupError, ValueError, OSError) as exc:
            return _operation_error(request, str(exc))
        return OperationResult(name=request.name, payload=_restore_payload(result))

    catalog.register("session.checkpoints.list", checkpoints_list)
    catalog.register("session.rollback", rollback)
    catalog.register("session.rollback.undo", rollback_undo)


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


async def _require_inactive_session(session_factory: async_sessionmaker, session_id: str) -> None:
    root_session_id = _root_session_id(session_id)
    async with session_factory() as db:
        runtime = await db.get(CoreRuntimeSession, root_session_id)
        projection = await db.get(CoreThreadSnapshot, root_session_id)
    runtime_status = str((runtime.runtime_state_json or {}).get("status") or "") if runtime is not None else ""
    projection_status = str((projection.snapshot_json or {}).get("status") or "") if projection is not None else ""
    if runtime_status in {"running", "waiting"} or projection_status in {"running", "waiting"}:
        raise ValueError("Session has an active turn; cancel or finish it before rollback")


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
        "session_id": row.session_id,
        "turn_id": row.turn_id,
        "actor_kind": row.actor_kind,
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
        "status": result.status,
        "restored_paths": list(result.restored_paths),
    }


def _operation_error(request: OperationRequest, message: str) -> OperationResult:
    return OperationResult(name=request.name, status="error", payload={"error": message})


def _checkpoint_ref(row: CoreCheckpoint) -> CheckpointRef:
    return CheckpointRef(
        id=row.id,
        session_id=row.session_id,
        turn_id=row.turn_id,
        actor_kind=row.actor_kind,
        work_root=row.work_root,
        manifest_hash=row.manifest_hash,
        created_at=row.created_at,
    )


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
    "CheckpointRef",
    "CHECKPOINT_OPERATION_NAMES",
    "CoreCheckpointCoordinator",
    "RestoreResult",
    "TurnCheckpointCoordinator",
    "register_checkpoint_operations",
]
