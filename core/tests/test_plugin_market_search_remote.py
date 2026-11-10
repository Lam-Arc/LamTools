"""user:“第二阶段结束后 就继续开展第三阶段”+(搜索原市场目录并保留真实来源及可用状态)。"""
import pytest
from .test_plugin_market_readonly_remote import market_env


@pytest.mark.asyncio
async def test_search_filters_actual_catalog_and_paginates(market_env):
    ctx, host, _, _ = market_env
    first = await ctx.plugin_market.search('', offset=0, limit=1)
    assert first['total'] == 2 and first['next_offset'] == 1 and first['source'] == 'github'
    second = await ctx.plugin_market.search('', offset=1, limit=1)
    assert second['total'] == 2 and second['next_offset'] is None
    assert first['items'][0]['id'] != second['items'][0]['id']
    result = await ctx.plugin_market.search('ＱＱ', offset=0, limit=10)
    assert [item['id'] for item in result['items']] == ['qq-bot']
    assert result['items'][0]['installable'] and host.get('qq-bot') is None
    assert (await ctx.plugin_market.search('无匹配', offset=0, limit=10))['items'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('text,offset,limit', [(None,0,1), ('x'*201,0,1), ('\x00',0,1), ('\ud800',0,1),
    ('',True,1), ('',-1,1), ('',0,True), ('',0,0), ('',0,101)])
async def test_invalid_search_rejected_before_provider(market_env, monkeypatch, text, offset, limit):
    ctx, _, catalog, _ = market_env
    async def forbidden(*args, **kwargs): pytest.fail('invalid query must not call provider')
    monkeypatch.setattr(catalog, 'execute', forbidden)
    with pytest.raises(ValueError): await ctx.plugin_market.search(text, offset=offset, limit=limit)


@pytest.mark.asyncio
async def test_offline_source_is_not_hidden_by_empty_search(market_env, monkeypatch):
    from lamtools_core.plugin_system import market
    ctx, _, _, _ = market_env
    def offline(*args, **kwargs): raise OSError('offline test')
    monkeypatch.setattr(market, 'get_json', offline)
    result = await ctx.plugin_market.search('no result')
    assert result['items'] == [] and result['source'] == 'unavailable' and result['error']


@pytest.mark.asyncio
async def test_search_crosses_real_explicit_http(market_env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_remote_gateway import configure
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, host, _, _ = market_env
    ctx._secret_store = host.backend_manager.context._secret_store
    host.backend_manager.context = ctx
    configure(host)
    (host.get('hook-demo').root / 'ops.py').write_text(
        'async def echo(request, *, context):\n'
        "    return await context.plugin_market.search(request.payload['body']['text'], limit=1)\n", encoding='utf8')
    catalog = OperationCatalog()
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'QQ'}},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert response.status_code == 200
    assert response.json()['payload']['items'][0]['id'] == 'qq-bot'
    assert host.get('qq-bot') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['cancel', 'scope'])
async def test_search_waits_for_provider_and_does_not_publish_after_revocation(market_env, monkeypatch, change):
    import asyncio
    import threading
    from lamtools_core.plugin_system import market
    ctx, _, _, data = market_env
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def gated():
        entered.set()
        release.wait()
        try: return market.validate_catalog(data)
        finally: finished.set()
    monkeypatch.setattr(market, 'load_catalog', gated)
    task = asyncio.create_task(ctx.plugin_market.search('qq'))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        if change == 'cancel':
            task.cancel()
            await asyncio.sleep(0.02)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        else:
            ctx._registration_scope.revoke()
        release.set()
        with pytest.raises(asyncio.CancelledError if change == 'cancel' else RuntimeError): await task
        assert finished.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


def test_migration_suggests_bounded_original_catalog_search(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {'index.ts': 'export function apply(ctx) { ctx.remote.pluginMarket.search(); }'})
    report = export_port(root, tmp_path / 'ported')
    item = next(row for row in report['remotes'] if row['name'] == 'pluginMarket.search')
    assert item['suggestedContract'] == 'context.plugin_market.search'
    assert '固定' in item['difference'] and report['runtimeVerified'] is False
