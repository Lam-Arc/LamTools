"""user:“逐项核对固定上游源码及手册”+(市场分类过滤只使用原目录的实际分类)。"""
import pytest

from .test_plugin_market_readonly_remote import market_env


@pytest.mark.asyncio
async def test_category_filters_original_entries_before_pagination(market_env):
    ctx, _, _, _ = market_env
    page = await ctx.plugin_market.search("", category="消息与协作", limit=1)
    assert [row["id"] for row in page["items"]] == ["qq-bot"]
    assert page["total"] == 1 and page["next_offset"] is None and page["source"] == "github"
    assert (await ctx.plugin_market.search("", category="　消息与协作　"))["total"] == 1
    assert (await ctx.plugin_market.search("", category=None))["total"] == 2
    assert (await ctx.plugin_market.search("qq", category="内容与信息"))["items"] == []
    assert (await ctx.plugin_market.search("", category="不存在"))["items"] == []
    assert (await ctx.plugin_market.search("", category="消息与协作", offset=1))["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["", " ", 123, "x" * 201, "bad\x00name", "\ud800"])
async def test_invalid_category_does_not_call_original_provider(market_env, monkeypatch, category):
    ctx, _, catalog, _ = market_env
    async def forbidden(*args, **kwargs): pytest.fail("invalid category reached provider")
    monkeypatch.setattr(catalog, "execute", forbidden)
    with pytest.raises(ValueError): await ctx.plugin_market.search("", category=category)


@pytest.mark.asyncio
async def test_category_preserves_original_offline_status(market_env, monkeypatch):
    from lamtools_core.plugin_system import market
    ctx, _, _, _ = market_env
    def offline(*args, **kwargs): raise OSError("offline")
    monkeypatch.setattr(market, "get_json", offline)
    result = await ctx.plugin_market.search("", category="消息与协作")
    assert result["source"] == "unavailable" and result["error"]
    assert all(not row["installable"] for row in result["items"])


def test_category_migration_describes_localized_difference(tmp_path):
    from .test_dsh_compatibility import source
    from lamtools_core.plugin_system.dsh_compat import export_port
    root = source(tmp_path, {"index.ts": "export function apply(ctx) { ctx.remote.pluginMarket.search(); }"})
    export_port(root, tmp_path / "ported")
    assert "原目录分类名称" in (tmp_path / "ported" / "PORTING.md").read_text(encoding="utf8")


@pytest.mark.asyncio
async def test_category_through_authenticated_remote(market_env, tmp_path):
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
        "async def echo(request, *, context):\n"
        "    return await context.plugin_market.search('', category=request.payload['body']['text'])\n", encoding="utf8")
    catalog = OperationCatalog(); register_plugin_operations(catalog, host)
    app = FastAPI(); app.include_router(create_plugin_http_router(lambda: host, lambda: catalog))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = "/plugin-remote/hook-demo/demo/echo"; body = {"args": {"text": "消息与协作"}}
        denied = await client.post(url, json=body, headers={"x-plugin-token": "wrong"})
        response = await client.post(url, json=body, headers={"x-plugin-token": plugin_http_token(host, "hook-demo")})
    assert denied.status_code == 401 and response.status_code == 200
    assert [row["id"] for row in response.json()["payload"]["items"]] == ["qq-bot"]
    assert host.get("qq-bot") is None


@pytest.mark.asyncio
async def test_category_repeated_cancel_waits_for_original_catalog(market_env, monkeypatch):
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
    task = asyncio.create_task(ctx.plugin_market.search("", category="消息与协作"))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel(); await asyncio.sleep(0); task.cancel(); await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert finished.is_set()
    finally:
        release.set(); await asyncio.gather(task, return_exceptions=True)
