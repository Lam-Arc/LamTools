from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from lamtools_core.app import CoreAppSnapshotProjector, OperationCatalog
from lamtools_core.app.core_db import CoreDbBase
from lamtools_core.app.event_store import AppEventEnvelope, AppEventInput, SqlAlchemyAppEventStore
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live.queue import handle_queue_reorder_operation
from lamtools_core.app.live_operations import CoreLiveContext
from lamtools_core.app.queue_state import next_dispatchable_queue_item
from lamtools_core.app.snapshot_store import SqlAlchemyThreadSnapshotStore


class Base(DeclarativeBase):
    pass


class AppEventRow(Base):
    __tablename__ = "test_queue_reorder_app_events"
    __table_args__ = (
        UniqueConstraint("thread_id", "seq", name="uq_test_queue_reorder_app_events_thread_seq"),
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


class ThreadSnapshotRow(Base):
    __tablename__ = "test_queue_reorder_thread_snapshots"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    snapshot_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class SnapshotItemRow(Base):
    __tablename__ = "test_queue_reorder_thread_snapshot_items"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


async def _context(tmp_path) -> tuple[object, CoreLiveContext]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'queue-reorder.db'}", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(CoreDbBase.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    event_store = SqlAlchemyAppEventStore(AppEventRow, protocol_version="core.app_server.v1")
    snapshot_store = SqlAlchemyThreadSnapshotStore(
        ThreadSnapshotRow, item_model=SnapshotItemRow,
        projector=CoreAppSnapshotProjector(member_defaults={"queue": []}),
    )
    return engine, CoreLiveContext(
        session_factory=session_factory,
        event_store=event_store,
        snapshot_store=snapshot_store,
        operations=OperationCatalog(),
        hub=CoreAppEventHub(),
    )


def _envelope(seq: int, payload: dict, method: str = "queue/itemAccepted", item_id: str | None = None) -> AppEventEnvelope:
    return AppEventEnvelope(
        event_id=f"evt-{seq}",
        protocol_version="test.v1",
        thread_id="thread-1",
        seq=seq,
        method=method,
        item_id=item_id,
        payload=payload,
        created_at=datetime.now(),
    )


def _accepted(seq: int, queue_item_id: str) -> AppEventEnvelope:
    return _envelope(
        seq,
        {
            "queue_item_id": queue_item_id,
            "status": "queued",
            "mode": "next_turn",
            "input": [{"type": "text", "text": queue_item_id}],
        },
        item_id=queue_item_id,
    )


# user:“排队项可拖拽上下移动重新排序”+(重排序事件给条目写 position，分发顺序跟随
#   position；没被点名的条目保持相对次序排在后面，旧数据没有 position 时退回 seq)。
def test_projector_applies_queue_reorder_events() -> None:
    projector = CoreAppSnapshotProjector(member_defaults={"queue": []})
    state = projector.empty("thread-1")
    for seq, queue_item_id in ((1, "a"), (2, "b"), (3, "c")):
        state = projector.apply_in_place(state, _accepted(seq, queue_item_id))

    reordered = projector.apply_in_place(
        state,
        _envelope(4, {"type": "queue", "order": ["c", "a", "b"]}, method="queue/itemReordered"),
    )

    assert [item["queue_item_id"] for item in reordered["queue"]] == ["c", "a", "b"]
    assert [item["position"] for item in reordered["queue"]] == [0, 1, 2]

    # 重排序之后新排队的条目没有 position：它按 seq 排在所有已定位条目之后。
    with_late = projector.apply_in_place(reordered, _accepted(5, "late"))
    assert [item["queue_item_id"] for item in with_late["queue"]] == ["c", "a", "b", "late"]
    assert "position" not in with_late["queue"][3]


def test_projector_reorder_keeps_unlisted_items_behind_in_relative_order() -> None:
    projector = CoreAppSnapshotProjector(member_defaults={"queue": []})
    state = projector.empty("thread-1")
    for seq, queue_item_id in ((1, "a"), (2, "b"), (3, "c")):
        state = projector.apply_in_place(state, _accepted(seq, queue_item_id))

    reordered = projector.apply_in_place(
        state,
        _envelope(4, {"type": "queue", "order": ["b"]}, method="queue/itemReordered"),
    )

    assert [item["queue_item_id"] for item in reordered["queue"]] == ["b", "a", "c"]


def test_projector_reorder_clears_positions_of_unlisted_items() -> None:
    # 先整队重排写入 position，再用子集重排：没被点名的条目必须丢掉旧 position，
    # 否则会插到已定位条目中间，和“新排队按 seq 垫底”的排序契约相反。
    projector = CoreAppSnapshotProjector(member_defaults={"queue": []})
    state = projector.empty("thread-1")
    for seq, queue_item_id in ((1, "a"), (2, "b"), (3, "c")):
        state = projector.apply_in_place(state, _accepted(seq, queue_item_id))

    state = projector.apply_in_place(
        state,
        _envelope(4, {"type": "queue", "order": ["c", "a", "b"]}, method="queue/itemReordered"),
    )
    subset = projector.apply_in_place(
        state,
        _envelope(5, {"type": "queue", "order": ["a"]}, method="queue/itemReordered"),
    )

    assert [item["queue_item_id"] for item in subset["queue"]] == ["a", "b", "c"]
    assert [item.get("position") for item in subset["queue"]] == [0, None, None]


