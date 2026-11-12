"""user:“第二阶段结束后 就继续开展第三阶段”+(显式资源按原插件认证和归属处理真实GET/HEAD)。"""
import json
import pytest
import httpx
from fastapi import FastAPI
from .test_plugin_http_routes import _host
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token

@pytest.fixture
async def resource_env(tmp_path):
    host,catalog,_=_host(tmp_path); root=host.get('hook-demo').root; path=root/'plugin.json'; data=json.loads(path.read_text(encoding='utf8'))
    data['operations']=[{'name':f'hook-demo.{name}','handler':f'ops:{name}','permission':'auto_allow'} for name in ('exact','prefix','deep','fallback')]
    data['http']['routes']=[{'method':'POST','path':'/'+name,'operation':'hook-demo.'+name} for name in ('exact','prefix','deep','fallback')]
    data['http']['resources']=[{'kind':'prefix','path':'/a','route':'/prefix'},{'kind':'prefix','path':'/a/b','route':'/deep'},
        {'kind':'exact','path':'/a/b/c','route':'/exact'},{'kind':'fallback','route':'/fallback'}]
    path.write_text(json.dumps(data),encoding='utf8'); host._invalidate()
    (root/'ops.py').write_text(''.join(f"def {name}(request, *, context):\n    return {{'content': {name.encode()!r}, 'mime_type':'text/plain'}}\n" for name in ('exact','prefix','deep','fallback')),encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    app=FastAPI(); app.state.providers={'host':host,'catalog':catalog}; app.include_router(create_plugin_http_router(lambda:app.state.providers['host'],lambda:app.state.providers['catalog']))
    yield host,catalog,app

@pytest.mark.asyncio
async def test_resource_routing_authentication_get_and_head(resource_env):
    host,_,app=resource_env; token=plugin_http_token(host,'hook-demo'); base='/plugin-resource/hook-demo'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        headers={'x-plugin-token':token}
        bad=await client.get(base+'/a/b/c',headers={'x-plugin-token':'wrong'})
        exact=await client.get(base+'/a/b/c',headers=headers)
        deep=await client.get(base+'/a/b/d',headers=headers)
        prefix=await client.get(base+'/a/c',headers=headers)
        fallback=await client.get(base+'/abc',headers=headers)
        head=await client.head(base+'/a/b/c',headers=headers)
        post=await client.post(base+'/a/b/c',headers=headers,content=b'ignored')
    assert bad.status_code==401 and exact.content==b'exact' and deep.content==b'deep' and prefix.content==b'prefix' and fallback.content==b'fallback'
    assert head.status_code==200 and head.content==b'' and head.headers['content-length']=='5'
    assert exact.headers['content-type'].startswith('text/plain') and exact.headers['x-content-type-options']=='nosniff'
    assert post.status_code==405

@pytest.mark.asyncio
@pytest.mark.parametrize('bad',[[],[{'kind':'exact','path':'/x','route':'/hook','extra':1}],
    [{'kind':'exact','path':'/x','route':'/open'}],[{'kind':'fallback','route':'/exact'},{'kind':'fallback','route':'/exact'}],
    [{'kind':'exact','path':'/x/','route':'/exact'}]])
async def test_invalid_resource_declaration_or_no_routes_is_not_dispatched(resource_env,bad,monkeypatch):
    host,catalog,app=resource_env; token=plugin_http_token(host,'hook-demo'); path=host.get('hook-demo').root/'plugin.json'
    data=json.loads(path.read_text(encoding='utf8')); data['http']['resources']=bad; path.write_text(json.dumps(data),encoding='utf8'); host._invalidate()
    original=catalog.execute; calls=[]
    async def track(*args,**kwargs):calls.append(args);return await original(*args,**kwargs)
    monkeypatch.setattr(catalog,'execute',track)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=await client.get('/plugin-resource/hook-demo/x',headers={'x-plugin-token':token})
    assert result.status_code in (400,404) and not calls

@pytest.mark.asyncio
@pytest.mark.parametrize('content,mime',[("b'x'*(8*1024*1024+1)","'text/plain'"), ("'not bytes'","'text/plain'"), ("b'a'","'text/plain\\r\\nX-Evil: yes'"), ("b'a'","None")])
async def test_resource_invalid_results_are_rejected(resource_env,content,mime):
    host,_,app=resource_env; token=plugin_http_token(host,'hook-demo'); root=host.get('hook-demo').root
    (root/'ops.py').write_text(f"def exact(request, *, context):\n    return {{'content':{content}, 'mime_type':{mime}}}\n",encoding='utf8')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=await client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token})
    assert result.status_code==502 and len(result.content)<1000 and 'x-evil' not in result.headers

