"""user:“给我把 2 阶段做完，前端除外”+(成员目录在创建时捕获，恢复保持原目录，配置和模型仍绑定原项目)。"""
from pathlib import Path

import pytest

from .test_plugin_working_directory import env
from .test_plugin_subagent_access import setup
from lamtools_core.sub_agent_supervisor import bound_child_identity, find_sub_agent_supervisor
from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner


@pytest.mark.asyncio
async def test_child_captures_parent_directory_and_reopen_does_not_retarget(setup):
    ctx, _, _, _, project = setup
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=state.revision)
    child = await ctx.subagents.create("s", "reader", kind="consider", model="test-model", reasoning_level="high")
    assert child["execution_directory"] == str(project / "one")
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "two", expected_revision=state.revision)
    await ctx.subagents.close("s", "reader")
    reopened = await ctx.subagents.create("s", "reader", kind="consider", model="test-model", reasoning_level="high")
    assert reopened["execution_directory"] == str(project / "one")
    supervisor = find_sub_agent_supervisor("s", data_dir=ctx.data_dir)
    assert supervisor._load(child["native_name"]).execution_directory == str(project / "one")
    runner = KernelSubAgentRunner(work_root=project, llm_client=object())
    with bound_child_identity(supervisor, "consider", child["native_name"]):
        toolbox = runner._build_toolbox(set(), active_mode="consider")
        await toolbox.refresh_execution_directory("s:sub:" + child["native_name"])
        assert toolbox._execution_root == project / "one"
        assert toolbox.work_root == project and runner.work_root == project


@pytest.mark.asyncio
async def test_missing_captured_directory_fails_without_recreating_or_following_parent(setup):
    ctx, _, _, _, project = setup
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=state.revision)
    child = await ctx.subagents.create("s", "reader", kind="consider", model="test-model", reasoning_level="high")
    (project / "one").rmdir()
    supervisor = find_sub_agent_supervisor("s", data_dir=ctx.data_dir)
    runner = KernelSubAgentRunner(work_root=project, llm_client=object())
    with bound_child_identity(supervisor, "consider", child["native_name"]):
        with pytest.raises(ValueError):
            runner._build_toolbox(set(), active_mode="consider")
    assert not (project / "one").exists()