def test_cli_registers_queue_reorder_subcommand() -> None:
    # 工具规则：GUI 能力必须有同接口 CLI；queue.reorder 不能只存在于桌面端。
    import argparse

    from lamtools_core.cli_commands.parse_turns import register_queue

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    register_queue(sub)
    args = parser.parse_args(["queue", "reorder", "thread-1", "b", "a"])
    assert args.func.__name__ == "cmd_queue_reorder"
    assert args.order == ["b", "a"]


def test_next_dispatchable_queue_item_follows_positions() -> None:
    def snapshot_with(queue: list[dict]) -> dict:
        return {"status": "completed", "queue": queue}

    # 旧数据没有 position：保持原有 seq 排序（行为不变）。
    legacy = snapshot_with([
        {"queue_item_id": "old-1", "status": "queued", "mode": "next_turn", "seq": 5, "input": []},
        {"queue_item_id": "old-2", "status": "queued", "mode": "next_turn", "seq": 6, "input": []},
    ])
    assert next_dispatchable_queue_item(legacy)["queue_item_id"] == "old-1"

    # position 是第一排序键；没有 position 的条目按 seq 排在已定位条目之后。
    mixed = snapshot_with([
        {"queue_item_id": "second", "status": "queued", "mode": "next_turn", "seq": 10, "position": 1, "input": []},
        {"queue_item_id": "late", "status": "queued", "mode": "next_turn", "seq": 11, "input": []},
        {"queue_item_id": "first", "status": "queued", "mode": "next_turn", "seq": 12, "position": 0, "input": []},
    ])
    assert next_dispatchable_queue_item(mixed)["queue_item_id"] == "first"
    # 弹出第一个之后按顺序取下一个。
    mixed["queue"] = [item for item in mixed["queue"] if item["queue_item_id"] != "first"]
    assert next_dispatchable_queue_item(mixed)["queue_item_id"] == "second"


@pytest.mark.asyncio
async def test_queue_reorder_operation_writes_event_and_is_idempotent(tmp_path) -> None:
    engine, context = await _context(tmp_path)
    try:
        async with context.session_factory() as db:
            for seq, queue_item_id in ((1, "a"), (2, "b"), (3, "c")):
                await context.persistence.append(db, AppEventInput(
                    thread_id="thread-1", method="queue/itemAccepted", item_id=queue_item_id,
                    payload={
                        "queue_item_id": queue_item_id, "status": "queued", "mode": "next_turn",
                        "input": [{"type": "text", "text": queue_item_id}],
                    },
                ))
            await db.commit()

        params = {
            "thread_id": "thread-1",
            "client_message_id": "reorder-1",
            "order": ["c", "a", "b"],
        }
        outcome = await handle_queue_reorder_operation(request_id=1, params=dict(params), context=context)
        result = outcome.response["result"]
        assert result["applied"] is True
        assert result["reason"] == ""
        event = result["events"][0]
        assert event["method"] == "queue/itemReordered"
        assert event["payload"]["order"] == ["c", "a", "b"]

        # 同一 client_message_id 重试：幂等返回，不追加第二条事件。
        retried = await handle_queue_reorder_operation(request_id=2, params=dict(params), context=context)
        retried_result = retried.response["result"]
        assert retried_result["applied"] is False
        assert retried_result["reason"] == "already_applied"
        assert len(retried_result["events"]) == 1

        # 顺序没变：不再追加事件，照实返回 unchanged。
        unchanged = await handle_queue_reorder_operation(
            request_id=3, params={"thread_id": "thread-1", "client_message_id": "reorder-2", "order": ["c", "a", "b"]},
            context=context,
        )
        unchanged_result = unchanged.response["result"]
        assert unchanged_result["applied"] is False
        assert unchanged_result["reason"] == "unchanged"
        assert unchanged_result["events"] == []

        # 落库后的快照顺序与 position。
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, "thread-1")
        assert [item["queue_item_id"] for item in snapshot["queue"]] == ["c", "a", "b"]
        assert [item["position"] for item in snapshot["queue"]] == [0, 1, 2]

        # 缺 order 参数直接拒绝（order=[] 是合法的"不变更"，返回 unchanged）。
        missing = await handle_queue_reorder_operation(
            request_id=4, params={"thread_id": "thread-1"}, context=context,
        )
        assert "error" in missing.response
        empty = await handle_queue_reorder_operation(
            request_id=5, params={"thread_id": "thread-1", "client_message_id": "reorder-3", "order": []},
            context=context,
        )
        assert empty.response["result"]["applied"] is False
        assert empty.response["result"]["reason"] == "unchanged"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_queue_reorder_operation_appends_unknown_ids_after_current_order(tmp_path) -> None:
    engine, context = await _context(tmp_path)
    try:
        async with context.session_factory() as db:
            for seq, queue_item_id in ((1, "a"), (2, "b")):
                await context.persistence.append(db, AppEventInput(
                    thread_id="thread-1", method="queue/itemAccepted", item_id=queue_item_id,
                    payload={
                        "queue_item_id": queue_item_id, "status": "queued", "mode": "next_turn",
                        "input": [{"type": "text", "text": queue_item_id}],
                    },
                ))
            await db.commit()

        # 客户端拖拽时把仍在排队的条目都点名；列表里没有的（并发新排队）保持原相对次序垫底。
        outcome = await handle_queue_reorder_operation(
            request_id=1, params={"thread_id": "thread-1", "client_message_id": "reorder-b", "order": ["b"]},
            context=context,
        )
        assert outcome.response["result"]["applied"] is True
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, "thread-1")
        assert [item["queue_item_id"] for item in snapshot["queue"]] == ["b", "a"]
    finally:
        await engine.dispose()
