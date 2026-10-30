"""user:“继续”+(单成员中断/恢复须复用原持久状态，不中断兄弟，也不能用全新运行冒充继续)。"""
import asyncio

import pytest

from lamtools_core.runtime import RuntimeState
from .test_plugin_subagent_access import setup
from .test_plugin_working_directory import env
from lamtools_core.sub_agent_supervisor import find_sub_agent_supervisor


@pytest.mark.asyncio
async def test_interrupt_targets_only_one_owned_member_and_resume_requires_committed_state(setup):
    from lamtools_core.plugin_system.subagent_access import SubagentAccessError
    ctx, store, runner, _, _ = setup
    runner.state_store = store._db_provider().runtime_state_store
    started = {name: asyncio.Event() for name in ("reader", "writer")}
    finished = {name: asyncio.Event() for name in started}
    resumed = asyncio.Event()
    calls = []
    async def run(**kwargs):
        friendly = next(name for name in started if kwargs["agent"].endswith("_" + name))
        sid = f"s:sub:{kwargs['agent']}"
        state = RuntimeState(session_id=sid, status="running", metadata={"turn_id": "logical-" + friendly})
        await runner.state_store.save_checkpoint(state, [{"role": "user", "content": friendly + " committed"}])
        started[friendly].set()
        try:
            await asyncio.Event().wait()
        finally:
            state.status = "cancelled"
            await runner.state_store.save(state)
            finished[friendly].set()
    async def resume_interrupted(**kwargs):
        state = await runner.state_store.get(kwargs["session_id"])
        history = await runner.state_store.get_history(kwargs["session_id"])
        calls.append((kwargs, state, history))
        resumed.set()
        await asyncio.Event().wait()
    runner.run, runner.resume_interrupted = run, resume_interrupted
    for name in started:
        await ctx.subagents.create("s", name, kind="consider", model="test-model", reasoning_level="high")
        await ctx.subagents.message("s", name, request_id="work-" + name, text=name)
        await asyncio.wait_for(started[name].wait(), 3)
    interrupted = await ctx.subagents.interrupt("s", "reader")
    assert interrupted["status"] == "interrupted" and finished["reader"].is_set()
    assert not finished["writer"].is_set()
    assert (await ctx.subagents.get("s", "writer"))["status"] == "running"
    reply = await ctx.subagents.resume("s", "reader")
    assert reply["status"] == "running"
    await asyncio.wait_for(resumed.wait(), 3)
    kwargs, state, history = calls[0]
    assert state.metadata["turn_id"] == "logical-reader"
    assert history[0]["content"] == "reader committed"
    assert kwargs["session_id"].endswith("_reader") and kwargs["prompt"] is None
    with pytest.raises(SubagentAccessError):
        await ctx.subagents.resume("s", "writer")
    await ctx.subagents.close("s", "reader")
    await ctx.subagents.close("s", "writer")


@pytest.mark.asyncio
async def test_resume_without_continuation_provider_does_not_fake_running(setup):
    from lamtools_core.plugin_system.subagent_access import SubagentAccessError
    ctx, _, runner, _, _ = setup
    await ctx.subagents.create("s", "reader", kind="consider", model="test-model", reasoning_level="high")
    await ctx.subagents.message("s", "reader", request_id="work", text="Work")
    await asyncio.wait_for(runner.started.wait(), 3)
    await ctx.subagents.interrupt("s", "reader")
    with pytest.raises(SubagentAccessError):
        await ctx.subagents.resume("s", "reader")
    assert (await ctx.subagents.get("s", "reader"))["status"] == "interrupted"
    assert len(runner.calls) == 1


