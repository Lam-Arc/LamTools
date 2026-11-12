"""user:“第二阶段结束后 就继续开展第三阶段”+(当前项目内容检索复用原可见会话及历史)。"""
import asyncio
import pytest
from .test_plugin_workspace_registry_current import workspace_env
from .test_plugin_workspace_sessions import populated
from .test_core_checkpoint_graph import _runtime

@pytest.mark.asyncio
async def test_search_page_uses_visible_project_history_and_scan_cursor(populated):
    ctx,db,_,first,other,_=populated
    ctx.require_service('session_query')._sessions._context().host.runtime_state_store=db.runtime_state_store
    for sid,text in [('a','first needle'),('b','second NEEDLE'),('hidden','hidden needle'),('private','private needle')]:
        await _runtime(db,sid,history=[{'role':'user','content':text}])
    first_page=await ctx.session_controller.search_project(first.id,'needle',scan_limit=1)
    rows=list(first_page['items']); page=first_page
    while page['has_more']:
        page=await ctx.session_controller.search_project(first.id,'needle',scan_limit=1,cursor=page['next_cursor'])
        rows.extend(page['items'])
    assert {x['session_id'] for x in rows}=={'a','b'}
    assert all('private' not in str(x) and 'hidden' not in str(x) for x in rows)
    with pytest.raises(RuntimeError): await ctx.session_controller.search_project(other.id,'needle')

@pytest.mark.asyncio
async def test_search_rejects_stale_results_and_propagates_cancel(populated,monkeypatch):
    ctx,db,_,first,_,store=populated
    ctx.require_service('session_query')._sessions._context().host.runtime_state_store=db.runtime_state_store
    await _runtime(db,'a',history=[{'role':'user','content':'needle'}])
    original=db.runtime_state_store.read_history_page; entered=asyncio.Event(); release=asyncio.Event()
    async def gated(*args,**kwargs):
        value=await original(*args,**kwargs); entered.set(); await release.wait(); return value
    monkeypatch.setattr(db.runtime_state_store,'read_history_page',gated)
    task=asyncio.create_task(ctx.session_controller.search_project(first.id,'needle'))
    try:
        await asyncio.wait_for(entered.wait(),3); store._session_visible=lambda sid,_: sid not in {'a','hidden'}; release.set()
        with pytest.raises(RuntimeError): await task
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
@pytest.mark.parametrize('change',['cancel','provider'])
async def test_search_wait_cancellation_and_provider_replacement(populated,monkeypatch,change):
    ctx,db,_,first,_,_=populated
    host=ctx.require_service('session_query')._sessions._context().host; host.runtime_state_store=db.runtime_state_store
    await _runtime(db,'a',history=[{'role':'user','content':'needle'}])
    original=db.runtime_state_store.read_history_page; entered=asyncio.Event(); release=asyncio.Event()
    async def gated(*args,**kwargs):
        result=await original(*args,**kwargs); entered.set(); await release.wait(); return result
    monkeypatch.setattr(db.runtime_state_store,'read_history_page',gated)
    task=asyncio.create_task(ctx.session_controller.search_project(first.id,'needle'))
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change=='cancel': task.cancel()
        else: host.runtime_state_store=object()
        release.set()
        with pytest.raises(asyncio.CancelledError if change=='cancel' else RuntimeError): await task
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
@pytest.mark.parametrize('query,limit',[('',10),('\ud800',10),('ok',0),('ok',21),('ok',True)])
async def test_search_rejects_invalid_inputs(populated,query,limit):
    ctx,_,_,first,_,_=populated
    with pytest.raises(ValueError): await ctx.session_controller.search_project(first.id,query,scan_limit=limit)

@pytest.mark.asyncio
async def test_project_search_through_explicit_remote(populated,tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,db,_,first,_,_=populated
    ctx.require_service('session_query')._sessions._context().host.runtime_state_store=db.runtime_state_store
    await _runtime(db,'a',history=[{'role':'user','content':'searchable example'}])
    host,catalog,old=_host(tmp_path); configure(host); ctx._secret_store=old._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        f"async def echo(request, *, context):\n    return await context.session_controller.search_project({first.id!r},request.payload['body']['text'])\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        endpoint='/plugin-remote/hook-demo/demo/echo'; body={'args':{'text':'example'}}
        bad=await client.post(endpoint,json=body,headers={'x-plugin-token':'wrong'})
        result=await client.post(endpoint,json=body,headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    assert bad.status_code==401 and result.status_code==200
    assert any(x['session_id']=='a' for x in result.json()['payload']['items'])

@pytest.mark.asyncio
async def test_search_fails_when_history_provider_changes_between_sessions(populated,monkeypatch):
    from lamtools_core.plugin_system.session_controller import PluginSessionController
    ctx,db,_,first,_,_=populated
    host=ctx.require_service('session_query')._sessions._context().host; host.runtime_state_store=db.runtime_state_store
    await _runtime(db,'a',history=[{'role':'user','content':'needle'}])
    original=PluginSessionController.search_archive
    async def replace_after_match(self,*args,**kwargs):
        value=await original(self,*args,**kwargs)
        host.runtime_state_store=object()
        return value
    monkeypatch.setattr(PluginSessionController,'search_archive',replace_after_match)
    with pytest.raises(RuntimeError): await ctx.session_controller.search_project(first.id,'needle',scan_limit=1)



def test_migration_lists_project_search_limitations(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.remote.session.search(); }'})
    report=export_port(root,tmp_path/'ported')
    text=(tmp_path/'ported'/'PORTING.md').read_text(encoding='utf8')
    assert 'search_project' in text and '压缩' in text and '非快照' in text
    assert report['runtimeVerified'] is False
