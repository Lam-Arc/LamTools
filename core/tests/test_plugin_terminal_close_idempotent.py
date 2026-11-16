"""user:“逐项核对固定上游源码及手册”+(已拥有的会话管道关闭可安全重试)。"""
import asyncio
import os
import sys

import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="original managed process is Windows-only")
async def test_closed_owned_pipe_is_idempotent_but_other_session_is_rejected(env):
    ctx, _, _, _ = env; api = ctx.terminal_controller
    tid = (await api.create_pipe("s", [sys.executable, "-c", "import time;time.sleep(15)"], timeout=20))["id"]
    terminal = ctx._registration_scope._session_terminal_pipes[tid][1]
    await api.close_pipe("s", tid)
    assert terminal._process._cleaned
    assert await api.close_pipe("s", tid) is None
    with pytest.raises(RuntimeError): await api.close_pipe("hidden", tid)
    with pytest.raises(RuntimeError): await api.close_pipe("s", "never-owned")
    with pytest.raises(RuntimeError): await api.close_pipe(None, "never-owned")


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="original managed process is Windows-only")
async def test_concurrent_close_waits_for_real_process_and_is_repeatable(env):
    ctx, _, _, _ = env; api = ctx.terminal_controller
    tid = (await api.create_pipe("s", [sys.executable, "-c", "import time;time.sleep(15)"], timeout=20))["id"]
    terminal = ctx._registration_scope._session_terminal_pipes[tid][1]
    await asyncio.gather(api.close_pipe("s", tid), api.close_pipe("s", tid))
    assert terminal._process._cleaned and await api.close_pipe("s", tid) is None


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="original managed process is Windows-only")
async def test_failed_cleanup_retains_handle_for_real_retry(env, monkeypatch):
    ctx, _, _, _ = env; api = ctx.terminal_controller
    tid = (await api.create_pipe("s", [sys.executable, "-c", "import time;time.sleep(15)"], timeout=20))["id"]
    terminal = ctx._registration_scope._session_terminal_pipes[tid][1]; original = terminal.close
    async def fail(): raise OSError("temporary cleanup failure")
    monkeypatch.setattr(terminal, "close", fail)
    try:
        with pytest.raises(OSError): await api.close_pipe("s", tid)
        assert tid in ctx._registration_scope._session_terminal_pipes and not terminal._process._cleaned
    finally:
        monkeypatch.setattr(terminal, "close", original)
        await api.close_pipe("s", tid)
    assert terminal._process._cleaned and await api.close_pipe("s", tid) is None


def test_migration_mentions_bounded_close_retry(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.terminal.close(); }"})
    export_port(root, tmp_path / "ported")
    assert "已关闭句柄可重试" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="original managed process is Windows-only")
async def test_cancelled_close_can_be_retried_after_cleanup(env, monkeypatch):
    ctx, _, _, _ = env; api = ctx.terminal_controller
    tid = (await api.create_pipe("s", [sys.executable, "-c", "import time;time.sleep(15)"], timeout=20))["id"]
    terminal = ctx._registration_scope._session_terminal_pipes[tid][1]; original = terminal.close
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated():
        entered.set(); await release.wait(); return await original()
    monkeypatch.setattr(terminal, "close", gated)
    task = asyncio.create_task(api.close_pipe("s", tid))
    try:
        await entered.wait(); task.cancel(); await asyncio.sleep(0); task.cancel(); await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert terminal._process._cleaned and await api.close_pipe("s", tid) is None
    finally:
        release.set(); await asyncio.gather(task, return_exceptions=True)
        if not terminal._process._cleaned: await original()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="original managed process is Windows-only")
async def test_repeated_close_crosses_authenticated_remote(env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, _ = env; api = ctx.terminal_controller
    tid = (await api.create_pipe("s", [sys.executable, "-c", "import time;time.sleep(15)"], timeout=20))["id"]
    terminal = ctx._registration_scope._session_terminal_pipes[tid][1]
    host, catalog, old = _host(tmp_path); configure(host)
    ctx._secret_store = old._secret_store; host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    await context.terminal_controller.close_pipe('s', request.payload['body']['text'])\n"
        "    return {'closed': True}\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo"); register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            url = "/plugin-remote/hook-demo/demo/echo"; body = {"args": {"text": tid}}
            denied = await client.post(url, json=body, headers={"x-plugin-token": "wrong"})
            assert denied.status_code == 401 and not terminal._process._cleaned
            headers = {"x-plugin-token": plugin_http_token(host, "hook-demo")}
            first = await client.post(url, json=body, headers=headers)
            second = await client.post(url, json=body, headers=headers)
        assert first.status_code == second.status_code == 200 and terminal._process._cleaned
    finally:
        if not terminal._process._cleaned: await api.close_pipe("s", tid)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="original managed process is Windows-only")
async def test_scope_disposal_waits_for_closing_process_and_clears_retry_history(env, monkeypatch):
    ctx, _, _, _ = env; api = ctx.terminal_controller; scope = ctx._registration_scope
    tid = (await api.create_pipe("s", [sys.executable, "-c", "import time;time.sleep(15)"], timeout=20))["id"]
    terminal = scope._session_terminal_pipes[tid][1]; original = terminal.close
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated():
        entered.set(); await release.wait(); return await original()
    monkeypatch.setattr(terminal, "close", gated)
    close = asyncio.create_task(api.close_pipe("s", tid))
    dispose = None
    try:
        await entered.wait(); dispose = asyncio.create_task(scope.dispose())
        await asyncio.sleep(0.02)
        assert not dispose.done()
        release.set(); await asyncio.gather(close, return_exceptions=True); await dispose
        assert terminal._process._cleaned and not scope._session_terminal_closed
    finally:
        release.set()
        await asyncio.gather(close, *(tuple([dispose]) if dispose else ()), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="original managed process is Windows-only")
async def test_retry_history_is_bounded(env):
    ctx, _, _, _ = env; api = ctx.terminal_controller
    tid = (await api.create_pipe("s", [sys.executable, "-c", "import time;time.sleep(15)"], timeout=20))["id"]
    closed = ctx._registration_scope._session_terminal_closed
    closed.update({f"old-{index}": "s" for index in range(128)})
    await api.close_pipe("s", tid)
    assert len(closed) == 128 and "old-0" not in closed and tid in closed
    with pytest.raises(RuntimeError): await api.close_pipe("s", "old-0")
