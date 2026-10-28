"""QQ Open Platform protocol layer.

This is a behavioural port of the parts of ``@tencent-connect/qqbot-nodejs``
1.0.5 that the upstream plugin actually uses: token management, the REST
message/media APIs, the WebSocket gateway (identify/resume/heartbeat/reconnect)
and C2C stream messages.  It has no Node dependency and no global state.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable
from urllib.parse import quote

import httpx
import websockets

from . import constants as C
from .util import now_ms, parse_timestamp, write_json, jsonc_load


# ── Errors ─────────────────────────────────────────────────────────────────

class QQApiError(RuntimeError):
    def __init__(self, message: str, *, status: int = 0, code: Any = None, path: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.path = path


class UploadDailyLimitExceeded(QQApiError):
    pass


# ── Reply targets / inbound messages ───────────────────────────────────────

@dataclass
class ReplyTarget:
    scope: str
    target_id: str
    msg_id: str = ""
    event_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "targetId": self.target_id,
            "msgId": self.msg_id,
            "eventId": self.event_id,
        }

    @property
    def key(self) -> str:
        return f"{self.scope}:{self.target_id}"


@dataclass
class InboundMessage:
    raw_event_type: str
    kind: str
    sender_id: str
    content: str = ""
    sender_name: str = ""
    message_id: str = ""
    timestamp: str = ""
    group_openid: str = ""
    msg_type: int | None = None
    attachments: list[dict[str, Any]] = field(default_factory=list)
    mentions: list[dict[str, Any]] = field(default_factory=list)
    message_scene: dict[str, Any] | None = None
    msg_elements: list[dict[str, Any]] = field(default_factory=list)
    ref_msg_idx: str = ""
    msg_idx: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def scope(self) -> str:
        if self.kind == "group":
            return "group"
        if self.kind in {"c2c", "dm"}:
            return "c2c"
        return self.kind

    @property
    def peer_id(self) -> str:
        if self.kind == "group":
            return self.group_openid or self.sender_id
        return self.sender_id

    @property
    def is_group(self) -> bool:
        return self.kind == "group"

    @property
    def reply_target(self) -> ReplyTarget:
        return ReplyTarget(self.scope, self.peer_id, self.message_id)

    @property
    def timestamp_ms(self) -> int:
        return parse_timestamp(self.timestamp)


def _parse_ref_indices(
    ext: Any,
    msg_type: int | None,
    msg_elements: Any,
) -> tuple[str, str]:
    ref_msg_idx = ""
    msg_idx = ""
    if isinstance(ext, list):
        for entry in ext:
            if not isinstance(entry, str) or "=" not in entry:
                continue
            key, value = entry.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not value:
                continue
            if key == "msg_idx":
                msg_idx = value
            elif key == "ref_msg_idx":
                ref_msg_idx = value
    if msg_type == 103 and isinstance(msg_elements, list):
        for element in msg_elements:
            if isinstance(element, dict) and element.get("msg_idx"):
                ref_msg_idx = str(element["msg_idx"])
                break
    return ref_msg_idx, msg_idx


def parse_inbound(event_type: str, data: dict[str, Any]) -> InboundMessage | None:
    """Convert a dispatch payload into an ``InboundMessage``."""
    if not isinstance(data, dict):
        return None
    if event_type == C.EVENT_C2C_MESSAGE_CREATE:
        author = data.get("author") or {}
        ref, idx = _parse_ref_indices(
            (data.get("message_scene") or {}).get("ext"),
            data.get("message_type"),
            data.get("msg_elements"),
        )
        return InboundMessage(
            raw_event_type=event_type,
            kind="c2c",
            sender_id=str(author.get("user_openid") or ""),
            sender_name=str(author.get("username") or ""),
            content=str(data.get("content") or ""),
            message_id=str(data.get("id") or ""),
            timestamp=str(data.get("timestamp") or ""),
            msg_type=data.get("message_type"),
            attachments=list(data.get("attachments") or []),
            message_scene=data.get("message_scene"),
            msg_elements=list(data.get("msg_elements") or []),
            ref_msg_idx=ref,
            msg_idx=idx,
            raw=data,
        )
    if event_type in {C.EVENT_GROUP_AT_MESSAGE_CREATE, C.EVENT_GROUP_MESSAGE_CREATE}:
        author = data.get("author") or {}
        ref, idx = _parse_ref_indices(
            (data.get("message_scene") or {}).get("ext"),
            data.get("message_type"),
            data.get("msg_elements"),
        )
        return InboundMessage(
            raw_event_type=event_type,
            kind="group",
            sender_id=str(author.get("member_openid") or ""),
            sender_name=str(author.get("username") or ""),
            content=str(data.get("content") or ""),
            message_id=str(data.get("id") or ""),
            timestamp=str(data.get("timestamp") or ""),
            group_openid=str(data.get("group_openid") or ""),
            msg_type=data.get("message_type"),
            attachments=list(data.get("attachments") or []),
            mentions=list(data.get("mentions") or []),
            message_scene=data.get("message_scene"),
            msg_elements=list(data.get("msg_elements") or []),
            ref_msg_idx=ref,
            msg_idx=idx,
            raw=data,
        )
    if event_type == C.EVENT_AT_MESSAGE_CREATE:
        author = data.get("author") or {}
        ref, idx = _parse_ref_indices(
            (data.get("message_scene") or {}).get("ext"),
            data.get("message_type"),
            data.get("msg_elements"),
        )
        return InboundMessage(
            raw_event_type=event_type,
            kind="guild",
            sender_id=str(author.get("id") or ""),
            sender_name=str(author.get("username") or ""),
            content=str(data.get("content") or ""),
            message_id=str(data.get("id") or ""),
            timestamp=str(data.get("timestamp") or ""),
            attachments=list(data.get("attachments") or []),
            msg_elements=list(data.get("msg_elements") or []),
            ref_msg_idx=ref,
            msg_idx=idx,
            raw=data,
        )
    if event_type == C.EVENT_DIRECT_MESSAGE_CREATE:
        author = data.get("author") or {}
        ref, idx = _parse_ref_indices(
            (data.get("message_scene") or {}).get("ext"),
            data.get("message_type"),
            data.get("msg_elements"),
        )
        return InboundMessage(
            raw_event_type=event_type,
            kind="dm",
            sender_id=str(author.get("id") or ""),
            sender_name=str(author.get("username") or ""),
            content=str(data.get("content") or ""),
            message_id=str(data.get("id") or ""),
            timestamp=str(data.get("timestamp") or ""),
            attachments=list(data.get("attachments") or []),
            msg_elements=list(data.get("msg_elements") or []),
            ref_msg_idx=ref,
            msg_idx=idx,
            raw=data,
        )
    return None


# ── Token manager ──────────────────────────────────────────────────────────

class TokenManager:
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        client: httpx.AsyncClient,
        base_url: str = C.DEFAULT_TOKEN_BASE_URL,
        user_agent: str = "lamtools-qqbot/0.1.0",
        logger: logging.Logger | None = None,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.logger = logger or logging.getLogger("qqbot")
        self._token = ""
        self._expires_at = 0.0
        self._lock = asyncio.Lock()
        self._refresh_task: asyncio.Task | None = None
        self._stopped = False

    async def get(self) -> str:
        now = time.time()
        # Refresh ahead by at most five minutes, or one third of the remaining
        # lifetime (the same heuristic as the SDK).
        refresh_ahead = min(300.0, max(0.0, (self._expires_at - now) / 3)) if self._token else 0.0
        if self._token and now < self._expires_at - refresh_ahead:
            return self._token
        async with self._lock:
            now = time.time()
            refresh_ahead = min(300.0, max(0.0, (self._expires_at - now) / 3)) if self._token else 0.0
            if self._token and now < self._expires_at - refresh_ahead:
                return self._token
            return await self._fetch()

    async def _fetch(self) -> str:
        url = f"{self.base_url}{C.DEFAULT_TOKEN_PATH}"
        try:
            response = await self.client.post(
                url,
                json={"appId": self.app_id, "clientSecret": self.app_secret},
                headers={"Content-Type": "application/json", "User-Agent": self.user_agent},
                timeout=10.0,
            )
        except Exception as exc:
            raise QQApiError(f"Network error getting access_token: {exc}") from exc
        if response.status_code >= 400:
            body = response.text[:200]
            raise QQApiError(f"Token fetch failed: HTTP {response.status_code} — {body}", status=response.status_code)
        try:
            data = response.json()
        except Exception as exc:
            raise QQApiError("Failed to parse access_token response") from exc
        token = str(data.get("access_token") or "")
        if not token:
            raise QQApiError(f"Failed to get access_token: {json.dumps(data, ensure_ascii=False)[:200]}")
        expires_in = int(data.get("expires_in") or 7200)
        self._token = token
        self._expires_at = time.time() + expires_in
        self.logger.debug("access token refreshed, expires in %ss", expires_in)
        return token

    def clear(self) -> None:
        self._token = ""
        self._expires_at = 0.0

    def start_background_refresh(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._stopped = False
        self._refresh_task = asyncio.create_task(self._refresh_loop(), name="qqbot:token-refresh")

    async def _refresh_loop(self) -> None:
        while not self._stopped:
            try:
                await self.get()
                remaining = self._expires_at - time.time()
                delay = max(60.0, remaining - min(300.0, remaining / 3) - random.random() * 30.0)
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.warning("token refresh failed: %s", exc)
                await asyncio.sleep(5.0)

    async def stop(self) -> None:
        self._stopped = True
        task = self._refresh_task
        self._refresh_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


# ── REST API ───────────────────────────────────────────────────────────────

def _next_msg_seq(msg_id: str | None = None) -> int:
    # The SDK uses a time/random mix; QQ only requires uniqueness in 0..65535.
    del msg_id
    return (int(time.time() * 1000) % 100_000_000 ^ random.randint(0, 65535)) % 65536


class QQApi:
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        base_url: str = C.DEFAULT_API_BASE_URL,
        token_base_url: str = C.DEFAULT_TOKEN_BASE_URL,
        user_agent: str = "lamtools-qqbot/0.1.0",
        logger: logging.Logger | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.logger = logger or logging.getLogger("qqbot")
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(follow_redirects=False)
        self.tokens = TokenManager(
            app_id=app_id,
            app_secret=app_secret,
            client=self.client,
            base_url=token_base_url,
            user_agent=user_agent,
            logger=self.logger,
        )

    async def close(self) -> None:
        await self.tokens.stop()
        if self._owns_client:
            await self.client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
        upload: bool = False,
    ) -> dict[str, Any]:
        token = await self.tokens.get()
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"QQBot {token}",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        try:
            response = await self.client.request(
                method,
                url,
                headers=headers,
                json=body,
                timeout=120.0 if upload else timeout,
            )
        except Exception as exc:
            raise QQApiError(f"Network error [{path}]: {exc}", path=path) from exc
        raw = response.text
        content_type = response.headers.get("content-type", "")
        is_html = "text/html" in content_type or raw.lstrip().startswith("<")
        if response.status_code >= 400:
            if is_html:
                hint = (
                    "调用发生异常，请稍候重试"
                    if response.status_code in {502, 503, 504}
                    else "请求过于频繁，已被限流"
                    if response.status_code == 429
                    else f"开放平台返回 HTTP {response.status_code}"
                )
                raise QQApiError(f"{hint}（{path}）", status=response.status_code, path=path)
            try:
                error = json.loads(raw)
                code = error.get("code", error.get("err_code"))
                message = error.get("message") or raw[:200]
                raise QQApiError(f"API Error [{path}]: {message}", status=response.status_code, code=code, path=path)
            except QQApiError:
                raise
            except Exception:
                raise QQApiError(
                    f"API Error [{path}] HTTP {response.status_code}: {raw[:200]}",
                    status=response.status_code,
                    path=path,
                )
        if is_html:
            raise QQApiError(f"QQ 服务端返回了非 JSON 响应（{path}）", status=response.status_code, path=path)
        try:
            value = json.loads(raw) if raw else {}
        except Exception as exc:
            raise QQApiError(f"开放平台响应格式异常（{path}）", status=response.status_code, path=path) from exc
        return value if isinstance(value, dict) else {"data": value}

    async def get_gateway_url(self) -> str:
        data = await self.request("GET", C.DEFAULT_GATEWAY_PATH)
        url = str(data.get("url") or "")
        if not url:
            raise QQApiError("gateway response has no url")
        return url

    # ── messages ───────────────────────────────────────────────────────────
    @staticmethod
    def message_path(scope: str, target_id: str) -> str:
        return f"/v2/users/{quote(str(target_id), safe='')}/messages" if scope == "c2c" else f"/v2/groups/{quote(str(target_id), safe='')}/messages"

    async def send_raw(self, target: ReplyTarget, body: dict[str, Any]) -> dict[str, Any]:
        payload = {key: value for key, value in dict(body).items() if value is not None}
        if "msg_seq" not in payload:
            payload["msg_seq"] = _next_msg_seq(payload.get("msg_id"))
        if "msg_type" not in payload:
            if payload.get("markdown"):
                payload["msg_type"] = C.MSG_TYPE_MARKDOWN
            elif payload.get("ark"):
                payload["msg_type"] = C.MSG_TYPE_ARK
            elif payload.get("embed"):
                payload["msg_type"] = C.MSG_TYPE_EMBED
            elif payload.get("media"):
                payload["msg_type"] = C.MSG_TYPE_MEDIA
            else:
                payload["msg_type"] = C.MSG_TYPE_TEXT
        if target.msg_id:
            payload.setdefault("msg_id", target.msg_id)
        if target.event_id:
            payload.setdefault("event_id", target.event_id)
        return await self.request("POST", self.message_path(target.scope, target.target_id), payload)

    async def send_markdown(
        self,
        target: ReplyTarget,
        content: str,
        keyboard: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"msg_type": C.MSG_TYPE_MARKDOWN, "markdown": {"content": content}}
        if keyboard:
            body["keyboard"] = keyboard
        return await self.send_raw(target, body)

    async def send_text(self, target: ReplyTarget, content: str) -> dict[str, Any]:
        return await self.send_raw(target, {"msg_type": C.MSG_TYPE_TEXT, "content": content})

    async def send_proactive_markdown(self, target: ReplyTarget, content: str) -> dict[str, Any]:
        return await self.send_raw(
            ReplyTarget(target.scope, target.target_id),
            {"msg_type": C.MSG_TYPE_MARKDOWN, "markdown": {"content": content}},
        )

    async def send_typing(self, target: ReplyTarget, seconds: int = C.DEFAULT_TYPING_SECONDS) -> dict[str, Any]:
        return await self.send_raw(
            target,
            {
                "msg_type": C.MSG_TYPE_INPUT_NOTIFY,
                "input_notify": {"input_type": 1, "input_second": max(1, int(seconds))},
            },
        )

    async def acknowledge_interaction(self, interaction_id: str, code: int = 0, data: dict[str, Any] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"code": int(code)}
        if data:
            body["data"] = data
        return await self.request("PUT", f"/interactions/{quote(str(interaction_id), safe='')}", body)

    async def recall(self, target: ReplyTarget, message_id: str) -> dict[str, Any]:
        path = f"{self.message_path(target.scope, target.target_id)}/{quote(str(message_id), safe='')}"
        return await self.request("DELETE", path)

    # ── C2C streaming ──────────────────────────────────────────────────────
    async def send_stream_chunk(
        self,
        target: ReplyTarget,
        *,
        text: str,
        state: str,
        index: int,
        msg_seq: int,
        stream_msg_id: str = "",
    ) -> dict[str, Any]:
        if target.scope != "c2c":
            raise QQApiError("streaming is only supported for C2C targets")
        body: dict[str, Any] = {
            "input_mode": "replace",
            "input_state": state,
            "content_type": "markdown",
            "content_raw": text,
            "msg_seq": msg_seq,
            "index": index,
        }
        if target.event_id:
            body["event_id"] = target.event_id
        if target.msg_id:
            body["msg_id"] = target.msg_id
        if stream_msg_id:
            body["stream_msg_id"] = stream_msg_id
        return await self.request("POST", f"/v2/users/{quote(str(target.target_id), safe='')}/stream_messages", body)

    def open_stream(self, target: ReplyTarget, *, throttle_ms: int = C.DEFAULT_STREAM_THROTTLE_MS) -> "StreamSession":
        return StreamSession(self, target, throttle_ms=throttle_ms)

    # ── media ──────────────────────────────────────────────────────────────
    @staticmethod
    def media_path(scope: str, target_id: str) -> str:
        return f"/v2/users/{quote(str(target_id), safe='')}/files" if scope == "c2c" else f"/v2/groups/{quote(str(target_id), safe='')}/files"

    async def upload_media(
        self,
        target: ReplyTarget,
        file_type: int,
        *,
        data: bytes | None = None,
        local_path: str | Path | None = None,
        file_name: str = "",
        url: str = "",
    ) -> dict[str, Any]:
        if url:
            body: dict[str, Any] = {"file_type": file_type, "srv_send_msg": False, "url": url}
            if file_type == C.MEDIA_TYPE_FILE and file_name:
                body["file_name"] = file_name
            return await self.request("POST", self.media_path(target.scope, target.target_id), body, upload=True)

        if data is None and local_path is not None:
            data = await asyncio.to_thread(Path(local_path).read_bytes)
        if data is None:
            raise QQApiError("upload_media requires data, local_path or url")
        if len(data) > C.CHUNKED_UPLOAD_MAX_SIZE:
            raise QQApiError(
                f"文件超过 QQ 单次上传上限（{len(data) / 1024 / 1024:.1f}MB > 100MB）"
            )
        if len(data) >= C.LARGE_FILE_THRESHOLD:
            return await self._upload_chunked(target, file_type, data, file_name)
        encoded = base64.b64encode(data).decode("ascii")
        body = {"file_type": file_type, "srv_send_msg": False, "file_data": encoded}
        if file_type == C.MEDIA_TYPE_FILE and file_name:
            body["file_name"] = file_name
        return await self.request("POST", self.media_path(target.scope, target.target_id), body, upload=True)

    async def _upload_chunked(
        self,
        target: ReplyTarget,
        file_type: int,
        data: bytes,
        file_name: str,
    ) -> dict[str, Any]:
        """Port of the SDK's chunked upload path (files >= 5MB)."""
        size = len(data)
        md5 = hashlib.md5(data).hexdigest()
        sha1 = hashlib.sha1(data).hexdigest()
        md5_10m = hashlib.md5(data[: 10_002_432]).hexdigest() if size > 10_002_432 else md5
        prepare_path = (
            f"/v2/users/{quote(str(target.target_id), safe='')}/upload_prepare"
            if target.scope == "c2c"
            else f"/v2/groups/{quote(str(target.target_id), safe='')}/upload_prepare"
        )
        prepare = await self.request(
            "POST",
            prepare_path,
            {
                "file_type": file_type,
                "file_name": file_name or "file",
                "file_size": size,
                "md5": md5,
                "sha1": sha1,
                "md5_10m": md5_10m,
            },
            upload=True,
        )
        upload_id = str(prepare.get("upload_id") or "")
        parts = prepare.get("parts") or []
        block_size = int(prepare.get("block_size") or 0)
        if not upload_id or not parts or block_size <= 0:
            raise QQApiError("upload_prepare returned an incomplete plan")
        finish_path = (
            f"/v2/users/{quote(str(target.target_id), safe='')}/upload_part_finish"
            if target.scope == "c2c"
            else f"/v2/groups/{quote(str(target.target_id), safe='')}/upload_part_finish"
        )
        concurrency = max(1, min(int(prepare.get("concurrency") or 1), 10))
        semaphore = asyncio.Semaphore(concurrency)

        async def upload_part(part: dict[str, Any]) -> None:
            index = int(part.get("index") or 0)
            offset = (index - 1) * block_size
            chunk = data[offset : offset + block_size]
            presigned = str(part.get("presigned_url") or "")
            if not presigned:
                raise QQApiError(f"upload part {index} has no presigned_url")
            async with semaphore:
                try:
                    put = await self.client.put(
                        presigned,
                        content=chunk,
                        headers={"Content-Length": str(len(chunk))},
                        timeout=300.0,
                    )
                except Exception as exc:
                    raise QQApiError(f"COS PUT failed for part {index}: {exc}") from exc
                if put.status_code < 200 or put.status_code >= 300:
                    raise QQApiError(
                        f"COS PUT failed: {put.status_code} {put.text[:120]}",
                        status=put.status_code,
                    )
                await self.request(
                    "POST",
                    finish_path,
                    {
                        "upload_id": upload_id,
                        "part_index": index,
                        "block_size": len(chunk),
                        "md5": hashlib.md5(chunk).hexdigest(),
                    },
                    upload=True,
                )

        await asyncio.gather(*(upload_part(part) for part in parts if isinstance(part, dict)))
        complete_path = self.media_path(target.scope, target.target_id)
        return await self.request("POST", complete_path, {"upload_id": upload_id}, upload=True)

    async def send_media(
        self,
        target: ReplyTarget,
        file_type: int,
        *,
        data: bytes | None = None,
        local_path: str | Path | None = None,
        file_name: str = "",
    ) -> dict[str, Any]:
        upload = await self.upload_media(
            target,
            file_type,
            data=data,
            local_path=local_path,
            file_name=file_name,
        )
        file_info = upload.get("file_info")
        if not file_info:
            raise QQApiError("upload returned no file_info")
        return await self.send_raw(
            target,
            {
                "msg_type": C.MSG_TYPE_MEDIA,
                "media": {"file_info": file_info},
            },
        )


