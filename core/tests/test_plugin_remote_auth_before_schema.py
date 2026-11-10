"""user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(先认证再公开方法或参数校验结果)。"""
import httpx
import pytest
from fastapi import FastAPI
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['known', 'unknown', 'invalid-body', 'invalid-declaration'])
async def test_unauthenticated_remote_cannot_probe_method_or_schema(tmp_path, case):
    host, catalog, _ = _host(tmp_path)
    configure(host, bad_schema=case == 'invalid-declaration')
    token = plugin_http_token(host, 'hook-demo')
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    endpoint = '/plugin-remote/hook-demo/demo/' + ('unknown' if case == 'unknown' else 'echo')
    body = {'args': {}} if case == 'invalid-body' else {'args': {'text': 'ok'}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        denied = await client.post(endpoint, json=body, headers={'x-plugin-token': 'invalid'})
        valid = await client.post(endpoint, json=body, headers={'x-plugin-token': token})
    assert denied.status_code == 401 and denied.json() == {'error': 'invalid plugin token'}
    assert valid.status_code == {'known': 200, 'unknown': 404, 'invalid-body': 400, 'invalid-declaration': 400}[case]


@pytest.mark.asyncio
async def test_unprovisioned_remote_does_not_create_credential_for_request(tmp_path):
    host, catalog, context = _host(tmp_path)
    configure(host)
    view = context._secret_store.view('hook-demo')
    assert not view.get('httpToken')
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'x'}},
                                     headers={'x-plugin-token': 'invalid'})
    assert response.status_code == 401 and not view.get('httpToken')


@pytest.mark.asyncio
@pytest.mark.parametrize('encoding', ['json', 'ndjson'])
async def test_revocation_between_gateway_and_route_does_not_regenerate_token(tmp_path, monkeypatch, encoding):
    from .test_plugin_remote_binary import set_encoding
    from lamtools_core.plugin_system import remote_gateway
    host, catalog, context = _host(tmp_path)
    configure(host)
    if encoding == 'ndjson': set_encoding(host, encoding)
    token = plugin_http_token(host, 'hook-demo')
    view = context._secret_store.view('hook-demo')
    original = remote_gateway.read_remote_methods
    def revoked_after_read(manifest):
        result = original(manifest)
        view.delete('httpToken')
        return result
    monkeypatch.setattr(remote_gateway, 'read_remote_methods', revoked_after_read)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'x'}},
                                     headers={'x-plugin-token': token})
    assert response.status_code == 401 and not view.get('httpToken')
    assert not getattr(host, '_remote_stream_slots', {})


@pytest.mark.asyncio
@pytest.mark.parametrize('body,headers', [
    (b'{bad-json', {'content-type': 'application/json'}),
    (b'{}', {'content-type': 'application/json', 'content-length': '1048577'}),
])
async def test_unauthenticated_remote_is_rejected_before_body_read(tmp_path, body, headers):
    host, catalog, context = _host(tmp_path)
    configure(host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/plugin-remote/hook-demo/demo/echo', content=body,
                                     headers={**headers, 'x-plugin-token': 'invalid'})
    assert response.status_code == 401
    assert not context._secret_store.view('hook-demo').get('httpToken')


@pytest.mark.asyncio
async def test_remote_revoked_while_body_arrives_never_dispatches_or_recreates_token(tmp_path, monkeypatch):
    import asyncio
    import json
    host, catalog, context = _host(tmp_path)
    configure(host)
    token = plugin_http_token(host, 'hook-demo')
    entered, release, messages = asyncio.Event(), asyncio.Event(), []
    async def forbidden(*args, **kwargs): pytest.fail('revoked request must not dispatch')
    monkeypatch.setattr(catalog, 'execute', forbidden)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async def receive():
        entered.set()
        await release.wait()
        return {'type': 'http.request', 'body': json.dumps({'args': {'text': 'x'}}).encode(), 'more_body': False}
    async def send(message): messages.append(message)
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST',
        'scheme': 'http', 'path': '/plugin-remote/hook-demo/demo/echo', 'query_string': b'',
        'headers': [(b'content-type', b'application/json'), (b'x-plugin-token', token.encode())],
        'client': ('127.0.0.1', 123), 'server': ('test', 80)}
    task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        context._secret_store.view('hook-demo').delete('httpToken')
        release.set()
        await asyncio.wait_for(task, 2)
        assert next(m['status'] for m in messages if m['type'] == 'http.response.start') == 401
        assert not context._secret_store.view('hook-demo').get('httpToken')
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_unauthenticated_asgi_request_does_not_pull_body(tmp_path):
    host, catalog, _ = _host(tmp_path)
    configure(host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    messages = []
    async def receive(): pytest.fail('unauthenticated request body must not be pulled')
    async def send(message): messages.append(message)
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST',
        'scheme': 'http', 'path': '/plugin-remote/hook-demo/demo/echo', 'query_string': b'',
        'headers': [(b'content-type', b'application/json'), (b'x-plugin-token', b'invalid')],
        'client': ('127.0.0.1', 123), 'server': ('test', 80)}
    await app(scope, receive, send)
    assert next(m['status'] for m in messages if m['type'] == 'http.response.start') == 401
