"""user:“完成真实接口、参数/错误、作用域、取消/清理”+(真实HTTP事件流断连与会话撤回都要结束并回收)。"""
import asyncio
import json
import pytest
from fastapi import FastAPI
from .test_plugin_working_directory import env
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from .test_plugin_remote_binary import set_encoding
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token

@pytest.mark.asyncio
@pytest.mark.parametrize('stop',['disconnect','visibility','project'])
async def test_real_scoped_stream_idle_shutdown(env,tmp_path,stop):
    ctx,store,_,_=env
    receipt=await ctx.session_controller.prompt('s',request_id='stream-http',text='hello')
    host,_,original=_host(tmp_path); configure(host); set_encoding(host,'ndjson')
    ctx._secret_store=original._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\nasync def echo(request, *, context):\n    return OperationResult(request.name,context.session_controller.follow('s',interval=.01))\n",encoding='utf8')
    catalog=OperationCatalog(); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    token=plugin_http_token(host,'hook-demo'); body=b'{"args":{"text":"s"}}'
    disconnect=asyncio.Event(); got_item=asyncio.Event(); sent=[]; delivered=False
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered=True; return {'type':'http.request','body':body,'more_body':False}
        await disconnect.wait(); return {'type':'http.disconnect'}
    async def send(msg):
        sent.append(msg)
        if msg['type']=='http.response.body' and msg.get('body') and b'"kind":"item"' in msg['body']: got_item.set()
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-remote/hook-demo/demo/echo','query_string':b'',
        'headers':[(b'content-type',b'application/json'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    task=asyncio.create_task(app(scope,receive,send))
    try:
        async with asyncio.timeout(4):
            await got_item.wait()
            if stop=='disconnect': disconnect.set()
            elif stop=='visibility': store._session_visible=lambda sid,_:sid!='s'
            else:
                other=tmp_path/'new-project'; other.mkdir()
                record,revision=await store.get_readonly_revision('s')
                await store.patch('s',metadata={**record.metadata,'work_root':str(other)},expected_revision=revision)
            await task
        assert sent[0]['status']==200 and ctx._registration_scope._idle.is_set()
        assert not host._remote_stream_slots
        if stop!='disconnect':
            last=json.loads(sent[-1]['body']); assert last=={'kind':'error','code':'gateway/stream-failed'}
    finally:
        disconnect.set()
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)
