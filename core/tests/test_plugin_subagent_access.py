"""user:“继续”+(插件通过原子代理监督器创建、投递和关闭自己的成员，不控制其他插件或整组成员)。"""
import asyncio

import pytest

from lamtools_core.sub_agent_supervisor import register_sub_agent_lifecycle_operations, find_sub_agent_supervisor
from .test_plugin_working_directory import env
from .test_sub_agent_supervisor import seed_model


class Runner:
    def __init__(self, root):
        self.work_root = root
        self.started, self.finished = asyncio.Event(), asyncio.Event()
        self.calls = []
        self.on_run = None

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        self.started.set()
        try:
            if self.on_run is not None:
                await self.on_run()
            await asyncio.Event().wait()
        finally:
            self.finished.set()


@pytest.fixture
async def setup(env):
    ctx, store, sessions, project = env
    seed_model(project)
    runner = Runner(project)
    catalog = sessions._context().operations
    register_sub_agent_lifecycle_operations(catalog, runner_factory=lambda: runner, data_dir=ctx.data_dir)
    ctx.operation_catalog = catalog
    try:
        yield ctx, store, runner, sessions, project
    finally:
        supervisor = find_sub_agent_supervisor("s", data_dir=ctx.data_dir)
        if supervisor is not None:
            await supervisor.shutdown()


@pytest.mark.asyncio
async def test_native_create_message_dedup_and_close_join_actual_member(setup):
    ctx, _, runner, _, _ = setup
    api = ctx.subagents
    created = await api.create("s", "reader", kind="consider", model="test-model", reasoning_level="high")
    assert created["name"] == "reader" and created["status"] == "idle"
    assert created["native_name"] != "reader"
    first = await api.message("s", "reader", request_id="request-one", text="Inspect this project")
    await asyncio.wait_for(runner.started.wait(), 3)
    again = await api.message("s", "reader", request_id="request-one", text="Changed retry")
    assert first["accepted"] and again["deduplicated"]
    assert first["message_id"] == again["message_id"]
    assert len(runner.calls) == 1
    assert (await api.get("s", "reader"))["status"] == "running"
    closed = await api.close("s", "reader")
    assert closed["status"] == "closed" and runner.finished.is_set()
    assert "runtime_owner" not in created and "execution_token" not in closed


@pytest.mark.asyncio
async def test_other_plugin_and_hidden_parent_cannot_address_members(setup):
    from lamtools_core.plugin_system.subagent_access import SubagentAccessError
    ctx, _, _, _, project = setup
    await ctx.subagents.create("s", "reader", kind="consider", model="test-model", reasoning_level="high")
    other = ctx.for_work_root(project)
    other._registration_scope = None
    other._begin_registration_scope("other", 1)
    try:
        assert (await other.subagents.list("s"))["items"] == []
        with pytest.raises(SubagentAccessError) as error:
            await other.subagents.close("s", "reader")
        assert error.value.code == "subagent/not-found"
        with pytest.raises(SubagentAccessError):
            await ctx.subagents.list("hidden")
    finally:
        await other._registration_scope.dispose()


@pytest.mark.asyncio
async def test_plugin_reload_revokes_facade_but_parent_owns_accepted_member(setup):
    from lamtools_core.plugin_system.services import ServiceError
    ctx, _, runner, _, _ = setup
    api = ctx.subagents
    await api.create("s", "reader", kind="consider", model="test-model", reasoning_level="high")
    await api.message("s", "reader", request_id="one", text="Work")
    await asyncio.wait_for(runner.started.wait(), 3)
    await ctx._registration_scope.dispose()
    assert not runner.finished.is_set()
    with pytest.raises(ServiceError):
        await api.list("s")
    ctx._begin_registration_scope("example", 2)
    assert (await ctx.subagents.get("s", "reader"))["status"] == "running"
    await ctx.subagents.close("s", "reader")
    assert runner.finished.is_set()


@pytest.mark.asyncio
async def test_native_errors_are_preserved_and_general_group_controls_are_absent(setup):
    from lamtools_core.plugin_system.subagent_access import SubagentAccessError
    ctx, _, _, _, _ = setup
    with pytest.raises(SubagentAccessError):
        await ctx.subagents.create("s", "reader", kind="consider", model="missing-model", reasoning_level="high")
    assert not hasattr(ctx.subagents, "terminate")
    assert not hasattr(ctx.subagents, "pause")
    assert not hasattr(ctx.subagents, "delete")


@pytest.mark.asyncio
async def test_child_cannot_close_itself_and_close_cancellation_joins_native_cleanup(setup, monkeypatch):
    from lamtools_core.plugin_system.subagent_access import SubagentAccessError
    ctx, _, runner, _, _ = setup
    checked = asyncio.Event()
    async def on_run():
        with pytest.raises(SubagentAccessError) as error:
            await ctx.subagents.close("s", "reader")
        assert error.value.code == "subagent/self-close"
        checked.set()
    runner.on_run = on_run
    await ctx.subagents.create("s", "reader", kind="consider", model="test-model", reasoning_level="high")
    await ctx.subagents.message("s", "reader", request_id="work", text="Work")
    await asyncio.wait_for(checked.wait(), 3)
    entered, release = asyncio.Event(), asyncio.Event()
    original = ctx.operation_catalog.execute
    async def delayed(name, payload, **kwargs):
        if name == "sub_agent.close":
            entered.set()
            await release.wait()
        return await original(name, payload, **kwargs)
    monkeypatch.setattr(ctx.operation_catalog, "execute", delayed)
    task = asyncio.create_task(ctx.subagents.close("s", "reader"))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runner.finished.is_set()
    assert (await ctx.subagents.get("s", "reader"))["status"] == "closed"


@pytest.mark.asyncio
async def test_project_mismatch_and_malformed_catalog_are_not_empty_success(setup, monkeypatch):
    from lamtools_core.plugin_system.subagent_access import SubagentAccessError
    from lamtools_core.app.operation_catalog import OperationResult
    ctx, _, _, _, project = setup
    other_project = ctx.for_work_root(project / "one")
    with pytest.raises(SubagentAccessError) as error:
        await other_project.subagents.list("s")
    assert error.value.code == "subagent/project-mismatch"
    original = ctx.operation_catalog.execute
    async def malformed(name, payload, **kwargs):
        if name == "sub_agent.list":
            return OperationResult(name, payload={"items": "not a list"})
        return await original(name, payload, **kwargs)
    monkeypatch.setattr(ctx.operation_catalog, "execute", malformed)
    with pytest.raises(SubagentAccessError) as error:
        await ctx.subagents.list("s")
    assert error.value.code == "subagent/invalid-result"
