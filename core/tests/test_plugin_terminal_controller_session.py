"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(终端按原可见会话执行目录启动真实受管管道)。"""
import asyncio
import os
import sys
from pathlib import Path

import pytest
from .test_plugin_working_directory import env


@pytest.mark.asyncio
async def test_terminal_environment_uses_session_directory_and_denies_hidden(env):
    ctx, _, _, root = env
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=state.revision)
    info = await ctx.terminal_controller.environment("s")
    assert Path(info["cwd"]) == root / "one" and info["pty"] is False and info["cwd_exists"]
    with pytest.raises((ValueError, RuntimeError)): await ctx.terminal_controller.environment("hidden")


@pytest.mark.asyncio
async def test_terminal_rejects_visible_session_from_another_project(env, tmp_path):
    from lamtools_core.session import SessionRecord
    ctx, store, _, _ = env
    other = tmp_path / "outside-project"
    other.mkdir()
    await store.create(SessionRecord("foreign", "core", "Foreign", "idle", metadata={"work_root": str(other)}))
    with pytest.raises(RuntimeError): await ctx.terminal_controller.environment("foreign")


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="original managed process is Windows-only")
async def test_actual_interactive_process_uses_session_cwd_and_closes(env):
    ctx, _, _, root = env
    state = await ctx.working_directory.get("s")
    await ctx.working_directory.set("s", "one", expected_revision=state.revision)
    code = "import os,sys;print(os.getcwd(),flush=True);print(sys.stdin.readline().strip(),flush=True)"
    terminal = await ctx.terminal_controller.open("s", [sys.executable, "-u", "-c", code], timeout=20)
    try:
        assert terminal.pty is False
        await terminal.send(b"session-input\n")
        async with asyncio.timeout(5):
            while b"session-input" not in terminal.read().stdout:
                await asyncio.sleep(0.01)
        assert str(root / "one").encode() in terminal.read().stdout
    finally:
        outcome = await terminal.close()
    assert outcome.quiescent


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["host", "scope", "root", "cancel"])
async def test_session_admission_prevents_late_process_launch(env, monkeypatch, tmp_path, change):
    ctx, _, _, _ = env
    host = ctx.require_service("working_directory")
    original = host.call
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        value = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return value
    async def forbidden(*args, **kwargs): pytest.fail("invalidated request must not spawn")
    monkeypatch.setattr(host, "call", gated)
    monkeypatch.setattr(ctx.processes, "spawn", forbidden)
    api = ctx.terminal_controller
    task = asyncio.create_task(api.open("s", [sys.executable, "-c", "pass"], timeout=10))
    try:
        await entered.wait()
        if change == "host": ctx.set_service("working_directory", object())
        elif change == "scope": ctx._registration_scope.revoke()
        elif change == "root": ctx.work_root = tmp_path / "changed"
        else: task.cancel()
        release.set()
        if change == "cancel":
            with pytest.raises(asyncio.CancelledError): await task
        else:
            with pytest.raises((RuntimeError, ValueError)): await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="original managed process is Windows-only")
async def test_host_withdrawal_after_spawn_joins_the_real_process(env, monkeypatch):
    from lamtools_core.plugin_system.terminal_access import PluginTerminalsAPI
    ctx, _, _, _ = env
    original = PluginTerminalsAPI.open
    entered, release, created = asyncio.Event(), asyncio.Event(), []
    async def gated(self, *args, **kwargs):
        terminal = await original(self, *args, **kwargs)
        created.append(terminal)
        entered.set()
        await release.wait()
        return terminal
    monkeypatch.setattr(PluginTerminalsAPI, "open", gated)
    task = asyncio.create_task(ctx.terminal_controller.open("s", [sys.executable, "-c", "import time;time.sleep(20)"], timeout=25))
    try:
        await entered.wait()
        ctx.set_service("working_directory", object())
        release.set()
        with pytest.raises(RuntimeError): await task
        assert created[0]._process._cleaned
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_environment_real_http_uses_declared_plugin_route(env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, root = env
    host, catalog, original = _host(tmp_path)
    configure(host)
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.terminal_controller.environment(request.payload['body']['text'])\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        headers = {"x-plugin-token": plugin_http_token(host, "hook-demo")}
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "s"}}, headers=headers)
        denied = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "hidden"}}, headers=headers)
    assert response.status_code == 200 and Path(response.json()["payload"]["cwd"]) == root
    assert response.json()["payload"]["pty"] is False and denied.status_code == 400


def test_terminal_migration_marks_pipe_and_unsupported_pty(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.terminal.environment(); }"})
    report = export_port(root, tmp_path / "ported")
    item = next(row for row in report["remotes"] if row["name"] == "terminal.environment")
    assert item["suggestedContract"] == "context.terminal_controller.environment"
    assert "pty" in item["difference"] and report["runtimeVerified"] is False
