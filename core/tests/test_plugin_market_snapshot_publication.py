"""user:“建立真实请求、错误、作用域、取消/流和清理验收”+(失败或撤回不能发布或挤掉市场快照)。"""
import asyncio

import pytest

from .test_plugin_market_readonly_remote import market_env


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_failed_first_page_does_not_evict_existing_snapshots(market_env, monkeypatch, failure):
    ctx, _, _, _ = market_env
    api = ctx.plugin_market
    first = await api.search_snapshot("")
    for _ in range(15):
        await api.search_snapshot("")
    cache = ctx._registration_scope._market_search_snapshots
    before = list(cache)
    entered = asyncio.Event()

    async def failed_inventory(_binding):
        entered.set()
        if failure == "cancel":
            await asyncio.Event().wait()
        raise RuntimeError("inventory unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(api, "_installed_versions", failed_inventory)
        task = asyncio.create_task(api.search_snapshot(""))
        await entered.wait()
        if failure == "cancel":
            task.cancel()
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
            await task
    assert list(cache) == before
    assert (await api.search_snapshot("", snapshot=first["snapshot"]))["snapshot"] == first["snapshot"]


@pytest.mark.asyncio
async def test_evicted_snapshot_is_not_published_after_inventory_wait(market_env, monkeypatch):
    from lamtools_core.plugin_system.management_access import HostOperationError

    ctx, _, _, _ = market_env
    api = ctx.plugin_market
    first = await api.search_snapshot("")
    entered, release = asyncio.Event(), asyncio.Event()
    original = api._installed_versions

    async def delayed_inventory(binding):
        result = await original(binding)
        entered.set()
        await release.wait()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(api, "_installed_versions", delayed_inventory)
        pending = asyncio.create_task(api.search_snapshot("", snapshot=first["snapshot"]))
        try:
            await entered.wait()
            for _ in range(16):
                await ctx.plugin_market.search_snapshot("")
            release.set()
            with pytest.raises(HostOperationError) as error:
                await pending
            assert error.value.code == "market/invalid-snapshot"
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["expiry", "provider"])
async def test_snapshot_rechecks_expiry_and_market_provider_after_inventory(market_env, monkeypatch, change):
    from lamtools_core.plugin_system import market_access
    from lamtools_core.plugin_system.management_access import HostOperationError

    ctx, _, catalog, _ = market_env
    clock = [100.0]
    monkeypatch.setattr(market_access, "_now", lambda: clock[0])
    api = ctx.plugin_market
    first = await api.search_snapshot("")
    original = api._installed_versions

    async def change_during_inventory(binding):
        result = await original(binding)
        if change == "expiry":
            clock[0] += 121
        else:
            handler = catalog._handlers.pop("plugin.market.list")
            catalog.register("plugin.market.list", handler, owner="plugin-system")
        return result

    monkeypatch.setattr(api, "_installed_versions", change_during_inventory)
    with pytest.raises(HostOperationError) as error:
        await api.search_snapshot("", snapshot=first["snapshot"])
    assert error.value.code == ("market/invalid-snapshot" if change == "expiry" else "host/changed")


@pytest.mark.asyncio
async def test_failed_authenticated_request_preserves_existing_snapshot(market_env, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.market_access import PluginMarketAPI
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    from .test_plugin_remote_gateway import configure

    ctx, host, _, _ = market_env
    first = await ctx.plugin_market.search_snapshot("")
    for _ in range(15):
        await ctx.plugin_market.search_snapshot("")
    cache = ctx._registration_scope._market_search_snapshots
    before = list(cache)
    ctx._secret_store = host.backend_manager.context._secret_store
    host.backend_manager.context = ctx
    configure(host)
    (host.get("hook-demo").root / "ops.py").write_text(
        "async def echo(request, *, context):\n"
        "    return await context.plugin_market.search_snapshot('')\n", encoding="utf8")
    catalog = OperationCatalog()
    register_plugin_operations(catalog, host)
    app = FastAPI()
    app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))

    async def failed_inventory(_self, _binding):
        raise RuntimeError("inventory unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(PluginMarketAPI, "_installed_versions", failed_inventory)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/plugin-remote/hook-demo/demo/echo", json={"args": {"text": "x"}},
                headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
        assert response.status_code == 400
    assert list(cache) == before
    assert (await ctx.plugin_market.search_snapshot("", snapshot=first["snapshot"]))["snapshot"] == first["snapshot"]


def test_migration_explains_snapshot_publication_boundary(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port

    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.pluginMarket.search(); }"})
    export_port(root, tmp_path / "ported")
    handoff = (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")
    assert "安装状态刷新成功后才发布新快照" in handoff
    assert "过期或淘汰" in handoff
