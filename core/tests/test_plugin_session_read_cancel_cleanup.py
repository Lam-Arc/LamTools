"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(会话读取的重复取消不能中断原提供方清理)。"""
import asyncio
import pytest
from .test_plugin_working_directory import env

@pytest.mark.asyncio
@pytest.mark.parametrize('method',['state','wait'])
async def test_session_read_repeated_cancellation_waits_for_provider_cleanup(env,monkeypatch,method):
    ctx,_,_,_=env; api=ctx.session_controller; entered=asyncio.Event(); cleaning=asyncio.Event(); release=asyncio.Event(); cleaned=asyncio.Event()
    async def gated(*args,**kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait(); cleaned.set()
    monkeypatch.setattr(api._sessions,'call',gated)
    task=asyncio.create_task(api.state('s') if method=='state' else api.wait('s',timeout=1))
    try:
        await asyncio.wait_for(entered.wait(),3); task.cancel(); await asyncio.wait_for(cleaning.wait(),3)
        task.cancel(); await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert cleaned.is_set() and ctx._registration_scope._idle.is_set()
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_native_scoped_reads_remain_available(env):
    ctx,_,_,_=env; api=ctx.session_controller
    assert (await api.state('s')).session_id=='s'
    assert (await api.events('s')).session_id=='s'
    assert (await api.wait('s',timeout=0)).state.session_id=='s'
    assert ctx._registration_scope._idle.is_set()

@pytest.mark.asyncio
async def test_scope_drain_waits_for_cancelled_read_cleanup(env,monkeypatch):
    ctx,_,_,_=env; api=ctx.session_controller; entered=asyncio.Event(); cleaning=asyncio.Event(); release=asyncio.Event()
    async def gated(*args,**kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait()
    monkeypatch.setattr(api._sessions,'call',gated)
    task=asyncio.create_task(api.state('s'))
    try:
        await asyncio.wait_for(entered.wait(),3); task.cancel(); await asyncio.wait_for(cleaning.wait(),3)
        drain=asyncio.create_task(ctx._registration_scope.drain()); await asyncio.sleep(0)
        assert not drain.done(); release.set()
        with pytest.raises(asyncio.CancelledError): await task
        await asyncio.wait_for(drain,3)
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_remote_cancel_joins_original_read_cleanup(env,tmp_path,monkeypatch):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    from lamtools_core.plugin_system.services import ServiceRef
    ctx,_,_,_=env; host,catalog,old=_host(tmp_path); configure(host); ctx._secret_store=old._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text("async def echo(request, *, context):\n    return await context.session_controller.state('s')\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    entered,cleaning,release,cleaned=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    original=ServiceRef.call
    async def gated(self,method,*args,**kwargs):
        if self.key.name!='sessions' or method!='state': return await original(self,method,*args,**kwargs)
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait(); cleaned.set()
    monkeypatch.setattr(ServiceRef,'call',gated)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'x'}},headers={'x-plugin-token':plugin_http_token(host,'hook-demo')}))
        try:
            await asyncio.wait_for(entered.wait(),3); task.cancel(); await asyncio.wait_for(cleaning.wait(),3); task.cancel(); await asyncio.sleep(0)
            assert not task.done() and not ctx._registration_scope._idle.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError): await task
            assert cleaned.is_set() and ctx._registration_scope._idle.is_set()
        finally:
            release.set(); await asyncio.gather(task,return_exceptions=True)
