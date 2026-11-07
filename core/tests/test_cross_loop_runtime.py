"""跨事件循环专项回归。

user:“跨循环专项回归，重点验证 20 次 TestClient 重建、不同事件循环的数据库访问、
并发写入、资源清理、插件 Task 生命周期及单循环兼容性；额外验证旧 Task 是否残留、
插件 on-load 是否重复执行”

背景：宿主会在同一进程里重建（Starlette TestClient 每次一个事件循环）。任何绑定在
某个循环上的对象（Task / Lock / Future）跨循环复用，都会抛
`ValueError: The future belongs to a different loop`。这组用例把该契约钉死。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import types

import pytest
from fastapi.testclient import TestClient

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.app.http_agent_app import create_core_agent_http_app
from lamtools_core.plugin_system.lifecycle import await_plugin_backends



async def _append_goal(db_path: Path, index: int) -> int:
    """一个新事件循环里写一条记录，返回累计条数。"""
    from lamtools_core.runtime.goal import GoalManager

    db = await open_core_app_db(db_path)
    try:
        manager = GoalManager(db.goal_store)
        await manager.create(
            thread_id=f"loop-{index}",
            objective=f"rebuild-{index}",
            completion_criteria=["ok"],
        )
        return len(await manager.list())
    finally:
        await db.close()


def _make_app(tmp_path: Path):
    return create_core_agent_http_app(
        model_id="model-record",
        core_db=tmp_path / "core.db",
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )


# ---------------------------------------------------------------------------
# 1. 连续创建 / 关闭 20 个 TestClient
# ---------------------------------------------------------------------------


def test_twenty_testclient_rebuilds_keep_the_same_database(tmp_path: Path) -> None:
    """同一进程内反复重建宿主，数据库必须一直可用且数据累积。"""
    (tmp_path / "workspace").mkdir(parents=True, exist_ok=True)
    for index in range(20):
        app = _make_app(tmp_path)
        with TestClient(app) as client:
            health = client.get("/api/health")
            assert health.status_code == 200, f"第 {index + 1} 次重建后健康检查失败"
        # 每次关闭后都从新循环里写一次库：既验证没有残留锁，也验证数据会累积。
        assert asyncio.run(_append_goal(tmp_path / "core.db", index)) == index + 1
        assert (tmp_path / "core.db").exists()


# ---------------------------------------------------------------------------
# 2. 不同事件循环访问同一 SQLite
# ---------------------------------------------------------------------------


def test_two_event_loops_share_one_sqlite_database(tmp_path: Path) -> None:
    """两个独立的 asyncio.run 依次操作同一个库，第二次必须看得到第一次的写入。"""

    async def write_once(marker: str) -> str:
        db = await open_core_app_db(tmp_path / "core.db")
        try:
            from lamtools_core.runtime.arrange import ArrangeManager

            manager = ArrangeManager(db.arrange_store)
            now = datetime.now(timezone.utc)
            job = await manager.create(
                thread_id="loop-a",
                work_root="proj",
                kind="routine",
                operation="turn.start",
                payload={"message": marker},
                trigger={"type": "once", "run_at": now.isoformat()},
                now=now,
            )
            return job.id
        finally:
            await db.close()

    async def count_jobs() -> int:
        db = await open_core_app_db(tmp_path / "core.db")
        try:
            from lamtools_core.runtime.arrange import ArrangeManager

            return len(await ArrangeManager(db.arrange_store).list())
        finally:
            await db.close()

    asyncio.run(write_once("first"))
    assert asyncio.run(count_jobs()) == 1
    asyncio.run(write_once("second"))
    assert asyncio.run(count_jobs()) == 2


# ---------------------------------------------------------------------------
# 3. 两个客户端并发写同一数据库
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_connections_write_concurrently(tmp_path: Path) -> None:
    """两个独立连接并发写同一个库，串行化必须成立、写入不能丢。"""
    first = await open_core_app_db(tmp_path / "core.db")
    second = await open_core_app_db(tmp_path / "core.db")
    try:
        from lamtools_core.runtime.arrange import ArrangeManager

        now = datetime.now(timezone.utc)

        async def write(manager: ArrangeManager, prefix: str, count: int) -> None:
            for index in range(count):
                await manager.create(
                    thread_id=f"{prefix}-{index}",
                    work_root="proj",
                    kind="routine",
                    operation="turn.start",
                    payload={"message": f"{prefix}-{index}"},
                    trigger={"type": "once", "run_at": now.isoformat()},
                    now=now,
                )

        await asyncio.gather(
            write(ArrangeManager(first.arrange_store), "a", 10),
            write(ArrangeManager(second.arrange_store), "b", 10),
        )
        jobs = await ArrangeManager(first.arrange_store).list()
        assert len(jobs) == 20, f"并发写入丢了数据：只有 {len(jobs)} 条"
    finally:
        await first.close()
        await second.close()


# ---------------------------------------------------------------------------
# 4. 应用关闭后无残留任务 / 锁
# ---------------------------------------------------------------------------


def test_app_shutdown_releases_the_scheduler_lease(tmp_path: Path) -> None:
    """关闭后调度租约必须释放，否则下一次启动会被判成第二个实例。"""
    (tmp_path / "workspace").mkdir(parents=True, exist_ok=True)
    from lamtools_core.runtime.single_instance import SchedulerLease

    with TestClient(_make_app(tmp_path)):
        lease_path = tmp_path / "core-data" / "arrange-scheduler.lock"
        probe = SchedulerLease(lease_path)
        assert probe.acquire() is False, "应用运行期间不该能拿到第二个调度租约"
        probe.release()

    probe = SchedulerLease(tmp_path / "core-data" / "arrange-scheduler.lock")
    assert probe.acquire() is True, "应用关闭后租约没有释放"
    probe.release()


# ---------------------------------------------------------------------------
# 5. 插件 startup Task 不跨循环复用
# ---------------------------------------------------------------------------


class _FakeHandle:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.plugin = types.SimpleNamespace(name="fake")
        self.context = types.SimpleNamespace(services={})
        self.managed = True
        self.state = "starting"
        # 必须立刻完成：await_plugin_backends 会 join 这些任务，
        # 用一个不会结束的假任务会把用例拖成挂起。
        async def _noop() -> None:
            return None

        self.startup_task = loop.create_task(_noop())

    # 供 _schedule_start 之后再次调用时使用
    @property
    def error(self):
        return None

    @property
    def last_error(self):
        return None

    @property
    def stopped(self):
        return False

    stop_requested = False


@pytest.mark.asyncio
async def test_plugin_startup_task_is_not_reused_across_loops(monkeypatch) -> None:
    """旧循环留下的 Task 必须被丢弃并在当前循环重新调度，而不是直接 gather。"""
    import lamtools_core.plugin_system.lifecycle as lifecycle

    scheduled: list[object] = []

    def _fake_schedule(handle, context) -> None:
        # 只记录调度决定，不去真的启动插件（那会拉起真实后端，把用例拖成挂起）。
        scheduled.append(handle)
        handle.state = "starting"
        async def _noop() -> None:
            return None

        handle.startup_task = asyncio.get_running_loop().create_task(_noop())

    monkeypatch.setattr(lifecycle, "_schedule_start", _fake_schedule)

    old_loop = asyncio.new_event_loop()
    handle = _FakeHandle(old_loop)
    stale_task = handle.startup_task
    old_loop.close()  # 模拟宿主重建：旧循环已经关掉

    await lifecycle.await_plugin_backends([handle])  # 之前这里会抛 ValueError

    assert scheduled == [handle], "旧循环的残留没有被替换成一次重新调度"
    assert handle.startup_task is not stale_task, "旧循环的 Task 被复用了"
    assert handle.startup_task.get_loop() is asyncio.get_running_loop()
    await handle.startup_task


@pytest.mark.asyncio
async def test_plugin_startup_task_is_reused_within_one_loop(monkeypatch) -> None:
    """单循环内不得重复调度：同一个 Task 只应在第一次被创建。"""
    import lamtools_core.plugin_system.lifecycle as lifecycle

    scheduled: list[object] = []

    def _fake_schedule(handle, context) -> None:
        scheduled.append(handle)
        handle.state = "starting"
        async def _noop() -> None:
            return None

        handle.startup_task = asyncio.get_running_loop().create_task(_noop())

    monkeypatch.setattr(lifecycle, "_schedule_start", _fake_schedule)

    handle = _FakeHandle(asyncio.get_running_loop())
    first = handle.startup_task
    await lifecycle.await_plugin_backends([handle])
    assert scheduled == [], "单循环下重复调度了 on-load"
    assert handle.startup_task is first
    await first


@pytest.mark.asyncio
async def test_cross_loop_replacement_drops_the_old_task(monkeypatch) -> None:
    """丢弃旧 Task 后不得再持有它，也不得把它放进当前循环的 gather。

    说明：循环已经关闭时 ``Task.cancel()`` 会抛 "Event loop is closed"，
    这个 Task 无法被取消，只能被放弃；因为它的循环永远不会再运行，
    放弃是安全的（product 侧已做 best-effort cancel）。
    """
    import lamtools_core.plugin_system.lifecycle as lifecycle

    def _fake_schedule(handle, context) -> None:
        async def _noop() -> None:
            return None

        handle.state = "starting"
        handle.startup_task = asyncio.get_running_loop().create_task(_noop())

    monkeypatch.setattr(lifecycle, "_schedule_start", _fake_schedule)

    old_loop = asyncio.new_event_loop()
    handle = _FakeHandle(old_loop)
    stale_task = handle.startup_task
    old_loop.close()

    await lifecycle.await_plugin_backends([handle])

    assert handle.startup_task is not stale_task, "旧循环的 Task 仍被当成当前执行"
    assert handle.startup_task.get_loop() is asyncio.get_running_loop()
    assert stale_task.get_loop() is old_loop, "旧 Task 记录的循环被改写，说明对象被复用"
    await handle.startup_task
