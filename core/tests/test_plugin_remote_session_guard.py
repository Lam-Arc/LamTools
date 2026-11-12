"""user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(显式会话资源复用原可见性)。"""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from .test_plugin_working_directory import env
from .test_plugin_workspace_registry_current import workspace_env
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
from lamtools_core.session import SessionRecord


@pytest.fixture
async def guarded(env, tmp_path):
    ctx, store, _, root = env
    await ctx._registration_scope.dispose()
    host, catalog, original = _host(tmp_path)
    configure(host)
    path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['http']['remote'][0]['resource'] = {'kind': 'session', 'argument': 'text'}
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    ctx._secret_store = original._secret_store
    ctx._begin_registration_scope('hook-demo', 2, manifest=host.get('hook-demo'))
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        'def echo(request, *, context):\n    return {"called": request.payload["body"]["text"]}\n', encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    yield ctx, store, root, host, catalog, app


@pytest.mark.asyncio
async def test_explicit_session_guard_checks_real_scope_before_dispatch(guarded, tmp_path, monkeypatch):
    ctx, store, _, host, catalog, app = guarded
    other = tmp_path / 'other'; other.mkdir()
    await store.create(SessionRecord('foreign', 'core', 'Foreign', 'idle', metadata={'work_root': str(other)}))
    original = catalog.execute; calls = []
    async def track(*args, **kwargs): calls.append(args[0]); return await original(*args, **kwargs)
    monkeypatch.setattr(catalog, 'execute', track)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        url = '/plugin-remote/hook-demo/demo/echo'
        async def call(sid, token):
            return await client.post(url, json={'args': {'text': sid}}, headers={'x-plugin-token': token})
        token = plugin_http_token(host, 'hook-demo')
        unauth = await call('s', 'wrong')
        hidden = await call('hidden', token)
        foreign = await call('foreign', token)
        missing = await call('missing', token)
        allowed = await call('s', token)
    assert unauth.status_code == 401 and hidden.status_code == foreign.status_code == missing.status_code == 403
    assert allowed.status_code == 200 and allowed.json()['payload']['called'] == 's'
    assert calls == ['hook-demo.echo'] and ctx._registration_scope._idle.is_set()


@pytest.mark.asyncio
async def test_guard_rechecks_session_after_original_operation(guarded, monkeypatch):
    _, store, _, host, catalog, app = guarded
    original = catalog.execute
    async def hide(*args, **kwargs):
        result = await original(*args, **kwargs)
        store._session_visible = lambda *_: False
        return result
    monkeypatch.setattr(catalog, 'execute', hide)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        result = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 's'}},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert result.status_code == 409 and result.json()['may_have_changed'] is True
    assert 'called' not in result.text


@pytest.mark.asyncio
async def test_guard_keeps_original_session_when_handler_mutates_payload(guarded, monkeypatch):
    _, store, root, host, catalog, app = guarded
    await store.create(SessionRecord('s2', 'core', 'Second', 'idle', metadata={'work_root': str(root)}))
    original = catalog.execute
    async def changed(name, payload, **kwargs):
        result = await original(name, payload, **kwargs)
        payload['body']['text'] = 's2'
        store._session_visible = lambda sid, _: sid != 's'
        return result
    monkeypatch.setattr(catalog, 'execute', changed)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        result = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 's'}},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert result.status_code == 409 and 'called' not in result.text


@pytest.mark.asyncio
@pytest.mark.parametrize('resource,encoding', [({'kind': 'other', 'argument': 'text'}, 'json'),
    ({'kind': 'session', 'argument': 'missing'}, 'json'),
    ({'kind': 'session', 'argument': 'text', 'extra': True}, 'json'), (None, 'json')])
async def test_invalid_resource_declarations_fail_closed(guarded, resource, encoding):
    _, _, _, host, _, app = guarded
    path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['http']['remote'][0]['resource'] = resource
    manifest['http']['remote'][0]['resultEncoding'] = encoding
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        result = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 's'}},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert result.status_code == 400


@pytest.mark.asyncio
async def test_missing_scoped_host_fails_closed(guarded):
    ctx, _, _, host, _, app = guarded
    ctx._registration_scope.revoke()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        result = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 's'}},
            headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert result.status_code == 403


