"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(设置写入返回原脱敏投影而非含秘密的原始保存对象)。"""
import json

import httpx
import pytest
from fastapi import FastAPI

from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.manifest import PluginManifest
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure


@pytest.fixture
async def settings_env(tmp_path):
    root = tmp_path / "plugin"
    root.mkdir()
    (root / "schema.json").write_text(json.dumps({"type": "object", "additionalProperties": False,
        "properties": {"token": {"type": "string", "writeOnly": True}, "label": {"type": "string"}}}), encoding="utf8")
    manifest = PluginManifest("settings-test", "1", root=root, raw={"config": {"schema": "./schema.json"}})
    ctx = PluginContext(root, data_dir=tmp_path / "data")
    ctx._begin_registration_scope("settings-test", 1, manifest=manifest)
    try:
        yield ctx
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_replace_returns_redacted_projection_and_preserves_conflict(settings_env):
    ctx = settings_env
    api = ctx.settings_controller
    before = api.describe()
    result = api.replace({"token": "temporary-settings-secret", "label": "visible"}, expected_revision=before["revision"])
    assert result["values"] == {"token": "<redacted>", "label": "visible"}
    assert "temporary-settings-secret" not in repr(result)
    assert ctx.config.read().values["token"] == "temporary-settings-secret"
    with pytest.raises(RuntimeError): api.replace({"token": "other"}, expected_revision=before["revision"])
    assert ctx.config.read().values["token"] == "temporary-settings-secret"


@pytest.mark.asyncio
async def test_invalid_values_and_revocation_do_not_write(settings_env):
    ctx = settings_env
    api = ctx.settings_controller
    before = api.describe()
    with pytest.raises(RuntimeError): api.replace({"label": 5}, expected_revision=before["revision"])
    assert api.describe()["revision"] == before["revision"]
    ctx._registration_scope.revoke()
    with pytest.raises(RuntimeError): api.replace({"label": "late"}, expected_revision=before["revision"])


@pytest.mark.asyncio
async def test_committed_settings_followed_by_manifest_replacement_reports_uncertain(settings_env, monkeypatch):
    ctx = settings_env
    api = ctx.settings_controller
    before = api.describe()
    original = api._settings.replace
    def swapped(*args, **kwargs):
        value = original(*args, **kwargs)
        ctx._plugin_manifest = PluginManifest("replacement", "1", root=ctx.work_root)
        return value
    monkeypatch.setattr(api._settings, "replace", swapped)
    with pytest.raises(RuntimeError) as error:
        api.replace({"token": "temporary-settings-secret"}, expected_revision=before["revision"])
    assert error.value.code == "settings/host-changed" and error.value.may_have_changed
    assert api._settings._config.read().values["token"] == "temporary-settings-secret"


@pytest.mark.asyncio
async def test_committed_settings_projection_failure_reports_distinct_uncertain_error(settings_env, monkeypatch):
    ctx = settings_env
    api = ctx.settings_controller
    before = api.describe()
    def failed_projection(): raise OSError("temporary-private-detail")
    monkeypatch.setattr(api._settings, "public", failed_projection)
    with pytest.raises(RuntimeError) as error:
        api.replace({"token": "temporary-settings-secret"}, expected_revision=before["revision"])
    assert error.value.code == "settings/post-commit-unavailable" and error.value.may_have_changed
    assert "temporary-private-detail" not in str(error.value)
    assert api._settings._config.read().values["token"] == "temporary-settings-secret"


@pytest.mark.asyncio
async def test_projection_does_not_publish_a_later_concurrent_configuration(settings_env, monkeypatch):
    api = settings_env.settings_controller
    before = api.describe()
    original = api._settings.public
    def concurrent_write():
        current = api._settings.read()
        api._settings.replace({"label": "later-writer"}, expected_revision=current.revision)
        return original()
    monkeypatch.setattr(api._settings, "public", concurrent_write)
    with pytest.raises(RuntimeError) as error:
        api.replace({"token": "temporary-settings-secret"}, expected_revision=before["revision"])
    assert error.value.code == "settings/post-commit-changed" and error.value.may_have_changed


@pytest.mark.asyncio
async def test_actual_http_settings_write_returns_only_redacted_values(tmp_path):
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    host, catalog, original = _host(tmp_path)
    configure(host)
    path = host.get("hook-demo").root / "plugin.json"
    data = json.loads(path.read_text(encoding="utf8"))
    data["config"] = {"schema": "./schema.json"}
    path.write_text(json.dumps(data), encoding="utf8")
    (path.parent / "schema.json").write_text(json.dumps({"type": "object", "properties": {"token": {"type": "string", "writeOnly": True}}}), encoding="utf8")
    (path.parent / "ops.py").write_text(
        "def echo(request, *, context):\n"
        "    api = context.settings_controller\n"
        "    return api.replace({'token': request.payload['body']['text']}, expected_revision=api.describe()['revision'])\n", encoding="utf8")
    host._invalidate()
    ctx = PluginContext(tmp_path, data_dir=tmp_path / "data", _secret_store=original._secret_store)
    ctx._begin_registration_scope("hook-demo", 1, manifest=host.get("hook-demo"))
    host.backend_manager.context = ctx
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "temporary-http-secret"}},
                headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
        assert response.status_code == 200 and response.json()["payload"]["values"]["token"] == "<redacted>"
        assert "temporary-http-secret" not in response.text
        assert ctx.config.read().values["token"] == "temporary-http-secret"
    finally:
        await ctx._registration_scope.dispose()


def test_migration_does_not_suggest_raw_settings_save_result(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.settings.replace(); }"})
    report = export_port(root, tmp_path / "ported")
    item = next(row for row in report["remotes"] if row["name"] == "settings.replace")
    assert item["suggestedContract"] == "context.settings_controller.replace"
    assert "脱敏" in item["difference"] and report["runtimeVerified"] is False
