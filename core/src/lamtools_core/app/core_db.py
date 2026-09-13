"""Core-owned SQLite storage for standalone Core Agent hosts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable
import uuid

from sqlalchemy import DateTime, Float, Index, Integer, JSON, String, UniqueConstraint, delete, event, func, select, text, update
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
from .project_visuals import DEFAULT_PROJECT_COLOR_KEY, DEFAULT_PROJECT_ICON_KEY
from .snapshot_store import CoreAppSnapshotProjector, SqlAlchemyThreadSnapshotStore
from .session_actor import SessionActorRegistry
from .sqlite_write import SQLiteWriteCoordinator, configure_sqlite_engine

if TYPE_CHECKING:
    from .project_store import CoreProjectStore


class CoreDbBase(DeclarativeBase):
    pass


CORE_SCHEMA_VERSION = 1


class CoreDbMetadata(CoreDbBase):
    """Small version/maintenance markers that keep startup work one-shot."""

    __tablename__ = "core_db_metadata"

    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    value: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreWorkspaceIdentity(CoreDbBase):
    """Stable identity for this local Workspace Host.

    It lives in the Core database so moving ``/data`` to another machine does
    not silently create a new Workspace for the same stored work data.
    """

    __tablename__ = "core_workspace_identity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


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
    # Canonical event-log fields.  ``seq``/``method`` remain as compatibility
    # aliases for the original Core live protocol; the fields below are the
    # stable sync contract shared by desktop and mobile clients.
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, default="thread.event")
    entity_id: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    event_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreThreadSnapshot(CoreDbBase):
    __tablename__ = "core_thread_snapshots"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_turn_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


@event.listens_for(CoreThreadSnapshot, "before_insert")
@event.listens_for(CoreThreadSnapshot, "before_update")
def _sync_snapshot_active_turn_index(_mapper: Any, _connection: Any, target: CoreThreadSnapshot) -> None:
    """Keep crash-recovery lookup data correct for every snapshot write path."""
    from .queue_state import latest_active_turn_id

    payload = target.snapshot_json if isinstance(target.snapshot_json, dict) else {}
    target.active_turn_id = latest_active_turn_id(payload)


class CoreThreadSnapshotItem(CoreDbBase):
    """One row per snapshot item (incremental projection).

    The thread snapshot's items live here instead of inside
    ``CoreThreadSnapshot.snapshot_json`` so a streaming part event only
    upserts the changed item row instead of rewriting the whole thread
    JSON (1.3-2.3s on 55MB threads). ``seq`` is the first-event seq anchor
    that keeps item_order equal to production order.
    """

    __tablename__ = "core_thread_snapshot_items"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    __table_args__ = (Index("idx_core_snapshot_items_thread_seq", "thread_id", "seq"),)


class CoreRuntimeSession(CoreDbBase):
    __tablename__ = "core_runtime_sessions"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    runtime_state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    history_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    pending_approval_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_event_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreHandoffContext(CoreDbBase):
    """Latest provider-neutral context captured at the model boundary.

    This is separate from ``core_runtime_sessions`` so the runtime state
    schema remains stable and the handoff payload can never be mistaken for
    resumable process state.  Only the latest context per thread is needed;
    the full historical transcript remains in the fact tables.
    """

    __tablename__ = "core_handoff_contexts"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    context_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
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
    # Per-message revision used by Local-First snapshots. History rows are
    # append-only, so the stable sequence is also a safe migration fallback.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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


class CoreSyncChange(CoreDbBase):
    """Global, append-only cursor used by Local-First mobile clients.

    ``core_app_events`` intentionally has a sequence per thread because the
    desktop live protocol orders a conversation that way. Mobile sync needs a
    single cursor across projects, threads and runtime changes, so it gets a
    separate journal. Rows are never updated in place; deletions are recorded
    as tombstones in ``entity_json``.
    """

    __tablename__ = "core_sync_changes"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    change_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False, default="")
    entity_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(256), index=True, nullable=False)
    thread_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False, default="")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    entity_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreCheckpointV2(CoreDbBase):
    """Metadata-only checkpoint index.

    Unlike ``core_checkpoints``, this table never contains a serialized
    conversation, event list, snapshot, or history blob.  The sequence
    numbers point back to the append-only fact tables and are sufficient to
    reconstruct a conversation at restore/export time.
    """

    __tablename__ = "core_checkpoints_v2"
    __table_args__ = (
        Index("idx_core_checkpoints_v2_root_created", "root_session_id", "created_at"),
        Index("idx_core_checkpoints_v2_session_created", "session_id", "created_at"),
        Index("idx_core_checkpoints_v2_parent", "parent_checkpoint_id"),
        Index("idx_core_checkpoints_v2_turn", "turn_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    root_session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_checkpoint_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    turn_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    actor_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="main")
    reason: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    event_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    history_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    runtime_state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    base_checkpoint_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    is_base_snapshot: Mapped[bool] = mapped_column(nullable=False, default=False)
    workspace_manifest_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreCheckpointV2Materialized(CoreDbBase):
    """Checkpoint-local recovery material for migrated legacy branches.

    The append-only fact tables are authoritative for new checkpoints, but
    old checkpoints were captured while those tables were mutable (rollback,
    fork, and compaction could replace the rows at the same sequence).  This
    small, explicit base snapshot keeps only the data needed to recover such a
    historical branch after ``CoreCheckpoint.conversation_json`` is cleared.
    It is deliberately separate from the legacy row and is never read as a
    fallback once the V2 row has been materialized.
    """

    __tablename__ = "core_checkpoint_v2_materialized"

    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    runtime_present: Mapped[bool] = mapped_column(nullable=False, default=False)
    runtime_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    history_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    projection_present: Mapped[bool] = mapped_column(nullable=False, default=False)
    projection_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    events_present: Mapped[bool] = mapped_column(nullable=False, default=False)
    events_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreCheckpointV2SessionMessages(CoreDbBase):
    """Checkpoint-local copy of the small session-store message list.

    These records are separate from the event projection because the legacy
    session adapter allowed UI messages to be written directly into the
    snapshot.  Keeping this list here preserves that API without copying the
    large event-derived projection into every new V2 checkpoint.
    """

    __tablename__ = "core_checkpoint_v2_session_messages"

    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    messages_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreCheckpointV2SessionHistory(CoreDbBase):
    """Exact LLM history captured at a V2 checkpoint boundary.

    Normally history can be read from ``core_history_entries`` by watermark.
    This compact boundary record also covers older/runtime-only sessions whose
    history had not yet been promoted to that table when the checkpoint was
    created.
    """

    __tablename__ = "core_checkpoint_v2_session_history"

    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    history_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class CoreCheckpointAttachmentRef(CoreDbBase):
    __tablename__ = "core_checkpoint_attachment_refs"
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attachment_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class CoreCheckpointBlobRef(CoreDbBase):
    __tablename__ = "core_checkpoint_blob_refs"
    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    blob_hash: Mapped[str] = mapped_column(String(64), primary_key=True)


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
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    work_root: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False)
    icon_key: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DEFAULT_PROJECT_ICON_KEY
    )
    color_key: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DEFAULT_PROJECT_COLOR_KEY
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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
    def __init__(
        self,
        session_factory: async_sessionmaker,
        write_coordinator: SQLiteWriteCoordinator,
        *,
        sync_journal: Any | None = None,
        sync_publisher: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator
        self._sync_journal = sync_journal
        self._sync_publisher = sync_publisher

    def set_sync_publisher(self, publisher: Callable[[dict[str, Any]], Awaitable[None]] | None) -> None:
        self._sync_publisher = publisher

    async def _publish_sync_change(self, change_id: str | None) -> None:
        if not change_id or self._sync_journal is None or self._sync_publisher is None:
            return
        change = await self._sync_journal.get_change(change_id)
        if change is not None:
            await self._sync_publisher({"method": "sync/change", "params": change})

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
        change_id = await self._save(state, history=None)
        await self._publish_sync_change(change_id)

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
        change_id = await self._save(state, history=history)
        await self._publish_sync_change(change_id)

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
                        if isinstance(msg, dict) and isinstance(msg.get("metadata"), dict):
                            msg["metadata"]["history_seq"] = i
                        db.add(
                            CoreHistoryEntry(
                                thread_id=session_id,
                                seq=i,
                                revision=i,
                                message_json=_json_safe(msg),
                            )
                        )
                    max_seq = len(row.history_json)
            for msg in messages:
                max_seq += 1
                # Tag each row with its own seq so context compaction can anchor
                # the resume boundary at the first retained message.
                if isinstance(msg, dict) and isinstance(msg.get("metadata"), dict):
                    msg["metadata"]["history_seq"] = max_seq
                db.add(
                    CoreHistoryEntry(
                        thread_id=session_id,
                        seq=max_seq,
                        revision=max_seq,
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
                # Keep row seqs in sync on every rewrite so compaction anchors
                # stay valid after truncation / loop-exit replaces renumber.
                if isinstance(msg, dict) and isinstance(msg.get("metadata"), dict):
                    msg["metadata"]["history_seq"] = i
                db.add(
                    CoreHistoryEntry(
                        thread_id=session_id,
                        seq=i,
                        revision=i,
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

    async def _save(self, state: RuntimeState, *, history: list[dict[str, Any]] | None) -> str | None:
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
                change = self._append_runtime_change(db, state, state_payload, pending_payload, now)
                return 1, change.change_id if change is not None else None

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
            change = self._append_runtime_change(db, state, state_payload, pending_payload, now)
            return next_revision, change.change_id if change is not None else None

        try:
            next_revision, change_id = await self.write_coordinator.run(write)
        except IntegrityError as exc:
            raise RuntimeStateConflictError(f"Runtime state revision conflict for {state.session_id}") from exc
        setattr(state, "_runtime_store_revision", next_revision)
        return change_id

    def _append_runtime_change(
        self,
        db: Any,
        state: RuntimeState,
        state_payload: dict[str, Any],
        pending_payload: dict[str, Any],
        now: datetime,
    ) -> Any | None:
        if self._sync_journal is None:
            return None
        entity = {
            "thread_id": state.session_id,
            **dict(state_payload),
            **dict(pending_payload),
            "updated_at": now.isoformat(),
        }
        return self._sync_journal.append(
            db,
            entity_type="runtime",
            operation="upsert",
            entity_id=state.session_id,
            thread_id=state.session_id,
            entity=entity,
        )


class SqlAlchemyHandoffContextStore:
    """Durable store for the last captured semantic model context."""

    def __init__(self, session_factory: async_sessionmaker, write_coordinator: SQLiteWriteCoordinator) -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator

    async def get(self, thread_id: str) -> dict[str, Any] | None:
        async with self.session_factory() as db:
            row = await db.get(CoreHandoffContext, thread_id)
        if row is None or not isinstance(row.context_json, dict):
            return None
        return _json_safe(row.context_json)

    async def save(self, thread_id: str, context: dict[str, Any]) -> None:
        if not thread_id:
            return
        payload = _json_safe(context)
        now = datetime.now()

        async def write(db: Any) -> None:
            row = await db.get(CoreHandoffContext, thread_id)
            if row is None:
                db.add(CoreHandoffContext(thread_id=thread_id, context_json=payload, updated_at=now))
            else:
                row.context_json = payload
                row.updated_at = now

        await self.write_coordinator.run(write)


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
            # Jobs whose lease just expired must not be re-claimed in this
            # same round — their previous owner may still be finishing
            # (audit 07 S2: same-round re-claim executed the job twice).
            expired_ids = {row.id for row in expired}
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
                        CoreArrangeJob.id.not_in(expired_ids),
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
        # Only reclaim jobs whose lease has actually expired — resetting every
        # running job would steal live work from another worker instance
        # sharing the DB (audit 07 S2: instance B startup double-ran instance
        # A's in-flight jobs).
        when = _utc_datetime(now)

        async def write(db):
            running_rows = (
                await db.execute(
                    select(CoreArrangeJob).where(
                        CoreArrangeJob.status == "running",
                        CoreArrangeJob.lease_expires_at.is_not(None),
                        CoreArrangeJob.lease_expires_at <= when,
                    )
                )
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
                .where(
                    CoreArrangeJob.status == "running",
                    CoreArrangeJob.lease_expires_at.is_not(None),
                    CoreArrangeJob.lease_expires_at <= when,
                )
                .values(
                    status="scheduled",
                    next_run_at=when,
                    lease_owner="",
                    lease_expires_at=None,
                    revision=CoreArrangeJob.revision + 1,
                    updated_at=when,
                )
                # Skip ORM session synchronization: the WHERE would be
                # Python-evaluated against the naive SQLite-read lease column
                # vs the aware `when` (TypeError) once rows are loaded in this
                # session (e.g. a test seeding an expired lease).
                .execution_options(synchronize_session=False)
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
    handoff_context_store: SqlAlchemyHandoffContextStore
    goal_store: GoalStore
    arrange_store: ArrangeStore
    project_store: CoreProjectStore
    sync_journal: Any
    workspace_id: str
    persistence: AppPersistenceHost
    memory_store: Any = None  # MemoryStoreProtocol; typed as Any to avoid import cycle
    member_defaults: dict = field(default_factory=dict)
    session_actors: SessionActorRegistry = field(default_factory=SessionActorRegistry)

    async def close(self) -> None:
        await self.engine.dispose()


async def open_core_app_db(
    path: Path | str,
    *,
    member_defaults: dict | None = None,
    workspace_id: str | None = None,
    project_roots: list[Path | str] | None = None,
    project_roots_file: Path | str | None = None,
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
        resolved_workspace_id = await _ensure_workspace_identity(conn, workspace_id)
        schema_version = await _core_schema_version(conn)
        if schema_version < CORE_SCHEMA_VERSION:
            await _migrate_core_app_schema(conn, workspace_id=resolved_workspace_id)
            await _set_core_schema_version(conn, CORE_SCHEMA_VERSION)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    write_coordinator = SQLiteWriteCoordinator(session_factory)
    from .project_store import CoreProjectStore
    from .sync_store import CoreSyncJournal
    from lamtools_core.mem.store import SqlAlchemyMemoryStore

    sync_journal = CoreSyncJournal(
        session_factory,
        write_coordinator,
        workspace_id=resolved_workspace_id,
    )
    event_store = SqlAlchemyAppEventStore(
        CoreAppEvent,
        sync_change_model=CoreSyncChange,
        workspace_id=resolved_workspace_id,
    )
    snapshot_store = SqlAlchemyThreadSnapshotStore(
        CoreThreadSnapshot,
        item_model=CoreThreadSnapshotItem,
        projector=CoreAppSnapshotProjector(),
        event_model=CoreAppEvent,
    )
    persistence = AppPersistenceHost(
        event_store,
        snapshot_store,
        session_factory=session_factory,
        write_coordinator=write_coordinator,
    )
    session_actors = SessionActorRegistry()
    return CoreAppDb(
        path=db_path,
        engine=engine,
        session_factory=session_factory,
        event_store=event_store,
        snapshot_store=snapshot_store,
        runtime_state_store=SqlAlchemyRuntimeStateStore(
            session_factory,
            write_coordinator,
            sync_journal=sync_journal,
        ),
        handoff_context_store=SqlAlchemyHandoffContextStore(session_factory, write_coordinator),
        goal_store=SqlAlchemyGoalStore(session_factory, write_coordinator),
        arrange_store=SqlAlchemyArrangeStore(session_factory, write_coordinator),
        project_store=CoreProjectStore(
            session_factory,
            write_coordinator,
            project_roots=project_roots,
            project_roots_file=project_roots_file,
            workspace_id=resolved_workspace_id,
            sync_journal=sync_journal,
        ),
        sync_journal=sync_journal,
        workspace_id=resolved_workspace_id,
        persistence=persistence,
        memory_store=SqlAlchemyMemoryStore(session_factory, write_coordinator),
        member_defaults=dict(member_defaults or {}),
        session_actors=session_actors,
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
            await db.event_store.refresh_envelopes(session, envelopes)
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


async def _ensure_workspace_identity(connection: Any, requested: str | None) -> str:
    result = await connection.execute(
        text("SELECT workspace_id FROM core_workspace_identity WHERE id = 1")
    )
    row = result.first()
    if row is not None and str(row[0] or "").strip():
        return str(row[0]).strip()
    value = str(requested or "").strip() or f"workspace_{uuid.uuid4().hex}"
    await connection.execute(
        text(
            "INSERT INTO core_workspace_identity (id, workspace_id, created_at) "
            "VALUES (1, :workspace_id, :created_at)"
        ),
        {"workspace_id": value, "created_at": datetime.now(timezone.utc)},
    )
    return value


async def _core_schema_version(connection: Any) -> int:
    value = await connection.scalar(
        select(CoreDbMetadata.value).where(CoreDbMetadata.key == "schema_version")
    )
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


async def _set_core_schema_version(connection: Any, version: int) -> None:
    await connection.execute(
        text(
            "INSERT INTO core_db_metadata (key, value, updated_at) "
            "VALUES ('schema_version', :value, :updated_at) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at"
        ),
        {"value": str(version), "updated_at": datetime.now()},
    )


async def _migrate_core_app_schema(connection: Any, *, workspace_id: str = "") -> None:
    app_event_columns = {
        row["name"]
        for row in (await connection.execute(text("PRAGMA table_info(core_app_events)"))).mappings()
    }
    app_event_additions = {
        "workspace_id": "VARCHAR(128) NOT NULL DEFAULT ''",
        "entity_type": "VARCHAR(64) NOT NULL DEFAULT 'thread.event'",
        "entity_id": "VARCHAR(256) NOT NULL DEFAULT ''",
        "event_seq": "INTEGER NOT NULL DEFAULT 0",
        "revision": "INTEGER NOT NULL DEFAULT 0",
        "event_type": "VARCHAR(128) NOT NULL DEFAULT ''",
    }
    for column, definition in app_event_additions.items():
        if column not in app_event_columns:
            await connection.execute(text(
                f"ALTER TABLE core_app_events ADD COLUMN {column} {definition}"
            ))
    # Backfill compatibility rows created before the canonical envelope was
    # introduced.  The identity is already resolved before this migration so
    # old events cannot remain invisible to Local-First sync.
    if workspace_id:
        await connection.execute(text(
            "UPDATE core_app_events SET workspace_id = :workspace_id "
            "WHERE workspace_id = '' OR workspace_id IS NULL"
        ), {"workspace_id": workspace_id})
    await connection.execute(text(
        "UPDATE core_app_events SET entity_id = thread_id "
        "WHERE entity_id = '' OR entity_id IS NULL"
    ))
    await connection.execute(text(
        "UPDATE core_app_events SET event_seq = seq WHERE event_seq = 0 OR event_seq IS NULL"
    ))
    await connection.execute(text(
        "UPDATE core_app_events SET event_type = method "
        "WHERE event_type = '' OR event_type IS NULL"
    ))

    snapshot_columns = {
        row["name"]
        for row in (await connection.execute(text("PRAGMA table_info(core_thread_snapshots)"))).mappings()
    }
    if "revision" not in snapshot_columns:
        await connection.execute(text(
            "ALTER TABLE core_thread_snapshots ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
        ))
        # Existing snapshots already have a monotonic event anchor.  Using it
        # as the initial revision preserves optimistic-concurrency safety on
        # upgraded databases without inventing a lower revision than clients
        # may have cached.
        await connection.execute(text(
            "UPDATE core_thread_snapshots SET revision = snapshot_seq "
            "WHERE revision = 0 AND snapshot_seq > 0"
        ))
    active_turn_index_added = "active_turn_id" not in snapshot_columns
    if active_turn_index_added:
        await connection.execute(text(
            "ALTER TABLE core_thread_snapshots ADD COLUMN active_turn_id VARCHAR(64)"
        ))
    await connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_core_thread_snapshots_active_turn_id "
        "ON core_thread_snapshots (active_turn_id)"
    ))
    if active_turn_index_added:
        # Upgrade-only compatibility pass. Runtime writes maintain this lookup
        # column incrementally; old databases pay the JSON scan exactly once.
        from .queue_state import latest_active_turn_id

        rows = (
            await connection.execute(text(
                "SELECT thread_id, snapshot_json FROM core_thread_snapshots"
            ))
        ).mappings().all()
        for row in rows:
            payload = row["snapshot_json"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    payload = {}
            active_turn_id = latest_active_turn_id(payload if isinstance(payload, dict) else {})
            if active_turn_id:
                await connection.execute(
                    text(
                        "UPDATE core_thread_snapshots SET active_turn_id = :active_turn_id "
                        "WHERE thread_id = :thread_id"
                    ),
                    {"active_turn_id": active_turn_id, "thread_id": row["thread_id"]},
                )

    project_columns = {
        row["name"]
        for row in (await connection.execute(text("PRAGMA table_info(core_projects)"))).mappings()
    }
    if "workspace_id" not in project_columns:
        await connection.execute(text(
            "ALTER TABLE core_projects ADD COLUMN workspace_id VARCHAR(128) NOT NULL DEFAULT ''"
        ))
    if "revision" not in project_columns:
        await connection.execute(text(
            "ALTER TABLE core_projects ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
        ))
    if "icon_key" not in project_columns:
        await connection.execute(text(
            "ALTER TABLE core_projects ADD COLUMN icon_key VARCHAR(32) NOT NULL DEFAULT 'folder'"
        ))
    if "color_key" not in project_columns:
        await connection.execute(text(
            "ALTER TABLE core_projects ADD COLUMN color_key VARCHAR(32) NOT NULL DEFAULT 'gray'"
        ))
    await connection.execute(text(
        "UPDATE core_projects SET icon_key = :icon_key WHERE icon_key = '' OR icon_key IS NULL"
    ), {"icon_key": DEFAULT_PROJECT_ICON_KEY})
    await connection.execute(text(
        "UPDATE core_projects SET color_key = :color_key WHERE color_key = '' OR color_key IS NULL"
    ), {"color_key": DEFAULT_PROJECT_COLOR_KEY})
    if workspace_id:
        await connection.execute(text(
            "UPDATE core_projects SET workspace_id = :workspace_id "
            "WHERE workspace_id = '' OR workspace_id IS NULL"
        ), {"workspace_id": workspace_id})

    history_columns = {
        row["name"]
        for row in (await connection.execute(text("PRAGMA table_info(core_history_entries)"))).mappings()
    }
    if "revision" not in history_columns:
        await connection.execute(text(
            "ALTER TABLE core_history_entries ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
        ))
    # History entries are append-only. Their sequence is a deterministic
    # revision for upgraded rows and for rows created by older checkpoint
    # restore code that did not know about the column yet.
    await connection.execute(text(
        "UPDATE core_history_entries SET revision = seq "
        "WHERE revision = 0 OR revision IS NULL"
    ))

    sync_columns = {
        row["name"]
        for row in (await connection.execute(text("PRAGMA table_info(core_sync_changes)"))).mappings()
    }
    if "workspace_id" not in sync_columns:
        await connection.execute(text(
            "ALTER TABLE core_sync_changes ADD COLUMN workspace_id VARCHAR(128) NOT NULL DEFAULT ''"
        ))
    if "event_type" not in sync_columns:
        await connection.execute(text(
            "ALTER TABLE core_sync_changes ADD COLUMN event_type VARCHAR(128) NOT NULL DEFAULT ''"
        ))
    if "revision" not in sync_columns:
        await connection.execute(text(
            "ALTER TABLE core_sync_changes ADD COLUMN revision INTEGER NOT NULL DEFAULT 0"
        ))
    if workspace_id:
        await connection.execute(text(
            "UPDATE core_sync_changes SET workspace_id = :workspace_id "
            "WHERE workspace_id = '' OR workspace_id IS NULL"
        ), {"workspace_id": workspace_id})
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
        # SQLite refuses to drop an indexed column — the historical model
        # declared project_id with index=True (audit 04 S2: old databases
        # failed to open after upgrade).
        await connection.execute(text("DROP INDEX IF EXISTS ix_core_arrange_jobs_project_id"))
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
    "CoreHandoffContext",
    "CoreProject",
    "CoreSyncChange",
    "CoreWorkspaceIdentity",
    "CoreRestoreOperation",
    "CoreRuntimeSession",
    "CoreThreadSnapshot",
    "CoreThreadSnapshotItem",
    "CoreWorkspaceManifest",
    "RuntimeStateConflictError",
    "SqlAlchemyRuntimeStateStore",
    "SqlAlchemyHandoffContextStore",
    "SqlAlchemyArrangeStore",
    "SqlAlchemyGoalStore",
    "list_core_sessions",
    "open_core_app_db",
    "persist_core_run_items",
    "show_core_session",
]
