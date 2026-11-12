"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(明确资源可有界流式发送并在断连撤回时回收)。"""
import asyncio,json
import httpx,pytest
from .test_plugin_explicit_resources import resource_env
from lamtools_core.app.operation_catalog import OperationResult
from lamtools_core.plugin_system.plugin_http import plugin_http_token


def enable_stream(host):
    path=host.get('hook-demo').root/'plugin.json'; data=json.loads(path.read_text(encoding='utf8'))
    for row in data['http']['resources']:
        if row['kind']=='exact': row['encoding']='stream'
    path.write_text(json.dumps(data),encoding='utf8'); host._invalidate()

@pytest.mark.asyncio
async def test_explicit_stream_sends_real_chunks_and_head_closes_source(resource_env):
    host,_,app=resource_env; enable_stream(host); token=plugin_http_token(host,'hook-demo'); root=host.get('hook-demo').root
    (root/'ops.py').write_text("from pathlib import Path\nasync def exact(request, *, context):\n    async def content():\n        try:\n            yield b'first'\n            yield b'second'\n        finally: (Path(__file__).parent/'stream-closed').touch()\n    return {'content':content(), 'mime_type':'application/octet-stream'}\n",encoding='utf8')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=await client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token})
    assert result.status_code==200 and result.content==b'firstsecond' and 'content-length' not in result.headers
    assert (root/'stream-closed').exists() and not host._remote_stream_slots

@pytest.mark.asyncio
@pytest.mark.parametrize('stop',['disconnect','revoke'])
async def test_stream_idle_disconnect_or_withdrawal_joins_cleanup(resource_env,monkeypatch,stop):
    host,catalog,app=resource_env; enable_stream(host); token=plugin_http_token(host,'hook-demo')
    waiting,cleaning,release,closed,disconnect=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    class Source:
        def __aiter__(self):return self
        async def __anext__(self):waiting.set(); await asyncio.Event().wait()
        async def aclose(self):cleaning.set(); await release.wait(); closed.set()
    async def handler(name,*args,**kwargs):return OperationResult(name,{'content':Source(),'mime_type':'application/octet-stream'})
    monkeypatch.setattr(catalog,'execute',handler); reads=0; sent=[]
    async def receive():
        nonlocal reads
        reads+=1
        if reads==1:return {'type':'http.request','body':b'','more_body':False}
        await disconnect.wait(); return {'type':'http.disconnect'}
    async def send(message):sent.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'GET','scheme':'http','path':'/plugin-resource/hook-demo/a/b/c','query_string':b'',
        'headers':[(b'x-plugin-token',token.encode())], 'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        await asyncio.wait_for(waiting.wait(),3)
        if stop=='disconnect':disconnect.set()
        else:host.backend_manager.context._secret_store.view('hook-demo').delete('httpToken')
        await asyncio.wait_for(cleaning.wait(),3); assert not task.done() and host._remote_stream_slots
        release.set(); await asyncio.gather(task,return_exceptions=True)
        assert closed.is_set() and not host._remote_stream_slots
    finally:
        disconnect.set(); release.set()
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_stream_head_closes_without_pulling_and_has_no_length(resource_env,monkeypatch):
    host,catalog,app=resource_env; enable_stream(host); token=plugin_http_token(host,'hook-demo'); closed=asyncio.Event(); pulls=[]
    class Source:
        def __aiter__(self):return self
        async def __anext__(self):pulls.append(True); return b'x'
        async def aclose(self):closed.set()
    async def handler(name,*args,**kwargs):return OperationResult(name,{'content':Source(),'mime_type':'application/octet-stream'})
    monkeypatch.setattr(catalog,'execute',handler)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.head('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token})
    assert response.status_code==200 and not response.content and 'content-length' not in response.headers
    assert closed.is_set() and not pulls and not host._remote_stream_slots

@pytest.mark.asyncio
async def test_buffered_resource_rejects_nested_source_and_waits_cleanup(resource_env,monkeypatch):
    host,catalog,app=resource_env; token=plugin_http_token(host,'hook-demo'); cleaning,release,closed=asyncio.Event(),asyncio.Event(),asyncio.Event()
    class Source:
        def __aiter__(self):return self
        async def __anext__(self):return b'x'
        async def aclose(self):cleaning.set(); await release.wait(); closed.set()
    async def handler(name,*args,**kwargs):return OperationResult(name,{'content':Source(),'mime_type':'application/octet-stream'})
    monkeypatch.setattr(catalog,'execute',handler)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token}))
        try:
            await asyncio.wait_for(cleaning.wait(),3); assert not task.done() and host._remote_stream_slots
            release.set(); result=await task
            assert result.status_code==502 and closed.is_set() and not host._remote_stream_slots
        finally:
            release.set()
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_stream_oversized_chunk_aborts_without_sending_it(resource_env,monkeypatch):
    host,catalog,app=resource_env; enable_stream(host); token=plugin_http_token(host,'hook-demo'); closed=asyncio.Event(); sent=[]; reads=0
    class Source:
        def __aiter__(self):return self
        async def __anext__(self):return b'x'*(256*1024+1)
        async def aclose(self):closed.set()
    async def handler(name,*args,**kwargs):return OperationResult(name,{'content':Source(),'mime_type':'application/octet-stream'})
    monkeypatch.setattr(catalog,'execute',handler)
    async def receive():
        nonlocal reads
        reads+=1
        if reads==1:return {'type':'http.request','body':b'','more_body':False}
        await asyncio.Event().wait()
    async def send(message):sent.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'GET','scheme':'http','path':'/plugin-resource/hook-demo/a/b/c','query_string':b'',
        'headers':[(b'x-plugin-token',token.encode())], 'client':('127.0.0.1',123),'server':('test',80)}
    with pytest.raises(ValueError): await app(scope,receive,send)
    assert closed.is_set() and not host._remote_stream_slots
    assert not any(len(message.get('body',b''))>256*1024 for message in sent)

