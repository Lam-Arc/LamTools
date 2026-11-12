"""user:“继续”+(明确声明的附件入口先认证，再以有界流复用原附件持久化)。"""
import asyncio
import json
from pathlib import Path
import pytest
from fastapi import FastAPI
from .test_plugin_working_directory import env
from .test_plugin_http_routes import _host
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token


@pytest.fixture
async def upload_env(env,tmp_path):
    ctx,_,_,_=env; host,catalog,old=_host(tmp_path)
    ctx._secret_store=old._secret_store; host.backend_manager.context=ctx
    path=host.get('hook-demo').root/'plugin.json'; data=json.loads(path.read_text(encoding='utf8'))
    data['http']['uploads']=[{'name':'files','route':'/hook'}]
    path.write_text(json.dumps(data),encoding='utf8'); host._invalidate()
    (path.parent/'ops.py').write_text(
        "async def echo(request, *, context):\n"
        "    body=request.payload['body']\n"
        "    saved=await context.file_uploads.save_chunks('s',filename='stream.bin',source=body['stream'],size=body['size'])\n"
        "    return {'id':saved['id']}\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    app=FastAPI(); app.state.providers={'host':host,'catalog':catalog}
    app.include_router(create_plugin_http_router(lambda:app.state.providers['host'],lambda:app.state.providers['catalog']))
    return ctx,host,app


async def request(app,token,size,messages,name='files',extra_headers=(),content_type=b'application/octet-stream'):
    read=0; sent=[]
    async def receive():
        nonlocal read
        read+=1
        if messages: return messages.pop(0)
        await asyncio.Event().wait()
    async def send(value): sent.append(value)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-upload/hook-demo/'+name,'query_string':b'',
        'headers':[(b'content-type',content_type),(b'x-upload-size',str(size).encode()),(b'x-plugin-token',token.encode()),*extra_headers],
        'client':('127.0.0.1',123),'server':('test',80)}
    async with asyncio.timeout(6): await app(scope,receive,send)
    status=next(x['status'] for x in sent if x['type']=='http.response.start')
    payload=json.loads(b''.join(x.get('body',b'') for x in sent if x['type']=='http.response.body'))
    return status,payload,read


@pytest.mark.asyncio
async def test_large_fragmented_upload_persists_real_file(upload_env):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo'); chunks=[b'a'*300000,b'b'*300000,b'c'*300000,b'd'*300000]
    messages=[{'type':'http.request','body':chunk,'more_body':True} for chunk in chunks]+[{'type':'http.request','body':b'','more_body':False}]
    status,payload,read=await request(app,token,1200000,messages)
    assert status==200 and read>=5
    saved=await ctx.attachments.get('s',payload['payload']['id'])
    assert Path(saved['path']).read_bytes()==b''.join(chunks)
    assert not getattr(host,'_remote_stream_slots',{})


