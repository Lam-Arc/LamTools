"""Inbound middleware chain.

The order mirrors the upstream ``setupMiddlewares`` call:

1. message filter (self-echo + dedup)
2. access policy
3. group history buffer (records messages even when they are skipped)
4. mention gate
5. content sanitizer
6. rate limiter (disabled by default, exactly like the upstream call)
7. slash commands / pending question answers (handled by the runtime before
   the concurrency guard, because they must not be queued)
8. concurrency guard (merge strategy, implemented in the runtime)
9. typing indicator
10. quote reference
11. attachment download
12. envelope formatter
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable

from .protocol import InboundMessage, ReplyTarget
from .util import format_file_size, parse_timestamp, short_sender_id

Next = Callable[[], Awaitable[None]]
Middleware = Callable[["MiddlewareContext", Next], Awaitable[None]]


@dataclass
class MiddlewareContext:
    message: InboundMessage
    bot: Any = None
    state: dict[str, Any] = field(default_factory=dict)
    received_at: float = field(default_factory=time.time)
    stopped: bool = False
    stop_reason: str = ""
    aborted: bool = False
    command: dict[str, Any] | None = None

    @property
    def reply_target(self) -> ReplyTarget:
        return self.message.reply_target

    def stop(self, reason: str = "") -> None:
        self.stopped = True
        self.stop_reason = reason

    def abort(self, reason: str = "") -> None:
        self.aborted = True
        self.stop(reason)


async def run_chain(middlewares: Iterable[Middleware], ctx: MiddlewareContext) -> None:
    chain = list(middlewares)

    async def dispatch(index: int) -> None:
        if index >= len(chain) or ctx.stopped:
            return
        await chain[index](ctx, lambda: dispatch(index + 1))

    await dispatch(0)


# ── Stores ─────────────────────────────────────────────────────────────────

class MemoryHistoryStore:
    def __init__(self) -> None:
        self._buffers: dict[str, list[dict[str, Any]]] = {}

    def append(self, group_key: str, entry: dict[str, Any], limit: int) -> None:
        buffer = self._buffers.setdefault(group_key, [])
        if any(item.get("messageId") == entry.get("messageId") for item in buffer):
            return
        buffer.append(entry)
        if len(buffer) > limit:
            del buffer[: len(buffer) - limit]

    def list(self, group_key: str, limit: int) -> list[dict[str, Any]]:
        return list(self._buffers.get(group_key, []))[-limit:]

    def clear(self, group_key: str) -> None:
        self._buffers.pop(group_key, None)

    def size(self) -> int:
        return len(self._buffers)


class MemoryRefIndexStore:
    def __init__(self, max_size: int = 500) -> None:
        self.max_size = max(1, int(max_size))
        self._map: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        return self._map.get(key)

    def set(self, key: str, entry: dict[str, Any]) -> None:
        if len(self._map) >= self.max_size and key not in self._map:
            oldest = next(iter(self._map), None)
            if oldest is not None:
                self._map.pop(oldest, None)
        self._map[key] = entry


# ── Middleware implementations ─────────────────────────────────────────────

def message_filter(
    *,
    skip_self_echo: bool = False,
    dedup_window_ms: int = 5000,
    max_size: int = 1000,
    logger: logging.Logger | None = None,
) -> Middleware:
    seen: dict[str, float] = {}
    window = dedup_window_ms / 1000.0

    async def middleware(ctx: MiddlewareContext, next_fn: Next) -> None:
        message = ctx.message
        if skip_self_echo and (message.raw.get("author") or {}).get("bot"):
            ctx.stop("self-echo")
            return
        message_id = message.message_id
        now = time.time()
        if message_id:
            previous = seen.get(message_id)
            if previous is not None and now - previous <= window:
                if logger is not None:
                    logger.debug("dropping duplicate messageId=%s", message_id)
                ctx.stop("deduplication")
                return
            seen[message_id] = now
            if len(seen) > max_size:
                cutoff = now - window
                for key in [key for key, value in seen.items() if value < cutoff]:
                    seen.pop(key, None)
                if len(seen) > max_size:
                    oldest = next(iter(seen), None)
                    if oldest is not None:
                        seen.pop(oldest, None)
        await next_fn()

    return middleware


def access_policy(access: dict[str, Any], *, logger: logging.Logger | None = None) -> Middleware:
    def matches(policy: dict[str, Any], identifier: str) -> tuple[bool, str]:
        mode = str(policy.get("mode") or "open")
        if mode == "disabled":
            return False, "scope disabled"
        if mode == "open":
            return True, ""
        allow = [str(item) for item in (policy.get("allow") or []) if str(item)]
        if not allow:
            return False, "allowlist is empty"
        if "*" in allow or identifier in allow:
            return True, ""
        return False, f"not in allowlist ({identifier})"

    async def middleware(ctx: MiddlewareContext, next_fn: Next) -> None:
        message = ctx.message
        if message.scope == "c2c":
            allowed, reason = matches(
                {"mode": access.get("c2cMode"), "allow": access.get("c2cAllow") or ["*"]},
                message.sender_id,
            )
        elif message.scope == "group":
            allowed, reason = matches(
                {"mode": access.get("groupMode"), "allow": access.get("groupAllow") or ["*"]},
                message.group_openid or "",
            )
        else:
            allowed, reason = True, ""
        if not allowed:
            if logger is not None:
                logger.debug("access blocked %s message from %s: %s", message.kind, message.sender_id, reason)
            ctx.stop(f"access:{reason}")
            return
        await next_fn()

    return middleware


def history_buffer(
    store: MemoryHistoryStore,
    *,
    limit: int,
    group_key: Callable[[MiddlewareContext], str | None],
    record_on_skip: bool = True,
    logger: logging.Logger | None = None,
) -> Middleware:
    async def middleware(ctx: MiddlewareContext, next_fn: Next) -> None:
        key = group_key(ctx)
        if not key:
            await next_fn()
            return
        ctx.state["history"] = store.list(key, max(0, limit))
        entry = {
            "senderId": ctx.message.sender_id,
            "senderName": ctx.message.sender_name,
            "content": ctx.message.content,
            "timestamp": ctx.message.timestamp_ms,
            "messageId": ctx.message.message_id,
        }
        try:
            store.append(key, entry, max(0, limit))
        except Exception as exc:
            if logger is not None:
                logger.warning("history append failed: %s", exc)
        if ctx.stopped and not record_on_skip:
            return
        await next_fn()

    return middleware


def mention_gate(*, require_mention: bool = True, logger: logging.Logger | None = None) -> Middleware:
    async def middleware(ctx: MiddlewareContext, next_fn: Next) -> None:
        message = ctx.message
        if message.kind != "group":
            ctx.state["mention"] = {
                "wasMentioned": True,
                "implicit": False,
                "shouldAnswer": True,
                "reason": "passthrough",
            }
            await next_fn()
            return
        app_id = str(getattr(ctx.bot, "app_id", "") or "")
        mentioned = message.raw_event_type == "GROUP_AT_MESSAGE_CREATE"
        if not mentioned and isinstance(message.mentions, list):
            mentioned = any(bool(item.get("is_you")) for item in message.mentions if isinstance(item, dict))
        if not mentioned and app_id:
            mentioned = re.search(rf"<@!?{re.escape(app_id)}>", message.content or "") is not None
        should_answer = (not require_mention) or mentioned
        reason = "passthrough" if should_answer else "no_mention"
        ctx.state["mention"] = {
            "wasMentioned": mentioned,
            "implicit": False,
            "shouldAnswer": should_answer,
            "reason": reason,
        }
        if not should_answer:
            if logger is not None:
                logger.debug("mention gate skipped group message (no_mention)")
            ctx.stop("mention-gate:no_mention")
            return
        await next_fn()

    return middleware


_FACE_TAGS = {
    "0": "😊", "1": "😣", "2": "😍", "4": "😎", "5": "😭", "6": "😳",
    "7": "🤐", "8": "😴", "9": "😢", "10": "😰", "11": "😡", "12": "🤗",
    "13": "⭐", "14": "🌟", "15": "🌙", "16": "👍", "18": "✊", "21": "😊",
    "23": "😢", "25": "🤔", "26": "😱", "27": "😅", "28": "😁", "29": "🤮",
    "30": "💪", "32": "🎉", "33": "😤", "34": "😏", "35": "🥺", "49": "🐷",
    "53": "🎂", "60": "☕", "63": "🌹", "66": "❤️", "74": "🌞", "75": "🌛",
    "76": "👏", "78": "🤝", "79": "✌️", "85": "🎅", "89": "🍉", "96": "😓",
    "97": "😲", "100": "😂", "101": "😊", "104": "😭", "106": "😱", "109": "😘",
    "111": "🥰",
}


def content_sanitizer(*, parse_face_tags: bool = True) -> Middleware:
    async def middleware(ctx: MiddlewareContext, next_fn: Next) -> None:
        content = ctx.message.content or ""
        app_id = str(getattr(ctx.bot, "app_id", "") or "")
        if app_id:
            content = re.sub(rf"<@!?{re.escape(app_id)}>\s*", "", content)
        if parse_face_tags:
            content = re.sub(
                r"\[<face,id=(\d+)/?>]",
                lambda match: _FACE_TAGS.get(match.group(1), ""),
                content,
            )
            content = re.sub(
                r'<faceType=\d+,faceId="[^"]*",ext="([^"]*)">',
                lambda match: _decode_face_tag(match.group(1)),
                content,
            )
        else:
            content = re.sub(r"\[<face,id=\d+/?>]", "", content)
            content = re.sub(r'<faceType=\d+,faceId="[^"]*",ext="[^"]*">', "", content)
        ctx.message.content = content.strip()
        await next_fn()

    return middleware


def _decode_face_tag(encoded: str) -> str:
    import base64
    import json

    try:
        payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
        return f"【表情: {payload.get('text') or '未知表情'}】"
    except Exception:
        return ""


class SlidingWindow:
    def __init__(self, max_events: int, window_ms: int) -> None:
        self.max_events = max(1, int(max_events))
        self.window = max(1, int(window_ms)) / 1000.0
        self._buckets: dict[str, list[float]] = {}

    def check(self, key: str) -> bool:
        now = time.time()
        bucket = self._buckets.setdefault(key, [])
        while bucket and now - bucket[0] > self.window:
            bucket.pop(0)
        if len(bucket) >= self.max_events:
            return False
        bucket.append(now)
        return True


def rate_limiter(
    *,
    per_sender: tuple[int, int] | None = None,
    per_group: tuple[int, int] | None = None,
    global_limit: tuple[int, int] | None = None,
) -> Middleware:
    sender_window = SlidingWindow(*per_sender) if per_sender else None
    group_window = SlidingWindow(*per_group) if per_group else None
    global_window = SlidingWindow(*global_limit) if global_limit else None

    async def middleware(ctx: MiddlewareContext, next_fn: Next) -> None:
        message = ctx.message
        group_key = message.group_openid or message.sender_id
        if global_window is not None and not global_window.check("__global__"):
            ctx.stop("rate-limit:global")
            return
        if group_window is not None and not group_window.check(group_key):
            ctx.stop("rate-limit:perGroup")
            return
        if sender_window is not None and not sender_window.check(message.sender_id):
            ctx.stop("rate-limit:perSender")
            return
        await next_fn()

    return middleware


def typing_indicator(
    *,
    api: Any,
    duration_sec: int = 60,
    keepalive_ms: int = 50_000,
    logger: logging.Logger | None = None,
) -> Middleware:
    async def middleware(ctx: MiddlewareContext, next_fn: Next) -> None:
        if ctx.message.kind != "c2c":
            await next_fn()
            return
        import asyncio

        async def send_typing() -> None:
            try:
                await api.send_typing(ctx.reply_target, duration_sec)
            except Exception as exc:
                if logger is not None:
                    logger.debug("typing indicator failed: %s", exc)

        await send_typing()
        task = asyncio.create_task(_typing_keepalive(send_typing, keepalive_ms), name="qqbot:typing")
        try:
            await next_fn()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return middleware


async def _typing_keepalive(send: Callable[[], Awaitable[None]], interval_ms: int) -> None:
    import asyncio

    while True:
        await asyncio.sleep(max(1000, interval_ms) / 1000.0)
        await send()


def quote_ref(
    store: MemoryRefIndexStore,
    *,
    content_limit: int = 200,
    prefer_msg_elements: bool = True,
    logger: logging.Logger | None = None,
) -> Middleware:
    async def middleware(ctx: MiddlewareContext, next_fn: Next) -> None:
        message = ctx.message
        key = message.msg_idx or message.message_id
        if key:
            store.set(
                key,
                {
                    "messageId": message.message_id,
                    "senderId": message.sender_id,
                    "senderName": message.sender_name,
                    "content": (message.content or "")[:content_limit],
                    "timestamp": message.timestamp,
                    "isBot": bool((message.raw.get("author") or {}).get("bot")),
                    "scope": message.kind,
                },
            )
        ref_key = message.ref_msg_idx
        if ref_key:
            entry = store.get(ref_key)
            elements_quote = _quote_from_elements(message) if prefer_msg_elements else None
            if elements_quote is not None:
                ctx.state["quote"] = elements_quote
            elif entry is not None:
                ctx.state["quote"] = {
                    "refKey": ref_key,
                    "source": "store",
                    "entry": entry,
                    "text": entry.get("content") or "[empty message]",
                }
            else:
                ctx.state["quote"] = {"refKey": ref_key, "source": "none", "text": ""}
            if logger is not None:
                logger.debug("quote ref resolved refKey=%s", ref_key)
        await next_fn()

    return middleware


def _quote_from_elements(message: InboundMessage) -> dict[str, Any] | None:
    elements = message.msg_elements
    if not isinstance(elements, list) or not elements:
        return None
    first = elements[0]
    if not isinstance(first, dict):
        return None
    content = str(first.get("content") or "")
    raw_attachments = first.get("attachments") or []
    if not content and not raw_attachments:
        return None
    attachments = [
        {
            "contentType": item.get("content_type"),
            "url": item.get("url"),
            "filename": item.get("filename"),
            "asrText": item.get("asr_refer_text"),
        }
        for item in raw_attachments
        if isinstance(item, dict)
    ]
    return {
        "refKey": message.ref_msg_idx,
        "source": "msg_elements",
        "rawContent": content,
        "attachments": attachments,
        "text": _quote_text(content, attachments),
    }


def _quote_text(content: str, attachments: list[dict[str, Any]]) -> str:
    parts = []
    if content.strip():
        parts.append(content.strip())
    for attachment in attachments:
        content_type = str(attachment.get("contentType") or "").lower()
        if content_type.startswith("audio/"):
            parts.append(f"[voice: {attachment.get('asrText')}]" if attachment.get("asrText") else "[voice]")
        elif content_type.startswith("image/"):
            parts.append(f"[image: {attachment.get('filename')}]" if attachment.get("filename") else "[image]")
        elif content_type.startswith("video/"):
            parts.append(f"[video: {attachment.get('filename')}]" if attachment.get("filename") else "[video]")
        else:
            parts.append(f"[file: {attachment.get('filename') or 'untitled'}]")
    return "\n".join(parts) or "[empty message]"


def attachment_processor(
    *,
    downloader: Callable[[list[dict[str, Any]], Any], Awaitable[list[dict[str, Any]]]],
    media_config: dict[str, Any],
    logger: logging.Logger | None = None,
) -> Middleware:
    async def middleware(ctx: MiddlewareContext, next_fn: Next) -> None:
        try:
            ctx.state["downloadedFiles"] = await downloader(ctx.message.attachments, media_config)
            quote = ctx.state.get("quote") or {}
            quote_attachments = quote.get("attachments") or []
            if quote_attachments:
                raw = [
                    {
                        "content_type": item.get("contentType") or "",
                        "filename": item.get("filename") or "",
                        "size": 0,
                        "url": item.get("url") or "",
                    }
                    for item in quote_attachments
                    if item.get("url")
                ]
                ctx.state["downloadedQuoteFiles"] = await downloader(raw, media_config)
        except Exception as exc:
            if logger is not None:
                logger.warning("attachment download failed: %s", exc)
        await next_fn()

    return middleware


def envelope_formatter(
    *,
    history_limit: int = 5,
    include_quote: bool = True,
    include_sender: bool = True,
) -> Middleware:
    async def middleware(ctx: MiddlewareContext, next_fn: Next) -> None:
        ctx.state["envelope"] = build_envelope(
            ctx,
            history_limit=history_limit,
            include_quote=include_quote,
            include_sender=include_sender,
        )
        await next_fn()

    return middleware


def build_envelope(ctx: MiddlewareContext, *, history_limit: int, include_quote: bool, include_sender: bool) -> str:
    message = ctx.message
    sections: list[str] = []
    if include_sender:
        name = message.sender_name or message.sender_id
        scope = f"group({message.group_openid or 'unknown'})" if message.kind == "group" else message.kind
        sections.append(f"<from>\nuser: {name}\nscope: {scope}\n</from>")
    if include_quote:
        quote = ctx.state.get("quote") or {}
        if quote.get("text"):
            entry = quote.get("entry") or {}
            sender = entry.get("senderName") or entry.get("senderId")
            line = f"{sender}: {quote['text']}" if sender else str(quote["text"])
            sections.append(f"<reply_to>\n{line}\n</reply_to>")
    history = ctx.state.get("history") or []
    if history:
        lines = [
            f"{item.get('senderName') or item.get('senderId')}: {str(item.get('content') or '')[:200]}"
            for item in history[-history_limit:]
        ]
        sections.append("<history>\n" + "\n".join(lines) + "\n</history>")
    content = (message.content or "").strip()
    attachments = message.attachments or []
    if content or attachments:
        parts = [content] if content else []
        for attachment in attachments:
            content_type = str(attachment.get("content_type") or "").lower()
            if content_type.startswith("image/"):
                parts.append(f"[image: {attachment.get('filename') or 'image'}]")
            elif content_type.startswith("audio/") or content_type == "voice":
                parts.append(f"[voice: {attachment.get('asr_refer_text')}]" if attachment.get("asr_refer_text") else "[voice]")
            elif content_type.startswith("video/"):
                parts.append("[video]")
            else:
                parts.append(f"[file: {attachment.get('filename') or 'file'}]")
        sections.append("<message>\n" + "\n".join(parts) + "\n</message>")
    return "\n\n".join(sections)


# ── Five-layer agent body (upstream ``assembleAgentBody``) ─────────────────

def build_agent_body(ctx: MiddlewareContext, *, history_limit: int) -> str | None:
    message = ctx.message
    state = ctx.state
    is_group = message.kind == "group"
    was_mentioned = bool((state.get("mention") or {}).get("wasMentioned"))

    user_content = _build_user_content(message, state)
    attachments = message.attachments or []
    if not user_content and not attachments and not (is_group and was_mentioned):
        return None

    quote_part = _build_quote_part(state.get("quote"))
    user_message = _build_user_message(
        user_content,
        quote_part,
        message.sender_id,
        message.sender_name,
        is_group,
        was_mentioned,
    )
    dynamic = _build_dynamic_context(message, state)
    base = f"{dynamic}{user_message}" if dynamic else user_message
    history = state.get("history") or []
    if not is_group or not was_mentioned or not history:
        return base
    lines = [
        f"[{item.get('senderName') or short_sender_id(str(item.get('senderId') or ''))} "
        f"({item.get('senderId')})] {item.get('content')}"
        for item in history[-history_limit:]
    ]
    return "\n".join(
        [
            "[Chat history begins]",
            *lines,
            "",
            "[Chat history ends]",
            "[Current message]",
            base,
        ]
    )


def _build_user_content(message: InboundMessage, state: dict[str, Any]) -> str:
    parts: list[str] = []
    text = (message.content or "").strip()
    if text:
        parts.append(text)
    processed = state.get("processedAttachments") or []
    for item in processed:
        if item.get("type") == "voice" and item.get("voiceText"):
            duration = f" ({item.get('duration')}s)" if item.get("duration") else ""
            parts.append(f"[Voice message{duration}] {item['voiceText']}")
    if not processed:
        for attachment in message.attachments or []:
            content_type = str(attachment.get("content_type") or "").lower()
            if (content_type.startswith("audio/") or content_type == "voice") and attachment.get("asr_refer_text"):
                parts.append(f"[Voice message] {str(attachment['asr_refer_text']).strip()}")
    tags = _attachment_tags(message.attachments or [])
    if tags:
        parts.append(tags)
    return "\n".join(parts)


def _attachment_tags(attachments: list[dict[str, Any]]) -> str:
    labels = {"image": "[图片]", "video": "[视频]", "file": "[文件]"}
    seen: set[str] = set()
    tags: list[str] = []
    for attachment in attachments:
        content_type = str(attachment.get("content_type") or "").lower()
        if content_type.startswith("audio/") or content_type == "voice":
            continue
        kind = "image" if content_type.startswith("image/") else "video" if content_type.startswith("video/") else "file"
        if kind in seen:
            continue
        seen.add(kind)
        tags.append(labels[kind])
    return " ".join(tags)


def _build_quote_part(quote: dict[str, Any] | None) -> str:
    if not quote:
        return ""
    text = quote.get("text") or (quote.get("entry") or {}).get("content")
    if not text:
        return ""
    return f"[Quoted message begins]\n{text}\n[Quoted message ends]\n[Current message]\n"


def _build_user_message(
    user_content: str,
    quote_part: str,
    sender_id: str,
    sender_name: str,
    is_group: bool,
    was_mentioned: bool,
) -> str:
    if not is_group:
        return f"{quote_part}{user_content}"
    mention_tag = " (@you)" if was_mentioned else ""
    display = sender_name or short_sender_id(sender_id)
    return f"{quote_part}[{display} ({sender_id})] {user_content}{mention_tag}"


def _build_dynamic_context(message: InboundMessage, state: dict[str, Any]) -> str:
    lines: list[str] = []
    attachments = message.attachments or []
    if attachments:
        downloaded = {item.get("filename"): item for item in (state.get("downloadedFiles") or [])}
        voices = []
        for attachment in attachments:
            content_type = str(attachment.get("content_type") or "").lower()
            if content_type.startswith("audio/") or content_type == "voice":
                voices.append(attachment)
                continue
            item = downloaded.get(attachment.get("filename"))
            kind = "image" if content_type.startswith("image/") else "video" if content_type.startswith("video/") else "file"
            lines.append(f"- {_render_media_line(kind, attachment.get('filename'), item.get('localPath') if item else None, attachment.get('url'), attachment.get('size'))}")
        if voices:
            asr = [str(item.get("asr_refer_text")).strip() for item in voices if item.get("asr_refer_text")]
            if asr:
                lines.append(f"- ASR: {' | '.join(asr)}")
            else:
                urls = [str(item.get("url")) for item in voices if item.get("url")]
                if urls:
                    lines.append(f"- Voice: {', '.join(urls)}")
    quote_attachments = (state.get("quote") or {}).get("attachments") or []
    if quote_attachments:
        downloaded_quote = {item.get("filename"): item for item in (state.get("downloadedQuoteFiles") or [])}
        lines.append("[Reference attachments]")
        for item in quote_attachments:
            content_type = str(item.get("contentType") or "").lower()
            if content_type.startswith("audio/") or content_type == "voice":
                if item.get("asrText"):
                    lines.append(f"  - Voice: {item['asrText']}")
                continue
            downloaded_item = downloaded_quote.get(item.get("filename"))
            kind = "image" if content_type.startswith("image/") else "video" if content_type.startswith("video/") else "file"
            lines.append(
                f"  - {_render_media_line(kind, item.get('filename'), downloaded_item.get('localPath') if downloaded_item else None, item.get('url'), None)}"
            )
    return "\n".join(lines) + "\n\n" if lines else ""


def _render_media_line(kind: str, filename: str | None, local_path: str | None, url: str | None, size: int | None) -> str:
    if kind == "image":
        return f"Image: {local_path or url or filename or 'image'}"
    if kind == "video":
        return f"Video: {local_path}" if local_path else f"Video: {filename or 'video'} (download failed)"
    return f"File: {local_path}" if local_path else f"File: {filename or 'file'} ({format_file_size(size or 0)})"


__all__ = [
    "MiddlewareContext",
    "run_chain",
    "MemoryHistoryStore",
    "MemoryRefIndexStore",
    "message_filter",
    "access_policy",
    "history_buffer",
    "mention_gate",
    "content_sanitizer",
    "rate_limiter",
    "typing_indicator",
    "quote_ref",
    "attachment_processor",
    "envelope_formatter",
    "build_envelope",
    "build_agent_body",
]
