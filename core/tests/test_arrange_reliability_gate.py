"""Reliability gate for Arrange + Observer (Super-agent 底座).

user:“先加固以下六项：全局并发限制、运行中任务暂停误变取消、租约 fencing 与旧执行隔离、
Observer 可靠事件投递/ACK/去重与重放、Observer 正常退出与失败重启策略、后台调度器异常自愈及健康检查”
+(这六项在修好之前，任何 Super-agent 上层能力都不可信。本文件用可观察的行为断言把它们钉住，
不允许通过放宽断言或跳过测试来"通过"。)

每个用例的断言写成"正确系统的行为"，在修复前失败即为缺陷证据；修复后通过即为回归保护。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from typing import Any

import pytest

from lamtools_core.app.durable_operations import register_durable_operations
from lamtools_core.app.operation_catalog import OperationCatalog, OperationResult
from lamtools_core.runtime.arrange import (
    ArrangeJob,
    ArrangeManager,
    ArrangeRunner,
    InMemoryArrangeStore,
)
from lamtools_core.runtime.goal import GoalManager, InMemoryGoalStore
from lamtools_core.runtime.observer import ObserverSupervisor, prepare_observer


NOW = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)


async def _wait_until(predicate, *, timeout: float = 8.0, label: str = "condition") -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"{label} was not met before timeout")
        await asyncio.sleep(0.02)


async def _create_routine(manager: ArrangeManager, *, index: int = 0, run_at: datetime = NOW) -> ArrangeJob:
    return await manager.create(
        thread_id="thread-1",
        work_root="test-proj",
        kind="routine",
        operation="turn.start",
        payload={"message": f"job-{index}"},
        trigger={"type": "once", "run_at": run_at.isoformat()},
        now=run_at,
    )


def _active_executions(runner: Any) -> list[Any]:
    """兼容修复前后的内部结构：只关心"当前有几个执行在跑"。"""
    active = getattr(runner, "_active", None)
    if isinstance(active, dict):
        return list(active.values())
    legacy = getattr(runner, "_active_tasks", None)
    return list(legacy.values()) if isinstance(legacy, dict) else []


def _active_tasks(runner: Any) -> list[asyncio.Task]:
    tasks: list[asyncio.Task] = []
    for item in _active_executions(runner):
        task = getattr(item, "task", item)
        if task is not None:
            tasks.append(task)
    return tasks


# ---------------------------------------------------------------------------
# 1. 总并发上限：配置 3 就必须真的是 3
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_peak_concurrency_never_exceeds_configured_limit() -> None:
    """限定并发为 3 时，无论轮询多少轮，同时在跑的必须不超过 3 个。

    当前实现按 `claim_limit` 每轮领取，从不扣减 `_active_tasks`，因此轮询越多次
    峰值并发越高。这里连续 5 轮领取即可观察到远超上限的峰值。
    """
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    for index in range(200):
        await _create_routine(manager, index=index)

    release = threading.Event()
    lock = threading.Lock()
    stats = {"current": 0, "peak": 0}

    def executor(_job: ArrangeJob) -> dict[str, Any]:
        with lock:
            stats["current"] += 1
            stats["peak"] = max(stats["peak"], stats["current"])
        try:
            release.wait(timeout=15.0)
        finally:
            with lock:
                stats["current"] -= 1
        return {"status": "ok"}

    kwargs: dict[str, Any] = {"claim_limit": 10, "clock": lambda: NOW, "poll_interval": 0.01}
    if "max_active_jobs" in inspect.signature(ArrangeRunner.__init__).parameters:
        kwargs["max_active_jobs"] = 3
    runner = ArrangeRunner(store, executor, **kwargs)
    try:
        for _ in range(5):
            await runner.run_due_once()
            # 必须让出事件循环，否则任务只是被 create_task 排队、线程根本没起来，
            # 断言就会空转通过（首版复现用例正是踩了这个坑）。
            await asyncio.sleep(0.1)
        peak = stats["peak"]
        claimed = len(_active_executions(runner))
    finally:
        release.set()
        await asyncio.gather(*_active_tasks(runner), return_exceptions=True)

    assert claimed >= 3, f"用例没有真正制造并发（活跃 {claimed} 个），断言无效"
    assert peak <= 3, f"峰值并发 {peak} 超过配置上限 3（领取数与活跃数没有互相扣减）"


# ---------------------------------------------------------------------------
# 2. 运行中任务暂停不得变成取消
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pausing_a_running_job_keeps_it_paused() -> None:
    """`arrange.pause` 对 running 任务必须是 paused，且旧执行不能再写回结果。

    当前 `arrange_status` 先调用 `cancel_running`（持久化为 cancelled），
    再调用 `update_status(..., 'paused')`，被终态检查拒绝——用户点了暂停，任务变成取消。
    """
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    blocker = asyncio.Event()

    async def executor(_job: ArrangeJob) -> dict[str, Any]:
        await blocker.wait()
        return {"status": "ok"}

    runner = ArrangeRunner(store, executor, clock=lambda: NOW, poll_interval=0.01)
    catalog = OperationCatalog()
    catalog.register("turn.start", lambda request: OperationResult(name=request.name, payload={}))
    register_durable_operations(
        catalog,
        goal_manager=GoalManager(InMemoryGoalStore()),
        arrange_manager=manager,
        wake_runner=runner.wake,
        cancel_running=runner.cancel,
    )

    job = await _create_routine(manager)
    assert await runner.run_due_once() == 1
    await asyncio.sleep(0.05)

    paused = await catalog.execute("arrange.pause", {"job_id": job.id})
    assert paused.status == "ok", f"暂停请求被拒绝: {paused.payload}"
    assert paused.payload["job"]["status"] == "paused"

    saved = await manager.get(job.id)
    assert saved is not None
    assert saved.status == "paused", f"用户暂停后任务落成了 {saved.status}"

    blocker.set()
    await asyncio.gather(*_active_tasks(runner), return_exceptions=True)
    still = await manager.get(job.id)
    assert still is not None and still.status != "cancelled"


# ---------------------------------------------------------------------------
# 3. 租约 fencing：旧执行不得污染新执行的检查点
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_execution_cannot_write_checkpoint_of_new_execution() -> None:
    """同一 Runner 内，租约过期被重新领取后，旧执行调用 checkpoint 必须被拒绝。

    当前 `_active_fences` 以 job_id 为键，重新领取会覆盖为新 fence；
    旧执行调用 `runner.checkpoint(job_id, ...)` 会拿到新 token 并通过校验，
    把过期执行的进度写进新执行的检查点。
    """
    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    clock = {"now": NOW}
    release_stale = asyncio.Event()
    finish_current = asyncio.Event()
    stale_checkpoint_errors: list[BaseException] = []
    stale_ready = asyncio.Event()
    current_ready = asyncio.Event()
    calls = {"count": 0}

    async def executor(claimed: ArrangeJob) -> dict[str, Any]:
        calls["count"] += 1
        if calls["count"] == 1:
            stale_ready.set()
            await release_stale.wait()
            try:
                await runner.checkpoint(claimed.id, {"from": "stale-execution"})
            except BaseException as exc:  # noqa: BLE001 - 记录现场，稍后断言
                stale_checkpoint_errors.append(exc)
        else:
            # 第二次执行必须一直持有租约，否则任务先完成，
            # 过期执行会被"任务已完成"挡住，测不出 fence 本身（首版就是这样空转通过的）。
            current_ready.set()
            await finish_current.wait()
        return {"status": "ok"}

    runner = ArrangeRunner(store, executor, clock=lambda: clock["now"], lease_seconds=5, poll_interval=0.01)
    job = await _create_routine(manager)

    assert await runner.run_due_once() == 1
    await asyncio.wait_for(stale_ready.wait(), timeout=2)

    clock["now"] = NOW + timedelta(seconds=6)
    await runner.run_due_once()  # 回收过期租约，本轮不重领
    assert await runner.run_due_once() == 1  # 新执行领取成功
    await asyncio.wait_for(current_ready.wait(), timeout=2)

    release_stale.set()
    await asyncio.sleep(0.2)

    saved = await manager.get(job.id)
    assert saved is not None
    assert saved.status == "running", "第二次执行必须仍在运行，fence 断言才有意义"
    assert stale_checkpoint_errors, "过期执行通过了 fence 校验并写入了检查点"

    finish_current.set()
    await asyncio.gather(*_active_tasks(runner), return_exceptions=True)
    assert saved.checkpoint.get("from") != "stale-execution"


# ---------------------------------------------------------------------------
# 4. Observer：on-failure 正常退出不得重启
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_failure_observer_exiting_cleanly_is_not_restarted(tmp_path: Path) -> None:
    """`restart=on-failure` 的观察器正常退出（退出码 0）后不应被再次拉起。

    当前 `_monitor` 把状态记为 stopped 却不记录终态，下一轮 `reconcile_once`
    发现它仍是 desired 且不在 `_processes` 里，立刻重启——形成每轮询一次的热循环。
    """
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    runs_path = work_root / "runs.txt"
    script = work_root / "observer.py"
    script.write_text(
        "\n".join(
            [
                "import os",
                "import sys",
                "from pathlib import Path",
                "root = Path(os.environ['LAMTOOLS_OBSERVER_WORK_ROOT'])",
                "with open(root / 'runs.txt', 'a', encoding='utf-8') as handle:",
                "    handle.write('run\\n')",
                "sys.exit(0)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root=str(work_root),
        kind="focus",
        operation="turn.start",
        payload={"message": "watch"},
        trigger={"type": "event", "event_type": "content.published"},
        observer=prepare_observer(
            {"entry": "observer.py", "restart": "on-failure"}, work_root=work_root
        ),
    )

    supervisor = ObserverSupervisor(store, data_dir=tmp_path / "data", poll_interval=0.05)
    await supervisor.start()
    try:
        await _wait_until(lambda: runs_path.exists() and runs_path.read_text(encoding="utf-8").count("run") >= 1, timeout=10, label="首次启动")
        await asyncio.sleep(1.5)
        launches = runs_path.read_text(encoding="utf-8").count("run")
    finally:
        await supervisor.stop()

    assert launches == 1, f"正常退出的观察器被重启了 {launches - 1} 次"
    assert supervisor.status(job.id)["status"] in {"stopped", "stopped_successfully"}


# ---------------------------------------------------------------------------
# 5. Observer：宿主写库失败不得造成事件永久丢失
# ---------------------------------------------------------------------------


class _FlakyEmitStore(InMemoryArrangeStore):
    """第一次 emit_signal 模拟短暂数据库故障。"""

    def __init__(self) -> None:
        super().__init__()
        self.failures_remaining = 1
        self.emit_attempts = 0

    async def emit_signal(self, signal, *, now, job_id=None):  # type: ignore[override]
        self.emit_attempts += 1
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise sqlite3.OperationalError("database is locked")
        return await super().emit_signal(signal, now=now, job_id=job_id)


@pytest.mark.asyncio
async def test_observer_event_survives_transient_host_write_failure(tmp_path: Path) -> None:
    """宿主提交事件短暂失败后，事件必须仍被处理（重放），不能永久丢失。

    观察器一发出信号就推进自己的游标（现实中无法避免），而协议没有 ACK：
    宿主写库失败后再没有任何重放路径，这条事件从此消失。
    """
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    script = work_root / "observer.py"
    script.write_text(
        "\n".join(
            [
                "import json",
                "import os",
                "import time",
                "from pathlib import Path",
                "state = Path(os.environ['LAMTOOLS_OBSERVER_STATE_DIR'])",
                "state.mkdir(parents=True, exist_ok=True)",
                "cursor = state / 'cursor.txt'",
                "if not cursor.exists():",
                "    print(json.dumps({",
                "        'protocol': 'lamtools.signal.v1',",
                "        'event_id': 'content:42',",
                "        'event_type': 'content.published',",
                "        'occurred_at': '2026-07-17T14:00:00Z',",
                "        'data': {'id': '42'},",
                "    }), flush=True)",
                "    cursor.write_text('content:42', encoding='utf-8')",
                "while True:",
                "    time.sleep(0.05)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    store = _FlakyEmitStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root=str(work_root),
        kind="focus",
        operation="turn.start",
        payload={"message": "watch"},
        trigger={"type": "event", "event_type": "content.published"},
        observer=prepare_observer({"entry": "observer.py"}, work_root=work_root),
    )

    supervisor = ObserverSupervisor(store, data_dir=tmp_path / "data", poll_interval=0.05)
    await supervisor.start()
    try:
        await _wait_until(lambda: store.emit_attempts >= 1, timeout=10, label="观察器首次投递")
        await _wait_until(
            lambda: bool(store._occurrences), timeout=5, label="事件最终入库"
        )
    finally:
        await supervisor.stop()

    occurrences = await manager.list_occurrences(job_id=job.id)
    assert len(occurrences) == 1, f"事件在宿主写库失败后丢失，最终入库 {len(occurrences)} 条"


# ---------------------------------------------------------------------------
# 6. 调度循环：短暂数据库故障后必须自愈，不能静默死亡
# ---------------------------------------------------------------------------


class _BusyOnceStore(InMemoryArrangeStore):
    """第一次 claim_due 模拟 SQLite busy。"""

    def __init__(self) -> None:
        super().__init__()
        self.failures_remaining = 1

    async def claim_due(self, **kwargs):  # type: ignore[override]
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise sqlite3.OperationalError("database is locked")
        return await super().claim_due(**kwargs)


@pytest.mark.asyncio
async def test_arrange_loop_survives_transient_database_failure() -> None:
    """数据库短暂不可用后，调度循环必须继续工作并最终把任务跑完。"""
    store = _BusyOnceStore()
    manager = ArrangeManager(store)
    executed: list[str] = []

    def executor(job: ArrangeJob) -> dict[str, Any]:
        executed.append(job.id)
        return {"status": "ok"}

    runner = ArrangeRunner(store, executor, clock=lambda: NOW, poll_interval=0.05)
    await _create_routine(manager)
    await runner.start()
    try:
        await _wait_until(lambda: bool(executed), timeout=8, label="任务在数据库恢复后被执行")
        await asyncio.sleep(0.1)
    finally:
        await runner.stop()

    assert executed, "第一次 claim 失败后调度循环直接死亡，任务再没被执行"
    jobs = await manager.list()
    assert jobs and jobs[0].status == "completed"


# ---------------------------------------------------------------------------
# 7. 健康检查：必须能读到后台循环的真实存活与容量
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arrange_and_observer_expose_live_health_snapshot(tmp_path: Path) -> None:
    """后台循环必须暴露可查询的健康快照，而不是只看 HTTP 是否存活。"""
    store = InMemoryArrangeStore()
    runner = ArrangeRunner(store, lambda job: {"status": "ok"}, clock=lambda: NOW)
    await _create_routine(ArrangeManager(store))

    runner_health = getattr(runner, "health", None)
    assert callable(runner_health), "ArrangeRunner 没有健康快照，无法判断调度是否还活着"
    snapshot = runner_health()
    required = {"alive", "active", "capacity", "queued"}
    assert required <= set(snapshot), f"ArrangeRunner 健康快照缺少字段: {required - set(snapshot)}"

    await runner.start()
    try:
        await _wait_until(lambda: runner_health()["alive"] is True, timeout=2, label="调度循环存活")
        assert runner_health()["capacity"] >= 1
    finally:
        await runner.stop()
    assert runner_health()["alive"] is False

    supervisor = ObserverSupervisor(store, data_dir=tmp_path / "health-data", poll_interval=0.05)
    observer_health = getattr(supervisor, "health", None)
    assert callable(observer_health), "ObserverSupervisor 没有健康快照"
    assert {"alive", "running", "backoff"} <= set(observer_health())


# ---------------------------------------------------------------------------
# 8. Observer 脏输入：单行超限不得让信号读取永久失效
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_observer_line_does_not_kill_signal_reader(tmp_path: Path) -> None:
    """超长 JSONL 行之后，后续合法事件仍必须被读取并处理。"""
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    script = work_root / "observer.py"
    script.write_text(
        "\n".join(
            [
                "import json",
                "import time",
                "big = {'protocol': 'lamtools.signal.v1', 'event_id': 'big', 'event_type': 'content.published', 'occurred_at': '2026-07-17T14:00:00Z', 'data': {'blob': 'x' * 1500000}}",
                "print(json.dumps(big), flush=True)",
                "print(json.dumps({'protocol': 'lamtools.signal.v1', 'event_id': 'after-big', 'event_type': 'content.published', 'occurred_at': '2026-07-17T14:10:00Z'}), flush=True)",
                "while True:",
                "    time.sleep(0.05)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root=str(work_root),
        kind="focus",
        operation="turn.start",
        payload={"message": "watch"},
        trigger={"type": "event", "event_type": "content.published"},
        observer=prepare_observer({"entry": "observer.py"}, work_root=work_root),
    )

    supervisor = ObserverSupervisor(store, data_dir=tmp_path / "data", poll_interval=0.05)
    await supervisor.start()
    try:
        await _wait_until(
            lambda: supervisor.status(job.id).get("last_signal_at") is not None,
            timeout=8,
            label="超长行之后的合法事件",
        )
        status = supervisor.status(job.id)
    finally:
        await supervisor.stop()

    assert status.get("last_event_id") == "after-big"


# ---------------------------------------------------------------------------
# 9. 单实例：同一份数据目录只允许一个调度器领任务
# ---------------------------------------------------------------------------


def test_scheduler_lease_allows_only_one_holder(tmp_path: Path) -> None:
    """第二个进程不得同时跑调度器，否则并发上限会按进程数翻倍。"""
    from lamtools_core.runtime.single_instance import SchedulerLease

    first = SchedulerLease(tmp_path / "arrange-scheduler.lock")
    assert first.acquire() is True
    try:
        second = SchedulerLease(tmp_path / "arrange-scheduler.lock")
        assert second.acquire() is False, "第二个进程也拿到了调度租约"
        assert second.holder_pid() == os.getpid()
    finally:
        first.release()

    third = SchedulerLease(tmp_path / "arrange-scheduler.lock")
    assert third.acquire() is True, "前一个持有者释放后应该能重新获取"
    third.release()
