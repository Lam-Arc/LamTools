"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(读取当前会话的原托管图片)。"""
import asyncio
import base64
import io
from pathlib import Path

import pytest
from PIL import Image
from .test_plugin_working_directory import env
from lamtools_core.session import SessionRecord


def png_bytes():
    output = io.BytesIO()
    Image.new('RGB', (2, 2), (12, 34, 56)).save(output, format='PNG')
    return output.getvalue()


@pytest.mark.asyncio
async def test_reads_verified_native_managed_image(env):
    ctx, _, _, _ = env
    image = png_bytes()
    item = await ctx.attachments.create('s', filename='picture.png', content=image, mime_type='image/png')
    result = await ctx.session_controller.attachment('s', item['id'])
    assert result == {'id': item['id'], 'mime_type': 'image/png', 'data_base64': base64.b64encode(image).decode('ascii')}
    assert item['path'] not in str(result) and ctx._registration_scope._idle.is_set()


@pytest.mark.asyncio
async def test_foreign_and_hidden_sessions_cannot_read_attachment(env, tmp_path):
    ctx, store, _, _ = env
    other = tmp_path / 'other'; other.mkdir()
    await store.create(SessionRecord('other', 'core', 'Other', 'idle', metadata={'work_root': str(other)}))
    item = await ctx.attachments.create('s', filename='picture.png', content=png_bytes(), mime_type='image/png')
    for sid in ('hidden', 'other'):
        with pytest.raises(RuntimeError): await ctx.session_controller.attachment(sid, item['id'])


@pytest.mark.asyncio
async def test_corrupt_or_changed_file_is_not_published(env):
    ctx, _, _, _ = env
    item = await ctx.attachments.create('s', filename='picture.png', content=png_bytes(), mime_type='image/png')
    Path(item['path']).write_bytes(b'not an image')
    with pytest.raises(RuntimeError): await ctx.session_controller.attachment('s', item['id'])


@pytest.mark.asyncio
async def test_external_reference_is_not_read_as_managed_attachment(env):
    ctx, _, _, project = env
    (project / 'picture.png').write_bytes(png_bytes())
    item = await ctx.attachments.reference('s', 'picture.png')
    with pytest.raises(RuntimeError): await ctx.session_controller.attachment('s', item['id'])


@pytest.mark.asyncio
@pytest.mark.parametrize('attachment_id', ['', None, '\ud800', 'x' * 257])
async def test_invalid_attachment_identifier_is_rejected(env, monkeypatch, attachment_id):
    ctx, _, _, _ = env
    async def forbidden(*args, **kwargs): pytest.fail('invalid identifier reached attachment host')
    monkeypatch.setattr(ctx.service('session_data'), 'call', forbidden)
    with pytest.raises((ValueError, RuntimeError)):
        await ctx.session_controller.attachment('s', attachment_id)


@pytest.mark.asyncio
async def test_large_and_non_image_content_rejected(env):
    import os
    ctx, _, _, _ = env
    output = io.BytesIO()
    Image.frombytes('RGB', (512, 512), os.urandom(512 * 512 * 3)).save(output, format='PNG')
    assert len(output.getvalue()) > 512 * 1024
    large = await ctx.attachments.create('s', filename='large.png', content=output.getvalue(), mime_type='image/png')
    invalid = await ctx.attachments.create('s', filename='invalid.png', content=b'not a PNG', mime_type='image/png')
    for item in (large, invalid):
        with pytest.raises(RuntimeError): await ctx.session_controller.attachment('s', item['id'])


