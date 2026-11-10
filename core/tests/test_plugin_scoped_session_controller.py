"""user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(会话只读先绑定原可见会话和项目)。"""
import asyncio
import pytest
from .test_plugin_working_directory import env
from lamtools_core.session import SessionRecord

@pytest.mark.asyncio
async def test_scoped_state_events_wait_use_original_session(env, tmp_path):
    ctx, store, _, project = env
    other = tmp_path / 'other'; other.mkdir()
    await store.create(SessionRecord('foreign', 'core', 'Other', 'idle', metadata={'work_root':str(other)}))
    api=ctx.session_controller
    assert (await api.state('s')).session_id == 's'
    assert (await api.events('s')).session_id == 's'
    assert (await api.wait('s', timeout=0)).state.session_id == 's'
    for name in ('hidden','foreign','missing'):
        with pytest.raises((ValueError, RuntimeError)): await api.state(name)

@pytest.mark.asyncio
async def test_scoped_read_does_not_publish_after_session_hidden(env, monkeypatch):
    ctx, store, _, _ = env
    api=ctx.session_controller
    original=api._sessions.call
    async def hidden_after(*args, **kwargs):
        result=await original(*args, **kwargs)
        store._session_visible=lambda sid, _: sid != 's'
        return result
    monkeypatch.setattr(api._sessions, 'call', hidden_after)
    with pytest.raises((ValueError, RuntimeError)): await api.state('s')

@pytest.mark.asyncio
async def test_scoped_read_rejects_replaced_session_provider(env, monkeypatch):
    ctx, _, _, _ = env
    api=ctx.session_controller
    original=api._sessions.call
    async def replaced(*args, **kwargs):
        value=await original(*args, **kwargs)
        ctx.set_service('sessions', object())
        return value
    monkeypatch.setattr(api._sessions, 'call', replaced)
    with pytest.raises(RuntimeError): await api.state('s')

@pytest.mark.asyncio
async def test_scoped_state_crosses_explicit_http_and_rejects_other_project(env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.app.operation_catalog import OperationCatalog, OperationResult
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, store, _, _ = env
    other=tmp_path/'other-http'; other.mkdir()
    await store.create(SessionRecord('foreign-http','core','Foreign','idle',metadata={'work_root':str(other)}))
    host, _, original_context=_host(tmp_path); configure(host)
    ctx._secret_store=original_context._secret_store; host.backend_manager.context=ctx
    (host.get('hook-demo').root/'ops.py').write_text(
        "from lamtools_core.app.operation_catalog import OperationResult\nasync def echo(request, *, context):\n    return OperationResult(request.name, await context.session_controller.state(request.payload['body']['text']))\n",encoding='utf8')
    catalog=OperationCatalog(); register_plugin_operations(catalog,host)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda:host,lambda:catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        path='/plugin-remote/hook-demo/demo/echo'; headers={'x-plugin-token':plugin_http_token(host,'hook-demo')}
        good=await client.post(path,json={'args':{'text':'s'}},headers=headers)
        bad=await client.post(path,json={'args':{'text':'foreign-http'}},headers=headers)
        assert good.status_code==200 and good.json()['payload']['session_id']=='s'
        assert bad.status_code!=200 and 'Foreign' not in bad.text

@pytest.mark.asyncio
async def test_scoped_read_cancellation_cleans_up_original_call(env, monkeypatch):
    ctx, _, _, _ = env
    api=ctx.session_controller
    entered=asyncio.Event(); cleaned=asyncio.Event()
    async def waiting(*args, **kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaned.set()
    monkeypatch.setattr(api._sessions, 'call', waiting)
    task=asyncio.create_task(api.wait('s', timeout=30))
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert cleaned.is_set() and ctx._registration_scope._idle.is_set()

@pytest.mark.asyncio
async def test_rejects_session_and_directory_hosts_from_different_generations(env):
    from lamtools_core.app.plugin_sessions import PluginSessionService
    ctx, _, sessions, _ = env
    replacement=PluginSessionService(lambda:sessions._context())
    ctx.set_service('sessions', replacement)
    try:
        with pytest.raises(RuntimeError): await ctx.session_controller.state('s')
    finally:
        replacement.shutdown()

def test_migration_suggests_scoped_read_controller(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root=source(tmp_path, {'index.ts':'export function apply(ctx) { ctx.remote.session.state(); ctx.remote.session.events(); ctx.remote.session.wait(); }'})
    report=export_port(root, tmp_path/'ported')
    methods={row['name']:row for row in report['remotes']}
    for method in ('state','events','wait'):
        row=methods['session.'+method]
        assert row['suggestedContract']=='context.session_controller.'+method
        assert row['conversion']=='agent-required'
    assert report['runtimeVerified'] is False
