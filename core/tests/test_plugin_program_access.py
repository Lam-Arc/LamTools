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


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["stop", "undefine"])
async def test_dynamic_cleanup_failure_still_joins_other_jobs_and_can_retry(ctx, monkeypatch, operation):
    # user:“完成真实接口、参数/错误、作用域、取消/清理”+(单个作业清理失败也须尝试其余原作业，保留失败记录供重试，撤回失败不能删除定义)。
    api, jobs = ctx.dynamic_runner, ctx.jobs
    definition = api.define("def main(value): return value")
    entered = [asyncio.Event(), asyncio.Event()]
    cleaned = [asyncio.Event(), asyncio.Event()]
    def work(index):
        async def execute(job):
            entered[index].set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned[index].set()
        return execute
    records = [jobs.start("dynamic", "Cleanup failure", work(index)) for index in range(2)]
    api._runs[definition["id"]] = {record.id for record in records}
    await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered)), 3)
    original = jobs.kill
    attempts, failed = [], []
    async def flaky_kill(job_id):
        attempts.append(job_id)
        if not failed:
            failed.append(job_id)
            raise RuntimeError("controlled cleanup failure")
        return await original(job_id)
    monkeypatch.setattr(jobs, "kill", flaky_kill)
    try:
        with pytest.raises(Exception):
            await getattr(api, operation)(definition["id"])
        assert set(attempts) == {record.id for record in records}
        assert sum(event.is_set() for event in cleaned) == 1
        assert definition["id"] in api._definitions
        assert api._runs[definition["id"]] == set(failed)
        assert not ctx._registration_scope._calls
        monkeypatch.setattr(jobs, "kill", original)
        await getattr(api, operation)(definition["id"])
        assert all(event.is_set() for event in cleaned)
        assert all(record._task.done() for record in records)
        assert definition["id"] not in api._runs
        assert (definition["id"] in api._definitions) == (operation == "stop")
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_dynamic_stop_closes_admission_and_joins_after_cancellation(ctx, monkeypatch):
    # user:“审查当前代码，然后继续”+(停止期间不能增添成员，调用者取消也须排空已接收任务)。
    api = ctx.dynamic_runner
    definition = api.define("def main(value): return value")
    jobs = ctx.jobs
    entered, release = asyncio.Event(), asyncio.Event()
    killed = []
    async def kill(job_id):
        entered.set()
        await release.wait()
        killed.append(job_id)
    monkeypatch.setattr(jobs, "kill", kill)
    api._runs[definition["id"]] = {"first", "second"}
    task = asyncio.create_task(api.stop(definition["id"]))
    await asyncio.wait_for(entered.wait(), 3)
    try:
        with pytest.raises(RuntimeError):
            api.run(definition["id"])
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await ctx._registration_scope.dispose()
    assert set(killed) == {"first", "second"}
