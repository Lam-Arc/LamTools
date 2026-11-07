"""Regressions for the long-session send path.

Each behaviour pinned here is one of the reasons the send transaction used to
grow with the conversation, so a later change cannot quietly restore the cost.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lamtools_core.app.event_store import AppEventEnvelope
from lamtools_core.app.snapshot_store import (
    CoreAppSnapshotProjector,
    SqlAlchemyThreadSnapshotStore,
)
from lamtools_core.app.sqlite_write import wal_maintenance_once

THREAD = "thread-send"


class Base(DeclarativeBase):
    pass


class ThreadSnapshotRow(Base):
    __tablename__ = "send_thread_snapshots"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class SnapshotItemRow(Base):
    __tablename__ = "send_thread_snapshot_items"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


async def _factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'send.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _message_envelope(seq: int, turn_id: str, item_id: str) -> AppEventEnvelope:
    payload = {
        "kind": "message",
        "thread_id": THREAD,
        "turn_id": turn_id,
        "item_id": item_id,
        "status": "completed",
        "payload": {"type": "agentMessage", "content": f"answer {seq}"},
    }
    return AppEventEnvelope(
        event_id=f"event-{seq}",
        protocol_version="test.v1",
        seq=seq,
        thread_id=THREAD,
        method="core/runItem",
        payload=payload,
        created_at=datetime.now(),
        turn_id=turn_id,
        item_id=item_id,
    )


async def _seed(store: SqlAlchemyThreadSnapshotStore, session_factory, turns: int) -> None:
    async with session_factory() as session:
        envelopes = [
            _message_envelope(
                seq=index + 1,
                turn_id=f"{THREAD}:turn:{index:03d}",
                item_id=f"{THREAD}:turn:{index:03d}:text",
            )
            for index in range(turns)
        ]
        await store.apply_many(session, envelopes)
        await session.commit()


@pytest.mark.asyncio
async def test_projection_skips_the_item_scan_when_no_item_is_new(tmp_path):
    """A batch naming only known items needs neither the scan nor anchor map."""
    engine, session_factory = await _factory(tmp_path)
    store = SqlAlchemyThreadSnapshotStore(
        ThreadSnapshotRow, item_model=SnapshotItemRow, projector=CoreAppSnapshotProjector()
    )
    await _seed(store, session_factory, turns=40)
    known_item = f"{THREAD}:turn:000:text"

    async with session_factory() as session:
        state = await store.apply_many(
            session, [_message_envelope(500, f"{THREAD}:turn:000", known_item)]
        )
        await session.commit()

    assert state is not None
    # The scan is the only thing that populates the anchor map, so its absence
    # is the proof that the O(items) read was skipped.
    assert "_item_seq_map" not in state["core"], "no anchors are needed for known items"
    assert known_item in state["core"]["item_order"]
    assert len(state["core"]["item_order"]) == 40
    await engine.dispose()


@pytest.mark.asyncio
async def test_projection_still_places_a_new_item_at_its_seq_position(tmp_path):
    """A genuinely new item id keeps its seq anchor and sorts last."""
    engine, session_factory = await _factory(tmp_path)
    store = SqlAlchemyThreadSnapshotStore(
        ThreadSnapshotRow, item_model=SnapshotItemRow, projector=CoreAppSnapshotProjector()
    )
    await _seed(store, session_factory, turns=5)
    fresh = f"{THREAD}:turn:new:text"

    async with session_factory() as session:
        state = await store.apply_many(
            session, [_message_envelope(600, f"{THREAD}:turn:new", fresh)]
        )
        await session.commit()

    assert state is not None
    assert state["core"]["item_order"][-1] == fresh
    assert len(state["core"]["item_order"]) == 6
    await engine.dispose()


def test_projector_mirrors_only_the_event_turn_onto_the_flattened_map():
    """An event may only restate its own turn; historical turns stay untouched.

    Walking every turn per event copied and deep-copied every historical turn's
    usage, which cost about 10ms per projected write on a 600-turn thread.
    """
    projector = CoreAppSnapshotProjector()
    untouched = {"turn_id": "t1", "status": "completed", "usage": {"input_tokens": 1}}
    state = {
        "thread_id": THREAD,
        "core": {
            "thread_id": THREAD,
            "turns": {
                "t1": {"turn_id": "t1", "status": "completed", "last_seq": 1,
                       "usage": {"input_tokens": 1}},
                "t2": {"turn_id": "t2", "status": "completed", "last_seq": 2,
                       "usage": {"input_tokens": 2}},
            },
        },
        "turns": {
            "t1": untouched,
            "t2": {"turn_id": "t2", "status": "completed", "usage": {"input_tokens": 2}},
        },
    }
    projector.apply_in_place(state, _message_envelope(3, "t2", "t2:text"))

    assert state["turns"]["t1"] is untouched, "the historical turn must not be re-copied"
    assert state["turns"]["t2"]["turn_id"] == "t2"


@pytest.mark.asyncio
async def test_wal_maintenance_reports_outstanding_frames(tmp_path):
    """The maintenance pass reports frames, not file size.

    A checkpointed WAL keeps its file size, so size alone cannot justify another
    checkpoint; the PRAGMA's frame counts are the real signal.
    """
    engine, session_factory = await _factory(tmp_path)
    result = await wal_maintenance_once(session_factory)
    assert result["state"] in {"ok", "no_wal"}
    if result["state"] == "ok":
        assert result["pending"] == max(0, result["log"] - result["checkpointed"])
    await engine.dispose()
