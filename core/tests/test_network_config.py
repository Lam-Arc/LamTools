"""Tests for the outbound routing settings (设置 → 通用)."""
from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.config.network import (
    NETWORK_NAMESPACE,
    httpx_client_kwargs,
    merge_network,
    network_config,
    host_bypasses_proxy,
    normalize_ca_cert,
    normalize_no_proxy,
    normalize_proxy,
    subprocess_env,
)
from lamtools_core.config.settings_store import set_setting


# --- defaults / direct connection -----------------------------------------


def test_defaults_are_a_direct_connection(isolated_config_root: Path) -> None:
    assert network_config() == {"proxy": "", "no_proxy": "", "ca_cert": ""}
    assert httpx_client_kwargs("https://api.example.com/v1") == {"trust_env": False}


def test_ambient_proxy_variables_never_reach_spawned_tools(
    isolated_config_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An inherited HTTP_PROXY must not decide the route on its own."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:7890")
    monkeypatch.setenv("NO_PROXY", "example.com")

    env = subprocess_env()

    assert "HTTP_PROXY" not in env
    assert "http_proxy" not in env
    assert "NO_PROXY" not in env


# --- configured proxy ------------------------------------------------------


def test_configured_proxy_carries_httpx_and_child_processes(isolated_config_root: Path) -> None:
    set_setting(NETWORK_NAMESPACE, {"proxy": "http://127.0.0.1:7890", "no_proxy": "", "ca_cert": ""})

    assert httpx_client_kwargs("https://api.example.com/v1") == {
        "trust_env": False,
        "proxy": "http://127.0.0.1:7890",
    }
    env = subprocess_env()
    assert env["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    assert env["https_proxy"] == "http://127.0.0.1:7890"


def test_loopback_endpoints_are_never_proxied(isolated_config_root: Path) -> None:
    """A local model gateway / hook / image API must stay reachable."""
    set_setting(NETWORK_NAMESPACE, {"proxy": "http://127.0.0.1:7890"})

    for url in (
        "http://127.0.0.1:8790/v1/chat/completions",
        "http://localhost:5000/hook",
        "http://[::1]:8080/v1",
    ):
        assert httpx_client_kwargs(url) == {"trust_env": False}, url


def test_bypass_rules(isolated_config_root: Path) -> None:
    set_setting(NETWORK_NAMESPACE, {"proxy": "http://127.0.0.1:7890", "no_proxy": ".corp.com,*.example.com,api.test"})

    assert host_bypasses_proxy("svc.corp.com")
    assert host_bypasses_proxy("corp.com")
    assert host_bypasses_proxy("a.example.com")
    assert host_bypasses_proxy("api.test")
    assert not host_bypasses_proxy("notapi.test")
    assert not host_bypasses_proxy("api.commandcode.ai")
    # A bypassed host keeps the direct route, bypassed hosts still ignore env.
    assert httpx_client_kwargs("https://svc.corp.com/v1") == {"trust_env": False}


def test_wildcard_bypasses_everything(isolated_config_root: Path) -> None:
    set_setting(NETWORK_NAMESPACE, {"proxy": "http://127.0.0.1:7890", "no_proxy": "*"})
    assert httpx_client_kwargs("https://api.example.com/v1") == {"trust_env": False}


# --- custom CA bundle ------------------------------------------------------


def test_ca_cert_is_applied_to_httpx_and_spawned_tools(isolated_config_root: Path, tmp_path: Path) -> None:
    pem = tmp_path / "root-ca.pem"
    pem.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    set_setting(NETWORK_NAMESPACE, {"ca_cert": str(pem)})

    assert httpx_client_kwargs("https://api.example.com/v1")["verify"] == str(pem)
    env = subprocess_env()
    assert env["SSL_CERT_FILE"] == str(pem)
    assert env["NODE_EXTRA_CA_CERTS"] == str(pem)
    assert env["REQUESTS_CA_BUNDLE"] == str(pem)


def test_missing_ca_cert_file_is_rejected(isolated_config_root: Path) -> None:
    with pytest.raises(ValueError):
        normalize_ca_cert("/nonexistent/root-ca.pem")


def test_wsl_env_translates_the_ca_path_for_the_linux_side(
    isolated_config_root: Path, tmp_path: Path
) -> None:
    pem = tmp_path / "root-ca.pem"
    pem.write_text("-----BEGIN CERTIFICATE-----\n", encoding="utf-8")
    set_setting(NETWORK_NAMESPACE, {"ca_cert": str(pem), "proxy": "http://127.0.0.1:7890"})

    from lamtools_core.config.network import to_wsl_path, wsl_forward_names

    wsl_env = subprocess_env(wsl=True)
    expected = to_wsl_path(str(pem))
    assert expected.startswith("/mnt/")
    assert wsl_env["SSL_CERT_FILE"] == expected
    # The Windows-side env keeps the native path.
    assert subprocess_env()["SSL_CERT_FILE"] == str(pem)
    # Proxy + CA names are all relayed through WSLENV, so they reach Linux.
    forwarded = set(wsl_forward_names(wsl_env))
    assert {"HTTP_PROXY", "https_proxy", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS"} <= forwarded


# --- validation ------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["127.0.0.1:7890", "ftp://127.0.0.1:7890", "http://127.0.0.1:7890/path", "http://"],
)
def test_invalid_proxy_urls_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_proxy(value)


def test_empty_proxy_means_direct() -> None:
    assert normalize_proxy("") == ""
    assert normalize_proxy("   ") == ""


def test_no_proxy_normalisation_drops_duplicates() -> None:
    assert normalize_no_proxy(" localhost , 127.0.0.1 , localhost ") == "localhost,127.0.0.1"
    with pytest.raises(ValueError):
        normalize_no_proxy("http://proxy.example.com")


def test_merge_network_updates_only_supplied_keys(isolated_config_root: Path) -> None:
    merged = merge_network({"proxy": "http://127.0.0.1:7890", "no_proxy": "a.test", "ca_cert": ""}, {"ca_cert": ""})
    assert merged == {"proxy": "http://127.0.0.1:7890", "no_proxy": "a.test", "ca_cert": ""}

    # Unknown keys are dropped, not persisted.
    merged = merge_network({}, {"unknown": "x"})
    assert merged == {"proxy": "", "no_proxy": "", "ca_cert": ""}

    with pytest.raises(ValueError):
        merge_network({}, {"proxy": "not-a-url"})


# --- egress wiring ---------------------------------------------------------


def test_web_fetch_picks_the_session_matching_the_route(
    isolated_config_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """web_fetch must use the proxied session for normal hosts and the direct
    session for bypassed ones — never the shell's route."""
    from lamtools_core.tool import web_tools

    direct = object()
    proxied = object()
    monkeypatch.setattr(web_tools, "_HTTP_CLIENT", direct)
    monkeypatch.setattr(web_tools, "_HTTP_PROXY_CLIENT", proxied)

    set_setting(NETWORK_NAMESPACE, {"proxy": "http://127.0.0.1:7890", "no_proxy": "internal.test"})

    assert web_tools._http_session("https://example.com/page") is proxied
    assert web_tools._http_session("http://127.0.0.1:8000/page") is direct
    assert web_tools._http_session("https://internal.test/x") is direct


def test_update_check_and_download_follow_the_routing_settings(
    isolated_config_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    import lamtools_core.update.checker as checker
    import lamtools_core.update.installer as installer

    set_setting(NETWORK_NAMESPACE, {"proxy": "http://127.0.0.1:7890"})
    captured: dict[str, dict] = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url):
            return httpx.Response(200, json={"version": "0.0.1"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    checker._http_get_json("https://dl.example.com/desktop-update.json")
    assert captured["client"]["proxy"] == "http://127.0.0.1:7890"
    assert captured["client"]["trust_env"] is False

    def _fake_stream(method, url, **kwargs):
        captured["stream"] = {"url": url, **kwargs}
        raise RuntimeError("stop here — the request arguments are what matters")

    monkeypatch.setattr(httpx, "stream", _fake_stream)
    with pytest.raises(RuntimeError):
        installer.download_update("https://dl.example.com/Sunday.exe", "0" * 64)
    assert captured["stream"]["proxy"] == "http://127.0.0.1:7890"


def test_duckduckgo_engine_proxy_port_wins_over_the_global_setting(
    isolated_config_root: Path,
) -> None:
    from lamtools_core.tool.search.duckduckgo import DuckDuckGoSearchProvider

    set_setting(NETWORK_NAMESPACE, {"proxy": "http://127.0.0.1:7890"})
    assert DuckDuckGoSearchProvider({"proxy_port": 10809}).proxy == "http://127.0.0.1:10809"
    assert DuckDuckGoSearchProvider({}).proxy is None


# --- RPC surface -----------------------------------------------------------


@pytest.mark.asyncio
async def test_settings_rpc_round_trip_and_validation(isolated_config_root: Path) -> None:
    from lamtools_core.config.operations import build_config_operation_catalog

    catalog = build_config_operation_catalog()

    saved = await catalog.execute(
        "settings.update",
        {"namespace": "core.network", "value": {"proxy": "http://127.0.0.1:7890", "no_proxy": "localhost"}},
        metadata={},
    )
    assert saved.status == "ok"
    assert saved.payload["value"]["proxy"] == "http://127.0.0.1:7890"
    # The file the UI reads back is the same one the egress helpers read.
    assert network_config()["proxy"] == "http://127.0.0.1:7890"

    fetched = await catalog.execute("settings.get", {"namespace": "core.network"}, metadata={})
    assert fetched.payload["value"] == {
        "proxy": "http://127.0.0.1:7890",
        "no_proxy": "localhost",
        "ca_cert": "",
    }

    rejected = await catalog.execute(
        "settings.update",
        {"namespace": "core.network", "value": {"proxy": "127.0.0.1:7890"}},
        metadata={},
    )
    assert rejected.status == "error"
    # The field-level reason reaches the settings page.
    assert "代理" in str(rejected.payload.get("error") or "")
    # A rejected update must not overwrite what is already stored.
    assert network_config()["proxy"] == "http://127.0.0.1:7890"
