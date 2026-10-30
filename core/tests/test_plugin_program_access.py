"""user:“给我把 2 阶段做完，前端除外”+(程序执行必须有真实结果、错误和原生进程回收，不靠空壳宣称PTC兼容)。"""
import asyncio
import os

import pytest

from lamtools_core.plugin_system import PluginContext


@pytest.fixture
def ctx(tmp_path):
    context = PluginContext(tmp_path)
    context._begin_registration_scope("program", 1)
    return context


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows Job process owner")
async def test_program_returns_actual_value_logs_and_classifies_exception(ctx):
    result = await ctx.ptc_runtime.run("def main(value):\n print('running')\n return {'sum': sum(value)}", input=[2, 3], timeout=10)
    assert result["status"] == "completed" and result["value"] == {"sum": 5}
    assert "running" in result["stdout"] and result["confined"] is False
    failed = await ctx.ptc_runtime.run("def main(value):\n raise ValueError('bad')", timeout=10)
    assert failed["status"] == "failed" and failed["error"]["type"] == "ValueError"
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows Job process owner")
async def test_program_deadline_and_cancellation_reclaim_process_range(ctx):
    result = await ctx.ptc_runtime.run("def main(value):\n import time\n time.sleep(10)", timeout=0.2)
    assert result["status"] == "timed_out" and result["quiescent"]
    task = asyncio.create_task(ctx.ptc_runtime.run("def main(value):\n import time\n time.sleep(10)", timeout=20))
    while not ctx.processes._handles:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not ctx.processes._handles
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="Windows Job process owner")
async def test_dynamic_definitions_are_immutable_and_runs_are_owned_jobs(ctx):
    api = ctx.dynamic_runner
    definition = api.define("def main(value):\n return value + 1")
    same = api.define("def main(value):\n return value + 1")
    assert definition == same
    job = api.run(definition["id"], input=4, timeout=10)
    done = await ctx.jobs.wait(job.id, timeout=10)
    assert done.status == "completed" and done.result["value"] == 5
    await api.undefine(definition["id"])
    with pytest.raises(LookupError):
        api.run(definition["id"], input=4)
    await ctx._registration_scope.dispose()