# ── C2C streaming writer ───────────────────────────────────────────────────

class StreamSession:
    def __init__(self, api: QQApi, target: ReplyTarget, *, throttle_ms: int) -> None:
        self.api = api
        self.target = target
        self.throttle_ms = max(int(throttle_ms or C.DEFAULT_STREAM_THROTTLE_MS), C.MIN_STREAM_THROTTLE_MS)
        self.event_id = target.event_id or target.msg_id
        self.msg_seq = _next_msg_seq(target.msg_id)
        self.stream_msg_id = ""
        self.index = 0
        self.pending_text = ""
        self.last_sent_text = ""
        self.last_flush_at = 0.0
        self._flush_task: asyncio.Task | None = None
        self._completed = False
        self._failed = False
        self.sent_count = 0

    @property
    def should_fallback(self) -> bool:
        return self.sent_count == 0

    @property
    def failed(self) -> bool:
        return self._failed

    async def update(self, full_text: str) -> None:
        if self._completed:
            return
        self.pending_text = full_text
        now = time.time()
        elapsed = now - self.last_flush_at
        if self._flush_task is not None and not self._flush_task.done():
            return
        if elapsed >= self.throttle_ms / 1000.0:
            self._flush_task = asyncio.create_task(self._flush("generating"), name="qqbot:stream-flush")
            return
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._delayed_flush(), name="qqbot:stream-delay")

    async def _delayed_flush(self) -> None:
        wait = max(0.0, self.throttle_ms / 1000.0 - (time.time() - self.last_flush_at))
        if wait:
            await asyncio.sleep(wait)
        if not self._completed:
            await self._flush("generating")

    async def _flush(self, state: str) -> None:
        if self._completed and state != "done":
            return
        text = self.pending_text
        if text == self.last_sent_text and state != "done":
            return
        try:
            response = await self.api.send_stream_chunk(
                self.target,
                text=text,
                state=state,
                index=self.index,
                msg_seq=self.msg_seq,
                stream_msg_id=self.stream_msg_id,
            )
            self.index += 1
            self.last_sent_text = text
            self.last_flush_at = time.time()
            self.sent_count += 1
            if not self.stream_msg_id and response.get("id"):
                self.stream_msg_id = str(response["id"])
        except asyncio.CancelledError:
            raise
        except Exception:
            self._failed = True
            raise

    async def complete(self) -> None:
        if self._completed:
            return
        self._completed = True
        task = self._flush_task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        try:
            await self._flush("done")
        except Exception:
            self._failed = True

    def cancel(self) -> None:
        self._completed = True
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()


