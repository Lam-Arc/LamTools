"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(工作区写后不发布已失效快照)。"""
import asyncio
import pytest

from .test_plugin_workspace_registry_current import workspace_env


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["rename", "delete"])
async def test_rename_does_not_publish_project_changed_after_commit(workspace_env, monkeypatch, change):
    ctx, db, catalog, first, _ = workspace_env
    original = catalog.execute
    async def changed(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == "project.update":
            if change == "rename":
                await db.project_store.update(first.id, name="Concurrent")
            else:
                await db.project_store.delete(first.id)
        return result
    monkeypatch.setattr(catalog, "execute", changed)
    with pytest.raises(RuntimeError) as error:
        await ctx.workspace_controller.rename(first.id, "Committed", expected_revision=first.revision)
    assert error.value.may_have_changed
    current = await db.project_store.get(first.id)
    assert current is None if change == "delete" else current.name == "Concurrent"
    assert ctx._registration_scope._idle.is_set()


@pytest.mark.asyncio
async def test_unchanged_native_commit_is_returned(workspace_env):
    ctx, db, _, first, _ = workspace_env
    result = await ctx.workspace_controller.rename(first.id, "Committed", expected_revision=first.revision)
    assert result["name"] == (await db.project_store.get(first.id)).name == "Committed"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["scope", "operation", "cancel"])
async def test_post_commit_recheck_handles_revocation_and_cancellation(workspace_env, monkeypatch, change):
    ctx, db, catalog, first, _ = workspace_env
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    lookups = 0
    async def gated(name, *args, **kwargs):
        nonlocal lookups
        result = await original(name, *args, **kwargs)
        if name == "project.get":
            lookups += 1
            if lookups == 2:
                entered.set()
                await release.wait()
        return result
    monkeypatch.setattr(catalog, "execute", gated)
    task = asyncio.create_task(ctx.workspace_controller.rename(first.id, "Committed", expected_revision=first.revision))
    try:
        await entered.wait()
        if change == "scope": ctx._registration_scope.revoke()
        elif change == "operation":
            handler = catalog._handlers.pop("project.update")
            catalog.register("project.update", handler)
        else: task.cancel()
        release.set()
        if change == "cancel":
            with pytest.raises(asyncio.CancelledError): await task
        else:
            with pytest.raises(RuntimeError) as error: await task
            assert error.value.may_have_changed
        assert (await db.project_store.get(first.id)).name == "Committed"
        assert ctx._registration_scope._idle.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_concurrent_rename_does_not_return_stale_snapshot_over_http(workspace_env, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, db, native, first, _ = workspace_env
    original = native.execute
    async def changed(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == "project.update": await db.project_store.update(first.id, name="Concurrent")
        return result
    monkeypatch.setattr(native, "execute", changed)
    host, catalog, original_context = _host(tmp_path)
    configure(host)
    ctx._secret_store = original_context._secret_store
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        f"    return await context.workspace_controller.rename('{first.id}', 'Committed', expected_revision={first.revision})\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo"); register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "x"}},
                                     headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code != 200 and '"name":"Committed"' not in response.text
    assert (await db.project_store.get(first.id)).name == "Concurrent"


def test_migration_explains_post_commit_recheck(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.workspace.rename(); }"})
    export_port(root, tmp_path / "ported")
    assert "重命名提交后复核原项目" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
