"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(同名操作重新注册后旧流和上传不能继续)。"""
import asyncio,json
import pytest
from .test_plugin_remote_stream import setup
from .test_plugin_raw_upload_stream import upload_env
from .test_plugin_working_directory import env
from lamtools_core.app.operation_catalog import OperationResult
from lamtools_core.plugin_system.plugin_http import plugin_http_token

@pytest.mark.asyncio
async def test_remote_stream_stops_when_same_owner_operation_replaced(tmp_path,monkeypatch):
    from lamtools_core.plugin_system import remote_stream
    monkeypatch.setattr(remote_stream,'POLL_INTERVAL',.01)
    waiting,closed=asyncio.Event(),asyncio.Event()
    class Source:
        def __aiter__(self): return self
        async def __anext__(self): waiting.set(); await asyncio.Event().wait()
        async def aclose(self): closed.set()
    host,catalog,app=setup(tmp_path,Source()); token=plugin_http_token(host,'hook-demo'); sent=[]; delivered=False
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered=True; return {'type':'http.request','body':json.dumps({'args':{'text':'x'}}).encode(),'more_body':False}
        await asyncio.Event().wait()
    async def send(message): sent.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-remote/hook-demo/demo/echo','query_string':b'',
        'headers':[(b'content-type',b'application/json'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        await asyncio.wait_for(waiting.wait(),3)
        catalog.unregister_owner('plugin:hook-demo')
        catalog.register('hook-demo.echo',lambda req:OperationResult(req.name,{}),owner='plugin:hook-demo')
        await asyncio.wait_for(asyncio.shield(task),1)
        assert closed.is_set() and json.loads(sent[-1]['body'])['kind']=='error'
        assert not host._remote_stream_slots
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_upload_stops_when_same_owner_operation_replaced(upload_env):
    ctx,host,app=upload_env; catalog=app.state.providers['catalog']; token=plugin_http_token(host,'hook-demo')
    entered,cancelled=asyncio.Event(),asyncio.Event(); reads=0; sent=[]
    async def receive():
        nonlocal reads
        reads+=1
        if reads==1:return {'type':'http.request','body':b'a','more_body':True}
        entered.set()
        try: await asyncio.Event().wait()
        finally: cancelled.set()
    async def send(message): sent.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-upload/hook-demo/files','query_string':b'',
        'headers':[(b'content-type',b'application/octet-stream'),(b'x-upload-size',b'2'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        await asyncio.wait_for(entered.wait(),3); catalog.unregister_owner('plugin:hook-demo')
        catalog.register('hook-demo.echo',lambda req:OperationResult(req.name,{}),owner='plugin:hook-demo')
        await asyncio.wait_for(asyncio.shield(task),1)
        assert cancelled.is_set() and next(m['status'] for m in sent if m['type']=='http.response.start')==409
        assert not host._remote_stream_slots and not (await ctx.attachments.list('s'))['items']
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
@pytest.mark.parametrize('encoding',['json','ndjson'])
async def test_remote_rejects_same_owner_replacement_before_dispatch(tmp_path,monkeypatch,encoding):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.plugin_system import plugin_http
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router
    host,catalog,_=_host(tmp_path); configure(host)
    if encoding=='ndjson': set_encoding(host,encoding)
    token=plugin_http_token(host,'hook-demo'); called=[]; original=plugin_http.read_operations; changed=False
    def replace(manifest):
        nonlocal changed
        specs=original(manifest)
        if not changed:
            changed=True; catalog.unregister_owner('plugin:hook-demo')
            def fake(req): called.append(True); return OperationResult(req.name,{'injected':True})
            catalog.register('hook-demo.echo',fake,owner='plugin:hook-demo')
        return specs
    monkeypatch.setattr(plugin_http,'read_operations',replace)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'x'}},headers={'x-plugin-token':token})
    assert response.status_code==409 and not called and not getattr(host,'_remote_stream_slots',{})

@pytest.mark.asyncio
@pytest.mark.parametrize('encoding',['json','ndjson'])
async def test_unchanged_remote_operation_still_works(tmp_path,encoding):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router
    host,catalog,_=_host(tmp_path); configure(host)
    if encoding=='ndjson':
        set_encoding(host,encoding)
        async def source(): yield {'ready':True}
        catalog.unregister_owner('plugin:hook-demo')
        catalog.register('hook-demo.echo',lambda req:OperationResult(req.name,source()),owner='plugin:hook-demo')
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=await client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'x'}},headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    assert result.status_code==200
    if encoding=='ndjson': assert [json.loads(x)['kind'] for x in result.text.splitlines()]==['item','end']
    else: assert result.json()['payload']['echo']=={'text':'x'}
