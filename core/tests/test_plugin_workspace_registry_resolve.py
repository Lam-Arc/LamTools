"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(当前项目可从原持久根解析，其他目录不能被探测)。"""
import asyncio
from pathlib import Path

import pytest

from .test_plugin_workspace_registry_current import workspace_env


@pytest.mark.asyncio
async def test_current_workspace_resolves_through_native_database_without_creation(workspace_env):
    ctx, db, _, project, _ = workspace_env
    before = await db.project_store.list()
    result = await ctx.workspace_registry.resolve_by_path(str(ctx.work_root))
    assert result["id"] == project.id and Path(result["work_root"]) == Path(ctx.work_root).resolve()
    assert await db.project_store.list() == before


@pytest.mark.asyncio
async def test_other_workspace_path_cannot_be_probed(workspace_env, monkeypatch):
    ctx, _, catalog, _, other = workspace_env
    async def forbidden(*args, **kwargs): pytest.fail("outside root must not be dispatched")
    monkeypatch.setattr(catalog, "execute", forbidden)
    assert await ctx.workspace_registry.resolve_by_path(other.work_root) is None


@pytest.mark.asyncio
async def test_absent_current_root_does_not_create_directory_or_project(workspace_env, tmp_path):
    ctx, db, _, _, _ = workspace_env
    missing = tmp_path / "missing-workspace"
    view = ctx.for_work_root(missing)
    before = await db.project_store.list()
    assert await view.workspace_registry.resolve_by_path(str(missing)) is None
    assert not missing.exists() and await db.project_store.list() == before


@pytest.mark.asyncio
async def test_resolve_crosses_native_plugin_operation_and_http(workspace_env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, project, other = workspace_env
    host, catalog, original_context = _host(tmp_path)
    configure(host)
    ctx._secret_store = original_context._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return {'project': await context.workspace_registry.resolve_by_path(request.payload['body']['text'])}\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    headers = {"x-plugin-token": plugin_http_token(host, "hook-demo")}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async def read(path):
            return await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": path}}, headers=headers)
        visible, hidden = await read(str(ctx.work_root)), await read(other.work_root)
        assert visible.status_code == 200 and visible.json()["payload"]["project"]["id"] == project.id
        assert hidden.status_code == 200 and hidden.json()["payload"]["project"] is None
        assert other.work_root not in hidden.text


def test_migration_names_the_actual_scoped_path_resolver(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.workspaceRegistry.resolveByPath(); }"})
    report = export_port(root, tmp_path / "ported")
    item = next(row for row in report["services"] if row["name"] == "workspaceRegistry")
    assert "resolve_by_path" in item["difference"] and report["runtimeVerified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [None, "", "relative/path", [], "x" * 4097])
async def test_malformed_workspace_path_is_rejected_before_dispatch(workspace_env, path, monkeypatch):
    ctx, _, catalog, _, _ = workspace_env
    async def forbidden(*args, **kwargs): pytest.fail("invalid root must not be dispatched")
    monkeypatch.setattr(catalog, "execute", forbidden)
    with pytest.raises(ValueError): await ctx.workspace_registry.resolve_by_path(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["scope", "catalog", "root", "cancel"])
async def test_inflight_resolve_cannot_publish_after_binding_changes(workspace_env, change, tmp_path, monkeypatch):
    ctx, _, catalog, _, _ = workspace_env
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(catalog, "execute", gated)
    api = ctx.workspace_registry
    task = asyncio.create_task(api.resolve_by_path(str(ctx.work_root)))
    try:
        await entered.wait()
        if change == "scope": ctx._registration_scope.revoke()
        elif change == "catalog": ctx.operation_catalog = type(catalog)()
        elif change == "root": ctx.work_root = tmp_path / "other-root"
        else: task.cancel()
        release.set()
        if change == "cancel":
            with pytest.raises(asyncio.CancelledError): await task
        else:
            with pytest.raises((RuntimeError, ValueError)): await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