@pytest.mark.asyncio
async def test_resource_auth_headers_never_reach_handler(resource_env):
    host,_,app=resource_env; token=plugin_http_token(host,'hook-demo'); root=host.get('hook-demo').root
    (root/'ops.py').write_text("def exact(request, *, context):\n    return {'content':str(request.payload['headers']).encode(), 'mime_type':'text/plain'}\n",encoding='utf8')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=await client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token,'cookie':'private-cookie'})
    assert result.status_code==200 and token not in result.text and 'private-cookie' not in result.text

@pytest.mark.asyncio
async def test_unexpected_resource_response_stream_is_closed(resource_env):
    host,_,app=resource_env; token=plugin_http_token(host,'hook-demo'); root=host.get('hook-demo').root
    (root/'ops.py').write_text("from pathlib import Path\nfrom lamtools_core.app.operation_catalog import OperationResult\nasync def exact(request, *, context):\n    async def source():\n        try: yield b'x'\n        finally: (Path(__file__).parent/'resource-closed').touch()\n    stream=source(); await anext(stream)\n    return OperationResult(request.name,stream)\n",encoding='utf8')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=await client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token})
    assert result.status_code==502 and (root/'resource-closed').exists()

@pytest.mark.asyncio
async def test_resource_provider_revoked_during_handler_withholds_old_bytes(resource_env,monkeypatch):
    import asyncio
    host,catalog,app=resource_env; token=plugin_http_token(host,'hook-demo'); entered,release=asyncio.Event(),asyncio.Event(); original=catalog.execute
    async def gated(name,*args,**kwargs):
        result=await original(name,*args,**kwargs); entered.set(); await release.wait(); return result
    monkeypatch.setattr(catalog,'execute',gated)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token}))
        try:
            await asyncio.wait_for(entered.wait(),3); app.state.providers['catalog']=None; release.set(); result=await task
            assert result.status_code==409 and b'exact' not in result.content and result.json()['may_have_changed'] is True
        finally: release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_resource_repeated_cancel_waits_handler_cleanup(resource_env,monkeypatch):
    import asyncio
    host,catalog,app=resource_env; token=plugin_http_token(host,'hook-demo'); entered,cleaning,release,cleaned=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def gated(*args,**kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait(); cleaned.set()
    monkeypatch.setattr(catalog,'execute',gated)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token}))
        try:
            await asyncio.wait_for(entered.wait(),3); task.cancel(); await asyncio.wait_for(cleaning.wait(),3); task.cancel(); await asyncio.sleep(0)
            assert not task.done(); release.set()
            with pytest.raises(asyncio.CancelledError):await task
            assert cleaned.is_set()
        finally:release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_resource_disconnect_joins_inflight_handler_cleanup(resource_env,monkeypatch):
    import asyncio
    host,catalog,app=resource_env; token=plugin_http_token(host,'hook-demo'); entered,cleaning,release,cleaned,disconnect=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def gated(*args,**kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait(); cleaned.set()
    monkeypatch.setattr(catalog,'execute',gated); reads=0; sent=[]
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
        await asyncio.wait_for(entered.wait(),3); disconnect.set(); await asyncio.wait_for(cleaning.wait(),1)
        assert not task.done(); release.set(); await asyncio.wait_for(task,3); assert cleaned.is_set()
    finally:
        disconnect.set(); release.set()
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_resource_withdrawal_during_idle_handler_cancels_and_joins(resource_env,monkeypatch):
    import asyncio
    host,catalog,app=resource_env; token=plugin_http_token(host,'hook-demo'); entered,cleaning,release,cleaned=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def gated(*args,**kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait(); cleaned.set()
    monkeypatch.setattr(catalog,'execute',gated)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token}))
        try:
            await asyncio.wait_for(entered.wait(),3); host.backend_manager.context._secret_store.view('hook-demo').delete('httpToken')
            await asyncio.wait_for(cleaning.wait(),1); assert not task.done() and host._remote_stream_slots
            release.set(); response=await task
            assert response.status_code==409 and response.json()['may_have_changed'] is True and cleaned.is_set() and not host._remote_stream_slots
        finally:
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_resource_uses_shared_per_plugin_capacity(resource_env):
    from lamtools_core.plugin_system.remote_stream import reserve
    host,_,app=resource_env; token=plugin_http_token(host,'hook-demo'); holds=[reserve(host,'hook-demo') for _ in range(32)]
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response=await client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token})
        assert response.status_code==429
    finally:
        for release in holds:release()
    assert not host._remote_stream_slots

@pytest.mark.asyncio
async def test_resource_rejects_oversized_query_before_dispatch(resource_env,monkeypatch):
    host,catalog,app=resource_env; token=plugin_http_token(host,'hook-demo'); calls=[]; original=catalog.execute
    async def track(*args,**kwargs): calls.append(True); return await original(*args,**kwargs)
    monkeypatch.setattr(catalog,'execute',track)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=await client.get('/plugin-resource/hook-demo/a/b/c?'+'q='+'x'*8193,headers={'x-plugin-token':token})
    assert result.status_code==400 and not calls

