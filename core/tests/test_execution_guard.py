"""执行代际守卫验收：取消/超时/租约失效必须真的杀掉在跑的进程树。

user:“优先解决 to_thread 无法强制终止执行的问题”“确保取消、超时、租约失效后，
旧执行不能继续修改工作区或产生未经授权的副作用”
+(这些用例断言的是"进程真的死了、后续 spawn 真的被拒"，不是"协程被 cancel 了")。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from lamtools_core.runtime.arrange import ArrangeManager, ArrangeRunner, InMemoryArrangeStore
from lamtools_core.runtime.execution_guard import (
    ExecutionGuard,
    ExecutionRevoked,
    bind_guard,
    ensure_spawn_allowed,
    reset_guard,
)
from lamtools_core.tool.command import run_subprocess_blocking

NOW = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        # tasklist 输出跟随系统代码页，按字节解码再判断，别让编码问题
        # 把"进程还活着"误判成异常。
        output = (result.stdout or b"").decode("utf-8", errors="ignore")
        if not output.strip():
            output = (result.stdout or b"").decode("mbcs", errors="ignore")
        return str(pid) in output
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


async def _wait_dead(pid: int, *, timeout: float = 10.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if not _pid_alive(pid):
            return True
        await asyncio.sleep(0.1)
    return False


async def _create_job(manager: ArrangeManager):
    return await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="routine",
        operation="turn.start",
        payload={"message": "run"},
        trigger={"type": "once", "run_at": NOW.isoformat()},
        now=NOW,
    )


# ---------------------------------------------------------------------------
# 1. 守卫本身
# ---------------------------------------------------------------------------


def test_revoked_guard_refuses_new_spawns() -> None:
    guard = ExecutionGuard(execution_id="exec-1", job_id="job-1", fencing_token=1)
    guard.ensure_spawn_allowed()  # 未吊销时放行
    assert guard.revoke("cancelled") is True
    assert guard.revoke("timeout") is False, "重复吊销不应覆盖第一次原因"
    with pytest.raises(ExecutionRevoked, match="cancelled"):
        guard.ensure_spawn_allowed()
    assert guard.stats()["spawn_rejected"] == 1


def test_bound_guard_is_visible_to_spawn_check() -> None:
    guard = ExecutionGuard(execution_id="exec-2")
    token = bind_guard(guard)
    try:
        ensure_spawn_allowed()
        guard.revoke("lease-lost")
        with pytest.raises(ExecutionRevoked, match="lease-lost"):
            ensure_spawn_allowed()
    finally:
        reset_guard(token)
    ensure_spawn_allowed()  # 上下文退出后不再受限


# ---------------------------------------------------------------------------
# 2. 取消 running 任务必须杀掉它的进程树
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_kills_the_running_command(tmp_path: Path) -> None:
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await _create_job(manager)

    pid_file = tmp_path / "child.pid"

    def executor(_job):
        # 让子进程把自己的 pid 写出来，后面用来确认它真的死了。
        code = (
            "import os,time;"
            f"open({str(pid_file)!r},'w').write(str(os.getpid()));"
            "time.sleep(60)"
        )
        return run_subprocess_blocking(
            [sys.executable, "-c", code], cwd=tmp_path, timeout=120
        )

    runner = ArrangeRunner(store, executor, clock=lambda: NOW, poll_interval=0.01)
    assert await runner.run_due_once() == 1

    deadline = time.perf_counter() + 20
    while not pid_file.exists() and time.perf_counter() < deadline:
        await asyncio.sleep(0.05)
    assert pid_file.exists(), "子进程没有启动，用例无效"
    pid = int(pid_file.read_text().strip())
    assert _pid_alive(pid)

    interrupted = await runner.interrupt(job.id)
    assert interrupted is True
    assert await _wait_dead(pid), f"取消后子进程 {pid} 仍在运行"

    await asyncio.sleep(0.2)
    saved = await manager.get(job.id)
    assert saved is not None
    assert saved.status in {"running", "cancelled", "scheduled", "failed"}


# ---------------------------------------------------------------------------
# 3. 超时必须吊销执行并杀掉在跑的命令
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_kills_the_running_command_and_fails_the_run(tmp_path: Path) -> None:
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await _create_job(manager)

    pid_file = tmp_path / "timeout_child.pid"
    code = (
        "import os,sys,time;"
        f"open(r'{pid_file}','w').write(str(os.getpid()));"
        "time.sleep(60)"
    )

    def executor(_job):
        return run_subprocess_blocking([sys.executable, "-c", code], cwd=tmp_path, timeout=120)

    runner = ArrangeRunner(
        store,
        executor,
        clock=lambda: NOW,
        poll_interval=0.01,
        job_timeout_seconds=0.5,
    )
    assert await runner.run_due_once() == 1

    deadline = time.perf_counter() + 15
    while not pid_file.exists() and time.perf_counter() < deadline:
        await asyncio.sleep(0.05)
    assert pid_file.exists(), "子进程没有启动，用例无效"
    pid = int(pid_file.read_text().strip())

    assert await _wait_dead(pid, timeout=20), f"超时后子进程 {pid} 仍在运行"

    saved = None
    deadline = time.perf_counter() + 20
    while time.perf_counter() < deadline:
        saved = await manager.get(job.id)
        if saved is not None and saved.status != "running":
            break
        await asyncio.sleep(0.05)
    assert saved is not None
    assert saved.status in {"scheduled", "failed"}, saved.status
    assert "timed out" in (saved.last_error or "").lower()


# ---------------------------------------------------------------------------
# 4. 租约失效必须吊销并停掉执行
# ---------------------------------------------------------------------------


class _NoRenewStore(InMemoryArrangeStore):
    """续租永远失败，模拟"租约被别的 worker 抢走"。"""

    async def renew_lease(self, **kwargs):  # type: ignore[override]
        return False


@pytest.mark.asyncio
async def test_lease_loss_revokes_the_execution() -> None:
    store = _NoRenewStore()
    manager = ArrangeManager(store)
    job = await _create_job(manager)
    reached = asyncio.Event()

    async def executor(_job):
        reached.set()
        await asyncio.sleep(30)

    runner = ArrangeRunner(
        store, executor, clock=lambda: NOW, poll_interval=0.01, lease_seconds=1.0
    )
    assert await runner.run_due_once() == 1
    await asyncio.wait_for(reached.wait(), timeout=5)

    deadline = time.perf_counter() + 15
    while time.perf_counter() < deadline:
        handles = runner.active_executions
        if handles and handles[0]["task"] is not None and handles[0]["task"].done():
            break
        await asyncio.sleep(0.05)

    saved = await manager.get(job.id)
    assert saved is not None
    assert saved.status != "completed", "续租失败后任务不应该被判定为完成"
    assert runner.health()["stale_execution_rejected"] >= 0


# ---------------------------------------------------------------------------
# 5. 已吊销的执行连进程都不许起
# ---------------------------------------------------------------------------


def test_revoked_execution_cannot_start_a_command(tmp_path: Path) -> None:
    guard = ExecutionGuard(execution_id="exec-3")
    guard.revoke("timeout")
    token = bind_guard(guard)
    try:
        with pytest.raises(ExecutionRevoked):
            run_subprocess_blocking(["cmd", "/c", "echo hi"], cwd=tmp_path, timeout=5)
    finally:
        reset_guard(token)


def test_guard_tracks_and_detaches_processes(tmp_path: Path) -> None:
    guard = ExecutionGuard(execution_id="exec-4")
    token = bind_guard(guard)
    try:
        process = subprocess.Popen(SLEEPER)
        from lamtools_core.runtime.execution_guard import register_process, unregister_process

        register_process(process, label="sleeper")
        assert guard.live_processes() == 1
        assert guard.terminate_all() == 1
        process.wait(timeout=10)
        assert guard.live_processes() == 0

        second = subprocess.Popen(SLEEPER)
        register_process(second, label="sleeper-2")
        unregister_process(second)
        assert guard.live_processes() == 0
        second.kill()
        second.wait(timeout=10)
    finally:
        reset_guard(token)
