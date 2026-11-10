"""user:“复用原宿主权威”+(附件完成写入后重新核对会话与宿主，不发布已撤回结果)。"""
import asyncio
from pathlib import Path
import pytest
from .test_plugin_session_data import env


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['hidden', 'host', 'root', 'scope'])
async def test_committed_upload_does_not_publish_after_binding_changes(env, monkeypatch, tmp_path, change):
    ctx, store, _, root = env
    host = ctx.require_service('session_data')
    original = host.call
    entered, release = asyncio.Event(), asyncio.Event()
    saved = []
    async def gated(scope, project, kind, method, session_id, **kwargs):
        result = await original(scope, project, kind, method, session_id, **kwargs)
        if kind == 'attachments' and method == 'create':
            saved.append(result)
            entered.set()
            await release.wait()
        return result
    monkeypatch.setattr(host, 'call', gated)
    task = asyncio.create_task(ctx.file_uploads.save_encoded('s', filename='committed.txt', content_base64='YQ=='))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if change == 'hidden': store._session_visible = lambda sid, _: sid != 's'
        elif change == 'host': ctx.set_service('session_data', object())
        elif change == 'root': ctx.work_root = tmp_path / 'other'
        else: ctx._registration_scope.revoke()
        release.set()
        with pytest.raises(ValueError) as error: await task
        assert error.value.may_have_changed is True
        assert error.value.code == ('file-upload/session-unavailable' if change == 'hidden' else 'file-upload/host-changed')
        assert Path(saved[0]['path']).read_bytes() == b'a'
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_unchanged_upload_preserves_original_attachment(env):
    ctx, _, _, _ = env
    saved = await ctx.file_uploads.save_encoded('s', filename='actual.txt', content_base64='YQ==')
    assert saved['session_id'] == 's' and (await ctx.attachments.get('s', saved['id']))['id'] == saved['id']


@pytest.mark.asyncio
async def test_cancellation_during_final_recheck_keeps_saved_attachment(env, monkeypatch):
    ctx, _, _, _ = env
    host = ctx.require_service('session_data')
    original = host.call
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(scope, project, kind, method, session_id, **kwargs):
        if kind == 'attachments' and method == 'get':
            entered.set()
            await release.wait()
        return await original(scope, project, kind, method, session_id, **kwargs)
    monkeypatch.setattr(host, 'call', gated)
    task = asyncio.create_task(ctx.file_uploads.save_encoded('s', filename='saved-before-cancel.txt', content_base64='YQ=='))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert not ctx._registration_scope._calls
        assert any(row['filename'] == 'saved-before-cancel.txt' for row in (await ctx.attachments.list('s'))['items'])
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_committed_upload_hidden_before_return_is_not_exposed_over_http(env, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, store, _, _ = env
    native = ctx.require_service('session_data')
    original_call = native.call
    entered, release = asyncio.Event(), asyncio.Event()
    saved = []
    async def gated(scope, project, kind, method, session_id, **kwargs):
        result = await original_call(scope, project, kind, method, session_id, **kwargs)
        if kind == 'attachments' and method == 'create':
            saved.append(result)
            entered.set()
            await release.wait()
        return result
    monkeypatch.setattr(native, 'call', gated)
    host, catalog, previous = _host(tmp_path)
    configure(host)
    ctx._secret_store = previous._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        "async def echo(request, *, context):\n    return await context.file_uploads.save_encoded('s', filename='private.txt', content_base64='YQ==')\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            task = asyncio.create_task(client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'x'}},
                headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')}))
            await asyncio.wait_for(entered.wait(), 3)
            store._session_visible = lambda sid, _: sid != 's'
            release.set()
            response = await asyncio.wait_for(task, 3)
        assert response.status_code == 400 and saved[0]['id'] not in response.text
        assert Path(saved[0]['path']).read_bytes() == b'a'
    finally:
        release.set()
