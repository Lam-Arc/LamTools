"""user:“复用原宿主权威”+(当前插件恢复原默认值仍须版本检查和脱敏)。"""
import json

import pytest

from .test_plugin_settings_controller_write import settings_env


@pytest.mark.asyncio
async def test_reset_uses_original_defaults_and_redacts(settings_env):
    ctx = settings_env; api = ctx.settings_controller
    (ctx._plugin_manifest.root / "schema.json").write_text(json.dumps({"type": "object", "properties": {
        "token": {"type": "string", "writeOnly": True, "default": "temporary-default-secret"},
        "label": {"type": "string", "default": "default-label"}}}), encoding="utf8")
    before = api.replace({"token": "temporary-old-secret", "label": "changed"}, expected_revision=api.describe()["revision"])
    result = api.reset(expected_revision=before["revision"])
    assert result["values"] == {"token": "<redacted>", "label": "default-label"}
    assert "temporary-default-secret" not in repr(result) and "temporary-old-secret" not in repr(result)
    assert ctx.settings.read().values == {"token": "temporary-default-secret", "label": "default-label"}
    with pytest.raises(RuntimeError): api.reset(expected_revision=before["revision"])


@pytest.mark.asyncio
async def test_reset_respects_real_schema_validation(settings_env):
    ctx = settings_env; api = ctx.settings_controller
    (ctx._plugin_manifest.root / "schema.json").write_text(json.dumps({"type": "object", "required": ["label"],
        "properties": {"label": {"type": "string"}}}), encoding="utf8")
    before = api.replace({"label": "retained"}, expected_revision=api.describe()["revision"])
    with pytest.raises(RuntimeError): api.reset(expected_revision=before["revision"])
    assert ctx.settings.read().values == {"label": "retained"}


@pytest.mark.asyncio
async def test_reset_revocation_before_write_does_not_change_config(settings_env, monkeypatch):
    ctx = settings_env; api = ctx.settings_controller; before = api.describe(); original = api._settings.read
    from pathlib import Path
    target = Path(original().path)
    old_bytes = target.read_bytes() if target.exists() else None
    def revoke():
        result = original(); ctx._registration_scope.revoke(); return result
    monkeypatch.setattr(api._settings, "read", revoke)
    with pytest.raises(RuntimeError): api.reset(expected_revision=before["revision"])
    assert (target.read_bytes() if target.exists() else None) == old_bytes


def test_reset_handoff_is_manual_and_scoped(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.settings.mutate(); }"})
    export_port(root, tmp_path / "ported")
    assert "settings_controller.reset" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")


@pytest.mark.asyncio
async def test_reset_reports_uncertain_after_committed_storage_failure(settings_env, monkeypatch):
    api = settings_env.settings_controller
    before = api.replace({"label": "changed"}, expected_revision=api.describe()["revision"])
    original = api._settings.replace
    def fail_after(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("private-error")
    monkeypatch.setattr(api._settings, "replace", fail_after)
    with pytest.raises(RuntimeError) as error: api.reset(expected_revision=before["revision"])
    assert error.value.code == "settings/write-uncertain" and error.value.may_have_changed
    assert "private-error" not in str(error.value)
    assert api._settings.read().values == {}


@pytest.mark.asyncio
async def test_reset_through_explicit_authenticated_remote(settings_env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx = settings_env; api = ctx.settings_controller
    api.replace({"token": "temporary-secret", "label": "changed"}, expected_revision=api.describe()["revision"])
    host, catalog, old = _host(tmp_path); configure(host)
    ctx._secret_store = old._secret_store; host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "def echo(request, *, context):\n"
        "    api = context.settings_controller\n"
        "    return api.reset(expected_revision=api.describe()['revision'])\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo"); register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = "/plugin-remote/hook-demo/demo/echo"; body = {"args": {"text": "x"}}
        denied = await client.post(url, json=body, headers={"x-plugin-token": "wrong"})
        assert denied.status_code == 401 and api._settings.read().values["token"] == "temporary-secret"
        response = await client.post(url, json=body, headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code == 200 and response.json()["payload"]["values"] == {}
    assert "temporary-secret" not in response.text