@pytest.mark.asyncio
async def test_stream_respects_backpressure_and_joins_on_cancel(resource_env,monkeypatch):
    host,catalog,app=resource_env; enable_stream(host); token=plugin_http_token(host,'hook-demo'); pulls=[]; sent_first,unblock,cleaned=asyncio.Event(),asyncio.Event(),asyncio.Event(); reads=0
    class Source:
        def __aiter__(self):return self
        async def __anext__(self):pulls.append(True);return b'x'
        async def aclose(self):cleaned.set()
    async def handler(name,*args,**kwargs):return OperationResult(name,{'content':Source(),'mime_type':'application/octet-stream'})
    monkeypatch.setattr(catalog,'execute',handler)
    async def receive():
        nonlocal reads
        reads+=1
        if reads==1:return {'type':'http.request','body':b'','more_body':False}
        await asyncio.Event().wait()
    async def send(message):
        if message['type']=='http.response.body' and message.get('body'):
            sent_first.set(); await unblock.wait()
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'GET','scheme':'http','path':'/plugin-resource/hook-demo/a/b/c','query_string':b'',
        'headers':[(b'x-plugin-token',token.encode())], 'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        await asyncio.wait_for(sent_first.wait(),3); await asyncio.sleep(.04); assert len(pulls)==1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert cleaned.is_set() and not host._remote_stream_slots
    finally:
        unblock.set()
        if not task.done():task.cancel()
        await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_stream_encoding_rejects_buffered_result(resource_env):
    host,_,app=resource_env; enable_stream(host); token=plugin_http_token(host,'hook-demo')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token})
    assert response.status_code==502 and not host._remote_stream_slots

@pytest.mark.asyncio
async def test_stream_total_size_limit_aborts_after_bounded_bytes(resource_env,monkeypatch):
    host,catalog,app=resource_env; enable_stream(host); token=plugin_http_token(host,'hook-demo'); closed=asyncio.Event(); sent=[]; reads=0
    class Source:
        def __aiter__(self):return self
        async def __anext__(self):return b'x'*(256*1024)
        async def aclose(self):closed.set()
    async def handler(name,*args,**kwargs):return OperationResult(name,{'content':Source(),'mime_type':'application/octet-stream'})
    monkeypatch.setattr(catalog,'execute',handler)
    async def receive():
        nonlocal reads
        reads+=1
        if reads==1:return {'type':'http.request','body':b'','more_body':False}
        await asyncio.Event().wait()
    async def send(message):sent.append(len(message.get('body',b'')))
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'GET','scheme':'http','path':'/plugin-resource/hook-demo/a/b/c','query_string':b'',
        'headers':[(b'x-plugin-token',token.encode())], 'client':('127.0.0.1',123),'server':('test',80)}
    with pytest.raises(ValueError):await app(scope,receive,send)
    assert sum(sent)==8*1024*1024 and closed.is_set() and not host._remote_stream_slots

