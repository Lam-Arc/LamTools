"""user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(会话写入沿原宿主并限制当前项目)。"""
import asyncio
import pytest
from .test_plugin_working_directory import env
from lamtools_core.session import SessionRecord

@pytest.mark.asyncio
async def test_scoped_prompt_update_delete_and_cancel_preserve_native_receipts(env, tmp_path):
    ctx, store, _, _=env
    other=tmp_path/'other-write'; other.mkdir()
    await store.create(SessionRecord('foreign-write','core','Other','idle',metadata={'work_root':str(other)}))
    api=ctx.session_controller
    for sid in ('hidden','foreign-write'):
        with pytest.raises((ValueError,RuntimeError)): await api.prompt(sid,request_id='x',text='hello')
    first=await api.prompt('s',request_id='one',text='hello')
    again=await api.prompt('s',request_id='one',text='different')
    assert first.accepted and first.event_seq==again.event_seq
    assert (await api.update_queue('s',first.queue_item_id,text='changed')).applied
    assert (await api.cancel('s')).status=='idle'
    assert (await api.update_queue('s',first.queue_item_id,delete=True)).applied
    assert (await api.state('s')).queued_count==0

@pytest.mark.asyncio
async def test_scope_changed_after_native_write_reports_uncertainty(env, monkeypatch):
    ctx, store, _, _=env
    api=ctx.session_controller; original=api._sessions.call
    async def hidden_after(*args, **kwargs):
        result=await original(*args, **kwargs)
        store._session_visible=lambda sid, _:sid != 's'
        return result
    monkeypatch.setattr(api._sessions,'call',hidden_after)
    with pytest.raises(RuntimeError) as error: await api.prompt('s',request_id='r',text='hello')
    assert error.value.code=='session-controller/write-uncertain' and error.value.may_have_changed

@pytest.mark.asyncio
async def test_cancelled_caller_waits_for_dispatched_prompt_commit(env, monkeypatch):
    ctx, _, _, _=env
    api=ctx.session_controller; original=api._sessions.call
    entered=asyncio.Event(); release=asyncio.Event(); committed=asyncio.Event()
    async def gated(*args, **kwargs):
        entered.set(); await release.wait()
        try: return await original(*args, **kwargs)
        finally: committed.set()
    monkeypatch.setattr(api._sessions, 'call', gated)
    task=asyncio.create_task(api.prompt('s', request_id='cancel-r', text='hello'))
    try:
        await asyncio.wait_for(entered.wait(),3); task.cancel(); await asyncio.sleep(0); task.cancel(); await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert committed.is_set() and (await api.state('s')).queued_count == 1
    finally:
        release.set(); await asyncio.gather(task, return_exceptions=True)

@pytest.mark.asyncio
async def test_scoped_prompt_via_http_rejects_cross_project(env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, store, _, _=env
    other=tmp_path/'other-http'; other.mkdir()
    await store.create(SessionRecord('foreign','core','Other','idle',metadata={'work_root':str(other)}))
    host, _, original_ctx=_host(tmp_path); configure(host)
    ctx._secret_store=original_ctx._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\nasync def echo(request, *, context):\n    result=await context.session_controller.prompt(request.payload['body']['text'], request_id='http-r', text='hello')\n    return OperationResult(request.name, result)\n",encoding='utf8')
    catalog=OperationCatalog(); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        path='/plugin-remote/hook-demo/demo/echo'; headers={'x-plugin-token':plugin_http_token(host,'hook-demo')}
        denied=await client.post(path,json={'args':{'text':'foreign'}},headers=headers)
        assert denied.status_code!=200
        good=await client.post(path,json={'args':{'text':'s'}},headers=headers)
        assert good.status_code==200 and good.json()['payload']['accepted']
    assert (await ctx.session_controller.state('s')).queued_count==1

def test_write_migration_recommends_project_scoped_controller(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path, {'index.ts':'export function apply(ctx) { ctx.remote.session.prompt(); ctx.remote.session.updateQueue(); ctx.remote.session.cancel(); }'})
    report=export_port(root,tmp_path/'ported'); rows={r['name']:r for r in report['remotes']}
    for upstream,method in [('prompt','prompt'),('updateQueue','update_queue'),('cancel','cancel')]:
        assert rows['session.'+upstream]['suggestedContract']=='context.session_controller.'+method
        assert rows['session.'+upstream]['conversion']=='agent-required'
