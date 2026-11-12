"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(流逐帧及空闲时复核显式资源)。"""
import asyncio
import json

import pytest
from .test_plugin_working_directory import env
from .test_plugin_workspace_registry_current import workspace_env
from .test_plugin_remote_session_guard import guarded
from lamtools_core.app.operation_catalog import OperationResult
from lamtools_core.plugin_system.plugin_http import plugin_http_token


@pytest.mark.asyncio
@pytest.mark.parametrize('stop', ['before_next', 'idle', 'disconnect', 'cancel'])
async def test_guarded_stream_revokes_and_joins_real_source(guarded, monkeypatch, stop):
    from lamtools_core.plugin_system import remote_stream
    monkeypatch.setattr(remote_stream, 'POLL_INTERVAL', 0.01)
    ctx, store, _, host, catalog, app = guarded
    path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['http']['remote'][0]['resultEncoding'] = 'ndjson'
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    sent, gate, closed, disconnect = asyncio.Event(), asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def source():
        try:
            yield {'value': 'first'}
            await gate.wait()
            yield {'value': 'secret-after-revoke'}
        finally:
            closed.set()
    catalog.unregister_owner('plugin:hook-demo')
    catalog.register('hook-demo.echo', lambda request: OperationResult(request.name, source()), owner='plugin:hook-demo')
    token = plugin_http_token(host, 'hook-demo')
    delivered = False; frames = []
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {'type': 'http.request', 'body': json.dumps({'args': {'text': 's'}}).encode(), 'more_body': False}
        await disconnect.wait()
        return {'type': 'http.disconnect'}
    async def send(message):
        frames.append(message)
        if message['type'] == 'http.response.body' and b'first' in message.get('body', b''): sent.set()
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST', 'scheme': 'http',
        'path': '/plugin-remote/hook-demo/demo/echo', 'query_string': b'',
        'headers': [(b'content-type', b'application/json'), (b'x-plugin-token', token.encode())],
        'client': ('127.0.0.1', 1), 'server': ('test', 80)}
    task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(sent.wait(), 3)
        if stop in {'before_next', 'idle'}:
            store._session_visible = lambda *_: False
            if stop == 'before_next': gate.set()
        elif stop == 'disconnect': disconnect.set()
        else: task.cancel()
        if stop == 'cancel':
            with pytest.raises(asyncio.CancelledError): await task
        else:
            await asyncio.wait_for(task, 3)
        assert closed.is_set() and not host._remote_stream_slots and ctx._registration_scope._idle.is_set()
        assert b'secret-after-revoke' not in b''.join(frame.get('body', b'') for frame in frames)
        if stop in {'before_next', 'idle'}:
            assert b'"kind":"error"' in b''.join(frame.get('body', b'') for frame in frames)
    finally:
        gate.set(); disconnect.set()
        if not task.done(): task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_disconnect_during_initial_resource_check_joins_check_and_closes_source(guarded, monkeypatch):
    from lamtools_core.plugin_system.remote_gateway import dispatch_remote_request
    from lamtools_core.plugin_system.session_controller import PluginSessionController
    ctx, _, _, host, catalog, _ = guarded
    path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['http']['remote'][0]['resultEncoding'] = 'ndjson'
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    entered, cleaning, release, closed, disconnect = (asyncio.Event() for _ in range(5))
    class Source:
        def __aiter__(self): return self
        async def __anext__(self): pytest.fail('unauthorized stream must not be pulled')
        async def aclose(self): closed.set()
    catalog.unregister_owner('plugin:hook-demo')
    catalog.register('hook-demo.echo', lambda request: OperationResult(request.name, Source()), owner='plugin:hook-demo')
    calls = 0; original = PluginSessionController._admit
    async def gated(self, sid):
        nonlocal calls
        calls += 1
        if calls == 3:
            entered.set()
            try: await asyncio.Event().wait()
            finally: cleaning.set(); await release.wait()
        return await original(self, sid)
    monkeypatch.setattr(PluginSessionController, '_admit', gated)
    status, response = await dispatch_remote_request(host=host, catalog=catalog, plugin='hook-demo', namespace='demo',
        method='echo', body={'args': {'text': 's'}}, headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert status == 200
    async def receive():
        await disconnect.wait()
        return {'type': 'http.disconnect'}
    async def send(message): pytest.fail('disconnected client must not get a frame')
    task = asyncio.create_task(response({}, receive, send))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        disconnect.set()
        await asyncio.wait_for(cleaning.wait(), 3)
        assert not task.done() and not closed.is_set() and host._remote_stream_slots
        release.set()
        await asyncio.wait_for(task, 3)
        assert closed.is_set() and not host._remote_stream_slots and ctx._registration_scope._idle.is_set()
    finally:
        release.set(); disconnect.set()
        if not task.done(): task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_workspace_stream_closes_when_original_project_is_deleted(workspace_env, tmp_path, monkeypatch):
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system import remote_stream
    from lamtools_core.plugin_system.remote_gateway import dispatch_remote_request
    monkeypatch.setattr(remote_stream, 'POLL_INTERVAL', 0.01)
    ctx, db, _, project, _ = workspace_env
    await ctx._registration_scope.dispose()
    host, catalog, original = _host(tmp_path); configure(host)
    path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['http']['remote'][0].update(resource={'kind': 'workspace', 'argument': 'text'}, resultEncoding='ndjson')
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    ctx._secret_store = original._secret_store
    ctx._begin_registration_scope('hook-demo', 2, manifest=host.get('hook-demo'))
    host.backend_manager.context = ctx
    emitted, closed = asyncio.Event(), asyncio.Event()
    async def source():
        try:
            yield {'value': 'first'}
            await asyncio.Event().wait()
        finally: closed.set()
    catalog.unregister_owner('plugin:hook-demo')
    catalog.register('hook-demo.echo', lambda request: OperationResult(request.name, source()), owner='plugin:hook-demo')
    status, response = await dispatch_remote_request(host=host, catalog=catalog, plugin='hook-demo', namespace='demo',
        method='echo', body={'args': {'text': project.id}}, headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert status == 200
    frames = []
    async def receive(): await asyncio.Event().wait()
    async def send(message):
        frames.append(message)
        if b'first' in message.get('body', b''): emitted.set()
    task = asyncio.create_task(response({}, receive, send))
    try:
        await asyncio.wait_for(emitted.wait(), 3)
        await db.project_store.delete_with_sessions(project.id)
        await asyncio.wait_for(task, 3)
        assert closed.is_set() and not host._remote_stream_slots and ctx._registration_scope._idle.is_set()
        assert b'"kind":"error"' in b''.join(frame.get('body', b'') for frame in frames)
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_guarded_stream_rechecks_resource_before_response_headers(guarded):
    from lamtools_core.plugin_system.remote_gateway import dispatch_remote_request
    ctx, store, _, host, catalog, _ = guarded
    path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['http']['remote'][0]['resultEncoding'] = 'ndjson'
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    closed = asyncio.Event()
    class Source:
        def __aiter__(self): return self
        async def __anext__(self): pytest.fail('withdrawn resource must not be pulled')
        async def aclose(self): closed.set()
    catalog.unregister_owner('plugin:hook-demo')
    catalog.register('hook-demo.echo', lambda request: OperationResult(request.name, Source()), owner='plugin:hook-demo')
    status, response = await dispatch_remote_request(host=host, catalog=catalog, plugin='hook-demo', namespace='demo',
        method='echo', body={'args': {'text': 's'}}, headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert status == 200
    store._session_visible = lambda *_: False
    frames = []
    async def receive(): await asyncio.Event().wait()
    async def send(message): frames.append(message)
    await response({}, receive, send)
    assert frames[0]['status'] == 409 and closed.is_set()
    assert not host._remote_stream_slots and ctx._registration_scope._idle.is_set()


@pytest.mark.asyncio
async def test_existing_unguarded_stream_keeps_original_behavior(guarded):
    import httpx
    _, _, _, host, catalog, app = guarded
    path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    descriptor = manifest['http']['remote'][0]
    descriptor.pop('resource'); descriptor['resultEncoding'] = 'ndjson'
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    closed = asyncio.Event()
    async def source():
        try:
            yield {'value': 'one'}
            yield {'value': 'two'}
        finally: closed.set()
    catalog.unregister_owner('plugin:hook-demo')
    catalog.register('hook-demo.echo', lambda request: OperationResult(request.name, source()), owner='plugin:hook-demo')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'anything'}},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert response.status_code == 200
    assert [json.loads(line)['kind'] for line in response.text.splitlines()] == ['item', 'item', 'end']
    assert closed.is_set() and not host._remote_stream_slots
