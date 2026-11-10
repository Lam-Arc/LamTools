"""user:“完成真实接口、参数/错误、作用域、取消/清理”+(配置提交后发生错误时不能假报没有修改)。"""
import pytest
from .test_plugin_settings_controller_write import settings_env


@pytest.mark.asyncio
async def test_native_atomic_write_error_after_commit_reports_uncertainty(settings_env, monkeypatch):
    from lamtools_core.plugin_system import config_store
    ctx = settings_env
    api, before = ctx.settings_controller, ctx.settings_controller.describe()
    original = config_store._atomic_write
    def committed_then_error(path, payload):
        original(path, payload)
        raise OSError('private temporary detail')
    monkeypatch.setattr(config_store, '_atomic_write', committed_then_error)
    with pytest.raises(RuntimeError) as error:
        api.replace({'token': 'temporary-secret'}, expected_revision=before['revision'])
    assert error.value.code == 'settings/write-uncertain' and error.value.may_have_changed
    assert 'temporary-secret' not in str(error.value) and 'private temporary detail' not in str(error.value)
    assert ctx.config.read().values['token'] == 'temporary-secret'


@pytest.mark.asyncio
async def test_binding_replaced_after_commit_and_exception_reports_host_change(settings_env, monkeypatch):
    from lamtools_core.plugin_system.manifest import PluginManifest
    ctx = settings_env
    api, before = ctx.settings_controller, ctx.settings_controller.describe()
    original = api._settings.replace
    def committed_then_changed(*args, **kwargs):
        original(*args, **kwargs)
        ctx._plugin_manifest = PluginManifest('replacement', '1', root=ctx.work_root)
        raise RuntimeError('private temporary detail')
    monkeypatch.setattr(api._settings, 'replace', committed_then_changed)
    with pytest.raises(RuntimeError) as error:
        api.replace({'label': 'saved'}, expected_revision=before['revision'])
    assert error.value.code == 'settings/host-changed' and error.value.may_have_changed
    assert api._settings._config.read().values['label'] == 'saved'


@pytest.mark.asyncio
async def test_invalid_and_stale_revision_remain_known_nonwrites(settings_env):
    ctx = settings_env
    api, before = ctx.settings_controller, ctx.settings_controller.describe()
    with pytest.raises(RuntimeError) as invalid:
        api.replace({'label': 5}, expected_revision=before['revision'])
    assert invalid.value.code == 'settings/invalid-values' and not getattr(invalid.value, 'may_have_changed', False)
    api.replace({'label': 'winner'}, expected_revision=before['revision'])
    with pytest.raises(RuntimeError) as conflict:
        api.replace({'label': 'loser'}, expected_revision=before['revision'])
    assert conflict.value.code == 'config/conflict' and not getattr(conflict.value, 'may_have_changed', False)
    assert ctx.config.read().values['label'] == 'winner'


@pytest.mark.asyncio
@pytest.mark.parametrize('values', [{'label': float('nan')}, {'label': '\ud800'}], ids=['nonfinite', 'invalid-utf8'])
async def test_invalid_json_never_enters_native_write_or_reports_uncertain(settings_env, monkeypatch, values):
    api = settings_env.settings_controller
    before = api.describe()
    monkeypatch.setattr(api._settings._config, 'replace', lambda *a, **k: pytest.fail('invalid JSON entered write'))
    with pytest.raises(RuntimeError) as error:
        api.replace(values, expected_revision=before['revision'])
    assert not getattr(error.value, 'may_have_changed', False)


@pytest.mark.asyncio
async def test_binding_change_during_preflight_never_enters_write(settings_env, monkeypatch):
    from lamtools_core.plugin_system.manifest import PluginManifest
    ctx = settings_env
    api, before = ctx.settings_controller, ctx.settings_controller.describe()
    original = api._settings.validate
    def switched(values):
        result = original(values)
        ctx._plugin_manifest = PluginManifest('replacement', '1', root=ctx.work_root)
        return result
    monkeypatch.setattr(api._settings, 'validate', switched)
    monkeypatch.setattr(api._settings._config, 'replace', lambda *a, **k: pytest.fail('changed binding entered write'))
    with pytest.raises(RuntimeError): api.replace({'label': 'no-write'}, expected_revision=before['revision'])
    assert api._settings._config.read().values == {}


@pytest.mark.asyncio
async def test_http_write_failure_after_commit_does_not_leak_secret(tmp_path, monkeypatch):
    import json
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system import config_store
    from lamtools_core.plugin_system.context import PluginContext
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    host, catalog, original_context = _host(tmp_path)
    configure(host)
    manifest_path = host.get('hook-demo').root / 'plugin.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    manifest['config'] = {'schema': './schema.json'}
    manifest_path.write_text(json.dumps(manifest), encoding='utf8')
    (manifest_path.parent / 'schema.json').write_text(json.dumps({'type':'object','properties':{'token':{'type':'string','writeOnly':True}}}), encoding='utf8')
    (manifest_path.parent / 'ops.py').write_text(
        "def echo(request, *, context):\n    api = context.settings_controller\n    return api.replace({'token': request.payload['body']['text']}, expected_revision=api.describe()['revision'])\n", encoding='utf8')
    host._invalidate()
    ctx = PluginContext(tmp_path, data_dir=tmp_path / 'data', _secret_store=original_context._secret_store)
    ctx._begin_registration_scope('hook-demo', 1, manifest=host.get('hook-demo'))
    host.backend_manager.context = ctx
    catalog.unregister_owner('plugin:hook-demo')
    register_plugin_operations(catalog, host)
    token = plugin_http_token(host, 'hook-demo')
    original_write = config_store._atomic_write
    def committed_then_error(path, payload):
        original_write(path, payload)
        raise OSError('private temporary detail')
    monkeypatch.setattr(config_store, '_atomic_write', committed_then_error)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/plugin-remote/hook-demo/demo/echo', json={'args': {'text': 'temporary-http-secret'}},
                                         headers={'x-plugin-token': token})
        assert response.status_code == 400
        assert 'temporary-http-secret' not in response.text and 'private temporary detail' not in response.text
        assert ctx.config.read().values['token'] == 'temporary-http-secret'
    finally:
        await ctx._registration_scope.dispose()
