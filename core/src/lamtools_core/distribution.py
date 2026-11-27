"""Verified distribution traffic shared by the app updater and plugin market.

Two things make a 90 MB installer fast on a slow link, and both live here:

* **The local EasyNet route.**  When the bundled network plugin runs, it hands
  this module a loopback HTTP proxy (the DoH accelerator, or the subscription
  proxy behind it).  Every HTTPS distribution request prefers that route and
  keeps a direct attempt as the fallback, so an update never depends on the
  plugin being healthy.
* **Several connections per file.**  Range-capable servers are fetched with
  ``connections`` parallel ranges; a server that ignores ranges simply falls
  back to one stream.  The digest is still computed over the assembled file, so
  parallel or not, only bytes matching the release manifest are published.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import threading
from contextlib import ExitStack, contextmanager
from urllib.parse import urlsplit

import httpx

from .config.network import httpx_client_kwargs

#: Below this the extra round trips cost more than they save.
PARALLEL_MIN_BYTES = 4 * 1024 * 1024
#: Enough to saturate a link without opening a wall of tunnels.
DEFAULT_CONNECTIONS = 4

_lock = threading.Lock()
#: (owner, kind, proxy) — ``kind`` is ``accelerator`` or ``proxy``.
_local_route: tuple[object, str, str] | None = None


class RangeUnsupported(Exception):
    """The server ignored a range request; the caller must stream sequentially."""


def register_local_route(owner, proxy: str, *, kind: str = "accelerator") -> None:
    # user:“sunday更新 可以优先 easy net 吗？这样更新的速度会快一些”+(本机加速与订阅代理都注册成宿主分发路由，只提供本机端口，不改系统代理、不替换下载地址和 TLS 身份)。
    parsed = urlsplit(proxy)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
        raise ValueError("distribution route must be a loopback HTTP proxy")
    global _local_route
    with _lock:
        _local_route = (owner, kind, proxy)


def clear_local_route(owner) -> None:
    global _local_route
    with _lock:
        if _local_route and _local_route[0] is owner:
            _local_route = None


def register_accelerator(owner, proxy: str) -> None:
    register_local_route(owner, proxy, kind="accelerator")


def clear_accelerator(owner) -> None:
    clear_local_route(owner)


def local_route():
    """The registered ``(owner, kind, proxy)`` route, or ``None``."""
    with _lock:
        return _local_route


def _is_loopback(host: str) -> bool:
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def route_candidates(url: str) -> list[dict]:
    """httpx kwargs to try in order: the local route first, then the plain route.

    A configured proxy in 设置 → 通用 stays authoritative — the user said where
    their traffic goes.  Loopback targets never take a detour through it.
    """
    configured = httpx_client_kwargs(url)
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    route = local_route()
    if route and not configured.get("proxy") and host and not _is_loopback(host):
        return [{**configured, "proxy": route[2]}, configured]
    return [configured]


def route_kind(route: dict) -> str:
    """``accelerator`` / ``proxy`` / ``configured`` / ``direct`` for one route."""
    proxy = route.get("proxy")
    if not proxy:
        return "direct"
    local = local_route()
    if local and proxy == local[2]:
        return local[1]
    return "configured"


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


def download_file(
    url,
    target,
    *,
    expected_sha256="",
    max_bytes,
    timeout=30.0,
    headers=None,
    progress=None,
    cancel=None,
    fallback_urls=(),
    connections=1,
    on_route=None,
):
    # user:“自动通过网络拓展加速…自动优化网络”+(完整传输失败才切换路由/备用 GitHub 入口，每次从零写入并独立校验，绝不拼接半包)。
    attempts = [(address, route) for address in (url, *fallback_urls) for route in route_candidates(address)]
    try:
        for index, (address, route) in enumerate(attempts):
            if on_route:
                on_route(route_kind(route))
            try:
                received, digest = _download_once(
                    address, target, route, timeout=timeout, headers=headers or {},
                    max_bytes=max_bytes, progress=progress, cancel=cancel, connections=connections,
                )
            except (httpx.TransportError, httpx.HTTPStatusError):
                if index + 1 == len(attempts):
                    raise
                continue
            if cancel:
                cancel()
            actual = digest
            if expected_sha256 and actual.lower() != expected_sha256.lower():
                raise ValueError(f"sha256 mismatch: expected {expected_sha256}, got {actual}")
            return {"bytes": received, "sha256": actual}
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    raise ValueError("no route attempted")


def _download_once(address, target, route, *, timeout, headers, max_bytes, progress, cancel, connections):
    if connections > 1:
        try:
            plan = _range_plan(address, route, timeout=timeout, headers=headers, max_bytes=max_bytes)
        except (httpx.TransportError, httpx.HTTPStatusError):
            plan = None
        if plan is not None:
            total, parts = plan
            try:
                return _download_parts(
                    address, target, route, timeout=timeout, headers=headers, total=total,
                    parts=parts, progress=progress, cancel=cancel,
                )
            except (RangeUnsupported, httpx.TransportError, httpx.HTTPStatusError):
                # 有的代理限制并发连接：先在同一条路由上退回单连接，别直接掉回直连。
                pass
    return _download_stream(
        address, target, route, timeout=timeout, headers=headers,
        max_bytes=max_bytes, progress=progress, cancel=cancel,
    )


def _download_stream(address, target, route, *, timeout, headers, max_bytes, progress, cancel):
    received, digest = 0, hashlib.sha256()
    with stream_get(address, timeout=timeout, headers=headers, route=route) as response:
        length = response.headers.get("content-length", "")
        declared = int(length) if length.isdigit() else 0
        if declared > max_bytes:
            raise ValueError("download exceeds expected size limit")
        if progress:
            progress(0, declared)
        with target.open("wb") as sink:
            for chunk in response.iter_bytes(1 << 20):
                if cancel:
                    cancel()
                received += len(chunk)
                if received > max_bytes:
                    raise ValueError("download exceeds expected size limit")
                sink.write(chunk)
                digest.update(chunk)
                if progress:
                    progress(received, declared)
    return received, digest.hexdigest()


def _range_plan(address, route, *, timeout, headers, max_bytes):
    """Ask for one byte to learn whether ranges and the size are usable."""
    probe_headers = {**headers, "Range": "bytes=0-0"}
    with stream_get(address, timeout=timeout, headers=probe_headers, route=route) as response:
        if getattr(response, "status_code", 200) != 206:
            return None
        content_range = str(response.headers.get("content-range") or "")
        total = _content_range_total(content_range)
    if not total or total > max_bytes or total < PARALLEL_MIN_BYTES:
        return None
    return total, _segments(total)


def _content_range_total(value: str) -> int:
    _, _, size = value.partition("/")
    size = size.strip()
    return int(size) if size.isdigit() else 0


def _segments(total: int, parts: int = DEFAULT_CONNECTIONS) -> list[tuple[int, int]]:
    parts = max(1, min(parts, total))
    size = (total + parts - 1) // parts
    segments = []
    start = 0
    while start < total:
        end = min(total, start + size) - 1
        segments.append((start, end))
        start = end + 1
    return segments


def _download_parts(address, target, route, *, timeout, headers, total, parts, progress, cancel):
    """Fetch each range on its own connection, then assemble in order."""
    part_paths = [target.with_name(f"{target.name}.part{index}") for index in range(len(parts))]
    stop = threading.Event()
    errors: list[BaseException] = []
    counter = {"received": 0}
    guard = threading.Lock()

    def report(delta):
        with guard:
            counter["received"] += delta
            current = counter["received"]
        if progress:
            progress(current, total)

    def worker(index, start, end):
        part = part_paths[index]
        expected = end - start + 1
        written = 0
        try:
            with client.stream("GET", address, headers={**headers, "Range": f"bytes={start}-{end}"}) as response:
                if getattr(response, "status_code", 200) != 206:
                    raise RangeUnsupported("server ignored the range request")
                response.raise_for_status()
                with part.open("wb") as sink:
                    for chunk in response.iter_bytes(1 << 20):
                        if stop.is_set():
                            return
                        if cancel:
                            cancel()
                        granted = min(len(chunk), expected - written)
                        if granted <= 0:
                            break
                        sink.write(chunk[:granted])
                        written += granted
                        report(granted)
                    if written != expected:
                        raise httpx.ReadError(f"range {start}-{end} returned {written} of {expected} bytes")
        except BaseException as exc:  # noqa: BLE001 — surfaced on the caller's thread
            errors.append(exc)
            stop.set()

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, **route) as client:
            threads = [
                threading.Thread(target=worker, args=(index, start, end), daemon=True, name=f"sunday-range-{index}")
                for index, (start, end) in enumerate(parts)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        if errors:
            raise errors[0]
        if counter["received"] != total:
            raise httpx.ReadError(f"assembled {counter['received']} of {total} bytes")
        digest = hashlib.sha256()
        with target.open("wb") as sink:
            for part in part_paths:
                with part.open("rb") as source:
                    while chunk := source.read(1 << 20):
                        sink.write(chunk)
                        digest.update(chunk)
        return counter["received"], digest.hexdigest()
    finally:
        for part in part_paths:
            part.unlink(missing_ok=True)