# ── Reply limiter / msg id cache ───────────────────────────────────────────

@dataclass
class _TrackedMessage:
    count: int
    first_seen_at: float


class ReplyLimiter:
    """Passive-reply quota per inbound message id (upstream default: 4)."""

    def __init__(self, limit: int = C.DEFAULT_REPLY_LIMIT, ttl_ms: int = C.DEFAULT_REPLY_LIMIT_TTL_MS, max_tracked: int = 10_000) -> None:
        self.limit = max(1, int(limit))
        self.ttl = ttl_ms / 1000.0
        self.max_tracked = max_tracked
        self._messages: dict[str, _TrackedMessage] = {}

    def check(self, message_id: str) -> tuple[bool, str]:
        tracked = self._messages.get(message_id)
        if tracked is None:
            return True, ""
        if time.time() - tracked.first_seen_at > self.ttl:
            self._messages.pop(message_id, None)
            return False, "expired"
        if tracked.count >= self.limit:
            return False, "limit_exceeded"
        return True, ""

    def record(self, message_id: str) -> None:
        tracked = self._messages.get(message_id)
        if tracked is not None:
            tracked.count += 1
            return
        if len(self._messages) >= self.max_tracked:
            oldest = next(iter(self._messages), None)
            if oldest is not None:
                self._messages.pop(oldest, None)
        self._messages[message_id] = _TrackedMessage(1, time.time())


