"""user:“完成真实接口、参数/错误、作用域、取消/清理”+(凭据写入可能提交后失败时禁止假报未修改)。"""
import pytest
from .test_plugin_credential_controller import credential_env
from lamtools_core.plugin_system.secrets import SecretStoreError


@pytest.mark.parametrize('action', ['set', 'unset'])
def test_original_store_failure_after_real_commit_reports_uncertain_without_secret(credential_env, monkeypatch, action):
    ctx, _, store = credential_env
    secret = 'temporary-only-secret'
    if action == 'unset': ctx.credentials.set('KEY', secret)
    method = 'set' if action == 'set' else 'delete'
    original = getattr(store, method)
    def committed_then_error(*args, **kwargs):
        original(*args, **kwargs)
        raise SecretStoreError('must-not-leak ' + secret, code='credentials/io')
    monkeypatch.setattr(store, method, committed_then_error)
    with pytest.raises(RuntimeError) as error:
        if action == 'set': ctx.credential_controller.set('KEY', secret)
        else: ctx.credential_controller.unset('KEY')
    assert error.value.code == 'credentials/write-uncertain' and error.value.may_have_changed
    assert secret not in str(error.value) and secret not in repr(error.value)
    assert bool(store.get('alpha', 'KEY')) == (action == 'set')


@pytest.mark.parametrize('ref,value,code', [('BAD-NAME', 'value', 'credentials/invalid-ref'),
                                            ('GOOD', '', 'credentials/invalid-value')])
def test_original_validation_error_is_not_reported_as_write_uncertain(credential_env, monkeypatch, ref, value, code):
    ctx, _, store = credential_env
    monkeypatch.setattr(store, 'set', lambda *a, **k: pytest.fail('invalid input reached store'))
    with pytest.raises(RuntimeError) as error: ctx.credential_controller.set(ref, value)
    assert error.value.code == code and not getattr(error.value, 'may_have_changed', False)


@pytest.mark.parametrize('action', ['set', 'unset'])
def test_binding_change_and_exception_after_commit_reports_host_changed(credential_env, tmp_path, monkeypatch, action):
    from lamtools_core.plugin_system.secrets import PluginSecretStore
    ctx, _, store = credential_env
    secret = 'temporary-test-only'
    if action == 'unset': ctx.credentials.set('KEY', secret)
    method = 'set' if action == 'set' else 'delete'
    original = getattr(store, method)
    def committed_then_replaced(*args, **kwargs):
        original(*args, **kwargs)
        ctx._secret_store = PluginSecretStore(tmp_path / 'replacement')
        raise RuntimeError(secret)
    monkeypatch.setattr(store, method, committed_then_replaced)
    with pytest.raises(RuntimeError) as error:
        if action == 'set': ctx.credential_controller.set('KEY', secret)
        else: ctx.credential_controller.unset('KEY')
    assert error.value.code == 'credentials/host-changed' and error.value.may_have_changed
    assert secret not in str(error.value) and bool(store.get('alpha', 'KEY')) == (action == 'set')


@pytest.mark.asyncio
async def test_uncertain_write_http_does_not_echo_temporary_secret(credential_env, monkeypatch, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.context import PluginContext
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    _, _, store = credential_env
    host, catalog, _ = _host(tmp_path)
    configure(host)
    ctx = PluginContext(tmp_path, _secret_store=store)
    ctx._begin_registration_scope('hook-demo', 1, manifest=host.get('hook-demo'))
    host.backend_manager.context = ctx
    (host.get('hook-demo').root / 'ops.py').write_text(
        "def echo(request, *, context):\n    context.credential_controller.set('KEY', request.payload['body']['text'])\n    return {'saved': True}\n", encoding='utf8')
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    token = plugin_http_token(host, 'hook-demo')
    original = store.set
    secret = 'temporary-http-test-secret'
    def fail_after(*args, **kwargs):
        original(*args, **kwargs)
        raise SecretStoreError('private ' + secret, code='credentials/io')
    monkeypatch.setattr(store, 'set', fail_after)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': secret}},
                                         headers={'x-plugin-token': token})
        assert response.status_code == 400 and secret not in response.text
        assert store.get('hook-demo', 'KEY') == secret
    finally:
        await ctx._registration_scope.dispose()
