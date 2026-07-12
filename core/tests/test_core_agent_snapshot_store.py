from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lamtools_core.app.event_store import AppEventEnvelope
from lamtools_core.app.snapshot_store import CoreAppSnapshotProjector, SqlAlchemyThreadSnapshotStore
from lamtools_core.event import RunItemEvent


class Base(DeclarativeBase):
    pass


class ThreadSnapshotRow(Base):
    __tablename__ = "test_thread_snapshots"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


async def _session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'snapshots.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _envelope(seq: int, payload: dict, *, method: str = "core/runItem", item_id: str | None = None) -> AppEventEnvelope:
    return AppEventEnvelope(
        event_id=f"event-{seq}",
        protocol_version="test.v1",
        seq=seq,
        thread_id="thread-1",
        method=method,
        payload=payload,
        created_at=datetime.now(),
        turn_id=payload.get("turn_id"),
        item_id=item_id if item_id is not None else payload.get("item_id"),
    )


def test_projector_keeps_member_defaults_and_core_snapshot():
    projector = CoreAppSnapshotProjector(member_defaults={"queue": []})

    state = projector.empty("thread-1")

    assert state["thread_id"] == "thread-1"
    assert state["queue"] == []
    assert state["core"]["thread_id"] == "thread-1"
    assert state["status"] == "idle"


