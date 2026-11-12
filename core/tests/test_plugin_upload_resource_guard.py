"""user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(原始上传在读内容前核对会话)。"""
import asyncio
import json
from pathlib import Path

import pytest
from .test_plugin_working_directory import env
from .test_plugin_raw_upload_stream import upload_env, request
from .test_plugin_workspace_registry_current import workspace_env
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import plugin_http_token


@pytest.fixture
async def guarded_upload(upload_env):
    ctx, host, app = upload_env
    await ctx._registration_scope.dispose()
    path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['http']['uploads'][0]['resource'] = 'session'
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    ctx._begin_registration_scope('hook-demo', 2, manifest=host.get('hook-demo'))
    (path.parent / 'ops.py').write_text(
        "async def echo(request, *, context):\n"
        "    b=request.payload['body']\n"
        "    saved=await context.file_uploads.save_chunks(b['resource_id'],filename='stream.bin',source=b['stream'],size=b['size'])\n"
        "    return {'id':saved['id']}\n", encoding='utf8')
    catalog = app.state.providers['catalog']
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog, host)
    return ctx, host, catalog, app


@pytest.mark.asyncio
async def test_scoped_upload_authenticates_and_checks_session_before_reading(guarded_upload):
    ctx, host, _, app = guarded_upload
    token = plugin_http_token(host, 'hook-demo')
    async def call(sid, auth=token):
        return await request(app, auth, 3, [{'type':'http.request', 'body':b'abc', 'more_body':False}],
                             extra_headers=[(b'x-resource-id', sid.encode())])
    denied, hidden, ok = await call('s', 'wrong'), await call('hidden'), await call('s')
    assert denied[0] == 401 and denied[2] == 0
    assert hidden[0] == 403 and hidden[2] == 0
    assert ok[0] == 200 and Path((await ctx.attachments.get('s', ok[1]['payload']['id']))['path']).read_bytes() == b'abc'
    assert not host._remote_stream_slots


@pytest.mark.asyncio
@pytest.mark.parametrize('value', [None, b'', b'x' * 257, b'\xff', b'a\x00b'])
async def test_scoped_upload_invalid_resource_rejected_without_read(guarded_upload, value):
    _, host, _, app = guarded_upload
    headers = [] if value is None else [(b'x-resource-id', value)]
    status, _, reads = await request(app, plugin_http_token(host, 'hook-demo'), 1,
        [{'type':'http.request','body':b'x','more_body':False}], extra_headers=headers)
    assert status == 400 and reads == 0


@pytest.mark.asyncio
async def test_duplicate_resource_header_is_rejected(guarded_upload):
    _, host, _, app = guarded_upload
    status, _, reads = await request(app, plugin_http_token(host, 'hook-demo'), 1,
        [{'type':'http.request','body':b'x','more_body':False}],
        extra_headers=[(b'x-resource-id', b's'), (b'x-resource-id', b'hidden')])
    assert status == 400 and reads == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('resource', [None, 'other', {'kind': 'session'}])
async def test_invalid_upload_resource_declaration_is_rejected(guarded_upload, resource):
    _, host, _, app = guarded_upload
    path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['http']['uploads'][0]['resource'] = resource
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    status, _, reads = await request(app, plugin_http_token(host, 'hook-demo'), 1,
        [{'type':'http.request','body':b'x','more_body':False}], extra_headers=[(b'x-resource-id', b's')])
    assert status == 400 and reads == 0


@pytest.mark.asyncio
async def test_upload_after_commit_rechecks_original_session(guarded_upload, monkeypatch):
    ctx, host, catalog, app = guarded_upload
    store = ctx.service('session_data')._store
    original = catalog.execute
    async def hide(*args, **kwargs):
        result = await original(*args, **kwargs)
        store._session_visible = lambda *_: False
        return result
    monkeypatch.setattr(catalog, 'execute', hide)
    status, payload, _ = await request(app, plugin_http_token(host, 'hook-demo'), 3,
        [{'type':'http.request','body':b'abc','more_body':False}], extra_headers=[(b'x-resource-id', b's')])
    assert status == 409 and payload['may_have_changed'] is True and 'id' not in payload
    assert not host._remote_stream_slots


