from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lamtools_core.app.event_store import AppEventEnvelope, AppEventInput
from lamtools_core.app.persistence_host import AppPersistenceHost
from lamtools_core.app.snapshot_store import CoreAppSnapshotProjector, SqlAlchemyThreadSnapshotStore
from lamtools_core.app.event_store import SqlAlchemyAppEventStore
from lamtools_core.event import RunItemEvent


def _envelope(*, event_id: str, seq: int, method: str = "turn/accepted") -> AppEventEnvelope:
    return AppEventEnvelope(
        event_id=event_id,
        protocol_version="test.v1",
        seq=seq,
        thread_id="thread-1",
        method=method,
        payload={"event_id": event_id},
        created_at=datetime.now(),
    )


class _EventStore:
    def __init__(self, calls: list[object]) -> None:
        self.calls = calls
        self.events = [_envelope(event_id="stored-1", seq=1), _envelope(event_id="stored-2", seq=2)]

    async def append(self, db, event: AppEventInput) -> AppEventEnvelope:
        self.calls.append(("append", event.event_id))
        return _envelope(event_id=event.event_id or "generated", seq=len(self.calls))

    async def append_run_item_event(self, db, event: RunItemEvent) -> AppEventEnvelope:
        self.calls.append(("append_run_item", event.event_id))
        return _envelope(event_id=event.event_id, seq=len(self.calls), method="core/runItem")

    async def list_after(self, db, *, thread_id: str, after_seq: int, limit: int):
        self.calls.append(("list_after", thread_id, after_seq, limit))
        return self.events[after_seq:]

    async def list_thread(self, db, *, thread_id: str, limit: int | None = None):
        self.calls.append(("list_thread", thread_id, limit))
        return self.events if limit is None else self.events[:limit]

    async def find_client_event(self, db, *, thread_id: str, client_message_id: str, methods: set[str]):
        self.calls.append(("find_client_event", thread_id, client_message_id, methods))
        return self.events[0]


class _SnapshotStore:
    def __init__(self, calls: list[object]) -> None:
        self.calls = calls

    async def apply(self, db, event: AppEventEnvelope) -> dict:
        self.calls.append(("apply", event.event_id))
        return {"thread_id": event.thread_id, "snapshot_seq": event.seq}

    async def load(self, db, thread_id: str) -> dict:
        self.calls.append(("load", thread_id))
        return {"thread_id": thread_id, "snapshot_seq": 2}

    async def rebuild(self, db, thread_id: str, events: list[AppEventEnvelope]) -> dict:
        self.calls.append(("rebuild", thread_id, [event.event_id for event in events]))
        return {"thread_id": thread_id, "snapshot_seq": len(events)}


class _NestedDb:
    def begin_nested(self):
        return _NestedTransaction()


class _NestedTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class Base(DeclarativeBase):
    pass


class AppEventRow(Base):
    __tablename__ = "test_persistence_host_events"
    __table_args__ = (UniqueConstraint("thread_id", "seq", name="uq_test_persistence_host_events_thread_seq"),)

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


class SnapshotRow(Base):
    __tablename__ = "test_persistence_host_snapshots"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


async def _persistence(tmp_path, *, projector: CoreAppSnapshotProjector | None = None):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'persistence-host.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    event_store = SqlAlchemyAppEventStore(AppEventRow, protocol_version="test.v1")
    snapshot_store = SqlAlchemyThreadSnapshotStore(SnapshotRow, projector=projector)
    return engine, session_factory, event_store, snapshot_store, AppPersistenceHost(event_store, snapshot_store)


class _FailingProjector(CoreAppSnapshotProjector):
    def __init__(self, failed_event_id: str) -> None:
        super().__init__()
        self.failed_event_id = failed_event_id

    def apply(self, state: dict | None, event: AppEventEnvelope) -> dict:
        if event.event_id == self.failed_event_id:
            raise RuntimeError("projection failed")
        return super().apply(state, event)


@pytest.mark.asyncio
async def test_append_persists_then_projects_and_returns_event_without_committing():
    calls: list[object] = []
    host = AppPersistenceHost(_EventStore(calls), _SnapshotStore(calls))
    db = _NestedDb()

    event = await host.append(db, AppEventInput(event_id="event-1", thread_id="thread-1", method="turn/accepted"))

    assert event.event_id == "event-1"
    assert calls == [("append", "event-1"), ("apply", "event-1")]


@pytest.mark.asyncio
async def test_append_run_item_persists_then_projects_and_returns_event():
    calls: list[object] = []
    host = AppPersistenceHost(_EventStore(calls), _SnapshotStore(calls))

    event = await host.append_run_item(
        _NestedDb(),
        RunItemEvent(event_id="run-item-1", kind="message", thread_id="thread-1", payload={}),
    )

    assert event.method == "core/runItem"
    assert calls == [("append_run_item", "run-item-1"), ("apply", "run-item-1")]