def test_projector_applies_core_run_item_event():
    projector = CoreAppSnapshotProjector(member_defaults={"queue": []})
    run_item = RunItemEvent(
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

    state = projector.apply(None, _envelope(1, run_item.to_dict()))

    assert state["snapshot_seq"] == 1
    assert state["core"]["items"]["item-1"]["content"] == "ok"
    assert state["status"] == "completed"
    assert state["queue"] == []


@pytest.mark.parametrize(
    ("run_status", "thread_status"),
    [
        ("running", "running"),
        ("waiting", "waiting"),
        ("completed", "completed"),
        ("failed", "failed"),
    ],
)
def test_projector_syncs_outer_turn_status_and_sequence_from_core_run_item(run_status, thread_status):
    projector = CoreAppSnapshotProjector(member_defaults={"queue": []})
    accepted = _envelope(1, {"turn_id": "turn-1", "status": "running"}, method="turn/accepted")
    core_status = RunItemEvent(
        event_id=f"turn-1:{run_status}",
        kind="status",
        thread_id="thread-1",
        run_id="turn-1",
        turn_id="turn-1",
        item_id=f"turn-1:{run_status}",
        status=run_status,
        payload={"type": "turn", "status": run_status},
    )

    state = projector.reduce("thread-1", [accepted, _envelope(2, core_status.to_dict())])

    assert state["core"]["turns"]["turn-1"]["status"] == run_status
    assert state["turns"]["turn-1"]["status"] == run_status
    assert state["core"]["turns"]["turn-1"]["last_seq"] == 2
    assert state["turns"]["turn-1"]["last_seq"] == 2
    assert state["core"]["status"] == thread_status
    assert state["status"] == thread_status


def test_projector_owns_queue_projection_and_terminal_removal():
    projector = CoreAppSnapshotProjector(member_defaults={"queue": []})

    accepted = projector.apply(
        None,
        _envelope(
            1,
            {
                "queue_item_id": "queue-1",
                "status": "queued",
                "input": [{"type": "text", "text": "shown"}],
                "runtime_input": [{"type": "text", "text": "runtime"}],
            },
            method="queue/itemAccepted",
        ),
    )
    assert accepted["queue"] == [
        {
            "queue_item_id": "queue-1",
            "status": "queued",
            "input": [{"type": "text", "text": "shown"}],
            "runtime_input": [{"type": "text", "text": "runtime"}],
            "mode": "next_turn",
            "seq": 1,
            "last_method": "queue/itemAccepted",
        }
    ]

    dispatched = projector.apply(
        accepted,
        _envelope(
            2,
            {"queue_item_id": "queue-1", "status": "dispatched"},
            method="queue/itemDispatched",
        ),
    )

    assert dispatched["queue"] == []


def test_projector_owns_all_generic_app_events():
    projector = CoreAppSnapshotProjector(member_defaults={"queue": []})
    events = [
        _envelope(1, {"status": "idle"}, method="thread/started"),
        _envelope(2, {"turn_id": "turn-1", "input": "hello"}, method="turn/accepted"),
        _envelope(3, {"turn_id": "turn-1", "status": "running"}, method="turn/started"),
        _envelope(4, {"type": "message", "turn_id": "turn-1"}, method="item/started", item_id="item-1"),
        _envelope(5, {"turn_id": "turn-1", "input": "be concise"}, method="turn/steered"),
        _envelope(
            6,
            {"request_id": "request-1", "kind": "approval", "decision": "approve"},
            method="serverRequest/resolved",
        ),
        _envelope(7, {"turn_id": "turn-1", "reason": "user_interrupt"}, method="turn/interrupted"),
    ]

    state = projector.reduce("thread-1", events)

    assert state["turns"]["turn-1"]["status"] == "interrupting"
    assert state["turns"]["turn-1"]["input"] == "be concise"
    assert state["turns"]["turn-1"]["items"] == ["item-1"]
    assert state["items"]["item-1"]["turn_id"] == "turn-1"
    assert state["requests"]["request-1"]["status"] == "resolved"
    assert state["status"] == "running"


def test_projector_remove_turns_cleans_generic_records_and_recomputes_status():
    projector = CoreAppSnapshotProjector(member_defaults={"queue": []})
    state = projector.empty("thread-1")
    state.update(
        {
            "status": "waiting",
            "turns": {
                "turn-1": {"turn_id": "turn-1", "status": "waiting", "seq": 1, "items": ["item-1"]},
                "turn-2": {"turn_id": "turn-2", "status": "completed", "seq": 2, "items": ["item-2"]},
            },
            "items": {
                "item-1": {"item_id": "item-1", "turn_id": "turn-1"},
                "item-2": {"item_id": "item-2", "turn_id": "turn-2"},
            },
            "item_order": ["item-1", "item-2"],
            "requests": {"request-1": {"request_id": "request-1", "turn_id": "turn-1", "item_id": "item-1", "status": "open"}},
            "artifacts": {"artifact-1": {"artifact_id": "artifact-1", "turn_id": "turn-1", "item_id": "item-1"}},
            "queue": [{"queue_item_id": "queue-1", "turn_id": "turn-1"}, {"queue_item_id": "queue-2", "turn_id": "turn-2"}],
            "core": {
                "thread_id": "thread-1",
                "turns": {"turn-1": {"turn_id": "turn-1", "status": "waiting", "items": ["item-1"]}},
                "items": {"item-1": {"item_id": "item-1", "turn_id": "turn-1"}},
                "item_order": ["item-1"],
                "requests": {"request-1": {"request_id": "request-1", "turn_id": "turn-1", "item_id": "item-1"}},
                "artifacts": {"artifact-1": {"artifact_id": "artifact-1", "turn_id": "turn-1", "item_id": "item-1"}},
                "status": "waiting",
            },
        }
    )

    projector.remove_turns(state, {"turn-1"})

    assert set(state["turns"]) == {"turn-2"}
    assert set(state["items"]) == {"item-2"}
    assert state["item_order"] == ["item-2"]
    assert state["requests"] == {}
    assert state["artifacts"] == {}
    assert state["queue"] == [{"queue_item_id": "queue-2", "turn_id": "turn-2"}]
    assert state["core"]["turns"] == {}
    assert state["core"]["items"] == {}
    assert state["core"]["requests"] == {}
    assert state["core"]["artifacts"] == {}
    assert state["core"]["status"] == "idle"
    assert state["status"] == "completed"


def test_projector_in_place_replay_matches_copying_apply():
    projector = CoreAppSnapshotProjector(member_defaults={"queue": []})
    events = [
        _envelope(1, {"turn_id": "turn-1", "status": "running"}, method="turn/accepted"),
        _envelope(
            2,
            RunItemEvent(
                event_id="core-item-1",
                kind="message",
                thread_id="thread-1",
                turn_id="turn-1",
                item_id="item-1",
                payload={"delta": "done"},
            ).to_dict(),
        ),
    ]
    copied = projector.reduce("thread-1", events)
    in_place = projector.empty("thread-1")
    for event in events:
        projector.apply_in_place(in_place, event)

    assert in_place == copied


@pytest.mark.asyncio
async def test_sqlalchemy_snapshot_store_load_apply_rebuild(tmp_path):
    engine, session_factory = await _session_factory(tmp_path)
    try:
        async with session_factory() as db:
            projector = CoreAppSnapshotProjector(member_defaults={"queue": []})
            store = SqlAlchemyThreadSnapshotStore(ThreadSnapshotRow, projector=projector)
            first = RunItemEvent(
                event_id="run-item-1",
                kind="message",
                thread_id="thread-1",
                run_id="run-1",
                turn_id="turn-1",
                item_id="item-1",
                seq=0,
                status="completed",
                payload={"role": "user", "content": "hello"},
            )
            second = RunItemEvent(
                event_id="run-item-2",
                kind="status",
                thread_id="thread-1",
                run_id="run-1",
                turn_id="turn-1",
                seq=0,
                status="completed",
                payload={"status": "completed"},
            )
            envelopes = [_envelope(1, first.to_dict()), _envelope(2, second.to_dict())]

            assert (await store.load(db, "thread-1"))["queue"] == []
            applied = await store.apply(db, envelopes[0])
            rebuilt = await store.rebuild(db, "thread-1", envelopes)

            assert applied["snapshot_seq"] == 1
            assert rebuilt["snapshot_seq"] == 2
            assert rebuilt["core"]["items"]["item-1"]["content"] == "hello"
    finally:
        await engine.dispose()
