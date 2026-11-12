"""user:“第二阶段结束后 就继续开展第三阶段”+(远程调用必须能识别可能已提交的写入)。"""
import pytest
import httpx
from fastapi import FastAPI
from .test_plugin_workspace_registry_current import workspace_env
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from lamtools_core.app.operation_catalog import OperationResult
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token


@pytest.mark.asyncio
async def test_committed_write_reports_uncertainty_over_real_http(workspace_env, tmp_path, monkeypatch):
    ctx, db, host_catalog, project, _ = workspace_env
    original = host_catalog.execute
    async def after_commit(name, *args, **kwargs):
        result = await original(name, *args, **kwargs)
        if name == 'project.sessions.create':
            return OperationResult(name, {'error': 'private backend detail'}, status='error')
        return result
    monkeypatch.setattr(host_catalog, 'execute', after_commit)
    host, catalog, old_context = _host(tmp_path)
    configure(host)
    ctx._secret_store = old_context._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        'async def echo(request, *, context):\n'
        f"    return await context.workspace_controller.create_session('{project.id}', title='Committed')\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'go'}},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert response.status_code == 400
    assert response.json()['payload']['may_have_changed'] is True
    assert 'private backend detail' not in response.text
    assert any(s.title == 'Committed' for s in await db.project_store.list_sessions(project.id))


@pytest.mark.asyncio
@pytest.mark.parametrize('value', ['false', 'string', 'missing'])
async def test_unmarked_errors_do_not_claim_uncertain_write(tmp_path, value):
    host, catalog, _ = _host(tmp_path)
    configure(host)
    (host.get('hook-demo').root / 'ops.py').write_text(
        'class TestError(Exception): pass\n'
        'async def echo(request, *, context):\n'
        "    e = TestError('rejected')\n"
        "    value = request.payload['body']['text']\n"
        "    if value == 'false': e.may_have_changed = False\n"
        "    if value == 'string': e.may_have_changed = 'yes'\n"
        '    raise e\n', encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': value}},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert response.status_code == 400
    assert 'may_have_changed' not in response.json()['payload']
