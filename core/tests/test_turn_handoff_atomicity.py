"""user:“该修修，相关插件也要修”+(验收断线交接、原子状态切换和插件共用入口)。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, select

from lamtools_core.app import OperationResult, OperationCatalog, open_core_app_db
from lamtools_core.app.live.context import CoreLiveContext
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.runtime import RuntimeTaskRegistry
from lamtools_core.app.core_db import CoreTurnIntent, CoreTurnRun
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.app.live import turn_options
from lamtools_core.app.live.runtime_tasks import _fail_runtime_start
from lamtools_core.app.live.turn_start import handle_turn_start_operation
from lamtools_core.app.live_plugin_service import LiveTurnService
from lamtools_core.event import RunItemEvent
from lamtools_core.turn import TurnCoordinator, TurnHooks


async def _context(tmp_path):
    db = await open_core_app_db(tmp_path / "atomicity.db")
    return db.engine, CoreLiveContext(
        operations=OperationCatalog(), session_factory=db.session_factory,
        persistence=db.persistence, hub=CoreAppEventHub(), runtime_task_registry=RuntimeTaskRegistry(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("plugin", [False, "start", "deliver"])
async def test_disconnect_after_acceptance_still_starts_exactly_once(tmp_path, monkeypatch, plugin):
    engine, context = await _context(tmp_path)
    configuring, release, started, finish = (asyncio.Event() for _ in range(4))
    calls = 0

    async def configuration(**kwargs):
        configuring.set()
        await release.wait()
        return {"enabled": False}

    async def operation(request):
        nonlocal calls
        calls += 1
        started.set()
        await finish.wait()
        return OperationResult(name="turn.start")

    context.operations.register("turn.start", operation)
    monkeypatch.setattr(turn_options, "_resolve_imagegen_config", configuration)
    service = LiveTurnService(lambda: context)
    params = {"thread_id": "thread", "client_message_id": "message", "input": [{"type": "text", "text": "hello"}]}

    async def send():
        if plugin:
            if plugin == "deliver":
                return await service.deliver_message(thread_id="thread", text="hello", client_message_id="message")
            return await service.start_turn(thread_id="thread", text="hello", client_message_id="message")
        return await context.host.execute("turn.start", request_id=1, params=params, context=context)

    task = asyncio.create_task(send())
    try:
        await asyncio.wait_for(configuring.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()  # disconnect/shutdown may cancel the same request twice
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        assert started.is_set(), "accepted input must be handed to a runtime despite disconnect"
        await send()
        assert calls == 1, "the same client message must not execute twice"
    finally:
        release.set()
        finish.set()
        await asyncio.gather(task, return_exceptions=True)
        live = context.host.runtime_task_registry.task("thread")
        if live is not None:
            await live
        context.host.runtime_task_registry.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_post_commit_setup_error_closes_accepted_turn(tmp_path, monkeypatch):
    engine, context = await _context(tmp_path)
    context.operations.register("turn.start", lambda request: None)
    monkeypatch.setattr(turn_options, "_resolve_imagegen_config", AsyncMock(side_effect=RuntimeError("configuration failed")))
    try:
        with pytest.raises(RuntimeError, match="configuration failed"):
            await handle_turn_start_operation(request_id=1, params={
                "thread_id": "thread", "client_message_id": "message", "include_snapshot": False,
                "input": [{"type": "text", "text": "hello"}],
            }, context=context)
        assert context.host.runtime_task_registry.active_run_id("thread") is None
        async with context.session_factory() as session:
            snapshot = await context.persistence.load(session, "thread")
        assert snapshot["status"] == "failed"
    finally:
        context.host.runtime_task_registry.clear()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["start", "resume", "begin_resumed"])
async def test_run_insert_failure_rolls_back_state_and_control_intent(tmp_path, action):
    engine, context = await _context(tmp_path)
    store = context.turn_store
    coordinator = TurnCoordinator(store)
    initial = "queued" if action == "start" else "paused"
    await coordinator.ensure_turn(thread_id="thread", turn_id="turn", status=initial)

    def reject_insert(*args):
        raise RuntimeError("run insert failed")

    async def execute():
        if action == "resume":
            return await coordinator.resume("turn")
        if action == "begin_resumed":
            return await coordinator.begin_resumed_run("turn", "run")
        return await coordinator.start_run("turn", "run")

    event.listen(CoreTurnRun, "before_insert", reject_insert)
    try:
        with pytest.raises(RuntimeError, match="run insert failed"):
            await execute()
        turn = await store.get_turn("turn")
        assert turn.status == initial
        assert turn.epoch == 0
        assert not turn.active_run_id
        assert await store.list_runs("turn") == []
        async with context.session_factory() as session:
            assert list((await session.scalars(select(CoreTurnIntent))).all()) == []
        event.remove(CoreTurnRun, "before_insert", reject_insert)
        result = await execute()
        assert result is not None
        assert len(await store.list_runs("turn")) == 1
    finally:
        if event.contains(CoreTurnRun, "before_insert", reject_insert):
            event.remove(CoreTurnRun, "before_insert", reject_insert)
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_hook_observes_committed_run(tmp_path):
    engine, context = await _context(tmp_path)
    store = context.turn_store

    async def start(turn, run):
        assert (await store.get_turn(turn.turn_id)).active_run_id == run.run_id
        assert await store.get_run(run.run_id) is not None

    coordinator = TurnCoordinator(store, hooks=TurnHooks(start_run=start))
    try:
        await coordinator.ensure_turn(thread_id="thread", turn_id="turn")
        assert await coordinator.start_run("turn", "run") is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_long_history_failure_cleanup_returns_actual_terminal_event(tmp_path):
    engine, context = await _context(tmp_path)

    async def seed(session):
        await context.persistence.append_batch(session, app_events=[
            AppEventInput(thread_id="thread", event_id=f"old-{i}", method="audit/noop") for i in range(501)
        ])
        await context.persistence.append_run_item(session, RunItemEvent(
            kind="status", thread_id="thread", turn_id="turn", run_id="run", event_id="completed",
            item_id="turn-status", status="completed", payload={"type": "turn", "status": "completed"},
        ))
        # A later tool event must not be mistaken for the turn's final status.
        await context.persistence.append_run_item(session, RunItemEvent(
            kind="tool_call", thread_id="thread", turn_id="turn", event_id="late-tool",
            item_id="tool", status="completed", payload={"type": "dynamicToolCall"},
        ))

    try:
        await context.persistence.write(seed)
        terminal, snapshot = await _fail_runtime_start(context=context, thread_id="thread", turn_id="turn", message="late failure")
        assert terminal.event_id == "completed"
        assert snapshot["turns"]["turn"]["status"] == "completed"
        async with context.session_factory() as session:
            events = await context.persistence.list_thread(session, thread_id="thread")
        assert not any(item.event_id == "turn:runtime-start-failed" for item in events)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_plugin_retry_returns_original_turn_identity(tmp_path):
    engine, context = await _context(tmp_path)
    finish = asyncio.Event()

    async def operation(request):
        await finish.wait()
        return OperationResult(name="turn.start")

    context.operations.register("turn.start", operation)
    service = LiveTurnService(lambda: context)
    try:
        first = await service.start_turn(thread_id="thread", text="hello", client_message_id="message")
        retry = await service.start_turn(thread_id="thread", text="hello", client_message_id="message")
        assert first["turn_id"]
        assert retry["turn_id"] == first["turn_id"]
    finally:
        finish.set()
        task = context.host.runtime_task_registry.task("thread")
        if task is not None:
            await task
        context.host.runtime_task_registry.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_plugin_waits_for_shared_session_actor(tmp_path):
    engine, context = await _context(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    service = LiveTurnService(lambda: context)

    async def hold():
        entered.set()
        await release.wait()

    context.operations.register("turn.start", AsyncMock(return_value=OperationResult(name="turn.start")))
    # Use the exact actor key selected by desktop dispatch.
    from lamtools_core.app.live.params import _serialized_actor_key
    actor_key = _serialized_actor_key("turn.start", {"thread_id": "thread"})
    owner = asyncio.create_task(context.host.session_actors.run(actor_key, hold))
    task = None
    try:
        await entered.wait()
        task = asyncio.create_task(service.start_turn(thread_id="thread", text="hello", client_message_id="message"))
        for _ in range(10):
            await asyncio.sleep(0)
        async with context.session_factory() as session:
            events = await context.persistence.list_thread(session, thread_id="thread")
        assert events == [], "plugins must not bypass the desktop's session owner"
    finally:
        release.set()
        await owner
        if task is not None:
            await task
        live = context.host.runtime_task_registry.task("thread")
        if live is not None:
            await live
        context.host.runtime_task_registry.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancellation_does_not_abandon_committed_runtime_hook(tmp_path):
    engine, context = await _context(tmp_path)
    entered, release, actuated = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def start(turn, run):
        entered.set()
        await release.wait()
        actuated.set()

    coordinator = TurnCoordinator(context.turn_store, hooks=TurnHooks(start_run=start))
    await coordinator.ensure_turn(thread_id="thread", turn_id="turn")
    task = asyncio.create_task(coordinator.start_run("turn", "run"))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert actuated.is_set(), "a committed run must complete its activation hook"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()


@pytest.mark.asyncio
async def test_control_roundtrip_commits_related_records_together(tmp_path):
    engine, context = await _context(tmp_path)
    store = context.turn_store
    coordinator = TurnCoordinator(store)
    try:
        await coordinator.ensure_turn(thread_id="thread", turn_id="turn")
        assert await coordinator.start_run("turn", "run") is not None
        assert (await coordinator.pause("turn")).status == "paused"
        turn, run = await coordinator.resume("turn")
        assert turn.active_run_id == run.run_id
        assert (await coordinator.cancel("turn", terminate=True)).status == "stopping"
        assert (await coordinator.settle_stopped("turn")).status == "cancelled"
        async with context.session_factory() as session:
            intents = list((await session.scalars(select(CoreTurnIntent))).all())
        assert len(intents) == 3
        assert all(item.status == "applied" for item in intents)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["turn.start", "turn.resume", "turn.steer", "approval.respond"])
async def test_every_plugin_control_uses_shared_host(tmp_path, monkeypatch, name):
    engine, context = await _context(tmp_path)
    from types import SimpleNamespace
    execute = AsyncMock(return_value=SimpleNamespace(response={"result": {"turn_id": "turn", "events": []}}))
    monkeypatch.setattr(context.host, "execute", execute)
    service = LiveTurnService(lambda: context)
    try:
        if name == "turn.start":
            await service.start_turn(thread_id="thread", text="hello", client_message_id="message")
        elif name == "turn.resume":
            await service.resume_turn(thread_id="thread", turn_id="turn", text="hello", client_message_id="message")
        elif name == "turn.steer":
            await service.steer_turn(thread_id="thread", turn_id="turn", text="hello", client_message_id="message")
        else:
            await service.respond_approval(thread_id="thread", request_id="approval", decision="allow")
        execute.assert_awaited_once()
        assert execute.call_args.args == (name,)
        assert execute.call_args.kwargs["context"] is context
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["resume", "queue"])
async def test_resume_and_queue_handoff_survive_disconnect(tmp_path, monkeypatch, path):
    from lamtools_core.app.live.queue import handle_queue_create_operation
    from lamtools_core.app.live.queue_dispatch import _dispatch_next_queue_item
    from lamtools_core.app.live.turn_start import handle_turn_resume_operation
    from lamtools_core.app.live.background import wait_live_background_tasks

    engine, context = await _context(tmp_path)
    publishing, release, started, finish = (asyncio.Event() for _ in range(4))

    async def operation(request):
        started.set()
        await finish.wait()
        return OperationResult(name="turn.start")

    context.operations.register("turn.start", operation)
    if path == "queue":
        await handle_queue_create_operation(request_id=1, params={
            "thread_id": "thread", "client_message_id": "queued", "input": [{"type": "text", "text": "hello"}],
        }, context=context)
    else:
        async def seed(session):
            await context.persistence.append(session, AppEventInput(
                thread_id="thread", turn_id="turn", method="turn/accepted",
                payload={"status": "paused", "input": [{"type": "text", "text": "hello"}]},
            ))
            await context.persistence.append_run_item(session, RunItemEvent(
                kind="status", thread_id="thread", turn_id="turn", item_id="status", status="paused",
                payload={"type": "turn", "status": "paused"},
            ))
        await context.persistence.write(seed)
        await TurnCoordinator(context.turn_store).ensure_turn(thread_id="thread", turn_id="turn", status="paused")

    original_publish = context.hub.publish

    async def publish(item):
        publishing.set()
        await release.wait()
        await original_publish(item)

    monkeypatch.setattr(context.hub, "publish", publish)
    if path == "queue":
        work = _dispatch_next_queue_item(context=context, thread_id="thread", work_root="", completed_turn_id="")
    else:
        work = handle_turn_resume_operation(request_id=1, params={"thread_id": "thread", "turn_id": "turn", "client_message_id": "resume"}, context=context)
    task = asyncio.create_task(work)
    try:
        await asyncio.wait_for(publishing.wait(), 3)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert started.is_set()
    finally:
        release.set()
        finish.set()
        await asyncio.gather(task, return_exceptions=True)
        live = context.host.runtime_task_registry.task("thread")
        if live is not None:
            await live
        await wait_live_background_tasks()
        context.host.runtime_task_registry.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_resumed_fast_completion_does_not_leave_running_control_model(tmp_path, monkeypatch):
    from lamtools_core.app.live import runtime_tasks
    from lamtools_core.app.live.turn_start import handle_turn_resume_operation
    from lamtools_core.app.live.background import wait_live_background_tasks

    engine, context = await _context(tmp_path)
    context.operations.register("turn.start", AsyncMock(return_value=OperationResult(name="turn.start")))

    async def seed(session):
        await context.persistence.append(session, AppEventInput(
            thread_id="thread", turn_id="turn", method="turn/accepted", payload={"status": "paused"},
        ))
        await context.persistence.append_run_item(session, RunItemEvent(
            kind="status", thread_id="thread", turn_id="turn", item_id="status", status="paused",
            payload={"type": "turn", "status": "paused"},
        ))

    await context.persistence.write(seed)
    await TurnCoordinator(context.turn_store).ensure_turn(thread_id="thread", turn_id="turn", status="paused")
    original_start = runtime_tasks._start_runtime_task

    async def fast_start(**kwargs):
        result = await original_start(**kwargs)
        task = context.host.runtime_task_registry.task("thread")
        if task is not None:
            await task
        return result

    monkeypatch.setattr(runtime_tasks, "_start_runtime_task", fast_start)
    try:
        await handle_turn_resume_operation(request_id=1, params={"thread_id": "thread", "turn_id": "turn"}, context=context)
        assert (await context.turn_store.get_turn("turn")).status == "completed"
    finally:
        await wait_live_background_tasks()
        context.host.runtime_task_registry.clear()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent", [False, True])
async def test_plugin_redelivery_does_not_turn_original_message_into_guidance(tmp_path, concurrent):
    engine, context = await _context(tmp_path)
    finish = asyncio.Event()

    async def operation(request):
        await finish.wait()
        return OperationResult(name="turn.start")

    context.operations.register("turn.start", operation)
    service = LiveTurnService(lambda: context)
    try:
        async def send():
            return await service.deliver_message(thread_id="thread", text="hello", client_message_id="message")
        if concurrent:
            first, retry = await asyncio.gather(send(), send())
        else:
            first, retry = await send(), await send()
        assert retry["turn_id"] == first["turn_id"]
        assert retry["mode"] == "started"
        async with context.session_factory() as session:
            events = await context.persistence.list_thread(session, thread_id="thread")
        received = [item for item in events if item.client_message_id == "message" and item.method in {"turn/accepted", "turn/started", "turn/steered"}]
        assert [item.method for item in received] == ["turn/accepted"]
    finally:
        finish.set()
        live = context.host.runtime_task_registry.task("thread")
        if live is not None:
            await live
        context.host.runtime_task_registry.clear()
        await engine.dispose()