@dataclass
class CachedReplyId:
    kind: str  # "msg" | "event"
    id: str


class MsgIdCache:
    def __init__(self) -> None:
        self._cache: dict[str, list[tuple[CachedReplyId, float]]] = {}

    def _push(self, scope: str, target_id: str, item: CachedReplyId) -> None:
        if not target_id or not item.id:
            return
        key = f"{scope}:{target_id}"
        entries = self._cache.setdefault(key, [])
        entries.append((item, time.time()))
        if len(entries) > C.DEFAULT_MSGID_CACHE_PER_TARGET:
            del entries[: len(entries) - C.DEFAULT_MSGID_CACHE_PER_TARGET]
        if len(self._cache) > C.DEFAULT_MSGID_CACHE_TARGETS:
            oldest = next(iter(self._cache), None)
            if oldest is not None and oldest != key:
                self._cache.pop(oldest, None)

    def cache_msg(self, scope: str, target_id: str, msg_id: str) -> None:
        if msg_id:
            self._push(scope, target_id, CachedReplyId("msg", msg_id))

    def cache_event(self, scope: str, target_id: str, event_id: str) -> None:
        if event_id:
            self._push(scope, target_id, CachedReplyId("event", C.EVENT_ID_PREFIX + event_id))

    def get(self, scope: str, target_id: str) -> list[CachedReplyId]:
        entries = self._cache.get(f"{scope}:{target_id}", [])
        ttl = C.GROUP_REPLY_TTL_MS if scope == "group" else C.C2C_REPLY_TTL_MS
        now = time.time()
        result = [item for item, timestamp in reversed(entries) if (now - timestamp) * 1000 < ttl]
        return result


