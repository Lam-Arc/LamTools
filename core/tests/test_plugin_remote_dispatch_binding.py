"""user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(调用前撤回或修改声明不能进入旧处理器)。"""
import json
import httpx
import pytest
from fastapi import FastAPI
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['remove', 'schema', 'generation'])
@pytest.mark.parametrize('encoding', ['json', 'ndjson'])
async def test_dispatch_rechecks_manifest_and_generation_before_handler(tmp_path, monkeypatch, change, encoding):
    from lamtools_core.plugin_system import plugin_http
    from .test_plugin_remote_binary import set_encoding
    host, catalog, _ = _host(tmp_path)
    configure(host)
    if encoding == 'ndjson': set_encoding(host, encoding)
    token = plugin_http_token(host, 'hook-demo')
    original = plugin_http.read_operations
    invoked = []
    native_execute = catalog.execute
    async def tracked(*args, **kwargs):
        invoked.append(True)
        return await native_execute(*args, **kwargs)
    monkeypatch.setattr(catalog, 'execute', tracked)
    def changed(manifest):
        result = original(manifest)
        if change == 'remove':
            configure(host, remove=True)
        elif change == 'schema':
            path = manifest.root / 'plugin.json'
            raw = json.loads(path.read_text(encoding='utf8'))
            raw['http']['remote'][0]['argsSchema']['properties']['text']['maxLength'] = 1
            path.write_text(json.dumps(raw), encoding='utf8')
            host._invalidate()
        else:
            host.backend_manager.generation['hook-demo'] = 77
        return result
    monkeypatch.setattr(plugin_http, 'read_operations', changed)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'hello'}},
                                     headers={'x-plugin-token': token})
    assert response.status_code in (404, 409)
    assert not invoked
    assert not getattr(host, '_remote_stream_slots', {})


@pytest.mark.asyncio
async def test_external_operation_spec_change_rejected_without_manifest_change(tmp_path, monkeypatch):
    from lamtools_core.plugin_system import plugin_http
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    host, catalog, _ = _host(tmp_path)
    configure(host)
    manifest = host.get('hook-demo')
    spec_path = manifest.root / 'operations.json'
    raw_path = manifest.root / 'plugin.json'
    raw = json.loads(raw_path.read_text(encoding='utf8'))
    spec_path.write_text(json.dumps({'operations': raw['operations']}), encoding='utf8')
    raw['operations'] = ['./operations.json']
    raw_path.write_text(json.dumps(raw), encoding='utf8')
    host._invalidate()
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    token = plugin_http_token(host, 'hook-demo')
    original = plugin_http.read_operations
    invoked = []
    native_execute = catalog.execute
    async def tracked(*args, **kwargs):
        invoked.append(True)
        return await native_execute(*args, **kwargs)
    monkeypatch.setattr(catalog, 'execute', tracked)
    def changed(current):
        result = original(current)
        data = json.loads(spec_path.read_text(encoding='utf8'))
        data['operations'][0]['permission'] = 'hard_block'
        spec_path.write_text(json.dumps(data), encoding='utf8')
        return result
    monkeypatch.setattr(plugin_http, 'read_operations', changed)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'x'}},
                                     headers={'x-plugin-token': token})
    assert response.status_code == 409 and not invoked


@pytest.mark.asyncio
@pytest.mark.parametrize('encoding', ['json', 'ndjson'])
async def test_unchanged_authorized_remote_still_dispatches(tmp_path, encoding):
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.app.operation_catalog import OperationResult
    host, catalog, _ = _host(tmp_path)
    configure(host)
    if encoding == 'ndjson':
        set_encoding(host, encoding)
        async def source(): yield {'value': 'ok'}
        catalog.unregister_owner('plugin:hook-demo')
        catalog.register('hook-demo.echo', lambda request: OperationResult(request.name, source()), owner='plugin:hook-demo')
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'ok'}},
                                     headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert response.status_code == 200
    if encoding == 'json': assert response.json()['payload']['echo'] == {'text': 'ok'}
    else: assert [json.loads(line)['kind'] for line in response.iter_lines()] == ['item', 'end']
    assert not getattr(host, '_remote_stream_slots', {})


@pytest.mark.asyncio
@pytest.mark.parametrize('encoding', ['json', 'ndjson'])
async def test_token_revoked_during_native_operation_check_never_executes(tmp_path, monkeypatch, encoding):
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.plugin_system import plugin_http
    host, catalog, context = _host(tmp_path)
    configure(host)
    if encoding == 'ndjson': set_encoding(host, encoding)
    token = plugin_http_token(host, 'hook-demo')
    original = plugin_http.read_operations
    def revoke(manifest):
        specs = original(manifest)
        context._secret_store.view('hook-demo').delete('httpToken')
        return specs
    monkeypatch.setattr(plugin_http, 'read_operations', revoke)
    async def forbidden(*args, **kwargs): pytest.fail('revoked token must not dispatch')
    monkeypatch.setattr(catalog, 'execute', forbidden)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'x'}},
                                     headers={'x-plugin-token': token})
    assert response.status_code == 401
    assert not context._secret_store.view('hook-demo').get('httpToken')
    assert not getattr(host, '_remote_stream_slots', {})


