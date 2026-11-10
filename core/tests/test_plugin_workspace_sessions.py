"""user:“第二阶段结束后 就继续开展第三阶段”+(只查询当前工作区可见会话，复用宿主有界扫描)。"""
import asyncio
import pytest
from .test_plugin_workspace_registry_current import workspace_env
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.live_operations import CoreLiveContext
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.app.plugin_sessions import install_plugin_session_services
from lamtools_core.session import SessionRecord


@pytest.fixture
async def populated(workspace_env):
    ctx, db, catalog, first, other = workspace_env
    store = CoreDbSessionStore(lambda: db)
    for sid, root in [('a', first.work_root), ('b', first.work_root), ('hidden', first.work_root), ('private', other.work_root)]:
        await store.create(SessionRecord(sid, 'core', sid, 'idle', metadata={'work_root': str(root)}))
    store._session_visible = lambda sid, _: sid != 'hidden'
    live = CoreLiveContext(session_factory=db.session_factory, persistence=db.persistence, operations=OperationCatalog(), hub=CoreAppEventHub())
    live.host.session_store = store
    sessions = install_plugin_session_services(ctx, lambda: live)
    try: yield ctx, db, catalog, first, other, store
    finally: sessions.shutdown()


@pytest.mark.asyncio
async def test_current_workspace_visible_sessions_and_cursor(populated):
    ctx, _, _, first, other, _ = populated
    api = ctx.workspace_registry
    page = await api.sessions(first.id, limit=1)
    assert len(page.items) == 1 and page.has_more
    first_cursor = page.next_cursor
    ids = [x.session_id for x in page.items]
    while page.has_more:
        page = await api.sessions(first.id, limit=1, cursor=page.next_cursor)
        ids.extend(x.session_id for x in page.items)
    assert {'a', 'b'}.issubset(ids) and 'hidden' not in ids and 'private' not in ids
    with pytest.raises(RuntimeError): await api.sessions(other.id)
    with pytest.raises(RuntimeError): await ctx.session_query.query(cursor=first_cursor)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['scope', 'catalog', 'service', 'root', 'cancel'])
async def test_inflight_scan_does_not_publish_after_binding_change(populated, monkeypatch, tmp_path, change):
    ctx, _, catalog, first, _, store = populated
    original = store.scan_readonly
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(store, 'scan_readonly', gated)
    task = asyncio.create_task(ctx.workspace_registry.sessions(first.id))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if change == 'scope': ctx._registration_scope.revoke()
        elif change == 'catalog': ctx.operation_catalog = OperationCatalog()
        elif change == 'service': ctx.set_service('session_query', object())
        elif change == 'root': ctx.work_root = tmp_path / 'elsewhere'
        else: task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError if change == 'cancel' else RuntimeError): await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_missing_native_session_provider_is_explicit(workspace_env):
    ctx, _, _, first, _ = workspace_env
    with pytest.raises(RuntimeError) as error: await ctx.workspace_registry.sessions(first.id)
    assert error.value.code == 'workspace-registry/unavailable'


@pytest.mark.asyncio
@pytest.mark.parametrize('limit', [0, 101, True])
async def test_invalid_page_limit_fails(populated, limit):
    ctx, _, _, first, _, _ = populated
    with pytest.raises(RuntimeError) as error: await ctx.workspace_registry.sessions(first.id, limit=limit)
    assert error.value.code == 'session-query/invalid-query'


@pytest.mark.asyncio
async def test_deleted_workspace_during_scan_cannot_publish_old_page(populated, monkeypatch):
    ctx, db, _, first, _, store = populated
    original = store.scan_readonly
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        rows = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return rows
    monkeypatch.setattr(store, 'scan_readonly', gated)
    task = asyncio.create_task(ctx.workspace_registry.sessions(first.id))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        assert await db.project_store.delete_with_sessions(first.id)
        release.set()
        with pytest.raises(RuntimeError) as error: await task
        assert error.value.code == 'workspace-registry/not-found'
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_session_hidden_during_scan_is_not_published(populated, monkeypatch):
    ctx, _, _, first, _, store = populated
    original = store.scan_readonly
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        rows = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return rows
    monkeypatch.setattr(store, 'scan_readonly', gated)
    task = asyncio.create_task(ctx.workspace_registry.sessions(first.id))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        store._session_visible = lambda sid, _: sid not in {'a', 'hidden'}
        release.set()
        page = await task
        assert 'a' not in {row.session_id for row in page.items}
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_scoped_session_page_crosses_real_http(populated, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, first, _, _ = populated
    host, catalog, original = _host(tmp_path)
    configure(host)
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        'from lamtools_core.app.operation_catalog import OperationResult\n'
        'async def echo(request, *, context):\n'
        "    page = await context.workspace_registry.sessions(request.payload['body']['text'], limit=50)\n"
        '    return OperationResult(request.name, page)\n', encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': first.id}},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert response.status_code == 200
    ids = {row['session_id'] for row in response.json()['payload']['items']}
    assert {'a', 'b'}.issubset(ids) and not {'hidden', 'private'} & ids


def test_workspace_session_migration_names_scoped_query(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {'index.ts': 'export function apply(ctx) { ctx.workspaceRegistry.get().sessions(); }'})
    report = export_port(root, tmp_path / 'ported')
    assert 'context.workspace_registry.sessions' in (tmp_path / 'ported' / 'PORTING.md').read_text(encoding='utf8')
    assert report['runtimeVerified'] is False
