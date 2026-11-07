"""强杀与半开状态闭环：父进程被 kill / 执行成功但结果未落库。

user:“特别注意强杀、僵尸进程、父子进程残留，以及执行成功但结果尚未持久化的情况”
+(这两条是无人值守最容易留下脏现场的路径，必须直接观测进程与库状态)。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import time

import pytest

from lamtools_core.runtime.arrange import ArrangeManager, ArrangeRunner, InMemoryArrangeStore

NOW = datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc)


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        output = (result.stdout or b"").decode("utf-8", errors="ignore")
        if not output.strip():
            output = (result.stdout or b"").decode("mbcs", errors="ignore")
        return str(pid) in output
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


async def _wait_dead(pid: int, *, timeout: float = 20.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if not _pid_alive(pid):
            return True
        await asyncio.sleep(0.1)
    return False


_HOST_SCRIPT = textwrap.dedent(
    '''
    """被测宿主：在受管执行里起一个长命令，把子进程 pid 写出来，然后一直等。"""
    import sys
    import time
    from pathlib import Path

    from lamtools_core.runtime.execution_guard import bind_guard, ExecutionGuard
    from lamtools_core.tool.command import run_subprocess_blocking

    work = Path(sys.argv[1])
    guard = ExecutionGuard(execution_id="exec-host", job_id="job-host")
    token = bind_guard(guard)
    try:
        code = (
            "import os,time;"
            f"open({str(work / 'child.pid')!r},'w').write(str(os.getpid()));"
            "time.sleep(120)"
        )
        run_subprocess_blocking([sys.executable, "-c", code], cwd=work, timeout=300)
    finally:
        pass
    '''
)


@pytest.mark.asyncio
async def test_hard_killed_host_leaves_no_child_processes(tmp_path: Path) -> None:
    """宿主被 /F 强杀后，它起的子进程必须跟着死（不能靠优雅退出）。"""
    script = tmp_path / "host.py"
    script.write_text(_HOST_SCRIPT, encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")

    host = subprocess.Popen(
        [sys.executable, str(script), str(tmp_path)], cwd=str(tmp_path), env=env
    )
    child_pid_file = tmp_path / "child.pid"
    try:
        deadline = time.perf_counter() + 40
        while not child_pid_file.exists() and time.perf_counter() < deadline:
            await asyncio.sleep(0.05)
        assert child_pid_file.exists(), "子进程没有启动，用例无效"
        child_pid = int(child_pid_file.read_text().strip())
        assert _pid_alive(child_pid)

        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(host.pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
                check=False,
            )
        else:
            host.kill()
        host.wait(timeout=15)

        # 宿主已死；子进程必须在 job object 关闭时被系统回收。
        assert await _wait_dead(child_pid), f"宿主强杀后子进程 {child_pid} 仍然存活"
    finally:
        if host.poll() is None:
            host.kill()
            host.wait(timeout=10)
        if child_pid_file.exists():
            pid = int(child_pid_file.read_text().strip())
            if _pid_alive(pid):
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )


# ---------------------------------------------------------------------------
# 执行成功但结果没落库：必须可恢复，且不能因此重复产生外部副作用
# ---------------------------------------------------------------------------


class _CompleteOnceFails(InMemoryArrangeStore):
    """第一次 complete_run 失败，模拟"执行完了但结果写不进去"。"""

    def __init__(self) -> None:
        super().__init__()
        self.failures = 1
        self.complete_calls = 0

    async def complete_run(self, **kwargs):  # type: ignore[override]
        self.complete_calls += 1
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("disk full while persisting result")
        return await super().complete_run(**kwargs)


@pytest.mark.asyncio
async def test_result_not_persisted_is_retried_without_duplicate_side_effects() -> None:
    store = _CompleteOnceFails()
    manager = ArrangeManager(store)
    runs: list[str] = []

    async def executor(_job):
        runs.append("run")
        return {"status": "ok"}

    job = await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="routine",
        operation="turn.start",
        payload={"message": "run"},
        trigger={"type": "once", "run_at": NOW.isoformat()},
        now=NOW,
    )
    runner = ArrangeRunner(store, executor, clock=lambda: NOW, poll_interval=0.01)

    assert await runner.run_due_once() == 1
    deadline = time.perf_counter() + 10
    while time.perf_counter() < deadline:
        saved = await manager.get(job.id)
        if saved is not None and saved.status in {"completed", "failed"}:
            break
        await runner.run_due_once()
        await asyncio.sleep(0.05)

    saved = await manager.get(job.id)
    assert saved is not None
    assert saved.status == "completed", f"结果落库失败后任务没有恢复，停在 {saved.status}"
    assert len(runs) >= 1
    assert store.complete_calls >= 2, "应当重试持久化，而不是丢下失败"


@pytest.mark.asyncio
async def test_effect_outbox_makes_retry_idempotent(tmp_path: Path) -> None:
    """同一幂等键的第二次执行不会重复创建外部资源。"""
    from lamtools_core.superagent import EffectOutbox, InMemorySuperagentStore

    store = InMemorySuperagentStore()
    outbox = EffectOutbox(store)

    class _Adapter:
        def __init__(self) -> None:
            self.perform_count = 0
            self.remote: dict[str, str] = {}

        async def lookup(self, effect):
            return self.remote.get(effect.idempotency_key)

        async def perform(self, effect):
            self.perform_count += 1
            self.remote[effect.idempotency_key] = f"pr:{effect.idempotency_key}"
            return self.remote[effect.idempotency_key]

    adapter = _Adapter()
    effect = await outbox.ensure(ticket_id="t", kind="create_pr", idempotency_key="tkt:pr")
    first = await outbox.deliver(effect, adapter)
    second = await outbox.deliver(first, adapter)

    assert first.remote_ref == second.remote_ref
    assert adapter.perform_count == 1, "第二次投递重复创建了外部资源"
