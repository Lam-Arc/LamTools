"""Verified distribution traffic shared by the app updater and plugin market."""
from __future__ import annotations

import json
import threading
from contextlib import ExitStack, contextmanager
from urllib.parse import urlsplit

import httpx

from .config.network import httpx_client_kwargs

_lock = threading.Lock()
_accelerator = None
GITHUB_HOSTS = ("github.com", "githubusercontent.com", "githubassets.com")


def register_accelerator(owner, proxy: str) -> None:
    # user:“自动通过网络拓展加速（如果需要）”+(插件只提供本机路由，不改系统代理、不替换下载地址和 TLS 身份)。
    parsed = urlsplit(proxy)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
        raise ValueError("distribution accelerator must be a loopback HTTP proxy")
    global _accelerator
    with _lock:
        _accelerator = (owner, proxy)


def clear_accelerator(owner) -> None:
    global _accelerator
    with _lock:
        if _accelerator and _accelerator[0] is owner:
            _accelerator = None


def route_candidates(url: str) -> list[dict]:
    configured = httpx_client_kwargs(url)
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    with _lock:
        route = _accelerator
    if route and not configured.get("proxy") and any(host == domain or host.endswith("." + domain) for domain in GITHUB_HOSTS):
        return [{**configured, "proxy": route[1]}, configured]
    return [configured]


@contextmanager
def stream_get(url: str, *, timeout=30.0, headers=None):
    # user:“从 GitHub 等平台下载并安装…摆脱对官网的依赖”+(共享加速与直连回退；下游仍对原始地址的内容执行摘要校验)。
    if urlsplit(url).scheme != "https" and urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("distribution requires HTTPS")
    routes = route_candidates(url)
    for index, route in enumerate(routes):
        stack = ExitStack()
        try:
            client = stack.enter_context(httpx.Client(timeout=timeout, follow_redirects=True, **route))
            response = stack.enter_context(client.stream("GET", url, headers=headers or {}))
            response.raise_for_status()
        except (httpx.TransportError, httpx.HTTPStatusError):
            stack.close()
            if index + 1 == len(routes):
                raise
            continue
        try:
            yield response
        finally:
            stack.close()
        return


def get_json(url: str, *, timeout=10.0, headers=None):
    with stream_get(url, timeout=timeout, headers=headers) as response:
        buffer = bytearray()
        for chunk in response.iter_bytes():
            buffer.extend(chunk)
            if len(buffer) > 2 * 1024 * 1024:
                raise ValueError("distribution metadata exceeds 2 MiB")
        data = json.loads(buffer)
    if not isinstance(data, dict):
        raise ValueError("distribution metadata must be an object")
    return data
