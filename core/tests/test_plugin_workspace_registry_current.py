"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(工作区只读查询复用原项目记录并限定当前根)。"""
import asyncio
from pathlib import Path

import pytest
import httpx
from fastapi import FastAPI

from lamtools_core.app import open_core_app_db
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.app.http_agent_app import _register_core_project_operations
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure


@pytest.fixture
async def workspace_env(tmp_path):
    db = await open_core_app_db(tmp_path / "workspace.db")
    root, other = tmp_path / "here", tmp_path / "other"
    first, _ = await db.project_store.create(root, name="Visible")
    second, _ = await db.project_store.create(other, name="Private")
    catalog = OperationCatalog()
    _register_core_project_operations(catalog, project_store=db.project_store)
    ctx = PluginContext(work_root=root, operation_catalog=catalog)
    ctx._begin_registration_scope("workspace-test", 1)
    try:
        yield ctx, db, catalog, first, second
    finally:
        await ctx._registration_scope.dispose()
        await db.close()


@pytest.mark.asyncio
async def test_scoped_registry_reads_native_project_and_hides_other_root(workspace_env):
    ctx, _, _, first, second = workspace_env
    record = await ctx.workspace_registry.get(first.id)
    assert record["id"] == first.id and record["name"] == "Visible"
    assert Path(record["work_root"]) == Path(ctx.work_root).resolve()
    assert await ctx.workspace_registry.get(second.id) is None
    assert await ctx.workspace_registry.get("unknown-project") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, "", " ", [], "x" * 129])
async def test_invalid_workspace_id_is_rejected_before_native_dispatch(workspace_env, value, monkeypatch):
    ctx, _, catalog, _, _ = workspace_env
    async def forbidden(*args, **kwargs): pytest.fail("invalid id must not dispatch")
    monkeypatch.setattr(catalog, "execute", forbidden)
    with pytest.raises(ValueError): await ctx.workspace_registry.get(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["catalog", "scope", "root", "cancel"])
async def test_waiting_project_lookup_cannot_publish_stale_result(workspace_env, change, monkeypatch, tmp_path):
    ctx, _, catalog, first, _ = workspace_env
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        value = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return value
    monkeypatch.setattr(catalog, "execute", gated)
    api = ctx.workspace_registry
    task = asyncio.create_task(api.get(first.id))
    try:
        await entered.wait()
        if change == "catalog": ctx.operation_catalog = OperationCatalog()
        elif change == "scope": ctx._registration_scope.revoke()
        elif change == "root": ctx.work_root = tmp_path / "different"
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
async def test_native_project_lookup_crosses_explicit_http_mapping(workspace_env, tmp_path):
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    ctx, _, _, first, second = workspace_env
    host, catalog, original_context = _host(tmp_path)
    configure(host)
    ctx._secret_store = original_context._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return {'project': await context.workspace_registry.get(request.payload['body']['text'])}\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    headers = {"x-plugin-token": plugin_http_token(host, "hook-demo")}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async def read(identifier):
            return await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": identifier}}, headers=headers)
        visible = await read(first.id)
        hidden = await read(second.id)
        assert visible.status_code == 200 and visible.json()["payload"]["project"]["id"] == first.id
        assert hidden.status_code == 200 and hidden.json()["payload"]["project"] is None
        assert "Private" not in hidden.text and str(Path(second.work_root)) not in hidden.text
        denied = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": first.id}},
            headers={"x-plugin-token": "wrong"})
        assert denied.status_code == 401


@pytest.mark.asyncio
async def test_native_project_record_survives_database_reopen(tmp_path):
    path, root = tmp_path / "persistent.db", tmp_path / "workspace"
    first_db = await open_core_app_db(path)
    project, _ = await first_db.project_store.create(root, name="Persistent")
    await first_db.close()
    second_db = await open_core_app_db(path)
    catalog = OperationCatalog()
    _register_core_project_operations(catalog, project_store=second_db.project_store)
    ctx = PluginContext(work_root=root, operation_catalog=catalog)
    ctx._begin_registration_scope("workspace-test", 2)
    try:
        found = await ctx.workspace_registry.get(project.id)
        assert found["id"] == project.id and found["name"] == "Persistent"
    finally:
        await ctx._registration_scope.dispose()
        await second_db.close()


def test_migration_handoff_suggests_only_real_scoped_project_lookup(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.workspaceRegistry.get(); ctx.remote.workspace.create(); }"})
    report = export_port(root, tmp_path / "ported")
    service = next(item for item in report["services"] if item["name"] == "workspaceRegistry")
    assert service["candidateContract"] == "context.workspace_registry.get"
    assert "当前" in service["difference"] and report["runtimeVerified"] is False
