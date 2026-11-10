"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(凭据批量描述只给当前插件的无密值状态)。"""
import pytest
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.secrets import PluginSecretStore


@pytest.fixture
async def credential_env(tmp_path):
    store = PluginSecretStore(tmp_path / "temporary-secrets")
    ctx = PluginContext(work_root=tmp_path, _secret_store=store)
    ctx._begin_registration_scope("alpha", 1)
    other = PluginContext(work_root=tmp_path, _secret_store=store)
    other._begin_registration_scope("beta", 1)
    try:
        yield ctx, other, store
    finally:
        await ctx._registration_scope.dispose()
        await other._registration_scope.dispose()


def test_batch_describe_uses_real_store_without_secret_values(credential_env, monkeypatch):
    ctx, other, store = credential_env
    ctx.credentials.set("API_KEY", "temporary-secret-value")
    other.credentials.set("OTHER_KEY", "other-temporary-secret")
    def forbid_get(*args, **kwargs): pytest.fail("description must not read secret values")
    monkeypatch.setattr(store, "get", forbid_get)
    result = ctx.credential_controller.describe(["API_KEY", "OTHER_KEY", "MISSING"])
    assert result["API_KEY"] == {"configured": True, "source": "plugin-store", "writable": True}
    assert not result["OTHER_KEY"]["configured"] and not result["MISSING"]["configured"]
    assert "temporary-secret" not in repr(result)


@pytest.mark.parametrize("refs", [None, "API_KEY", ["ok", "bad-name"], ["x"] * 65, ["a", 5]])
def test_invalid_batch_rejected_before_original_store(credential_env, monkeypatch, refs):
    ctx, _, store = credential_env
    def forbidden(*args, **kwargs): pytest.fail("invalid batch must not read original store")
    monkeypatch.setattr(store, "keys", forbidden)
    with pytest.raises(ValueError): ctx.credential_controller.describe(refs)


def test_bound_store_and_scope_are_rechecked(credential_env, tmp_path):
    ctx, _, _ = credential_env
    api = ctx.credential_controller
    ctx._secret_store = PluginSecretStore(tmp_path / "replacement")
    with pytest.raises(RuntimeError): api.describe(["API_KEY"])
    ctx._registration_scope.revoke()
    with pytest.raises(RuntimeError): api.describe(["API_KEY"])


def test_batch_reads_one_original_key_snapshot(credential_env, monkeypatch):
    ctx, _, store = credential_env
    ctx.credentials.set("ONE", "temporary-value")
    original = store.keys
    calls = []
    def observed(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(store, "keys", observed)
    result = ctx.credential_controller.describe(["ONE", "TWO", "THREE"])
    assert result["ONE"]["configured"] and not result["TWO"]["configured"]
    assert len(calls) == 1


def test_store_replaced_during_snapshot_cannot_publish_metadata(credential_env, monkeypatch, tmp_path):
    ctx, _, store = credential_env
    original = store.keys
    def swapped(*args, **kwargs):
        result = original(*args, **kwargs)
        ctx._secret_store = PluginSecretStore(tmp_path / "new-store")
        return result
    monkeypatch.setattr(store, "keys", swapped)
    with pytest.raises(RuntimeError): ctx.credential_controller.describe(["ONE"])


@pytest.mark.asyncio
async def test_credential_metadata_crosses_explicit_http_without_value(credential_env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, _, store = credential_env
    host, catalog, _ = _host(tmp_path)
    configure(host)
    host.backend_manager.context = ctx
    ctx.credentials.set("API_KEY", "temporary-secret-for-http")
    (host.get("hook-demo").root / "ops.py").write_text(
        "def echo(request, *, context):\n"
        "    return context.credential_controller.describe([request.payload['body']['text']])\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "API_KEY"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code == 200 and response.json()["payload"]["API_KEY"]["configured"]
    assert "temporary-secret-for-http" not in response.text


def test_migration_does_not_suggest_remote_secret_resolution(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.credentials.describe(); }"})
    report = export_port(root, tmp_path / "ported")
    item = next(row for row in report["remotes"] if row["name"] == "credentials.describe")
    assert item["suggestedContract"] == "context.credential_controller.describe"
    assert "不返回" in item["difference"] and report["runtimeVerified"] is False
