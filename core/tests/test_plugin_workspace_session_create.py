"""user:“第二阶段结束后 就继续开展第三阶段”+(当前项目创建会话复用宿主事务)。"""
import asyncio

import pytest
from .test_plugin_workspace_registry_current import workspace_env


@pytest.mark.asyncio
async def test_create_binds_native_project_and_rejects_other(workspace_env):
    ctx, db, _, project, other = workspace_env
    result = await ctx.workspace_controller.create_session(project.id, title="New chat")
    stored = next(s for s in await db.project_store.list_sessions(project.id) if s.id == result["id"])
    assert stored.title == "New chat" and stored.metadata["work_root"] == project.work_root
    before = await db.project_store.list_sessions(other.id)
    with pytest.raises(RuntimeError):
        await ctx.workspace_controller.create_session(other.id, title="Denied")
    assert await db.project_store.list_sessions(other.id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("title", [None, "x" * 257, "\ud800", "a\x00b"])
async def test_invalid_title_is_not_dispatched(workspace_env, monkeypatch, title):
    ctx, _, catalog, project, _ = workspace_env
    async def forbidden(*args, **kwargs): pytest.fail("invalid title reached host")
    monkeypatch.setattr(catalog, "execute", forbidden)
    with pytest.raises(ValueError): await ctx.workspace_controller.create_session(project.id, title=title)


@pytest.mark.asyncio
async def test_creation_crosses_real_http(workspace_env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, db, _, project, _ = workspace_env
    host, catalog, original = _host(tmp_path)
    configure(host)
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        'async def echo(request, *, context):\n'
        f"    return await context.workspace_controller.create_session('{project.id}', title=request.payload['body']['text'])\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        body = {'args': {'text': 'HTTP chat'}}
        denied = await client.post('/plugin-remote/hook-demo/demo/echo', json=body, headers={'x-plugin-token': 'wrong'})
        assert denied.status_code == 401
        response = await client.post('/plugin-remote/hook-demo/demo/echo', json=body,
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert response.status_code == 200
    assert any(s.id == response.json()['payload']['id'] and s.title == 'HTTP chat'
               for s in await db.project_store.list_sessions(project.id))


@pytest.mark.asyncio
async def test_creation_cancel_waits_for_native_commit(workspace_env, monkeypatch):
    ctx, db, catalog, project, _ = workspace_env
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(name, *args, **kwargs):
        if name == "project.sessions.create":
            entered.set()
            await release.wait()
        return await original(name, *args, **kwargs)
    monkeypatch.setattr(catalog, "execute", gated)
    task = asyncio.create_task(ctx.workspace_controller.create_session(project.id, title="Committed"))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert any(s.title == "Committed" for s in await db.project_store.list_sessions(project.id))
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_creation_binding_change_after_commit_reports_uncertain(workspace_env, monkeypatch):
    ctx, db, catalog, project, _ = workspace_env
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == "project.sessions.create":
            entered.set()
            await release.wait()
        return result
    monkeypatch.setattr(catalog, "execute", gated)
    task = asyncio.create_task(ctx.workspace_controller.create_session(project.id, title="Saved"))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        ctx.operation_catalog = type(catalog)()
        release.set()
        with pytest.raises(RuntimeError) as exc: await task
        assert exc.value.may_have_changed
        assert any(s.title == "Saved" for s in await db.project_store.list_sessions(project.id))
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_admission_change_never_dispatches_creation(workspace_env, monkeypatch):
    ctx, db, catalog, project, _ = workspace_env
    before = await db.project_store.list_sessions(project.id)
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == 'project.get':
            entered.set()
            await release.wait()
        return result
    monkeypatch.setattr(catalog, 'execute', gated)
    task = asyncio.create_task(ctx.workspace_controller.create_session(project.id, title='No write'))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        ctx._registration_scope.revoke()
        release.set()
        with pytest.raises(RuntimeError): await task
        assert await db.project_store.list_sessions(project.id) == before
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_unclassified_post_commit_failure_is_uncertain(workspace_env, monkeypatch):
    from lamtools_core.app.operation_catalog import OperationResult
    ctx, db, catalog, project, _ = workspace_env
    original = catalog.execute
    async def ambiguous(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == 'project.sessions.create':
            return OperationResult(name, {'error': 'internal detail'}, status='error')
        return result
    monkeypatch.setattr(catalog, 'execute', ambiguous)
    with pytest.raises(RuntimeError) as exc:
        await ctx.workspace_controller.create_session(project.id, title='Saved despite error')
    assert exc.value.may_have_changed and 'internal detail' not in str(exc.value)
    assert any(s.title == 'Saved despite error' for s in await db.project_store.list_sessions(project.id))


def test_migration_identifies_create_as_partial(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {'index.ts': 'export function apply(ctx) { ctx.remote.session.create(); }'})
    report = export_port(root, tmp_path / 'ported')
    item = next(row for row in report['remotes'] if row['name'] == 'session.create')
    assert item['suggestedContract'] == 'context.workspace_controller.create_session'
    assert '复用' in item['difference'] and report['runtimeVerified'] is False
