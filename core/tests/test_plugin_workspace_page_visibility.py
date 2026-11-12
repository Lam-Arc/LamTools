"""user:“第二阶段结束后 就继续开展第三阶段”+(会话分页返回前复核已选记录)。"""
import asyncio
import pytest
from .test_plugin_workspace_sessions import populated
from .test_plugin_workspace_registry_current import workspace_env


@pytest.mark.asyncio
async def test_earlier_session_hidden_while_later_row_is_read(populated, monkeypatch):
    ctx, _, _, project, _, store = populated
    original = store.get_readonly
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(identifier):
        result = await original(identifier)
        if identifier == 'b':
            entered.set()
            await release.wait()
        return result
    monkeypatch.setattr(store, 'get_readonly', gated)
    task = asyncio.create_task(ctx.workspace_registry.sessions(project.id, limit=50))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        store._session_visible = lambda sid, _: sid not in {'a', 'hidden'}
        release.set()
        page = await task
        assert 'a' not in {item.session_id for item in page.items}
        assert 'b' in {item.session_id for item in page.items}
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_http_page_omits_session_hidden_during_scan(populated, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, project, _, store = populated
    host, catalog, original_context = _host(tmp_path)
    configure(host)
    ctx._secret_store = original_context._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        'from lamtools_core.app.operation_catalog import OperationResult\n'
        'async def echo(request, *, context):\n'
        f"    return OperationResult(request.name, await context.workspace_registry.sessions('{project.id}'))\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    original = store.get_readonly
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(identifier):
        result = await original(identifier)
        if identifier == 'b' and not entered.is_set():
            entered.set()
            await release.wait()
        return result
    monkeypatch.setattr(store, 'get_readonly', gated)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        task = asyncio.create_task(client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'go'}},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')}))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            store._session_visible = lambda sid, _: sid not in {'a', 'hidden'}
            release.set()
            response = await task
            assert response.status_code == 200
            assert 'a' not in {x['session_id'] for x in response.json()['payload']['items']}
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
