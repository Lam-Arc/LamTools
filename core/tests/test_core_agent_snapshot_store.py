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
    assert state["status"] == "running"
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


@pytest.mark.asyncio
async def test_snapshot_load_reconciles_stale_running_status_from_terminal_turns(tmp_path):
    engine, session_factory = await _session_factory(tmp_path)
    store = SqlAlchemyThreadSnapshotStore(ThreadSnapshotRow)
    stale = store.projector.empty("thread-stale")
    stale["status"] = "running"
    stale["turns"] = {
        "turn-1": {"turn_id": "turn-1", "status": "completed", "last_seq": 5, "items": []}
    }
    stale["core"]["status"] = "running"
    stale["core"]["turns"] = {
        "turn-1": {"turn_id": "turn-1", "status": "completed", "last_seq": 5, "items": []}
    }
    try:
        async with session_factory() as db:
            db.add(ThreadSnapshotRow(thread_id="thread-stale", snapshot_seq=5, snapshot_json=stale))
            await db.commit()

        async with session_factory() as db:
            loaded = await store.load(db, "thread-stale")

        assert loaded["status"] == "completed"
        assert loaded["core"]["status"] == "completed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_snapshot_load_closes_open_requests_from_cancelled_turns(tmp_path):
    engine, session_factory = await _session_factory(tmp_path)
    store = SqlAlchemyThreadSnapshotStore(ThreadSnapshotRow)
    stale = store.projector.empty("thread-cancelled")
    stale["status"] = "cancelled"
    stale["turns"] = {
        "turn-1": {"turn_id": "turn-1", "status": "cancelled", "last_seq": 5, "items": []}
    }
    stale["core"]["status"] = "cancelled"
    stale["core"]["turns"] = {
        "turn-1": {"turn_id": "turn-1", "status": "cancelled", "last_seq": 5, "items": []}
    }
    stale["core"]["requests"] = {
        "request-1": {"request_id": "request-1", "turn_id": "turn-1", "status": "open"}
    }
    try:
        async with session_factory() as db:
            db.add(ThreadSnapshotRow(thread_id="thread-cancelled", snapshot_seq=5, snapshot_json=stale))
            await db.commit()

        async with session_factory() as db:
            loaded = await store.load(db, "thread-cancelled")

        assert loaded["status"] == "cancelled"
        assert loaded["core"]["status"] == "cancelled"
        assert loaded["core"]["requests"]["request-1"]["status"] == "cancelled"
    finally:
        await engine.dispose()


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


