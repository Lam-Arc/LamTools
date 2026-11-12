"""user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(受保护操作不能从弱入口绕过)。"""
import json
import httpx
import pytest
from .test_plugin_working_directory import env
from .test_plugin_workspace_registry_current import workspace_env
from .test_plugin_remote_session_guard import guarded
from .test_plugin_raw_upload_stream import request
from lamtools_core.plugin_system.plugin_http import plugin_http_token


@pytest.mark.asyncio
async def test_direct_plugin_http_cannot_bypass_guarded_operation(guarded, monkeypatch):
    _, _, _, host, catalog, app = guarded
    calls = []
    async def forbidden(*args, **kwargs): calls.append(args); pytest.fail('unguarded direct route dispatched')
    monkeypatch.setattr(catalog, 'execute', forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-http/hook-demo/hook', json={'text':'hidden'},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert response.status_code == 403 and not calls


@pytest.mark.asyncio
async def test_unguarded_remote_alias_cannot_bypass_guarded_operation(guarded, monkeypatch):
    _, _, _, host, catalog, app = guarded
    path = host.get('hook-demo').root / 'plugin.json'; manifest = json.loads(path.read_text(encoding='utf8'))
    alias = dict(manifest['http']['remote'][0]); alias['method'] = 'unguarded'; alias.pop('resource')
    manifest['http']['remote'].append(alias); path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    calls = []
    async def forbidden(*args, **kwargs): calls.append(args); pytest.fail('unguarded alias dispatched')
    monkeypatch.setattr(catalog, 'execute', forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/unguarded', json={'args': {'text':'hidden'}},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert response.status_code == 403 and not calls


@pytest.mark.asyncio
async def test_unguarded_upload_alias_cannot_bypass_guarded_operation(guarded, monkeypatch):
    _, _, _, host, catalog, app = guarded
    path = host.get('hook-demo').root / 'plugin.json'; manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['http']['uploads'] = [{'name':'files', 'route':'/hook'}]
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    calls = []
    async def forbidden(*args, **kwargs): calls.append(args); pytest.fail('unguarded upload dispatched')
    monkeypatch.setattr(catalog, 'execute', forbidden)
    status, _, reads = await request(app, plugin_http_token(host, 'hook-demo'), 1,
        [{'type':'http.request','body':b'x','more_body':False}])
    assert status == 403 and reads == 0 and not calls


@pytest.mark.asyncio
async def test_differently_guarded_alias_cannot_bypass_original_guard(guarded, monkeypatch):
    _, _, _, host, catalog, app = guarded
    path = host.get('hook-demo').root / 'plugin.json'; manifest = json.loads(path.read_text(encoding='utf8'))
    alias = dict(manifest['http']['remote'][0]); alias['method'] = 'different'
    alias['resource'] = {'kind': 'workspace', 'argument': 'text'}
    manifest['http']['remote'].append(alias); path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    calls = []
    async def admitted(): pass
    monkeypatch.setattr('lamtools_core.plugin_system.remote_gateway.resource_admission', lambda *args: admitted)
    async def forbidden(*args, **kwargs): calls.append(args); pytest.fail('inconsistent guard dispatched')
    monkeypatch.setattr(catalog, 'execute', forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/different', json={'args': {'text':'s'}},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert response.status_code in (400, 403) and not calls