@pytest.mark.asyncio
async def test_parent_pause_and_live_child_state_block_targeted_resume(setup):
    from lamtools_core.plugin_system.subagent_access import SubagentAccessError
    ctx, store, runner, _, _ = setup
    runner.state_store = store._db_provider().runtime_state_store
    async def resume_interrupted(**kwargs):
        pytest.fail("Parent pause/live child state must prevent resumption")
    runner.resume_interrupted = resume_interrupted
    created = await ctx.subagents.create("s", "reader", kind="consider", model="test-model", reasoning_level="high")
    await ctx.subagents.message("s", "reader", request_id="work", text="Work")
    await asyncio.wait_for(runner.started.wait(), 3)
    await ctx.subagents.interrupt("s", "reader")
    await runner.state_store.save(RuntimeState(session_id=created["sub_session_id"], status="cancelled", metadata={"turn_id": "logical"}))
    supervisor = find_sub_agent_supervisor("s", data_dir=ctx.data_dir)
    supervisor.pause_event.set()
    try:
        with pytest.raises(SubagentAccessError):
            await ctx.subagents.resume("s", "reader")
    finally:
        supervisor.pause_event.clear()
    # user:“继续”+(冷恢复时共享事件可能尚未重建，父会话的持久暂停状态也必须阻止子级恢复)。
    await runner.state_store.save(RuntimeState(session_id="s", status="paused", metadata={"turn_id": "parent-turn"}))
    with pytest.raises(SubagentAccessError):
        await ctx.subagents.resume("s", "reader")
    await runner.state_store.save(RuntimeState(session_id="s", status="completed", metadata={"turn_id": "parent-turn"}))
    await runner.state_store.save(RuntimeState(session_id=created["sub_session_id"], status="running", metadata={"turn_id": "logical"}))
    with pytest.raises(SubagentAccessError):
        await ctx.subagents.resume("s", "reader")
    assert (await ctx.subagents.get("s", "reader"))["status"] == "interrupted"


@pytest.mark.asyncio
async def test_self_interrupt_is_rejected_by_sdk_and_native_operation(setup):
    from lamtools_core.plugin_system.subagent_access import SubagentAccessError
    ctx, _, runner, _, _ = setup
    checked = asyncio.Event()
    async def on_run():
        with pytest.raises(SubagentAccessError) as error:
            await ctx.subagents.interrupt("s", "reader")
        assert error.value.code == "subagent/self-interrupt"
        member = await ctx.subagents.get("s", "reader")
        native = await ctx.operation_catalog.execute("sub_agent.interrupt_member", {"thread_id": "s", "name": member["native_name"]})
        assert native.status == "error"
        checked.set()
    runner.on_run = on_run
    await ctx.subagents.create("s", "reader", kind="consider", model="test-model", reasoning_level="high")
    await ctx.subagents.message("s", "reader", request_id="work", text="Work")
    await asyncio.wait_for(checked.wait(), 3)
    assert (await ctx.subagents.interrupt("s", "reader"))["status"] == "interrupted"


@pytest.mark.asyncio
async def test_existing_session_wide_stop_and_resume_keep_their_original_scope(setup):
    ctx, _, runner, _, _ = setup
    both_started, both_resumed = asyncio.Event(), asyncio.Event()
    async def on_run():
        if len(runner.calls) >= 2:
            both_started.set()
        if len(runner.calls) >= 4:
            both_resumed.set()
    runner.on_run = on_run
    for name in ("reader", "writer"):
        await ctx.subagents.create("s", name, kind="consider", model="test-model", reasoning_level="high")
        await ctx.subagents.message("s", name, request_id="work-" + name, text=name)
    await asyncio.wait_for(both_started.wait(), 3)
    stopped = await ctx.operation_catalog.execute("sub_agent.interrupt", {"thread_id": "s"})
    assert stopped.status == "ok" and len(stopped.payload["items"]) == 2
    assert {row["status"] for row in (await ctx.subagents.list("s"))["items"]} == {"interrupted"}
    resumed = await ctx.operation_catalog.execute("sub_agent.resume", {"thread_id": "s"})
    assert resumed.status == "ok" and len(resumed.payload["items"]) == 2
    await asyncio.wait_for(both_resumed.wait(), 3)


