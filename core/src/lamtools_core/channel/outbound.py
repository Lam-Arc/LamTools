"""Outbound helpers shared by channel runtimes."""

from __future__ import annotations

import re

_CODE_FENCE = re.compile(r"^```")
_GFM_TABLE_LINE = re.compile(r"^\|.+\|$")


def chunk_text(text: str, limit: int) -> list[str]:
    """Split text on Markdown-safe boundaries (code fences / GFM tables)."""
    text = str(text or "")
    limit = max(64, int(limit or 4500))
    if len(text) <= limit:
        return [text] if text else []

    lines = text.split("\n")
    chunks: list[str] = []
    current = ""
    in_code_block = False
    table_buffer: list[str] = []

    def flush_table() -> None:
        nonlocal current, table_buffer
        if not table_buffer:
            return
        block = "\n".join(table_buffer)
        table_buffer = []
        if not current:
            current = block
            return
        candidate = current + "\n" + block
        if len(candidate) > limit:
            chunks.append(current)
            current = block
        else:
            current = candidate

    def append_line(line: str) -> None:
        nonlocal current
        if not current:
            current = line
            return
        candidate = current + "\n" + line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate

    for line in lines:
        if _CODE_FENCE.match(line):
            flush_table()
            in_code_block = not in_code_block
            append_line(line)
            continue
        if in_code_block:
            append_line(line)
            continue
        if _GFM_TABLE_LINE.match(line):
            table_buffer.append(line)
            continue
        flush_table()
        append_line(line)
    flush_table()
    if current:
        chunks.append(current)
    return chunks or [text]


__all__ = ["chunk_text"]
