"""user:“完成真实接口、参数/错误、作用域、取消/清理”+(附件保存抛错不假定已写文件和索引被回滚)。"""
import pytest
from .test_plugin_session_data import env

@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['io', 'lookup'])
async def test_attachment_committed_then_error_reports_uncertain(env, monkeypatch, failure):
    ctx, _, _, _ = env
    host = ctx.require_service('session_data')
    original = host.call
    async def committed_then_failed(*args, **kwargs):
        result = await original(*args, **kwargs)
        if args[3] == 'create':
            if failure == 'lookup':
                from lamtools_core.plugin_system.session_data import SessionDataError
                raise SessionDataError('session-data/not-found', 'private detail')
            raise OSError('private detail')
        return result
    monkeypatch.setattr(host, 'call', committed_then_failed)
    with pytest.raises(Exception) as error:
        await ctx.file_uploads.save_encoded('s', filename='uncertain.txt', content_base64='YQ==')
    assert error.value.code == 'file-upload/write-uncertain'
    assert error.value.may_have_changed and 'private detail' not in str(error.value)
    assert any(x['filename'] == 'uncertain.txt' for x in (await ctx.attachments.list('s'))['items'])

@pytest.mark.asyncio
async def test_invalid_filename_is_known_prewrite(env, monkeypatch):
    ctx, _, _, _ = env
    async def forbidden(*args, **kwargs): pytest.fail('invalid filename reached host')
    monkeypatch.setattr(ctx.require_service('session_data'), 'call', forbidden)
    with pytest.raises(RuntimeError) as error:
        await ctx.file_uploads.save_encoded('s', filename='', content_base64='YQ==')
    assert not getattr(error.value, 'may_have_changed', False)

@pytest.mark.asyncio
async def test_uncertain_error_http_does_not_expose_internal_details(env, tmp_path, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, _, _ = env
    host, catalog, original_context = _host(tmp_path)
    configure(host)
    ctx._secret_store = original_context._secret_store
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        "async def echo(request, *, context):\n    return await context.file_uploads.save_encoded('s', filename='private.txt', content_base64=request.payload['body']['text'])\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo'); register_plugin_operations(catalog, host)
    native = ctx.require_service('session_data'); original = native.call
    async def failed_after(*args, **kwargs):
        result = await original(*args, **kwargs)
        if args[3] == 'create': raise OSError('sensitive-internal-error')
        return result
    monkeypatch.setattr(native, 'call', failed_after)
    app=FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response=await client.post('/plugin-remote/hook-demo/demo/echo', json={'args':{'text':'YQ=='}}, headers={'x-plugin-token':plugin_http_token(host,'hook-demo')})
    assert response.status_code != 200 and 'sensitive-internal-error' not in response.text
    assert any(x['filename'] == 'private.txt' for x in (await ctx.attachments.list('s'))['items'])
