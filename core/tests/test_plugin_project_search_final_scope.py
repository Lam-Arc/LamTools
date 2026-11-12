"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(项目复核等待期间隐藏的会话不能返回旧搜索结果)。"""
import asyncio
import pytest
from .test_plugin_workspace_registry_current import workspace_env
from .test_plugin_workspace_sessions import populated
from .test_core_checkpoint_graph import _runtime
from lamtools_core.plugin_system.workspace_registry_access import PluginWorkspaceRegistryAPI

@pytest.mark.asyncio
async def test_search_does_not_publish_hit_hidden_during_final_project_lookup(populated,monkeypatch):
    ctx,db,_,project,_,store=populated
    ctx.require_service('session_query')._sessions._context().host.runtime_state_store=db.runtime_state_store
    await _runtime(db,'a',history=[{'role':'user','content':'needle'}])
    original=PluginWorkspaceRegistryAPI.get; calls=0; entered=asyncio.Event(); release=asyncio.Event()
    async def gated(self,project_id):
        nonlocal calls
        result=await original(self,project_id); calls+=1
        if calls==3:
            entered.set(); await release.wait()
        return result
    monkeypatch.setattr(PluginWorkspaceRegistryAPI,'get',gated)
    task=asyncio.create_task(ctx.session_controller.search_project(project.id,'needle'))
    try:
        await asyncio.wait_for(entered.wait(),3)
        store._session_visible=lambda sid,_: sid not in {'a','hidden'}
        release.set()
        with pytest.raises(RuntimeError): await task
    finally:
        release.set(); await asyncio.gather(task,return_exceptions=True)

@pytest.mark.asyncio
async def test_final_project_lookup_revocation_cannot_leak_via_remote(populated,monkeypatch,tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,db,_,project,_,store=populated
    ctx.require_service('session_query')._sessions._context().host.runtime_state_store=db.runtime_state_store
    await _runtime(db,'a',history=[{'role':'user','content':'private needle'}])
    host,catalog,old=_host(tmp_path); configure(host); ctx._secret_store=old._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        f"async def echo(request, *, context):\n    return await context.session_controller.search_project({project.id!r},request.payload['body']['text'])\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    original=PluginWorkspaceRegistryAPI.get; calls=0; entered=asyncio.Event(); release=asyncio.Event()
    async def gated(self,project_id):
        nonlocal calls
        result=await original(self,project_id); calls+=1
        if calls==3: entered.set(); await release.wait()
        return result
    monkeypatch.setattr(PluginWorkspaceRegistryAPI,'get',gated)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'needle'}},headers={'x-plugin-token':plugin_http_token(host,'hook-demo')}))
        try:
            await asyncio.wait_for(entered.wait(),3); store._session_visible=lambda sid,_: sid not in {'a','hidden'}; release.set()
            response=await task
            assert response.status_code>=400 and 'private needle' not in response.text
        finally:
            release.set(); await asyncio.gather(task,return_exceptions=True)
