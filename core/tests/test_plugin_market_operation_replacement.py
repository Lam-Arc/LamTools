"""user:“不用静态扫描、空壳或未安装提供方冒充可用”+(读取等待期间原市场同名操作替换也拒绝旧结果)。"""
import asyncio
import threading
import pytest
from .test_plugin_market_readonly_remote import market_env
from lamtools_core.app.operation_catalog import OperationResult

@pytest.mark.asyncio
async def test_same_owner_replacement_does_not_publish_old_market(market_env,monkeypatch):
    from lamtools_core.plugin_system import market
    ctx,_,catalog,data=market_env; entered,release=threading.Event(),threading.Event()
    def gated(): entered.set(); release.wait(); return market.validate_catalog(data)
    monkeypatch.setattr(market,'load_catalog',gated)
    task=asyncio.create_task(ctx.plugin_market.list())
    try:
        assert await asyncio.to_thread(entered.wait,3)
        catalog.unregister_owner('plugin-system')
        catalog.register('plugin.market.list',lambda req:OperationResult(req.name,{}),owner='plugin-system')
        release.set()
        with pytest.raises(RuntimeError): await task
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_unchanged_market_binding_returns_native_result(market_env):
    ctx,_,_,_=market_env
    result=await ctx.plugin_market.list()
    assert result['source']=='github' and any(item['id']=='qq-bot' for item in result['plugins'])

@pytest.mark.asyncio
async def test_same_owner_replacement_cannot_leak_over_remote(market_env,monkeypatch,tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system import market
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,host,catalog,data=market_env; ctx._secret_store=host.backend_manager.context._secret_store; host.backend_manager.context=ctx; configure(host)
    (host.get('hook-demo').root/'ops.py').write_text('async def echo(request, *, context):\n    return await context.plugin_market.list()\n',encoding='utf8')
    plugins=OperationCatalog(); register_plugin_operations(plugins,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:plugins))
    entered,release=threading.Event(),threading.Event()
    def gated(): entered.set(); release.wait(); return market.validate_catalog(data)
    monkeypatch.setattr(market,'load_catalog',gated)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'list'}},headers={'x-plugin-token':plugin_http_token(host,'hook-demo')}))
        try:
            assert await asyncio.to_thread(entered.wait,3)
            catalog.unregister_owner('plugin-system')
            catalog.register('plugin.market.list',lambda req:OperationResult(req.name,{}),owner='plugin-system')
            release.set(); response=await task
            assert response.status_code>=400 and '1.2.3' not in response.text
        finally:
            release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_replacement_before_dispatch_never_executes_new_handler(market_env,monkeypatch):
    from lamtools_core.plugin_system import market_access
    ctx,_,catalog,_=market_env; entered=asyncio.Event(); release=asyncio.Event(); called=[]
    original=market_access.finish_on_cancel
    async def delayed(work,*,name):
        entered.set(); await release.wait()
        return await original(work,name=name)
    monkeypatch.setattr(market_access,'finish_on_cancel',delayed)
    task=asyncio.create_task(ctx.plugin_market.list())
    try:
        await asyncio.wait_for(entered.wait(),3); catalog.unregister_owner('plugin-system')
        def fake(req): called.append(True); return OperationResult(req.name,{'plugins':[]})
        catalog.register('plugin.market.list',fake,owner='plugin-system'); release.set()
        with pytest.raises(RuntimeError): await task
        assert not called
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True)
