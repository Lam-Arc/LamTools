"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(远程方法清单必须来自当前实际声明及原操作归属)。"""
import json

import pytest
from .test_plugin_http_routes import _host
from .test_plugin_remote_gateway import configure
from lamtools_core.plugin_system.context import PluginContext


@pytest.fixture
async def remote_env(tmp_path):
    host, catalog, original = _host(tmp_path)
    configure(host)
    catalog.plugin_system_host = host
    ctx = PluginContext(tmp_path, operation_catalog=catalog, _secret_store=original._secret_store)
    ctx._begin_registration_scope("hook-demo", 1, manifest=host.get("hook-demo"))
    try:
        yield ctx, host, catalog
    finally:
        await ctx._registration_scope.dispose()


def test_inventory_uses_live_method_declaration_and_original_owner(remote_env):
    ctx, host, catalog = remote_env
    api = ctx.remote_access
    result = api.declared_methods()
    assert result == {"methods": [{"namespace": "demo", "method": "echo", "result_encoding": "json"}]}
    configure(host, remove=True)
    assert api.declared_methods() == {"methods": []}


@pytest.mark.parametrize("change", ["foreign-owner", "approval", "unmounted"])
def test_unusable_methods_are_not_listed(remote_env, change):
    ctx, host, catalog = remote_env
    if change == "foreign-owner":
        catalog.unregister_owner("plugin:hook-demo")
        catalog.register("hook-demo.echo", lambda request: None, owner="another-plugin")
    elif change == "unmounted":
        catalog.unregister_owner("plugin:hook-demo")
    else:
        path = host.get("hook-demo").root / "plugin.json"
        data = json.loads(path.read_text(encoding="utf8"))
        data["operations"][0]["permission"] = "ask_user"
        path.write_text(json.dumps(data), encoding="utf8")
        host._invalidate()
    assert ctx.remote_access.declared_methods() == {"methods": []}


@pytest.mark.parametrize("change", ["host", "catalog", "scope", "disabled"])
def test_inventory_rejects_stale_or_disabled_host(remote_env, change):
    ctx, host, catalog = remote_env
    api = ctx.remote_access
    if change == "host": catalog.plugin_system_host = object()
    elif change == "catalog": ctx.operation_catalog = type(catalog)()
    elif change == "scope": ctx._registration_scope.revoke()
    else: host.disable("hook-demo")
    with pytest.raises(RuntimeError): api.declared_methods()


def test_missing_host_is_error_not_fake_empty_policy(tmp_path):
    from lamtools_core.app.operation_catalog import OperationCatalog
    ctx = PluginContext(tmp_path, operation_catalog=OperationCatalog())
    ctx._begin_registration_scope("missing", 1)
    try:
        with pytest.raises(RuntimeError): ctx.remote_access.declared_methods()
    finally:
        ctx._registration_scope.revoke()


def test_invalid_manifest_is_rejected_not_advertised(remote_env):
    ctx, host, _ = remote_env
    configure(host, bad_schema=True)
    with pytest.raises(RuntimeError) as error:
        ctx.remote_access.declared_methods()
    assert error.value.code == "host/invalid-declaration"


def test_inventory_does_not_publish_withdrawn_declaration(remote_env, monkeypatch):
    from lamtools_core.plugin_system import remote_access
    ctx, host, _ = remote_env
    original = remote_access.read_operations
    def changed(manifest):
        result = original(manifest)
        configure(host, remove=True)
        return result
    monkeypatch.setattr(remote_access, "read_operations", changed)
    with pytest.raises(RuntimeError): ctx.remote_access.declared_methods()


@pytest.mark.asyncio
async def test_inventory_crosses_original_plugin_http_without_tokens(remote_env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, host, catalog = remote_env
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "def echo(request, *, context):\n    return context.remote_access.declared_methods()\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        token = plugin_http_token(host, "hook-demo")
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "list"}},
            headers={"x-plugin-token": token})
    assert response.status_code == 200
    assert response.json()["payload"]["methods"][0]["method"] == "echo"
    assert token not in response.text


def test_migration_describes_inventory_not_dsh_peer_policy(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remoteAccess.follow(); }"})
    report = export_port(root, tmp_path / "ported")
    item = next(row for row in report["services"] if row["name"] == "remoteAccess")
    assert item["candidateContract"] == "context.remote_access.declared_methods"
    assert "Peer" in item["difference"] and report["runtimeVerified"] is False
