"""user:“第二阶段结束后 就继续开展第三阶段”+(会话投影返回前复核原项目和可见性)。"""
import asyncio
import pytest
from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['hidden','moved'])
@pytest.mark.parametrize('method',['get','events'])
async def test_projection_rechecks_session_after_read(env, monkeypatch, tmp_path, change, method):
    ctx, store, _, _ = env
    api = ctx.session_projections
    original = api._host.call
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(api._host, 'call', gated)
    task = asyncio.create_task(api.get('s') if method == 'get' else api.events('s'))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if change == 'hidden':
            store._session_visible = lambda *_: False
        else:
            record, revision = await store.get_readonly_revision('s')
            await store.patch('s', metadata={**record.metadata, 'work_root':str(tmp_path / 'other')}, expected_revision=revision)
        release.set()
        with pytest.raises(RuntimeError) as exc: await task
        assert exc.value.code == 'session-data/not-found'
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_hidden_projection_is_not_returned_over_remote(env, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, store, _, _ = env
    host, catalog, old = _host(tmp_path)
    configure(host)
    ctx._secret_store = old._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        "async def echo(request, *, context):\n    return await context.session_projections.get('s')\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    original = ctx.session_projections._host.call
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(ctx.session_projections._host, 'call', gated)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        task = asyncio.create_task(client.post('/plugin-remote/hook-demo/demo/echo', json={'args':{'text':'go'}},
            headers={'x-plugin-token':plugin_http_token(host, 'hook-demo')}))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            store._session_visible = lambda *_: False
            release.set()
            response = await task
            assert response.status_code == 400 and 'Example' not in response.text
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
