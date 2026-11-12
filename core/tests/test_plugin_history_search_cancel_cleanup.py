"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(会话历史搜索重复取消等待底层读取清理)。"""
import asyncio
import pytest
from .test_plugin_working_directory import env
from .test_plugin_checkpoint_access import setup
from .test_core_checkpoint_graph import _runtime

@pytest.mark.asyncio
async def test_history_search_repeated_cancel_waits_native_read_cleanup(setup,monkeypatch):
    ctx,_,sessions,_,db=setup; sessions._context().host.runtime_state_store=db.runtime_state_store
    await _runtime(db,'s',history=[{'role':'user','content':'needle'}])
    entered,cleaning,release,cleaned=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event()
    original=db.runtime_state_store.read_history_page
    async def gated(*args,**kwargs):
        await original(*args,**kwargs); entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait(); cleaned.set()
    monkeypatch.setattr(db.runtime_state_store,'read_history_page',gated)
    task=asyncio.create_task(ctx.session_controller.search_archive('s','needle'))
    try:
        await asyncio.wait_for(entered.wait(),3); task.cancel(); await asyncio.wait_for(cleaning.wait(),3); task.cancel(); await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert cleaned.is_set() and ctx._registration_scope._idle.is_set()
    finally: release.set(); await asyncio.gather(task,return_exceptions=True)

from .test_plugin_workspace_registry_current import workspace_env
from .test_plugin_workspace_sessions import populated

@pytest.mark.asyncio
async def test_project_search_repeated_cancel_waits_native_read_cleanup(populated,monkeypatch):
    ctx,db,_,project,_,_=populated; ctx.require_service('session_query')._sessions._context().host.runtime_state_store=db.runtime_state_store
    await _runtime(db,'a',history=[{'role':'user','content':'needle'}])
    entered,cleaning,release,cleaned=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event(); original=db.runtime_state_store.read_history_page
    async def gated(*args,**kwargs):
        await original(*args,**kwargs); entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait(); cleaned.set()
    monkeypatch.setattr(db.runtime_state_store,'read_history_page',gated)
    task=asyncio.create_task(ctx.session_controller.search_project(project.id,'needle'))
    try:
        await asyncio.wait_for(entered.wait(),3); task.cancel(); await asyncio.wait_for(cleaning.wait(),3); task.cancel(); await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert cleaned.is_set() and ctx._registration_scope._idle.is_set()
    finally: release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_archive_search_still_returns_real_user_and_assistant_hits(setup):
    ctx,_,sessions,_,db=setup; sessions._context().host.runtime_state_store=db.runtime_state_store
    await _runtime(db,'s',history=[{'role':'user','content':'needle'},{'role':'assistant','content':'needle'}])
    result=await ctx.session_controller.search_archive('s','needle')
    assert [row['role'] for row in result['matches']]==['user','assistant']

@pytest.mark.asyncio
async def test_remote_history_search_cancel_waits_cleanup(setup,tmp_path,monkeypatch):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,_,sessions,_,db=setup; sessions._context().host.runtime_state_store=db.runtime_state_store
    await _runtime(db,'s',history=[{'role':'user','content':'needle'}]); host,catalog,old=_host(tmp_path); configure(host)
    ctx._secret_store=old._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text("async def echo(request, *, context):\n    return await context.session_controller.search_archive('s','needle')\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    entered,cleaning,release,cleaned=asyncio.Event(),asyncio.Event(),asyncio.Event(),asyncio.Event(); original=db.runtime_state_store.read_history_page
    async def gated(*args,**kwargs):
        await original(*args,**kwargs); entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait(); cleaned.set()
    monkeypatch.setattr(db.runtime_state_store,'read_history_page',gated)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'x'}},headers={'x-plugin-token':plugin_http_token(host,'hook-demo')}))
        try:
            await asyncio.wait_for(entered.wait(),3); task.cancel(); await asyncio.wait_for(cleaning.wait(),3); task.cancel(); await asyncio.sleep(0)
            assert not task.done() and not ctx._registration_scope._idle.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError): await task
            assert cleaned.is_set() and ctx._registration_scope._idle.is_set()
        finally: release.set(); await asyncio.gather(task,return_exceptions=True)
