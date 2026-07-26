"""Shared token accounting helpers."""

from __future__ import annotations

from math import ceil
from typing import Any


def estimate_text_tokens(text: str, *, fast: bool = False) -> int:
    """Estimate text tokens for local budgeting when exact usage is unavailable.

    Set *fast* to True to skip per-character Unicode categorisation and use a
    simple character-length approximation instead.  Suitable for trigger /
    threshold checks where ±20 % is acceptable.
    """
    if not text:
        return 0
    if fast:
        return ceil(len(text) / 3.2)
    ascii_chars = 0
    cjk_chars = 0
    emoji_chars = 0
    other_chars = 0
    for ch in text:
        cp = ord(ch)
        if 0x3400 <= cp <= 0x4DBF or 0x4E00 <= cp <= 0x9FFF or 0x3000 <= cp <= 0x303F:
            cjk_chars += 1
        elif cp > 0x1F000:
            emoji_chars += 1
        elif cp < 128:
            ascii_chars += 1
        else:
            other_chars += 1
    return ceil(ascii_chars / 3.5 + cjk_chars / 1.5 + emoji_chars * 2 + other_chars / 2)


def estimate_message_tokens(
    messages: list[dict[str, Any]],
    *,
    image_tokens: int = 85,
    fast: bool = False,
) -> int:
    """Estimate chat-message tokens, including simple image blocks and tool calls.

    Set *fast* to True for a rough character-length approximation; the per-message
    overhead is halved (100 instead of 200) to keep trigger checks lightweight.
    """
    overhead = 100 if fast else 200
    total = 0
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            total += estimate_text_tokens(content, fast=fast)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        total += estimate_text_tokens(str(part.get("text", "")), fast=fast)
                    elif part.get("type") == "image_url":
                        total += image_tokens
                    else:
                        total += estimate_text_tokens(str(part), fast=fast)
                else:
                    total += estimate_text_tokens(str(part), fast=fast)
        else:
            total += estimate_text_tokens(str(content), fast=fast)

        reasoning = message.get("reasoning_content", "")
        if isinstance(reasoning, str):
            total += estimate_text_tokens(reasoning, fast=fast)

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if isinstance(tool_call, dict):
                    function = tool_call.get("function", {})
                    if isinstance(function, dict):
                        total += estimate_text_tokens(str(function.get("arguments", "")), fast=fast)
                    total += 50

        total += overhead
    return total


__all__ = ["estimate_text_tokens", "estimate_message_tokens"]
