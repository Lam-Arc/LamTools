"""user:“第二阶段结束后 就继续开展第三阶段”+(工作区变化流只观察当前项目原记录)。"""
import asyncio
import pytest
from .test_plugin_workspace_registry_current import workspace_env


@pytest.mark.asyncio
async def test_follow_current_project_update_delete_and_snapshot_isolation(workspace_env):
    ctx,db,_,project,other=workspace_env
    stream=ctx.workspace_controller.follow(interval=.01)
    try:
        first=await anext(stream)
        assert first['kind']=='baseline' and first['project']['id']==project.id
        first['project']['name']='caller mutation'
        await db.project_store.rename(other.id,'Foreign changed')
        await db.project_store.rename(project.id,'Renamed')
        frame=await asyncio.wait_for(anext(stream),3)
        assert frame['kind']=='snapshot' and frame['project']['name']=='Renamed'
        assert await db.project_store.delete_with_sessions(project.id)
        assert (await asyncio.wait_for(anext(stream),3))['project'] is None
    finally:
        await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['catalog','scope','cancel'])
async def test_follow_waiting_read_is_revocable(workspace_env,monkeypatch,change):
    ctx,_,catalog,_,_=workspace_env
    stream=ctx.workspace_controller.follow(interval=.01)
    await anext(stream)
    original=catalog.execute; entered,release=asyncio.Event(),asyncio.Event()
    async def gated(name,*args,**kwargs):
        value=await original(name,*args,**kwargs)
        if name=='project.resolve': entered.set(); await release.wait()
        return value
    monkeypatch.setattr(catalog,'execute',gated)
    task=asyncio.create_task(anext(stream))
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change=='catalog': ctx.operation_catalog=type(catalog)()
        elif change=='scope': ctx._registration_scope.revoke()
        else: task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError if change=='cancel' else RuntimeError): await task
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True); await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('interval',[0,3,True,float('nan'),'bad'])
async def test_follow_rejects_invalid_interval_before_native_read(workspace_env,monkeypatch,interval):
    ctx,_,catalog,_,_=workspace_env
    async def forbidden(*args,**kwargs): pytest.fail('invalid interval accessed host')
    monkeypatch.setattr(catalog,'execute',forbidden)
    with pytest.raises(ValueError): await anext(ctx.workspace_controller.follow(interval=interval))


@pytest.mark.asyncio
async def test_follow_ndjson_disconnect_releases_capacity(workspace_env,tmp_path):
    import json
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,_,_,project,_=workspace_env
    host,catalog,old=_host(tmp_path); configure(host); set_encoding(host,'ndjson')
    ctx._secret_store=old._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\n"
        "def echo(request, *, context):\n    return OperationResult(request.name,context.workspace_controller.follow(interval=.01))\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    disconnected=asyncio.Event(); delivered=False; frames=[]
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered=True
            return {'type':'http.request','body':json.dumps({'args':{'text':'go'}}).encode(),'more_body':False}
        await disconnected.wait(); return {'type':'http.disconnect'}
    async def send(message):
        if message['type']=='http.response.body' and message.get('body'):
            frames.append(json.loads(message['body'])); disconnected.set()
    token=plugin_http_token(host,'hook-demo')
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-remote/hook-demo/demo/echo','query_string':b'',
        'headers':[(b'content-type',b'application/json'),(b'x-plugin-token',token.encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    async with asyncio.timeout(3): await app(scope,receive,send)
    assert frames[0]['payload']['kind']=='baseline' and frames[0]['payload']['project']['id']==project.id
    assert not host._remote_stream_slots


def test_follow_migration_states_approximation(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.remote.workspace.follow(); }'})
    report=export_port(root,tmp_path/'ported'); row=next(x for x in report['remotes'] if x['name']=='workspace.follow')
    assert row['suggestedContract']=='context.workspace_controller.follow' and row['conversion']=='agent-required'
