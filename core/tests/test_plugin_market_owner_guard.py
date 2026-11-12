"""user:“不用静态扫描、空壳或未安装提供方冒充可用”+(市场读取只接受原插件系统操作所有者)。"""
import asyncio
import threading
import pytest
from .test_plugin_market_readonly_remote import market_env
from lamtools_core.app.operation_catalog import OperationResult

@pytest.mark.asyncio
@pytest.mark.parametrize('method',['list','search','entry'])
async def test_foreign_market_operation_never_executes(market_env,method):
    ctx,_,catalog,_=market_env; catalog.unregister_owner('plugin-system'); called=[]
    def fake(req): called.append(True); return OperationResult(req.name,{'plugins':[],'source':'fake','error':None})
    catalog.register('plugin.market.list',fake,owner='foreign')
    with pytest.raises(RuntimeError):
        if method=='entry': await ctx.plugin_market.entry('qq-bot')
        else: await getattr(ctx.plugin_market,method)()
    assert not called

@pytest.mark.asyncio
async def test_owner_replaced_during_native_read_does_not_publish(market_env,monkeypatch):
    from lamtools_core.plugin_system import market
    ctx,_,catalog,data=market_env; entered,release=threading.Event(),threading.Event()
    def gated(): entered.set(); release.wait(); return market.validate_catalog(data)
    monkeypatch.setattr(market,'load_catalog',gated)
    task=asyncio.create_task(ctx.plugin_market.list())
    try:
        assert await asyncio.to_thread(entered.wait,3)
        catalog.unregister_owner('plugin-system')
        catalog.register('plugin.market.list',lambda req: OperationResult(req.name,{}),owner='foreign')
        release.set()
        with pytest.raises(RuntimeError): await task
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_foreign_market_owner_rejected_through_remote(market_env,tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_remote_gateway import configure
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,host,catalog,_=market_env; ctx._secret_store=host.backend_manager.context._secret_store; host.backend_manager.context=ctx; configure(host)
    (host.get('hook-demo').root/'ops.py').write_text('async def echo(request, *, context):\n    return await context.plugin_market.list()\n',encoding='utf8')
    plugins=OperationCatalog(); register_plugin_operations(plugins,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:plugins))
    catalog.unregister_owner('plugin-system'); called=[]
    def fake(req): called.append(True); return OperationResult(req.name,{'plugins':[],'source':'fake','error':None})
    catalog.register('plugin.market.list',fake,owner='foreign')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=await client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'list'}},headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    assert result.status_code>=400 and 'fake' not in result.text and not called
