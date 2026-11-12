"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(项目历史分页不能跨不同搜索词续用)。"""
import pytest
from .test_plugin_workspace_registry_current import workspace_env
from .test_plugin_workspace_sessions import populated
from .test_core_checkpoint_graph import _runtime

@pytest.mark.asyncio
async def test_project_history_cursor_is_bound_to_query_and_plugin(populated):
    ctx,db,_,project,_,_=populated
    ctx.require_service('session_query')._sessions._context().host.runtime_state_store=db.runtime_state_store
    await _runtime(db,'a',history=[{'role':'user','content':'needle'}])
    page=await ctx.session_controller.search_project(project.id,'needle',scan_limit=1)
    assert page['has_more'] and page['next_cursor']
    with pytest.raises(RuntimeError):
        await ctx.session_controller.search_project(project.id,'other',scan_limit=1,cursor=page['next_cursor'])
    resumed=await ctx.session_controller.search_project(project.id,'needle',scan_limit=1,cursor=page['next_cursor'])
    assert 'items' in resumed
    with pytest.raises(RuntimeError):
        await ctx.workspace_registry.sessions(project.id,limit=1,cursor=page['next_cursor'])

@pytest.mark.asyncio
async def test_cursor_binding_enforced_over_real_http(populated,tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router,plugin_http_token
    ctx,db,_,project,_,_=populated
    ctx.require_service('session_query')._sessions._context().host.runtime_state_store=db.runtime_state_store
    await _runtime(db,'a',history=[{'role':'user','content':'needle'}])
    host,catalog,old=_host(tmp_path); ctx._secret_store=old._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        f"async def echo(request, *, context):\n    body=request.payload['body']\n    return await context.session_controller.search_project({project.id!r},body['query'],scan_limit=1,cursor=body.get('cursor'))\n",encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        endpoint='/plugin-http/hook-demo/hook'; headers={'x-plugin-token':plugin_http_token(host,'hook-demo')}
        first=await client.post(endpoint,json={'query':'needle'},headers=headers)
        cursor=first.json()['payload']['next_cursor']; assert first.status_code==200 and cursor
        wrong=await client.post(endpoint,json={'query':'other','cursor':cursor},headers=headers)
        valid=await client.post(endpoint,json={'query':'needle','cursor':cursor},headers=headers)
        assert wrong.status_code>=400 and valid.status_code==200