def resolve_reply_target(
    target: ReplyTarget,
    limiter: ReplyLimiter,
    cache: MsgIdCache,
    *,
    allow_event: bool,
) -> ReplyTarget:
    """Pick a passive-reply id, falling back to a proactive message.

    The upstream implementation tries the explicit msgId first, then cached
    msg/event ids, then drops both ids (proactive push).  The same order is
    kept here; file sends pass ``allow_event=False`` because the QQ file API
    does not accept ``event_id``.
    """
    candidates: list[CachedReplyId] = []
    if target.msg_id:
        candidates.append(CachedReplyId("msg", target.msg_id))
    candidates.extend(cache.get(target.scope, target.target_id))
    for candidate in candidates:
        if candidate.kind == "event" and not allow_event:
            continue
        allowed, _reason = limiter.check(candidate.id)
        if allowed:
            limiter.record(candidate.id)
            if candidate.kind == "event":
                return ReplyTarget(target.scope, target.target_id, "", candidate.id)
            return ReplyTarget(target.scope, target.target_id, candidate.id, "")
    return ReplyTarget(target.scope, target.target_id)


# ── Gateway ────────────────────────────────────────────────────────────────

class GatewaySessionStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "gateway-session.json"

    def load(self) -> dict[str, Any] | None:
        raw = jsonc_load(self.path, default=None)
        if isinstance(raw, dict) and raw.get("sessionId"):
            return raw
        return None

    def save(self, session_id: str, last_seq: int | None) -> None:
        try:
            write_json(self.path, {"sessionId": session_id, "lastSeq": last_seq})
        except Exception:
            pass

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except Exception:
            pass


