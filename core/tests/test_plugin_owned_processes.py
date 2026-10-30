"""user:“继续，把 2 阶段都做完”+(进程必须实际启动，输出有界，停用和取消回收自己拥有的范围)。"""
import asyncio
import os
from pathlib import Path
import sys

import pytest

from lamtools_core.plugin_system import PluginContext, ProcessAccessError

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows desktop Job owner")


def access(root):
    ctx = PluginContext(root)
    ctx._begin_registration_scope("example", 1)
    return ctx, ctx.processes


@pytest.mark.asyncio
async def test_real_process_output_exit_and_no_shell_interpretation(tmp_path):
    ctx, api = access(tmp_path)
    try:
        child = await api.spawn([sys.executable, "-c", "import sys; print(sys.argv[1]); print('err',file=sys.stderr);sys.exit(7)", "a & b"], timeout=10)
        assert child.pid > 0
        result = await child.wait()
        assert result.exit_code == 7 and result.status == "exited" and result.quiescent
        output = child.read_output()
        assert output.stdout.strip() == b"a & b" and output.stderr.strip() == b"err"
        assert output.complete and not output.stdout_lost
        assert child.read_output(stdout_after=output.stdout_after, stderr_after=output.stderr_after).stdout == b""
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_output_is_bounded_nonconsuming_and_reports_lost_prefix(tmp_path):
    ctx, api = access(tmp_path)
    try:
        child = await api.spawn([sys.executable, "-c", "import sys;sys.stdout.buffer.write(b'x'*100000);sys.stdout.flush()"], timeout=10, max_output_bytes=1024)
        await child.wait()
        first = child.read_output()
        assert len(first.stdout) == 1024 and first.stdout_after == 100000 and first.stdout_lost
        assert child.read_output() == first
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_environment_is_scrubbed_and_work_directory_is_pinned(tmp_path, monkeypatch):
    ctx, api = access(tmp_path)
    monkeypatch.setenv("PRIVATE_API_KEY", "hidden")
    ctx.work_root = tmp_path / "changed"
    try:
        child = await api.spawn([sys.executable, "-c", "import os; print(os.getcwd()); print(os.getenv('PRIVATE_API_KEY','missing')); print(os.getenv('EXPLICIT'))"], env={"EXPLICIT": "yes"}, timeout=10)
        await child.wait()
        lines = child.read_output().stdout.decode().splitlines()
        assert Path(lines[0]) == tmp_path and lines[1:] == ["missing", "yes"]
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_timeout_and_explicit_terminate_wait_for_owned_range(tmp_path):
    ctx, api = access(tmp_path)
    try:
        child = await api.spawn([sys.executable, "-c", "import time;time.sleep(30)"], timeout=0.1)
        result = await child.wait()
        assert result.status == "timed_out" and result.quiescent
        other = await api.spawn([sys.executable, "-c", "import time;time.sleep(30)"], timeout=10)
        stopped = await other.terminate()
        assert stopped.status == "stopped" and stopped.quiescent
        assert await other.terminate() == stopped
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_stop_reclaims_live_process_and_stale_handle_cannot_read(tmp_path):
    from lamtools_core.plugin_system.services import ServiceError
    ctx, api = access(tmp_path)
    child = await api.spawn([sys.executable, "-c", "import time;time.sleep(30)"], timeout=10)
    waiting = asyncio.create_task(child.wait())
    await asyncio.sleep(0)
    await ctx._registration_scope.dispose()
    assert (await waiting).quiescent
    with pytest.raises(ServiceError):
        child.read_output()
    with pytest.raises(ServiceError):
        await api.spawn([sys.executable, "-c", "pass"], timeout=10)


@pytest.mark.asyncio
async def test_actual_descendant_is_killed_with_owner(tmp_path):
    import ctypes
    from ctypes import wintypes
    ctx, api = access(tmp_path)
    source = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);print(p.pid,flush=True);time.sleep(30)"
    process_handle = None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        child = await api.spawn([sys.executable, "-c", source], timeout=10)
        for _ in range(200):
            output = child.read_output().stdout.strip()
            if output:
                break
            await asyncio.sleep(0.01)
        assert output
        descendant = int(output)
        process_handle = kernel.OpenProcess(0x100000, False, descendant)
        assert process_handle
        assert (await child.terminate()).quiescent
        assert kernel.WaitForSingleObject(process_handle, 1000) == 0
    finally:
        await ctx._registration_scope.dispose()
        if process_handle:
            kernel.CloseHandle(process_handle)


@pytest.mark.asyncio
async def test_cancel_run_reclaims_process_before_propagating_cancel(tmp_path):
    ctx, api = access(tmp_path)
    task = asyncio.create_task(api.run([sys.executable, "-c", "import time;time.sleep(30)"], timeout=10))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await ctx._registration_scope.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("argv,timeout", [("echo bad", 1), ([], 1), ([sys.executable], True), ([sys.executable], float("inf")), ([sys.executable], 0)])
async def test_invalid_spawn_is_rejected_before_creation(tmp_path, argv, timeout):
    ctx, api = access(tmp_path)
    try:
        with pytest.raises(ProcessAccessError):
            await api.spawn(argv, timeout=timeout)
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_failed_job_admission_reaps_root_and_closes_unpublished_pipes(tmp_path, monkeypatch):
    from lamtools_core.plugin_system import owned_processes as implementation
    ctx, api = access(tmp_path)
    original = implementation.subprocess.Popen
    seen = []
    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        seen.append(process)
        return process
    monkeypatch.setattr(implementation, "_windows_job_assign", lambda process: None)
    monkeypatch.setattr(implementation.subprocess, "Popen", capture)
    try:
        with pytest.raises(ProcessAccessError) as error:
            await api.spawn([sys.executable, "-c", "import time;time.sleep(30)"], timeout=10)
        assert error.value.code == "process/owner-unavailable"
        assert seen[0].poll() is not None and seen[0].stdout.closed and seen[0].stderr.closed
    finally:
        await ctx._registration_scope.dispose()
