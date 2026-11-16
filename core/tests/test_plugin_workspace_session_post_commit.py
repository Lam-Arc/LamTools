"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(新建会话提交后核对原记录)。"""
import asyncio
import copy
import pytest

from lamtools_core.app.core_session_store import CoreDbSessionStore
from .test_plugin_workspace_registry_current import workspace_env


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["deleted", "hidden", "moved", "renamed"])
async def test_created_session_not_published_after_native_record_changes(workspace_env, monkeypatch, change):
    ctx, db, catalog, project, other = workspace_env
    store = CoreDbSessionStore(lambda: db)
    original = catalog.execute
    async def changed(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == "project.sessions.create":
            sid = result.payload["session"]["id"]
            if change == "deleted": await store.delete(sid)
            elif change == "hidden": db.project_store._session_visible = lambda session_id, metadata: session_id != sid
            elif change == "moved":
                from lamtools_core.app.core_db import CoreThreadSnapshot
                async def move(connection):
                    row = await connection.get(CoreThreadSnapshot, sid)
                    snapshot = copy.deepcopy(row.snapshot_json)
                    snapshot["session"]["metadata"]["work_root"] = other.work_root
                    row.snapshot_json = snapshot
                await db.persistence.write(move)
            else:
                session = await store.get(sid)
                session.title = "Changed"
                await store.update(session)
        return result
    monkeypatch.setattr(catalog, "execute", changed)
    with pytest.raises(RuntimeError) as error:
        await ctx.workspace_controller.create_session(project.id, title="Created")
    assert error.value.may_have_changed
    assert ctx._registration_scope._idle.is_set()


@pytest.mark.asyncio
async def test_unchanged_created_session_is_returned(workspace_env):
    ctx, db, _, project, _ = workspace_env
    result = await ctx.workspace_controller.create_session(project.id, title="Created")
    assert any(s.id == result["id"] for s in await db.project_store.list_sessions(project.id))


@pytest.mark.asyncio
async def test_native_lookup_checks_project_and_visibility(workspace_env):
    _, db, catalog, project, other = workspace_env
    session = await db.project_store.create_session(project.id, title="Visible")
    assert (await db.project_store.get_session(project.id, session.id)).id == session.id
    assert await db.project_store.get_session(other.id, session.id) is None
    result = await catalog.execute("project.sessions.get", {"project_id": other.id, "session_id": session.id})
    assert result.payload == {"session": None}
    db.project_store._session_visible = lambda *_: False
    assert await db.project_store.get_session(project.id, session.id) is None


@pytest.mark.asyncio
async def test_missing_lookup_does_not_create_session(workspace_env):
    ctx, db, catalog, project, _ = workspace_env
    before = await db.project_store.list_sessions(project.id)
    catalog._handlers.pop("project.sessions.get")
    with pytest.raises(RuntimeError) as error:
        await ctx.workspace_controller.create_session(project.id, title="No write")
    assert not error.value.may_have_changed
    assert await db.project_store.list_sessions(project.id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["lookup", "write", "scope", "cancel"])
async def test_post_commit_lookup_binding_and_cancellation(workspace_env, monkeypatch, change):
    ctx, db, catalog, project, _ = workspace_env
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == "project.sessions.get":
            entered.set(); await release.wait()
        return result
    monkeypatch.setattr(catalog, "execute", gated)
    task = asyncio.create_task(ctx.workspace_controller.create_session(project.id, title="Committed"))
    try:
        await entered.wait()
        if change in ("lookup", "write"):
            operation = "project.sessions.get" if change == "lookup" else "project.sessions.create"
            handler = catalog._handlers.pop(operation); catalog.register(operation, handler)
        elif change == "scope": ctx._registration_scope.revoke()
        else: task.cancel()
        release.set()
        if change == "cancel":
            with pytest.raises(asyncio.CancelledError): await task
        else:
            with pytest.raises(RuntimeError) as error: await task
            assert error.value.may_have_changed
        assert any(s.title == "Committed" for s in await db.project_store.list_sessions(project.id))
        assert ctx._registration_scope._idle.is_set()
    finally:
        release.set(); await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_deleted_session_is_not_returned_over_authenticated_http(workspace_env, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, db, native, project, _ = workspace_env
    store = CoreDbSessionStore(lambda: db)
    original = native.execute
    async def changed(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == "project.sessions.create": await store.delete(result.payload["session"]["id"])
        return result
    monkeypatch.setattr(native, "execute", changed)
    host, catalog, old = _host(tmp_path); configure(host)
    ctx._secret_store = old._secret_store; host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        f"    return await context.workspace_controller.create_session('{project.id}', title='Deleted')\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo"); register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "x"}},
                                     headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code != 200 and '"title":"Deleted"' not in response.text
    assert not any(s.title == "Deleted" for s in await db.project_store.list_sessions(project.id))


def test_migration_describes_session_recheck(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.session.create(); }"})
    export_port(root, tmp_path / "ported")
    assert "新建会话提交后复核原会话" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
