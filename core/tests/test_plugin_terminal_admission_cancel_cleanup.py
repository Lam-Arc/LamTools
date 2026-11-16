"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(终端准入被重复取消时等待原会话读取清理)。"""
import asyncio
import os
import sys

import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["environment", "read", "send", "follow", "open", "create"])
async def test_terminal_admission_repeated_cancel_waits_for_original_cleanup(env, monkeypatch, method):
    ctx, _, _, _ = env
    api = ctx.terminal_controller
    host = ctx.require_service("working_directory")
    original = host.call
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def gated(*args, **kwargs):
        await original(*args, **kwargs)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()

    async def forbidden(*args, **kwargs):
        pytest.fail("cancelled admission must not start a process")

    monkeypatch.setattr(host, "call", gated)
    monkeypatch.setattr(ctx.processes, "spawn", forbidden)
    stream = None
    if method == "environment":
        call = api.environment("s")
    elif method == "read":
        call = api.read_pipe("s", "unknown")
    elif method == "send":
        call = api.send_pipe("s", "unknown", "eA==")
    elif method == "follow":
        stream = api.follow_pipe("s", "unknown")
        call = anext(stream)
    elif method == "open":
        call = api.open("s", [sys.executable], timeout=10)
    else:
        call = api.create_pipe("s", [sys.executable], timeout=10)
    task = asyncio.create_task(call)
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert ctx._registration_scope._idle.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        if stream is not None:
            await stream.aclose()


@pytest.mark.asyncio
async def test_authenticated_remote_cancel_waits_for_terminal_admission_cleanup(env, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    ctx, _, _, _ = env
    host, catalog, previous = _host(tmp_path)
    configure(host)
    ctx._secret_store = previous._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.terminal_controller.environment('s')\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    session_host = ctx.require_service("working_directory")
    original = session_host.call

    async def gated(*args, **kwargs):
        await original(*args, **kwargs)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()

    monkeypatch.setattr(session_host, "call", gated)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        task = asyncio.create_task(client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "s"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")}))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            task.cancel()
            await asyncio.wait_for(cleaning.wait(), 3)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not ctx._registration_scope._idle.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert ctx._registration_scope._idle.is_set()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_normal_terminal_environment_still_uses_original_session(env):
    ctx, _, _, root = env
    result = await ctx.terminal_controller.environment("s")
    assert result["session_id"] == "s" and result["cwd"] == str(root) and result["pty"] is False
    with pytest.raises(RuntimeError):
        await ctx.terminal_controller.environment("hidden")


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="original managed process is Windows-only")
async def test_repeated_cancel_after_process_start_joins_admission_and_process(env, monkeypatch):
    from lamtools_core.plugin_system.terminal_access import PluginTerminalsAPI

    ctx, _, _, _ = env
    host = ctx.require_service("working_directory")
    original_call, original_open = host.call, PluginTerminalsAPI.open
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    created, calls = [], 0

    async def capture_open(self, *args, **kwargs):
        terminal = await original_open(self, *args, **kwargs)
        created.append(terminal)
        return terminal

    async def gated(*args, **kwargs):
        nonlocal calls
        result = await original_call(*args, **kwargs)
        calls += 1
        if calls == 2:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
        return result

    monkeypatch.setattr(PluginTerminalsAPI, "open", capture_open)
    monkeypatch.setattr(host, "call", gated)
    task = asyncio.create_task(ctx.terminal_controller.create_pipe(
        "s", [sys.executable, "-c", "import time; time.sleep(20)"], timeout=25))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert created and not created[0]._process._cleaned
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert created[0]._process._cleaned
        assert not getattr(ctx._registration_scope, "_session_terminal_pipes", {})
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        if created and not created[0]._process._cleaned:
            await created[0].close()


def test_migration_describes_terminal_admission_cleanup(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.terminal.environment(); }"})
    export_port(root, tmp_path / "ported")
    handoff = (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
    assert "终端会话准入重复取消" in handoff
