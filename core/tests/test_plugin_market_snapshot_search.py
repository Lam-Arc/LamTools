"""user:“逐项核对固定上游源码及手册”+(固定目录分页保留真实首次读取快照)。"""
import pytest

from .test_plugin_market_readonly_remote import market_env


@pytest.mark.asyncio
async def test_snapshot_pages_keep_actual_initial_catalog_and_are_defensive(market_env, monkeypatch):
    from lamtools_core.plugin_system import market
    ctx, _, _, data = market_env
    first = await ctx.plugin_market.search_snapshot("", limit=1)
    assert first["total"] == 2 and first["next_offset"] == 1 and first["source"] == "github"
    first["items"][0]["title"] = "tampered"
    data["plugins"][0]["version"] = "9.9.9"
    monkeypatch.setattr(market, "load_catalog", lambda: pytest.fail("snapshot should not refetch"))
    again = await ctx.plugin_market.search_snapshot("", limit=1, snapshot=first["snapshot"])
    later = await ctx.plugin_market.search_snapshot("", offset=1, limit=1, snapshot=first["snapshot"])
    assert again["items"][0]["title"] != "tampered" and again["items"][0]["version"] == "1.2.3"
    assert later["items"][0]["id"] != again["items"][0]["id"] and later["next_offset"] is None


@pytest.mark.asyncio
async def test_snapshot_binds_query_and_category(market_env):
    ctx, _, _, _ = market_env
    first = await ctx.plugin_market.search_snapshot("qq", category="消息与协作")
    for text, category in [("other", "消息与协作"), ("qq", None)]:
        with pytest.raises(RuntimeError):
            await ctx.plugin_market.search_snapshot(text, category=category, snapshot=first["snapshot"])


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["scope", "operation", "owner"])
async def test_snapshot_rejects_changed_provider_or_scope(market_env, change):
    ctx, _, catalog, _ = market_env
    api = ctx.plugin_market; first = await api.search_snapshot("")
    if change == "scope": ctx._registration_scope.revoke()
    else:
        operation = "plugin.market.list"
        handler = catalog._handlers.pop(operation)
        catalog.register(operation, handler, owner="plugin-system" if change == "operation" else "other")
    with pytest.raises(RuntimeError): await api.search_snapshot("", snapshot=first["snapshot"])


@pytest.mark.asyncio
async def test_expired_snapshot_is_not_silent_fresh_fetch(market_env, monkeypatch):
    from lamtools_core.plugin_system import market_access
    ctx, _, _, _ = market_env
    clock = [100.0]; monkeypatch.setattr(market_access, "_now", lambda: clock[0])
    first = await ctx.plugin_market.search_snapshot("")
    clock[0] += 121
    with pytest.raises(RuntimeError): await ctx.plugin_market.search_snapshot("", snapshot=first["snapshot"])


def test_snapshot_migration_names_capture_limit(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.pluginMarket.search(); }"})
    export_port(root, tmp_path / "ported")
    assert "search_snapshot" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")


@pytest.mark.asyncio
async def test_snapshot_disposal_clears_original_scope_cache(market_env):
    ctx, _, _, _ = market_env
    first = await ctx.plugin_market.search_snapshot("")
    cache = ctx._registration_scope._market_search_snapshots
    assert first["snapshot"] in cache
    await ctx._registration_scope.dispose()
    assert not cache


@pytest.mark.asyncio
async def test_snapshot_cache_is_bounded_and_eviction_is_explicit(market_env):
    ctx, _, _, _ = market_env
    first = await ctx.plugin_market.search_snapshot("")
    for _ in range(16): await ctx.plugin_market.search_snapshot("")
    assert len(ctx._registration_scope._market_search_snapshots) == 16
    with pytest.raises(RuntimeError) as error:
        await ctx.plugin_market.search_snapshot("", snapshot=first["snapshot"])
    assert error.value.code == "market/invalid-snapshot"


@pytest.mark.asyncio
async def test_snapshot_repeated_cancel_waits_for_original_catalog(market_env, monkeypatch):
    import asyncio
    import threading
    from lamtools_core.plugin_system import market
    ctx, _, _, data = market_env
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def gated():
        entered.set(); release.wait()
        try: return market.validate_catalog(data)
        finally: finished.set()
    monkeypatch.setattr(market, "load_catalog", gated)
    task = asyncio.create_task(ctx.plugin_market.search_snapshot(""))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel(); await asyncio.sleep(0); task.cancel(); await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert finished.is_set() and not ctx._registration_scope._market_search_snapshots
    finally:
        release.set(); await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_snapshot_pages_cross_authenticated_http(market_env, tmp_path):
    import httpx
    from fastapi import FastAPI
    from .test_plugin_remote_gateway import configure
    from lamtools_core.app.operation_catalog import OperationCatalog
    from lamtools_core.plugin_system.operation_bridge import register_plugin_operations
    from lamtools_core.plugin_system.plugin_http import create_plugin_http_router, plugin_http_token
    ctx, host, _, _ = market_env
    ctx._secret_store = host.backend_manager.context._secret_store; host.backend_manager.context = ctx
    configure(host)
    (host.get("hook-demo").root / "ops.py").write_text(
        "import json\nasync def echo(request, *, context):\n"
        "    args = json.loads(request.payload['body']['text'])\n"
        "    return await context.plugin_market.search_snapshot('', limit=1, offset=args.get('offset', 0), snapshot=args.get('snapshot'))\n", encoding="utf8")
    catalog = OperationCatalog(); register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        import json
        url = "/plugin-remote/hook-demo/demo/echo"
        async def call(value, token):
            return await client.post(url, json={"args": {"text": json.dumps(value)}}, headers={"x-plugin-token": token})
        assert (await call({}, "wrong")).status_code == 401
        first = await call({}, plugin_http_token(host, "hook-demo"))
        second = await call({"snapshot": first.json()["payload"]["snapshot"], "offset": 1}, plugin_http_token(host, "hook-demo"))
    assert first.status_code == second.status_code == 200
    assert first.json()["payload"]["items"][0]["id"] != second.json()["payload"]["items"][0]["id"]
    assert host.get("qq-bot") is None