@pytest.mark.asyncio
async def test_resource_unapproved_operation_never_executes(resource_env,monkeypatch):
    host,catalog,app=resource_env; token=plugin_http_token(host,'hook-demo'); path=host.get('hook-demo').root/'plugin.json'
    data=json.loads(path.read_text(encoding='utf8')); data['operations'][0]['permission']='ask_user'; path.write_text(json.dumps(data),encoding='utf8'); host._invalidate()
    original=catalog.execute; calls=[]
    async def track(*args,**kwargs):calls.append(True);return await original(*args,**kwargs)
    monkeypatch.setattr(catalog,'execute',track)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token})
    assert response.status_code in (403,409) and not calls

@pytest.mark.asyncio
async def test_cancelled_resource_handler_returned_stream_is_closed_before_release(resource_env,monkeypatch):
    import asyncio
    from lamtools_core.app.operation_catalog import OperationResult
    host,catalog,app=resource_env; token=plugin_http_token(host,'hook-demo'); entered,closing,release,closed=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def source():
        try:yield b'ignored'
        finally:closing.set(); await release.wait(); closed.set()
    async def handler(name,*args,**kwargs):
        stream=source(); await anext(stream); entered.set()
        try:await asyncio.Event().wait()
        except asyncio.CancelledError:return OperationResult(name,stream)
    monkeypatch.setattr(catalog,'execute',handler)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token}))
        try:
            await asyncio.wait_for(entered.wait(),3); task.cancel(); await asyncio.wait_for(closing.wait(),3); task.cancel(); await asyncio.sleep(0)
            assert not task.done() and host._remote_stream_slots
            release.set()
            with pytest.raises(asyncio.CancelledError):await task
            assert closed.is_set() and not host._remote_stream_slots
        finally:
            release.set()
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_bad_token_precedes_malformed_declaration_and_body_read(resource_env):
    host,_,app=resource_env; path=host.get('hook-demo').root/'plugin.json'; data=json.loads(path.read_text(encoding='utf8'))
    data['http']['resources']='invalid'; path.write_text(json.dumps(data),encoding='utf8'); host._invalidate()
    reads=0; sent=[]
    async def receive():
        nonlocal reads
        reads+=1; raise AssertionError('request body must not be read')
    async def send(message):sent.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'GET','scheme':'http','path':'/plugin-resource/hook-demo/a','query_string':b'',
        'headers':[(b'x-plugin-token',b'wrong')], 'client':('127.0.0.1',123),'server':('test',80)}
    await app(scope,receive,send)
    assert next(x['status'] for x in sent if x['type']=='http.response.start')==401 and reads==0

@pytest.mark.asyncio
async def test_resource_handler_gets_requested_path_and_safe_query(resource_env):
    host,_,app=resource_env; root=host.get('hook-demo').root; token=plugin_http_token(host,'hook-demo')
    (root/'ops.py').write_text("def deep(request, *, context):\n    b=request.payload['body']; q=request.payload['query']; return {'content':(b['path']+'|'+b['method']+'|'+q['k']).encode(), 'mime_type':'text/plain'}\n",encoding='utf8')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get('/plugin-resource/hook-demo/a/b/example?k=value',headers={'x-plugin-token':token})
    assert response.status_code==200 and response.content==b'/a/b/example|GET|value'

@pytest.mark.asyncio
async def test_resource_rejects_same_owner_replacement_before_dispatch(resource_env,monkeypatch):
    from lamtools_core.app.operation_catalog import OperationResult
    from lamtools_core.plugin_system import plugin_http
    host,catalog,app=resource_env; token=plugin_http_token(host,'hook-demo'); original=plugin_http.read_operations; called=[]; replaced=False
    def changed(manifest):
        nonlocal replaced
        result=original(manifest)
        if not replaced:
            replaced=True; catalog.unregister_owner('plugin:hook-demo')
            def fake(req):called.append(True);return OperationResult(req.name,{'content':b'fake','mime_type':'text/plain'})
            catalog.register('hook-demo.exact',fake,owner='plugin:hook-demo')
        return result
    monkeypatch.setattr(plugin_http,'read_operations',changed)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=await client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token})
    assert result.status_code==409 and not called and not getattr(host,'_remote_stream_slots',{})

