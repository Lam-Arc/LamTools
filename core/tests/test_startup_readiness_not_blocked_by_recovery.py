"""user:“setup/constant 打不开了”+(启动就绪不能被上次中断留下的修复挡住：
服务先能接受健康检查、界面先出来；释放残留所有权、恢复残留回合、重排未完成任务、
对账子代理仍按原来的先后顺序在后台完成)。

第二处同类缺陷一并锁住：命令目录的文件扫描必须离开事件循环，
否则一次冷扫描就会让健康检查和界面请求一起排队（实测 39.8 秒）。
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

import lamtools_core.app.http_agent_app as http_agent_app_module
from lamtools_core.app.http_agent_app import create_core_agent_http_app


def _fast_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the Windows shell probe and power request; both are unrelated to readiness."""
    monkeypatch.setattr(http_agent_app_module, "warm_command_shell", lambda: None)
    import lamtools_core.runtime.power as power_module

    monkeypatch.setattr(power_module, "apply_keep_awake", lambda: None)


def _build_app(tmp_path):
    return create_core_agent_http_app(
        core_db=tmp_path / "core.db",
        data_dir=tmp_path / "core-data",
        work_root=tmp_path / "workspace",
    )


async def _enter_lifespan(app, timeout: float = 10.0):
    """Enter the app lifespan with a hard bound, so a regression fails instead of hanging."""
    context = app.router.lifespan_context(app)

    async def enter():
        await context.__aenter__()
        return context

    return await asyncio.wait_for(enter(), timeout=timeout)


async def test_health_answers_while_interruption_recovery_is_still_running(
    tmp_path, monkeypatch
) -> None:
    """The port must open before orphan release / stale-turn / sub-agent repair finish."""
    from lamtools_core.app import sub_agent_recovery
    from lamtools_core.app.core_db import SqlAlchemyRuntimeStateStore

    _fast_boot(monkeypatch)
    release_entered = asyncio.Event()
    release_gate = asyncio.Event()
    stale_gate = asyncio.Event()
    calls: list[str] = []

    async def blocked_release(self, *, reason: str = "owner_gone") -> int:
        calls.append("release")
        release_entered.set()
        await release_gate.wait()
        return 0

    async def blocked_stale(*, context) -> int:
        calls.append("stale")
        await stale_gate.wait()
        return 0

    async def blocked_reconcile(**kwargs) -> int:
        calls.append("reconcile")
        return 0

    monkeypatch.setattr(
        SqlAlchemyRuntimeStateStore, "release_orphaned_owners", blocked_release
    )
    monkeypatch.setattr(
        http_agent_app_module, "recover_stale_active_turns", blocked_stale
    )
    monkeypatch.setattr(
        sub_agent_recovery, "reconcile_sub_agent_state", blocked_reconcile
    )

    app = _build_app(tmp_path)
    started = time.monotonic()
    context = await _enter_lifespan(app)
    elapsed = time.monotonic() - started
    try:
        # Before the fix this call never returned: lifespan awaited the repair.
        assert elapsed < 6.0, f"startup waited for recovery: {elapsed:.1f}s"
        await asyncio.wait_for(release_entered.wait(), timeout=3.0)
        assert calls == ["release"]

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1"
        ) as client:
            health = await client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["startup"]["state"] == "running"

        # Repair still runs, in the original order, once the gate opens.
        release_gate.set()
        stale_gate.set()
        recovery_task = app.state.core_agent_app_state["startup_recovery_task"]
        await asyncio.wait_for(recovery_task, timeout=10.0)
        # 前三步是启动修复本身；之后 memory-resume 的首轮巡检会再对账一次。
        assert calls[:3] == ["release", "stale", "reconcile"]

        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1"
        ) as client:
            health = await client.get("/api/health")
        assert health.json()["startup"]["state"] == "done"
    finally:
        await context.__aexit__(None, None, None)


async def test_command_catalog_build_runs_off_the_event_loop(
    tmp_path, monkeypatch
) -> None:
    """A slow catalog scan must not stop unrelated coroutines (health, RPC)."""
    from lamtools_core.app import default_agent

    _fast_boot(monkeypatch)

    def slow_build(**kwargs):
        time.sleep(0.6)
        return []

    monkeypatch.setattr(default_agent, "build_composer_command_catalog", slow_build)

    app = _build_app(tmp_path)
    context = await _enter_lifespan(app)
    try:
        operations = app.state.core_agent_app_state["operations"]
        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.02)

        task = asyncio.create_task(ticker())
        started = time.monotonic()
        await operations.execute("command.catalog", {})
        elapsed = time.monotonic() - started
        task.cancel()
        assert elapsed >= 0.55
        assert ticks >= 10, f"event loop was blocked during the scan; ticks={ticks}"
    finally:
        await context.__aexit__(None, None, None)
