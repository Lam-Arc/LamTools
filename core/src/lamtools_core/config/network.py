"""Outbound network routing for model, MCP and command-tool traffic.

Settings live in ``settings.jsonc`` under ``core.network``::

    {"core": {"network": {"proxy": "http://127.0.0.1:7890",
                          "no_proxy": "localhost,127.0.0.1,.corp.com",
                          "ca_cert": ""}}}

Contract (设置 → 通用):

* A configured ``proxy`` carries model/provider, MCP and command-tool egress.
* The ambient process environment is never consulted for those egresses: an
  empty ``proxy`` means a direct connection, so a shell-level ``HTTP_PROXY``
  cannot silently reroute them.  The renderer (WebView2) follows the operating
  system proxy and is unaffected by this setting.
* ``ca_cert`` names a PEM bundle used as the trust root by model clients and
  injected into spawned tools.
"""

from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from lamtools_core.config.settings_store import get_setting

NETWORK_NAMESPACE = "core.network"

PROXY_SCHEMES = frozenset({"http", "https", "socks5", "socks5h", "socks4"})

# Every spelling a spawned tool may consult.  They are cleared before the
# configured values are applied so an inherited value can never win.
_PROXY_ENV_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)

_CA_ENV_NAMES = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS")

_TOKEN_RE = re.compile(r"^[A-Za-z0-9._*:\[\]-]+$")

_EMPTY_CONFIG: dict[str, str] = {"proxy": "", "no_proxy": "", "ca_cert": ""}


def _text(value: Any) -> str:
    return str(value or "").strip()


def normalize_proxy(value: Any) -> str:
    """Return a validated proxy URL, or ``""`` for a direct connection."""
    raw = _text(value)
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in PROXY_SCHEMES or not parsed.netloc:
        raise ValueError("代理地址必须是形如 http://127.0.0.1:7890 的完整地址")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("代理地址不能带路径、查询或片段")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("代理地址缺少主机名")
    return raw


def normalize_no_proxy(value: Any) -> str:
    """Return the comma-joined bypass list (``localhost,.corp.com,*.x.com``)."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        tokens = [_text(item) for item in value]
    else:
        tokens = [item.strip() for item in _text(value).split(",")]
    kept: list[str] = []
    for token in tokens:
        if not token:
            continue
        if not _TOKEN_RE.match(token):
            raise ValueError(f"不使用代理的地址只能是主机或域名规则：{token}")
        if token not in kept:
            kept.append(token)
    return ",".join(kept)


def normalize_ca_cert(value: Any) -> str:
    """Return the PEM path as typed, or ``""``.  A named file must exist."""
    raw = _text(value)
    if not raw:
        return ""
    path = Path(raw).expanduser()
    if not path.is_file():
        raise ValueError(f"自定义证书文件不存在：{raw}")
    return raw


def ca_cert_path(value: Any = None) -> str:
    """Return the absolute PEM path, or ``""`` when unset."""
    raw = _text(value) if value is not None else network_config()["ca_cert"]
    if not raw:
        return ""
    return str(Path(raw).expanduser())


def merge_network(current: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge a ``core.network`` update, raising ``ValueError`` when invalid.

    Unknown keys are dropped rather than persisted (same discipline as
    ``core.runtimeControls``).
    """
    merged = {**(current if isinstance(current, dict) else {})}
    for key, raw in incoming.items():
        if key == "proxy":
            merged[key] = normalize_proxy(raw)
        elif key == "no_proxy":
            merged[key] = normalize_no_proxy(raw)
        elif key == "ca_cert":
            merged[key] = normalize_ca_cert(raw)
    for key, value in _EMPTY_CONFIG.items():
        merged.setdefault(key, value)
    return merged


def network_config() -> dict[str, str]:
    """Return the stored routing settings, defaulted to a direct connection."""
    stored = get_setting(NETWORK_NAMESPACE)
    values = dict(stored) if isinstance(stored, dict) else {}
    return {key: _text(values.get(key)) for key in _EMPTY_CONFIG}


def proxy_url() -> str:
    return network_config()["proxy"]


def no_proxy() -> str:
    return network_config()["no_proxy"]


def _split_host_port(token: str) -> str:
    host = token.strip().lower()
    if host.startswith("["):  # [::1]:8080
        end = host.find("]")
        return host[: end + 1] if end >= 0 else host
    if host.count(":") > 1:
        # Unbracketed IPv6 literal (``::1``) — no port to strip.
        return host
    head, _, tail = host.rpartition(":")
    if head and tail.isdigit():
        return head
    return host


