"""Rich-media download, cleanup and sending.

Downloading is deliberately conservative: HTTPS only, every resolved address
must be public, the declared/actual size is bounded, and the request has a
timeout.  These checks are host-side policy (the upstream SDK leaves SSRF
protection to the integration layer).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

from .constants import (
    DEFAULT_TYPING_SECONDS,
    MEDIA_TYPE_FILE,
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_VIDEO,
    MEDIA_TYPE_VOICE,
)
from .protocol import QQApi, QQApiError, ReplyTarget
from .util import (
    classify_media,
    format_file_size,
    is_path_allowed,
    media_file_type,
    sanitize_filename,
    to_posix_path,
    unique_filename,
)

DOWNLOAD_TIMEOUT_SEC = 120.0


class MediaError(RuntimeError):
    pass


def _is_public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        # IPv4-mapped addresses must be judged as IPv4.
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def _assert_safe_hostname(hostname: str) -> None:
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, hostname, 443, type=socket.SOCK_STREAM)
    except Exception as exc:
        raise MediaError(f"DNS resolution failed: {hostname}") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise MediaError(f"DNS resolution failed: {hostname}")
    for address in addresses:
        if not _is_public_address(address):
            raise MediaError(f"SSRF blocked: {hostname} resolves to private IP {address}")


async def download_url(url: str, max_bytes: int, *, allow_http: bool = False) -> bytes:
    """Download a public URL with SSRF/size/timeout guards."""
    parsed = urlparse(str(url or ""))
    allowed_schemes = {"https", "http"} if allow_http else {"https"}
    if parsed.scheme not in allowed_schemes:
        raise MediaError(f"Only {'/'.join(sorted(allowed_schemes))} allowed: {parsed.scheme or '(none)'}")
    if not parsed.hostname:
        raise MediaError("URL has no hostname")
    await _assert_safe_hostname(parsed.hostname)
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=DOWNLOAD_TIMEOUT_SEC) as client:
            response = await client.get(url)
            if response.status_code >= 400:
                raise MediaError(f"HTTP {response.status_code}")
            data = response.content
    except MediaError:
        raise
    except Exception as exc:
        raise MediaError(f"download failed: {exc}") from exc
    if len(data) > max_bytes:
        raise MediaError(f"Download exceeds {format_file_size(max_bytes)}")
    return data


class MediaStore:
    def __init__(self, data_dir: Path, logger: logging.Logger | None = None) -> None:
        self.root = Path(data_dir) / "media"
        self.logger = logger or logging.getLogger("qqbot")

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    async def download_attachments(
        self,
        attachments: list[dict[str, Any]] | None,
        media_config: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not media_config.get("enabled", True):
            return []
        targets = [
            item
            for item in (attachments or [])
            if isinstance(item, dict)
            and item.get("url")
            and not str(item.get("content_type") or "").lower().startswith("audio/")
            and str(item.get("content_type") or "").lower() != "voice"
        ]
        if not targets:
            return []
        self.ensure()
        max_bytes = max(1, int(media_config.get("maxMB") or 200)) * 1024 * 1024
        results: list[dict[str, Any]] = []
        for attachment in targets:
            declared = int(attachment.get("size") or 0)
            if declared > max_bytes:
                self.logger.debug("skip download (%sB too large): %s", declared, attachment.get("filename"))
                continue
            filename = str(attachment.get("filename") or "attachment")
            local_name = unique_filename(filename)
            local_path = self.root / local_name
            try:
                data = await download_url(str(attachment["url"]), max_bytes)
                await asyncio.to_thread(local_path.write_bytes, data)
            except Exception as exc:
                self.logger.warning("download failed: %s — %s", filename, exc)
                continue
            content_type = str(attachment.get("content_type") or "").lower()
            kind = (
                "image"
                if content_type.startswith("image/")
                else "video"
                if content_type.startswith("video/")
                else "file"
            )
            results.append(
                {
                    "filename": filename,
                    "contentType": kind,
                    "localPath": to_posix_path(local_path),
                    "size": len(data),
                }
            )
            self.logger.debug("attachment downloaded: %s (%s) -> %s", filename, format_file_size(len(data)), local_path)
        return results

    async def cleanup_expired(self, ttl_hours: int) -> int:
        if int(ttl_hours or 0) <= 0 or not self.root.exists():
            return 0
        cutoff = time.time() - int(ttl_hours) * 3600
        removed = 0
        for entry in await asyncio.to_thread(lambda: list(self.root.iterdir())):
            try:
                if entry.is_file() and entry.stat().st_mtime < cutoff:
                    await asyncio.to_thread(entry.unlink, True)
                    removed += 1
            except Exception as exc:
                self.logger.warning("media cleanup failed for %s: %s", entry.name, exc)
        return removed


# ── Sending ────────────────────────────────────────────────────────────────

async def send_media_file(
    api: QQApi,
    target: ReplyTarget,
    file_path: str | Path,
    *,
    file_name: str = "",
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    path = Path(file_path)
    try:
        info = await asyncio.to_thread(path.stat)
    except Exception:
        return {"outcome": "missing"}
    if not info.st_mode or not path.is_file():
        return {"outcome": "missing"}
    name = file_name or path.name
    file_type = media_file_type(name)
    try:
        data = await asyncio.to_thread(path.read_bytes)
    except Exception as exc:
        return {"outcome": "failed", "error": str(exc)}
    try:
        result = await api.send_media(
            target,
            file_type,
            data=data,
            file_name=sanitize_filename(name),
        )
    except QQApiError as exc:
        return {"outcome": "failed", "error": str(exc)}
    except Exception as exc:
        return {"outcome": "failed", "error": str(exc)}
    upload = result.get("upload") if isinstance(result.get("upload"), dict) else result
    message = result.get("message") if isinstance(result.get("message"), dict) else {}
    return {
        "outcome": "sent",
        "size": len(data),
        "fileUuid": str((upload or {}).get("file_uuid") or ""),
        "messageId": str((message or {}).get("id") or ""),
    }


def send_roots(
    *,
    data_dir: Path,
    work_root: str | Path | None,
    config: dict[str, Any],
) -> list[str]:
    roots: list[str] = [str(Path(data_dir) / "media")]
    if work_root:
        roots.append(str(work_root))
    send_file = config.get("sendFile") or {}
    roots.extend(str(item) for item in (send_file.get("extraRoots") or []))
    cwd = str(config.get("cwd") or "").strip()
    if cwd:
        roots.append(cwd)
    return roots


def path_is_allowed(
    file_path: str | Path,
    *,
    data_dir: Path,
    work_root: str | Path | None,
    config: dict[str, Any],
) -> bool:
    send_file = config.get("sendFile") or {}
    return is_path_allowed(
        file_path,
        send_roots(data_dir=data_dir, work_root=work_root, config=config),
        restrict=bool(send_file.get("restrictPaths", True)),
    )


__all__ = [
    "MediaError",
    "download_url",
    "MediaStore",
    "send_media_file",
    "send_roots",
    "path_is_allowed",
]