@pytest.mark.asyncio
async def test_repeated_session_guards_do_not_accumulate_scope_dependencies(guarded):
    ctx, _, _, host, _, app = guarded
    scope = ctx._registration_scope
    initial = len(scope.dependencies)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        url = '/plugin-remote/hook-demo/demo/echo'; headers = {'x-plugin-token': plugin_http_token(host, 'hook-demo')}
        for _ in range(20):
            result = await client.post(url, json={'args': {'text': 's'}}, headers=headers)
            assert result.status_code == 200
    assert len(scope.dependencies) <= initial + 1


@pytest.mark.asyncio
async def test_guard_cancellation_waits_native_admission_cleanup(guarded, monkeypatch):
    ctx, _, _, host, catalog, _ = guarded
    from lamtools_core.plugin_system.remote_gateway import dispatch_remote_request
    directory = ctx.service('working_directory')
    original = directory.call
    entered, cleaning, release, closed = (asyncio.Event() for _ in range(4))
    async def gated(*args, **kwargs):
        entered.set()
        try: await asyncio.Event().wait()
        finally: cleaning.set(); await release.wait(); closed.set()
        return await original(*args, **kwargs)
    monkeypatch.setattr(directory, 'call', gated)
    token = plugin_http_token(host, 'hook-demo')
    task = asyncio.create_task(dispatch_remote_request(host=host, catalog=catalog, plugin='hook-demo',
        namespace='demo', method='echo', body={'args': {'text': 's'}}, headers={'x-plugin-token': token}))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel(); await asyncio.wait_for(cleaning.wait(), 3); task.cancel(); await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert closed.is_set() and ctx._registration_scope._idle.is_set()
    finally:
        release.set(); await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_guard_binds_validated_argument_across_wait(guarded, monkeypatch):
    from lamtools_core.plugin_system.remote_gateway import dispatch_remote_request
    from lamtools_core.plugin_system.session_controller import PluginSessionController
    _, _, _, host, catalog, _ = guarded
    entered, release = asyncio.Event(), asyncio.Event()
    original_admit = PluginSessionController._admit
    calls = 0
    async def gated(self, sid):
        nonlocal calls
        result = await original_admit(self, sid)
        calls += 1
        if calls == 1: entered.set(); await release.wait()
        return result
    monkeypatch.setattr(PluginSessionController, '_admit', gated)
    body = {'args': {'text': 's'}}
    task = asyncio.create_task(dispatch_remote_request(host=host, catalog=catalog, plugin='hook-demo',
        namespace='demo', method='echo', body=body, headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')}))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        body['args']['text'] = 'hidden'
        release.set()
        status, result = await task
        assert status == 200 and result.value['payload']['called'] == 's'
    finally:
        release.set(); await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancel_during_final_guard_closes_unexpected_result_stream(guarded, monkeypatch):
    from lamtools_core.plugin_system.remote_gateway import dispatch_remote_request
    from lamtools_core.plugin_system.session_controller import PluginSessionController
    from lamtools_core.app.operation_catalog import OperationResult
    _, _, _, host, catalog, _ = guarded
    entered, closed = asyncio.Event(), asyncio.Event()
    calls = 0
    original_admit = PluginSessionController._admit
    async def gated(self, session_id):
        nonlocal calls
        calls += 1
        if calls == 2: entered.set(); await asyncio.Event().wait()
        return await original_admit(self, session_id)
    monkeypatch.setattr(PluginSessionController, '_admit', gated)
    async def source():
        try: yield {'value': 1}
        finally: closed.set()
    stream = source(); await anext(stream)
    async def handler(name, *args, **kwargs): return OperationResult(name, stream)
    monkeypatch.setattr(catalog, 'execute', handler)
    task = asyncio.create_task(dispatch_remote_request(host=host, catalog=catalog, plugin='hook-demo',
        namespace='demo', method='echo', body={'args': {'text': 's'}},
        headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')}))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert closed.is_set()
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await stream.aclose()


def test_guard_migration_reports_explicit_scope_not_peer_policy(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {'index.ts': 'export function apply(ctx) { ctx.remote.session.state(); }'})
    output = tmp_path / 'ported'
    report = export_port(root, output)
    contract = report['sundayHostContracts']['remoteGateway']
    assert contract['version'] == 9
    text = (output / 'PORTING.md').read_text(encoding='utf8')
    assert 'resource' in text and 'Peer' in text
    assert report['runtimeVerified'] is False


@pytest.mark.asyncio
async def test_workspace_resource_uses_native_project_authority(workspace_env, tmp_path, monkeypatch):
    ctx, db, _, project, other = workspace_env
    await ctx._registration_scope.dispose()
    host, catalog, original = _host(tmp_path); configure(host)
    path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['http']['remote'][0]['resource'] = {'kind': 'workspace', 'argument': 'text'}
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    ctx._secret_store = original._secret_store
    ctx._begin_registration_scope('hook-demo', 2, manifest=host.get('hook-demo'))
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        'def echo(request, *, context):\n    return {"called": request.payload["body"]["text"]}\n', encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        url = '/plugin-remote/hook-demo/demo/echo'; token = plugin_http_token(host, 'hook-demo')
        async def call(project_id):
            return await client.post(url, json={'args': {'text': project_id}}, headers={'x-plugin-token': token})
        foreign = await call(other.id); missing = await call('missing'); allowed = await call(project.id)
        original_execute = catalog.execute
        async def delete_after(*args, **kwargs):
            result = await original_execute(*args, **kwargs)
            await db.project_store.delete_with_sessions(project.id)
            return result
        monkeypatch.setattr(catalog, 'execute', delete_after)
        withdrawn = await call(project.id)
    assert foreign.status_code == missing.status_code == 403
    assert allowed.status_code == 200 and allowed.json()['payload']['called'] == project.id
    assert withdrawn.status_code == 409 and withdrawn.json()['may_have_changed'] is True and 'called' not in withdrawn.text


@pytest.mark.asyncio
async def test_resource_guard_uses_real_managed_plugin_context(env, tmp_path):
    ctx, _, _, _ = env
    await ctx._registration_scope.dispose()
    host, catalog, original = _host(tmp_path); configure(host)
    path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['backend'] = './backend.py'
    manifest['http']['remote'][0]['resource'] = {'kind': 'session', 'argument': 'text'}
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    (path.parent / 'backend.py').write_text('class Runtime:\n    async def start(self, context): pass\n    async def stop(self): pass\ndef create_plugin(context): return Runtime()\n', encoding='utf8')
    (path.parent / 'ops.py').write_text('def echo(request, *, context):\n    return {"called": request.payload["body"]["text"]}\n', encoding='utf8')
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog, host)
    assert await host.backend_manager.start('hook-demo')
    handle = host.backend_manager.get('hook-demo')
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda:host, lambda:catalog))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            url = '/plugin-remote/hook-demo/demo/echo'; headers = {'x-plugin-token': plugin_http_token(host, 'hook-demo')}
            good = await client.post(url, json={'args': {'text': 's'}}, headers=headers)
            denied = await client.post(url, json={'args': {'text': 'hidden'}}, headers=headers)
        assert good.status_code == 200 and denied.status_code == 403
        assert handle.context._registration_scope._idle.is_set() and host.backend_manager._active['hook-demo'] == 0
    finally:
        await host.backend_manager.stop('hook-demo')
    assert handle.context._registration_scope.disposed


@pytest.mark.asyncio
async def test_guarded_multipart_returns_actual_bytes_only_for_admitted_session(guarded):
    from .test_plugin_remote_binary import decode_parts
    from lamtools_core.app.operation_catalog import OperationResult
    _, _, _, host, catalog, app = guarded
    path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(path.read_text(encoding='utf8'))
    manifest['http']['remote'][0]['resultEncoding'] = 'multipart'
    path.write_text(json.dumps(manifest), encoding='utf8'); host._invalidate()
    catalog.unregister_owner('plugin:hook-demo')
    catalog.register('hook-demo.echo', lambda request: OperationResult(request.name, {'data': b'actual-bytes'}), owner='plugin:hook-demo')
    token = plugin_http_token(host, 'hook-demo')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        url = '/plugin-remote/hook-demo/demo/echo'
        hidden = await client.post(url, json={'args': {'text': 'hidden'}}, headers={'x-plugin-token': token})
        good = await client.post(url, json={'args': {'text': 's'}}, headers={'x-plugin-token': token})
    assert hidden.status_code == 403 and b'actual-bytes' not in hidden.content
    assert good.status_code == 200
    metadata, parts = decode_parts(good)
    assert parts[metadata['attachments'][0]['part']] == b'actual-bytes'
