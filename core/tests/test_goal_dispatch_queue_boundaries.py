"""user:“在正常的目标终止之后，还会多发这条消息出去”+(目标续跑不能留下可再次发送的队列项)。"""

from unittest.mock import AsyncMock

import pytest

from core.tests.test_core_live import _context
from lamtools_core.runtime import RuntimeTaskRegistry
from lamtools_core.app import live_operations as live
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.runtime.goal import GoalManager, InMemoryGoalStore


@pytest.mark.asyncio
@pytest.mark.parametrize("user_queued", [False, True])
async def test_goal_dispatch_never_creates_a_queue_item(tmp_path, monkeypatch, user_queued):
    engine, context = await _context(tmp_path)
    context.host.runtime_task_registry = RuntimeTaskRegistry()
    started = AsyncMock()
    monkeypatch.setattr(live, "_start_runtime_task", started)
    monkeypatch.setattr(live, "_mirror_turn_started", AsyncMock())
    try:
        if user_queued:
            await live.handle_queue_create_operation(request_id=1, context=context, params={
                "thread_id": "t", "input": [{"type": "text", "text": "user request"}],
            })
        await live._dispatch_next_queue_item(context=context, thread_id="t", work_root=str(tmp_path),
            completed_turn_id="old", active_goal={"id": "g", "objective": "finish work"})
        started.assert_awaited_once()
        payload = started.call_args.kwargs["runtime_start"]
        assert payload["goal_id"] == "g"
        assert payload["text"] == ("user request" if user_queued else "存在目标：finish work 未完成，请继续。")
        assert payload.get("goal_continuation_text") == ("存在目标：finish work 未完成，请继续。" if user_queued else None)
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, "t")
            events = await context.event_store.list_thread(db, thread_id="t")
        assert snapshot.get("queue", []) == []
        assert not any(e.method == "queue/itemAccepted" and e.payload.get("goal_continuation") for e in events)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "waiting", "paused", "cancelled", "failed"])
async def test_noncompleted_turn_never_leaves_a_goal_reminder_queued(tmp_path, monkeypatch, status):
    engine, context = await _context(tmp_path)
    context.host.runtime_task_registry = RuntimeTaskRegistry()
    started = AsyncMock()
    monkeypatch.setattr(live, "_start_runtime_task", started)
    try:
        await context.persistence.write(lambda db: context.persistence.append(
            db, AppEventInput(thread_id="t", turn_id="old", method="turn/accepted",
                payload={"status": status}),
        ))
        await live._dispatch_next_queue_item(context=context, thread_id="t", work_root=str(tmp_path),
            completed_turn_id="old", active_goal={"id": "g", "objective": "finish"})
        started.assert_not_awaited()
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, "t")
        assert snapshot.get("queue", []) == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_turn_write_failure_leaves_no_goal_reminder_or_claim(tmp_path, monkeypatch):
    engine, context = await _context(tmp_path)
    context.host.runtime_task_registry = RuntimeTaskRegistry()
    monkeypatch.setattr(context.persistence, "append_batch", AsyncMock(side_effect=RuntimeError("write failed")))
    started = AsyncMock()
    monkeypatch.setattr(live, "_start_runtime_task", started)
    try:
        with pytest.raises(RuntimeError, match="write failed"):
            await live._dispatch_next_queue_item(context=context, thread_id="t", work_root=str(tmp_path),
                completed_turn_id="old", active_goal={"id": "g", "objective": "finish"})
        started.assert_not_awaited()
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, "t")
        assert snapshot.get("queue", []) == []
        assert context.host.runtime_task_registry.accept_run("t", "replacement")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("goal_active", [False, True])
async def test_legacy_reminder_is_discarded_and_only_current_goal_can_continue(tmp_path, monkeypatch, goal_active):
    engine, context = await _context(tmp_path)
    context.host.runtime_task_registry = RuntimeTaskRegistry()
    started = AsyncMock()
    monkeypatch.setattr(live, "_start_runtime_task", started)
    monkeypatch.setattr(live, "_mirror_turn_started", AsyncMock())
    try:
        await live.handle_queue_create_operation(request_id=1, context=context, params={
            "thread_id": "t", "goal_continuation": True,
            "input": [{"type": "text", "text": "obsolete reminder"}],
        })
        await live._dispatch_next_queue_item(context=context, thread_id="t", work_root=str(tmp_path),
            completed_turn_id="old", active_goal={"id": "g", "objective": "current"} if goal_active else None)
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, "t")
        assert snapshot.get("queue", []) == []
        assert started.await_count == int(goal_active)
        if goal_active:
            assert "obsolete" not in started.call_args.kwargs["runtime_start"]["text"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["archived", "blocked"])
async def test_stale_active_goal_does_not_start_a_turn(tmp_path, monkeypatch, status):
    engine, context = await _context(tmp_path)
    context.host.runtime_task_registry = RuntimeTaskRegistry()
    started = AsyncMock()
    monkeypatch.setattr(live, "_start_runtime_task", started)
    manager = GoalManager(InMemoryGoalStore())
    context.host.goal_manager = manager
    goal = await manager.create(thread_id="t", objective="finish")
    await manager.update(goal.id, status=status)
    try:
        await live._dispatch_next_queue_item(context=context, thread_id="t", work_root=str(tmp_path),
            completed_turn_id="old", active_goal={"id": goal.id, "objective": goal.objective})
        started.assert_not_awaited()
    finally:
        await engine.dispose()
