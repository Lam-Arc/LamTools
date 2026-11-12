"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(投影读取重复取消时等待原提供方清理)。"""
import asyncio
import pytest
from .test_plugin_working_directory import env

@pytest.mark.asyncio
async def test_projection_observer_repeated_cancel_waits_for_source(env,monkeypatch):
    ctx,_,_,_=env; entered,cleaning,release,cleaned=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def gated(*args,**kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait(); cleaned.set()
    monkeypatch.setattr(ctx.require_service('session_data'),'call',gated)
    stream=ctx.session_controller.observe_projections('s',interval=.01); task=asyncio.create_task(anext(stream))
    try:
        await asyncio.wait_for(entered.wait(),3); task.cancel(); await asyncio.wait_for(cleaning.wait(),3)
        task.cancel(); await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert cleaned.is_set() and ctx._registration_scope._idle.is_set()
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True); await stream.aclose()

@pytest.mark.asyncio
async def test_normal_projection_and_scoped_state_still_work(env):
    ctx,_,_,_=env; api=ctx.session_controller; stream=api.observe_projections('s',interval=.01)
    try: assert (await anext(stream))['session_id']=='s' and (await api.state('s')).session_id=='s'
    finally: await stream.aclose()
    assert ctx._registration_scope._idle.is_set()

@pytest.mark.asyncio
async def test_projection_disconnect_waits_for_real_source_cleanup(env,tmp_path,monkeypatch):
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,_,_,_=env; host,_,old=_host(tmp_path); configure(host); set_encoding(host,'ndjson')
    ctx._secret_store=old._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text("from lamtools_core.app.operation_catalog import OperationResult\nasync def echo(request, *, context):\n    return OperationResult(request.name,context.session_controller.observe_projections('s',interval=.01))\n",encoding='utf8')
    catalog=OperationCatalog(); register_plugin_operations(catalog,host); app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    entered,cleaning,release,cleaned=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def gated(*args,**kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait(); cleaned.set()
    monkeypatch.setattr(ctx.require_service('session_data'),'call',gated)
    reads=0; disconnect=asyncio.Event(); sent=[]
    async def receive():
        nonlocal reads
        reads+=1
        if reads==1:return {'type':'http.request','body':b'{"args":{"text":"x"}}','more_body':False}
        await disconnect.wait(); return {'type':'http.disconnect'}
    async def send(message): sent.append(message)
    token=plugin_http_token(host,'hook-demo'); scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http','path':'/plugin-remote/hook-demo/demo/echo','query_string':b'',
        'headers':[(b'content-type',b'application/json'),(b'x-plugin-token',token.encode())], 'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        await asyncio.wait_for(entered.wait(),3); disconnect.set(); await asyncio.wait_for(cleaning.wait(),3)
        assert not task.done() and host._remote_stream_slots and not ctx._registration_scope._idle.is_set()
        release.set(); await asyncio.wait_for(task,3)
        assert cleaned.is_set() and not host._remote_stream_slots and ctx._registration_scope._idle.is_set()
    finally:
        release.set(); disconnect.set()
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_shared_read_helper_preserves_state_repeated_cancel(env,monkeypatch):
    ctx,_,_,_=env; api=ctx.session_controller; entered,cleaning,release,cleaned=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def gated(*args,**kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait(); cleaned.set()
    monkeypatch.setattr(api._sessions,'call',gated); task=asyncio.create_task(api.state('s'))
    try:
        await asyncio.wait_for(entered.wait(),3); task.cancel(); await asyncio.wait_for(cleaning.wait(),3); task.cancel(); await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError):await task
        assert cleaned.is_set() and ctx._registration_scope._idle.is_set()
    finally: release.set(); await asyncio.gather(task,return_exceptions=True)