@pytest.mark.asyncio
async def test_head_stream_cleanup_survives_repeated_cancellation(resource_env,monkeypatch):
    host,catalog,app=resource_env; enable_stream(host); token=plugin_http_token(host,'hook-demo'); cleaning,release,closed=asyncio.Event(),asyncio.Event(),asyncio.Event()
    class Source:
        def __aiter__(self):return self
        async def __anext__(self):pytest.fail('HEAD must not pull')
        async def aclose(self):cleaning.set(); await release.wait(); closed.set()
    async def handler(name,*args,**kwargs):return OperationResult(name,{'content':Source(),'mime_type':'application/octet-stream'})
    monkeypatch.setattr(catalog,'execute',handler)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.head('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token}))
        try:
            await asyncio.wait_for(cleaning.wait(),3); task.cancel(); task.cancel(); await asyncio.sleep(0)
            assert not task.done() and host._remote_stream_slots
            release.set()
            with pytest.raises(asyncio.CancelledError):await task
            assert closed.is_set() and not host._remote_stream_slots
        finally:
            release.set()
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_cancelled_handler_returning_nested_stream_is_closed(resource_env,monkeypatch):
    host,catalog,app=resource_env; enable_stream(host); token=plugin_http_token(host,'hook-demo'); entered,cleaning,release,closed=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    class Source:
        def __aiter__(self):return self
        async def __anext__(self):return b'x'
        async def aclose(self):cleaning.set(); await release.wait(); closed.set()
    async def handler(name,*args,**kwargs):
        entered.set()
        try:await asyncio.Event().wait()
        except asyncio.CancelledError:return OperationResult(name,{'content':Source(),'mime_type':'application/octet-stream'})
    monkeypatch.setattr(catalog,'execute',handler)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token}))
        try:
            await asyncio.wait_for(entered.wait(),3); task.cancel(); await asyncio.wait_for(cleaning.wait(),3); task.cancel(); await asyncio.sleep(0)
            assert not task.done() and host._remote_stream_slots
            release.set()
            with pytest.raises(asyncio.CancelledError):await task
            assert closed.is_set() and not host._remote_stream_slots
        finally:
            release.set()
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_invalid_stream_declaration_is_rejected_before_dispatch(resource_env,monkeypatch):
    host,catalog,app=resource_env; enable_stream(host); path=host.get('hook-demo').root/'plugin.json'; data=json.loads(path.read_text(encoding='utf8'))
    for row in data['http']['resources']:
        if row['kind']=='exact':row['encoding']='unknown'
    path.write_text(json.dumps(data),encoding='utf8');host._invalidate(); called=[]
    async def handler(*args,**kwargs):called.append(True);raise AssertionError('must not dispatch')
    monkeypatch.setattr(catalog,'execute',handler)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    assert response.status_code==400 and not called

def test_resource_stream_migration_describes_explicit_bounded_stream(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.webServer.registerResource(); }'})
    output=tmp_path/'ported'; report=export_port(root,output); text=(output/'PORTING.md').read_text(encoding='utf8')
    assert 'http.resources' in text and 'encoding=stream' in text and report['runtimeVerified'] is False
    assert not json.loads((output/'plugin.json').read_text(encoding='utf8')).get('http',{}).get('resources')

@pytest.mark.asyncio
async def test_buffered_resource_still_works_after_stream_support(resource_env):
    host,_,app=resource_env; token=plugin_http_token(host,'hook-demo')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=await client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token})
        head=await client.head('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token})
    assert result.status_code==200 and result.content==b'exact'
    assert head.status_code==200 and head.content==b'' and head.headers['content-length']=='5'
    assert not host._remote_stream_slots
