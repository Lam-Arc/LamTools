"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(项目复核等待后不得发布已隐藏会话)。"""
import asyncio
import copy

import pytest

from .test_plugin_workspace_registry_current import workspace_env
from .test_plugin_workspace_sessions import populated


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["hidden", "moved"])
async def test_session_page_rechecks_after_project_lookup(populated, monkeypatch, change):
    ctx, db, catalog, project, other, store = populated
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    lookups = 0
    async def gated(name, *args, **kwargs):
        nonlocal lookups
        result = await original(name, *args, **kwargs)
        if name == "project.get":
            lookups += 1
            if lookups == 2:
                entered.set(); await release.wait()
        return result
    monkeypatch.setattr(catalog, "execute", gated)
    task = asyncio.create_task(ctx.workspace_registry.sessions(project.id))
    try:
        await entered.wait()
        if change == "hidden": store._session_visible = lambda sid, _: sid not in {"a", "hidden"}
        else:
            from lamtools_core.app.core_db import CoreThreadSnapshot
            async def move(connection):
                row = await connection.get(CoreThreadSnapshot, "a")
                snapshot = copy.deepcopy(row.snapshot_json)
                snapshot["session"]["metadata"]["work_root"] = other.work_root
                row.snapshot_json = snapshot
            await db.persistence.write(move)
        release.set()
        page = await task
        assert "a" not in {item.session_id for item in page.items}
        assert "b" in {item.session_id for item in page.items}
    finally:
        release.set(); await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["scope", "provider", "cancel"])
async def test_final_page_recheck_withdrawal_and_cleanup(populated, monkeypatch, change):
    ctx, _, _, project, _, _ = populated
    host = ctx.service("session_query")
    original = host.revalidate_project_page
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args):
        entered.set(); await release.wait()
        return await original(*args)
    monkeypatch.setattr(host, "revalidate_project_page", gated)
    task = asyncio.create_task(ctx.workspace_registry.sessions(project.id))
    try:
        await entered.wait()
        if change == "scope": ctx._registration_scope.revoke()
        elif change == "provider": ctx.set_service("session_query", object())
        else: task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError if change == "cancel" else RuntimeError): await task
        assert ctx._registration_scope._idle.is_set()
    finally:
        release.set(); await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_filtered_page_uses_real_authenticated_http(populated, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, native, project, _, store = populated
    host, catalog, old = _host(tmp_path); configure(host)
    ctx._secret_store = old._secret_store; host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\n"
        "async def echo(request, *, context):\n"
        f"    return OperationResult(request.name, await context.workspace_registry.sessions('{project.id}'))\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo"); register_plugin_operations(catalog, host)
    original = native.execute; entered, release = asyncio.Event(), asyncio.Event(); lookups = 0
    async def gated(name, *args, **kwargs):
        nonlocal lookups
        result = await original(name, *args, **kwargs)
        if name == "project.get":
            lookups += 1
            if lookups == 2: entered.set(); await release.wait()
        return result
    monkeypatch.setattr(native, "execute", gated)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        task = asyncio.create_task(client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "x"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")}))
        try:
            await entered.wait(); store._session_visible = lambda sid, _: sid not in {"a", "hidden"}; release.set()
            response = await task
            assert response.status_code == 200
            assert "a" not in {row["session_id"] for row in response.json()["payload"]["items"]}
        finally:
            release.set(); await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_repeated_cancel_waits_for_final_page_recheck_cleanup(populated, monkeypatch):
    ctx, _, _, project, _, _ = populated
    host = ctx.service("session_query")
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def gated(*args):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set(); await release.wait()
    monkeypatch.setattr(host, "revalidate_project_page", gated)
    task = asyncio.create_task(ctx.workspace_registry.sessions(project.id))
    try:
        await entered.wait(); task.cancel(); await cleaning.wait(); task.cancel(); await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert ctx._registration_scope._idle.is_set()
    finally:
        release.set(); await asyncio.gather(task, return_exceptions=True)


def test_migration_describes_final_session_page_recheck(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.workspaceRegistry.list(); }"})
    export_port(root, tmp_path / "ported")
    assert "项目复核后重新检查会话" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