@pytest.mark.asyncio
async def test_resource_process_runtime_is_rejected_without_starting(resource_env,monkeypatch):
    host,catalog,app=resource_env; token=plugin_http_token(host,'hook-demo'); path=host.get('hook-demo').root/'plugin.json'; data=json.loads(path.read_text(encoding='utf8'))
    data['runtime']={'kind':'process','command':['never-start-this']}; path.write_text(json.dumps(data),encoding='utf8'); host._invalidate()
    called=[]
    async def forbidden(*args,**kwargs):called.append(True);raise AssertionError('must not dispatch')
    monkeypatch.setattr(catalog,'execute',forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token})
    assert response.status_code==400 and not called

@pytest.mark.asyncio
async def test_resource_rechecks_binding_immediately_before_response_send(resource_env):
    import asyncio
    from starlette.requests import Request
    from lamtools_core.plugin_system.remote_resource import dispatch_resource
    host,catalog,app=resource_env; token=plugin_http_token(host,'hook-demo'); reads=0; sent=[]
    async def receive():
        nonlocal reads
        reads+=1
        if reads==1:return {'type':'http.request','body':b'','more_body':False}
        await asyncio.Event().wait()
    async def send(message):sent.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'GET','scheme':'http','path':'/plugin-resource/hook-demo/a/b/c','query_string':b'',
        'headers':[(b'x-plugin-token',token.encode())], 'client':('127.0.0.1',123),'server':('test',80)}
    response=await dispatch_resource(lambda:host,lambda:catalog,'hook-demo','a/b/c',Request(scope,receive))
    host.backend_manager.context._secret_store.view('hook-demo').delete('httpToken')
    await response(scope,receive,send)
    assert next(x['status'] for x in sent if x['type']=='http.response.start')==409
    assert b'exact' not in b''.join(x.get('body',b'') for x in sent)

@pytest.mark.asyncio
async def test_resource_wrong_method_does_not_read_body(resource_env):
    host,_,app=resource_env; token=plugin_http_token(host,'hook-demo'); reads=0; sent=[]
    async def receive():
        nonlocal reads
        reads+=1; raise AssertionError('wrong method must not read request body')
    async def send(message):sent.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http','path':'/plugin-resource/hook-demo/a/b/c','query_string':b'',
        'headers':[(b'x-plugin-token',token.encode())], 'client':('127.0.0.1',123),'server':('test',80)}
    await app(scope,receive,send)
    assert next(x['status'] for x in sent if x['type']=='http.response.start')==405 and reads==0

@pytest.mark.asyncio
async def test_resource_foreign_operation_owner_cannot_run(resource_env):
    from lamtools_core.app.operation_catalog import OperationResult
    host,catalog,app=resource_env; token=plugin_http_token(host,'hook-demo'); called=[]
    catalog.unregister_owner('plugin:hook-demo')
    def fake(req):called.append(True);return OperationResult(req.name,{'content':b'fake','mime_type':'text/plain'})
    catalog.register('hook-demo.exact',fake,owner='another-plugin')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=await client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token})
    assert result.status_code in (403,409) and not called

def test_migration_mentions_explicit_resource_without_automatic_mapping(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.webServer.registerResource(); }'})
    output=tmp_path/'ported'; report=export_port(root,output); handoff=(output/'PORTING.md').read_text(encoding='utf8')
    assert 'http.resources' in handoff and 'plugin-resource' in handoff
    assert not json.loads((output/'plugin.json').read_text(encoding='utf8')).get('http',{}).get('resources')
    assert report['runtimeVerified'] is False

@pytest.mark.asyncio
async def test_resource_handler_serves_real_plugin_owned_file(resource_env):
    host,_,app=resource_env; token=plugin_http_token(host,'hook-demo'); root=host.get('hook-demo').root
    (root/'fixture.bin').write_bytes(b'actual\x00resource')
    (root/'ops.py').write_text("from pathlib import Path\ndef exact(request, *, context):\n    return {'content':(Path(__file__).parent/'fixture.bin').read_bytes(), 'mime_type':'application/octet-stream'}\n",encoding='utf8')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=await client.get('/plugin-resource/hook-demo/a/b/c',headers={'x-plugin-token':token})
    assert result.status_code==200 and result.content==b'actual\x00resource'
    assert result.headers['content-security-policy']=="sandbox; default-src 'none'"

@pytest.mark.asyncio
async def test_resource_head_error_never_sends_response_body(resource_env):
    host,_,app=resource_env; sent=[]
    async def receive():raise AssertionError('authentication failure must not read body')
    async def send(message):sent.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'HEAD','scheme':'http','path':'/plugin-resource/hook-demo/a/b/c','query_string':b'',
        'headers':[(b'x-plugin-token',b'wrong')], 'client':('127.0.0.1',123),'server':('test',80)}
    await app(scope,receive,send)
    assert next(x['status'] for x in sent if x['type']=='http.response.start')==401
    assert not b''.join(x.get('body',b'') for x in sent)
