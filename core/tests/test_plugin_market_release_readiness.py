"""user:“注意一下插件市场，如果没有或者没做好的话给它做好”+(验收离线、缓存和版本保护)。"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lamtools_core.plugin_system import market, management


def catalog(version="0.1.1"):
    return {"format": 1, "plugins": [{
        "id": "qq-bot", "version": version, "sha256": "a" * 64, "size": 200,
        "url": f"https://github.com/Lam-Arc/Sunday-Plugins/releases/download/plugins-test/qq-bot-{version}.zip",
    }]}


def host(tmp_path, installed=None):
    return SimpleNamespace(state=SimpleNamespace(path=tmp_path / "state.json"), get=lambda name: installed)


@pytest.mark.parametrize("size", [0, -1, "200", True, 300 * 1024 * 1024])
def test_catalog_rejects_invalid_package_size(size):
    data = catalog()
    data["plugins"][0]["size"] = size
    with pytest.raises(ValueError):
        market.validate_catalog(data)


@pytest.mark.asyncio
async def test_fresh_catalog_survives_unwritable_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(market, "load_catalog", catalog)
    # A directory at the cache filename makes cache replacement fail.
    (tmp_path / "plugin-market-cache.json").mkdir()
    result = await market.list_market(host(tmp_path))
    assert result["source"] == "github"
    assert result["plugins"][0]["installable"]
    assert result["plugins"][0]["version"] == "0.1.1"


@pytest.mark.asyncio
async def test_offline_without_cache_is_not_reported_as_cached(tmp_path, monkeypatch):
    def offline():
        raise OSError("network unavailable")
    monkeypatch.setattr(market, "load_catalog", offline)
    result = await market.list_market(host(tmp_path))
    assert result["source"] == "unavailable"
    assert result["error"]
    assert not any(row["installable"] for row in result["plugins"])


@pytest.mark.asyncio
async def test_offline_can_show_verified_cached_catalog(tmp_path, monkeypatch):
    (tmp_path / "plugin-market-cache.json").write_text(json.dumps(catalog()))
    monkeypatch.setattr(market, "load_catalog", lambda: (_ for _ in ()).throw(OSError("offline")))
    result = await market.list_market(host(tmp_path))
    assert result["source"] == "cache"
    assert result["plugins"][0]["installable"]


@pytest.mark.asyncio
async def test_market_install_protects_newer_local_version(tmp_path, monkeypatch):
    monkeypatch.setattr(market, "load_catalog", catalog)
    install = AsyncMock()
    monkeypatch.setattr(management, "install_or_update", install)
    with pytest.raises(ValueError, match="版本"):
        await market.install_market_plugin(host(tmp_path, SimpleNamespace(version="0.2.0")), "qq-bot")
    install.assert_not_awaited()


@pytest.mark.asyncio
async def test_market_passes_transactional_version_protection(tmp_path, monkeypatch):
    monkeypatch.setattr(market, "load_catalog", catalog)
    install = AsyncMock(return_value={"installed": True})
    monkeypatch.setattr(management, "install_or_update", install)
    await market.install_market_plugin(host(tmp_path), "qq-bot")
    assert install.call_args.args[1]["no_downgrade"] is True


@pytest.mark.asyncio
async def test_update_transaction_rechecks_version_after_download(tmp_path):
    from lamtools_core.plugin_system import PluginHost
    root = tmp_path / "plugins"
    existing = root / "qq-bot"
    incoming = tmp_path / "incoming"
    existing.mkdir(parents=True)
    incoming.mkdir()
    for folder, version in ((existing, "0.2.0"), (incoming, "0.1.1")):
        (folder / "plugin.json").write_text(json.dumps({"name": "qq-bot", "version": version}))
    plugin_host = PluginHost(roots=[root], state_path=tmp_path / "state.json")
    with pytest.raises(ValueError, match="版本"):
        await management.install_or_update(plugin_host, {"path": str(incoming), "no_downgrade": True}, update=True)
    assert plugin_host.get("qq-bot").version == "0.2.0"
