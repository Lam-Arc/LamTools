"""user:“目前市场就提供一个 QQ robot 和哔哩哔哩…自动通过网络拓展加速”+(宿主校验市场身份并共用可信下载路由)。"""
import json
import hashlib
from unittest.mock import AsyncMock

import pytest


def test_download_routes_use_accelerator_only_for_github(monkeypatch):
    from lamtools_core import distribution as dist
    monkeypatch.setattr(dist, "httpx_client_kwargs", lambda url: {"trust_env": False})
    owner = object()
    dist.register_accelerator(owner, "http://127.0.0.1:12345")
    try:
        assert dist.route_candidates("https://api.github.com/repos/a/b")[0]["proxy"] == "http://127.0.0.1:12345"
        assert "proxy" not in dist.route_candidates("https://example.com")[0]
        assert "proxy" not in dist.route_candidates("https://github.com.evil.test")[0]
        assert len(dist.route_candidates("https://github.com/a/b")) == 2
        dist.clear_accelerator(object())
        assert "proxy" in dist.route_candidates("https://github.com")[0]
    finally:
        dist.clear_accelerator(owner)
    assert "proxy" not in dist.route_candidates("https://github.com")[0]


def test_download_routes_preserve_explicit_proxy(monkeypatch):
    from lamtools_core import distribution as dist
    monkeypatch.setattr(dist, "httpx_client_kwargs", lambda url: {"trust_env": False, "proxy": "http://configured:8000"})
    assert dist.route_candidates("https://github.com") == [{"trust_env": False, "proxy": "http://configured:8000"}]


@pytest.mark.asyncio
async def test_market_install_uses_trusted_release_and_verifies_identity(tmp_path, monkeypatch):
    from lamtools_core.plugin_system import market, management, PluginHost
    row = {"id": "qq-bot", "version": "0.1.0", "url": "https://github.com/Lam-Arc/Sunday-Plugins/releases/download/plugins-1/qq-bot.zip", "sha256": "a"*64}
    monkeypatch.setattr(market, "load_catalog", lambda: {"plugins": [row]})
    install = AsyncMock(return_value={"installed": True, "name": "qq-bot"})
    monkeypatch.setattr(management, "install_or_update", install)
    host = PluginHost(roots=[tmp_path / "plugins"], state_path=tmp_path / "state.json")
    await market.install_market_plugin(host, "qq-bot")
    payload = install.call_args.args[1]
    assert payload["sha256"] == "a"*64
    assert payload["expected_name"] == "qq-bot"
    assert payload["expected_version"] == "0.1.0"
    with pytest.raises(ValueError):
        await market.install_market_plugin(host, "unknown")


@pytest.mark.parametrize("change", [{"id": "evil"}, {"url": "https://evil.test/plugin.zip"}, {"sha256": ""}, {"version": ""}])
def test_market_rejects_untrusted_catalog_entries(change):
    from lamtools_core.plugin_system.market import validate_catalog
    row = {"id": "qq-bot", "version": "0.1.0", "url": "https://github.com/Lam-Arc/Sunday-Plugins/releases/download/plugins-1/qq-bot.zip", "sha256": "a"*64, **change}
    with pytest.raises(ValueError):
        validate_catalog({"format": 1, "plugins": [row]})


def test_app_update_checks_github_before_site(monkeypatch):
    from lamtools_core.update import checker
    monkeypatch.setattr(checker, "_site_candidate", lambda: pytest.fail("site should not be required"))
    monkeypatch.setattr(checker, "_github_candidate", lambda: {"version": "99.0.0", "download_url": "https://github.com/a.exe", "release_url": "https://github.com", "release_notes": "", "published_at": "", "sha256": "a"*64})
    assert checker.check_update()["source"] == "github"


def test_mid_download_failure_retries_without_appending_partial_bytes(tmp_path, monkeypatch):
    from contextlib import contextmanager
    import httpx
    from lamtools_core import distribution as dist
    monkeypatch.setattr(dist, "route_candidates", lambda url: [{"proxy": "http://127.0.0.1:12345"}, {"trust_env": False}])
    attempts = []
    @contextmanager
    def stream(url, **kwargs):
        attempts.append(kwargs)
        class Response:
            headers = {"content-length": "8"}
            def iter_bytes(self, *args):
                if len(attempts) == 1:
                    yield b"partial"
                    raise httpx.ReadTimeout("connection reset")
                yield b"complete"
        yield Response()
    monkeypatch.setattr(dist, "stream_get", stream)
    target = tmp_path / "package.part"
    digest = hashlib.sha256(b"complete").hexdigest()
    result = dist.download_file("https://github.com/a.zip", target, expected_sha256=digest, max_bytes=100)
    assert target.read_bytes() == b"complete"
    assert result["sha256"] == digest
    assert len(attempts) == 2


def test_update_api_asset_keeps_installer_name_and_checksum(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from lamtools_core import distribution as dist
    from lamtools_core.update import installer
    payload = b"verified test installer bytes"
    @contextmanager
    def stream(url, **kwargs):
        class Response:
            headers = {"content-length": str(len(payload))}
            def iter_bytes(self, *args): yield payload
        yield Response()
    monkeypatch.setattr(dist, "stream_get", stream)
    monkeypatch.setenv("LAMTOOLS_UPDATE_DIR", str(tmp_path))
    installer._CANCEL.clear()
    result = installer.download_update("https://api.github.com/repos/Lam-Arc/LamTools/releases/assets/123", hashlib.sha256(payload).hexdigest(), "Sunday_0.3.23_x64-setup.exe")
    assert result["name"] == "Sunday_0.3.23_x64-setup.exe"
    assert result["bytes"] == len(payload)
    assert not list(tmp_path.glob("*.part"))
