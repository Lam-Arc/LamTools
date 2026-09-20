"""Session resource adapter backed by the Core thread snapshot directory."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy import delete, select

from lamtools_core.session import MessageRecord, SessionRecord

from .core_db import (
    CoreAppDb, CoreAppEvent, CoreAttachment, CoreArrangeJob, CoreArrangeOccurrence,
    CoreCheckpoint, CoreCheckpointAttachmentRef, CoreCheckpointBlobRef, CoreCheckpointV2,
    CoreCheckpointV2Materialized,
    CoreCheckpointV2SessionMessages,
    CoreCheckpointV2SessionHistory,
    CoreGoal, CoreHandoffContext, CoreHistoryEntry, CoreRestoreOperation, CoreRuntimeSession,
    CoreProject, CoreThreadSnapshot, CoreThreadSnapshotItem, CoreWorkspaceManifest,
)
from .session_autotitle import is_default_title
from .snapshot_store import CoreAppSnapshotProjector
from .runtime_permissions import (
    merge_session_runtime_preferences,
    session_runtime_preferences,
    with_session_runtime_preferences,
)


class CoreDbSessionStore:
    def __init__(
        self,
        db_provider: Callable[[], CoreAppDb],
        *,
        session_visible: Callable[[str, dict[str, Any]], bool] | None = None,
        sync_publisher: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        fallback_work_root: Path | str | None = None,
    ) -> None:
        self._db_provider = db_provider
        self._session_visible = session_visible or (lambda _session_id, _metadata: True)
        self._sync_journal: Any = None
        self._sync_publisher = sync_publisher
        self._runtime_preferences_by_session: dict[str, dict[str, Any]] = {}
        self._fallback_work_root = (
            str(Path(fallback_work_root).expanduser().resolve())
            if fallback_work_root is not None
            else ""
        )

    def set_sync_journal(self, sync_journal: Any) -> None:
        self._sync_journal = sync_journal

    def set_sync_publisher(self, publisher: Callable[[dict[str, Any]], Awaitable[None]] | None) -> None:
        self._sync_publisher = publisher

    def runtime_preferences(self, session_id: str) -> dict[str, Any] | None:
        """Return the latest cached session permission state synchronously.

        Running toolboxes use this read path before each tool decision.  The
        cache is refreshed by every session-store read/write, while the
        durable session metadata remains the source of truth.
        """
        value = self._runtime_preferences_by_session.get(session_id)
        return dict(value) if value is not None else None

    def _remember_runtime_preferences(self, session: SessionRecord) -> None:
        self._runtime_preferences_by_session[session.id] = session_runtime_preferences(
            session.metadata
        )

    async def _publish_sync_changes(self, change_ids: list[str]) -> None:
        if self._sync_journal is None or self._sync_publisher is None:
            return
        for change_id in change_ids:
            change = await self._sync_journal.get_change(change_id)
            if change is not None:
                await self._sync_publisher({"method": "sync/change", "params": change})

    def _is_visible(self, session_id: str, metadata: dict[str, Any]) -> bool:
        try:
            return bool(self._session_visible(session_id, metadata))
        except Exception:  # noqa: BLE001 — unavailable plugin sessions stay isolated
            # A broken visibility resolver must not leak a plugin-owned
            # resource into the generic chat surface. Regular sessions remain
            # usable so a plugin discovery failure cannot hide Core itself.
            return not bool(str(metadata.get("owner_plugin") or "").strip())

    def _row_is_visible(self, row: CoreThreadSnapshot) -> bool:
        return self._is_visible(str(row.thread_id), _session_metadata(row.snapshot_json))

    async def create(self, session: SessionRecord) -> SessionRecord:
        db = self._db_provider()
        if not self._is_visible(session.id, session.metadata):
            raise ValueError("Session owner plugin is disabled or unavailable")
        # Trusted plugin resources may explicitly own a global conversation.
        # Ordinary Agent sessions retain the existing fallback-project rule.
        project_independent = bool(session.metadata.get("owner_plugin")) and session.metadata.get("project_independent") is True
        if self._fallback_work_root and not project_independent:
            requested_root = str(session.metadata.get("work_root") or "").strip()
            project_exists = False
            if requested_root:
                async with db.session_factory() as connection:
                    project_exists = await connection.scalar(
                        select(CoreProject.id).where(CoreProject.work_root == requested_root)
                    ) is not None
            if not project_exists:
                await db.project_store.ensure_fallback_project(
                    self._fallback_work_root,
                    name="MyProject",
                )
                session.metadata = {**session.metadata, "work_root": self._fallback_work_root}
        session.metadata = with_session_runtime_preferences(session.metadata)

        change_ids: list[str] = []

        async def write(connection):
            change_ids.clear()
            if await connection.get(CoreThreadSnapshot, session.id) is not None:
                raise ValueError(f"Session '{session.id}' already exists")
            state = session_snapshot(session, projector=db.snapshot_store.projector)
            connection.add(
                CoreThreadSnapshot(
                    thread_id=session.id,
                    snapshot_seq=0,
                    snapshot_json=state,
                    updated_at=session.updated_at,
                )
            )
            if self._sync_journal is not None:
                change = self._sync_journal.append(
                    connection,
                    entity_type="thread",
                    operation="upsert",
                    entity_id=session.id,
                    thread_id=session.id,
                    revision=int(state.get("revision") or 0),
                    entity=_thread_entity(session, state),
                )
                change_ids.append(change.change_id)
            await connection.flush()

        await db.persistence.write(write)
        self._remember_runtime_preferences(session)
        await self._publish_sync_changes(change_ids)
        return session

    async def get(self, session_id: str) -> SessionRecord | None:
        db = self._db_provider()
        async with db.session_factory() as connection:
            row = await connection.get(CoreThreadSnapshot, session_id)
            if row is None:
                return None
            if not self._row_is_visible(row):
                return None
            record = session_record_from_snapshot(row)
        if "runtime_preferences" in record.metadata:
            self._remember_runtime_preferences(record)
            return record

        # Keep the common read path read-only. Legacy snapshots are
        # canonicalized once, after the connection is closed, so a GET does
        # not unnecessarily acquire the SQLite write coordinator.
        record.metadata = with_session_runtime_preferences(record.metadata)
        await _persist_legacy_runtime_preferences(db, record)
        self._remember_runtime_preferences(record)
        return record

    async def list(self, member_id: str | None = None) -> list[SessionRecord]:
        db = self._db_provider()
        async with db.session_factory() as connection:
            rows = (
                await connection.execute(
                    select(CoreThreadSnapshot).order_by(CoreThreadSnapshot.updated_at.desc())
                )
            ).scalars().all()
        records = [
            session_record_from_snapshot(row)
            for row in rows
            if self._row_is_visible(row)
        ]
        legacy_fork_records = _inherit_legacy_fork_project_metadata(records)
        if legacy_fork_records:
            await _persist_legacy_fork_project_metadata(db, *legacy_fork_records)
        legacy_records = [record for record in records if "runtime_preferences" not in record.metadata]
        for record in legacy_records:
            record.metadata = with_session_runtime_preferences(record.metadata)
        if legacy_records:
            await _persist_legacy_runtime_preferences(db, *legacy_records)
        for record in records:
            self._remember_runtime_preferences(record)
        return [record for record in records if member_id is None or record.member_id == member_id]

    async def update(self, session: SessionRecord, *, expected_revision: int | None = None) -> SessionRecord:
        db = self._db_provider()
        if not self._is_visible(session.id, session.metadata):
            raise KeyError(session.id)
        session.updated_at = datetime.now()

        change_ids: list[str] = []

        async def write(connection):
            change_ids.clear()
            row = await connection.get(CoreThreadSnapshot, session.id)
            if row is None:
                raise KeyError(session.id)
            if not self._row_is_visible(row):
                raise KeyError(session.id)
            existing = session_record_from_snapshot(row)
            current_revision = _snapshot_revision(row)
            await db.persistence.assert_revision(connection, session.id, expected_revision)
            session.metadata = _canonicalize_project_metadata(existing.metadata, session.metadata)
            session.metadata = merge_session_runtime_preferences(existing.metadata, session.metadata)
            state = dict(row.snapshot_json or {})
            state.update(_session_state(session, messages=state.get("messages")))
            state["revision"] = current_revision + 1
            row.snapshot_json = state
            if hasattr(row, "revision"):
                row.revision = current_revision + 1
            row.updated_at = session.updated_at
            if self._sync_journal is not None:
                change = self._sync_journal.append(
                    connection,
                    entity_type="thread",
                    operation="upsert",
                    entity_id=session.id,
                    thread_id=session.id,
                    revision=current_revision + 1,
                    entity=_thread_entity(session, state),
                )
                change_ids.append(change.change_id)
            await connection.flush()

        await db.persistence.write(write)
        self._remember_runtime_preferences(session)
        await self._publish_sync_changes(change_ids)
        return session

    async def patch(
        self,
        session_id: str,
        *,
        title: str | None = None,
        status: str | None = None,
        metadata: dict | None = None,
        only_if_title_default: bool = False,
        expected_revision: int | None = None,
    ) -> SessionRecord | None:
        db = self._db_provider()
        change_ids: list[str] = []

        async def write(connection):
            change_ids.clear()
            row = await connection.get(CoreThreadSnapshot, session_id)
            if row is None:
                return None
            if not self._row_is_visible(row):
                return None
            record = session_record_from_snapshot(row)
            current_revision = _snapshot_revision(row)
            if (
                only_if_title_default
                and title is not None
                and not is_default_title(record.title, session_id=session_id)
            ):
                # The title was set (e.g. renamed manually) since the caller's
                # earlier guard check — skip the write instead of clobbering it.
                # Returning None is indistinguishable from a missing row, which
                # is exactly what callers need: nothing was updated.
                return None
            await db.persistence.assert_revision(connection, session_id, expected_revision)
            if title is not None:
                record.title = title
            if status is not None:
                record.status = status
            if metadata is not None:
                record.metadata = _canonicalize_project_metadata(record.metadata, metadata)
                record.metadata = merge_session_runtime_preferences(record.metadata, metadata)
            record.updated_at = datetime.now()
            state = dict(row.snapshot_json or {})
            state.update(_session_state(record, messages=state.get("messages")))
            state["revision"] = current_revision + 1
            row.snapshot_json = state
            if hasattr(row, "revision"):
                row.revision = current_revision + 1
            row.updated_at = record.updated_at
            if self._sync_journal is not None:
                change = self._sync_journal.append(
                    connection,
                    entity_type="thread",
                    operation="upsert",
                    entity_id=session_id,
                    thread_id=session_id,
                    revision=current_revision + 1,
                    entity=_thread_entity(record, state),
                )
                change_ids.append(change.change_id)
            await connection.flush()
            return record

        result = await db.persistence.write(write)
        if result is not None:
            self._remember_runtime_preferences(result)
        await self._publish_sync_changes(change_ids)
        return result

    async def delete(self, session_id: str, *, expected_revision: int | None = None) -> bool:
        db = self._db_provider()
        change_ids: list[str] = []

        async def write(connection):
            change_ids.clear()
            row = await connection.get(CoreThreadSnapshot, session_id)
            if row is None:
                return False
            if not self._row_is_visible(row):
                return False
            current_revision = _snapshot_revision(row)
            await db.persistence.assert_revision(connection, session_id, expected_revision)
            if self._sync_journal is not None:
                change = self._sync_journal.append(
                    connection,
                    entity_type="thread",
                    operation="delete",
                    entity_id=session_id,
                    thread_id=session_id,
                    revision=current_revision + 1,
                    entity={"id": session_id, "deleted": True},
                )
                change_ids.append(change.change_id)
            await delete_session_records(connection, [session_id])
            return True

        result = bool(await db.persistence.write(write))
        if result:
            self._runtime_preferences_by_session.pop(session_id, None)
        await self._publish_sync_changes(change_ids)
        return result

    async def add_message(self, message: MessageRecord, *, expected_revision: int | None = None) -> MessageRecord:
        db = self._db_provider()
        change_ids: list[str] = []

        async def write(connection):
            change_ids.clear()
            row = await connection.get(CoreThreadSnapshot, message.session_id)
            if row is None:
                raise KeyError(message.session_id)
            if not self._row_is_visible(row):
                raise KeyError(message.session_id)
            current_revision = _snapshot_revision(row)
            await db.persistence.assert_revision(connection, message.session_id, expected_revision)
            state = dict(row.snapshot_json or {})
            messages = list(state.get("messages") or [])
            messages.append(message.to_dict())
            state["messages"] = messages
            state["revision"] = current_revision + 1
            row.snapshot_json = state
            if hasattr(row, "revision"):
                row.revision = current_revision + 1
            row.updated_at = datetime.now()
            if self._sync_journal is not None:
                change = self._sync_journal.append(
                    connection,
                    entity_type="message",
                    operation="upsert",
                    entity_id=message.id,
                    thread_id=message.session_id,
                    entity={
                        "id": message.id,
                        "thread_id": message.session_id,
                        "seq": int(message.metadata.get("history_seq") or 0),
                        "message": message.to_dict(),
                        "deleted": False,
                    },
                    revision=current_revision + 1,
                )
                change_ids.append(change.change_id)
            await connection.flush()

        await db.persistence.write(write)
        await self._publish_sync_changes(change_ids)
        return message

    async def list_messages(self, session_id: str) -> list[MessageRecord]:
        db = self._db_provider()
        async with db.session_factory() as connection:
            row = await connection.get(CoreThreadSnapshot, session_id)
        if row is None:
            return []
        if not self._row_is_visible(row):
            return []
        raw_messages = (row.snapshot_json or {}).get("messages") or []
        records = [_message_from_dict(item) for item in raw_messages if isinstance(item, dict)]
        return sorted(records, key=lambda item: item.created_at)


def _session_state(session: SessionRecord, *, messages=None) -> dict:
    state = {
        "thread_id": session.id,
        "status": session.status,
        "session": {
            "member_id": session.member_id,
            "title": session.title,
            "metadata": session.metadata,
            "created_at": session.created_at.isoformat(),
        },
    }
    if messages is not None:
        state["messages"] = messages
    return state


def _thread_entity(session: SessionRecord, state: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "metadata": dict(session.metadata),
        "project_id": session.metadata.get("project_id"),
        "revision": int(state.get("revision") or 0),
        "snapshot": state,
        "deleted": False,
    }


def _session_metadata(snapshot: object) -> dict[str, Any]:
    """Extract metadata without materializing the session resource.

    Plugin-owned sessions must be gated before runtime-preference migration or
    any other normal session hydration is attempted.
    """
    state = snapshot if isinstance(snapshot, dict) else {}
    session = state.get("session") if isinstance(state.get("session"), dict) else {}
    metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    return dict(metadata)


def _inherit_legacy_fork_project_metadata(records: list[SessionRecord]) -> list[SessionRecord]:
    """Resolve ownership and default titles for pre-inheritance forks."""
    records_by_id = {record.id: record for record in records}
    repaired: list[SessionRecord] = []
    unresolved = [
        record for record in records
        if not str(record.metadata.get("work_root") or "")
        and str(record.metadata.get("forked_from_session_id") or "")
    ]
    for _ in range(len(unresolved)):
        changed = False
        for record in list(unresolved):
            parent_id = str(record.metadata.get("forked_from_session_id") or "")
            parent = records_by_id.get(parent_id)
            work_root = str(parent.metadata.get("work_root") or "") if parent else ""
            if not work_root:
                continue
            record.metadata = {**record.metadata, "work_root": work_root}
            project_id = parent.metadata.get("project_id") if parent else None
            if project_id:
                record.metadata["project_id"] = project_id
            legacy_titles = {f"{parent_id} fork", f"{parent.title} fork"}
            if record.title in legacy_titles:
                base = str(parent.metadata.get("fork_title_base") or parent.title).strip()
                used_numbers: set[int] = set()
                prefix = f"{base}（"
                for candidate in records:
                    candidate_root = str(candidate.metadata.get("work_root") or "")
                    candidate_title = str(candidate.title or "")
                    if candidate_root != work_root or not candidate_title.startswith(prefix):
                        continue
                    suffix = candidate_title[len(prefix):]
                    if suffix.endswith("）") and suffix[:-1].isdigit():
                        used_numbers.add(int(suffix[:-1]))
                record.title = f"{base}（{max(used_numbers, default=0) + 1}）"
                record.metadata["fork_title_base"] = base
            repaired.append(record)
            unresolved.remove(record)
            changed = True
        if not changed:
            break
    return repaired


async def _persist_legacy_fork_project_metadata(
    db: CoreAppDb,
    *records: SessionRecord,
) -> None:
    """Persist inferred project ownership once for legacy orphan forks."""
    canonical = {
        record.id: {
            "title": record.title,
            "metadata": {
                key: record.metadata[key]
                for key in ("work_root", "project_id", "fork_title_base")
                if key in record.metadata
            },
        }
        for record in records
        if str(record.metadata.get("work_root") or "")
    }
    if not canonical:
        return

    async def write(connection):
        for session_id, inherited in canonical.items():
            row = await connection.get(CoreThreadSnapshot, session_id)
            if row is None:
                continue
            state = dict(row.snapshot_json or {})
            session_state = dict(state.get("session") or {})
            metadata = dict(session_state.get("metadata") or {})
            if str(metadata.get("work_root") or ""):
                continue
            metadata.update(inherited["metadata"])
            session_state["title"] = inherited["title"]
            session_state["metadata"] = metadata
            state["session"] = session_state
            row.snapshot_json = state
            row.updated_at = datetime.now()
        await connection.flush()

    await db.persistence.write(write)


async def _persist_legacy_runtime_preferences(db: CoreAppDb, *records: SessionRecord) -> None:
    """Persist preferences inferred for pre-runtime-preferences sessions.

    The caller has already materialized the canonical values from the first
    read. The write transaction only fills the missing block and preserves a
    concurrent update that has already supplied one.
    """
    if not records:
        return
    canonical = {
        record.id: dict(record.metadata)
        for record in records
        if "runtime_preferences" in record.metadata
    }
    if not canonical:
        return

    async def write(connection):
        for session_id, metadata in canonical.items():
            row = await connection.get(CoreThreadSnapshot, session_id)
            if row is None:
                continue
            current = session_record_from_snapshot(row)
            if "runtime_preferences" in current.metadata:
                continue
            current.metadata = {
                **current.metadata,
                "runtime_preferences": metadata["runtime_preferences"],
            }
            state = dict(row.snapshot_json or {})
            session_state = dict(state.get("session") or {})
            session_state["metadata"] = current.metadata
            state["session"] = session_state
            row.snapshot_json = state
            row.updated_at = datetime.now()
        await connection.flush()

    await db.persistence.write(write)


def _canonicalize_project_metadata(existing: dict, requested: dict) -> dict:
    work_root = existing.get("work_root")
    if not isinstance(work_root, str) or not work_root:
        if "work_root" in requested:
            raise ValueError("Use the project session endpoint for project-owned sessions")
        return dict(requested)
    metadata = dict(requested)
    metadata["work_root"] = str(work_root)
    return metadata


def session_snapshot(
    session: SessionRecord,
    *,
    projector: CoreAppSnapshotProjector | None = None,
) -> dict:
    session.metadata = with_session_runtime_preferences(session.metadata)
    state = (projector or CoreAppSnapshotProjector()).empty(session.id)
    state.update(_session_state(session))
    state.setdefault("revision", 0)
    return state


async def delete_session_records(connection, session_ids: list[str]) -> None:
    if not session_ids:
        return
    # Session ids own their sub-agent descendants as well.  This keeps the
    # deletion operation closed over the session family even though the legacy
    # schema has no foreign keys.
    root_ids = {str(item) for item in session_ids if str(item)}
    owned_ids = set(root_ids)
    # Older runs can leave history/snapshot rows after their runtime row has
    # already disappeared.  Discover the complete family from every table
    # carrying a session id so deletion is closed even without runtime rows.
    family_queries = (
        select(CoreRuntimeSession.thread_id),
        select(CoreAppEvent.thread_id),
        select(CoreHistoryEntry.thread_id),
        select(CoreThreadSnapshotItem.thread_id),
        select(CoreThreadSnapshot.thread_id),
        select(CoreAttachment.session_id),
        select(CoreGoal.thread_id),
        select(CoreHandoffContext.thread_id),
    )
    for query in family_queries:
        result = await connection.execute(query)
        owned_ids.update(
            str(value)
            for (value,) in result.all()
            if value is not None
            and any(str(value) == root or str(value).startswith(root + ":sub:") for root in root_ids)
        )
    attachment_rows = list((await connection.execute(
        select(CoreAttachment.storage_path).where(CoreAttachment.session_id.in_(owned_ids))
    )).all())
    await connection.execute(delete(CoreAppEvent).where(CoreAppEvent.thread_id.in_(owned_ids)))
    await connection.execute(delete(CoreHistoryEntry).where(CoreHistoryEntry.thread_id.in_(owned_ids)))
    await connection.execute(delete(CoreHandoffContext).where(CoreHandoffContext.thread_id.in_(owned_ids)))
    await connection.execute(delete(CoreRuntimeSession).where(CoreRuntimeSession.thread_id.in_(owned_ids)))
    await connection.execute(delete(CoreThreadSnapshotItem).where(CoreThreadSnapshotItem.thread_id.in_(owned_ids)))
    await connection.execute(delete(CoreThreadSnapshot).where(CoreThreadSnapshot.thread_id.in_(owned_ids)))
    checkpoint_ids = select(CoreCheckpoint.id).where(CoreCheckpoint.root_session_id.in_(owned_ids))
    await connection.execute(delete(CoreCheckpointAttachmentRef).where(CoreCheckpointAttachmentRef.checkpoint_id.in_(checkpoint_ids)))
    await connection.execute(delete(CoreCheckpointBlobRef).where(CoreCheckpointBlobRef.checkpoint_id.in_(checkpoint_ids)))
    await connection.execute(delete(CoreCheckpointV2SessionMessages).where(
        CoreCheckpointV2SessionMessages.checkpoint_id.in_(checkpoint_ids)
    ))
    await connection.execute(delete(CoreCheckpointV2SessionHistory).where(
        CoreCheckpointV2SessionHistory.checkpoint_id.in_(checkpoint_ids)
    ))
    await connection.execute(delete(CoreCheckpointV2Materialized).where(
        CoreCheckpointV2Materialized.checkpoint_id.in_(checkpoint_ids)
    ))
    await connection.execute(delete(CoreCheckpointV2).where(CoreCheckpointV2.root_session_id.in_(owned_ids)))
    await connection.execute(delete(CoreCheckpoint).where(CoreCheckpoint.root_session_id.in_(owned_ids)))
    await connection.execute(delete(CoreRestoreOperation).where(CoreRestoreOperation.root_session_id.in_(owned_ids)))
    await connection.execute(delete(CoreAttachment).where(CoreAttachment.session_id.in_(owned_ids)))
    await connection.execute(delete(CoreGoal).where(CoreGoal.thread_id.in_(owned_ids)))
    await connection.execute(delete(CoreArrangeOccurrence).where(CoreArrangeOccurrence.job_id.in_(select(CoreArrangeJob.id).where(CoreArrangeJob.thread_id.in_(owned_ids)))))
    await connection.execute(delete(CoreArrangeJob).where(CoreArrangeJob.thread_id.in_(owned_ids)))
    for (storage_path,) in attachment_rows:
        if not storage_path:
            continue
        try:
            Path(str(storage_path)).unlink(missing_ok=True)
        except OSError:
            # Database ownership is still removed; a missing/unremovable blob
            # is an operational cleanup warning, not a reason to resurrect a
            # deleted session.
            continue


def session_record_from_snapshot(row: CoreThreadSnapshot) -> SessionRecord:
    state = dict(row.snapshot_json or {})
    session = state.get("session") if isinstance(state.get("session"), dict) else {}
    updated_at = row.updated_at or datetime.now()
    return SessionRecord(
        id=str(row.thread_id),
        member_id=str(session.get("member_id") or "core"),
        title=str(session.get("title") or row.thread_id),
        status=str(state.get("status") or "idle"),
        metadata=dict(session.get("metadata") or {}),
        created_at=_datetime(session.get("created_at"), fallback=updated_at),
        updated_at=updated_at,
    )


def _snapshot_revision(row: CoreThreadSnapshot) -> int:
    value = getattr(row, "revision", None)
    if value is None:
        state = row.snapshot_json if isinstance(getattr(row, "snapshot_json", None), dict) else {}
        value = state.get("revision", 0)
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _message_from_dict(value: dict) -> MessageRecord:
    return MessageRecord(
        id=str(value.get("id") or ""),
        session_id=str(value.get("session_id") or ""),
        role=str(value.get("role") or ""),
        content=str(value.get("content") or ""),
        parts=list(value.get("parts") or []),
        metadata=dict(value.get("metadata") or {}),
        created_at=_datetime(value.get("created_at"), fallback=datetime.now()),
    )


def _datetime(value, *, fallback: datetime) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return fallback


__all__ = [
    "CoreDbSessionStore",
    "delete_session_records",
    "session_record_from_snapshot",
    "session_snapshot",
]
