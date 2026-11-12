"""Persisted payload policy: attachments are addresses, not inline bytes.

user:“不应该有任何一个信息大于 4 兆，因为哪怕在恶劣的情况下，估计百万 token
的文字信息也只有 2MB，像这种一旦涉及到其他的附件，应该用的是指针或者说是地址
来表示，而不是直接放什么 base64 或者源文件”+(常态下单条落盘记录不超过 4MB；
图片/附件一律外置成地址。4MB 不是硬拒绝线：用户明确要求读取超大图片等特殊情况
可以突破，但必须能在日志里被看见、被解释)。

The live ``ChatMessage`` keeps its image block so the immediately following model
request still sees the original pixels.  Only the persisted copy is externalized:
the block is dropped and ``metadata.image_ref`` (path + mime + sha256) remains, so
the model can re-read the file through ``read_file`` and the UI can fetch bytes
from the attachment/workspace address.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

#: Normal upper bound for one persisted row (history message, snapshot entity,
#: sync journal entity).  Exceeding it is logged, never silently accepted.
MAX_NORMAL_PAYLOAD_BYTES = 4 * 1024 * 1024

_logger = logging.getLogger(__name__)


def payload_size_bytes(value: Any) -> int:
    """UTF-8 JSON size of one payload, the same shape SQLite stores."""
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return 0


def _inline_data_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("data:")


def persistable_message(message: dict[str, Any]) -> dict[str, Any]:
    """Return the persisted copy of a message with inline attachments removed.

    The input dict is never mutated: the kernel's live history keeps the image
    block for the current request, while the row written to
    ``core_history_entries`` carries only text plus ``image_ref``.
    """
    row = copy.deepcopy(message)
    content = row.get("content")
    if isinstance(content, list):
        kept: list[Any] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "image_url":
                image = block.get("image_url")
                url = image.get("url") if isinstance(image, dict) else None
                if _inline_data_url(url):
                    # The bytes stay in the live message; the persisted row
                    # keeps the address in metadata.image_ref instead.
                    continue
            kept.append(block)
        if len(kept) != len(content):
            row["content"] = kept
    return row


def warn_if_oversized(kind: str, key: str, row: dict[str, Any]) -> int:
    """Log one warning when a persisted row exceeds the normal bound.

    Returns the measured size so callers can add their own metrics without
    serializing the payload twice.
    """
    size = payload_size_bytes(row)
    if size > MAX_NORMAL_PAYLOAD_BYTES:
        _logger.warning(
            "[payload] %s %s is %.1f MB (> %.0f MB normal limit); "
            "attachments must be stored as addresses, not inline content",
            kind,
            key,
            size / (1024 * 1024),
            MAX_NORMAL_PAYLOAD_BYTES / (1024 * 1024),
        )
    return size


__all__ = [
    "MAX_NORMAL_PAYLOAD_BYTES",
    "payload_size_bytes",
    "persistable_message",
    "warn_if_oversized",
]
