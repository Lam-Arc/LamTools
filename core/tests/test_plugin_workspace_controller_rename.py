"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(工作区重命名限定当前项目并复用原持久化版本控制)。"""
import asyncio

import pytest
from .test_plugin_workspace_registry_current import workspace_env


@pytest.mark.asyncio
async def test_rename_is_scoped_and_native_revision_checked(workspace_env):
    ctx, db, _, first, other = workspace_env
    api = ctx.workspace_controller
    result = await api.rename(first.id, "Renamed", expected_revision=first.revision)
    assert result["name"] == "Renamed" and result["revision"] == first.revision + 1
    assert (await db.project_store.get(first.id)).name == "Renamed"
    with pytest.raises(RuntimeError): await api.rename(first.id, "Stale", expected_revision=first.revision)
    with pytest.raises(RuntimeError): await api.rename(other.id, "Foreign", expected_revision=other.revision)
    assert (await db.project_store.get(other.id)).name == "Private"


@pytest.mark.asyncio
@pytest.mark.parametrize("name,revision", [("", 1), (" ", 1), ("x", True), ("x", 0), (None, 1)])
async def test_invalid_rename_fails_before_original_dispatch(workspace_env, monkeypatch, name, revision):
    ctx, _, catalog, first, _ = workspace_env
    async def forbidden(*args, **kwargs): pytest.fail("invalid request must not dispatch")
    monkeypatch.setattr(catalog, "execute", forbidden)
    with pytest.raises(ValueError): await ctx.workspace_controller.rename(first.id, name, expected_revision=revision)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["scope", "host", "root", "cancel"])
async def test_rename_admission_cannot_write_after_binding_changes(workspace_env, monkeypatch, tmp_path, change):
    ctx, db, catalog, first, _ = workspace_env
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == "project.get":
            entered.set()
            await release.wait()
        return result
    monkeypatch.setattr(catalog, "execute", gated)
    api = ctx.workspace_controller
    task = asyncio.create_task(api.rename(first.id, "Must not write", expected_revision=first.revision))
    try:
        await entered.wait()
        if change == "scope": ctx._registration_scope.revoke()
        elif change == "host": ctx.operation_catalog = type(catalog)()
        elif change == "root": ctx.work_root = tmp_path / "other"
        else: task.cancel()
        release.set()
        if change == "cancel":
            with pytest.raises(asyncio.CancelledError): await task
        else:
            with pytest.raises((ValueError, RuntimeError)): await task
        assert (await db.project_store.get(first.id)).name == "Visible"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_repeated_cancel_after_write_dispatch_waits_for_original_commit(workspace_env, monkeypatch):
    ctx, db, catalog, first, _ = workspace_env
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(name, *args, **kwargs):
        if name == "project.update":
            entered.set()
            await release.wait()
        return await original(name, *args, **kwargs)
    monkeypatch.setattr(catalog, "execute", gated)
    task = asyncio.create_task(ctx.workspace_controller.rename(first.id, "Committed", expected_revision=first.revision))
    try:
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert (await db.project_store.get(first.id)).name == "Committed"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_binding_change_after_native_commit_reports_may_have_changed(workspace_env, monkeypatch):
    ctx, db, catalog, first, _ = workspace_env
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == "project.update":
            entered.set()
            await release.wait()
        return result
    monkeypatch.setattr(catalog, "execute", gated)
    task = asyncio.create_task(ctx.workspace_controller.rename(first.id, "Committed", expected_revision=first.revision))
    try:
        await entered.wait()
        ctx.operation_catalog = type(catalog)()
        release.set()
        with pytest.raises(RuntimeError) as error: await task
        assert error.value.code == "workspace/host-changed" and error.value.may_have_changed
        assert (await db.project_store.get(first.id)).name == "Committed"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_unclassified_operation_error_after_commit_reports_uncertain(workspace_env, monkeypatch):
    from lamtools_core.app.operation_catalog import OperationResult
    ctx, db, catalog, first, _ = workspace_env
    original = catalog.execute
    async def ambiguous(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == "project.update":
            return OperationResult(name, {"error": "unclassified post-write failure"}, status="error")
        return result
    monkeypatch.setattr(catalog, "execute", ambiguous)
    with pytest.raises(RuntimeError) as error:
        await ctx.workspace_controller.rename(first.id, "Committed", expected_revision=first.revision)
    assert error.value.code == "workspace/rejected" and error.value.may_have_changed
    assert (await db.project_store.get(first.id)).name == "Committed"


@pytest.mark.asyncio
async def test_workspace_rename_crosses_real_plugin_http(workspace_env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, db, _, first, _ = workspace_env
    host, catalog, original = _host(tmp_path)
    configure(host)
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        f"    return await context.workspace_controller.rename('{first.id}', request.payload['body']['text'], expected_revision={first.revision})\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        body = {"args": {"text": "HTTP renamed"}}
        denied = await client.post("/plugin-remote/hook-demo/demo/echo", json=body, headers={"x-plugin-token": "wrong"})
        assert denied.status_code == 401 and (await db.project_store.get(first.id)).name == "Visible"
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json=body,
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code == 200 and response.json()["payload"]["name"] == "HTTP renamed"
    assert (await db.project_store.get(first.id)).name == "HTTP renamed"


def test_workspace_rename_handoff_reports_cas_and_scope(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.workspace.rename(); }"})
    report = export_port(root, tmp_path / "ported")
    item = next(row for row in report["remotes"] if row["name"] == "workspace.rename")
    assert item["suggestedContract"] == "context.workspace_controller.rename"
    assert "修订" in item["difference"] and report["runtimeVerified"] is False
