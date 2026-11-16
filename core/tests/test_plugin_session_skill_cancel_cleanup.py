"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(技能目录重复取消等待原会话准入清理)。"""
import asyncio

import pytest

from .test_plugin_session_skill_catalog import provider
from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize("gate_at", [1, 2])
async def test_repeated_cancel_waits_for_skill_session_admission(provider, monkeypatch, gate_at):
    ctx, _, _, _, root = provider
    (root / "visible.txt").write_text("x", encoding="utf8")
    host = ctx.require_service("working_directory")
    original = host.call
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = 0

    async def gated(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == gate_at:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(host, "call", gated)
    task = asyncio.create_task(ctx.session_skill_catalog.list("s"))
    try:
        await entered.wait()
        task.cancel()
        await cleaning.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert ctx._registration_scope._idle.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_remote_repeated_cancel_waits_for_skill_session_admission(provider, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    ctx, _, _, _, root = provider
    host, catalog, previous = _host(tmp_path)
    configure(host)
    ctx._secret_store = previous._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.session_skill_catalog.list('s')\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def blocked(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()

    monkeypatch.setattr(ctx.require_service("working_directory"), "call", blocked)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        task = asyncio.create_task(client.post(
            "/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "find"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")}))
        try:
            await entered.wait()
            task.cancel()
            await cleaning.wait()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert not ctx._registration_scope._idle.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert ctx._registration_scope._idle.is_set()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


def test_migration_reports_session_skill_cancellation_cleanup(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.skills.list(); }"})
    result = export_port(root, tmp_path / "ported")
    porting = (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
    assert "重复取消等待原准入清理" in porting
    assert result["runtimeVerified"] is False
