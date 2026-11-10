"""user:“第二阶段结束后 就继续开展第三阶段”+(会话分叉复用原检查点且限制当前项目)。"""
import pytest
from .test_plugin_checkpoint_access import setup
from .test_plugin_working_directory import env
from .test_core_checkpoint_graph import _append_production_turn, _runtime, _tool_call_history
from lamtools_core.session import SessionRecord

@pytest.mark.asyncio
async def test_scoped_fork_uses_real_checkpoint_and_rejects_other_project(setup,tmp_path):
    ctx,store,_,project,db=setup
    await _runtime(db,'s',history=_tool_call_history('one'))
    await _append_production_turn(db,'s','turn-1','one')
    cp=(await ctx.checkpoints.create('s',label='boundary'))['checkpoint']
    other=tmp_path/'other'; other.mkdir()
    await store.create(SessionRecord('foreign','core','Other','idle',metadata={'work_root':str(other)}))
    with pytest.raises((RuntimeError,ValueError)): await ctx.session_controller.fork('foreign',checkpoint_id=cp['id'],new_session_id='denied')
    result=await ctx.session_controller.fork('s',checkpoint_id=cp['id'],new_session_id='scoped-fork',title='Fork')
    assert result['session_id']=='scoped-fork'
    assert (await store.get_readonly('scoped-fork')).metadata['work_root']==str(project)
    assert await store.get_readonly('denied') is None

@pytest.mark.asyncio
async def test_scoped_fork_unknown_boundary_rejected(setup):
    ctx,store,_,_,_=setup
    with pytest.raises(RuntimeError): await ctx.session_controller.fork('s',checkpoint_id='unknown',new_session_id='missing-fork')
    assert await store.get_readonly('missing-fork') is None

def test_fork_migration_recommends_bounded_original_operation(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path,{'index.ts':'export function apply(ctx) { ctx.remote.session.fork(); }'})
    report=export_port(root,tmp_path/'ported'); row=next(r for r in report['remotes'] if r['name']=='session.fork')
    assert row['suggestedContract']=='context.session_controller.fork' and row['conversion']=='agent-required'


@pytest.mark.asyncio
async def test_scoped_fork_crosses_explicit_http(setup,tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,store,_,_,db=setup
    await _runtime(db,'s',history=_tool_call_history('one'))
    await _append_production_turn(db,'s','turn-http','one')
    checkpoint=(await ctx.checkpoints.create('s',label='http'))['checkpoint']['id']
    host,_,original=_host(tmp_path); configure(host)
    ctx._secret_store=original._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        "async def echo(request, *, context):\n    return await context.session_controller.fork('s',checkpoint_id=request.payload['body']['text'],new_session_id='http-fork')\n",encoding='utf8')
    plugin_catalog=OperationCatalog(); register_plugin_operations(plugin_catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:plugin_catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        endpoint='/plugin-remote/hook-demo/demo/echo'
        bad=await client.post(endpoint,json={'args':{'text':checkpoint}},headers={'x-plugin-token':'wrong'})
        assert bad.status_code==401 and await store.get_readonly('http-fork') is None
        good=await client.post(endpoint,json={'args':{'text':checkpoint}},headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    assert good.status_code==200 and good.json()['payload']['session_id']=='http-fork'
    assert await store.get_readonly('http-fork') is not None

@pytest.mark.asyncio
async def test_scoped_fork_cancel_waits_for_original_commit(setup,monkeypatch):
    import asyncio
    ctx,store,_,_,db=setup
    await _runtime(db,'s',history=_tool_call_history('one'))
    await _append_production_turn(db,'s','turn-cancel','one')
    checkpoint=(await ctx.checkpoints.create('s',label='cancel'))['checkpoint']['id']
    catalog=ctx.operation_catalog; original=catalog.execute; entered=asyncio.Event(); release=asyncio.Event()
    async def gated(name,*args,**kwargs):
        if name=='session.fork': entered.set(); await release.wait()
        return await original(name,*args,**kwargs)
    monkeypatch.setattr(catalog,'execute',gated)
    task=asyncio.create_task(ctx.session_controller.fork('s',checkpoint_id=checkpoint,new_session_id='cancel-fork'))
    try:
        await asyncio.wait_for(entered.wait(),3); task.cancel(); await asyncio.sleep(0); task.cancel(); await asyncio.sleep(0)
        assert not task.done(); release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert await store.get_readonly('cancel-fork') is not None
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_scoped_fork_source_moved_after_commit_reports_uncertainty(setup,tmp_path,monkeypatch):
    from lamtools_core.plugin_system.checkpoint_access import PluginCheckpointAPI
    ctx,store,_,_,db=setup
    await _runtime(db,'s',history=_tool_call_history('one'))
    await _append_production_turn(db,'s','turn-move','one')
    checkpoint=(await ctx.checkpoints.create('s',label='move'))['checkpoint']['id']
    other=tmp_path/'moved'; other.mkdir(); original=PluginCheckpointAPI.fork
    async def moved_after(self,*args,**kwargs):
        result=await original(self,*args,**kwargs)
        record,revision=await store.get_readonly_revision('s')
        await store.patch('s',metadata={**record.metadata,'work_root':str(other)},expected_revision=revision)
        return result
    monkeypatch.setattr(PluginCheckpointAPI,'fork',moved_after)
    with pytest.raises(RuntimeError) as error:
        await ctx.session_controller.fork('s',checkpoint_id=checkpoint,new_session_id='moved-fork')
    assert error.value.code=='session-controller/write-uncertain' and error.value.may_have_changed
    assert await store.get_readonly('moved-fork') is not None