@pytest.mark.asyncio
async def test_foreign_plugin_and_missing_state_do_not_resume_or_stop_a_member(setup):
    from lamtools_core.plugin_system.subagent_access import SubagentAccessError
    ctx, store, runner, _, project = setup
    async def resume_interrupted(**kwargs):
        pytest.fail("No committed child state exists")
    runner.state_store = store._db_provider().runtime_state_store
    runner.resume_interrupted = resume_interrupted
    await ctx.subagents.create("s", "reader", kind="consider", model="test-model", reasoning_level="high")
    await ctx.subagents.message("s", "reader", request_id="work", text="Work")
    await asyncio.wait_for(runner.started.wait(), 3)
    other = ctx.for_work_root(project)
    other._registration_scope = None
    other._begin_registration_scope("other", 1)
    try:
        with pytest.raises(SubagentAccessError):
            await other.subagents.interrupt("s", "reader")
        assert (await ctx.subagents.get("s", "reader"))["status"] == "running"
        await ctx.subagents.interrupt("s", "reader")
        with pytest.raises(SubagentAccessError):
            await ctx.subagents.resume("s", "reader")
        await ctx.subagents.close("s", "reader")
        with pytest.raises(SubagentAccessError):
            await ctx.subagents.resume("s", "reader")
        assert (await ctx.subagents.get("s", "reader"))["status"] == "closed"
    finally:
        await other._registration_scope.dispose()


@pytest.mark.asyncio
async def test_owned_runner_clone_without_resume_never_falls_back_to_fresh_run(setup):
    from .test_plugin_subagent_access import Runner
    ctx, store, runner, _, project = setup
    runner.state_store = store._db_provider().runtime_state_store
    clone = Runner(project)
    clone.state_store = runner.state_store
    original_run = clone.run
    async def run(**kwargs):
        sid = f"s:sub:{kwargs['agent']}"
        state = RuntimeState(session_id=sid, status="running", metadata={"turn_id": "logical"})
        await clone.state_store.save_checkpoint(state, [{"role": "user", "content": "committed"}])
        try:
            return await original_run(**kwargs)
        finally:
            state.status = "cancelled"
            await clone.state_store.save(state)
    clone.run = run
    async def create_runner():
        return clone
    async def resume_interrupted(**kwargs):
        pytest.fail("Native execution should use its owned clone")
    runner.create_supervisor_runner = create_runner
    runner.resume_interrupted = resume_interrupted
    await ctx.subagents.create("s", "reader", kind="consider", model="test-model", reasoning_level="high")
    await ctx.subagents.message("s", "reader", request_id="work", text="Work")
    await asyncio.wait_for(clone.started.wait(), 3)
    await ctx.subagents.interrupt("s", "reader")
    await ctx.subagents.resume("s", "reader")
    for attempt in range(100):
        if (await ctx.subagents.get("s", "reader"))["status"] == "failed":
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("Unsupported owned continuation must settle as failed")
    assert len(clone.calls) == 1


@pytest.mark.asyncio
async def test_interrupt_cancellation_waits_for_member_cleanup(setup):
    ctx, _, runner, _, _ = setup
    cleanup_started, cleanup_release = asyncio.Event(), asyncio.Event()
    finished = asyncio.Event()
    async def run(**kwargs):
        runner.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await cleanup_release.wait()
            finished.set()
    runner.run = run
    await ctx.subagents.create("s", "reader", kind="consider", model="test-model", reasoning_level="high")
    await ctx.subagents.message("s", "reader", request_id="work", text="Work")
    await asyncio.wait_for(runner.started.wait(), 3)
    task = asyncio.create_task(ctx.subagents.interrupt("s", "reader"))
    try:
        await asyncio.wait_for(cleanup_started.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not finished.is_set()
    finally:
        cleanup_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
    assert (await ctx.subagents.get("s", "reader"))["status"] == "interrupted"
