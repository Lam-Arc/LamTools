"""Core-owned SQLite storage for standalone Core Agent hosts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import RuntimeState, RuntimeStateConflictError

from .event_store import SqlAlchemyAppEventStore
from .persistence_host import AppPersistenceHost
from .snapshot_store import CoreAppSnapshotProjector, SqlAlchemyThreadSnapshotStore
from .sqlite_write import SQLiteWriteCoordinator, configure_sqlite_engine

if TYPE_CHECKING:
    from .project_store import CoreProjectStore


class CoreDbBase(DeclarativeBase):
    pass


class CoreAppEvent(CoreDbBase):
    __tablename__ = "core_app_events"
    __table_args__ = (
        UniqueConstraint("thread_id", "seq", name="uq_core_app_events_thread_seq"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parent_item_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    client_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    method: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreThreadSnapshot(CoreDbBase):
    __tablename__ = "core_thread_snapshots"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreRuntimeSession(CoreDbBase):
    __tablename__ = "core_runtime_sessions"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    runtime_state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    history_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    pending_approval_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_event_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreCheckpoint(CoreDbBase):
    __tablename__ = "core_checkpoints"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    root_session_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    turn_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="main")
    work_root: Mapped[str] = mapped_column(String(2048), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    conversation_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreWorkspaceManifest(CoreDbBase):
    __tablename__ = "core_workspace_manifests"

    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    entries_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreCheckpointBlob(CoreDbBase):
    __tablename__ = "core_checkpoint_blobs"

    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreRestoreOperation(CoreDbBase):
    __tablename__ = "core_restore_operations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    root_session_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    target_checkpoint_id: Mapped[str] = mapped_column(String(64), nullable=False)
    undo_checkpoint_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="prepared")
    error: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreProject(CoreDbBase):
    __tablename__ = "core_projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    work_root: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )


class CoreAttachment(CoreDbBase):
    __tablename__ = "core_attachments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    preview_type: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class SqlAlchemyRuntimeStateStore:
    def __init__(self, session_factory: async_sessionmaker, write_coordinator: SQLiteWriteCoordinator) -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator

    async def get(self, session_id: str) -> RuntimeState | None:
        async with self.session_factory() as db:
            row = await db.get(CoreRuntimeSession, session_id)
        if row is None:
            return None
        payload = dict(row.runtime_state_json or {})
        metadata = dict(payload.get("metadata") or {})
        metadata.update(dict(row.pending_approval_json or {}))
        payload["metadata"] = metadata
        allowed = {"session_id", "run_id", "status", "position", "loop_state", "turn_count", "metadata"}
        state = RuntimeState(**{key: value for key, value in payload.items() if key in allowed})
        setattr(state, "_runtime_store_revision", int(row.revision or 0))
        return state

    async def save(self, state: RuntimeState) -> None:
        await self._save(state, history=None)

    async def get_history(self, session_id: str) -> list[dict[str, Any]]:
        async with self.session_factory() as db:
            row = await db.get(CoreRuntimeSession, session_id)
        if row is None or not isinstance(row.history_json, list):
            return []
        return _json_safe(row.history_json)

    async def save_checkpoint(self, state: RuntimeState, history: list[dict[str, Any]]) -> None:
        await self._save(state, history=history)

    async def find_pending_approval(self, request_id: str) -> RuntimeState | None:
        async with self.session_factory() as db:
            rows = (await db.execute(select(CoreRuntimeSession))).scalars().all()
        for row in rows:
            pending_root = row.pending_approval_json if isinstance(row.pending_approval_json, dict) else {}
            pending = pending_root.get("pending_approval") if isinstance(pending_root, dict) else None
            tool_call = pending.get("tool_call") if isinstance(pending, dict) else None
            pending_request_id = pending.get("request_id") if isinstance(pending, dict) else None
            tool_call_id = tool_call.get("id") if isinstance(tool_call, dict) else None
            if request_id in {str(pending_request_id or ""), str(tool_call_id or "")}:
                return await self.get(row.thread_id)
        return None

    async def _save(self, state: RuntimeState, *, history: list[dict[str, Any]] | None) -> None:
        state_payload, pending_payload = _runtime_state_payloads(state)
        expected_revision = getattr(state, "_runtime_store_revision", None)
        now = datetime.now()
        async def write(db):
            row = await db.get(CoreRuntimeSession, state.session_id)
            if row is None:
                if expected_revision not in {None, 0}:
                    raise RuntimeStateConflictError(f"Runtime state revision conflict for {state.session_id}")
                db.add(
                    CoreRuntimeSession(
                        thread_id=state.session_id,
                        revision=1,
                        runtime_state_json=state_payload,
                        history_json=_json_safe(history or []),
                        pending_approval_json=pending_payload,
                        last_event_seq=_last_event_seq(state),
                        updated_at=now,
                    )
                )
                await db.flush()
                return 1

            current_revision = int(row.revision or 0)
            if expected_revision is None or int(expected_revision) != current_revision:
                raise RuntimeStateConflictError(f"Runtime state revision conflict for {state.session_id}")
            next_revision = current_revision + 1
            values: dict[str, Any] = {
                "revision": next_revision,
                "runtime_state_json": state_payload,
                "pending_approval_json": pending_payload,
                "last_event_seq": _last_event_seq(state),
                "updated_at": now,
            }
            if history is not None:
                values["history_json"] = _json_safe(history)
            result = await db.execute(
                update(CoreRuntimeSession)
                .where(
                    CoreRuntimeSession.thread_id == state.session_id,
                    CoreRuntimeSession.revision == current_revision,
                )
                .values(**values)
            )
            if result.rowcount != 1:
                raise RuntimeStateConflictError(f"Runtime state revision conflict for {state.session_id}")
            return next_revision

        try:
            next_revision = await self.write_coordinator.run(write)
        except IntegrityError as exc:
            raise RuntimeStateConflictError(f"Runtime state revision conflict for {state.session_id}") from exc
        setattr(state, "_runtime_store_revision", next_revision)


@dataclass(frozen=True)
class CoreAppDb:
    path: Path
    engine: AsyncEngine
    session_factory: async_sessionmaker
    event_store: SqlAlchemyAppEventStore
    snapshot_store: SqlAlchemyThreadSnapshotStore
    runtime_state_store: SqlAlchemyRuntimeStateStore
    project_store: CoreProjectStore
    persistence: AppPersistenceHost

    async def close(self) -> None:
        await self.engine.dispose()


async def open_core_app_db(
    path: Path | str,
    *,
    member_defaults: dict[str, Any] | None = None,
) -> CoreAppDb:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(
        _sqlite_url(db_path),
        future=True,
        poolclass=NullPool,
    )
    configure_sqlite_engine(engine)
    async with engine.begin() as conn:
        await conn.run_sync(CoreDbBase.metadata.create_all)
        await _migrate_core_app_schema(conn)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    write_coordinator = SQLiteWriteCoordinator(session_factory)
    from .project_store import CoreProjectStore

    event_store = SqlAlchemyAppEventStore(CoreAppEvent)
    snapshot_store = SqlAlchemyThreadSnapshotStore(
        CoreThreadSnapshot,
        projector=CoreAppSnapshotProjector(member_defaults=dict(member_defaults or {})),
    )
    persistence = AppPersistenceHost(
        event_store,
        snapshot_store,
        session_factory=session_factory,
        write_coordinator=write_coordinator,
    )
    return CoreAppDb(
        path=db_path,
        engine=engine,
        session_factory=session_factory,
        event_store=event_store,
        snapshot_store=snapshot_store,
        runtime_state_store=SqlAlchemyRuntimeStateStore(session_factory, write_coordinator),
        project_store=CoreProjectStore(session_factory, write_coordinator),
        persistence=persistence,
    )


async def persist_core_run_items(db: CoreAppDb, run_items: list[RunItemEvent]) -> dict[str, Any] | None:
    if not run_items:
        return None
    snapshot: dict[str, Any] | None = None
    async def write(session):
        snapshot: dict[str, Any] | None = None
        envelopes_by_thread: dict[str, list[Any]] = {}
        for item in run_items:
            envelope = await db.event_store.append_run_item_event(session, item)
            envelopes_by_thread.setdefault(envelope.thread_id, []).append(envelope)
        for envelopes in envelopes_by_thread.values():
            snapshot = await db.snapshot_store.apply_many(session, envelopes)
        return snapshot

    return await db.persistence.write(write)


async def list_core_sessions(db: CoreAppDb) -> list[dict[str, Any]]:
    async with db.session_factory() as session:
        result = await session.execute(select(CoreThreadSnapshot).order_by(CoreThreadSnapshot.updated_at.desc()))
        rows = result.scalars().all()
    return [_snapshot_summary(row) for row in rows]


async def show_core_session(db: CoreAppDb, thread_id: str) -> dict[str, Any]:
    async with db.session_factory() as session:
        snapshot = await db.snapshot_store.load(session, thread_id)
        events = await db.event_store.list_thread(session, thread_id=thread_id)
    return {
        "thread_id": thread_id,
        "snapshot": snapshot,
        "events": [event.to_dict() for event in events],
    }


def _snapshot_summary(row: CoreThreadSnapshot) -> dict[str, Any]:
    snapshot = dict(row.snapshot_json or {})
    return {
        "thread_id": row.thread_id,
        "status": snapshot.get("status") or "",
        "snapshot_seq": int(row.snapshot_seq or 0),
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


async def _migrate_core_app_schema(connection: Any) -> None:
    checkpoint_columns = {
        row["name"]
        for row in (await connection.execute(text("PRAGMA table_info(core_checkpoints)"))).mappings()
    }
    if "work_root" in checkpoint_columns:
        return
    await connection.execute(text(
        "ALTER TABLE core_checkpoints "
        "ADD COLUMN work_root VARCHAR(2048) NOT NULL DEFAULT ''"
    ))
    # Legacy checkpoints did not record their workspace and cannot be restored safely.
    await connection.execute(text(
        "UPDATE core_checkpoints SET status = 'unavailable' WHERE work_root = ''"
    ))


def _runtime_state_payloads(state: RuntimeState) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = state.to_dict()
    metadata = dict(payload.get("metadata") or {})
    pending = {
        key: metadata.pop(key)
        for key in ("pending_approval", "pending_waiting_request")
        if key in metadata
    }
    if metadata:
        payload["metadata"] = metadata
    else:
        payload.pop("metadata", None)
    return _json_safe(payload), _json_safe(pending)


def _last_event_seq(state: RuntimeState) -> int:
    value = state.metadata.get("last_event_seq") if isinstance(state.metadata, dict) else 0
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


__all__ = [
    "CoreAppDb",
    "CoreAppEvent",
    "CoreAttachment",
    "CoreCheckpoint",
    "CoreCheckpointBlob",
    "CoreProject",
    "CoreRestoreOperation",
    "CoreRuntimeSession",
    "CoreThreadSnapshot",
    "CoreWorkspaceManifest",
    "RuntimeStateConflictError",
    "SqlAlchemyRuntimeStateStore",
    "list_core_sessions",
    "open_core_app_db",
    "persist_core_run_items",
    "show_core_session",
]
