"""user:“第二阶段结束后 就继续开展第三阶段”+(终端输出流复用原管道并按会话范围读取)。"""
import asyncio
import base64
import os
import sys
import pytest
from .test_plugin_working_directory import env


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
async def test_follow_reports_output_without_consuming_or_closing_terminal(env):
    ctx,_,_,_=env; api=ctx.terminal_controller
    tid=(await api.create_pipe('s',[sys.executable,'-u','-c',"print('hello',flush=True); input()"],timeout=10))['id']
    stream=api.follow_pipe('s',tid,interval=.01)
    try:
        assert (await anext(stream))['kind']=='opened'
        frame=await asyncio.wait_for(anext(stream),3)
        assert frame['kind']=='output' and b'hello' in base64.b64decode(frame['stdout_base64'])
        await stream.aclose()
        assert b'hello' in base64.b64decode((await api.read_pipe('s',tid))['stdout_base64'])
        assert not ctx._registration_scope._session_terminal_pipes[tid][1]._process._task.done()
    finally:
        await stream.aclose(); await api.close_pipe('s',tid)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
@pytest.mark.parametrize('change',['hidden','cancel','close'])
async def test_follow_empty_wait_rechecks_scope_and_cleans(env,change):
    ctx,store,_,_=env; api=ctx.terminal_controller
    tid=(await api.create_pipe('s',[sys.executable,'-u','-c','import time;time.sleep(20)'],timeout=25))['id']
    stream=api.follow_pipe('s',tid,interval=.01); await anext(stream)
    task=asyncio.create_task(anext(stream))
    try:
        await asyncio.sleep(.04); assert not task.done()
        if change=='hidden': store._session_visible=lambda *_:False
        elif change=='close': await api.close_pipe('s',tid)
        else: task.cancel()
        with pytest.raises(asyncio.CancelledError if change=='cancel' else RuntimeError): await asyncio.wait_for(task,3)
    finally:
        await asyncio.gather(task,return_exceptions=True); await stream.aclose()
        if tid in ctx._registration_scope._session_terminal_pipes: await api.close_pipe('s',tid)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
async def test_buffered_output_is_not_published_after_opened_revocation(env):
    ctx,store,_,_=env; api=ctx.terminal_controller
    tid=(await api.create_pipe('s',[sys.executable,'-u','-c',"print('private',flush=True); input()"],timeout=10))['id']
    stream=api.follow_pipe('s',tid,interval=.01)
    try:
        for _ in range(100):
            if base64.b64decode((await api.read_pipe('s',tid))['stdout_base64']): break
            await asyncio.sleep(.02)
        assert (await anext(stream))['kind']=='opened'
        store._session_visible=lambda *_:False
        with pytest.raises(RuntimeError): await anext(stream)
    finally:
        await stream.aclose(); await api.close_pipe('s',tid)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
async def test_completed_process_emits_output_then_end(env):
    ctx,_,_,_=env; api=ctx.terminal_controller
    tid=(await api.create_pipe('s',[sys.executable,'-u','-c',"print('done')"],timeout=10))['id']
    stream=api.follow_pipe('s',tid,interval=.01)
    try:
        frames=[]
        async with asyncio.timeout(3):
            async for frame in stream: frames.append(frame)
        assert frames[0]['kind']=='opened' and frames[-1]['kind']=='end'
        assert b'done' in b''.join(base64.b64decode(f['stdout_base64']) for f in frames if f['kind']=='output')
    finally:
        await stream.aclose(); await api.close_pipe('s',tid)


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
async def test_follow_reports_lost_prefix_and_resume_offset(env):
    ctx,_,_,_=env; api=ctx.terminal_controller
    tid=(await api.create_pipe('s',[sys.executable,'-u','-c',"print('x'*2000)"],timeout=10,max_output_bytes=128))['id']
    terminal=ctx._registration_scope._session_terminal_pipes[tid][1]
    await asyncio.wait_for(asyncio.shield(terminal._process._task),3)
    stream=api.follow_pipe('s',tid,interval=.01)
    try:
        assert (await anext(stream))['kind']=='opened'
        frame=await anext(stream)
        assert frame['kind']=='output' and frame['stdout_lost'] and len(base64.b64decode(frame['stdout_base64']))==128
        end=await anext(stream)
        assert end['kind']=='end' and end['stdout_after']==frame['stdout_after']
    finally:
        await stream.aclose(); await api.close_pipe('s',tid)


@pytest.mark.asyncio
@pytest.mark.parametrize('interval',[0,3,True,float('nan'),'bad'])
async def test_invalid_interval_rejected_before_session_read(env,monkeypatch,interval):
    ctx,_,_,_=env; api=ctx.terminal_controller
    async def forbidden(*args,**kwargs): pytest.fail('invalid interval accessed session')
    monkeypatch.setattr(api,'read_pipe',forbidden)
    with pytest.raises(RuntimeError): await anext(api.follow_pipe('s','unknown',interval=interval))


@pytest.mark.asyncio
@pytest.mark.skipif(os.name!='nt',reason='original managed process is Windows-only')
async def test_ndjson_disconnect_releases_stream_without_stopping_process(env,tmp_path):
    import json
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,_,_,_=env; api=ctx.terminal_controller
    tid=(await api.create_pipe('s',[sys.executable,'-u','-c',"print('hello',flush=True); input()"],timeout=10))['id']
    terminal=ctx._registration_scope._session_terminal_pipes[tid][1]
    host,catalog,old=_host(tmp_path); configure(host); set_encoding(host,'ndjson')
    ctx._secret_store=old._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        'from lamtools_core.app.operation_catalog import OperationResult\n'
        "def echo(request, *, context):\n    return OperationResult(request.name,context.terminal_controller.follow_pipe('s',request.payload['body']['text'],interval=.01))\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    disconnected=asyncio.Event(); delivered=False; frames=[]
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered=True
            return {'type':'http.request','body':json.dumps({'args':{'text':tid}}).encode(),'more_body':False}
        await disconnected.wait(); return {'type':'http.disconnect'}
    async def send(message):
        if message['type']=='http.response.body' and message.get('body'):
            frames.append(json.loads(message['body'])); disconnected.set()
    token=plugin_http_token(host,'hook-demo')
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-remote/hook-demo/demo/echo','query_string':b'',
        'headers':[(b'content-type',b'application/json'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    try:
        async with asyncio.timeout(3): await app(scope,receive,send)
        assert frames[0]['payload']['kind']=='opened' and not host._remote_stream_slots
        assert not terminal._process._task.done()
    finally:
        await api.close_pipe('s',tid)


def test_terminal_follow_migration_is_explicitly_not_duplex(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.remote.terminal.attach(); }'})
    report=export_port(root,tmp_path/'ported'); row=next(x for x in report['remotes'] if x['name']=='terminal.attach')
    assert row['suggestedContract']=='context.terminal_controller.send_pipe/follow_pipe' and report['runtimeVerified'] is False
