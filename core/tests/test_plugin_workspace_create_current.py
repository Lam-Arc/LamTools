"""user:“第二阶段结束后 就继续开展第三阶段”+(当前项目根创建复用宿主持久记录)。"""
import asyncio
from pathlib import Path

import pytest

from lamtools_core.app import open_core_app_db
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.app.http_agent_app import _register_core_project_operations
from lamtools_core.plugin_system.context import PluginContext


@pytest.fixture
async def empty_workspace(tmp_path):
    db = await open_core_app_db(tmp_path / 'create.db')
    root = tmp_path / 'workspace'
    root.mkdir()
    catalog = OperationCatalog()
    _register_core_project_operations(catalog, project_store=db.project_store)
    ctx = PluginContext(work_root=root, operation_catalog=catalog)
    ctx._begin_registration_scope('workspace-test', 1)
    try:
        yield ctx, db, catalog, root
    finally:
        await ctx._registration_scope.dispose()
        await db.close()


@pytest.mark.asyncio
async def test_create_and_resolve_current_root_in_real_database(empty_workspace):
    ctx, db, _, root = empty_workspace
    first = await ctx.workspace_controller.create(str(root))
    second = await ctx.workspace_controller.create(str(root))
    assert first['created'] is True and second['created'] is False
    assert first['project']['id'] == second['project']['id']
    assert len(await db.project_store.list_sessions(first['project']['id'])) == 1
    assert (await db.project_store.resolve_by_path(root)).id == first['project']['id']


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['', 'relative', None, '/not-current', 'x' * 4097, '\ud800'])
async def test_invalid_and_foreign_paths_never_dispatch(empty_workspace, monkeypatch, path):
    ctx, _, catalog, _ = empty_workspace
    async def forbidden(*args, **kwargs): pytest.fail('invalid path was dispatched')
    monkeypatch.setattr(catalog, 'execute', forbidden)
    with pytest.raises((ValueError, RuntimeError)):
        await ctx.workspace_controller.create(path)


@pytest.mark.asyncio
async def test_missing_directory_is_not_created(empty_workspace):
    ctx, db, _, root = empty_workspace
    root.rmdir()
    with pytest.raises(RuntimeError): await ctx.workspace_controller.create(str(root))
    assert not root.exists() and await db.project_store.list() == []


@pytest.mark.asyncio
async def test_cancelled_create_waits_for_native_write(empty_workspace, monkeypatch):
    ctx, db, catalog, root = empty_workspace
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(name, *args, **kwargs):
        if name == 'project.create':
            entered.set()
            await release.wait()
        return await original(name, *args, **kwargs)
    monkeypatch.setattr(catalog, 'execute', gated)
    task = asyncio.create_task(ctx.workspace_controller.create(str(root)))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert await db.project_store.resolve_by_path(root) is not None
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_replaced_create_binding_reports_uncertain_after_commit(empty_workspace, monkeypatch):
    ctx, db, catalog, root = empty_workspace
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == 'project.create': entered.set(); await release.wait()
        return result
    monkeypatch.setattr(catalog, 'execute', gated)
    task = asyncio.create_task(ctx.workspace_controller.create(str(root)))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        handler = catalog._handlers.pop('project.create')
        catalog.register('project.create', handler)
        release.set()
        with pytest.raises(RuntimeError) as error: await task
        assert error.value.may_have_changed and await db.project_store.resolve_by_path(root) is not None
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_concurrent_creates_use_native_transaction_result(empty_workspace):
    ctx, db, _, root = empty_workspace
    first, second = await asyncio.gather(*(ctx.workspace_controller.create(str(root)) for _ in range(2)))
    assert sorted([first['created'], second['created']]) == [False, True]
    assert first['project']['id'] == second['project']['id']
    assert len(await db.project_store.list()) == 1
    assert len(await db.project_store.list_sessions(first['project']['id'])) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['scope', 'catalog'])
async def test_revoked_before_creation_does_not_write(empty_workspace, monkeypatch, change):
    ctx, db, catalog, root = empty_workspace
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == 'project.resolve': entered.set(); await release.wait()
        return result
    monkeypatch.setattr(catalog, 'execute', gated)
    task = asyncio.create_task(ctx.workspace_controller.create(str(root)))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if change == 'scope': ctx._registration_scope.revoke()
        else: ctx.operation_catalog = OperationCatalog()
        release.set()
        with pytest.raises(RuntimeError): await task
        assert await db.project_store.resolve_by_path(root) is None
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_directory_removed_during_admission_is_not_recreated(empty_workspace, monkeypatch):
    ctx, db, catalog, root = empty_workspace
    original = catalog.execute
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == 'project.resolve': entered.set(); await release.wait()
        return result
    monkeypatch.setattr(catalog, 'execute', gated)
    task = asyncio.create_task(ctx.workspace_controller.create(str(root)))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        root.rmdir()
        release.set()
        with pytest.raises(RuntimeError): await task
        assert not root.exists() and await db.project_store.resolve_by_path(root) is None
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_create_via_explicit_authenticated_remote(empty_workspace, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, db, _, root = empty_workspace
    host, catalog, original = _host(tmp_path)
    configure(host)
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        'async def echo(request, *, context):\n'
        '    return await context.workspace_controller.create(request.payload["body"]["text"])\n', encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        body = {'args': {'text': str(root)}}
        denied = await client.post('/plugin-remote/hook-demo/demo/echo', json=body, headers={'x-plugin-token': 'wrong'})
        assert denied.status_code == 401 and await db.project_store.resolve_by_path(root) is None
        headers = {'x-plugin-token': plugin_http_token(host, 'hook-demo')}
        made = await client.post('/plugin-remote/hook-demo/demo/echo', json=body, headers=headers)
        again = await client.post('/plugin-remote/hook-demo/demo/echo', json=body, headers=headers)
    assert made.status_code == again.status_code == 200
    assert made.json()['payload']['created'] is True and again.json()['payload']['created'] is False
    assert (await db.project_store.resolve_by_path(root)).id == made.json()['payload']['project']['id']


def test_create_migration_reports_native_session_difference(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {'index.ts': 'export function apply(ctx) { ctx.remote.workspace.create(); }'})
    report = export_port(root, tmp_path / 'ported')
    item = next(row for row in report['remotes'] if row['name'] == 'workspace.create')
    assert item['suggestedContract'] == 'context.workspace_controller.create'
    assert '初始会话' in item['difference'] and report['runtimeVerified'] is False