class QQGateway:
    """WebSocket gateway with identify/resume/heartbeat and reconnects."""

    def __init__(
        self,
        *,
        api: QQApi,
        user_agent: str,
        logger: logging.Logger,
        session_store: GatewaySessionStore,
        on_message: Callable[[InboundMessage], Awaitable[None]],
        on_interaction: Callable[[dict[str, Any]], Awaitable[None]],
        on_ready: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_resumed: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_disconnected: Callable[[int, str, bool], Awaitable[None]] | None = None,
        on_error: Callable[[Exception], Awaitable[None]] | None = None,
        on_raw: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        intents: int = C.FULL_INTENTS,
    ) -> None:
        self.api = api
        self.user_agent = user_agent
        self.logger = logger
        self.session_store = session_store
        self.on_message = on_message
        self.on_interaction = on_interaction
        self.on_ready = on_ready
        self.on_resumed = on_resumed
        self.on_disconnected = on_disconnected
        self.on_error = on_error
        self.on_raw = on_raw
        self.intents = intents
        self.session_id: str | None = None
        self.last_seq: int | None = None
        self.connected = False
        self._task: asyncio.Task | None = None
        self._stopped = False
        self._ws: Any = None
        self._heartbeat_task: asyncio.Task | None = None
        self._heartbeat_interval = 0.0
        self._last_ack = 0.0
        self._attempt = 0
        self._last_close_code = 0
        self._last_close_reason = ""

    def start(self) -> asyncio.Task:
        if self._task is not None and not self._task.done():
            return self._task
        self._stopped = False
        self._task = asyncio.create_task(self._run(), name="qqbot:gateway")
        return self._task

    async def stop(self) -> None:
        self._stopped = True
        await self._cancel_heartbeat()
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.connected = False

    async def _cancel_heartbeat(self) -> None:
        task = self._heartbeat_task
        self._heartbeat_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while not self._stopped:
            try:
                url = await self.api.get_gateway_url()
                self.logger.info("connecting QQ gateway: %s", url)
                async with websockets.connect(
                    url,
                    additional_headers={"User-Agent": self.user_agent},
                    open_timeout=30.0,
                    ping_interval=None,
                    max_size=16 * 1024 * 1024,
                ) as ws:
                    self._ws = ws
                    self._attempt = 0
                    await self._receive_loop(ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stopped:
                    break
                self.logger.warning("QQ gateway error: %s", exc)
                if self.on_error is not None:
                    try:
                        await self.on_error(exc)
                    except Exception:
                        pass
            finally:
                self._ws = None
                self.connected = False
                await self._cancel_heartbeat()
            if self._stopped:
                break
            delay = C.RECONNECT_DELAYS[min(self._attempt, len(C.RECONNECT_DELAYS) - 1)]
            self._attempt += 1
            self.logger.info("reconnecting QQ gateway in %.1fs (attempt %s)", delay, self._attempt)
            if self.on_disconnected is not None:
                try:
                    await self.on_disconnected(self._last_close_code, self._last_close_reason, True)
                except Exception:
                    pass
            await asyncio.sleep(delay)

    async def _receive_loop(self, ws: Any) -> None:
        async for raw in ws:
            if self._stopped:
                break
            try:
                payload = json.loads(raw)
            except Exception:
                self.logger.warning("QQ gateway sent non-JSON frame")
                continue
            await self._handle_payload(payload)
            if payload.get("op") == C.OP_DISPATCH and payload.get("t") == C.EVENT_READY:
                self.connected = True
        # The async-for exits on close; the context manager reports the code
        # only through an exception on some websockets versions.
        self.connected = False

    async def _handle_payload(self, payload: dict[str, Any]) -> None:
        op = payload.get("op")
        d = payload.get("d")
        seq = payload.get("s")
        if seq is not None:
            self.last_seq = int(seq)
            if self.session_id:
                self.session_store.save(self.session_id, self.last_seq)
        if op == C.OP_HELLO:
            interval = float((d or {}).get("heartbeat_interval") or 30000) / 1000.0
            self._heartbeat_interval = max(1.0, interval)
            await self._send_identify_or_resume()
            await self._start_heartbeat()
            return
        if op == C.OP_DISPATCH:
            await self._dispatch(str(payload.get("t") or ""), d if isinstance(d, dict) else {})
            return
        if op == C.OP_HEARTBEAT_ACK:
            self._last_ack = time.time()
            return
        if op == C.OP_RECONNECT:
            self.logger.info("QQ gateway requested reconnect")
            await self._force_reconnect(0)
            return
        if op == C.OP_INVALID_SESSION:
            can_resume = bool(d)
            if not can_resume:
                self.session_id = None
                self.last_seq = None
                self.session_store.clear()
                self.api.tokens.clear()
            self.logger.info("QQ gateway invalid session (resume=%s)", can_resume)
            await self._force_reconnect(C.INVALID_SESSION_DELAY)
            return

    async def _force_reconnect(self, delay: float) -> None:
        ws = self._ws
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        if delay:
            await asyncio.sleep(delay)

    async def _send_identify_or_resume(self) -> None:
        ws = self._ws
        if ws is None:
            return
        token = await self.api.tokens.get()
        if self.session_id and self.last_seq is not None:
            await ws.send(
                json.dumps(
                    {
                        "op": C.OP_RESUME,
                        "d": {
                            "token": f"QQBot {token}",
                            "session_id": self.session_id,
                            "seq": self.last_seq,
                        },
                    }
                )
            )
            self.logger.info("QQ gateway resume sent")
        else:
            await ws.send(
                json.dumps(
                    {
                        "op": C.OP_IDENTIFY,
                        "d": {
                            "token": f"QQBot {token}",
                            "intents": self.intents,
                            "shard": [0, 1],
                        },
                    }
                )
            )
            self.logger.info("QQ gateway identify sent")

    async def _start_heartbeat(self) -> None:
        await self._cancel_heartbeat()
        self._last_ack = time.time()

        async def beat() -> None:
            while not self._stopped:
                await asyncio.sleep(self._heartbeat_interval)
                ws = self._ws
                if ws is None:
                    return
                if time.time() - self._last_ack > self._heartbeat_interval * 2:
                    self.logger.warning("QQ gateway heartbeat timeout")
                    try:
                        await ws.close()
                    except Exception:
                        pass
                    return
                try:
                    await ws.send(json.dumps({"op": C.OP_HEARTBEAT, "d": self.last_seq}))
                except Exception:
                    return

        self._heartbeat_task = asyncio.create_task(beat(), name="qqbot:heartbeat")

    async def _dispatch(self, event_type: str, data: dict[str, Any]) -> None:
        if event_type == C.EVENT_READY:
            self.session_id = str(data.get("session_id") or "") or None
            self.last_seq = self.last_seq or 0
            if self.session_id:
                self.session_store.save(self.session_id, self.last_seq)
            self.connected = True
            if self.on_ready is not None:
                await self.on_ready(data)
            return
        if event_type == C.EVENT_RESUMED:
            self.connected = True
            if self.on_resumed is not None:
                await self.on_resumed(data)
            return
        if event_type == C.EVENT_INTERACTION_CREATE:
            if self.on_interaction is not None:
                await self.on_interaction(data)
            return
        if event_type in C.MESSAGE_EVENTS:
            message = parse_inbound(event_type, data)
            if message is not None and self.on_message is not None:
                await self.on_message(message)
            return
        if self.on_raw is not None:
            await self.on_raw(event_type, data)


__all__ = [
    "QQApiError",
    "UploadDailyLimitExceeded",
    "ReplyTarget",
    "InboundMessage",
    "parse_inbound",
    "TokenManager",
    "QQApi",
    "StreamSession",
    "ReplyLimiter",
    "MsgIdCache",
    "resolve_reply_target",
    "GatewaySessionStore",
    "QQGateway",
]
