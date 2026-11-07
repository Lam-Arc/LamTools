"""user:“继续，无人值守模式，不要停下来”+(根代理句柄复用原桌面会话、接收回执和队列，不另建运行循环)。"""
import asyncio
import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize("operation",["create","attach","state","wait","events"])
@pytest.mark.parametrize("change",["shutdown","store","scope"])
async def test_root_agent_wait_boundaries_recheck_host_without_orphan_creation(env,monkeypatch,operation,change):
    # user:“复用原宿主权威”+(根代理读取等待后复核原宿主与启动代，创建不能在失效读取后留下旧存储孤立记录)。
    from lamtools_core.plugin_system.agent_access import AgentAccessError
    from lamtools_core.plugin_system.sessions import SessionError
    from lamtools_core.plugin_system.services import ServiceError
    ctx, store, sessions, _ = env
    api = ctx.agents
    host = sessions._context().host
    handle = None if operation == "create" else await api.create(request_id="existing")
    before = [sid for sid,_ in (await store.scan_readonly(after_id="",scan_limit=1000))[0]]
    entered, release = asyncio.Event(), asyncio.Event()
    if operation in {"create","attach"}:
        original = store.get_readonly
        target, name = store, "get_readonly"
    else:
        original = getattr(sessions,operation)
        target, name = sessions, operation
    async def gated(*args,**kwargs):
        result = await original(*args,**kwargs)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(target,name,gated)
    if operation == "create":
        work = api.create(request_id="must-not-leave-record")
    elif operation == "attach":
        work = api.attach(handle.session_id)
    elif operation == "wait":
        work = handle.wait(timeout=0.1)
    else:
        work = getattr(handle,operation)()
    task = asyncio.create_task(work)
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change == "shutdown":
            sessions.shutdown()
        elif change == "store":
            host.session_store = object()
        else:
            ctx._registration_scope.revoke()
        release.set()
        with pytest.raises((AgentAccessError,SessionError,ServiceError)) as error:
            await asyncio.wait_for(task,3)
        assert error.value.code == {"shutdown":"session/closed","store":"agent/host-changed","scope":"service/scope-closed"}[change]
        assert [sid for sid,_ in (await store.scan_readonly(after_id="",scan_limit=1000))[0]] == before
    finally:
        host.session_store = store
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_agent_create_is_durable_idempotent_and_messages_use_native_receipts(env):
    ctx, store, _, project = env
    handle = await ctx.agents.create(request_id="create-one", title="Plugin agent")
    retry = await ctx.agents.create(request_id="create-one", title="Changed retry")
    assert retry.session_id == handle.session_id
    assert (await ctx.agent_loop.attach(handle.session_id)).session_id == handle.session_id
    record = await store.get_readonly(handle.session_id)
    assert record.title == "Plugin agent" and record.metadata["work_root"] == str(project)
    first = await handle.followup(request_id="message-one", text="Do this")
    again = await retry.followup(request_id="message-one", text="Changed retry")
    assert first.accepted and not first.completed
    assert first.message_id == again.message_id
    assert (await handle.state()).queued_count == 1
    assert len([event for event in (await handle.events()).events if event["method"] == "thread/started"]) == 1


@pytest.mark.asyncio
async def test_agent_namespace_visibility_and_stopped_handles_are_enforced(env):
    ctx, _, _, project = env
    handle = await ctx.agents.create(request_id="create-one")
    other = ctx.for_work_root(project)
    other._registration_scope = None
    other._begin_registration_scope("other", 1)
    try:
        with pytest.raises(Exception):
            await other.agents.attach(handle.session_id)
        with pytest.raises(Exception):
            await ctx.agents.attach("hidden")
        await ctx._registration_scope.dispose()
        with pytest.raises(Exception):
            await handle.state()
        ctx._begin_registration_scope("example", 2)
        restored = await ctx.agents.attach(handle.session_id)
        assert (await restored.state()).session_id == handle.session_id
    finally:
        await other._registration_scope.dispose()


