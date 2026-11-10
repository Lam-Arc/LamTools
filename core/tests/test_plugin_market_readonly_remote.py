"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(市场只读复用原来源及缓存，不调用安装)。"""
import asyncio
import threading

import pytest
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.plugin_system.context import PluginContext
from lamtools_core.plugin_system.market import register_market_operations
from .test_plugin_http_routes import _host


@pytest.fixture
async def market_env(tmp_path, monkeypatch):
    from lamtools_core.plugin_system import market
    host, _, _ = _host(tmp_path)
    catalog = OperationCatalog()
    register_market_operations(catalog, host)
    ctx = PluginContext(tmp_path, operation_catalog=catalog)
    ctx._begin_registration_scope("market-test", 1)
    release = {"assets": [{"name": "catalog.json", "url": "https://api.github.com/catalog"}]}
    data = {"format": 1, "plugins": [{"id": "qq-bot", "version": "1.2.3", "size": 123,
        "sha256": "a" * 64, "url": "https://github.com/Lam-Arc/Sunday-Plugins/releases/download/v1/qq.zip"}]}
    def fetch(url, **kwargs):
        return release if url.endswith("/releases/latest") else data
    monkeypatch.setattr(market, "get_json", fetch)
    try:
        yield ctx, host, catalog, data
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_original_market_operation_validates_catalog_and_reports_actual_availability(market_env):
    ctx, host, _, _ = market_env
    result = await ctx.plugin_market.list()
    items = {row["id"]: row for row in result["plugins"]}
    assert result["source"] == "github" and items["qq-bot"]["installable"]
    assert items["qq-bot"]["version"] == "1.2.3" and not items["bili-scroll"]["installable"]
    assert host.get("qq-bot") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cancel", "scope", "catalog"])
async def test_read_does_not_publish_old_state_and_joins_original_thread(market_env, monkeypatch, change):
    from lamtools_core.plugin_system import market
    ctx, _, _, data = market_env
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    def gated():
        entered.set()
        release.wait()
        try:
            return market.validate_catalog(data)
        finally:
            done.set()
    monkeypatch.setattr(market, "load_catalog", gated)
    api = ctx.plugin_market
    task = asyncio.create_task(api.list())
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        if change == "cancel":
            task.cancel()
            await asyncio.sleep(0.02)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        elif change == "scope": ctx._registration_scope.revoke()
        else: ctx.operation_catalog = OperationCatalog()
        release.set()
        if change == "cancel":
            with pytest.raises(asyncio.CancelledError): await task
        else:
            with pytest.raises(RuntimeError): await task
        assert done.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_missing_market_provider_is_error_not_fake_empty_success(tmp_path):
    ctx = PluginContext(tmp_path, operation_catalog=OperationCatalog())
    ctx._begin_registration_scope("market-test", 1)
    try:
        with pytest.raises(RuntimeError): await ctx.plugin_market.list()
    finally:
        await ctx._registration_scope.dispose()


@pytest.mark.asyncio
async def test_original_network_failure_is_reported_unavailable_not_installable(market_env, monkeypatch):
    from lamtools_core.plugin_system import market
    ctx, _, _, _ = market_env
    def offline(*args, **kwargs): raise OSError("temporary test offline")
    monkeypatch.setattr(market, "get_json", offline)
    result = await ctx.plugin_market.list()
    assert result["source"] == "unavailable" and result["error"]
    assert all(not row["installable"] for row in result["plugins"])


@pytest.mark.asyncio
async def test_actual_market_operation_crosses_explicit_http_without_install(market_env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_remote_gateway import configure
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, host, _, _ = market_env
    ctx._secret_store = host.backend_manager.context._secret_store
    host.backend_manager.context = ctx
    configure(host)
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n    return await context.plugin_market.list()\n", encoding="utf8")
    plugin_catalog = OperationCatalog()
    register_plugin_operations(plugin_catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: plugin_catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "list"}},
            headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert response.status_code == 200 and response.json()["payload"]["source"] == "github"
    assert host.get("qq-bot") is None


def test_market_migration_identifies_fixed_catalog_not_dynamic_indexes(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.pluginMarket.search(); }"})
    report = export_port(root, tmp_path / "ported")
    item = next(row for row in report["remotes"] if row["name"] == "pluginMarket.search")
    assert item["suggestedContract"] == "context.plugin_market.search"
    assert "固定" in item["difference"] and report["runtimeVerified"] is False
