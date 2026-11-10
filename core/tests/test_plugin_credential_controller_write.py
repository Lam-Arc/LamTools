"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(仅当前插件的凭据写入且不在响应返回密值)。"""
import pytest

from .test_plugin_credential_controller import credential_env
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.secrets import PluginSecretStore


def test_write_and_unset_reuse_original_private_owner_store(credential_env):
    ctx, other, _ = credential_env
    assert ctx.credential_controller.set("API_KEY", "temporary-test-secret") is None
    assert ctx.credentials.resolve("API_KEY").value == "temporary-test-secret"
    assert not other.credential_controller.describe(["API_KEY"])["API_KEY"]["configured"]
    assert other.credential_controller.unset("API_KEY") is None
    assert ctx.credentials.describe("API_KEY").configured
    assert ctx.credential_controller.unset("API_KEY") is None
    assert not ctx.credentials.describe("API_KEY").configured


@pytest.mark.parametrize("ref,value", [("BAD-NAME", "x"), ("GOOD", ""), ("GOOD", "   "), ("GOOD", "x" * 65537)],
    ids=["bad-ref", "empty", "blank", "oversize"])
def test_invalid_credentials_rejected_before_original_write(credential_env, monkeypatch, ref, value):
    ctx, _, store = credential_env
    def forbidden(*args, **kwargs): pytest.fail("invalid credential must not write")
    monkeypatch.setattr(store, "set", forbidden)
    with pytest.raises(RuntimeError): ctx.credential_controller.set(ref, value)


@pytest.mark.parametrize("action", ["set", "unset"])
def test_completed_write_then_host_change_reports_may_have_changed(credential_env, tmp_path, monkeypatch, action):
    ctx, _, store = credential_env
    if action == "unset": ctx.credentials.set("KEY", "temporary-test-secret")
    original = getattr(store, "set" if action == "set" else "delete")
    def swapped(*args, **kwargs):
        original(*args, **kwargs)
        ctx._secret_store = PluginSecretStore(tmp_path / "replacement-store")
    monkeypatch.setattr(store, "set" if action == "set" else "delete", swapped)
    with pytest.raises(RuntimeError) as error:
        if action == "set": ctx.credential_controller.set("KEY", "temporary-test-secret")
        else: ctx.credential_controller.unset("KEY")
    assert error.value.code == "credentials/host-changed" and error.value.may_have_changed
    assert bool(store.get("alpha", "KEY")) == (action == "set")


def test_revoked_scope_rejects_credential_write_before_store(credential_env, monkeypatch):
    ctx, _, store = credential_env
    api = ctx.credential_controller
    def forbidden(*args, **kwargs): pytest.fail("revoked scope must not write")
    monkeypatch.setattr(store, "set", forbidden)
    ctx._registration_scope.revoke()
    with pytest.raises(RuntimeError): api.set("KEY", "temporary-test-secret")


@pytest.mark.asyncio
async def test_write_http_never_returns_secret_and_rejects_bad_token(credential_env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_http_routes import _host
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    _, _, store = credential_env
    host, catalog, _ = _host(tmp_path)
    configure(host)
    ctx = PluginContext(tmp_path, _secret_store=store)
    ctx._begin_registration_scope("hook-demo", 1, manifest=host.get("hook-demo"))
    host.backend_manager.context = ctx
    (host.get("hook-demo").root / "ops.py").write_text(
        "def echo(request, *, context):\n"
        "    context.credential_controller.set('KEY', request.payload['body']['text'])\n"
        "    return {'saved': True}\n", encoding="utf8")
    catalog.unregister_owner("plugin:hook-demo")
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    secret = "temporary-http-secret"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            body = {"args": {"text": secret}}
            denied = await client.post("/plugin-remote/hook-demo/demo/echo", json=body, headers={"x-plugin-token": "bad"})
            assert denied.status_code == 401 and not ctx.credentials.describe("KEY").configured
            response = await client.post("/plugin-remote/hook-demo/demo/echo", json=body,
                headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
        assert response.status_code == 200 and secret not in response.text
        assert ctx.credentials.describe("KEY").configured
    finally:
        await ctx._registration_scope.dispose()


def test_migration_describes_one_way_credential_write(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.credentials.set(); ctx.remote.credentials.unset(); }"})
    report = export_port(root, tmp_path / "ported")
    items = {row["name"]: row for row in report["remotes"]}
    assert items["credentials.set"]["suggestedContract"] == "context.credential_controller.set"
    assert items["credentials.unset"]["suggestedContract"] == "context.credential_controller.unset"
    assert "不返回" in items["credentials.set"]["difference"] and report["runtimeVerified"] is False