@pytest.mark.asyncio
async def test_sqlalchemy_snapshot_store_applies_batch_in_one_projection(tmp_path):
    engine, session_factory = await _session_factory(tmp_path)
    try:
        async with session_factory() as db:
            store = SqlAlchemyThreadSnapshotStore(
                ThreadSnapshotRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            )
            first = RunItemEvent(
                event_id="batch-item-1",
                kind="message",
                thread_id="thread-1",
                run_id="run-1",
                turn_id="turn-1",
                item_id="item-1",
                status="running",
                payload={"delta": "hel"},
            )
            second = RunItemEvent(
                event_id="batch-item-2",
                kind="message",
                thread_id="thread-1",
                run_id="run-1",
                turn_id="turn-1",
                item_id="item-1",
                status="completed",
                payload={"content": "hello"},
            )

            snapshot = await store.apply_many(
                db,
                [_envelope(1, first.to_dict()), _envelope(2, second.to_dict())],
            )
            loaded = await store.load(db, "thread-1")

            assert snapshot is not None
            assert snapshot["snapshot_seq"] == 2
            assert loaded["snapshot_seq"] == 2
            assert loaded["core"]["items"]["item-1"]["content"] == "hello"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_apply_many_projects_deferred_events_with_seq_behind_snapshot(tmp_path):
    """Streaming part events are appended without projection (project_snapshot=False);
    their seq is then older than the snapshot seq advanced by later-projected
    events. The turn-boundary apply_many must still project them (seen-dedup is
    the only guard), otherwise message/thinking content never reaches the
    snapshot and switching sessions loses the text."""
    engine, session_factory = await _session_factory(tmp_path)
    try:
        async with session_factory() as db:
            store = SqlAlchemyThreadSnapshotStore(
                ThreadSnapshotRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            )
            tool = RunItemEvent(
                event_id="tool-10", kind="tool_result", thread_id="thread-1",
                run_id="run-1", turn_id="turn-1", item_id="item-tool", seq=0,
                status="completed",
                payload={"tool_name": "ls", "content": "file list", "role": "tool"},
            )
            message = RunItemEvent(
                event_id="msg-5", kind="message", thread_id="thread-1",
                run_id="run-1", turn_id="turn-1", item_id="item-msg", seq=0,
                status="completed",
                payload={"role": "assistant", "content": "final answer"},
                metadata={"runtime_phase": "runtime.part"},
            )
            # Later event projected first (tool result lands in snapshot, seq -> 10)
            await store.apply(db, _envelope(10, tool.to_dict(), item_id="item-tool"))
            # Boundary replay: batch contains the deferred message with seq=5 < 10
            await store.apply_many(db, [_envelope(5, message.to_dict(), item_id="item-msg")])
            await db.commit()

        # A fresh session must read the message from the persisted JSON column —
        # in-place projection on a shallow copy otherwise evades SQLAlchemy's
        # attribute diff and the UPDATE silently drops snapshot_json.
        async with session_factory() as db:
            store = SqlAlchemyThreadSnapshotStore(
                ThreadSnapshotRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            )
            state = await store.load(db, "thread-1")
            items = state["core"]["items"]
            assert items["item-msg"]["content"] == "final answer"
            assert items["item-tool"]["content"] == "file list"
            assert state["snapshot_seq"] == 10
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_apply_many_is_idempotent_for_seen_events(tmp_path):
    engine, session_factory = await _session_factory(tmp_path)
    try:
        async with session_factory() as db:
            store = SqlAlchemyThreadSnapshotStore(
                ThreadSnapshotRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            )
            message = RunItemEvent(
                event_id="msg-1", kind="message", thread_id="thread-1",
                run_id="run-1", turn_id="turn-1", item_id="item-1", seq=0,
                status="completed",
                payload={"role": "assistant", "content": "answer"},
            )
            env = _envelope(1, message.to_dict(), item_id="item-1")
            await store.apply_many(db, [env])
            await store.apply_many(db, [env])  # same event id again

            state = await store.load(db, "thread-1")
            items = state["core"]["items"]
            assert len(items) == 1
            assert items["item-1"]["content"] == "answer"
            assert len(state["seen_event_ids"]) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_apply_many_reorders_items_by_first_event_seq(tmp_path):
    """Tool results project at runtime (before the turn boundary), while the
    deferred thinking/message part events only reach the snapshot at the
    boundary batch. The batch must reorder its items by first-event seq so the
    turn renders as thinking -> message -> tool call, not tool calls first."""
    engine, session_factory = await _session_factory(tmp_path)
    try:
        async with session_factory() as db:
            store = SqlAlchemyThreadSnapshotStore(
                ThreadSnapshotRow,
                projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
            )
            tool = RunItemEvent(
                event_id="tool-10", kind="tool_result", thread_id="thread-1",
                run_id="run-1", turn_id="turn-1", item_id="item-tool", seq=0,
                status="completed",
                payload={"tool_name": "ls", "content": "file list", "role": "tool"},
            )
            message = RunItemEvent(
                event_id="msg-5", kind="message", thread_id="thread-1",
                run_id="run-1", turn_id="turn-1", item_id="item-msg", seq=0,
                status="completed",
                payload={"role": "assistant", "content": "final answer"},
                metadata={"runtime_phase": "runtime.part"},
            )
            # Runtime projection: the tool result lands in the snapshot first.
            await store.apply(db, _envelope(10, tool.to_dict(), item_id="item-tool"))

            # Turn boundary: the full batch contains the deferred message
            # (seq=5) plus the already-projected tool result (seq=10).
            await store.apply_many(
                db,
                [
                    _envelope(5, message.to_dict(), item_id="item-msg"),
                    _envelope(10, tool.to_dict(), item_id="item-tool"),
                ],
            )

            state = await store.load(db, "thread-1")
            order = state["core"]["item_order"]
            assert order == ["item-msg", "item-tool"]
            # the ordering anchor is recorded on first creation
            assert state["core"]["items"]["item-msg"]["seq"] == 5
            assert state["core"]["items"]["item-tool"]["seq"] == 10
    finally:
        await engine.dispose()
