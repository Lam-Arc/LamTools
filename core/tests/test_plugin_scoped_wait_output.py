"""user:“第二阶段结束后 就继续开展第三阶段”+(等待后可有界读取原已持久化助手输出)。"""
import pytest
from .test_plugin_working_directory import env
from .test_plugin_checkpoint_access import setup
from .test_core_checkpoint_graph import _append_production_turn

@pytest.mark.asyncio
async def test_wait_output_uses_durable_assistant_events_and_cursor(setup):
    ctx,_,_,_,db=setup
    await _append_production_turn(db,'s','one','first')
    first=(await ctx.session_controller.state('s')).last_event_seq
    await _append_production_turn(db,'s','two','second')
    result=await ctx.session_controller.wait_with_output('s',timeout=0,after_seq=first,max_messages=5)
    assert result['reason'] in {'idle','timeout','blocked','closed'}
    assert result['scan_complete'] and [item['text'] for item in result['messages']]==['reply second']
    assert all(item['seq']>first for item in result['messages'])
    assert 'read_file' not in str(result) and 'first' not in str(result)

@pytest.mark.asyncio
async def test_wait_output_bounded_and_newest_first(setup):
    ctx,_,_,_,db=setup
    for i in range(3): await _append_production_turn(db,'s',f'turn{i}',f'message{i}')
    result=await ctx.session_controller.wait_with_output('s',timeout=0,after_seq=0,max_messages=2)
    assert [x['text'] for x in result['messages']]==['reply message2','reply message1']
    assert result['truncated'] and result['scan_complete']

@pytest.mark.asyncio
@pytest.mark.parametrize('after,limit',[(-1,2),(True,2),(0,0),(0,21)])
async def test_wait_output_rejects_bad_bounds(setup,after,limit):
    ctx,_,_,_,_=setup
    with pytest.raises(ValueError): await ctx.session_controller.wait_with_output('s',timeout=0,after_seq=after,max_messages=limit)

@pytest.mark.asyncio
async def test_wait_output_excludes_events_after_stopping_state(setup,monkeypatch):
    ctx,_,_,_,db=setup; api=ctx.session_controller
    await _append_production_turn(db,'s','early','early')
    original=api.wait
    async def wait_then_write(*args,**kwargs):
        result=await original(*args,**kwargs)
        await _append_production_turn(db,'s','late','late')
        return result
    monkeypatch.setattr(api,'wait',wait_then_write)
    result=await api.wait_with_output('s',timeout=0)
    assert [item['text'] for item in result['messages']]==['reply early'] and result['scan_complete']

@pytest.mark.asyncio
async def test_wait_output_withdrawal_after_event_read_rejects_old_output(setup,monkeypatch):
    import asyncio
    ctx,store,_,_,db=setup; await _append_production_turn(db,'s','one','private')
    api=ctx.session_controller; original=api.events; entered=asyncio.Event(); release=asyncio.Event()
    async def gated(*args,**kwargs):
        result=await original(*args,**kwargs); entered.set(); await release.wait(); return result
    monkeypatch.setattr(api,'events',gated); task=asyncio.create_task(api.wait_with_output('s',timeout=0))
    try:
        await asyncio.wait_for(entered.wait(),3); store._session_visible=lambda *_:False; release.set()
        with pytest.raises(RuntimeError):await task
    finally:release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_wait_output_repeated_cancel_joins_event_cleanup(setup,monkeypatch):
    import asyncio
    ctx,_,_,_,db=setup; await _append_production_turn(db,'s','one','private')
    api=ctx.session_controller; entered,cleaning,release,cleaned=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def gated(*args,**kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally:cleaning.set(); await release.wait(); cleaned.set()
    monkeypatch.setattr(api,'events',gated); task=asyncio.create_task(api.wait_with_output('s',timeout=0))
    try:
        await asyncio.wait_for(entered.wait(),3); task.cancel(); await asyncio.wait_for(cleaning.wait(),3); task.cancel(); await asyncio.sleep(0)
        assert not task.done(); release.set()
        with pytest.raises(asyncio.CancelledError):await task
        assert cleaned.is_set() and ctx._registration_scope._idle.is_set()
    finally:release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_wait_output_stops_if_page_has_no_event_at_or_before_cut(setup,monkeypatch):
    import asyncio
    from dataclasses import replace
    from types import SimpleNamespace
    from lamtools_core.plugin_system.sessions import SessionWaitResult
    ctx,_,_,_,_=setup; api=ctx.session_controller; state=replace(await api.state('s'),last_event_seq=5)
    async def fake_wait(*args,**kwargs):return SessionWaitResult('idle',state)
    async def later_page(*args,**kwargs):
        await asyncio.sleep(0)
        return SimpleNamespace(events=({'seq':6},),has_more=True)
    monkeypatch.setattr(api,'wait',fake_wait); monkeypatch.setattr(api,'events',later_page)
    result=await asyncio.wait_for(api.wait_with_output('s',timeout=0),1)
    assert not result['scan_complete'] and result['truncated'] and result['next_after_seq']==0

@pytest.mark.asyncio
async def test_wait_output_scan_budget_reports_incomplete(setup,monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    from lamtools_core.plugin_system.sessions import SessionWaitResult
    ctx,_,_,_,_=setup; api=ctx.session_controller; state=replace(await api.state('s'),last_event_seq=2101); calls=[]
    async def fake_wait(*args,**kwargs): return SessionWaitResult('idle',state)
    async def page(*args,after_seq,limit,**kwargs):
        calls.append((after_seq,limit)); events=tuple({'seq':i} for i in range(after_seq+1,min(after_seq+limit,2101)+1))
        return SimpleNamespace(events=events,has_more=True)
    monkeypatch.setattr(api,'wait',fake_wait); monkeypatch.setattr(api,'events',page)
    result=await api.wait_with_output('s',timeout=0)
    assert not result['scan_complete'] and result['truncated'] and result['next_after_seq']==2000 and len(calls)==20

@pytest.mark.asyncio
async def test_wait_output_crosses_explicit_remote(setup,tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,_,_,_,db=setup; await _append_production_turn(db,'s','remote','example')
    host,catalog,old=_host(tmp_path); configure(host); ctx._secret_store=old._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text("async def echo(request, *, context):\n    return await context.session_controller.wait_with_output(request.payload['body']['text'],timeout=0)\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        endpoint='/plugin-remote/hook-demo/demo/echo'; payload={'args':{'text':'s'}}
        denied=await client.post(endpoint,json=payload,headers={'x-plugin-token':'wrong'})
        result=await client.post(endpoint,json=payload,headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    assert denied.status_code==401 and result.status_code==200
    assert result.json()['payload']['messages'][0]['text']=='reply example'

@pytest.mark.asyncio
async def test_wait_output_limits_individual_assistant_text(setup):
    ctx,_,_,_,db=setup; await _append_production_turn(db,'s','large','x'*5000)
    result=await ctx.session_controller.wait_with_output('s',timeout=0)
    assert len(result['messages'][0]['text'])==4096 and result['messages'][0]['text_truncated']

def test_wait_output_migration_reports_event_limits(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.remote.session.wait(); }'})
    output=tmp_path/'ported'; report=export_port(root,output)
    handoff=(output/'PORTING.md').read_text(encoding='utf8')
    assert 'wait_with_output' in handoff and '持久' in handoff and report['runtimeVerified'] is False
