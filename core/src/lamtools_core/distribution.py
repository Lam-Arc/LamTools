"""Verified distribution traffic shared by the app updater and plugin market."""
from __future__ import annotations

import json
import hashlib
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
def stream_get(url: str, *, timeout=30.0, headers=None, route=None):
    # user:“从 GitHub 等平台下载并安装…摆脱对官网的依赖”+(共享加速与直连回退；下游仍对原始地址的内容执行摘要校验)。
    if urlsplit(url).scheme != "https" and urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("distribution requires HTTPS")
    routes = [route] if route is not None else route_candidates(url)
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
    for index, route in enumerate(routes := route_candidates(url)):
        try:
            with stream_get(url, timeout=timeout, headers=headers, route=route) as response:
                buffer = bytearray()
                for chunk in response.iter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > 2 * 1024 * 1024:
                        raise ValueError("distribution metadata exceeds 2 MiB")
                data = json.loads(buffer)
            break
        except (httpx.TransportError, httpx.HTTPStatusError):
            if index + 1 == len(routes):
                raise
    if not isinstance(data, dict):
        raise ValueError("distribution metadata must be an object")
    return data


def download_file(url, target, *, expected_sha256="", max_bytes, timeout=30.0, headers=None, progress=None, cancel=None, fallback_urls=()):
    # user:“自动通过网络拓展加速…自动优化网络”+(完整传输失败才切换路由/备用 GitHub 入口，每次从零写入并独立校验，绝不拼接半包)。
    attempts = [(address, route) for address in (url, *fallback_urls) for route in route_candidates(address)]
    try:
        for index, (address, route) in enumerate(attempts):
            received, digest = 0, hashlib.sha256()
            try:
                with stream_get(address, timeout=timeout, headers=headers, route=route) as response:
                    length = response.headers.get("content-length", "")
                    declared = int(length) if length.isdigit() else 0
                    if declared > max_bytes:
                        raise ValueError("download exceeds expected size limit")
                    if progress: progress(0, declared)
                    with target.open("wb") as sink:
                        for chunk in response.iter_bytes(1 << 20):
                            if cancel: cancel()
                            received += len(chunk)
                            if received > max_bytes:
                                raise ValueError("download exceeds expected size limit")
                            sink.write(chunk)
                            digest.update(chunk)
                            if progress: progress(received, declared)
                if cancel: cancel()
                actual = digest.hexdigest()
                if expected_sha256 and actual.lower() != expected_sha256.lower():
                    raise ValueError(f"sha256 mismatch: expected {expected_sha256}, got {actual}")
                return {"bytes": received, "sha256": actual}
            except (httpx.TransportError, httpx.HTTPStatusError):
                if index + 1 == len(attempts):
                    raise
    except BaseException:
        target.unlink(missing_ok=True)
        raise
