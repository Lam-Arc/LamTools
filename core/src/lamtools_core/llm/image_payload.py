"""Model-visible image payloads: full fidelity once, then a cheap copy.

Every model call re-sends the whole history, so an inline image is uploaded
again on every step of the session.  The original measurement that motivated
this module: a 2.31 MB reference PNG cost 20.8 s and 1011 prompt tokens per
call, while a much smaller re-encoded copy cost 3.7 s and 288 tokens, with an
identical description from the model.

Full resolution is what lets the model read small text, count details and judge
artefacts, so the *first* request that carries an image keeps it as sent.  From
the request after that, the image is degraded to a 360p, 256-colour PNG:
landscape at most 640x360, portrait at most 360x640.  It stays visible as a
reference but can no longer answer fine-detail questions.

Two properties matter more than they look:

* **Deterministic bytes.**  The degraded copy is cached by content hash and
  re-encoded with fixed parameters, because a prefix that changes on every
  request would invalidate the provider's prompt cache on every step.
* **Fail open.**  If the picture cannot be decoded, or Pillow is unavailable,
  the original is returned untouched — a missing shrink must never break a
  model call or silently drop an image.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
from collections import OrderedDict
from typing import Any

if True:
    from lamtools_core.llm import ChatMessage

#: user:“再低清一些，建议改成 8bit，360p”+降级副本固定为 360p 的 256 色调色板 PNG。
#: The box is orientation-aware: landscape is at most 640x360, portrait 360x640.
DEGRADED_IMAGE_MAX_LONG_SIDE = 640
DEGRADED_IMAGE_MAX_SHORT_SIDE = 360
DEGRADED_IMAGE_COLORS = 256
DEGRADED_IMAGE_MIME = "image/png"

#: Appended to a message whose images were degraded, so the model does not treat
#: a low-resolution copy as evidence about picture quality.
DEGRADED_IMAGE_NOTE = (
    "[图片已降为低分辨率副本，仅用于辨认大致内容；不要据此判断画质细节，"
    "需要细看请重新读取原文件]"
)

#: Metadata key stamped on a message when it enters history (kernel, neutral
#: bookkeeping).  Messages without it arrived before the first model call.
MESSAGE_ADDED_AT_STEP = "added_at_step"

_CACHE_LIMIT = 64
_CACHE: "OrderedDict[str, str]" = OrderedDict()


def split_data_url(url: str) -> tuple[str, bytes] | None:
    """Return ``(mime, payload)`` for a base64 data URL, else ``None``."""
    if not isinstance(url, str) or not url.startswith("data:"):
        return None
    head, _, body = url.partition(",")
    if not body or ";base64" not in head:
        return None
    mime = head[5:].split(";", 1)[0].strip().lower()
    try:
        payload = base64.b64decode(body, validate=False)
    except (binascii.Error, ValueError):
        return None
    if not payload:
        return None
    return mime, payload


def degraded_data_url(url: str) -> str | None:
    """Return a small 8-bit 360p PNG data URL for *url*, or ``None``.

    Deterministic for the same input, so repeated request builds produce byte
    identical payloads.
    """
    decoded = split_data_url(url)
    if decoded is None:
        return None
    mime, payload = decoded
    if (
        mime == "image/jpeg"
        and len(payload) <= 64 * 1024
        and _within_degraded_box(_jpeg_size(payload))
    ):
        # Already small enough — re-encoding would only change bytes and cost cache.
        return url
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 — degrade is best-effort by design
        return None
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            image = opened.convert("RGB")
            width, height = image.size
            if width >= height:
                max_width = DEGRADED_IMAGE_MAX_LONG_SIDE
                max_height = DEGRADED_IMAGE_MAX_SHORT_SIDE
            else:
                max_width = DEGRADED_IMAGE_MAX_SHORT_SIDE
                max_height = DEGRADED_IMAGE_MAX_LONG_SIDE
            scale = min(1.0, max_width / width, max_height / height)
            if scale < 1.0:
                image = image.resize(
                    (max(1, int(width * scale)), max(1, int(height * scale))),
                    Image.LANCZOS,
                )
            # 8-bit palette keeps the copy small and its bytes deterministic.
            image = image.convert(
                "P",
                palette=Image.ADAPTIVE,
                colors=DEGRADED_IMAGE_COLORS,
                dither=Image.Dither.NONE,
            )
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
    except Exception:  # noqa: BLE001 — an undecodable picture keeps its original
        return None
    if not buffer.tell():
        return None
    result = (
        f"data:{DEGRADED_IMAGE_MIME};base64,"
        + base64.b64encode(buffer.getvalue()).decode("ascii")
    )
    _CACHE[key] = result
    while len(_CACHE) > _CACHE_LIMIT:
        _CACHE.popitem(last=False)
    return result


def _within_degraded_box(size: tuple[int, int]) -> bool:
    """Whether *size* already fits the 360p degraded box."""
    width, height = size
    if width <= 0 or height <= 0:
        return False
    return (
        max(width, height) <= DEGRADED_IMAGE_MAX_LONG_SIDE
        and min(width, height) <= DEGRADED_IMAGE_MAX_SHORT_SIDE
    )


def _jpeg_size(payload: bytes) -> tuple[int, int]:
    """Best-effort ``(width, height)`` from a JPEG header; ``(0, 0)`` if unknown."""
    index = 2
    try:
        while index + 9 < len(payload):
            if payload[index] != 0xFF:
                index += 1
                continue
            marker = payload[index + 1]
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                index += 2
                continue
            length = int.from_bytes(payload[index + 2:index + 4], "big")
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                return (
                    int.from_bytes(payload[index + 7:index + 9], "big"),
                    int.from_bytes(payload[index + 5:index + 7], "big"),
                )
            index += 2 + max(length, 2)
    except (IndexError, ValueError):
        pass
    return 0, 0


def image_blocks(content: Any) -> list[dict[str, Any]]:
    """Return the ``image_url`` blocks of a message content value."""
    if not isinstance(content, list):
        return []
    return [
        block
        for block in content
        if isinstance(block, dict) and block.get("type") == "image_url"
    ]


def has_images(content: Any) -> bool:
    return bool(image_blocks(content))


def image_step_allowance(metadata: Any) -> int:
    """Return the counter value at which this message is still full size.

    user:“作为下一轮的输入时，它应该是以自己本身的清晰度输入...在这之后立马把它降成极低清晰度”+消息记录产生它时的模型回答次数；下一次请求使用同一个数，仍看高清，再下一次才降清。
    """
    if not isinstance(metadata, dict):
        return 0
    raw = metadata.get(MESSAGE_ADDED_AT_STEP)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def degraded_content(content: Any) -> tuple[list[dict[str, Any]], int] | None:
    """Return ``(content, degraded_count)`` with stale images shrunk, or ``None``.

    ``None`` means "nothing to do" — the caller keeps the original message, which
    also keeps its object identity for downstream memoization.
    """
    blocks = image_blocks(content)
    if not blocks:
        return None
    degraded = 0
    result: list[dict[str, Any]] = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "image_url":
            result.append(block)
            continue
        holder = block.get("image_url")
        url = holder.get("url") if isinstance(holder, dict) else None
        smaller = degraded_data_url(url) if isinstance(url, str) else None
        if smaller is None or smaller == url:
            result.append(block)
            continue
        result.append({**block, "image_url": {**holder, "url": smaller}})
        degraded += 1
    if not degraded:
        return None
    result.append({"type": "text", "text": DEGRADED_IMAGE_NOTE})
    return result, degraded


def degrade_stale_message_images(messages: "list[ChatMessage]", *, current_step: int) -> "list[ChatMessage]":
    """Return request-bound copies where images past their full-fidelity
    request are small copies, keeping the stored history untouched.

    This is the same transform the chat request path applies, so any consumer
    that builds a request-shaped input (compaction included) carries exactly
    what a normal request would carry.
    """
    from dataclasses import replace

    result: list[ChatMessage] = []
    for message in messages:
        if not has_images(message.content):
            result.append(message)
            continue
        if current_step <= image_step_allowance(message.metadata):
            result.append(message)
            continue
        degraded = degraded_content(message.content)
        result.append(replace(message, content=degraded[0]) if degraded else message)
    return result


__all__ = [
    "DEGRADED_IMAGE_COLORS",
    "DEGRADED_IMAGE_MAX_LONG_SIDE",
    "DEGRADED_IMAGE_MAX_SHORT_SIDE",
    "DEGRADED_IMAGE_MIME",
    "degrade_stale_message_images",
    "DEGRADED_IMAGE_NOTE",
    "MESSAGE_ADDED_AT_STEP",
    "degraded_content",
    "degraded_data_url",
    "has_images",
    "image_blocks",
    "image_step_allowance",
    "split_data_url",
]