def test_migration_reports_gateway_binding_contract(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {'index.ts': 'export function apply(ctx) { ctx.remote.session.state(); }'})
    report = export_port(root, tmp_path / 'ported')
    assert report['sundayHostContracts']['remoteGateway']['version'] == 5
    assert '派发前' in (tmp_path / 'ported' / 'PORTING.md').read_text(encoding='utf8')
    assert report['runtimeVerified'] is False


@pytest.mark.asyncio
async def test_stream_stops_when_external_operation_permission_is_withdrawn(tmp_path):
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.app.operation_catalog import OperationResult
    host, catalog, _ = _host(tmp_path)
    configure(host)
    set_encoding(host, 'ndjson')
    manifest = host.get('hook-demo')
    spec_path = manifest.root / 'operations.json'
    raw_path = manifest.root / 'plugin.json'
    raw = json.loads(raw_path.read_text(encoding='utf8'))
    spec_path.write_text(json.dumps({'operations': raw['operations']}), encoding='utf8')
    raw['operations'] = ['./operations.json']
    raw_path.write_text(json.dumps(raw), encoding='utf8')
    host._invalidate()
    async def source():
        yield {'value': 'permitted'}
        data = json.loads(spec_path.read_text(encoding='utf8'))
        data['operations'][0]['permission'] = 'hard_block'
        spec_path.write_text(json.dumps(data), encoding='utf8')
        yield {'value': 'must-not-appear'}
    catalog.unregister_owner('plugin:hook-demo')
    catalog.register('hook-demo.echo', lambda request: OperationResult(request.name, source()), owner='plugin:hook-demo')
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'x'}},
                                     headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    frames = [json.loads(line) for line in response.iter_lines()]
    assert frames[0]['payload']['value'] == 'permitted' and frames[-1]['kind'] == 'error'
    assert 'must-not-appear' not in response.text and not host._remote_stream_slots


@pytest.mark.asyncio
async def test_idle_stream_closes_after_external_operation_withdrawal(tmp_path):
    import asyncio
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.app.operation_catalog import OperationResult
    host, catalog, _ = _host(tmp_path)
    configure(host)
    set_encoding(host, 'ndjson')
    manifest = host.get('hook-demo')
    spec_path, raw_path = manifest.root / 'operations.json', manifest.root / 'plugin.json'
    raw = json.loads(raw_path.read_text(encoding='utf8'))
    spec_path.write_text(json.dumps({'operations': raw['operations']}), encoding='utf8')
    raw['operations'] = ['./operations.json']
    raw_path.write_text(json.dumps(raw), encoding='utf8')
    host._invalidate()
    closed, done, messages = asyncio.Event(), asyncio.Event(), []
    async def source():
        try:
            yield {'value': 'opened'}
            await asyncio.Event().wait()
        finally:
            closed.set()
    catalog.unregister_owner('plugin:hook-demo')
    catalog.register('hook-demo.echo', lambda request: OperationResult(request.name, source()), owner='plugin:hook-demo')
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    delivered = False
    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {'type': 'http.request', 'body': json.dumps({'args': {'text': 'x'}}).encode(), 'more_body': False}
        await done.wait()
        return {'type': 'http.disconnect'}
    async def send(message):
        if message['type'] == 'http.response.body' and message.get('body'):
            messages.append(json.loads(message['body']))
            if len(messages) == 1:
                data = json.loads(spec_path.read_text(encoding='utf8'))
                data['operations'][0]['permission'] = 'hard_block'
                spec_path.write_text(json.dumps(data), encoding='utf8')
            if not message.get('more_body', False): done.set()
    scope = {'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST',
        'scheme':'http','path':'/plugin-remote/hook-demo/demo/echo','query_string':b'',
        'headers':[(b'content-type',b'application/json'),(b'x-plugin-token',plugin_http_token(host, 'hook-demo').encode())],
        'client':('127.0.0.1',123),'server':('test',80)}
    try:
        async with asyncio.timeout(3): await app(scope, receive, send)
        assert messages[0]['payload']['value'] == 'opened' and messages[-1]['kind'] == 'error'
        assert closed.is_set() and not host._remote_stream_slots
    finally:
        done.set()
