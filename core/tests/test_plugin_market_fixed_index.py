"""user:“第二阶段结束后 就继续开展第三阶段”+(市场索引只报告原已挂载固定提供方)。"""
import pytest
from .test_plugin_market_readonly_remote import market_env
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.market import CATALOG_URL


@pytest.mark.asyncio
async def test_fixed_index_reports_configured_source_without_network(market_env,monkeypatch):
    from lamtools_core.plugin_system import market
    ctx,_,_,_=market_env
    def forbidden(*args, **kwargs): pytest.fail('index inventory must not fetch')
    monkeypatch.setattr(market,'get_json',forbidden)
    assert await ctx.plugin_market.list_indexes()==[{'url':CATALOG_URL}]


@pytest.mark.asyncio
async def test_no_native_provider_or_wrong_owner_is_rejected(tmp_path):
    catalog=OperationCatalog(); ctx=PluginContext(tmp_path,operation_catalog=catalog)
    ctx._begin_registration_scope('market-test',1)
    try:
        with pytest.raises(RuntimeError): await ctx.plugin_market.list_indexes()
        catalog.register('plugin.market.list',lambda *_:None,owner='foreign')
        with pytest.raises(RuntimeError): await ctx.plugin_market.list_indexes()
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_index_view_respects_replaced_catalog_and_revocation(market_env):
    ctx,_,_,_=market_env; api=ctx.plugin_market
    ctx.operation_catalog=OperationCatalog()
    with pytest.raises(RuntimeError): await api.list_indexes()
    ctx._registration_scope.revoke()
    with pytest.raises(RuntimeError): await api.list_indexes()


@pytest.mark.asyncio
async def test_fixed_index_crosses_explicit_remote(market_env,tmp_path,monkeypatch):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system import market
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,host,_,_=market_env
    ctx._secret_store=host.backend_manager.context._secret_store; host.backend_manager.context=ctx
    configure(host)
    (host.get('hook-demo').root/'ops.py').write_text(
        "async def echo(request, *, context):\n    return {'indexes':await context.plugin_market.list_indexes()}\n",encoding='utf8')
    plugin_catalog=OperationCatalog(); register_plugin_operations(plugin_catalog,host)
    monkeypatch.setattr(market,'get_json',lambda *a,**k:pytest.fail('must not fetch'))
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:plugin_catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        path='/plugin-remote/hook-demo/demo/echo'; body={'args':{'text':'go'}}
        denied=await client.post(path,json=body,headers={'x-plugin-token':'wrong'})
        result=await client.post(path,json=body,headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    assert denied.status_code==401 and result.status_code==200
    assert result.json()['payload']['indexes']==[{'url':CATALOG_URL}]


def test_migration_reports_fixed_index_limit(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.remote.pluginMarket.listIndexes(); }'})
    report=export_port(root,tmp_path/'ported'); row=next(x for x in report['remotes'] if x['name']=='pluginMarket.listIndexes')
    assert row['suggestedContract']=='context.plugin_market.list_indexes' and row['conversion']=='agent-required'
