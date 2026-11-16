"""user:“第二阶段结束后 就继续开展第三阶段”+(可见会话只列当前插件真实受管管道)。"""
import asyncio
import os
import sys

import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="original managed process is Windows-only")
async def test_list_only_owned_session_pipes_and_retains_completed(env):
    from lamtools_core.session import SessionRecord
    ctx, store, _, root = env
    await store.create(SessionRecord("second", "core", "Second", "idle", metadata={"work_root": str(root)}))
    api = ctx.terminal_controller
    first = (await api.create_pipe("s", [sys.executable, "-c", "print('done')"], timeout=10))["id"]
    second = (await api.create_pipe("second", [sys.executable, "-c", "import time;time.sleep(15)"], timeout=20))["id"]
    try:
        await ctx._registration_scope._session_terminal_pipes[first][1].wait()
        assert await api.list_pipes("s") == [{"id": first, "pty": False, "complete": True}]
        assert await api.list_pipes("second") == [{"id": second, "pty": False, "complete": False}]
        with pytest.raises(RuntimeError): await api.list_pipes("hidden")
        await api.close_pipe("s", first)
        assert await api.list_pipes("s") == []
    finally:
        if first in ctx._registration_scope._session_terminal_pipes: await api.close_pipe("s", first)
        await api.close_pipe("second", second)


@pytest.mark.asyncio
async def test_list_rejects_session_revoked_during_admission(env, monkeypatch):
    ctx, store, _, _ = env
    api = ctx.terminal_controller
    original = api._host.for_scope
    entered, release = asyncio.Event(), asyncio.Event()
    class Gate:
        async def get(self, sid):
            state = await original(api._scope).get(sid)
            entered.set(); await release.wait()
            return state
    monkeypatch.setattr(api._host, "for_scope", lambda scope: Gate())
    task = asyncio.create_task(api.list_pipes("s"))
    try:
        await entered.wait(); ctx._registration_scope.revoke(); release.set()
        with pytest.raises(RuntimeError): await task
    finally:
        release.set(); await asyncio.gather(task, return_exceptions=True)


def test_terminal_list_migration_is_explicit_approximation(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.terminal.list(); }"})
    report = export_port(root, tmp_path / "ported")
    row = next(row for row in report["remotes"] if row["name"] == "terminal.list")
    assert row["suggestedContract"] == "context.terminal_controller.list_pipes"
    assert report["runtimeVerified"] is False


@pytest.mark.asyncio
async def test_repeated_cancel_waits_for_admission_cleanup(env, monkeypatch):
    ctx, _, _, _ = env
    api = ctx.terminal_controller
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def gated(_):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait()
    monkeypatch.setattr(api, "_admit", gated)
    task = asyncio.create_task(api.list_pipes("s"))
    try:
        await entered.wait(); task.cancel(); await cleaning.wait(); task.cancel(); await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert ctx._registration_scope._idle.is_set()
    finally:
        release.set(); await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name != "nt", reason="original managed process is Windows-only")
async def test_pipe_list_over_authenticated_remote(env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, _ = env
    tid = (await ctx.terminal_controller.create_pipe("s", [sys.executable, "-c", "import time; time.sleep(15)"], timeout=20))["id"]
    host, catalog, old = _host(tmp_path); configure(host)
    ctx._secret_store = old._secret_store; host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return {'terminals': await context.terminal_controller.list_pipes(request.payload['body']['text'])}\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo"); register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            url = "/plugin-remote/hook-demo/demo/echo"; body = {"args": {"text": "s"}}
            denied = await client.post(url, json=body, headers={"x-plugin-token": "wrong"})
            allowed = await client.post(url, json=body, headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
        assert denied.status_code == 401 and allowed.status_code == 200
        assert allowed.json()["payload"]["terminals"] == [{"id": tid, "pty": False, "complete": False}]
    finally:
        await ctx.terminal_controller.close_pipe("s", tid)