@pytest.mark.asyncio
async def test_resource_revocation_during_chunk_wait_cancels_receive_without_saving(guarded_upload):
    ctx, host, _, app = guarded_upload
    store = ctx.service('session_data')._store
    waiting, receive_closed = asyncio.Event(), asyncio.Event()
    calls = 0; sent = []
    async def receive():
        nonlocal calls
        calls += 1
        if calls == 1:
            return {'type': 'http.request', 'body': b'a', 'more_body': True}
        waiting.set()
        try: await asyncio.Event().wait()
        finally: receive_closed.set()
    async def send(message): sent.append(message)
    token = plugin_http_token(host, 'hook-demo')
    scope = {'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/plugin-upload/hook-demo/files','query_string':b'',
        'headers':[(b'content-type',b'application/octet-stream'),(b'x-upload-size',b'2'),
                   (b'x-plugin-token',token.encode()),(b'x-resource-id',b's')],
        'client':('127.0.0.1',1),'server':('test',80)}
    task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(waiting.wait(), 3)
        store._session_visible = lambda *_: False
        await asyncio.wait_for(task, 3)
        assert receive_closed.is_set() and not host._remote_stream_slots
        assert next(frame['status'] for frame in sent if frame['type'] == 'http.response.start') == 409
        store._session_visible = lambda sid, _: sid != 'hidden'
        assert (await ctx.attachments.list('s'))['items'] == []
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_idle_upload_revocation_cancels_handler_and_joins_cleanup(guarded_upload, monkeypatch):
    ctx, host, catalog, app = guarded_upload
    store = ctx.service('session_data')._store
    entered, cleaning, release, closed = (asyncio.Event() for _ in range(4))
    from lamtools_core.app.operation_catalog import OperationResult
    async def handler(name, *args, **kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait(); closed.set()
        return OperationResult(name, {})
    monkeypatch.setattr(catalog, 'execute', handler)
    task = asyncio.create_task(request(app, plugin_http_token(host, 'hook-demo'), 1,
        [{'type':'http.request','body':b'x','more_body':False}], extra_headers=[(b'x-resource-id',b's')]))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        store._session_visible = lambda *_: False
        await asyncio.wait_for(cleaning.wait(), 3)
        assert not task.done() and not closed.is_set() and host._remote_stream_slots
        release.set()
        status, payload, _ = await task
        assert status == 409 and payload['may_have_changed'] is True and closed.is_set()
        assert not host._remote_stream_slots and ctx._registration_scope._idle.is_set()
    finally:
        release.set()
        if not task.done(): task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_unguarded_original_upload_still_works(upload_env):
    ctx, host, app = upload_env
    status, payload, _ = await request(app, plugin_http_token(host, 'hook-demo'), 3,
        [{'type':'http.request','body':b'abc','more_body':False}])
    assert status == 200 and Path((await ctx.attachments.get('s', payload['payload']['id']))['path']).read_bytes() == b'abc'


@pytest.mark.asyncio
async def test_workspace_upload_guard_uses_original_project_scope(workspace_env, tmp_path):
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router
    ctx, _, _, project, other = workspace_env
    await ctx._registration_scope.dispose()
    host, catalog, original = _host(tmp_path)
    path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['http']['uploads'] = [{'name': 'files', 'route': '/hook', 'resource': 'workspace'}]
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    ctx._secret_store = original._secret_store
    ctx._begin_registration_scope('hook-demo', 2, manifest=host.get('hook-demo'))
    host.backend_manager.context = ctx
    (path.parent / 'ops.py').write_text(
        "async def echo(request, *, context):\n"
        "    b=request.payload['body']\n"
        "    data=b''\n"
        "    async for part in b['stream']: data += part\n"
        "    return {'resource_id':b['resource_id'], 'length':len(data)}\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda:host, lambda:catalog))
    token = plugin_http_token(host, 'hook-demo')
    async def call(project_id):
        return await request(app, token, 3, [{'type':'http.request','body':b'abc','more_body':False}],
            extra_headers=[(b'x-resource-id', project_id.encode())])
    denied, ok = await call(other.id), await call(project.id)
    assert denied[0] == 403 and denied[2] == 0
    assert ok[0] == 200 and ok[1]['payload'] == {'resource_id': project.id, 'length': 3}


def test_upload_guard_migration_keeps_explicit_declaration(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {'index.ts': 'export function apply(ctx) { ctx.fileUpload.upload(); }'})
    output = tmp_path / 'ported'
    report = export_port(root, output)
    text = (output / 'PORTING.md').read_text(encoding='utf8')
    assert 'x-resource-id' in text and 'http.uploads' in text
    manifest = json.loads((output / 'plugin.json').read_text(encoding='utf8'))
    assert not manifest.get('http', {}).get('uploads') and report['runtimeVerified'] is False
