"""user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(会话持久事件流限定原可见会话及项目)。"""
import asyncio
import pytest
from .test_plugin_working_directory import env

@pytest.mark.asyncio
async def test_follow_streams_original_event_and_closes_without_background_task(env):
    ctx, _, _, _=env
    api=ctx.session_controller
    receipt=await api.prompt('s',request_id='follow',text='hello')
    stream=api.follow('s',after_seq=0,interval=.01)
    try:
        async with asyncio.timeout(3):
            while True:
                event=await anext(stream)
                if event['seq']==receipt.event_seq: break
        assert event['method']=='queue/itemAccepted'
    finally: await stream.aclose()
    assert ctx._registration_scope._idle.is_set()

@pytest.mark.asyncio
async def test_follow_checks_project_before_publishing_buffered_page(env, monkeypatch, tmp_path):
    ctx, store, _, _=env
    api=ctx.session_controller
    await api.prompt('s',request_id='buffer',text='hello')
    original=api.events
    other=tmp_path/'new-root'; other.mkdir()
    async def moved(*args,**kwargs):
        page=await original(*args,**kwargs)
        record, revision=await store.get_readonly_revision('s')
        await store.patch('s',metadata={**record.metadata,'work_root':str(other)},expected_revision=revision)
        return page
    monkeypatch.setattr(api,'events',moved)
    stream=api.follow('s',interval=.01)
    try:
        with pytest.raises(RuntimeError): await anext(stream)
    finally: await stream.aclose()

@pytest.mark.asyncio
async def test_follow_idle_rechecks_visibility_and_cancel_releases(env):
    ctx, store, _, _=env
    api=ctx.session_controller; cursor=(await api.state('s')).last_event_seq
    stream=api.follow('s',after_seq=cursor,interval=.01)
    pending=asyncio.create_task(anext(stream))
    try:
        await asyncio.sleep(.05); assert not pending.done()
        store._session_visible=lambda sid, _:sid!='s'
        with pytest.raises(RuntimeError): await asyncio.wait_for(pending,3)
    finally:
        if not pending.done(): pending.cancel()
        await asyncio.gather(pending,return_exceptions=True); await stream.aclose()
    assert ctx._registration_scope._idle.is_set()

@pytest.mark.asyncio
@pytest.mark.parametrize('interval',[0,3,float('nan'),True])
async def test_follow_rejects_invalid_interval(env,interval):
    ctx, _, _, _=env
    stream=ctx.session_controller.follow('s',interval=interval)
    with pytest.raises(ValueError): await anext(stream)
    await stream.aclose()

@pytest.mark.asyncio
async def test_scoped_follow_crosses_explicit_ndjson_http(env,tmp_path):
    import httpx,json
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,_,_,_=env
    await ctx.session_controller.prompt('s',request_id='http-follow',text='hello')
    host,_,original_ctx=_host(tmp_path); configure(host); set_encoding(host,'ndjson')
    ctx._secret_store=original_ctx._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\nasync def echo(request, *, context):\n    async def one():\n        stream=context.session_controller.follow(request.payload['body']['text'],interval=.01)\n        try:\n            yield await anext(stream)\n        finally:\n            await stream.aclose()\n    return OperationResult(request.name,one())\n",encoding='utf8')
    catalog=OperationCatalog(); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'s'}},headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    frames=[json.loads(line) for line in response.iter_lines()]
    assert response.status_code==200 and frames[0]['kind']=='item' and 'seq' in frames[0]['payload']
    assert frames[-1]=={'kind':'end'} and ctx._registration_scope._idle.is_set()

@pytest.mark.asyncio
async def test_follow_cancel_pending_pull_releases_scope(env):
    ctx,_,_,_=env
    api=ctx.session_controller; cursor=(await api.state('s')).last_event_seq
    stream=api.follow('s',after_seq=cursor,interval=.01)
    pending=asyncio.create_task(anext(stream))
    await asyncio.sleep(.05); pending.cancel()
    with pytest.raises(asyncio.CancelledError): await pending
    await stream.aclose()
    assert ctx._registration_scope._idle.is_set()

def test_follow_migration_suggests_scoped_stream(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.remote.session.follow(); }'})
    report=export_port(root,tmp_path/'ported')
    row=next(r for r in report['remotes'] if r['name']=='session.follow')
    assert row['suggestedContract']=='context.session_controller.follow' and row['conversion']=='agent-required'
