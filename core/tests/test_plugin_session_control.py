"""user:“宿主能力补齐和接口完善与文档更新”+(会话契约必须经过真实桌面接收、队列和持久事件路径验收)。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from lamtools_core.app.event_store import AppEventInput
from lamtools_core.app.operation_catalog import OperationResult
from lamtools_core.app.plugin_sessions import PluginSessionService, install_plugin_session_services
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.sessions import SESSIONS, SessionError
from lamtools_core.runtime import RuntimeTaskRegistry
from .test_core_live import _context, AppEventRow, ThreadSnapshotRow


@pytest.fixture
async def host(tmp_path):
    engine, context = await _context(tmp_path)
    context.host.runtime_task_registry = RuntimeTaskRegistry()
    service = PluginSessionService(lambda: context, poll_interval=0.005)
    try:
        yield context, service
    finally:
        service.shutdown()
        from lamtools_core.app.live.background import wait_live_background_tasks
        await wait_live_background_tasks()
        await engine.dispose()


async def append(context, session_id, method, payload=None, turn_id=None):
    async def write(db):
        return await context.persistence.append(db, AppEventInput(
            thread_id=session_id, method=method, payload=payload or {}, turn_id=turn_id,
        ))
    return await context.persistence.write(write)


@pytest.mark.asyncio
async def test_installed_contract_uses_live_host_and_creates_real_thread(host, tmp_path):
    context, _ = host
    root = PluginContext(tmp_path)
    service = install_plugin_session_services(root, lambda: context)
    try:
        assert root.require_service("live_turn_service") is not None
        reference = root.bind_service(SESSIONS)
        state = await reference.call("create", session_id="created", title="Demo")
        assert state.session_id == "created" and state.status == "idle" and state.last_event_seq == 1
        assert await reference.call("state", "created") == state
        page = await service.events("created")
        assert page.events[0]["method"] == "thread/started"
    finally:
        service.shutdown()


@pytest.mark.asyncio
async def test_create_existing_session_cannot_reset_its_state(host):
    _, service = host
    first = await service.create(session_id="s", title="original")
    with pytest.raises(SessionError, match="already-exists"):
        await service.create(session_id="s", title="replacement")
    assert (await service.state("s")).last_event_seq == first.last_event_seq


@pytest.mark.asyncio
async def test_queued_receipt_is_durable_not_a_completion_and_retry_returns_original(host):
    _, service = host
    await service.create(session_id="s")
    first = await service.prompt("s", request_id="request", text="first", mode="queue")
    again = await service.prompt("s", request_id="request", text="changed", mode="steer")
    assert first.accepted and not first.completed and first.disposition == "queued"
    assert first.event_seq == again.event_seq and first.queue_item_id == again.queue_item_id
    page = await service.events("s")
    queued = [event for event in page.events if event["method"] == "queue/itemAccepted"]
    assert len(queued) == 1 and queued[0]["payload"]["input"][0]["text"] == "first"
    assert (await service.state("s")).queued_count == 1
    assert (await service.wait("s", timeout=0)).reason == "timeout"


@pytest.mark.asyncio
async def test_concurrent_message_retries_share_one_receipt(host):
    _, service = host
    await service.create(session_id="s")
    results = await asyncio.gather(*(service.prompt("s", request_id="same", text="hello") for _ in range(8)))
    assert len({receipt.event_seq for receipt in results}) == 1
    assert (await service.state("s")).queued_count == 1


@pytest.mark.asyncio
async def test_idle_queue_wakes_existing_runtime_and_writes_desktop_user_projection(host):
    context, service = host
    async def run(request):
        return OperationResult(request.name, payload={"text": "finished"})
    context.operations.register("turn.start", run)
    await service.create(session_id="s")
    receipt = await service.prompt("s", request_id="wake", text="hello")
    from lamtools_core.app.live.background import wait_live_background_tasks
    await wait_live_background_tasks()
    assert receipt.accepted and receipt.disposition == "queued" and receipt.wake_error is None
    state = await service.state("s")
    assert state.queued_count == 0
    page = await service.events("s", limit=100)
    assert any(e["method"] == "turn/accepted" for e in page.events)
    async with context.session_factory() as db:
        snapshot = await context.persistence.load(db, "s")
    assert any(item.get("type") == "userMessage" for item in snapshot.get("items", {}).values())


@pytest.mark.asyncio
async def test_running_steer_is_recorded_by_shared_live_handler_and_deduplicated(host):
    context, service = host
    await service.create(session_id="s")
    await append(context, "s", "turn/started", {"status": "running", "type": "turn"}, "turn-a")
    running = asyncio.create_task(asyncio.Event().wait())
    context.host.runtime_task_registry.register("s", running, run_id="turn-a", turn_id="turn-a")
    try:
        first = await service.prompt("s", request_id="guide", text="change it", mode="steer")
        second = await service.prompt("s", request_id="guide", text="change it", mode="steer")
        assert first.disposition == "steered" and first.turn_id == "turn-a"
        assert first.event_seq == second.event_seq
        assert (await service.state("s")).queued_count == 0
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
async def test_queue_during_running_turn_does_not_become_steering(host):
    context, service = host
    await service.create(session_id="s")
    await append(context, "s", "turn/started", {"status": "running", "type": "turn"}, "turn-a")
    context.host.runtime_task_registry.accept_run("s", "run-a", turn_id="turn-a")
    receipt = await service.prompt("s", request_id="next", text="later", mode="queue")
    assert receipt.disposition == "queued"
    assert not any(e["method"] == "turn/steered" for e in (await service.events("s")).events)
    context.host.runtime_task_registry.release_run("s", run_id="run-a")


@pytest.mark.asyncio
async def test_paused_state_is_blocked_and_message_remains_queued(host):
    context, service = host
    await service.create(session_id="s")
    await append(context, "s", "turn/started", {"status": "paused", "type": "turn"}, "paused")
    state = await service.state("s")
    assert state.status == "paused" and state.paused_turn_id == "paused"
    assert (await service.wait("s", timeout=1)).reason == "blocked"
    assert (await service.prompt("s", request_id="next", text="later")).disposition == "queued"


@pytest.mark.asyncio
async def test_queue_edit_and_delete_use_existing_handlers(host):
    _, service = host
    await service.create(session_id="s")
    receipt = await service.prompt("s", request_id="one", text="before")
    assert (await service.update_queue("s", receipt.queue_item_id, text="after")).applied
    edited = (await service.events("s")).events[-1]
    assert edited["method"] == "queue/itemUpdated" and edited["payload"]["input"][0]["text"] == "after"
    assert (await service.update_queue("s", receipt.queue_item_id, delete=True)).applied
    assert (await service.state("s")).queued_count == 0
    assert not (await service.update_queue("s", receipt.queue_item_id, text="too late")).applied


@pytest.mark.asyncio
async def test_cancel_targets_exact_turn_and_keeps_pending_queue(host):
    context, service = host
    await service.create(session_id="s")
    await append(context, "s", "turn/started", {"status": "running", "type": "turn"}, "turn-a")
    context.host.runtime_task_registry.accept_run("s", "run-a", turn_id="turn-a")
    await service.prompt("s", request_id="next", text="keep")
    stale = await service.cancel("s", turn_id="older")
    assert stale.status == "stale_target"
    assert context.host.runtime_task_registry.active_run_id("s") == "run-a"
    accepted = await service.cancel("s", turn_id="turn-a")
    assert accepted.status == "cancelling" and not accepted.completed
    from lamtools_core.app.live.background import wait_live_background_tasks
    await wait_live_background_tasks()
    assert (await service.state("s")).queued_count == 1


@pytest.mark.asyncio
async def test_events_are_exclusive_cursor_pages_of_persistent_records(host):
    context, service = host
    await service.create(session_id="s")
    await append(context, "s", "custom/one")
    await append(context, "s", "custom/two")
    first = await service.events("s", after_seq=0, limit=2)
    assert [e["seq"] for e in first.events] == [1, 2] and first.has_more
    second = await service.events("s", after_seq=first.next_after_seq, limit=2)
    assert [e["seq"] for e in second.events] == [3] and not second.has_more
    assert (await service.events("s", after_seq=3)).events == ()


@pytest.mark.asyncio
async def test_missing_history_and_future_cursor_fail_explicitly(host):
    context, service = host
    await service.create(session_id="s")
    await append(context, "s", "custom/one")
    await append(context, "s", "custom/two")
    async def remove(db):
        await db.execute(delete(AppEventRow).where(AppEventRow.thread_id == "s", AppEventRow.seq == 2))
    await context.persistence.write(remove)
    with pytest.raises(SessionError, match="cursor-expired"):
        await service.events("s", after_seq=1)
    with pytest.raises(SessionError, match="invalid-cursor"):
        await service.events("s", after_seq=100)


@pytest.mark.asyncio
async def test_event_byte_budget_refuses_oversized_record_without_advancing_cursor(host):
    context, service = host
    await service.create(session_id="s")
    await append(context, "s", "custom/large", {"text": "x" * 2000})
    with pytest.raises(SessionError, match="event-too-large"):
        await service.events("s", after_seq=1, max_bytes=1024)


@pytest.mark.asyncio
async def test_follow_reads_commits_without_hub_delivery_and_excludes_transient_output(host):
    context, service = host
    await service.create(session_id="s")
    feed = service.follow("s", after_seq=1)
    pending = asyncio.create_task(anext(feed))
    await context.hub.publish({"thread_id": "s", "method": "transient", "seq": 0})
    event = await append(context, "s", "custom/persisted", {"text": "saved"})
    frame = await pending
    assert frame["seq"] == event.seq and frame["method"] == "custom/persisted"
    await feed.aclose()
    assert not context.hub._subscribers


@pytest.mark.asyncio
async def test_shutdown_wakes_follow_and_wait_and_rejects_new_calls(host):
    context, service = host
    await service.create(session_id="s")
    context.host.runtime_task_registry.accept_run("s", "active", turn_id="active")
    feed = service.follow("s", after_seq=1)
    pending = asyncio.create_task(anext(feed))
    waiter = asyncio.create_task(service.wait("s", timeout=1))
    await asyncio.sleep(0.02)
    service.shutdown()
    with pytest.raises(StopAsyncIteration):
        await pending
    assert (await waiter).reason == "closed"
    with pytest.raises(SessionError, match="closed"):
        await service.state("s")
    context.host.runtime_task_registry.release_run("s", run_id="active")


@pytest.mark.asyncio
async def test_wait_cancellation_does_not_cancel_the_agent(host):
    context, service = host
    await service.create(session_id="s")
    context.host.runtime_task_registry.accept_run("s", "active", turn_id="active")
    waiter = asyncio.create_task(service.wait("s", timeout=1))
    await asyncio.sleep(0.01)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert context.host.runtime_task_registry.active_run_id("s") == "active"
    context.host.runtime_task_registry.release_run("s", run_id="active")


@pytest.mark.asyncio
async def test_unknown_session_cannot_be_implicitly_created_by_state_or_prompt(host):
    _, service = host
    with pytest.raises(SessionError, match="not-found"):
        await service.state("missing")
    with pytest.raises(SessionError, match="not-found"):
        await service.prompt("missing", request_id="one", text="hello")


@pytest.mark.asyncio
async def test_malformed_live_response_is_not_reported_as_success(host, monkeypatch):
    context, service = host
    await service.create(session_id="s")
    async def invalid(*args, **kwargs):
        return SimpleNamespace(response={})
    monkeypatch.setattr(context.host, "execute", invalid)
    with pytest.raises(SessionError, match="invalid-response"):
        await service.prompt("s", request_id="bad", text="hello")


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"text": " "}, {"mode": "automatic"}, {"request_id": ""}])
async def test_invalid_prompt_input_is_rejected_before_mutation(host, kwargs):
    _, service = host
    await service.create(session_id="s")
    request = {"request_id": "r", "text": "hello", **kwargs}
    with pytest.raises((ValueError, TypeError)):
        await service.prompt("s", **request)
    assert (await service.state("s")).last_event_seq == 1


@pytest.mark.asyncio
async def test_receipt_survives_recreating_the_facade(host):
    context, service = host
    await service.create(session_id="s")
    first = await service.prompt("s", request_id="retry", text="original")
    replacement = PluginSessionService(lambda: context)
    try:
        retry = await replacement.prompt("s", request_id="retry", text="different")
        assert (first.message_id, first.event_seq, first.queue_item_id) == (retry.message_id, retry.event_seq, retry.queue_item_id)
        assert (await replacement.state("s")).queued_count == 1
    finally:
        replacement.shutdown()


@pytest.mark.asyncio
async def test_create_racing_with_another_writer_cannot_reset_the_winner(host, monkeypatch):
    context, service = host
    execute = service._execute
    async def racing(ctx, sid, name, params):
        await context.host.execute("thread.start", request_id=None, params={"thread_id": sid, "title": "winner"}, context=context)
        return await execute(ctx, sid, name, params)
    monkeypatch.setattr(service, "_execute", racing)
    with pytest.raises(SessionError):
        await service.create(session_id="s", title="loser")
    events = (await service.events("s")).events
    assert len(events) == 1 and events[0]["payload"]["title"] == "winner"


@pytest.mark.asyncio
async def test_create_racing_with_zero_revision_project_placeholder_does_not_overwrite_it(host, monkeypatch):
    context, service = host
    execute = service._execute
    async def racing(ctx, sid, name, params):
        async def add_placeholder(db):
            db.add(ThreadSnapshotRow(thread_id=sid, snapshot_seq=0, snapshot_json={"session": {"title": "project placeholder"}}))
        await context.persistence.write(add_placeholder)
        return await execute(ctx, sid, name, params)
    monkeypatch.setattr(service, "_execute", racing)
    with pytest.raises(SessionError):
        await service.create(session_id="s", title="loser")
    async with context.session_factory() as db:
        snapshot = await context.persistence.load_metadata(db, "s")
    assert snapshot["session"]["title"] == "project placeholder" and not snapshot.get("snapshot_seq")


@pytest.mark.asyncio
async def test_explicit_steer_refusal_falls_back_to_durable_queue(host, monkeypatch):
    context, service = host
    await service.create(session_id="s")
    await append(context, "s", "turn/started", {"type": "turn", "status": "running"}, "turn-a")
    execute = service._execute
    async def refusing(ctx, sid, name, params):
        if name == "turn.steer":
            return {"applied": False, "reason": "active_turn_mismatch"}
        return await execute(ctx, sid, name, params)
    monkeypatch.setattr(service, "_execute", refusing)
    receipt = await service.prompt("s", request_id="race", text="preserve it", mode="steer")
    assert receipt.disposition == "queued" and receipt.accepted


@pytest.mark.asyncio
async def test_cancel_waiting_prompt_finishes_acceptance_then_retry_deduplicates(host, monkeypatch):
    context, service = host
    await service.create(session_id="s")
    entered, release = asyncio.Event(), asyncio.Event()
    execute = service._execute
    async def held(ctx, sid, name, params):
        if name == "queue.create":
            entered.set()
            await release.wait()
        return await execute(ctx, sid, name, params)
    monkeypatch.setattr(service, "_execute", held)
    task = asyncio.create_task(service.prompt("s", request_id="cancelled-request", text="accepted"))
    await entered.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    receipt = await service.prompt("s", request_id="cancelled-request", text="retry")
    assert receipt.accepted and (await service.state("s")).queued_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{"after_seq": True}, {"after_seq": -1}, {"limit": 501}, {"max_bytes": 0}])
async def test_invalid_event_bounds_are_explicit(host, options):
    _, service = host
    await service.create(session_id="s")
    with pytest.raises(ValueError):
        await service.events("s", **options)


def test_desktop_boot_publishes_session_contract_before_plugin_start(tmp_path, monkeypatch):
    import json
    from functools import partial
    from fastapi.testclient import TestClient
    from lamtools_core.app.http_agent_app import create_core_agent_http_app
    monkeypatch.setattr("lamtools_core.app.http_agent_app.warm_command_shell", lambda: None)
    monkeypatch.setattr("lamtools_core.runtime.power.apply_keep_awake", lambda: None)
    plugin_root = tmp_path / "plugins" / "session-consumer"
    plugin_root.mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(json.dumps({"name": "session-consumer", "version": "1", "backend": "./backend.py"}))
    (plugin_root / "backend.py").write_text('''
from lamtools_core.plugin_system import SESSIONS
class Runtime:
    def start(self, context):
        self.sessions = context.bind_service(SESSIONS)
def create_plugin(context):
    return Runtime()
''')
    app = create_core_agent_http_app(core_db=tmp_path / "boot.db", data_dir=tmp_path / "data",
                                     work_root=tmp_path / "project", plugin_roots=[tmp_path / "plugins"])
    with TestClient(app) as client:
        state = app.state.core_agent_app_state
        runtime = next(h for h in state["plugin_runtimes"] if h.plugin.name == "session-consumer")
        assert runtime.state == "ready", runtime.error
        service = state["plugin_session_service"]
        created = client.portal.call(partial(service.create, session_id="boot-created", title="Plugin session"))
        assert created.session_id == "boot-created"
        assert client.portal.call(runtime.value.sessions.call, "state", "boot-created") == created
    assert service._closed.is_set()
