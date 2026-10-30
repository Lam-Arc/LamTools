"""user:“宿主能力补齐和接口完善与文档更新”+(压缩接口须共用桌面执行、排他、取消与持久事件，不能伪装成功)。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from lamtools_core.app.live_member import DefaultCoreLiveMemberHooks
from lamtools_core.app.plugin_sessions import install_plugin_session_services
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.runtime import RuntimeState
from .test_core_live import _context


@pytest.fixture
async def env(tmp_path):
    engine, live = await _context(tmp_path)
    root = PluginContext(tmp_path)
    sessions = install_plugin_session_services(root, lambda: live)
    root._begin_registration_scope("example", 1)
    callbacks = []
    async def default(**kwargs):
        callbacks.append(kwargs)
        return {"status": "not_needed", "summary": "", "reason": "empty"}
    class Hooks(DefaultCoreLiveMemberHooks):
        action = staticmethod(default)
        def command_action_handlers(self):
            return {"compact": self.action}
    hooks = Hooks()
    live.host.member_hooks = hooks
    await sessions.create(session_id="s")
    try:
        yield root, live, sessions, hooks, callbacks
    finally:
        sessions.shutdown()
        await root._registration_scope.dispose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_live_path_noop_records_control_events_and_pins_directory(env):
    root, live, sessions, _, calls = env
    api = root.compaction
    original = root.work_root
    root.work_root = Path(original) / "other"
    result = await api.compact_now("s", expected_revision=1)
    assert result.status == "not_needed" and result.summary == ""
    assert result.session_id == "s" and result.reason == "empty"
    assert calls[0]["work_root"] == str(original)
    assert live.host.runtime_task_registry.active_run_id("s") is None
    events = (await sessions.events("s")).events
    assert any(e["payload"].get("status") == "completed" for e in events)
    assert (await sessions.state("s")).last_event_seq > 1


@pytest.mark.asyncio
async def test_actual_summarization_persists_summary_and_preserves_source_after_reopen(env, tmp_path):
    from lamtools_core.app import open_core_app_db
    from lamtools_core.app.command_execution import compact_runtime_history, _load_effective_compaction_history
    from lamtools_core.llm import ChatMessage
    from .test_kernel import CapturingLLMClient
    root, _, _, hooks, _ = env
    db_path = str(tmp_path / "runtime.db")
    db = await open_core_app_db(db_path)
    rows = [ChatMessage(role=role, content=f"{role} {i} " + "x" * 1000).to_dict()
            for i in range(20) for role in ("user", "assistant")]
    try:
        await db.runtime_state_store.save_checkpoint(RuntimeState(session_id="s", metadata={
            "runtime_context_metrics": {"model_id": "mock-model", "context_window_tokens": 50000,
                                        "total_context_window_tokens": 50000, "context_usage_prompt_tokens": 45000}}), rows)
        async def compact(**kwargs):
            return await compact_runtime_history(runtime_state_store=db.runtime_state_store,
                thread_id=kwargs["thread_id"], llm_client=CapturingLLMClient(), model="mock-model", on_event=kwargs["on_event"])
        hooks.action = compact
        result = await root.compaction.compact_now("s", expected_revision=1)
        assert result.status == "compacted" and result.summary
        assert result.before_tokens > result.after_tokens
    finally:
        await db.close()
    reopened = await open_core_app_db(db_path)
    try:
        store = reopened.runtime_state_store
        saved = await store.get("s")
        assert saved.metadata["context_compaction"]["summary"] == result.summary
        assert await store.get_history("s") == rows
        view = await _load_effective_compaction_history(store, "s", saved.metadata)
        assert len(view) < len(rows)
        assert sum(m.metadata.get("key") == "context_compaction_summary" for m in view) == 1
        assert not any(m.role == "assistant" and m.content == rows[1]["content"] for m in view)
    finally:
        await reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", [None, True, -1, 1.5, "1"])
async def test_revision_must_be_explicit_integer(env, revision):
    root, _, sessions, _, calls = env
    from lamtools_core.plugin_system import CompactionError
    with pytest.raises(CompactionError) as error:
        await root.compaction.compact_now("s", expected_revision=revision)
    assert error.value.code == "compaction/invalid-revision" and not error.value.may_have_changed
    assert not calls and (await sessions.state("s")).last_event_seq == 1


@pytest.mark.asyncio
async def test_stale_revision_and_unknown_session_do_not_run(env):
    root, _, sessions, _, calls = env
    from lamtools_core.plugin_system import CompactionError
    for sid, revision, code in [("s", 0, "compaction/conflict"), ("missing", 0, "compaction/not-found")]:
        with pytest.raises(CompactionError) as error:
            await root.compaction.compact_now(sid, expected_revision=revision)
        assert error.value.code == code
    assert not calls and (await sessions.state("s")).last_event_seq == 1


@pytest.mark.asyncio
async def test_overlapping_turn_and_compaction_rejected_and_queue_stays_durable(env):
    root, live, sessions, hooks, _ = env
    from lamtools_core.plugin_system import CompactionError
    started, release = asyncio.Event(), asyncio.Event()
    async def block(**kwargs):
        started.set()
        await release.wait()
        return {"status": "not_needed"}
    hooks.action = block
    task = asyncio.create_task(root.compaction.compact_now("s", expected_revision=1))
    try:
        await asyncio.wait_for(started.wait(), 5)
        revision = (await sessions.state("s")).last_event_seq
        with pytest.raises(CompactionError) as error:
            await root.compaction.compact_now("s", expected_revision=revision)
        assert error.value.code == "compaction/busy"
        response = await live.host.execute("turn.start", request_id=None,
            params={"thread_id": "s", "input": [{"type": "text", "text": "later"}]}, context=live)
        assert response.response["error"]["data"]["code"] == "SESSION_BUSY"
        assert (await sessions.prompt("s", request_id="queued", text="later")).accepted
    finally:
        release.set()
        await task
    assert (await sessions.state("s")).queued_count == 1
    assert live.host.runtime_task_registry.active_run_id("s") is None


@pytest.mark.asyncio
async def test_caller_cancellation_is_not_silent_success_and_releases_claim(env):
    root, live, sessions, hooks, _ = env
    started = asyncio.Event()
    async def block(**kwargs):
        started.set()
        await asyncio.Event().wait()
    hooks.action = block
    task = asyncio.create_task(root.compaction.compact_now("s", expected_revision=1))
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert live.host.runtime_task_registry.active_run_id("s") is None
    assert any(e["payload"].get("status") == "cancelled" for e in (await sessions.events("s")).events)


@pytest.mark.asyncio
async def test_stop_revokes_new_calls_but_drains_admitted_call(env):
    root, _, _, hooks, _ = env
    from lamtools_core.plugin_system.services import ServiceError
    started, release = asyncio.Event(), asyncio.Event()
    async def block(**kwargs):
        started.set()
        await release.wait()
        return {"status": "not_needed"}
    hooks.action = block
    api = root.compaction
    task = asyncio.create_task(api.compact_now("s", expected_revision=1))
    stop = None
    try:
        await asyncio.wait_for(started.wait(), 5)
        root._registration_scope.revoke()
        stop = asyncio.create_task(root._registration_scope.dispose())
        await asyncio.sleep(0)
        assert not stop.done()
        with pytest.raises(ServiceError):
            await api.compact_now("s", expected_revision=1)
    finally:
        release.set()
        await task
        if stop:
            await stop


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"status": "failed"}, {"status": "unknown"}, {"status": {}}, {"status": "not_needed", "session_id": "another"}, {"status": "compacted", "before_tokens": True}])
async def test_bad_or_failed_backend_result_is_explicit_error(env, payload):
    root, _, _, hooks, _ = env
    from lamtools_core.plugin_system import CompactionError
    async def action(**kwargs):
        return payload
    hooks.action = action
    with pytest.raises(CompactionError) as error:
        await root.compaction.compact_now("s", expected_revision=1)
    assert error.value.may_have_changed


@pytest.mark.asyncio
async def test_backend_failure_is_recorded_and_not_reported_as_applied(env):
    root, live, sessions, hooks, _ = env
    from lamtools_core.plugin_system import CompactionError
    async def fail(**kwargs):
        raise RuntimeError("summary failed")
    hooks.action = fail
    with pytest.raises(CompactionError) as error:
        await root.compaction.compact_now("s", expected_revision=1)
    assert error.value.code == "compaction/operation-failed" and error.value.may_have_changed
    assert live.host.runtime_task_registry.active_run_id("s") is None
    assert any(e["payload"].get("status") == "failed" for e in (await sessions.events("s")).events)


@pytest.mark.asyncio
async def test_host_shutdown_blocks_new_request(env):
    root, _, sessions, _, calls = env
    from lamtools_core.plugin_system import CompactionError
    sessions.shutdown()
    with pytest.raises(CompactionError) as error:
        await root.compaction.compact_now("s", expected_revision=1)
    assert error.value.code == "compaction/closed" and not calls


@pytest.mark.asyncio
async def test_final_dispatch_revision_check_catches_concurrent_change(env, monkeypatch):
    from lamtools_core.app.event_store import AppEventInput
    from lamtools_core.plugin_system import CompactionError
    root, live, sessions, _, calls = env
    execute = sessions._execute
    async def changed(context, sid, name, params):
        async def write(db):
            await live.persistence.append(db, AppEventInput(thread_id=sid, method="thread/updated", payload={"title": "changed"}))
        await live.persistence.write(write)
        return await execute(context, sid, name, params)
    monkeypatch.setattr(sessions, "_execute", changed)
    with pytest.raises(CompactionError) as error:
        await root.compaction.compact_now("s", expected_revision=1)
    assert error.value.code == "compaction/conflict" and not error.value.may_have_changed
    assert not calls


@pytest.mark.asyncio
async def test_paused_session_cannot_be_compacted(env):
    from lamtools_core.app.event_store import AppEventInput
    from lamtools_core.plugin_system import CompactionError
    root, live, sessions, _, calls = env
    async def write(db):
        await live.persistence.append(db, AppEventInput(thread_id="s", turn_id="paused", method="turn/started", payload={"status": "paused", "type": "turn"}))
    await live.persistence.write(write)
    revision = (await sessions.state("s")).last_event_seq
    with pytest.raises(CompactionError) as error:
        await root.compaction.compact_now("s", expected_revision=revision)
    assert error.value.code == "compaction/busy" and not calls


@pytest.mark.asyncio
async def test_desktop_cancel_returns_explicit_cancelled_result(env):
    root, live, sessions, hooks, _ = env
    started = asyncio.Event()
    async def block(**kwargs):
        started.set()
        await asyncio.Event().wait()
    hooks.action = block
    task = asyncio.create_task(root.compaction.compact_now("s", expected_revision=1))
    try:
        await asyncio.wait_for(started.wait(), 5)
        receipt = await sessions.cancel("s")
        assert receipt.status == "cancelling"
        result = await asyncio.wait_for(asyncio.shield(task), 5)
        assert result.status == "cancelled"
        assert live.host.runtime_task_registry.active_run_id("s") is None
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_compaction_requires_managed_scope_and_installed_host(tmp_path):
    root = PluginContext(tmp_path)
    root._begin_registration_scope("example", 1)
    with pytest.raises(LookupError):
        _ = root.compaction
