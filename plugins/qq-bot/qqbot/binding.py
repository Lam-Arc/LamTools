"""QR-code binding against q.qq.com.

The upstream plugin uses ``@tencent-connect/qqbot-connector``.  That package is
a thin wrapper around three public endpoints (create task / poll / decrypt), so
the port reimplements the same protocol in Python instead of requiring Node at
runtime:

* ``POST https://q.qq.com/lite/create_bind_task``  ``{key}``
* ``POST https://q.qq.com/lite/poll_bind_result``  ``{task_id}``
* AES-256-GCM decrypt of ``bot_encrypt_secret`` with ``key``
* ``https://q.qq.com/qqbot/openclaw/connect.html?task_id=…&source=…&_wv=2``
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .constants import DEFAULT_QR_HOST

_VENDOR = Path(__file__).resolve().parent.parent / "vendor"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))


POLL_INTERVAL_SEC = 2.0
BIND_STATUS_NONE = 0
BIND_STATUS_PENDING = 1
BIND_STATUS_COMPLETED = 2
BIND_STATUS_EXPIRED = 3


@dataclass
class BindingState:
    phase: str = "starting"
    url: str = ""
    qr_svg: str = ""
    issued_at: int = 0
    reason: str = ""
    app_id: str = ""

    def wire(self) -> dict[str, Any]:
        if self.phase == "waiting":
            return {
                "phase": "waiting",
                "url": self.url,
                "qrSvg": self.qr_svg or None,
                "issuedAt": self.issued_at,
            }
        if self.phase == "failed":
            return {"phase": "failed", "reason": self.reason}
        if self.phase == "bound":
            return {"phase": "bound", "appId": self.app_id}
        return {"phase": self.phase}


def generate_bind_key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


def decrypt_secret(encrypted_b64: str, key_b64: str) -> str:
    """Decrypt ``bot_encrypt_secret`` (AES-256-GCM, 12-byte nonce, 16-byte tag)."""
    key = base64.b64decode(key_b64)
    payload = base64.b64decode(encrypted_b64)
    if len(key) != 32 or len(payload) < 28:
        raise ValueError("invalid QR binding key or payload")
    nonce = payload[:12]
    tag = payload[-16:]
    ciphertext = payload[12:-16]
    plaintext = AESGCM(key).decrypt(nonce, ciphertext + tag, None)
    return plaintext.decode("utf-8")


def build_connect_url(task_id: str, source: str = "lamtools-qqbot") -> str:
    return (
        f"https://{DEFAULT_QR_HOST}/qqbot/openclaw/connect.html"
        f"?task_id={quote(str(task_id), safe='')}&source={quote(source, safe='')}&_wv=2"
    )


def render_qr_svg_data_url(url: str) -> str:
    """Render a QR code as an SVG data URL using the vendored qrcode package."""
    import qrcode
    import qrcode.image.svg

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    svg = image.to_string()
    if isinstance(svg, bytes):
        svg = svg.decode("utf-8")
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


class QQBindClient:
    """Small injectable client so tests do not need q.qq.com."""

    def __init__(self, *, host: str = DEFAULT_QR_HOST, client: httpx.AsyncClient | None = None) -> None:
        self.host = host
        self._client = client
        self._owns = client is None

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"https://{self.host}{path}"
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        try:
            response = await self._client.post(
                url,
                json=body,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
        except Exception as exc:
            raise RuntimeError(f"请求 {url} 失败: {exc}") from exc
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code} from {url}")
        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"绑定接口返回非 JSON: {url}") from exc
        if data.get("retcode") != 0:
            raise RuntimeError(str(data.get("msg") or "bind request failed"))
        return data

    async def create_task(self) -> dict[str, Any]:
        key = generate_bind_key()
        data = await self._post("/lite/create_bind_task", {"key": key})
        task_id = str((data.get("data") or {}).get("task_id") or "")
        if not task_id:
            raise RuntimeError("create_bind_task: missing task_id")
        return {"taskId": task_id, "key": key}

    async def poll(self, task_id: str) -> dict[str, Any]:
        data = await self._post("/lite/poll_bind_result", {"task_id": task_id})
        payload = data.get("data") or {}
        return {
            "status": int(payload.get("status") or BIND_STATUS_NONE),
            "botAppId": str(payload.get("bot_appid") or ""),
            "botEncryptSecret": str(payload.get("bot_encrypt_secret") or ""),
            "userOpenid": str(payload.get("user_openid") or ""),
        }

    async def close(self) -> None:
        if self._owns and self._client is not None:
            await self._client.aclose()
            self._client = None


class BindingService:
    """One QR binding session; ``refresh`` replaces the current task."""

    def __init__(
        self,
        *,
        client: QQBindClient,
        logger: logging.Logger,
        on_state: Callable[[BindingState], None] | None = None,
        on_success: Callable[[dict[str, str]], Awaitable[None] | None] | None = None,
        on_failure: Callable[[str], Awaitable[None] | None] | None = None,
        poll_interval: float = POLL_INTERVAL_SEC,
        render_qr: Callable[[str], str] = render_qr_svg_data_url,
    ) -> None:
        self.client = client
        self.logger = logger
        self.on_state = on_state
        self.on_success = on_success
        self.on_failure = on_failure
        self.poll_interval = poll_interval
        self.render_qr = render_qr
        self.state = BindingState(phase="starting")
        self._task: asyncio.Task | None = None
        self._refresh = asyncio.Event()
        self._disposed = False
        self._generation = 0

    @property
    def phase(self) -> str:
        return self.state.phase

    def _set_state(self, state: BindingState) -> None:
        self.state = state
        if self.on_state is not None:
            try:
                self.on_state(state)
            except Exception:
                pass

    def start(self) -> asyncio.Task:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="qqbot:binding")
        return self._task

    def refresh(self) -> None:
        if self._disposed:
            return
        self._refresh.set()

    async def dispose(self) -> None:
        self._disposed = True
        self._refresh.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.client.close()

    async def _run(self) -> None:
        while not self._disposed:
            self._generation += 1
            generation = self._generation
            self._refresh.clear()
            try:
                task = await self.client.create_task()
            except Exception as exc:
                reason = str(exc)
                self._set_state(BindingState(phase="failed", reason=reason))
                self.logger.warning("QR binding failed: %s", reason)
                if self.on_failure is not None:
                    result = self.on_failure(reason)
                    if asyncio.iscoroutine(result):
                        await result
                return

            url = build_connect_url(task["taskId"])
            qr_svg = ""
            try:
                qr_svg = await asyncio.to_thread(self.render_qr, url)
            except Exception as exc:
                self.logger.warning("QR SVG rendering failed (page will show the link): %s", exc)
            if self._disposed or generation != self._generation:
                return
            self._set_state(
                BindingState(
                    phase="waiting",
                    url=url,
                    qr_svg=qr_svg,
                    issued_at=int(time.time() * 1000),
                )
            )
            self.logger.info("QR binding waiting: %s", url)

            while not self._disposed:
                if self._refresh.is_set():
                    self._refresh.clear()
                    break
                try:
                    result = await self.client.poll(task["taskId"])
                except Exception as exc:
                    self.logger.debug("poll bind result failed: %s", exc)
                    await asyncio.sleep(self.poll_interval)
                    continue
                status = result["status"]
                if status == BIND_STATUS_COMPLETED:
                    try:
                        secret = decrypt_secret(result["botEncryptSecret"], task["key"])
                    except Exception as exc:
                        reason = f"凭据解密失败: {exc}"
                        self._set_state(BindingState(phase="failed", reason=reason))
                        if self.on_failure is not None:
                            maybe = self.on_failure(reason)
                            if asyncio.iscoroutine(maybe):
                                await maybe
                        return
                    credentials = {"appId": result["botAppId"], "appSecret": secret}
                    self._set_state(BindingState(phase="saving"))
                    self.logger.info("QR binding completed appId=%s", credentials["appId"])
                    if self.on_success is not None:
                        maybe = self.on_success(credentials)
                        if asyncio.iscoroutine(maybe):
                            await maybe
                    return
                if status == BIND_STATUS_EXPIRED:
                    self.logger.info("QR code expired; regenerating")
                    break
                await asyncio.sleep(self.poll_interval)
        # disposed


__all__ = [
    "BindingState",
    "BindingService",
    "QQBindClient",
    "generate_bind_key",
    "decrypt_secret",
    "build_connect_url",
    "render_qr_svg_data_url",
]