@pytest.mark.asyncio
async def test_append_many_preserves_append_apply_order():
    calls: list[object] = []
    host = AppPersistenceHost(_EventStore(calls), _SnapshotStore(calls))

    events = await host.append_many(
        _NestedDb(),
        [
            AppEventInput(event_id="event-1", thread_id="thread-1", method="turn/accepted"),
            AppEventInput(event_id="event-2", thread_id="thread-1", method="item/started"),
        ],
    )

    assert [event.event_id for event in events] == ["event-1", "event-2"]
    assert calls == [
        ("append", "event-1"),
        ("apply", "event-1"),
        ("append", "event-2"),
        ("apply", "event-2"),
    ]


@pytest.mark.asyncio
async def test_load_rebuild_list_and_find_delegate_to_the_shared_stores():
    calls: list[object] = []
    host = AppPersistenceHost(_EventStore(calls), _SnapshotStore(calls))

    loaded = await host.load(_NestedDb(), "thread-1")
    rebuilt = await host.rebuild(_NestedDb(), "thread-1")
    after = await host.list_after(_NestedDb(), thread_id="thread-1", after_seq=1, limit=50)
    listed = await host.list_thread(_NestedDb(), thread_id="thread-1", limit=1)
    found = await host.find_client_event(
        _NestedDb(),
        thread_id="thread-1",
        client_message_id="client-1",
        methods={"turn/accepted"},
    )

    assert loaded["snapshot_seq"] == 2
    assert rebuilt["snapshot_seq"] == 2
    assert [event.event_id for event in after] == ["stored-2"]
    assert [event.event_id for event in listed] == ["stored-1"]
    assert found is not None and found.event_id == "stored-1"
    assert calls == [
        ("load", "thread-1"),
        ("list_thread", "thread-1", None),
        ("rebuild", "thread-1", ["stored-1", "stored-2"]),
        ("list_after", "thread-1", 1, 50),
        ("list_thread", "thread-1", 1),
        ("find_client_event", "thread-1", "client-1", {"turn/accepted"}),
    ]


@pytest.mark.asyncio
async def test_existing_event_is_reprojected_when_snapshot_is_behind(tmp_path):
    engine, session_factory, event_store, snapshot_store, host = await _persistence(tmp_path)
    try:
        async with session_factory() as db:
            event_input = AppEventInput(
                event_id="event-1",
                thread_id="thread-1",
                method="turn/accepted",
                turn_id="turn-1",
                payload={"status": "running"},
            )
            stored = await event_store.append(db, event_input)
            replayed = await host.append(db, event_input)

            snapshot = await snapshot_store.load(db, "thread-1")
            assert replayed.event_id == stored.event_id
            assert snapshot["snapshot_seq"] == stored.seq
            assert snapshot["turns"]["turn-1"]["status"] == "running"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_existing_event_is_not_reprojected_after_seen_ids_are_trimmed(tmp_path):
    engine, session_factory, _, snapshot_store, host = await _persistence(tmp_path)
    try:
        async with session_factory() as db:
            event = RunItemEvent(
                event_id="event-1",
                kind="message",
                thread_id="thread-1",
                turn_id="turn-1",
                item_id="item-1",
                payload={"delta": "once"},
            )
            await host.append_run_item(db, event)
            row = await db.get(SnapshotRow, "thread-1")
            assert row is not None
            row.snapshot_seq = 2001
            row.snapshot_json = {
                **dict(row.snapshot_json),
                "snapshot_seq": 2001,
                "seen_event_ids": [f"event-{index}" for index in range(2, 2002)],
            }
            await db.flush()

            await host.append_run_item(db, event)

            snapshot = await snapshot_store.load(db, "thread-1")
            assert snapshot["core"]["items"]["item-1"]["content"] == "once"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_append_rolls_back_event_and_snapshot_when_projection_fails(tmp_path):
    engine, session_factory, event_store, snapshot_store, host = await _persistence(
        tmp_path,
        projector=_FailingProjector("event-fails"),
    )
    try:
        async with session_factory() as db:
            with pytest.raises(RuntimeError, match="projection failed"):
                await host.append(
                    db,
                    AppEventInput(event_id="event-fails", thread_id="thread-1", method="turn/accepted"),
                )
            await db.commit()

        async with session_factory() as db:
            assert await event_store.list_thread(db, thread_id="thread-1") == []
            assert (await snapshot_store.load(db, "thread-1"))["snapshot_seq"] == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_append_many_rolls_back_the_whole_batch_when_one_projection_fails(tmp_path):
    engine, session_factory, event_store, snapshot_store, host = await _persistence(
        tmp_path,
        projector=_FailingProjector("event-fails"),
    )
    try:
        async with session_factory() as db:
            with pytest.raises(RuntimeError, match="projection failed"):
                await host.append_many(
                    db,
                    [
                        AppEventInput(event_id="event-1", thread_id="thread-1", method="turn/accepted"),
                        AppEventInput(event_id="event-fails", thread_id="thread-1", method="item/started"),
                    ],
                )
            await db.commit()

        async with session_factory() as db:
            assert await event_store.list_thread(db, thread_id="thread-1") == []
            assert (await snapshot_store.load(db, "thread-1"))["snapshot_seq"] == 0
    finally:
        await engine.dispose()