@pytest.mark.asyncio
async def test_dispose_revokes_handle_but_does_not_delete_history_and_idle_resume_is_rejected(env):
    ctx, store, _, _ = env
    handle = await ctx.agents.create(request_id="create-one")
    with pytest.raises(Exception):
        await handle.resume(request_id="resume-idle")
    await handle.dispose()
    assert await store.get_readonly(handle.session_id) is not None
    with pytest.raises(Exception):
        await handle.followup(request_id="late", text="Late")


@pytest.mark.asyncio
async def test_creation_repairs_native_event_handoff_with_same_request_after_failure(env, monkeypatch):
    from lamtools_core.plugin_system.agent_access import AgentAccessError
    ctx, _, sessions, _ = env
    execute = sessions._execute
    async def failed(*args, **kwargs):
        raise RuntimeError("simulated handoff failure")
    monkeypatch.setattr(sessions, "_execute", failed)
    with pytest.raises(AgentAccessError) as error:
        await ctx.agents.create(request_id="recover", title="Original title")
    assert error.value.may_have_changed
    monkeypatch.setattr(sessions, "_execute", execute)
    handle = await ctx.agents.create(request_id="recover", title="Changed retry")
    assert (await ctx.session_title.get(handle.session_id))["title"] == "Original title"
    assert len([row for row in (await handle.events()).events if row["method"] == "thread/started"]) == 1


@pytest.mark.asyncio
async def test_missing_original_project_is_rejected_before_agent_creation(env):
    from lamtools_core.plugin_system.agent_access import AgentAccessError
    ctx, _, _, project = env
    missing = project / "missing"
    with pytest.raises(AgentAccessError) as error:
        await ctx.for_work_root(missing).agents.create(request_id="missing")
    assert error.value.code == "agent/missing-project" and not missing.exists()


@pytest.mark.asyncio
async def test_root_agent_resume_continues_real_history_and_retry_does_not_start_another_turn(tmp_path):
    import asyncio
    from lamtools_core.app import open_core_app_db
    from lamtools_core.app.core_session_store import CoreDbSessionStore
    from lamtools_core.app.plugin_sessions import install_plugin_session_services
    from lamtools_core.app.live_operations import handle_turn_pause_operation, wait_live_background_tasks
    from lamtools_core.plugin_system import PluginContext
    from .test_same_turn_resume import context_for, ScriptedModel
    models = tmp_path / ".lam" / "config" / "models"
    models.mkdir(parents=True)
    (models / "fixture.jsonc").write_text('{"model_id":"fixture","capability":"text"}', encoding="utf8")
    db = await open_core_app_db(tmp_path / "agent.db")
    model = ScriptedModel("stream")
    live = await context_for(db, tmp_path, model)
    live.host.session_store = CoreDbSessionStore(lambda: db)
    ctx = PluginContext(tmp_path, data_dir=tmp_path / "data")
    service = install_plugin_session_services(ctx, lambda: live)
    ctx._begin_registration_scope("root-agent", 1)
    try:
        handle = await ctx.agents.create(request_id="root")
        await handle.followup(request_id="first", text="Do the task")
        await asyncio.wait_for(model.blocked.wait(), 10)
        state = await handle.state()
        await handle_turn_pause_operation(request_id=None, params={"thread_id": handle.session_id, "turn_id": state.active_turn_id}, context=live)
        await wait_live_background_tasks()
        paused = await handle.state()
        assert paused.paused_turn_id == state.active_turn_id
        await handle.resume(request_id="resume-once")
        async with asyncio.timeout(10):
            while live.runtime_task_registry.is_running(handle.session_id):
                await asyncio.sleep(0.005)
        await wait_live_background_tasks()
        assert len(model.requests) == 2
        retry = await handle.resume(request_id="resume-once")
        assert retry["deduplicated"] and len(model.requests) == 2
        history = await db.runtime_state_store.get_history(handle.session_id)
        assert len([row for row in history if row["role"] == "user"]) == 1
        assert "INCOMPLETE_FRAGMENT" not in str(history)
    finally:
        current = locals().get("handle")
        task = live.runtime_task_registry.task(current.session_id) if current is not None else None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await wait_live_background_tasks()
        service.shutdown()
        await ctx._registration_scope.dispose()
        await db.close()
