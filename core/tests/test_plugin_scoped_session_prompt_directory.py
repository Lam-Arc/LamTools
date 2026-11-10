"""user:“复用原宿主权威”+(会话消息投递采用会话实际执行目录，不由调用者提供目录)。"""
import pytest
from .test_plugin_working_directory import env

@pytest.mark.asyncio
async def test_prompt_uses_selected_session_directory(env, monkeypatch):
    ctx, _, _, root=env
    before=await ctx.working_directory.get('s')
    await ctx.working_directory.set('s','one',expected_revision=before.revision)
    api=ctx.session_controller; original=api._sessions.call; calls=[]
    async def track(method,*args,**kwargs):
        if method=='prompt': calls.append(kwargs['work_root'])
        return await original(method,*args,**kwargs)
    monkeypatch.setattr(api._sessions,'call',track)
    result=await api.prompt('s',request_id='cwd',text='hello')
    assert result.accepted and calls==[str(root/'one')]

@pytest.mark.asyncio
async def test_missing_execution_directory_rejects_before_prompt(env, monkeypatch):
    ctx, store, _, root=env
    record, revision=await store.get_readonly_revision('s')
    await store.patch('s',metadata={**record.metadata,'execution_directory':str(root/'missing')},expected_revision=revision)
    api=ctx.session_controller
    async def forbidden(*args,**kwargs): pytest.fail('missing execution directory dispatched prompt')
    monkeypatch.setattr(api._sessions,'call',forbidden)
    with pytest.raises(RuntimeError) as error: await api.prompt('s',request_id='no',text='hello')
    assert error.value.code=='session-controller/directory-unavailable' and not error.value.may_have_changed

@pytest.mark.asyncio
async def test_selected_directory_through_real_http(env, tmp_path, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, sessions, root=env
    state=await ctx.working_directory.get('s')
    await ctx.working_directory.set('s','one',expected_revision=state.revision)
    original=sessions.prompt; received=[]
    async def record(*args,**kwargs):
        received.append(kwargs['work_root']); return await original(*args,**kwargs)
    monkeypatch.setattr(sessions,'prompt',record)
    host, _, original_ctx=_host(tmp_path); configure(host)
    ctx._secret_store=original_ctx._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\nasync def echo(request, *, context):\n    value=await context.session_controller.prompt('s',request_id='http-cwd',text=request.payload['body']['text'])\n    return OperationResult(request.name,value)\n",encoding='utf8')
    catalog=OperationCatalog(); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post('/plugin-remote/hook-demo/demo/echo',json={'args':{'text':'hello'}},headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    assert response.status_code==200 and response.json()['payload']['accepted']
    assert received==[str(root/'one')]

@pytest.mark.asyncio
async def test_prompt_uses_one_directory_snapshot_if_session_changes_after_dispatch(env, monkeypatch):
    ctx, _, _, root=env
    first=await ctx.working_directory.get('s')
    await ctx.working_directory.set('s','one',expected_revision=first.revision)
    api=ctx.session_controller; original=api._sessions.call; captured=[]
    async def change_then_dispatch(method,*args,**kwargs):
        if method=='prompt':
            captured.append(kwargs['work_root'])
            current=await ctx.working_directory.get('s')
            await ctx.working_directory.set('s','two',expected_revision=current.revision)
        return await original(method,*args,**kwargs)
    monkeypatch.setattr(api._sessions,'call',change_then_dispatch)
    result=await api.prompt('s',request_id='snapshot',text='hello')
    assert result.accepted and captured==[str(root/'one')]
    assert (await ctx.working_directory.get('s')).path==str(root/'two')
