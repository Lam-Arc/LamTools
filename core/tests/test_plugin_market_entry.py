"""user:“第二阶段结束后 就继续开展第三阶段”+(按原固定市场目录精确读取条目，保留来源与不可用状态)。"""
import pytest
from .test_plugin_market_readonly_remote import market_env

@pytest.mark.asyncio
async def test_exact_entry_reads_native_catalog_and_reports_missing(market_env):
    ctx, host, _, _ = market_env
    found = await ctx.plugin_market.entry('qq-bot')
    assert found['item']['id'] == 'qq-bot' and found['item']['installable']
    assert found['source'] == 'github' and host.get('qq-bot') is None
    missing = await ctx.plugin_market.entry('QQ-BOT')
    assert missing['item'] is None and missing['source'] == 'github'

@pytest.mark.asyncio
@pytest.mark.parametrize('name', [None, '', 'x'*201, '\x00', '\ud800'])
async def test_invalid_entry_fails_before_provider(market_env, monkeypatch, name):
    ctx, _, catalog, _ = market_env
    async def forbidden(*args, **kwargs): pytest.fail('invalid name entered provider')
    monkeypatch.setattr(catalog, 'execute', forbidden)
    with pytest.raises(ValueError): await ctx.plugin_market.entry(name)

@pytest.mark.asyncio
async def test_entry_http_and_cached_source(market_env, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_remote_gateway import configure
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    from lamtools_core.plugin_system import market
    ctx, host, _, _ = market_env
    ctx._secret_store = host.backend_manager.context._secret_store
    host.backend_manager.context = ctx
    configure(host)
    (host.get('hook-demo').root / 'ops.py').write_text(
        "async def echo(request, *, context):\n    return await context.plugin_market.entry(request.payload['body']['text'])\n", encoding='utf8')
    catalog = OperationCatalog(); register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')}
        response=await client.post('/plugin-remote/hook-demo/demo/echo', json={'args':{'text':'qq-bot'}},headers=headers)
        assert response.status_code == 200 and response.json()['payload']['item']['id'] == 'qq-bot'
        def offline(*args, **kwargs): raise OSError('offline')
        monkeypatch.setattr(market, 'get_json', offline)
        response=await client.post('/plugin-remote/hook-demo/demo/echo', json={'args':{'text':'unknown'}},headers=headers)
        assert response.json()['payload']['item'] is None and response.json()['payload']['source'] == 'cache'



@pytest.mark.asyncio
async def test_entry_preserves_native_unavailable_state(market_env, monkeypatch):
    from lamtools_core.plugin_system import market
    ctx, _, _, _ = market_env
    def offline(*args, **kwargs): raise OSError('offline')
    monkeypatch.setattr(market, 'get_json', offline)
    result = await ctx.plugin_market.entry('qq-bot')
    assert result['source'] == 'unavailable' and result['error']
    assert result['item']['installable'] is False
