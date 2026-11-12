"""user:“第二阶段结束后 就继续开展第三阶段”+(可见会话状态流复用原宿主并在撤回时停止)。"""
import asyncio
import pytest
from .test_plugin_working_directory import env

@pytest.mark.asyncio
async def test_state_stream_initial_change_and_cleanup(env):
    ctx,_,_,_=env; api=ctx.session_controller; stream=api.observe_state('s',interval=.01)
    try:
        first=await anext(stream); assert first.session_id=='s'
        pending=asyncio.create_task(anext(stream)); await asyncio.sleep(.03); assert not pending.done()
        await api.prompt('s',request_id='state-watch',text='hello')
        changed=await asyncio.wait_for(pending,3)
        assert changed.last_event_seq>first.last_event_seq and changed.queued_count>first.queued_count
    finally: await stream.aclose()
    assert ctx._registration_scope._idle.is_set()

@pytest.mark.asyncio
async def test_idle_state_stream_withdrawal_and_cancel_release(env):
    ctx,store,_,_=env; stream=ctx.session_controller.observe_state('s',interval=.01)
    await anext(stream); pending=asyncio.create_task(anext(stream)); await asyncio.sleep(.03)
    store._session_visible=lambda sid,_:sid!='s'
    with pytest.raises(RuntimeError): await asyncio.wait_for(pending,3)
    await stream.aclose(); assert ctx._registration_scope._idle.is_set()

@pytest.mark.asyncio
@pytest.mark.parametrize('interval',[0,3,True,float('nan')])
async def test_state_stream_rejects_invalid_interval(env,interval):
    ctx,_,_,_=env; stream=ctx.session_controller.observe_state('s',interval=interval)
    with pytest.raises(ValueError): await anext(stream)
    await stream.aclose()

@pytest.mark.asyncio
async def test_state_stream_cancel_pending_pull_does_not_leave_lease(env):
    ctx,_,_,_=env; stream=ctx.session_controller.observe_state('s',interval=.01)
    await anext(stream); pending=asyncio.create_task(anext(stream)); await asyncio.sleep(.03); pending.cancel()
    with pytest.raises(asyncio.CancelledError): await pending
    await stream.aclose(); assert ctx._registration_scope._idle.is_set()

@pytest.mark.asyncio
async def test_state_stream_rejects_other_project(env,tmp_path):
    from lamtools_core.session import SessionRecord
    ctx,store,_,_=env; other=tmp_path/'other'; other.mkdir()
    await store.create(SessionRecord('foreign-state','core','Private','idle',metadata={'work_root':str(other)}))
    stream=ctx.session_controller.observe_state('foreign-state',interval=.01)
    with pytest.raises(RuntimeError): await anext(stream)
    await stream.aclose()

@pytest.mark.asyncio
async def test_state_stream_real_ndjson_and_disconnect(env,tmp_path):
    import json
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,_,_,_=env; host,_,old=_host(tmp_path); configure(host); set_encoding(host,'ndjson')
    ctx._secret_store=old._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\nasync def echo(request, *, context):\n    return OperationResult(request.name, context.session_controller.observe_state(request.payload['body']['text'],interval=.01))\n",encoding='utf8')
    catalog=OperationCatalog(); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    sent=[]; reads=0; disconnect=asyncio.Event(); first=asyncio.Event()
    async def receive():
        nonlocal reads
        reads+=1
        if reads==1:return {'type':'http.request','body':b'{"args":{"text":"s"}}','more_body':False}
        await disconnect.wait(); return {'type':'http.disconnect'}
    async def send(message):
        sent.append(message)
        if message['type']=='http.response.body' and message.get('body'): first.set()
    token=plugin_http_token(host,'hook-demo'); scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http','path':'/plugin-remote/hook-demo/demo/echo','query_string':b'',
        'headers':[(b'content-type',b'application/json'),(b'x-plugin-token',token.encode())], 'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        await asyncio.wait_for(first.wait(),3)
        frame=next(m['body'] for m in sent if m['type']=='http.response.body' and m.get('body'))
        assert json.loads(frame)['payload']['session_id']=='s'
        disconnect.set(); await asyncio.wait_for(task,3)
        assert not host._remote_stream_slots and ctx._registration_scope._idle.is_set()
    finally:
        disconnect.set()
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)

def test_observe_state_migration_names_polling_difference(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.remote.session.observeState(); }'})
    report=export_port(root,tmp_path/'ported')
    row=next(x for x in report['remotes'] if x['name']=='session.observeState')
    assert row['suggestedContract']=='context.session_controller.observe_state'
    assert '轮询' in row['difference'] and report['runtimeVerified'] is False
