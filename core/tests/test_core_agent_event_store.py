from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lamtools_core.app.event_store import (
    CORE_RUN_ITEM_METHOD,
    AppEventInput,
    SqlAlchemyAppEventStore,
)
from lamtools_core.app.sqlite_write import SQLiteWriteCoordinator
from lamtools_core.event import RunItemEvent


class Base(DeclarativeBase):
    pass


class AppEventRow(Base):
    __tablename__ = "test_app_events"
    __table_args__ = (
        UniqueConstraint("thread_id", "seq", name="uq_test_app_events_thread_seq"),
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
    persisted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


async def _session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'events.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_app_event_store_allocates_thread_sequence(tmp_path):
    engine, session_factory = await _session_factory(tmp_path)
    try:
        async with session_factory() as db:
            store = SqlAlchemyAppEventStore(AppEventRow, protocol_version="test.v1")
            first = await store.append(
                db,
                AppEventInput(thread_id="thread-1", method="turn.accepted", payload={"status": "running"}),
            )
            second = await store.append(
                db,
                AppEventInput(thread_id="thread-1", method="turn.completed", payload={"status": "completed"}),
            )
            other = await store.append(
                db,
                AppEventInput(thread_id="thread-2", method="turn.accepted", payload={}),
            )

            assert first.seq == 1
            assert second.seq == 2
            assert other.seq == 1
            assert second.protocol_version == "test.v1"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_app_event_store_returns_existing_event_by_id(tmp_path):
    engine, session_factory = await _session_factory(tmp_path)
    try:
        async with session_factory() as db:
            store = SqlAlchemyAppEventStore(AppEventRow, protocol_version="test.v1")
            first = await store.append(
                db,
                AppEventInput(
                    event_id="event-fixed",
                    thread_id="thread-1",
                    method="turn.accepted",
                    payload={"attempt": 1},
                ),
            )
            duplicate = await store.append(
                db,
                AppEventInput(
                    event_id="event-fixed",
                    thread_id="thread-1",
                    method="turn.accepted",
                    payload={"attempt": 2},
                ),
            )

            rows = (await db.execute(select(AppEventRow))).scalars().all()
            assert len(rows) == 1
            assert duplicate.event_id == first.event_id
            assert duplicate.payload == {"attempt": 1}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_write_coordinator_retries_whole_event_transaction_with_a_new_session(tmp_path):
    engine, session_factory = await _session_factory(tmp_path)
    opened_sessions = []
    closed_sessions: list[bool] = []

    class TrackingSessionContext:
        def __init__(self) -> None:
            self._context = session_factory()

        async def __aenter__(self):
            session = await self._context.__aenter__()
            opened_sessions.append(session)
            return session

        async def __aexit__(self, exc_type, exc, traceback):
            try:
                return await self._context.__aexit__(exc_type, exc, traceback)
            finally:
                closed_sessions.append(True)

    def tracking_session_factory():
        return TrackingSessionContext()

    try:
        store = SqlAlchemyAppEventStore(AppEventRow, protocol_version="test.v1")
        coordinator = SQLiteWriteCoordinator(
            tracking_session_factory,
            identity=f"test:{tmp_path}",
            retry_delays=(0,),
        )
        action_calls = 0

        async def append_event(db):
            nonlocal action_calls
            action_calls += 1
            if action_calls == 1:
                await store.append(
                    db,
                    AppEventInput(
                        event_id="event-after-lock",
                        thread_id="thread-1",
                        method="turn.accepted",
                        payload={"status": "running"},
                    ),
                )
                raise OperationalError("BEGIN IMMEDIATE", {}, Exception("database is locked"))
            return await store.append(
                db,
                AppEventInput(
                    event_id="event-after-lock",
                    thread_id="thread-1",
                    method="turn.accepted",
                    payload={"status": "running"},
                ),
            )

        envelope = await coordinator.run(append_event)

        assert envelope.event_id == "event-after-lock"
        assert envelope.seq == 1
        assert action_calls == 2
        assert len(opened_sessions) == 2
        assert opened_sessions[0] is not opened_sessions[1]
        assert closed_sessions == [True, True]
        async with session_factory() as db:
            rows = (await db.execute(select(AppEventRow))).scalars().all()
        assert [(row.event_id, row.seq) for row in rows] == [("event-after-lock", 1)]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_app_event_store_wraps_run_item_event(tmp_path):
    engine, session_factory = await _session_factory(tmp_path)
    try:
        async with session_factory() as db:
            store = SqlAlchemyAppEventStore(AppEventRow, protocol_version="test.v1")
            event = RunItemEvent(
                event_id="run-item-1",
                kind="message",
                thread_id="thread-1",
                run_id="run-1",
                turn_id="turn-1",
                item_id="item-1",
                seq=0,
                status="completed",
                payload={"role": "assistant", "content": "ok"},
            )

            envelope = await store.append_run_item_event(db, event)

            assert envelope.event_id == "run-item-1"
            assert envelope.method == CORE_RUN_ITEM_METHOD
            assert envelope.turn_id == "turn-1"
            assert envelope.item_id == "item-1"
            assert envelope.payload["kind"] == "message"
            assert envelope.payload["thread_id"] == "thread-1"
    finally:
        await engine.dispose()
