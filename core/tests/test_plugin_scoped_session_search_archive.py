"""user:“第二阶段结束后 就继续开展第三阶段”+(会话内容检索复用原有界历史，不公开工具调用)。"""
import asyncio
import pytest
from .test_plugin_working_directory import env
from .test_plugin_checkpoint_access import setup
from .test_core_checkpoint_graph import _runtime


@pytest.mark.asyncio
async def test_scoped_search_reads_native_history_and_excludes_tool_content(setup):
    ctx, _, sessions, _, db = setup
    sessions._context().host.runtime_state_store = db.runtime_state_store
    await _runtime(db, 's', history=[
        {'role':'user','content':'first needle'},
        {'role':'assistant','content':'second NEEDLE','tool_calls':[{'name':'hidden-needle','arguments':{'secret':'needle'}}]},
        {'role':'tool','content':'private needle'}])
    result = await ctx.session_controller.search_archive('s', 'needle', limit=20)
    assert [x['role'] for x in result['matches']] == ['user', 'assistant']
    assert 'private needle' not in str(result) and 'hidden-needle' not in str(result)
    with pytest.raises(RuntimeError): await ctx.session_controller.search_archive('hidden', 'needle')


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['hide','replace','cancel'])
async def test_search_rechecks_authority_after_history_read(setup,monkeypatch,change):
    ctx, store, sessions, _, db = setup
    host = sessions._context().host
    host.runtime_state_store = db.runtime_state_store
    await _runtime(db, 's', history=[{'role':'user','content':'private needle'}])
    original = db.runtime_state_store.read_history_page
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(db.runtime_state_store, 'read_history_page', gated)
    task = asyncio.create_task(ctx.session_controller.search_archive('s','needle'))
    try:
        await asyncio.wait_for(entered.wait(),3)
        if change == 'hide': store._session_visible = lambda *_: False
        elif change == 'replace': host.runtime_state_store = object()
        else: task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError if change == 'cancel' else RuntimeError): await task
    finally:
        release.set()
        await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_paging_and_missing_provider_are_explicit(setup):
    ctx, _, sessions, _, db = setup
    host = sessions._context().host
    with pytest.raises(RuntimeError) as exc: await ctx.session_controller.search_archive('s', 'x')
    assert exc.value.code == 'session-controller/unavailable'
    host.runtime_state_store = db.runtime_state_store
    await _runtime(db, 's', history=[{'role':'user','content':'first x'}, {'role':'assistant','content':'second x'}])
    first = await ctx.session_controller.search_archive('s','x',limit=1)
    assert len(first['matches']) == 1 and first['next_after_seq'] is not None
    second = await ctx.session_controller.search_archive('s','x',limit=1,after_seq=first['next_after_seq'])
    assert len(second['matches']) == 1 and second['matches'][0]['history_seq'] > first['matches'][0]['history_seq']


@pytest.mark.asyncio
@pytest.mark.parametrize('query,limit,after', [('',10,0), ('\ud800',10,0), ('x',21,0), ('x',10,-1)])
async def test_invalid_search_parameters_are_rejected(setup, query, limit, after):
    from lamtools_core.tool.context_history import HistoryError
    ctx, _, sessions, _, db = setup
    sessions._context().host.runtime_state_store = db.runtime_state_store
    with pytest.raises((ValueError, HistoryError)):
        await ctx.session_controller.search_archive('s', query, limit=limit, after_seq=after)


@pytest.mark.asyncio
async def test_search_archive_crosses_real_remote(setup,tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx, _, sessions, _, db = setup
    sessions._context().host.runtime_state_store = db.runtime_state_store
    await _runtime(db,'s',history=[{'role':'user','content':'remote search example'}])
    host,catalog,old=_host(tmp_path); configure(host)
    ctx._secret_store=old._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        "async def echo(request, *, context):\n    return await context.session_controller.search_archive('s',request.payload['body']['text'])\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        endpoint='/plugin-remote/hook-demo/demo/echo'; body={'args':{'text':'example'}}
        denied=await client.post(endpoint,json=body,headers={'x-plugin-token':'wrong'})
        response=await client.post(endpoint,json=body,headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    assert denied.status_code==401 and response.status_code==200
    assert response.json()['payload']['matches'][0]['preview']=='remote search example'


def test_migration_describes_single_session_archive_difference(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.remote.session.search(); }'})
    report=export_port(root,tmp_path/'ported')
    item=next(row for row in report['remotes'] if row['name']=='session.search')
    assert item['suggestedContract']=='context.session_controller.search_archive'
    assert '单会话' in item['difference'] and report['runtimeVerified'] is False