@pytest.mark.asyncio
async def test_handler_never_receives_authentication_headers(upload_env):
    _,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    (host.get('hook-demo').root/'ops.py').write_text(
        "async def echo(request, *, context):\n"
        "    async for _ in request.payload['body']['stream']: pass\n"
        "    return {'headers':request.payload['headers']}\n",encoding='utf8')
    status,payload,_=await request(app,token,1,[{'type':'http.request','body':b'a','more_body':False}],extra_headers=[(b'cookie',b'test-cookie')])
    assert status==200 and 'x-plugin-token' not in payload['payload']['headers']
    assert 'cookie' not in payload['payload']['headers'] and token not in str(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize('value',["b'\\xff'", "'x'*(1024*1024+1)"])
async def test_unserializable_or_oversized_handler_result_is_bounded(upload_env,value):
    _,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    (host.get('hook-demo').root/'ops.py').write_text(
        "async def echo(request, *, context):\n"
        "    async for _ in request.payload['body']['stream']: pass\n"
        f"    return {{'value':{value}}}\n",encoding='utf8')
    status,payload,_=await request(app,token,1,[{'type':'http.request','body':b'a','more_body':False}])
    assert status==502 and payload['error']['code']=='gateway/invalid-result' and len(str(payload))<1000
    assert not host._remote_stream_slots


@pytest.mark.asyncio
async def test_unexpected_async_result_is_closed(upload_env):
    _,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    root=host.get('hook-demo').root
    (root/'ops.py').write_text(
        'from pathlib import Path\n'
        'from lamtools_core.app.operation_catalog import OperationResult\n'
        'async def echo(request, *, context):\n'
        "    async for _ in request.payload['body']['stream']: pass\n"
        '    async def source():\n'
        "        try: yield 'first'\n"
        "        finally: (Path(__file__).parent/'closed.txt').write_text('closed')\n"
        '    stream=source(); await anext(stream)\n'
        '    return OperationResult(request.name,stream)\n',encoding='utf8')
    status,_,_=await request(app,token,1,[{'type':'http.request','body':b'a','more_body':False}])
    assert status==502 and (root/'closed.txt').read_text()=='closed' and not host._remote_stream_slots


@pytest.mark.asyncio
@pytest.mark.parametrize('token_kind,name,expected',[('bad','files',401),('good','missing',404)])
async def test_auth_and_declaration_precede_body_read(upload_env,token_kind,name,expected):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo') if token_kind=='good' else 'wrong'
    status,_,read=await request(app,token,1,[],name=name)
    assert status==expected and read==0 and not (await ctx.attachments.list('s'))['items']


@pytest.mark.asyncio
async def test_disconnected_input_saves_nothing_and_releases_capacity(upload_env):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    messages=[{'type':'http.request','body':b'a','more_body':True},{'type':'http.disconnect'}]
    status,_,read=await request(app,token,2,messages)
    assert status>=400 and read>=2 and not (await ctx.attachments.list('s'))['items']
    assert not getattr(host,'_remote_stream_slots',{})


@pytest.mark.asyncio
@pytest.mark.parametrize('declared,chunks',[(2,[b'a']), (1,[b'ab'])])
async def test_size_mismatch_never_saves_partial_data(upload_env,declared,chunks):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    messages=[{'type':'http.request','body':chunk,'more_body':True} for chunk in chunks]+[{'type':'http.request','body':b'','more_body':False}]
    status,_,read=await request(app,token,declared,messages)
    assert status>=400 and read>=1 and not (await ctx.attachments.list('s'))['items']
    assert not getattr(host,'_remote_stream_slots',{})


@pytest.mark.asyncio
async def test_oversized_declaration_rejected_before_body_read(upload_env):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    status,_,read=await request(app,token,8*1024*1024+1,[])
    assert status==413 and read==0 and not (await ctx.attachments.list('s'))['items']


@pytest.mark.asyncio
async def test_conflicting_content_length_rejected_before_body_read(upload_env):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    status,_,read=await request(app,token,2,[],extra_headers=[(b'content-length',b'1')])
    assert status==400 and read==0 and not (await ctx.attachments.list('s'))['items']


@pytest.mark.asyncio
@pytest.mark.parametrize('size',['-1','nan','123456789'])
async def test_invalid_size_rejected_without_read(upload_env,size):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    status,_,read=await request(app,token,size,[])
    assert status==400 and read==0 and not (await ctx.attachments.list('s'))['items']


@pytest.mark.asyncio
async def test_wrong_media_type_rejected_without_read(upload_env):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    status,_,read=await request(app,token,1,[],content_type=b'text/plain')
    assert status==415 and read==0 and not (await ctx.attachments.list('s'))['items']


@pytest.mark.asyncio
async def test_empty_upload_is_valid(upload_env):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    status,payload,read=await request(app,token,0,[{'type':'http.request','body':b'','more_body':False}])
    assert status==200 and read==1
    assert Path((await ctx.attachments.get('s',payload['payload']['id']))['path']).read_bytes()==b''


@pytest.mark.asyncio
async def test_capacity_limit_rejected_before_body_read(upload_env):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    host._remote_stream_slots={'hook-demo':32}
    try:
        status,_,read=await request(app,token,1,[])
        assert status==429 and read==0 and not (await ctx.attachments.list('s'))['items']
    finally:
        host._remote_stream_slots.clear()


@pytest.mark.asyncio
async def test_upload_waits_for_final_chunk_before_persisting(upload_env):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    entered,release=asyncio.Event(),asyncio.Event(); count=0; sent=[]
    async def receive():
        nonlocal count
        count+=1
        if count==1: return {'type':'http.request','body':b'a','more_body':True}
        entered.set(); await release.wait()
        return {'type':'http.request','body':b'b','more_body':False}
    async def send(value): sent.append(value)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-upload/hook-demo/files','query_string':b'',
        'headers':[(b'content-type',b'application/octet-stream'),(b'x-upload-size',b'2'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        await asyncio.wait_for(entered.wait(),3)
        assert not task.done() and not (await ctx.attachments.list('s'))['items']
        release.set(); await asyncio.wait_for(task,3)
        assert next(x['status'] for x in sent if x['type']=='http.response.start')==200
        assert len((await ctx.attachments.list('s'))['items'])==1 and not host._remote_stream_slots
    finally:
        release.set()
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('entries', [None, [{'name':'files','route':'/hook'},{'name':'files','route':'/hook'}],
    [{'name':'files','route':'/open'}], [{'name':'files','route':'/hook','extra':True}]])
async def test_invalid_upload_declaration_rejected_without_read(upload_env,entries):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    path=host.get('hook-demo').root/'plugin.json'; data=json.loads(path.read_text(encoding='utf8'))
    data['http']['uploads']=entries; path.write_text(json.dumps(data),encoding='utf8'); host._invalidate()
    status,_,read=await request(app,token,1,[])
    assert status==400 and read==0 and not (await ctx.attachments.list('s'))['items']


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['owner','approval','process'])
async def test_unowned_unapproved_or_process_operation_rejected_before_body_read(upload_env,change):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    if change=='owner':
        catalog=next(iter(host.operation_catalogs))
        catalog.unregister_owner('plugin:hook-demo')
        catalog.register('hook-demo.echo',lambda *_:None,owner='foreign')
    else:
        path=host.get('hook-demo').root/'plugin.json'; data=json.loads(path.read_text(encoding='utf8'))
        if change=='approval': data['operations'][0]['permission']='ask_user'
        else: data['runtime']={'kind':'process','command':['python','unused.py']}
        path.write_text(json.dumps(data),encoding='utf8'); host._invalidate()
    status,_,read=await request(app,token,1,[])
    assert status>=400 and read==0 and not (await ctx.attachments.list('s'))['items']


@pytest.mark.asyncio
async def test_handler_cannot_report_success_without_consuming_stream(upload_env):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    (host.get('hook-demo').root/'ops.py').write_text(
        "async def echo(request, *, context):\n    return {'accepted':True}\n",encoding='utf8')
    status,payload,read=await request(app,token,1,[{'type':'http.request','body':b'a','more_body':False}])
    assert status==400 and payload['may_have_changed'] is True and read==0
    assert not (await ctx.attachments.list('s'))['items'] and not getattr(host,'_remote_stream_slots',{})


@pytest.mark.asyncio
async def test_partial_consumption_cannot_report_success(upload_env):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    (host.get('hook-demo').root/'ops.py').write_text(
        "async def echo(request, *, context):\n    await anext(request.payload['body']['stream'])\n    return {'accepted':True}\n",encoding='utf8')
    status,payload,read=await request(app,token,2,[{'type':'http.request','body':b'a','more_body':True}])
    assert status==400 and payload['may_have_changed'] is True and read==1
    assert not (await ctx.attachments.list('s'))['items'] and not getattr(host,'_remote_stream_slots',{})


@pytest.mark.asyncio
async def test_manifest_removed_after_auth_is_rejected_without_body(upload_env,monkeypatch):
    from lamtools_core.plugin_system import remote_upload
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    original_auth=remote_upload.authenticate_remote; original_get=host.get; completed=False
    def authenticate(*args,**kwargs):
        nonlocal completed
        result=original_auth(*args,**kwargs); completed=True; return result
    def get(name): return None if completed else original_get(name)
    monkeypatch.setattr(remote_upload,'authenticate_remote',authenticate)
    monkeypatch.setattr(host,'get',get)
    status,_,read=await request(app,token,1,[])
    assert status in {404,409} and read==0 and not (await ctx.attachments.list('s'))['items']


@pytest.mark.asyncio
async def test_binding_snapshot_failure_is_closed_without_body(upload_env,monkeypatch):
    from lamtools_core.plugin_system import remote_upload
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    def failed(*args,**kwargs): raise OSError('internal detail')
    monkeypatch.setattr(remote_upload,'binding_check',failed)
    status,payload,read=await request(app,token,1,[])
    assert status==409 and read==0 and 'internal detail' not in str(payload)
    assert not (await ctx.attachments.list('s'))['items']


@pytest.mark.asyncio
async def test_token_revoked_after_save_reports_possible_commit(upload_env,monkeypatch):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    native=ctx.require_service('session_data'); original=native.call
    entered,release=asyncio.Event(),asyncio.Event()
    async def gated(*args,**kwargs):
        result=await original(*args,**kwargs)
        if args[3]=='create': entered.set(); await release.wait()
        return result
    monkeypatch.setattr(native,'call',gated)
    task=asyncio.create_task(request(app,token,1,[{'type':'http.request','body':b'a','more_body':False}]))
    try:
        await asyncio.wait_for(entered.wait(),3)
        ctx._secret_store.view('hook-demo').delete('httpToken'); release.set()
        status,payload,_=await task
        assert status==409 and payload['may_have_changed'] is True
        assert len((await ctx.attachments.list('s'))['items'])==1
        assert not getattr(host,'_remote_stream_slots',{})
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['token','declaration','host','catalog'])
async def test_idle_upload_revocation_cancels_receive_and_releases_capacity(upload_env,change):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    entered,cancelled=asyncio.Event(),asyncio.Event(); received=0; sent=[]
    async def receive():
        nonlocal received
        received+=1
        if received==1: return {'type':'http.request','body':b'a','more_body':True}
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
        await asyncio.wait_for(entered.wait(),3)
        if change=='token':
            ctx._secret_store.view('hook-demo').delete('httpToken')
        elif change=='declaration':
            path=host.get('hook-demo').root/'plugin.json'
            data=json.loads(path.read_text(encoding='utf8')); data['http']['uploads']=[]
            path.write_text(json.dumps(data),encoding='utf8'); host._invalidate()
        else:
            app.state.providers[change]=None
        await asyncio.wait_for(task,4)
        assert cancelled.is_set() and next(x['status'] for x in sent if x['type']=='http.response.start')==409
        assert not getattr(host,'_remote_stream_slots',{}) and not (await ctx.attachments.list('s'))['items']
        if change=='token': assert not ctx._secret_store.view('hook-demo').get('httpToken')
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_external_operation_permission_withdrawal_stops_idle_upload(upload_env):
    ctx,host,app=upload_env
    path=host.get('hook-demo').root/'plugin.json'; spec=path.parent/'operations.json'
    data=json.loads(path.read_text(encoding='utf8')); spec.write_text(json.dumps({'operations':data['operations']}),encoding='utf8')
    data['operations']=['./operations.json']; path.write_text(json.dumps(data),encoding='utf8'); host._invalidate()
    catalog=app.state.providers['catalog']; catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    token=plugin_http_token(host,'hook-demo'); entered,cancelled=asyncio.Event(),asyncio.Event(); received=0; sent=[]
    async def receive():
        nonlocal received
        received+=1
        if received==1: return {'type':'http.request','body':b'a','more_body':True}
        entered.set()
        try: await asyncio.Event().wait()
        finally: cancelled.set()
    async def send(value): sent.append(value)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-upload/hook-demo/files','query_string':b'',
        'headers':[(b'content-type',b'application/octet-stream'),(b'x-upload-size',b'2'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        await asyncio.wait_for(entered.wait(),3)
        changed=json.loads(spec.read_text(encoding='utf8')); changed['operations'][0]['permission']='hard_block'
        spec.write_text(json.dumps(changed),encoding='utf8')
        await asyncio.wait_for(task,4)
        assert cancelled.is_set() and next(x['status'] for x in sent if x['type']=='http.response.start')==409
        assert not host._remote_stream_slots and not (await ctx.attachments.list('s'))['items']
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_caller_cancellation_joins_inflight_receive_without_saving(upload_env):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    entered,cancelled=asyncio.Event(),asyncio.Event(); received=0
    async def receive():
        nonlocal received
        received+=1
        if received==1: return {'type':'http.request','body':b'a','more_body':True}
        entered.set()
        try: await asyncio.Event().wait()
        finally: cancelled.set()
    async def send(_): pass
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-upload/hook-demo/files','query_string':b'',
        'headers':[(b'content-type',b'application/octet-stream'),(b'x-upload-size',b'2'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        await asyncio.wait_for(entered.wait(),3)
        task.cancel(); await asyncio.sleep(0); task.cancel()
        with pytest.raises(asyncio.CancelledError): await asyncio.wait_for(task,4)
        assert cancelled.is_set() and not getattr(host,'_remote_stream_slots',{})
        assert not (await ctx.attachments.list('s'))['items']
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_repeated_cancel_waits_for_receive_cleanup_before_releasing_capacity(upload_env):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    entered,closing,release=asyncio.Event(),asyncio.Event(),asyncio.Event(); received=0
    async def receive():
        nonlocal received
        received+=1
        if received==1: return {'type':'http.request','body':b'a','more_body':True}
        entered.set()
        try: await asyncio.Event().wait()
        finally:
            closing.set(); await release.wait()
    async def send(_): pass
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-upload/hook-demo/files','query_string':b'',
        'headers':[(b'content-type',b'application/octet-stream'),(b'x-upload-size',b'2'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        await asyncio.wait_for(entered.wait(),3)
        task.cancel(); await asyncio.wait_for(closing.wait(),3)
        task.cancel(); await asyncio.sleep(.02)
        assert not task.done() and host._remote_stream_slots
        release.set()
        with pytest.raises(asyncio.CancelledError): await asyncio.wait_for(task,4)
        assert not host._remote_stream_slots and not (await ctx.attachments.list('s'))['items']
    finally:
        release.set()
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['session','scope'])
async def test_idle_upload_stops_when_original_session_or_plugin_scope_is_revoked(upload_env,change):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    store=ctx.require_service('session_data')._store; original_visible=store._session_visible
    entered,cancelled=asyncio.Event(),asyncio.Event(); received=0; sent=[]
    async def receive():
        nonlocal received
        received+=1
        if received==1: return {'type':'http.request','body':b'a','more_body':True}
        entered.set()
        try: await asyncio.Event().wait()
        finally: cancelled.set()
    async def send(value): sent.append(value)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-upload/hook-demo/files','query_string':b'',
        'headers':[(b'content-type',b'application/octet-stream'),(b'x-upload-size',b'2'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change=='session': store._session_visible=lambda *_:False
        else: ctx._registration_scope.revoke()
        await asyncio.wait_for(task,4)
        assert cancelled.is_set() and next(x['status'] for x in sent if x['type']=='http.response.start')>=400
        assert not getattr(host,'_remote_stream_slots',{})
        if change=='session':
            store._session_visible=original_visible
            assert not (await ctx.attachments.list('s'))['items']
    finally:
        store._session_visible=original_visible
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_concurrent_source_close_keeps_capacity_until_receive_cleanup(upload_env):
    ctx,host,app=upload_env; token=plugin_http_token(host,'hook-demo')
    (host.get('hook-demo').root/'ops.py').write_text(
        'import asyncio\n'
        'async def echo(request, *, context):\n'
        "    source=request.payload['body']['stream']\n"
        '    asyncio.create_task(anext(source)); await asyncio.sleep(.05)\n'
        '    asyncio.create_task(source.aclose()); await asyncio.sleep(.05)\n'
        "    return {'accepted':True}\n",encoding='utf8')
    entered,closing,release=asyncio.Event(),asyncio.Event(),asyncio.Event(); sent=[]
    async def receive():
        entered.set()
        try: await asyncio.Event().wait()
        finally:
            closing.set()
            await release.wait()
    async def send(message): sent.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-upload/hook-demo/files','query_string':b'',
        'headers':[(b'content-type',b'application/octet-stream'),(b'x-upload-size',b'1'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        await asyncio.wait_for(entered.wait(),3); await asyncio.wait_for(closing.wait(),3)
        await asyncio.sleep(.15)
        assert not task.done() and host._remote_stream_slots
        release.set(); await asyncio.wait_for(task,3)
        assert not host._remote_stream_slots and not (await ctx.attachments.list('s'))['items']
    finally:
        release.set()
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)


def test_upload_migration_documents_explicit_raw_route_without_auto_mapping(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.fileUploads.upload(); }'})
    output=tmp_path/'ported'; report=export_port(root,output)
    handoff=(output/'PORTING.md').read_text(encoding='utf8')
    assert 'http.uploads' in handoff and 'x-upload-size' in handoff
    assert not json.loads((output/'plugin.json').read_text(encoding='utf8')).get('http',{}).get('uploads')
    assert report['runtimeVerified'] is False


@pytest.mark.asyncio
async def test_existing_buffered_http_and_remote_routes_remain_available(tmp_path):
    import httpx
    from .test_plugin_remote_gateway import configure
    host,catalog,_=_host(tmp_path); configure(host); token=plugin_http_token(host,'hook-demo')
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        headers={'x-plugin-token':token}
        ordinary=await client.post('/plugin-http/hook-demo/hook',json={'hello':'world'},headers=headers)
        remote=await client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'hello'}},headers=headers)
    assert ordinary.status_code==200 and ordinary.json()['payload']['echo']=={'hello':'world'}
    assert remote.status_code==200 and remote.json()['payload']['echo']=={'text':'hello'}
