"""Core-owned SQLite storage for standalone Core Agent hosts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
import uuid

from sqlalchemy import DateTime, Float, Integer, JSON, String, UniqueConstraint, delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import RuntimeState, RuntimeStateConflictError
from lamtools_core.runtime.arrange import (
    ArrangeJob,
    ArrangeOccurrence,
    ArrangeStatus,
    ArrangeStore,
    SignalEmission,
    next_arrange_run,
)
from lamtools_core.runtime.goal import Goal, GoalStatus, GoalStore

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


class CoreHistoryEntry(CoreDbBase):
    """Incremental conversation history — one row per message (append-only).

    Replaces the monolithic ``history_json`` blob on ``CoreRuntimeSession``.
    Old sessions are migrated lazily: ``get_history`` falls back to the blob
    when no rows exist yet, and ``append_history`` migrates the blob on first
    append.
    """

    __tablename__ = "core_history_entries"
    __table_args__ = (
        UniqueConstraint("thread_id", "seq", name="uq_core_history_thread_seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    message_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreGoal(CoreDbBase):
    __tablename__ = "core_goals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    objective: Mapped[str] = mapped_column(String, nullable=False)
    completion_criteria_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    status_reason: Mapped[str] = mapped_column(String, nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CoreArrangeJob(CoreDbBase):
    __tablename__ = "core_arrange_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    source_thread_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="")
    work_root: Mapped[str] = mapped_column(String(2048), index=True, nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    trigger_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    session_strategy: Mapped[str] = mapped_column(String(16), nullable=False, default="new")
    model_id: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    observer_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurrence_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    lease_owner: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(String, nullable=False, default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoreArrangeSignal(CoreDbBase):
    __tablename__ = "core_arrange_signals"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(256), index=True, nullable=False)
    envelope_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoreArrangeOccurrence(CoreDbBase):
    __tablename__ = "core_arrange_occurrences"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    signal_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False, default="")
    signal_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(String, nullable=False, default="")
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CoreCheckpoint(CoreDbBase):
    __tablename__ = "core_checkpoints"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    root_session_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    graph_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    parent_checkpoint_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    edge_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="checkpoint")
    reason: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    label: Mapped[str] = mapped_column(String(256), nullable=False, default="")
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
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="all")
    derived_checkpoint_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
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


class CoreMemory(CoreDbBase):
    """Short-term memory entries produced by dreaming.

    Mirrors :class:`lamtools_core.mem.MemoryEntry`. ``work_root`` is indexed so
    memories can be scoped per project (same isolation pattern as
    ``core_arrange_jobs``). Long-term memory lives in ``MEMORY.md``; this table
    holds the structured, searchable, decayable layer used for de-duplication
    during dreaming.
    """

    __tablename__ = "core_memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False, default="")
    work_root: Mapped[str] = mapped_column(String(2048), index=True, nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(64), nullable=False, default="fact")
    content: Mapped[str] = mapped_column(String, nullable=False, default="")
    domain: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    layer: Mapped[str] = mapped_column(String(16), nullable=False, default="warm")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    accessed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


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

    async def get_history(self, session_id: str, *, after_seq: int = 0) -> list[dict[str, Any]]:
        async with self.session_factory() as db:
            stmt = (
                select(CoreHistoryEntry)
                .where(CoreHistoryEntry.thread_id == session_id)
                .order_by(CoreHistoryEntry.seq.asc())
            )
            if after_seq > 0:
                stmt = stmt.where(CoreHistoryEntry.seq > after_seq)
            rows = (await db.execute(stmt)).scalars().all()
            if rows:
                return [dict(row.message_json) for row in rows]
            # Fallback: old monolithic blob (pre-migration)
            row = await db.get(CoreRuntimeSession, session_id)
        if row is None or not isinstance(row.history_json, list):
            return []
        return _json_safe(row.history_json)

    async def save_checkpoint(self, state: RuntimeState, history: list[dict[str, Any]]) -> None:
        await self._save(state, history=history)

    async def history_max_seq(self, session_id: str) -> int:
        async with self.session_factory() as db:
            result = await db.execute(
                select(func.coalesce(func.max(CoreHistoryEntry.seq), 0)).where(
                    CoreHistoryEntry.thread_id == session_id
                )
            )
            return int(result.scalar_one())

    async def append_history(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        """Append messages incrementally to the ``core_history_entries`` table.

        On first call for a session that still has data in the legacy
        ``history_json`` blob, the blob is migrated to rows first (lazy
        migration), then the new messages are appended.

        Routed through the :class:`SQLiteWriteCoordinator` so the ``max_seq``
        read and the inserts share a single ``BEGIN IMMEDIATE`` transaction.
        This both closes a TOCTOU gap (seq could otherwise change between the
        read and the insert) and serialises the write against concurrent
        ``replace_history`` / sub-agent ``append_history`` calls — the
        historical cause of ``database is locked`` deadlocks.
        """
        if not messages:
            return

        async def write(db) -> None:
            max_seq = int(
                (
                    await db.execute(
                        select(func.coalesce(func.max(CoreHistoryEntry.seq), 0)).where(
                            CoreHistoryEntry.thread_id == session_id
                        )
                    )
                ).scalar_one()
            )
            # Lazy migration: if incremental table is empty but blob has data,
            # migrate the blob first.
            if max_seq == 0:
                row = await db.get(CoreRuntimeSession, session_id)
                if row is not None and isinstance(row.history_json, list) and row.history_json:
                    for i, msg in enumerate(row.history_json, 1):
                        db.add(
                            CoreHistoryEntry(
                                thread_id=session_id,
                                seq=i,
                                message_json=_json_safe(msg),
                            )
                        )
                    max_seq = len(row.history_json)
            for msg in messages:
                max_seq += 1
                db.add(
                    CoreHistoryEntry(
                        thread_id=session_id,
                        seq=max_seq,
                        message_json=_json_safe(msg),
                    )
                )

        await self.write_coordinator.run(write)

    async def replace_history(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        """Replace the entire history (used after compaction / truncation).

        Deletes all existing rows for the session and re-inserts the given
        messages with fresh sequential numbering. Also clears the legacy
        ``history_json`` blob so subsequent ``get_history`` calls read only
        from the incremental table.

        Routed through the :class:`SQLiteWriteCoordinator` (single
        ``BEGIN IMMEDIATE``) to avoid ``database is locked`` when a concurrent
        sub-agent ``append_history`` is in flight — the deadlock root cause.
        """
        async def write(db) -> None:
            await db.execute(
                delete(CoreHistoryEntry).where(CoreHistoryEntry.thread_id == session_id)
            )
            for i, msg in enumerate(messages, 1):
                db.add(
                    CoreHistoryEntry(
                        thread_id=session_id,
                        seq=i,
                        message_json=_json_safe(msg),
                    )
                )
            # Clear legacy blob to avoid stale fallback reads.
            row = await db.get(CoreRuntimeSession, session_id)
            if row is not None:
                row.history_json = []

        await self.write_coordinator.run(write)

    async def find_pending_approval(self, request_id: str) -> RuntimeState | None:
        async with self.session_factory() as db:
            # Filter at the SQL layer to only sessions that actually carry a
            # pending_approval payload. Most sessions have an empty
            # pending_approval_json, so this avoids deserialising the whole
            # table on every approval lookup. json_extract is sqlite-native
            # (the only backend this store targets).
            rows = (
                await db.execute(
                    select(CoreRuntimeSession).where(
                        func.json_extract(
                            CoreRuntimeSession.pending_approval_json,
                            "$.pending_approval",
                        ).isnot(None)
                    )
                )
            ).scalars().all()
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


class SqlAlchemyGoalStore:
    def __init__(self, session_factory: async_sessionmaker, write_coordinator: SQLiteWriteCoordinator) -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator

    async def insert(self, goal: Goal) -> Goal:
        async def write(db):
            if await db.get(CoreGoal, goal.id) is not None:
                raise ValueError(f"Goal already exists: {goal.id}")
            db.add(_goal_row(goal))
            await db.flush()
            return goal

        return await self.write_coordinator.run(write)

    async def get(self, goal_id: str) -> Goal | None:
        async with self.session_factory() as db:
            row = await db.get(CoreGoal, goal_id)
        return _goal_from_row(row) if row is not None else None

    async def list(
        self, *, thread_id: str | None = None, status: GoalStatus | None = None
    ) -> list[Goal]:
        statement = select(CoreGoal)
        if thread_id is not None:
            statement = statement.where(CoreGoal.thread_id == thread_id)
        if status is not None:
            statement = statement.where(CoreGoal.status == status)
        statement = statement.order_by(CoreGoal.created_at, CoreGoal.id)
        async with self.session_factory() as db:
            rows = (await db.execute(statement)).scalars().all()
        return [_goal_from_row(row) for row in rows]

    async def replace(self, goal: Goal, *, expected_revision: int) -> Goal:
        async def write(db):
            result = await db.execute(
                update(CoreGoal)
                .where(CoreGoal.id == goal.id, CoreGoal.revision == expected_revision)
                .values(**_goal_values(goal))
            )
            if result.rowcount != 1:
                existing = await db.get(CoreGoal, goal.id)
                if existing is None:
                    raise LookupError(f"Goal not found: {goal.id}")
                raise RuntimeError(f"Goal revision conflict: {goal.id}")
            return goal

        return await self.write_coordinator.run(write)


class SqlAlchemyArrangeStore:
    def __init__(self, session_factory: async_sessionmaker, write_coordinator: SQLiteWriteCoordinator) -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator

    async def insert(self, job: ArrangeJob) -> ArrangeJob:
        async def write(db):
            if await db.get(CoreArrangeJob, job.id) is not None:
                raise ValueError(f"Arrange job already exists: {job.id}")
            db.add(_arrange_row(job))
            await db.flush()
            return job

        return await self.write_coordinator.run(write)

    async def get(self, job_id: str) -> ArrangeJob | None:
        async with self.session_factory() as db:
            row = await db.get(CoreArrangeJob, job_id)
        return _arrange_from_row(row) if row is not None else None

    async def list(
        self, *, thread_id: str | None = None, work_root: str | None = None, status: ArrangeStatus | None = None
    ) -> list[ArrangeJob]:
        statement = select(CoreArrangeJob)
        if thread_id is not None:
            statement = statement.where(CoreArrangeJob.thread_id == thread_id)
        if work_root is not None:
            statement = statement.where(CoreArrangeJob.work_root == work_root)
        if status is not None:
            statement = statement.where(CoreArrangeJob.status == status)
        statement = statement.order_by(CoreArrangeJob.created_at, CoreArrangeJob.id)
        async with self.session_factory() as db:
            rows = (await db.execute(statement)).scalars().all()
        return [_arrange_from_row(row) for row in rows]

    async def replace(self, job: ArrangeJob, *, expected_revision: int) -> ArrangeJob:
        async def write(db):
            current_row = await db.get(CoreArrangeJob, job.id)
            if (
                current_row is not None
                and current_row.revision == expected_revision
                and current_row.status == "running"
                and current_row.occurrence_id
                and job.status in {"paused", "cancelled"}
            ):
                occurrence_row = await db.get(CoreArrangeOccurrence, current_row.occurrence_id)
                if occurrence_row is not None and occurrence_row.status == "running":
                    occurrence = _occurrence_from_row(occurrence_row)
                    await db.execute(
                        update(CoreArrangeOccurrence)
                        .where(
                            CoreArrangeOccurrence.id == occurrence.id,
                            CoreArrangeOccurrence.status == "running",
                        )
                        .values(**_occurrence_values(replace(
                            occurrence,
                            status="pending" if job.status == "paused" else "cancelled",
                            started_at=None if job.status == "paused" else occurrence.started_at,
                            completed_at=job.updated_at if job.status == "cancelled" else None,
                            updated_at=job.updated_at,
                        )))
                    )
            result = await db.execute(
                update(CoreArrangeJob)
                .where(CoreArrangeJob.id == job.id, CoreArrangeJob.revision == expected_revision)
                .values(**_arrange_values(job))
            )
            if result.rowcount != 1:
                existing = await db.get(CoreArrangeJob, job.id)
                if existing is None:
                    raise LookupError(f"Arrange job not found: {job.id}")
                raise RuntimeError(f"Arrange job revision conflict: {job.id}")
            return job

        return await self.write_coordinator.run(write)

    async def claim_due(
        self,
        *,
        now: datetime,
        worker_id: str,
        lease_seconds: float,
        limit: int,
    ) -> list[ArrangeJob]:
        claim_time = _utc_datetime(now)

        async def write(db):
            expired = (
                await db.execute(
                    select(CoreArrangeJob).where(
                        CoreArrangeJob.status == "running",
                        CoreArrangeJob.lease_expires_at.is_not(None),
                        CoreArrangeJob.lease_expires_at <= claim_time,
                    )
                )
            ).scalars().all()
            for row in expired:
                if row.occurrence_id:
                    await db.execute(
                        update(CoreArrangeOccurrence)
                        .where(
                            CoreArrangeOccurrence.id == row.occurrence_id,
                            CoreArrangeOccurrence.status == "running",
                        )
                        .values(status="pending", started_at=None, updated_at=claim_time)
                    )
            await db.execute(
                update(CoreArrangeJob)
                .execution_options(synchronize_session=False)
                .where(
                    CoreArrangeJob.status == "running",
                    CoreArrangeJob.lease_expires_at.is_not(None),
                    CoreArrangeJob.lease_expires_at <= claim_time,
                )
                .values(
                    status="scheduled",
                    next_run_at=claim_time,
                    lease_owner="",
                    lease_expires_at=None,
                    revision=CoreArrangeJob.revision + 1,
                    updated_at=claim_time,
                )
            )
            rows = (
                await db.execute(
                    select(CoreArrangeJob)
                    .where(
                        CoreArrangeJob.status == "scheduled",
                        CoreArrangeJob.next_run_at.is_not(None),
                        CoreArrangeJob.next_run_at <= claim_time,
                    )
                    .order_by(CoreArrangeJob.next_run_at, CoreArrangeJob.created_at, CoreArrangeJob.id)
                    .limit(max(1, limit))
                )
            ).scalars().all()
            claimed: list[ArrangeJob] = []
            for row in rows:
                current = _arrange_from_row(row)
                occurrence_row = (
                    await db.execute(
                        select(CoreArrangeOccurrence)
                        .where(
                            CoreArrangeOccurrence.job_id == current.id,
                            CoreArrangeOccurrence.status == "pending",
                        )
                        .order_by(
                            CoreArrangeOccurrence.scheduled_at,
                            CoreArrangeOccurrence.created_at,
                            CoreArrangeOccurrence.id,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if occurrence_row is None:
                    if str(current.trigger.get("type") or "") == "event":
                        continue
                    occurrence = ArrangeOccurrence(
                        id=current.occurrence_id or f"occ_{uuid.uuid4().hex}",
                        job_id=current.id,
                        scheduled_at=current.next_run_at or claim_time,
                        created_at=claim_time,
                        updated_at=claim_time,
                    )
                    occurrence_row = _occurrence_row(occurrence)
                    db.add(occurrence_row)
                    await db.flush()
                occurrence = _occurrence_from_row(occurrence_row)
                running_occurrence = replace(
                    occurrence,
                    status="running",
                    started_at=claim_time,
                    attempt_count=occurrence.attempt_count + 1,
                    updated_at=claim_time,
                )
                await db.execute(
                    update(CoreArrangeOccurrence)
                    .where(
                        CoreArrangeOccurrence.id == occurrence.id,
                        CoreArrangeOccurrence.status == "pending",
                    )
                    .values(**_occurrence_values(running_occurrence))
                )
                claimed_job = replace(
                    current,
                    status="running",
                    occurrence_id=occurrence.id,
                    signal=deepcopy(occurrence.signal),
                    lease_owner=worker_id,
                    lease_expires_at=claim_time + timedelta(seconds=lease_seconds),
                    revision=current.revision + 1,
                    updated_at=claim_time,
                )
                await db.execute(
                    update(CoreArrangeJob)
                    .where(
                        CoreArrangeJob.id == current.id,
                        CoreArrangeJob.revision == current.revision,
                        CoreArrangeJob.status == "scheduled",
                    )
                    .values(**_arrange_values(claimed_job))
                )
                claimed.append(claimed_job)
            return claimed

        return await self.write_coordinator.run(write)

    async def renew_lease(
        self, *, job_id: str, worker_id: str, now: datetime, lease_seconds: float
    ) -> bool:
        when = _utc_datetime(now)

        async def write(db):
            row = await db.get(CoreArrangeJob, job_id)
            if row is None or row.status != "running" or row.lease_owner != worker_id:
                return False
            result = await db.execute(
                update(CoreArrangeJob)
                .where(
                    CoreArrangeJob.id == job_id,
                    CoreArrangeJob.revision == row.revision,
                    CoreArrangeJob.status == "running",
                    CoreArrangeJob.lease_owner == worker_id,
                )
                .values(
                    lease_expires_at=when + timedelta(seconds=lease_seconds),
                    revision=row.revision + 1,
                    updated_at=when,
                )
            )
            return result.rowcount == 1

        return await self.write_coordinator.run(write)

    async def complete_run(
        self,
        *,
        job_id: str,
        worker_id: str,
        now: datetime,
        result: dict[str, Any] | None = None,
    ) -> ArrangeJob:
        when = _utc_datetime(now)

        async def write(db):
            current = await self._owned_running(db, job_id, worker_id)
            occurrence_row = await db.get(CoreArrangeOccurrence, current.occurrence_id)
            if occurrence_row is not None:
                occurrence = _occurrence_from_row(occurrence_row)
                await db.execute(
                    update(CoreArrangeOccurrence)
                    .where(CoreArrangeOccurrence.id == occurrence.id)
                    .values(**_occurrence_values(replace(
                        occurrence,
                        status="completed",
                        completed_at=when,
                        last_error="",
                        result=_json_safe(result or {}),
                        updated_at=when,
                    )))
                )
            run_count = current.run_count + 1
            trigger_type = str(current.trigger.get("type") or "")
            repeat = trigger_type in {"interval", "calendar", "event"} and (
                current.max_runs is None or run_count < current.max_runs
            )
            pending_event = trigger_type == "event" and await self._has_pending_occurrence(db, job_id)
            next_status: ArrangeStatus = (
                "scheduled" if repeat and pending_event
                else "waiting" if repeat and trigger_type == "event"
                else "scheduled" if repeat
                else "completed"
            )
            updated = replace(
                current,
                status=next_status,
                next_run_at=(
                    when if repeat and pending_event
                    else next_arrange_run(current.trigger, when) if repeat
                    else None
                ),
                run_count=run_count,
                occurrence_id="" if repeat else current.occurrence_id,
                signal={},
                lease_owner="",
                lease_expires_at=None,
                last_error="",
                revision=current.revision + 1,
                updated_at=when,
            )
            await db.execute(
                update(CoreArrangeJob)
                .where(
                    CoreArrangeJob.id == job_id,
                    CoreArrangeJob.revision == current.revision,
                    CoreArrangeJob.lease_owner == worker_id,
                )
                .values(**_arrange_values(updated))
            )
            return updated

        return await self.write_coordinator.run(write)

    async def fail_run(
        self, *, job_id: str, worker_id: str, now: datetime, error: str
    ) -> ArrangeJob:
        when = _utc_datetime(now)

        async def write(db):
            current = await self._owned_running(db, job_id, worker_id)
            occurrence_row = await db.get(CoreArrangeOccurrence, current.occurrence_id)
            retry = False
            if occurrence_row is not None:
                occurrence = _occurrence_from_row(occurrence_row)
                retry = occurrence.attempt_count < 3
                await db.execute(
                    update(CoreArrangeOccurrence)
                    .where(CoreArrangeOccurrence.id == occurrence.id)
                    .values(**_occurrence_values(replace(
                        occurrence,
                        status="pending" if retry else "failed",
                        started_at=None if retry else occurrence.started_at,
                        completed_at=None if retry else when,
                        last_error=str(error or "arranged operation failed"),
                        updated_at=when,
                    )))
                )
            updated = replace(
                current,
                status="scheduled" if retry else "failed",
                next_run_at=when if retry else None,
                signal={},
                lease_owner="",
                lease_expires_at=None,
                last_error=str(error or "arranged operation failed"),
                revision=current.revision + 1,
                updated_at=when,
            )
            await db.execute(
                update(CoreArrangeJob)
                .where(
                    CoreArrangeJob.id == job_id,
                    CoreArrangeJob.revision == current.revision,
                    CoreArrangeJob.lease_owner == worker_id,
                )
                .values(**_arrange_values(updated))
            )
            return updated

        return await self.write_coordinator.run(write)

    async def recover_running(self, *, now: datetime) -> int:
        when = _utc_datetime(now)

        async def write(db):
            running_rows = (
                await db.execute(select(CoreArrangeJob).where(CoreArrangeJob.status == "running"))
            ).scalars().all()
            for row in running_rows:
                if row.occurrence_id:
                    await db.execute(
                        update(CoreArrangeOccurrence)
                        .where(
                            CoreArrangeOccurrence.id == row.occurrence_id,
                            CoreArrangeOccurrence.status == "running",
                        )
                        .values(status="pending", started_at=None, updated_at=when)
                    )
            result = await db.execute(
                update(CoreArrangeJob)
                .where(CoreArrangeJob.status == "running")
                .values(
                    status="scheduled",
                    next_run_at=when,
                    lease_owner="",
                    lease_expires_at=None,
                    revision=CoreArrangeJob.revision + 1,
                    updated_at=when,
                )
            )
            return int(result.rowcount or 0)

        return await self.write_coordinator.run(write)

    async def emit_signal(
        self,
        signal: dict[str, Any],
        *,
        now: datetime,
        job_id: str | None = None,
    ) -> SignalEmission:
        when = _utc_datetime(now)

        async def write(db):
            event_id = str(signal.get("event_id") or "")
            existing = await db.get(CoreArrangeSignal, event_id)
            if existing is not None:
                return SignalEmission(signal=_json_safe(existing.envelope_json), created=False)
            db.add(CoreArrangeSignal(
                event_id=event_id,
                event_type=str(signal.get("event_type") or ""),
                envelope_json=_json_safe(signal),
                occurred_at=_utc_datetime(datetime.fromisoformat(str(signal["occurred_at"]))),
                received_at=when,
            ))
            jobs = select(CoreArrangeJob).where(
                CoreArrangeJob.status.not_in(("completed", "failed", "cancelled"))
            )
            if job_id is not None:
                jobs = jobs.where(CoreArrangeJob.id == job_id)
            rows = (await db.execute(jobs)).scalars().all()
            occurrences: list[ArrangeOccurrence] = []
            for row in rows:
                trigger = row.trigger_json if isinstance(row.trigger_json, dict) else {}
                if (
                    str(trigger.get("type") or "") != "event"
                    or str(trigger.get("event_type") or trigger.get("key") or "")
                    != str(signal.get("event_type") or "")
                ):
                    continue
                occurrence = ArrangeOccurrence(
                    id=f"occ_{uuid.uuid4().hex}",
                    job_id=row.id,
                    signal_id=event_id,
                    signal=_json_safe(signal),
                    scheduled_at=when,
                    created_at=when,
                    updated_at=when,
                )
                db.add(_occurrence_row(occurrence))
                occurrences.append(occurrence)
                if row.status == "waiting":
                    await db.execute(
                        update(CoreArrangeJob)
                        .where(CoreArrangeJob.id == row.id, CoreArrangeJob.revision == row.revision)
                        .values(
                            status="scheduled",
                            next_run_at=when,
                            revision=row.revision + 1,
                            updated_at=when,
                        )
                    )
            await db.flush()
            return SignalEmission(
                signal=_json_safe(signal),
                created=True,
                occurrences=tuple(occurrences),
            )

        return await self.write_coordinator.run(write)

    async def get_occurrence(self, occurrence_id: str) -> ArrangeOccurrence | None:
        async with self.session_factory() as db:
            row = await db.get(CoreArrangeOccurrence, occurrence_id)
        return _occurrence_from_row(row) if row is not None else None

    async def list_occurrences(self, *, job_id: str | None = None) -> list[ArrangeOccurrence]:
        statement = select(CoreArrangeOccurrence)
        if job_id is not None:
            statement = statement.where(CoreArrangeOccurrence.job_id == job_id)
        statement = statement.order_by(CoreArrangeOccurrence.created_at, CoreArrangeOccurrence.id)
        async with self.session_factory() as db:
            rows = (await db.execute(statement)).scalars().all()
        return [_occurrence_from_row(row) for row in rows]

    @staticmethod
    async def _has_pending_occurrence(db: Any, job_id: str) -> bool:
        row = (
            await db.execute(
                select(CoreArrangeOccurrence.id)
                .where(
                    CoreArrangeOccurrence.job_id == job_id,
                    CoreArrangeOccurrence.status == "pending",
                )
                .limit(1)
            )
        ).first()
        return row is not None

    @staticmethod
    async def _owned_running(db: Any, job_id: str, worker_id: str) -> ArrangeJob:
        row = await db.get(CoreArrangeJob, job_id)
        if row is None:
            raise LookupError(f"Arrange job not found: {job_id}")
        if row.status != "running" or row.lease_owner != worker_id:
            raise RuntimeError(f"Arrange job lease lost: {job_id}")
        return _arrange_from_row(row)


@dataclass(frozen=True)
class CoreAppDb:
    path: Path
    engine: AsyncEngine
    session_factory: async_sessionmaker
    event_store: SqlAlchemyAppEventStore
    snapshot_store: SqlAlchemyThreadSnapshotStore
    runtime_state_store: SqlAlchemyRuntimeStateStore
    goal_store: GoalStore
    arrange_store: ArrangeStore
    project_store: CoreProjectStore
    persistence: AppPersistenceHost
    memory_store: Any = None  # MemoryStoreProtocol; typed as Any to avoid import cycle
    member_defaults: dict = field(default_factory=dict)

    async def close(self) -> None:
        await self.engine.dispose()


async def open_core_app_db(path: Path | str, *, member_defaults: dict | None = None) -> CoreAppDb:
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
    from lamtools_core.mem.store import SqlAlchemyMemoryStore

    event_store = SqlAlchemyAppEventStore(CoreAppEvent)
    snapshot_store = SqlAlchemyThreadSnapshotStore(CoreThreadSnapshot, projector=CoreAppSnapshotProjector())
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
        goal_store=SqlAlchemyGoalStore(session_factory, write_coordinator),
        arrange_store=SqlAlchemyArrangeStore(session_factory, write_coordinator),
        project_store=CoreProjectStore(session_factory, write_coordinator),
        persistence=persistence,
        memory_store=SqlAlchemyMemoryStore(session_factory, write_coordinator),
        member_defaults=dict(member_defaults or {}),
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
    if "work_root" not in checkpoint_columns:
        await connection.execute(text(
            "ALTER TABLE core_checkpoints "
            "ADD COLUMN work_root VARCHAR(2048) NOT NULL DEFAULT ''"
        ))
        # Legacy checkpoints did not record their workspace and cannot be restored safely.
        await connection.execute(text(
            "UPDATE core_checkpoints SET status = 'unavailable' WHERE work_root = ''"
        ))
    arrange_columns = {
        row["name"]
        for row in (await connection.execute(text("PRAGMA table_info(core_arrange_jobs)"))).mappings()
    }
    if "goal_id" in arrange_columns:
        await connection.execute(text("DROP INDEX IF EXISTS ix_core_arrange_jobs_goal_id"))
        await connection.execute(text(
            "ALTER TABLE core_arrange_jobs DROP COLUMN goal_id"
        ))
    if "project_id" in arrange_columns:
        await connection.execute(text(
            "ALTER TABLE core_arrange_jobs DROP COLUMN project_id"
        ))
    if "source_thread_id" not in arrange_columns:
        await connection.execute(text(
            "ALTER TABLE core_arrange_jobs "
            "ADD COLUMN source_thread_id VARCHAR(64) NOT NULL DEFAULT ''"
        ))
        await connection.execute(text(
            "UPDATE core_arrange_jobs SET source_thread_id = thread_id WHERE source_thread_id = ''"
        ))
    if "observer_json" not in arrange_columns:
        await connection.execute(text(
            "ALTER TABLE core_arrange_jobs "
            "ADD COLUMN observer_json JSON NOT NULL DEFAULT '{}'"
        ))
    if "work_root" not in arrange_columns:
        await connection.execute(text(
            "ALTER TABLE core_arrange_jobs "
            "ADD COLUMN work_root VARCHAR(2048) NOT NULL DEFAULT ''"
        ))
    if "title" not in arrange_columns:
        await connection.execute(text(
            "ALTER TABLE core_arrange_jobs "
            "ADD COLUMN title VARCHAR(256) NOT NULL DEFAULT ''"
        ))
        # Backfill title from payload_json.message (first 80 chars)
        await connection.execute(text(
            "UPDATE core_arrange_jobs SET title = COALESCE("
            "  SUBSTR(json_extract(payload_json, '$.message'), 1, 80), ''"
            ") WHERE title = ''"
        ))
    if "session_strategy" not in arrange_columns:
        await connection.execute(text(
            "ALTER TABLE core_arrange_jobs "
            "ADD COLUMN session_strategy VARCHAR(16) NOT NULL DEFAULT 'new'"
        ))
    if "model_id" not in arrange_columns:
        await connection.execute(text(
            "ALTER TABLE core_arrange_jobs "
            "ADD COLUMN model_id VARCHAR(256) NOT NULL DEFAULT ''"
        ))
    restore_columns = {
        row["name"]
        for row in (await connection.execute(text("PRAGMA table_info(core_restore_operations)"))).mappings()
    }
    if "scope" not in restore_columns:
        await connection.execute(text(
            "ALTER TABLE core_restore_operations "
            "ADD COLUMN scope VARCHAR(32) NOT NULL DEFAULT 'all'"
        ))
    if "derived_checkpoint_id" not in restore_columns:
        await connection.execute(text(
            "ALTER TABLE core_restore_operations "
            "ADD COLUMN derived_checkpoint_id VARCHAR(64) NOT NULL DEFAULT ''"
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


def _utc_datetime(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _goal_values(goal: Goal) -> dict[str, Any]:
    return {
        "thread_id": goal.thread_id,
        "objective": goal.objective,
        "completion_criteria_json": list(goal.completion_criteria),
        "status": goal.status,
        "status_reason": goal.status_reason,
        "metadata_json": _json_safe(goal.metadata),
        "revision": goal.revision,
        "created_at": _utc_datetime(goal.created_at),
        "updated_at": _utc_datetime(goal.updated_at),
        "completed_at": _utc_datetime(goal.completed_at) if goal.completed_at else None,
    }


def _goal_row(goal: Goal) -> CoreGoal:
    return CoreGoal(id=goal.id, **_goal_values(goal))


def _goal_from_row(row: CoreGoal) -> Goal:
    return Goal(
        id=row.id,
        thread_id=row.thread_id,
        objective=row.objective,
        completion_criteria=tuple(str(item) for item in (row.completion_criteria_json or [])),
        status=row.status,  # type: ignore[arg-type]
        status_reason=row.status_reason or "",
        metadata=_json_safe(row.metadata_json or {}),
        revision=int(row.revision or 1),
        created_at=_utc_datetime(row.created_at),
        updated_at=_utc_datetime(row.updated_at),
        completed_at=_utc_datetime(row.completed_at) if row.completed_at else None,
    )


def _arrange_values(job: ArrangeJob) -> dict[str, Any]:
    return {
        "thread_id": job.thread_id,
        "source_thread_id": job.source_thread_id,
        "work_root": job.work_root,
        "kind": job.kind,
        "operation": job.operation,
        "payload_json": _json_safe(job.payload),
        "trigger_json": _json_safe(job.trigger),
        "title": job.title,
        "session_strategy": job.session_strategy,
        "model_id": job.model_id,
        "observer_json": _json_safe(job.observer),
        "status": job.status,
        "next_run_at": _utc_datetime(job.next_run_at) if job.next_run_at else None,
        "run_count": job.run_count,
        "max_runs": job.max_runs,
        "occurrence_id": job.occurrence_id,
        "lease_owner": job.lease_owner,
        "lease_expires_at": _utc_datetime(job.lease_expires_at) if job.lease_expires_at else None,
        "last_error": job.last_error,
        "revision": job.revision,
        "created_at": _utc_datetime(job.created_at),
        "updated_at": _utc_datetime(job.updated_at),
    }


def _arrange_row(job: ArrangeJob) -> CoreArrangeJob:
    return CoreArrangeJob(id=job.id, **_arrange_values(job))


def _arrange_from_row(row: CoreArrangeJob) -> ArrangeJob:
    return ArrangeJob(
        id=row.id,
        thread_id=row.thread_id,
        source_thread_id=row.source_thread_id or row.thread_id,
        work_root=row.work_root or "",
        kind=row.kind,  # type: ignore[arg-type]
        operation=row.operation,
        payload=_json_safe(row.payload_json or {}),
        trigger=_json_safe(row.trigger_json or {}),
        title=row.title or "",
        session_strategy=row.session_strategy or "new",  # type: ignore[arg-type]
        model_id=row.model_id or "",
        observer=_json_safe(row.observer_json or {}),
        status=row.status,  # type: ignore[arg-type]
        next_run_at=_utc_datetime(row.next_run_at) if row.next_run_at else None,
        run_count=int(row.run_count or 0),
        max_runs=int(row.max_runs) if row.max_runs is not None else None,
        occurrence_id=row.occurrence_id or "",
        lease_owner=row.lease_owner or "",
        lease_expires_at=_utc_datetime(row.lease_expires_at) if row.lease_expires_at else None,
        last_error=row.last_error or "",
        revision=int(row.revision or 1),
        created_at=_utc_datetime(row.created_at),
        updated_at=_utc_datetime(row.updated_at),
    )


def _occurrence_values(item: ArrangeOccurrence) -> dict[str, Any]:
    return {
        "job_id": item.job_id,
        "signal_id": item.signal_id,
        "signal_json": _json_safe(item.signal),
        "status": item.status,
        "scheduled_at": _utc_datetime(item.scheduled_at),
        "started_at": _utc_datetime(item.started_at) if item.started_at else None,
        "completed_at": _utc_datetime(item.completed_at) if item.completed_at else None,
        "attempt_count": item.attempt_count,
        "last_error": item.last_error,
        "result_json": _json_safe(item.result),
        "created_at": _utc_datetime(item.created_at),
        "updated_at": _utc_datetime(item.updated_at),
    }


def _occurrence_row(item: ArrangeOccurrence) -> CoreArrangeOccurrence:
    return CoreArrangeOccurrence(id=item.id, **_occurrence_values(item))


def _occurrence_from_row(row: CoreArrangeOccurrence) -> ArrangeOccurrence:
    return ArrangeOccurrence(
        id=row.id,
        job_id=row.job_id,
        signal_id=row.signal_id or "",
        signal=_json_safe(row.signal_json or {}),
        status=row.status,  # type: ignore[arg-type]
        scheduled_at=_utc_datetime(row.scheduled_at),
        started_at=_utc_datetime(row.started_at) if row.started_at else None,
        completed_at=_utc_datetime(row.completed_at) if row.completed_at else None,
        attempt_count=int(row.attempt_count or 0),
        last_error=row.last_error or "",
        result=_json_safe(row.result_json or {}),
        created_at=_utc_datetime(row.created_at),
        updated_at=_utc_datetime(row.updated_at),
    )


__all__ = [
    "CoreAppDb",
    "CoreAppEvent",
    "CoreArrangeJob",
    "CoreArrangeOccurrence",
    "CoreArrangeSignal",
    "CoreAttachment",
    "CoreCheckpoint",
    "CoreCheckpointBlob",
    "CoreGoal",
    "CoreProject",
    "CoreRestoreOperation",
    "CoreRuntimeSession",
    "CoreThreadSnapshot",
    "CoreWorkspaceManifest",
    "RuntimeStateConflictError",
    "SqlAlchemyRuntimeStateStore",
    "SqlAlchemyArrangeStore",
    "SqlAlchemyGoalStore",
    "list_core_sessions",
    "open_core_app_db",
    "persist_core_run_items",
    "show_core_session",
]
