"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(文件读取取消等待原会话准入退出)。"""
import asyncio

import pytest

from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize("action,gate_at", [("stat", 1), ("list", 1), ("read", 1), ("read_bytes", 1), ("read", 2)])
async def test_repeated_cancel_waits_for_directory_admission_cleanup(env, monkeypatch, action, gate_at):
    ctx, _, _, root = env
    (root / "sample.txt").write_text("hello", encoding="utf8")
    host = ctx.require_service("working_directory"); original = host.call
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event(); calls = 0
    async def gated(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == gate_at:
            entered.set()
            try: await asyncio.Event().wait()
            finally: cleaning.set(); await release.wait()
        return await original(*args, **kwargs)
    monkeypatch.setattr(host, "call", gated)
    api = ctx.workspace_files
    work = getattr(api, action)("s", "." if action == "list" else "sample.txt")
    task = asyncio.create_task(work)
    try:
        await entered.wait(); task.cancel(); await cleaning.wait(); task.cancel(); await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert ctx._registration_scope._idle.is_set()
    finally:
        release.set(); await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_normal_workspace_read_still_uses_actual_file(env):
    ctx, _, _, root = env
    (root / "sample.txt").write_bytes(b"hello\n")
    result = await ctx.workspace_files.read("s", "sample.txt")
    assert result["text"] == "hello" and result["lines"] == 1


def test_migration_describes_workspace_read_cleanup(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.workspaceFiles.read(); }"})
    export_port(root, tmp_path / "ported")
    assert "文件读取准入取消" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")


@pytest.mark.asyncio
async def test_remote_file_read_cancel_waits_for_original_admission(env, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, root = env; (root / "sample.txt").write_bytes(b"hello\n")
    host, catalog, old = _host(tmp_path); configure(host)
    ctx._secret_store = old._secret_store; host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.workspace_files.read('s', request.payload['body']['text'])\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo"); register_plugin_operations(catalog, host)
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def blocked(*args, **kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait()
    monkeypatch.setattr(ctx.require_service("working_directory"), "call", blocked)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        task = asyncio.create_task(client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "sample.txt"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")}))
        try:
            await entered.wait(); task.cancel(); await cleaning.wait(); task.cancel(); await asyncio.sleep(0)
            assert not task.done() and not ctx._registration_scope._idle.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError): await task
            assert ctx._registration_scope._idle.is_set()
        finally:
            release.set(); await asyncio.gather(task, return_exceptions=True)
