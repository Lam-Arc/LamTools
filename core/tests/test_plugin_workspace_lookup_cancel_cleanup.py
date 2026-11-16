"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(工作区原生读取重复取消等待清理)。"""
import asyncio

import pytest

from .test_plugin_workspace_registry_current import workspace_env


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "resolve", "follow", "create", "rename"])
async def test_repeated_cancel_waits_for_workspace_lookup_cleanup(workspace_env, monkeypatch, method):
    ctx, _, catalog, project, _ = workspace_env
    before = await ctx.workspace_registry.get(project.id)
    original = catalog.execute
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def gated(name, *args, **kwargs):
        if name in {"project.create", "project.update"}:
            pytest.fail("cancelled admission must not write a project")
        result = await original(name, *args, **kwargs)
        if name in {"project.get", "project.resolve"}:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
        return result

    monkeypatch.setattr(catalog, "execute", gated)
    stream = None
    if method == "get":
        call = ctx.workspace_registry.get(project.id)
    elif method == "resolve":
        call = ctx.workspace_registry.resolve_by_path(str(ctx.work_root))
    elif method == "follow":
        stream = ctx.workspace_controller.follow()
        call = anext(stream)
    elif method == "create":
        call = ctx.workspace_controller.create(str(ctx.work_root))
    else:
        call = ctx.workspace_controller.rename(project.id, "New name", expected_revision=before["revision"])
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
async def test_real_remote_cancel_waits_for_workspace_lookup_cleanup(workspace_env, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

    ctx, _, native_catalog, project, _ = workspace_env
    host, catalog, previous = _host(tmp_path)
    configure(host)
    ctx._secret_store = previous._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return {'project': await context.workspace_registry.get(request.payload['body']['text'])}\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    original = native_catalog.execute
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def gated(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == "project.get":
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
        return result

    monkeypatch.setattr(native_catalog, "execute", gated)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        task = asyncio.create_task(client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": project.id}},
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
async def test_scope_disposal_waits_for_cancelled_lookup_cleanup(workspace_env, monkeypatch):
    ctx, _, catalog, project, _ = workspace_env
    original = catalog.execute
    entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def gated(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
        return result

    monkeypatch.setattr(catalog, "execute", gated)
    task = asyncio.create_task(ctx.workspace_registry.get(project.id))
    disposal = None
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 3)
        task.cancel()
        disposal = asyncio.create_task(ctx._registration_scope.dispose())
        await asyncio.sleep(0)
        assert not task.done() and not disposal.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await disposal
        assert ctx._registration_scope._idle.is_set()
    finally:
        release.set()
        await asyncio.gather(task, *(tuple([disposal]) if disposal else ()), return_exceptions=True)


@pytest.mark.asyncio
async def test_workspace_lookup_retains_current_project_scope(workspace_env):
    ctx, _, _, project, other = workspace_env
    assert (await ctx.workspace_registry.get(project.id))["id"] == project.id
    assert (await ctx.workspace_registry.resolve_by_path(str(ctx.work_root)))["id"] == project.id
    assert await ctx.workspace_registry.get(other.id) is None
    assert await ctx.workspace_registry.resolve_by_path(str(other.work_root)) is None


def test_migration_records_workspace_lookup_cancellation(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.workspaceRegistry.get(); }"})
    export_port(root, tmp_path / "ported")
    assert "工作区原生读取重复取消" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
