"""user:“继续，把 2 阶段都做完”+(通用后台工作必须有真实任务、隔离句柄、有界输出和停用回收)。"""
import asyncio

import pytest

from lamtools_core.plugin_system import PluginContext


def context(tmp_path, owner="caller"):
    ctx = PluginContext(tmp_path)
    ctx._begin_registration_scope(owner, 1)
    return ctx


@pytest.mark.asyncio
async def test_real_job_progress_output_result_and_observer_offsets(tmp_path):
    ctx = context(tmp_path)
    release = asyncio.Event()
    async def work(job):
        job.emit("stdout", "中文" * 100)
        job.progress("Working")
        await release.wait()
        return {"done": True}
    try:
        api = ctx.jobs
        job = api.start("worker", "Example", work, session_id="s", max_output_bytes=32)
        await asyncio.sleep(0)
        assert api.get(job.id).progress == "Working"
        first = api.read(job.id)
        assert len(first.stdout) == 32 and first.stdout_lost
        assert api.read(job.id, stdout_after=first.stdout_offset).stdout == b""
        assert api.read(job.id).stdout == first.stdout
        assert (await api.wait(job.id, timeout=0)).status == "running"
        release.set()
        finished = await api.wait(job.id, timeout=3)
        assert finished.status == "completed" and finished.result == {"done": True}
        finished.result["done"] = False
        assert api.get(job.id).result == {"done": True}
        api.remove(job.id)
        assert api.list() == ()
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_kill_and_disposal_join_actual_callbacks_and_observer_cancel_does_not_cancel_job(tmp_path):
    ctx = context(tmp_path)
    entered, cleaned = asyncio.Event(), asyncio.Event()
    async def work(job):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()
    api = ctx.jobs
    record = api.start("worker", "Waiting", work)
    await asyncio.wait_for(entered.wait(), 3)
    waiter = asyncio.create_task(api.wait(record.id, timeout=30))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert api.get(record.id).status == "running"
    await ctx._registration_scope.dispose()
    assert cleaned.is_set()
    assert record._task.done()


@pytest.mark.asyncio
async def test_foreign_scope_cannot_read_kill_or_remove_and_errors_are_sanitized(tmp_path):
    from lamtools_core.plugin_system.jobs_access import JobAccessError
    ctx, other = context(tmp_path), context(tmp_path, "other")
    async def broken(job):
        raise RuntimeError("secret credentials")
    try:
        job = ctx.jobs.start("worker", "Broken", broken)
        result = await ctx.jobs.wait(job.id, timeout=3)
        assert result.status == "failed" and "secret" not in repr(result)
        with pytest.raises(JobAccessError):
            other.jobs.get(job.id)
        with pytest.raises(JobAccessError):
            await other.jobs.kill(job.id)
        with pytest.raises(JobAccessError):
            other.jobs.remove(job.id)
    finally:
        await ctx._registration_scope.dispose()
        await other._registration_scope.dispose()


@pytest.mark.asyncio
async def test_running_remove_rejected_and_self_kill_cannot_deadlock(tmp_path):
    from lamtools_core.plugin_system.jobs_access import JobAccessError
    ctx = context(tmp_path)
    async def work(job):
        with pytest.raises(JobAccessError) as error:
            await ctx.jobs.kill(job.id)
        assert error.value.code == "job/self-stop"
        return {"ok": True}
    try:
        job = ctx.jobs.start("worker", "Self stop", work)
        with pytest.raises(JobAccessError):
            ctx.jobs.remove(job.id)
        assert (await ctx.jobs.wait(job.id, timeout=3)).status == "completed"
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_preflight_capacity_and_immediate_kill_do_not_leave_tasks(tmp_path):
    from lamtools_core.plugin_system.jobs_access import JobAccessError
    ctx = context(tmp_path)
    calls = []
    async def work(job):
        calls.append(job.id)
        await asyncio.Event().wait()
    try:
        api = ctx.jobs
        records = [api.start("worker", "Waiting", work) for _ in range(8)]
        with pytest.raises(JobAccessError) as error:
            api.start("worker", "Rejected", work)
        assert error.value.code == "job/limit"
        assert (await api.kill(records[0].id)).status == "killed"
        assert records[0].id not in calls
    finally:
        await ctx._registration_scope.dispose()
    assert all(r._task.done() for r in records)


@pytest.mark.asyncio
async def test_late_success_after_cancel_is_killed_and_callback_failure_is_failed(tmp_path):
    ctx = context(tmp_path)
    started = asyncio.Event()
    async def late(job):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return {"late": True}
    async def broken_cleanup(job):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise RuntimeError("private failure")
    try:
        job = ctx.jobs.start("worker", "Late", late)
        await asyncio.wait_for(started.wait(), 3)
        result = await ctx.jobs.kill(job.id)
        assert result.status == "killed" and result.result is None
        started.clear()
        job = ctx.jobs.start("worker", "Bad cleanup", broken_cleanup)
        await asyncio.wait_for(started.wait(), 3)
        assert (await ctx.jobs.kill(job.id)).status == "failed"
    finally:
        await ctx._registration_scope.dispose()
