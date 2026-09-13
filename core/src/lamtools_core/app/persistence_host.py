"""Coordinates app-event persistence with thread snapshot projection."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Iterable, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from lamtools_core.event import RunItemEvent

from .event_store import AppEventEnvelope, AppEventInput, SqlAlchemyAppEventStore
from .snapshot_store import SqlAlchemyThreadSnapshotStore
from .sqlite_write import SQLiteWriteCoordinator, database_identity


T = TypeVar("T")
WriteCoordinatorFactory = Callable[[Any], SQLiteWriteCoordinator]


class RevisionConflictError(RuntimeError):
    """Raised when a mutation was based on an outdated session revision."""

    def __init__(self, *, thread_id: str, expected_revision: int, current_revision: int) -> None:
        self.thread_id = str(thread_id)
        self.expected_revision = int(expected_revision)
        self.current_revision = int(current_revision)
        super().__init__(
            f"Revision conflict for {self.thread_id}: "
            f"expected {self.expected_revision}, current {self.current_revision}"
        )

    @property
    def data(self) -> dict[str, int | str]:
        return {
            "code": "REVISION_CONFLICT",
            "thread_id": self.thread_id,
            "expected_revision": self.expected_revision,
            "current_revision": self.current_revision,
        }


class AppPersistenceHost:
    """Persists events and applies their projections without committing a transaction."""

    def __init__(
        self,
        event_store: SqlAlchemyAppEventStore,
        snapshot_store: SqlAlchemyThreadSnapshotStore,
        *,
        session_factory: Any | None = None,
        write_coordinator: SQLiteWriteCoordinator | None = None,
        write_coordinator_factory: WriteCoordinatorFactory | None = None,
    ) -> None:
        self.event_store = event_store
        self.snapshot_store = snapshot_store
        self._write_coordinator_factory = write_coordinator_factory
        self._write_coordinator = write_coordinator
        if self._write_coordinator is None and session_factory is not None:
            self._write_coordinator = self._new_write_coordinator(session_factory)

    @property
    def write_coordinator(self) -> SQLiteWriteCoordinator | None:
        return self._write_coordinator

    def bind_session_factory(self, session_factory: Any) -> None:
        if (
            self._write_coordinator is None
            or self._write_coordinator.identity != database_identity(session_factory)
        ):
            self._write_coordinator = self._new_write_coordinator(session_factory)

    def _new_write_coordinator(self, session_factory: Any) -> SQLiteWriteCoordinator:
        if self._write_coordinator_factory is not None:
            return self._write_coordinator_factory(session_factory)
        return SQLiteWriteCoordinator(session_factory)

    async def write(self, action: Callable[[AsyncSession], Awaitable[T]]) -> T:
        if self._write_coordinator is None:
            raise RuntimeError("AppPersistenceHost requires a session factory for writes")
        return await self._write_coordinator.run(action)

    async def _refresh_envelopes(
        self,
        db: AsyncSession,
        envelopes: list[AppEventEnvelope],
    ) -> list[AppEventEnvelope]:
        """Refresh store-owned fields when the event store supports it.

        The production SQLAlchemy store reloads rows after projection so fields
        such as the canonical revision are returned to callers.  Keeping the
        fallback here makes the persistence host usable with small in-memory
        or test doubles that already return complete envelopes.
        """

        refresh = getattr(self.event_store, "refresh_envelopes", None)
        if not callable(refresh):
            return envelopes
        return await refresh(db, envelopes)

    async def append(self, db: AsyncSession, event: AppEventInput) -> AppEventEnvelope:
        async with db.begin_nested():
            envelope = await self._append(db, event)
            refreshed = await self._refresh_envelopes(db, [envelope])
            return refreshed[0]

    async def append_run_item(self, db: AsyncSession, event: RunItemEvent) -> AppEventEnvelope:
        async with db.begin_nested():
            envelope = await self.event_store.append_run_item_event(db, event)
            await self.apply(db, envelope)
            refreshed = await self._refresh_envelopes(db, [envelope])
            return refreshed[0]

    async def append_many(
        self,
        db: AsyncSession,
        events: Iterable[AppEventInput],
        *,
        expected_revision: int | None = None,
        revision_thread_id: str | None = None,
    ) -> list[AppEventEnvelope]:
        app_events = list(events)
        if not app_events:
            return []
        return await self.append_batch(
            db,
            app_events=app_events,
            expected_revision=expected_revision,
            revision_thread_id=revision_thread_id,
        )

    async def append_batch(
        self,
        db: AsyncSession,
        *,
        app_events: Iterable[AppEventInput] = (),
        run_item_events: Iterable[RunItemEvent] = (),
        return_state: bool = False,
        project_snapshot: bool = True,
        expected_revision: int | None = None,
        revision_thread_id: str | None = None,
    ) -> list[AppEventEnvelope] | tuple[list[AppEventEnvelope], dict[str, Any] | None]:
        """Append multiple events in one savepoint with a single batch projection.

        With ``project_snapshot=False`` events are appended to the event table
        only; the thread snapshot is NOT projected. Streaming emits many
        low-frequency state events (part start/end, status, usage) while a turn
        is running — projecting the full thread snapshot for each one costs
        1.3-2.3s on 55MB threads (measured) and stalls the stream. The snapshot
        is projected once at the turn boundary instead; clients keep rendering
        from the runItem event stream in the meantime.
        """
        app_event_list = list(app_events)
        run_item_list = list(run_item_events)
        if not app_event_list and not run_item_list:
            if return_state:
                return [], None
            return []
        async with db.begin_nested():
            if expected_revision is not None:
                target_thread_id = revision_thread_id or (
                    app_event_list[0].thread_id if app_event_list else run_item_list[0].thread_id
                )
                await self.assert_revision(db, target_thread_id, expected_revision)
            envelopes: list[AppEventEnvelope] = []
            for event in app_event_list:
                envelope = await self.event_store.append(db, event)
                envelopes.append(envelope)
            for item in run_item_list:
                envelope = await self.event_store.append_run_item_event(db, item)
                envelopes.append(envelope)
            if not project_snapshot:
                return await self._refresh_envelopes(db, envelopes)
            by_thread: dict[str, list[AppEventEnvelope]] = {}
            for envelope in envelopes:
                by_thread.setdefault(envelope.thread_id, []).append(envelope)
            state: dict[str, Any] | None = None
            for group in by_thread.values():
                state = await self.snapshot_store.apply_many(db, group)
            envelopes = await self._refresh_envelopes(db, envelopes)
            if return_state:
                # apply_many returns the partial projection (only touched
                # items); callers that hand the state to clients need the full
                # assembled snapshot.
                if state is not None:
                    state = await self.snapshot_store.load(db, state.get("thread_id") or "")
                return envelopes, state
            return envelopes

    async def _append(self, db: AsyncSession, event: AppEventInput) -> AppEventEnvelope:
        envelope = await self.event_store.append(db, event)
        await self.apply(db, envelope)
        return envelope

    async def apply(self, db: AsyncSession, event: AppEventEnvelope) -> dict[str, Any]:
        return await self.snapshot_store.apply(db, event)

    async def current_revision(self, db: AsyncSession, thread_id: str) -> int:
        """Return the durable revision for a thread, or zero if it is new."""

        row = await db.get(self.snapshot_store.snapshot_model, str(thread_id))
        if row is None:
            return 0
        value = getattr(row, "revision", None)
        if value is None:
            state = getattr(row, "snapshot_json", None)
            value = state.get("revision", 0) if isinstance(state, dict) else 0
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    async def assert_revision(
        self,
        db: AsyncSession,
        thread_id: str,
        expected_revision: int | None,
    ) -> int:
        """CAS-check a thread revision inside the caller's write transaction.

        ``None`` deliberately preserves the legacy read/modify/write behavior
        for local callers that have not opted into optimistic concurrency yet.
        An explicit zero is meaningful for a newly-created session and is not
        treated as an omitted value.
        """

        current = await self.current_revision(db, thread_id)
        if expected_revision is None:
            return current
        expected = int(expected_revision)
        if expected != current:
            raise RevisionConflictError(
                thread_id=thread_id,
                expected_revision=expected,
                current_revision=current,
            )
        return current

    async def load(self, db: AsyncSession, thread_id: str) -> dict[str, Any]:
        return await self.snapshot_store.load(db, thread_id)

    async def list_thread_ids(self, db: AsyncSession) -> list[str]:
        return await self.snapshot_store.list_thread_ids(db)

    async def list_active_thread_ids(self, db: AsyncSession) -> list[str]:
        return await self.snapshot_store.list_active_thread_ids(db)

    async def rebuild(self, db: AsyncSession, thread_id: str) -> dict[str, Any]:
        events = await self.list_thread(db, thread_id=thread_id)
        return await self.snapshot_store.rebuild(db, thread_id, events)

    async def list_after(
        self,
        db: AsyncSession,
        *,
        thread_id: str,
        after_seq: int = 0,
        limit: int = 500,
    ) -> list[AppEventEnvelope]:
        return await self.event_store.list_after(db, thread_id=thread_id, after_seq=after_seq, limit=limit)

    async def list_thread(
        self,
        db: AsyncSession,
        *,
        thread_id: str,
        limit: int | None = None,
    ) -> list[AppEventEnvelope]:
        return await self.event_store.list_thread(db, thread_id=thread_id, limit=limit)

    async def find_client_event(
        self,
        db: AsyncSession,
        *,
        thread_id: str,
        client_message_id: str,
        methods: set[str],
    ) -> AppEventEnvelope | None:
        return await self.event_store.find_client_event(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            methods=methods,
        )


__all__ = ["AppPersistenceHost", "RevisionConflictError"]
