"""user:“第二阶段结束后 就继续开展第三阶段”+(只描述真实配置结构，不公开值或伪装完整schema)。"""
import json

import pytest

from .test_plugin_settings_controller_write import settings_env


@pytest.mark.asyncio
async def test_outline_uses_actual_schema_without_default_example_or_values(settings_env):
    ctx = settings_env
    path = ctx._plugin_manifest.root / "schema.json"
    path.write_text(json.dumps({"type": "object", "required": ["token"], "properties": {
        "token": {"type": "string", "writeOnly": True, "default": "private-default", "examples": ["private-example"]},
        "nested": {"type": "object", "properties": {"count": {"type": "integer", "enum": [111, 222]}}},
        "list": {"type": "array", "items": {"type": "string"}},
        "choice": {"$ref": "#/$defs/choice"}}, "$defs": {"choice": {"type": "string"}}}), encoding="utf8")
    result = ctx.settings_controller.schema_outline()
    assert result["partial"] is True and result["revision"] == ctx.settings_controller.describe()["revision"]
    fields = result["schema"]["properties"]
    assert fields["token"]["secret_hint"] is True and "token" in result["schema"]["required"]
    assert fields["nested"]["properties"]["count"]["type"] == "integer"
    assert fields["list"]["items"]["type"] == "string" and fields["choice"]["has_reference"] is True
    assert all(value not in repr(result) for value in ("private-default", "private-example", "111", "222"))


@pytest.mark.asyncio
async def test_outline_detects_revoked_scope_after_original_read(settings_env, monkeypatch):
    ctx = settings_env; api = ctx.settings_controller; original = api._settings.read
    def revoke():
        value = original(); ctx._registration_scope.revoke(); return value
    monkeypatch.setattr(api._settings, "read", revoke)
    with pytest.raises(RuntimeError): api.schema_outline()


def test_migration_describes_partial_schema_outline(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.settings.describe(); }"})
    export_port(root, tmp_path / "ported")
    assert "schema_outline" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")


@pytest.mark.asyncio
async def test_outline_limit_rejects_large_schema_without_values(settings_env):
    ctx = settings_env
    path = ctx._plugin_manifest.root / "schema.json"
    path.write_text(json.dumps({"type": "object", "properties": {f"field_{i}": {"type": "string"} for i in range(1025)}}), encoding="utf8")
    with pytest.raises(RuntimeError) as error: ctx.settings_controller.schema_outline()
    assert error.value.code == "settings/schema-limit"


@pytest.mark.asyncio
async def test_outline_through_authenticated_http(tmp_path):
    import httpx
    from fastapi import FastAPI
    from lamtools_core.plugin_system.context import PluginContext
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    host, catalog, old = _host(tmp_path); configure(host)
    path = host.get("hook-demo").root / "plugin.json"
    manifest = json.loads(path.read_text(encoding="utf8")); manifest["config"] = {"schema": "./schema.json"}
    path.write_text(json.dumps(manifest), encoding="utf8")
    (path.parent / "schema.json").write_text(json.dumps({"type": "object", "properties": {
        "token": {"type": "string", "writeOnly": True, "default": "private-example"}}}), encoding="utf8")
    (path.parent / "ops.py").write_text("def echo(request, *, context):\n    return context.settings_controller.schema_outline()\n", encoding="utf8")
    host._invalidate()
    ctx = PluginContext(tmp_path, data_dir=tmp_path / "data", _secret_store=old._secret_store)
    ctx._begin_registration_scope("hook-demo", 1, manifest=host.get("hook-demo")); host.backend_manager.context = ctx
    catalog.unregister_owner("plugin:hook-demo"); register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            url = "/plugin-remote/hook-demo/demo/echo"; body = {"args": {"text": "x"}}
            denied = await client.post(url, json=body, headers={"x-plugin-token": "wrong"})
            response = await client.post(url, json=body, headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
        assert denied.status_code == 401 and response.status_code == 200
        assert response.json()["payload"]["schema"]["properties"]["token"]["secret_hint"] is True
        assert "private-example" not in response.text
    finally:
        await ctx._registration_scope.dispose()
