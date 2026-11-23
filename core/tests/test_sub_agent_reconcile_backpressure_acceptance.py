"""Acceptance tests preventing historical sub-agent status broadcast storms.

user:“check，事件通道压力过高：可靠通道 32/64；已丢弃 257 帧可丢进度；正在自动恢复，无需操作”+(先编写验收测试：
1. 活跃会话反复执行 reconcile_sub_agent_state 时，不再向实时事件通道或数据库重播已落库的历史子代理状态；仅新增缺失状态才会补发。
2. _persist_core_event_live 对同一确定性 event_id 的重复写入不重复广播，也不重写快照。
3. Rust append_batch_atomic 在重复事件且已投影时短路跳过快照重写，且支持 only_new=True 仅返回新写入事件。)
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from lamtools_core.app.core_db import CoreAppEvent, CoreThreadSnapshot, open_core_app_db
from lamtools_core.app.default_agent import _persist_core_event_live
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import CoreLiveContext
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.app.sub_agent_recovery import reconcile_sub_agent_state
from lamtools_core.event import CollectingEventSink, CoreEvent
from lamtools_core.runtime import InMemoryRuntimeStateStore
from lamtools_core.sub_agent_supervisor import SubAgentRecord, get_sub_agent_supervisor


def _drain_queue(queue: asyncio.Queue) -> list:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


@pytest.mark.asyncio
async def test_reconcile_live_supervisor_does_not_republish_existing_historical_sub_agent_statuses(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    db = await open_core_app_db(tmp_path / "core.db", workspace_id="ws-reconcile")
    hub = CoreAppEventHub()
    queue = hub.subscribe("parent")
    store = InMemoryRuntimeStateStore()
    live_calls = 0

    async def live_callback(event: CoreEvent) -> None:
        nonlocal live_calls
        live_calls += 1
        await _persist_core_event_live(
            event,
            thread_id="parent",
            db_session_factory=db.session_factory,
            app_event_store=db.event_store,
            thread_snapshot_store=db.snapshot_store,
            app_event_hub=hub,
            write_coordinator=db.persistence._write_coordinator,
        )

    live_sink = CollectingEventSink(live_callback)
    runner = SimpleNamespace(
        state_store=store,
        parent_event_sink=live_sink,
        run=lambda *_args, **_kwargs: None,
    )
    supervisor = await get_sub_agent_supervisor(
        parent_thread_id="parent",
        runner=runner,
        data_dir=tmp_path,
    )
    context = CoreLiveContext(
        operations=OperationCatalog(),
        session_factory=db.session_factory,
        persistence=db.persistence,
        runtime_state_store=store,
        hub=hub,
    )

    try:
        statuses = ("idle", "closed", "failed")
        for i in range(50):
            supervisor._save(
                SubAgentRecord(
                    parent_thread_id="parent",
                    type="execute",
                    name=f"worker_{i:02d}",
                    model_id="fixture",
                    reasoning_level="high",
                    status=statuses[i % len(statuses)],
                    started_at=10 + i,
                    completed_at=100 + i,
                    sub_session_id=f"parent:sub:worker_{i:02d}",
                    source_turn_id=f"parent:turn:{i}",
                    source_run_id=f"parent:turn:{i}",
                    source_call_id=f"call_{i}",
                )
            )

        await reconcile_sub_agent_state(context=context, data_dir=tmp_path)
        initial_events = _drain_queue(queue)
        assert len(initial_events) == 50

        async with db.session_factory() as session:
            base_event_count = await session.scalar(select(func.count()).select_from(CoreAppEvent))
            snap = await session.get(CoreThreadSnapshot, "parent")
            assert snap is not None
            base_revision = snap.revision
            base_updated_at = snap.updated_at

        base_live_calls = live_calls

        await asyncio.sleep(0.02)
        await reconcile_sub_agent_state(context=context, data_dir=tmp_path)
        await asyncio.sleep(0.02)
        await reconcile_sub_agent_state(context=context, data_dir=tmp_path)

        assert queue.empty()
        assert live_calls == base_live_calls

        async with db.session_factory() as session:
            after_event_count = await session.scalar(select(func.count()).select_from(CoreAppEvent))
            snap_after = await session.get(CoreThreadSnapshot, "parent")
            assert snap_after is not None
            assert after_event_count == base_event_count
            assert snap_after.revision == base_revision
            assert snap_after.updated_at == base_updated_at

        supervisor._save(
            SubAgentRecord(
                parent_thread_id="parent",
                type="execute",
                name="worker_new",
                model_id="fixture",
                reasoning_level="high",
                status="idle",
                started_at=900,
                completed_at=999,
                sub_session_id="parent:sub:worker_new",
                source_turn_id="parent:turn:999",
                source_run_id="parent:turn:999",
                source_call_id="call_999",
            )
        )
        await reconcile_sub_agent_state(context=context, data_dir=tmp_path)
        added_events = _drain_queue(queue)
        assert len(added_events) == 1
        assert added_events[0].item_id == "parent:sub:worker_new:status"

        async with db.session_factory() as session:
            final_event_count = await session.scalar(select(func.count()).select_from(CoreAppEvent))
            assert final_event_count == base_event_count + 1
    finally:
        hub.unsubscribe("parent", queue)
        await supervisor.shutdown()
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("disable_rust", [False, True])
async def test_persist_core_event_live_dedupes_existing_event_without_republishing(
    tmp_path, monkeypatch: pytest.MonkeyPatch, disable_rust: bool
) -> None:
    if disable_rust:
        monkeypatch.setenv("LAMTOOLS_DISABLE_RUST_DB", "1")
    else:
        monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)

    db = await open_core_app_db(tmp_path / f"core_{int(disable_rust)}.db", workspace_id="ws-live-dedup")
    hub = CoreAppEventHub()
    queue = hub.subscribe("t-live")
    try:
        if not disable_rust:
            assert db.rust_db is not None

        event = CoreEvent(
            event_id="fixed-member-status-1",
            name="runtime.sub_agent_status",
            category="message",
            session_id="t-live",
            run_id="t-live:turn:1",
            turn_id="t-live:turn:1",
            payload={
                "event": "member_finished",
                "sub_agent": {
                    "name": "w1",
                    "status": "idle",
                    "parent_turn_id": "t-live:turn:1",
                },
            },
        )

        await _persist_core_event_live(
            event,
            thread_id="t-live",
            db_session_factory=db.session_factory,
            app_event_store=db.event_store,
            thread_snapshot_store=db.snapshot_store,
            app_event_hub=hub,
            write_coordinator=db.persistence._write_coordinator,
        )
        first_batch = _drain_queue(queue)
        assert len(first_batch) == 1

        async with db.session_factory() as session:
            count_first = await session.scalar(select(func.count()).select_from(CoreAppEvent))
            snap_first = await session.get(CoreThreadSnapshot, "t-live")
            assert count_first == 1
            assert snap_first is not None
            assert snap_first.revision == 1
            first_updated_at = snap_first.updated_at

        await asyncio.sleep(0.02)
        await _persist_core_event_live(
            event,
            thread_id="t-live",
            db_session_factory=db.session_factory,
            app_event_store=db.event_store,
            thread_snapshot_store=db.snapshot_store,
            app_event_hub=hub,
            write_coordinator=db.persistence._write_coordinator,
        )

        assert queue.empty()
        async with db.session_factory() as session:
            count_second = await session.scalar(select(func.count()).select_from(CoreAppEvent))
            snap_second = await session.get(CoreThreadSnapshot, "t-live")
            assert count_second == 1
            assert snap_second is not None
            assert snap_second.revision == 1
            assert snap_second.updated_at == first_updated_at
    finally:
        hub.unsubscribe("t-live", queue)
        await db.close()


@pytest.mark.asyncio
async def test_rust_append_batch_atomic_duplicate_skips_snapshot_rewrite_and_honors_only_new(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LAMTOOLS_DISABLE_RUST_DB", raising=False)
    db = await open_core_app_db(tmp_path / "rust_dedup.db", workspace_id="ws-rust-dedup")
    try:
        assert db.rust_db is not None
        ev1 = AppEventInput(
            event_id="evt-rust-1",
            thread_id="t1",
            method="thread/started",
            payload={"type": "thread", "status": "idle"},
        )
        ev2 = AppEventInput(
            event_id="evt-rust-2",
            thread_id="t1",
            method="turn/accepted",
            turn_id="turn-1",
            payload={"type": "turn", "status": "running"},
        )

        envs1 = await db.persistence.append_batch_atomic(app_events=[ev1])
        assert len(envs1) == 1
        assert envs1[0].seq == 1
        assert envs1[0].revision == 1

        async with db.session_factory() as session:
            snap1 = await session.get(CoreThreadSnapshot, "t1")
            assert snap1 is not None
            first_updated_at = snap1.updated_at

        await asyncio.sleep(0.02)
        envs_dup = await db.persistence.append_batch_atomic(app_events=[ev1])
        assert len(envs_dup) == 1
        assert envs_dup[0].seq == 1
        assert envs_dup[0].revision == 1

        async with db.session_factory() as session:
            snap_after_dup = await session.get(CoreThreadSnapshot, "t1")
            assert snap_after_dup is not None
            assert snap_after_dup.updated_at == first_updated_at

        envs_only_new_dup = await db.persistence.append_batch_atomic(
            app_events=[ev1],
            only_new=True,
        )
        assert envs_only_new_dup == []

        envs_mixed = await db.persistence.append_batch_atomic(
            app_events=[ev1, ev2],
            only_new=True,
        )
        assert len(envs_mixed) == 1
        assert envs_mixed[0].event_id == ev2.event_id
        assert envs_mixed[0].revision == 2

        wrong_thread_ev1 = AppEventInput(
            event_id="evt-rust-1",
            thread_id="t2",
            method="thread/started",
            payload={"type": "thread", "status": "idle"},
        )
        with pytest.raises(ValueError, match="another thread"):
            await db.persistence.append_batch_atomic(
                app_events=[wrong_thread_ev1],
                only_new=True,
            )
    finally:
        await db.close()
