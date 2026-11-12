"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(一元远程请求等待期间撤回不能返回旧业务结果)。"""
import asyncio
import httpx
import pytest
from fastapi import FastAPI
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from lamtools_core.app.operation_catalog import OperationResult
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token

@pytest.mark.asyncio
@pytest.mark.parametrize('change',['token','operation'])
async def test_unary_remote_withdrawal_while_handler_runs_does_not_publish(tmp_path,change):
    host,catalog,_=_host(tmp_path); configure(host); token=plugin_http_token(host,'hook-demo')
    entered,release=asyncio.Event(),asyncio.Event()
    async def handler(req):
        entered.set(); await release.wait(); return OperationResult(req.name,{'private':'must-not-leak'})
    catalog.unregister_owner('plugin:hook-demo'); catalog.register('hook-demo.echo',handler,owner='plugin:hook-demo')
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'x'}},headers={'x-plugin-token':token}))
        try:
            await asyncio.wait_for(entered.wait(),3)
            if change=='token': host.backend_manager.context._secret_store.view('hook-demo').delete('httpToken')
            else:
                catalog.unregister_owner('plugin:hook-demo')
                catalog.register('hook-demo.echo',lambda req:OperationResult(req.name,{}),owner='plugin:hook-demo')
            release.set(); response=await task
            assert response.status_code==409 and 'must-not-leak' not in response.text
            assert response.json().get('may_have_changed') is True
        finally:
            release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_ndjson_returned_after_revocation_closes_source(tmp_path):
    from .test_plugin_remote_binary import set_encoding
    host,catalog,_=_host(tmp_path); configure(host); set_encoding(host,'ndjson'); token=plugin_http_token(host,'hook-demo')
    entered,release,closed=asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def source():
        try: yield 'secret'
        finally: closed.set()
    async def handler(req):
        stream=source(); await anext(stream); entered.set(); await release.wait()
        return OperationResult(req.name,stream)
    catalog.unregister_owner('plugin:hook-demo'); catalog.register('hook-demo.echo',handler,owner='plugin:hook-demo')
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'x'}},headers={'x-plugin-token':token}))
        try:
            await asyncio.wait_for(entered.wait(),3); host.backend_manager.context._secret_store.view('hook-demo').delete('httpToken'); release.set()
            response=await task
            assert response.status_code==409 and closed.is_set() and 'secret' not in response.text and not host._remote_stream_slots
        finally:
            release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_revalidation_does_not_claim_write_was_rolled_back(tmp_path):
    host,catalog,_=_host(tmp_path); configure(host); token=plugin_http_token(host,'hook-demo')
    entered,release=asyncio.Event(),asyncio.Event(); target=tmp_path/'committed.txt'
    async def handler(req):
        target.write_text('committed'); entered.set(); await release.wait(); return OperationResult(req.name,{'ok':True})
    catalog.unregister_owner('plugin:hook-demo'); catalog.register('hook-demo.echo',handler,owner='plugin:hook-demo')
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'x'}},headers={'x-plugin-token':token}))
        try:
            await asyncio.wait_for(entered.wait(),3); host.backend_manager.context._secret_store.view('hook-demo').delete('httpToken'); release.set()
            response=await task
            assert response.status_code==409 and response.json()['may_have_changed'] is True and target.read_text()=='committed'
        finally:
            release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
@pytest.mark.parametrize('replace',['host','catalog'])
async def test_unary_rejects_replaced_application_provider(tmp_path,replace):
    host,catalog,_=_host(tmp_path); configure(host); token=plugin_http_token(host,'hook-demo'); entered=asyncio.Event(); release=asyncio.Event()
    async def handler(req): entered.set(); await release.wait(); return OperationResult(req.name,{'secret':'old'})
    catalog.unregister_owner('plugin:hook-demo'); catalog.register('hook-demo.echo',handler,owner='plugin:hook-demo')
    app=FastAPI(); app.state.providers={'host':host,'catalog':catalog}
    app.include_router(create_plugin_http_router(lambda:app.state.providers['host'],lambda:app.state.providers['catalog']))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'x'}},headers={'x-plugin-token':token}))
        try:
            await asyncio.wait_for(entered.wait(),3); app.state.providers[replace]=None; release.set(); response=await task
            assert response.status_code==409 and 'old' not in response.text
        finally:
            release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_stream_closes_if_application_catalog_is_replaced(tmp_path,monkeypatch):
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.plugin_system import remote_stream
    monkeypatch.setattr(remote_stream,'POLL_INTERVAL',.01)
    host,catalog,_=_host(tmp_path); configure(host); set_encoding(host,'ndjson'); token=plugin_http_token(host,'hook-demo')
    waiting,closed=asyncio.Event(),asyncio.Event()
    class Source:
        def __aiter__(self): return self
        async def __anext__(self): waiting.set(); await asyncio.Event().wait()
        async def aclose(self): closed.set()
    catalog.unregister_owner('plugin:hook-demo'); catalog.register('hook-demo.echo',lambda req:OperationResult(req.name,Source()),owner='plugin:hook-demo')
    app=FastAPI(); app.state.providers={'host':host,'catalog':catalog}
    app.include_router(create_plugin_http_router(lambda:app.state.providers['host'],lambda:app.state.providers['catalog']))
    reads=0; sent=[]
    async def receive():
        nonlocal reads
        reads+=1
        if reads==1:return {'type':'http.request','body':b'{"args":{"text":"x"}}','more_body':False}
        await asyncio.Event().wait()
    async def send(message): sent.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-remote/hook-demo/demo/echo','query_string':b'',
        'headers':[(b'content-type',b'application/json'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        await asyncio.wait_for(waiting.wait(),3); app.state.providers['catalog']=None
        await asyncio.wait_for(task,3)
        assert closed.is_set() and not host._remote_stream_slots and sent[-1]['more_body'] is False
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)
