"""user:“逐项核对固定上游源码及手册”+(目录结果保持快照，安装事实按原宿主每页刷新)。"""
import json

import pytest

from .test_plugin_market_readonly_remote import market_env


@pytest.mark.asyncio
async def test_snapshot_page_keeps_catalog_and_refreshes_native_installation(market_env, monkeypatch):
    from lamtools_core.plugin_system import market

    ctx, host, _, data = market_env
    data["plugins"].append({"id": "bili-scroll", "version": "2.0.0", "size": 123,
        "sha256": "b" * 64,
        "url": "https://github.com/Lam-Arc/Sunday-Plugins/releases/download/v2/bili.zip"})
    first = await ctx.plugin_market.search_snapshot("", limit=1)
    assert first["items"][0]["id"] == "qq-bot"

    plugin_root = host.get("hook-demo").root.parent / "bili-scroll"
    plugin_root.mkdir()
    (plugin_root / "plugin.json").write_text(json.dumps({"name": "bili-scroll", "version": "1.0.0"}), encoding="utf8")

    def no_catalog_refetch():
        pytest.fail("later snapshot pages must not reread the market catalog")

    monkeypatch.setattr(market, "load_catalog", no_catalog_refetch)
    later = await ctx.plugin_market.search_snapshot("", offset=1, limit=1, snapshot=first["snapshot"])
    item = later["items"][0]
    assert item["id"] == "bili-scroll" and item["version"] == "2.0.0"
    assert item["installed_version"] == "1.0.0" and item["update_available"] is True
    assert later["total"] == first["total"] and later["source"] == first["source"]


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", ["missing", "foreign-owner", "same-owner"])
async def test_snapshot_fails_closed_when_native_installation_provider_changes(market_env, replacement):
    from lamtools_core.app.operation_catalog import OperationResult
    from lamtools_core.plugin_system.management_access import HostOperationError

    ctx, _, catalog, _ = market_env
    first = await ctx.plugin_market.search_snapshot("")
    name = "plugin.system.list"
    original = catalog._handlers.pop(name)
    catalog._owners.pop(name, None)
    catalog._binding_tokens.pop(name, None)
    catalog._availability.pop(name, None)
    if replacement == "foreign-owner":
        catalog.register(name, lambda request: OperationResult(request.name, {"plugins": []}), owner="other")
    elif replacement == "same-owner":
        catalog.register(name, original, owner="plugin-system")

    with pytest.raises(HostOperationError) as error:
        await ctx.plugin_market.search_snapshot("", snapshot=first["snapshot"])
    assert error.value.code == ("host/changed" if replacement == "same-owner" else "host/unavailable")
