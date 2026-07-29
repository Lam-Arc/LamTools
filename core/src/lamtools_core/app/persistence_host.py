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

    async def append(self, db: AsyncSession, event: AppEventInput) -> AppEventEnvelope:
        async with db.begin_nested():
            return await self._append(db, event)

    async def append_run_item(self, db: AsyncSession, event: RunItemEvent) -> AppEventEnvelope:
        async with db.begin_nested():
            envelope = await self.event_store.append_run_item_event(db, event)
            await self.apply(db, envelope)
            return envelope

    async def append_many(
        self,
        db: AsyncSession,
        events: Iterable[AppEventInput],
    ) -> list[AppEventEnvelope]:
        async with db.begin_nested():
            return [await self._append(db, event) for event in events]

    async def _append(self, db: AsyncSession, event: AppEventInput) -> AppEventEnvelope:
        envelope = await self.event_store.append(db, event)
        await self.apply(db, envelope)
        return envelope

    async def apply(self, db: AsyncSession, event: AppEventEnvelope) -> dict[str, Any]:
        return await self.snapshot_store.apply(db, event)

    async def load(self, db: AsyncSession, thread_id: str) -> dict[str, Any]:
        return await self.snapshot_store.load(db, thread_id)

    async def list_thread_ids(self, db: AsyncSession) -> list[str]:
        return await self.snapshot_store.list_thread_ids(db)

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


__all__ = ["AppPersistenceHost"]