def _is_loopback_host(host: str) -> bool:
    """Loopback targets are always direct.

    A configured proxy must never swallow the machine's own endpoints: hook
    URLs, a local image API, and a locally hosted model gateway (e.g. a
    record/replay proxy) all live on 127.0.0.1.
    """
    candidate = _split_host_port(host).strip("[]")
    if not candidate:
        return False
    if candidate == "localhost" or candidate.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def host_bypasses_proxy(host: str, bypass: str | None = None) -> bool:
    """True when ``host`` must connect directly instead of via the proxy."""
    if _is_loopback_host(host):
        return True
    rules = no_proxy() if bypass is None else bypass
    if not rules:
        return False
    target = _split_host_port(host)
    if not target:
        return False
    for raw_rule in str(rules).split(","):
        rule = raw_rule.strip().lower()
        if not rule:
            continue
        if rule == "*":
            return True
        if rule.startswith("*."):
            rule = rule[1:]
        elif rule.startswith("*"):
            rule = rule[1:]
        candidate = _split_host_port(rule)
        if not candidate:
            continue
        if candidate.startswith("."):
            bare = candidate[1:]
            if target == bare or target.endswith(candidate):
                return True
            continue
        if target == candidate:
            return True
    return False


def url_bypasses_proxy(url: str) -> bool:
    return host_bypasses_proxy(urlsplit(str(url)).hostname or "")


def httpx_client_kwargs(target_url: str = "") -> dict[str, Any]:
    """Extra :class:`httpx.AsyncClient` keyword arguments for an egress URL.

    ``trust_env=False`` is unconditional: the process environment must never
    decide the route for these calls (see module docstring).
    """
    config = network_config()
    kwargs: dict[str, Any] = {"trust_env": False}
    proxy = config["proxy"]
    if proxy and not (target_url and url_bypasses_proxy(target_url)):
        kwargs["proxy"] = proxy
    cert = ca_cert_path(config["ca_cert"])
    if cert:
        kwargs["verify"] = cert
    return kwargs


def to_wsl_path(value: str) -> str:
    """Translate a Windows path into the WSL mount form (``C:\\x`` → ``/mnt/c/x``).

    A Windows path handed to a Linux-side tool is worse than no path at all:
    it silently points the trust store at a file that does not exist.
    """
    raw = _text(value)
    if not raw:
        return ""
    path = Path(raw)
    drive = path.drive
    if len(drive) == 2 and drive[1] == ":":
        rest = str(path)[2:].lstrip("\\/").replace("\\", "/")
        return f"/mnt/{drive[0].lower()}/{rest}"
    return raw.replace("\\", "/")


def subprocess_env(base: Mapping[str, str] | None = None, *, wsl: bool = False) -> dict[str, str]:
    """Environment for a spawned tool (MCP server, hook, observer, shell).

    Inherited proxy variables are always cleared first, so the effective route
    is exactly what 设置 → 通用 shows.  ``wsl=True`` translates the CA bundle
    path for the Linux side.
    """
    env = dict(os.environ if base is None else base)
    for name in _PROXY_ENV_NAMES:
        env.pop(name, None)

    config = network_config()
    proxy = config["proxy"]
    if proxy:
        env["HTTP_PROXY"] = proxy
        env["HTTPS_PROXY"] = proxy
        env["ALL_PROXY"] = proxy
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy
        env["all_proxy"] = proxy
    bypass = config["no_proxy"]
    if bypass:
        env["NO_PROXY"] = bypass
        env["no_proxy"] = bypass
    cert = ca_cert_path(config["ca_cert"])
    if cert:
        resolved = to_wsl_path(cert) if wsl else cert
        for name in _CA_ENV_NAMES:
            env[name] = resolved
    return env


def has_routing() -> bool:
    """True when the settings differ from a plain direct connection."""
    config = network_config()
    return bool(config["proxy"] or config["ca_cert"])


def wsl_forward_names(env: Mapping[str, str]) -> list[str]:
    """Routing variable names present in ``env`` that must cross into WSL.

    ``wsl.exe`` only relays names listed in ``WSLENV``.
    """
    return [name for name in (*_PROXY_ENV_NAMES, *_CA_ENV_NAMES) if name in env]


__all__ = [
    "NETWORK_NAMESPACE",
    "PROXY_SCHEMES",
    "ca_cert_path",
    "has_routing",
    "host_bypasses_proxy",
    "httpx_client_kwargs",
    "merge_network",
    "network_config",
    "no_proxy",
    "normalize_ca_cert",
    "normalize_no_proxy",
    "normalize_proxy",
    "proxy_url",
    "subprocess_env",
    "to_wsl_path",
    "url_bypasses_proxy",
    "wsl_forward_names",
]
