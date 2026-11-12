"""user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(明确列出的全部资源均须准入)。"""
import json

import httpx
import pytest

from .test_plugin_working_directory import env
from .test_plugin_workspace_registry_current import workspace_env
from .test_plugin_remote_session_guard import guarded
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import plugin_http_token
from lamtools_core.session import SessionRecord


def configure_multi(host, resources):
    path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    method = manifest['http']['remote'][0]
    method['resource'] = resources
    method['argsSchema']['properties']['target'] = {'type': 'string'}
    method['argsSchema']['required'].append('target')
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()


@pytest.mark.asyncio
async def test_all_declared_sessions_must_be_visible(guarded, monkeypatch):
    _, store, root, host, catalog, app = guarded
    await store.create(SessionRecord('s2', 'core', 'Second', 'idle', metadata={'work_root': str(root)}))
    configure_multi(host, [{'kind':'session','argument':'text'}, {'kind':'session','argument':'target'}])
    original = catalog.execute; calls = []
    async def tracked(*args, **kwargs): calls.append(args[0]); return await original(*args, **kwargs)
    monkeypatch.setattr(catalog, 'execute', tracked)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        url = '/plugin-remote/hook-demo/demo/echo'; headers = {'x-plugin-token': plugin_http_token(host, 'hook-demo')}
        denied = await client.post(url, json={'args': {'text':'s', 'target':'hidden'}}, headers=headers)
        allowed = await client.post(url, json={'args': {'text':'s', 'target':'s2'}}, headers=headers)
    assert denied.status_code == 403 and allowed.status_code == 200 and calls == ['hook-demo.echo']


@pytest.mark.asyncio
async def test_each_resource_rechecked_after_operation(guarded, monkeypatch):
    _, store, root, host, catalog, app = guarded
    await store.create(SessionRecord('s2', 'core', 'Second', 'idle', metadata={'work_root': str(root)}))
    configure_multi(host, [{'kind':'session','argument':'text'}, {'kind':'session','argument':'target'}])
    original = catalog.execute
    async def hide_second(*args, **kwargs):
        result = await original(*args, **kwargs)
        store._session_visible = lambda sid, _: sid != 's2'
        return result
    monkeypatch.setattr(catalog, 'execute', hide_second)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        result = await client.post('/plugin-remote/hook-demo/demo/echo',
            json={'args': {'text':'s', 'target':'s2'}}, headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert result.status_code == 409 and result.json()['may_have_changed'] is True and 'called' not in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize('resources', [[], [{'kind':'session','argument':'text'}]*2,
    [{'kind':'session','argument':'text'}]*5, [{'kind':'session','argument':'target'}, {'kind':'other','argument':'text'}]])
async def test_invalid_multi_resource_declaration_fails_closed(guarded, resources):
    _, _, _, host, _, app = guarded
    configure_multi(host, resources)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        result = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text':'s','target':'s'}},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert result.status_code == 400


@pytest.mark.asyncio
async def test_mixed_session_and_workspace_each_use_original_host(guarded):
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.app.http_agent_app import _register_core_project_operations
    ctx, store, root, host, _, app = guarded
    db = store._db_provider()
    project, _ = await db.project_store.create(root, name='Current')
    native = OperationCatalog(); _register_core_project_operations(native, project_store=db.project_store)
    ctx.operation_catalog = native
    configure_multi(host, [{'kind':'session','argument':'text'}, {'kind':'workspace','argument':'target'}])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        url = '/plugin-remote/hook-demo/demo/echo'; headers = {'x-plugin-token': plugin_http_token(host, 'hook-demo')}
        denied = await client.post(url, json={'args': {'text':'s', 'target':'missing'}}, headers=headers)
        allowed = await client.post(url, json={'args': {'text':'s', 'target':project.id}}, headers=headers)
    assert denied.status_code == 403 and allowed.status_code == 200


@pytest.mark.asyncio
async def test_multi_resource_stream_rechecks_each_resource_while_idle(guarded, monkeypatch):
    import asyncio
    from lamtools_core.app.operation_catalog import OperationResult
    from lamtools_core.plugin_system import remote_stream
    from lamtools_core.plugin_system.remote_gateway import dispatch_remote_request
    monkeypatch.setattr(remote_stream, 'POLL_INTERVAL', 0.01)
    _, store, root, host, catalog, _ = guarded
    await store.create(SessionRecord('s2', 'core', 'Second', 'idle', metadata={'work_root': str(root)}))
    configure_multi(host, [{'kind':'session','argument':'text'}, {'kind':'session','argument':'target'}])
    path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8')); manifest['http']['remote'][0]['resultEncoding'] = 'ndjson'
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    sent, closed = asyncio.Event(), asyncio.Event()
    async def source():
        try:
            yield {'value':'first'}
            await asyncio.Event().wait()
        finally: closed.set()
    catalog.unregister_owner('plugin:hook-demo')
    catalog.register('hook-demo.echo', lambda request: OperationResult(request.name, source()), owner='plugin:hook-demo')
    status, response = await dispatch_remote_request(host=host, catalog=catalog, plugin='hook-demo', namespace='demo',
        method='echo', body={'args': {'text':'s','target':'s2'}}, headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert status == 200
    frames = []
    async def receive(): await asyncio.Event().wait()
    async def send(message):
        frames.append(message)
        if b'first' in message.get('body', b''): sent.set()
    task = asyncio.create_task(response({}, receive, send))
    try:
        await asyncio.wait_for(sent.wait(), 3)
        store._session_visible = lambda sid, _: sid != 's2'
        await asyncio.wait_for(task, 3)
        assert closed.is_set() and not host._remote_stream_slots
        assert b'"kind":"error"' in b''.join(frame.get('body', b'') for frame in frames)
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_multi_resource_migration_does_not_auto_grant(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {'index.ts': 'export function apply(ctx) { ctx.remote.session.state(); }'})
    output = tmp_path / 'ported'; report = export_port(root, output)
    text = (output / 'PORTING.md').read_text(encoding='utf8')
    assert '1–4' in text and 'Peer' in text and report['runtimeVerified'] is False
    manifest = json.loads((output / 'plugin.json').read_text(encoding='utf8'))
    assert not manifest.get('http', {}).get('remote')