@pytest.mark.asyncio
async def test_scope_revocation_after_attachment_lookup_withholds_bytes(env, monkeypatch):
    ctx, _, _, _ = env
    item = await ctx.attachments.create('s', filename='picture.png', content=png_bytes(), mime_type='image/png')
    host = ctx.service('session_data')
    original = host.call
    entered, release = asyncio.Event(), asyncio.Event()
    async def gated(scope, root, kind, method, sid, **kwargs):
        value = await original(scope, root, kind, method, sid, **kwargs)
        if kind == 'attachments' and method == 'get': entered.set(); await release.wait()
        return value
    monkeypatch.setattr(host, 'call', gated)
    task = asyncio.create_task(ctx.session_controller.attachment('s', item['id']))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        ctx._registration_scope.revoke()
        release.set()
        with pytest.raises(RuntimeError): await task
        assert ctx._registration_scope._idle.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_session_hidden_after_content_read_withholds_bytes(env, monkeypatch):
    ctx, store, _, _ = env
    item = await ctx.attachments.create('s', filename='picture.png', content=png_bytes(), mime_type='image/png')
    host = ctx.service('session_data')
    original = host.call
    calls = 0
    async def hide(scope, root, kind, method, sid, **kwargs):
        nonlocal calls
        value = await original(scope, root, kind, method, sid, **kwargs)
        if kind == 'attachments' and method == 'get':
            calls += 1
            if calls == 2: store._session_visible = lambda *_: False
        return value
    monkeypatch.setattr(host, 'call', hide)
    with pytest.raises(RuntimeError): await ctx.session_controller.attachment('s', item['id'])
    assert ctx._registration_scope._idle.is_set()


@pytest.mark.asyncio
async def test_repeated_cancel_waits_for_original_lookup_cleanup(env, monkeypatch):
    ctx, _, _, _ = env
    item = await ctx.attachments.create('s', filename='picture.png', content=png_bytes(), mime_type='image/png')
    host = ctx.service('session_data')
    original = host.call
    entered, cleaning, release, closed = (asyncio.Event() for _ in range(4))
    async def gated(scope, root, kind, method, sid, **kwargs):
        if kind == 'attachments' and method == 'get':
            entered.set()
            try: await asyncio.Event().wait()
            finally: cleaning.set(); await release.wait(); closed.set()
        return await original(scope, root, kind, method, sid, **kwargs)
    monkeypatch.setattr(host, 'call', gated)
    task = asyncio.create_task(ctx.session_controller.attachment('s', item['id']))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), 3)
        task.cancel(); await asyncio.sleep(0)
        assert not task.done() and not ctx._registration_scope._idle.is_set()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert closed.is_set() and ctx._registration_scope._idle.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_image_attachment_through_explicit_remote(env, tmp_path):
    import os
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, _ = env
    output = io.BytesIO()
    Image.frombytes('RGB', (400, 400), os.urandom(400 * 400 * 3)).save(output, format='PNG')
    image = output.getvalue()
    assert 400 * 1024 < len(image) < 512 * 1024
    item = await ctx.attachments.create('s', filename='picture.png', content=image, mime_type='image/png')
    host, catalog, original = _host(tmp_path)
    configure(host)
    ctx._secret_store = original._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        'async def echo(request, *, context):\n'
        '    return await context.session_controller.attachment("s", request.payload["body"]["text"])\n', encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        url, body = '/plugin-remote/hook-demo/demo/echo', {'args': {'text': item['id']}}
        denied = await client.post(url, json=body, headers={'x-plugin-token': 'wrong'})
        good = await client.post(url, json=body, headers={'x-plugin-token': plugin_http_token(host, 'hook-demo')})
    assert denied.status_code == 401 and good.status_code == 200
    assert base64.b64decode(good.json()['payload']['data_base64']) == image
    assert item['path'] not in good.text


def test_image_attachment_migration_keeps_original_scope_difference(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {'index.ts': 'export function apply(ctx) { ctx.remote.session.attachment(); }'})
    report = export_port(root, tmp_path / 'ported')
    row = next(item for item in report['remotes'] if item['name'] == 'session.attachment')
    assert row['suggestedContract'] == 'context.session_controller.attachment'
    assert '托管' in row['difference'] and report['runtimeVerified'] is False
