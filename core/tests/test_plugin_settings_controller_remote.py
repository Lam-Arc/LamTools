"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(设置Remote复用当前插件原脱敏投影，不输出敏感配置)。"""
import json

import httpx
import pytest
from fastapi import FastAPI

from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token


@pytest.mark.asyncio
async def test_original_redacted_settings_cross_explicit_http(tmp_path):
    host, catalog, original_context = _host(tmp_path)
    configure(host)
    path = host.get("hook-demo").root / "plugin.json"
    data = json.loads(path.read_text(encoding="utf8"))
    data["config"] = {"schema": "./settings-schema.json"}
    path.write_text(json.dumps(data), encoding="utf8")
    (path.parent / "settings-schema.json").write_text(json.dumps({"type": "object", "properties": {
        "secret": {"type": "string", "writeOnly": True}, "label": {"type": "string"}}}), encoding="utf8")
    (path.parent / "ops.py").write_text("def echo(request, *, context):\n    return context.settings.public()\n", encoding="utf8")
    host._invalidate()
    ctx = PluginContext(tmp_path, data_dir=tmp_path / "data", _secret_store=original_context._secret_store)
    ctx._begin_registration_scope("hook-demo", 1, manifest=host.get("hook-demo"))
    host.backend_manager.context = ctx
    snapshot = ctx.settings.read()
    ctx.settings.replace({"secret": "temporary-private-value", "label": "visible"}, expected_revision=snapshot.revision)
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            body = {"args": {"text": "settings"}}
            response = await client.post("/plugin-remote/hook-demo/demo/echo", json=body,
                headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
            denied = await client.post("/plugin-remote/hook-demo/demo/echo", json=body, headers={"x-plugin-token": "wrong"})
            ctx._registration_scope.revoke()
            stopped = await client.post("/plugin-remote/hook-demo/demo/echo", json=body,
                headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
        assert response.status_code == 200 and denied.status_code == 401
        assert response.json()["payload"]["values"] == {"secret": "<redacted>", "label": "visible"}
        assert "temporary-private-value" not in response.text
        assert stopped.status_code == 400 and "temporary-private-value" not in stopped.text
        assert "schema" not in response.json()["payload"]
    finally:
        await ctx._registration_scope.dispose()


def test_settings_handoff_only_recommends_public_projection(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.settings.describe(); }"})
    report = export_port(root, tmp_path / "ported")
    item = next(row for row in report["remotes"] if row["name"] == "settings.describe")
    assert item["suggestedContract"] == "context.settings.public"
    assert "脱敏" in item["difference"] and report["runtimeVerified"] is False
