from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from lamtools_core.app import CoreAppEventHub

_app_hub = CoreAppEventHub()
from app.app_server.protocol import WriterAppEventEnvelope
from app.app_server.runtime_bridge import persist_run_item_events_as_app_events
from app.database import create_writer_engine, writer_write_coordinator
from lamtools_core.event import RunItemEvent

logger = logging.getLogger(__name__)

PersistRunItems = Callable[[Any, list[RunItemEvent]], Awaitable[list[WriterAppEventEnvelope]]]


class AppProjectionSink:
    def __init__(
        self,
        *,
        database_url: str = "",
        debug: bool = False,
        persist_run_items: PersistRunItems | None = None,
        hub: Any = None,
        session_factory: async_sessionmaker | None = None,
        write_coordinator: Any | None = None,
    ) -> None:
        self._database_url = database_url
        self._debug = debug
        self._persist_run_items = persist_run_items or persist_run_item_events_as_app_events
        self._hub = hub
        self._engine: AsyncEngine | None = None
        self._session_factory = session_factory
        self._write_coordinator = write_coordinator
        self._owns_engine = session_factory is None

    def _sessions(self) -> async_sessionmaker:
        if self._session_factory is None:
            self._engine = create_writer_engine(self._database_url, debug=self._debug)
            self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        return self._session_factory

    def _coordinator(self):
        if self._write_coordinator is None:
            self._write_coordinator = writer_write_coordinator(self._sessions())
        return self._write_coordinator

    async def close(self) -> None:
        if self._owns_engine and self._engine is not None:
            await self._engine.dispose()
        self._engine = None
        if self._owns_engine:
            self._session_factory = None
        self._write_coordinator = None

    async def persist_in_transaction(
        self,
        db: AsyncSession,
        events: list[RunItemEvent],
    ) -> list[WriterAppEventEnvelope]:
        return await self._persist_run_items(db, events)

    async def broadcast(self, envelopes: list[WriterAppEventEnvelope]) -> None:
        for envelope in envelopes:
            await self._hub.publish(envelope)

    async def publish(
        self,
        events: list[RunItemEvent],
        *,
        session_id: str,
        source_event_id: str,
    ) -> list[WriterAppEventEnvelope]:
        if not events:
            return []
        try:
            async def write(db: AsyncSession) -> list[WriterAppEventEnvelope]:
                return await self.persist_in_transaction(db, events)

            envelopes = await self._coordinator().run(write)
        except Exception:
            logger.exception(
                "Failed to persist Writer app projection for session %s event %s",
                session_id,
                source_event_id,
            )
            raise

        await self.broadcast(envelopes)
        return envelopes
