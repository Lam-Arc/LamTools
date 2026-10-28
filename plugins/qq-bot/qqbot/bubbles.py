"""Markdown-aware QQ bubble planning.

The transport sends one Markdown message per bubble.  A bubble is therefore a
rendered content block, not an arbitrary line: tables, fenced code, lists and
quotes must stay readable even when they exceed the transport limit.

The default profile is ``full`` because the user's QQ client renders tables and
fenced code correctly.  ``safe`` is available for clients that show raw pipes
or backticks; it converts those constructs into supported Markdown shapes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Any, Iterable

_CODE_FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
_HR = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")
_QUOTE_LINE = re.compile(r"^\s*>")
_LIST_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+")
_TABLE_SEPARATOR = re.compile(
    r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)+\|?\s*$"
)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_INLINE_MATH = re.compile(r"(?<!\$)\$([^$\n]+)\$(?!\$)")
_HTML_TAG = re.compile(r"<[^>]+>")
_STYLE_OPEN = re.compile(r"^\s*:::+[A-Za-z][\w-]*(?:\{[^}]*\})?(?:\s+.*)?$")
_STYLE_CLOSE = re.compile(r"^\s*:::\s*$")


@dataclass(frozen=True)
class Block:
    """One Markdown rendering unit."""

    kind: str
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


@dataclass(frozen=True)
class BubbleOptions:
    """How a block is rendered for the target QQ client."""

    profile: str = "full"
    table: str = "markdown"
    code: str = "fence"
    heading: str = "keep"
    inline_code: str = "keep"
    math: str = "keep"
    html: str = "keep"

    @classmethod
    def for_profile(cls, profile: str = "full") -> "BubbleOptions":
        if str(profile or "full").strip().lower() == "safe":
            return cls(
                profile="safe",
                table="cards",
                code="quote",
                heading="keep",
                inline_code="quote",
                math="plain",
                html="strip",
            )
        return cls()

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "BubbleOptions":
        raw = (config or {}).get("bubbles")
        raw = raw if isinstance(raw, dict) else {}
        profile = str(raw.get("profile") or "full").strip().lower()
        base = cls.for_profile(profile)
        return cls(
            profile=base.profile,
            table=str(raw.get("table") or base.table),
            code=str(raw.get("code") or base.code),
            heading=str(raw.get("heading") or base.heading),
            inline_code=str(raw.get("inlineCode") or base.inline_code),
            math=str(raw.get("math") or base.math),
            html=str(raw.get("html") or base.html),
        )


class MarkdownBlockBuilder:
    """Incremental parser for streamed Markdown replies.

    Plain prose stays one bubble per non-empty line.  Fenced code, GFM tables,
    blockquotes and lists are buffered until the whole block is known.  A table
    only starts when a pipe-bearing header line is followed by a separator, so
    ordinary prose containing ``|`` is not mistaken for a table.
    """

    def __init__(self) -> None:
        self._in_code = False
        self._fence = ""
        self._in_math = False
        self._in_style = False
        self._kind = ""
        self._buffer: list[str] = []
        self._pending_blanks = 0
        self._pending_pipe: str | None = None

    @property
    def current_text(self) -> str:
        if self._kind:
            return "\n".join(self._buffer)
        return self._pending_pipe or ""

    @property
    def current_block(self) -> Block | None:
        if self._kind:
            return Block(self._kind, tuple(self._buffer))
        if self._pending_pipe is not None:
            return Block("paragraph", (self._pending_pipe,))
        return None

    def _finish_block(self) -> Block | None:
        if not self._buffer:
            self._kind = ""
            return None
        while self._buffer and not self._buffer[-1].strip():
            self._buffer.pop()
        lines = tuple(self._buffer)
        kind = self._kind
        self._buffer = []
        self._kind = ""
        return Block(kind, lines) if lines else None

    @staticmethod
    def _fence_match(line: str) -> re.Match[str] | None:
        return _CODE_FENCE.match(line)

    def _closing_fence(self, line: str) -> bool:
        stripped = line.strip()
        return stripped.startswith(self._fence) and not stripped[len(self._fence) :].strip()

    @staticmethod
    def _is_pipe_line(line: str) -> bool:
        return "|" in line and bool(line.strip())

    def _process_line(self, line: str, *, allow_table: bool) -> list[Block]:
        parts: list[Block] = []
        line = str(line or "").rstrip()
        while True:
            if self._in_code:
                self._buffer.append(line)
                if self._closing_fence(line):
                    block = self._finish_block()
                    self._in_code = False
                    self._fence = ""
                    if block is not None:
                        parts.append(block)
                return parts
            if self._in_math:
                self._buffer.append(line)
                if line.strip() == "$$":
                    block = self._finish_block()
                    self._in_math = False
                    if block is not None:
                        parts.append(block)
                return parts
            if self._in_style:
                self._buffer.append(line)
                if _STYLE_CLOSE.match(line):
                    block = self._finish_block()
                    self._in_style = False
                    if block is not None:
                        parts.append(block)
                return parts

            if not line.strip():
                if self._kind == "list":
                    self._pending_blanks += 1
                    return parts
                block = self._finish_block()
                if block is not None:
                    parts.append(block)
                return parts

            if self._kind == "table":
                if self._is_pipe_line(line):
                    self._buffer.append(line)
                    return parts
                block = self._finish_block()
                if block is not None:
                    parts.append(block)
                continue

            if self._pending_blanks:
                if self._kind == "list" and _LIST_ITEM.match(line):
                    self._buffer.append("")
                    self._pending_blanks = 0
                    self._buffer.append(line)
                    return parts
                block = self._finish_block()
                self._pending_blanks = 0
                if block is not None:
                    parts.append(block)
                continue

            fence = self._fence_match(line)
            if fence is not None:
                block = self._finish_block()
                if block is not None:
                    parts.append(block)
                self._in_code = True
                self._fence = fence.group(1)
                self._kind = "code"
                self._buffer.append(line)
                return parts
            if _STYLE_OPEN.match(line):
                block = self._finish_block()
                if block is not None:
                    parts.append(block)
                self._in_style = True
                self._kind = "style"
                self._buffer.append(line)
                return parts
            if line.strip() == "$$":
                block = self._finish_block()
                if block is not None:
                    parts.append(block)
                self._in_math = True
                self._kind = "math"
                self._buffer.append(line)
                return parts
            if line.strip().startswith("$$") and line.strip().endswith("$$") and len(line.strip()) > 4:
                block = self._finish_block()
                if block is not None:
                    parts.append(block)
                parts.append(Block("math", (line,)))
                return parts

            if _QUOTE_LINE.match(line):
                if self._kind not in {"", "quote"}:
                    block = self._finish_block()
                    if block is not None:
                        parts.append(block)
                self._kind = "quote"
                self._buffer.append(line)
                return parts
            if _LIST_ITEM.match(line) or (
                self._kind == "list" and line.startswith((" ", "\t"))
            ):
                if self._kind not in {"", "list"}:
                    block = self._finish_block()
                    if block is not None:
                        parts.append(block)
                self._kind = "list"
                self._buffer.append(line)
                return parts

            if allow_table and self._is_pipe_line(line) and self._kind == "":
                # Wait one line: only a following separator proves this is a
                # GFM table header instead of prose containing a pipe.
                self._pending_pipe = line
                return parts

            if self._kind:
                block = self._finish_block()
                if block is not None:
                    parts.append(block)
            if _HEADING.match(line):
                parts.append(Block("heading", (line,)))
            elif _HR.match(line):
                parts.append(Block("hr", (line,)))
            else:
                parts.append(Block("paragraph", (line,)))
            return parts

    def add_line(self, line: str) -> list[Block]:
        line = str(line or "").rstrip()
        parts: list[Block] = []
        if self._pending_pipe is not None:
            pending = self._pending_pipe
            if _TABLE_SEPARATOR.match(line):
                self._pending_pipe = None
                self._kind = "table"
                self._buffer = [pending, line]
                return parts
            self._pending_pipe = None
            parts.extend(self._process_line(pending, allow_table=False))
        parts.extend(self._process_line(line, allow_table=True))
        return parts

    def finish(self) -> list[Block]:
        parts: list[Block] = []
        if self._pending_pipe is not None:
            pending = self._pending_pipe
            self._pending_pipe = None
            parts.extend(self._process_line(pending, allow_table=False))
        block = self._finish_block()
        if block is not None:
            parts.append(block)
        self._in_code = False
        self._in_math = False
        self._in_style = False
        self._fence = ""
        return parts

    def preview_text(self, remainder: str = "", options: BubbleOptions | None = None) -> str:
        """Text for an in-place stream bubble; tables are never previewed raw."""
        options = options or BubbleOptions()
        if options.profile != "full" and (
            self._pending_pipe is not None or self._is_pipe_line(remainder)
        ):
            return ""
        block = self.current_block
        if block is None:
            return str(remainder or "")
        lines = list(block.lines)
        if remainder and not block.kind == "table":
            lines.append(str(remainder))
        preview = Block(block.kind, tuple(lines))
        if preview.kind == "table" and options.profile != "full":
            return ""
        rendered = render_block(preview, 4500, options)
        return rendered[0] if rendered else ""


def markdown_blocks(text: str) -> list[Block]:
    builder = MarkdownBlockBuilder()
    blocks: list[Block] = []
    for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        blocks.extend(builder.add_line(line))
    blocks.extend(builder.finish())
    return blocks


def split_bubbles(
    text: str,
    limit: int = 4500,
    *,
    options: BubbleOptions | None = None,
    profile: str | None = None,
) -> list[str]:
    """Split a reply into QQ bubbles using the selected render profile."""
    options = options or BubbleOptions.for_profile(profile or "full")
    limit = max(64, int(limit or 4500))
    bubbles: list[str] = []
    for block in markdown_blocks(text):
        bubbles.extend(render_block(block, limit, options))
    return [bubble for bubble in bubbles if bubble.strip()]


def chunk_markdown_text(text: str, limit: int) -> list[str]:
    """Backward-compatible full-profile chunking helper."""
    return split_bubbles(text, limit, profile="full")


def render_block(block: Block, limit: int, options: BubbleOptions) -> list[str]:
    limit = max(64, int(limit or 4500))
    if block.kind == "paragraph":
        return _render_paragraph(block.text, limit, options)
    if block.kind == "heading":
        return _render_heading(block.text, limit, options)
    if block.kind == "list":
        return _render_list(block.text, limit, options)
    if block.kind == "quote":
        return _render_quote(block.text, limit, options)
    if block.kind == "code":
        return (
            _render_code_full(block.text, limit, options)
            if options.code == "fence"
            else _render_code_safe(block.text, limit, options)
        )
    if block.kind == "table":
        return (
            _render_table_full(block.text, limit, options)
            if options.table == "markdown"
            else _render_table_cards(block.text, limit, options)
        )
    if block.kind == "math":
        return _render_math(block.text, limit, options)
    if block.kind == "style":
        return _render_style(block.text, limit)
    if block.kind == "hr":
        return ["***"]
    return _render_paragraph(block.text, limit, options)


def _inline(text: str, options: BubbleOptions) -> str:
    text = str(text or "")
    if options.inline_code == "quote":
        text = _INLINE_CODE.sub(lambda match: f"「{match.group(1)}」", text)
    if options.math == "plain":
        text = _INLINE_MATH.sub(lambda match: match.group(1), text)
    if options.html == "strip":
        text = unescape(_HTML_TAG.sub("", text))
    return text


def _render_paragraph(text: str, limit: int, options: BubbleOptions) -> list[str]:
    text = _inline(str(text or "").strip(), options)
    if not text:
        return []
    return _split_text(text, limit)


def _render_heading(text: str, limit: int, options: BubbleOptions) -> list[str]:
    match = _HEADING.match(str(text or ""))
    if not match:
        return _render_paragraph(text, limit, options)
    level = len(match.group(1))
    title = _inline(match.group(2).strip(), options)
    if options.heading == "bold" or (options.profile == "safe" and level > 2):
        rendered = f"**{title}**"
    else:
        rendered = f"{'#' * level} {title}"
    return _split_text(rendered, limit)


def _render_list(text: str, limit: int, options: BubbleOptions) -> list[str]:
    text = _inline(str(text or "").strip(), options)
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    items = _list_items(text)
    if not items:
        return _split_text(text, limit)
    bubbles: list[str] = []
    current = ""
    for item in items:
        candidate = f"{current}\n{item}" if current else item
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            bubbles.append(current)
        if len(item) <= limit:
            current = item
        else:
            bubbles.extend(_split_text(item, limit))
            current = ""
    if current:
        bubbles.append(current)
    return bubbles or _split_text(text, limit)


def _list_items(text: str) -> list[str]:
    lines = text.split("\n")
    starts: list[int] = []
    base_indent = min(
        (len(match.group(1)) for line in lines if (match := _LIST_ITEM.match(line))),
        default=0,
    )
    for index, line in enumerate(lines):
        match = _LIST_ITEM.match(line)
        if match and len(match.group(1)) == base_indent:
            starts.append(index)
    if not starts:
        return []
    items: list[str] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        item = "\n".join(lines[start:end]).strip()
        if item:
            items.append(item)
    return items


def _render_quote(text: str, limit: int, options: BubbleOptions) -> list[str]:
    text = _inline(str(text or "").strip(), options)
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    lines = text.split("\n")
    bubbles: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        add = len(line) + (1 if current else 0)
        if current and size + add > limit:
            bubbles.append("\n".join(current))
            current = []
            size = 0
        current.append(line)
        size += add
    if current:
        bubbles.append("\n".join(current))
    result: list[str] = []
    for bubble in bubbles:
        if len(bubble) <= limit:
            result.append(bubble)
            continue
        for chunk in _split_text(bubble, max(32, limit - 2)):
            result.append(chunk if chunk.startswith(">") else f"> {chunk}")
    return result


def _code_language(first_line: str) -> str:
    match = _CODE_FENCE.match(first_line)
    if not match:
        return ""
    return match.group(2).strip().split()[0] if match.group(2).strip() else ""


def _code_content(text: str) -> tuple[str, list[str]]:
    lines = str(text or "").split("\n")
    language = _code_language(lines[0]) if lines else ""
    content = lines[1:]
    if content and content[-1].strip().startswith(("```", "~~~")):
        content = content[:-1]
    return language, content


def _code_header(language: str, index: int = 0, total: int = 0) -> str:
    label = f"**代码 · {language}**" if language else "**代码**"
    if total > 1:
        label = label[:-2] + f"（{index}/{total}）**"
    return label


def _render_code_safe(text: str, limit: int, options: BubbleOptions) -> list[str]:
    del options
    language, content = _code_content(text)
    if not content:
        return [_code_header(language)]
    quoted = [">" if not line else f"> {line}" for line in content]
    header = _code_header(language)
    if len(header) + 1 + len("\n".join(quoted)) <= limit:
        return [header + "\n" + "\n".join(quoted)]
    chunks = _chunk_lines(content, max(32, limit - len(header) - 20))
    total = len(chunks)
    return [
        _code_header(language, index + 1, total) + "\n" + "\n".join(
            ">" if not line else f"> {line}" for line in chunk
        )
        for index, chunk in enumerate(chunks)
    ]


def _render_code_full(text: str, limit: int, options: BubbleOptions) -> list[str]:
    del options
    if len(text) <= limit:
        return [text]
    language, content = _code_content(text)
    fence = "```"
    overhead = len(_code_header(language, 9, 9)) + 2 * (len(fence) + 1) + 8
    chunks = _chunk_lines(content, max(32, limit - overhead))
    total = len(chunks)
    return [
        _code_header(language, index + 1, total)
        + f"\n{fence}{language}\n"
        + "\n".join(chunk)
        + f"\n{fence}"
        for index, chunk in enumerate(chunks)
    ]


def _chunk_lines(lines: Iterable[str], limit: int) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    size = 0
    for line in lines:
        line = str(line)
        pieces = [line] if len(line) <= limit else _split_text(line, limit)
        for piece in pieces:
            add = len(piece) + (1 if current else 0)
            if current and size + add > limit:
                chunks.append(current)
                current = []
                size = 0
            current.append(piece)
            size += len(piece) + (1 if len(current) > 1 else 0)
    if current:
        chunks.append(current)
    return chunks or [[""]]


def _table_rows(text: str) -> tuple[list[str], list[list[str]]]:
    lines = [line for line in str(text or "").split("\n") if line.strip()]
    if not lines:
        return [], []
    header = _split_table_row(lines[0])
    rows = [_split_table_row(line) for line in lines[2:]] if len(lines) >= 2 else []
    return header, rows


def _split_table_row(line: str) -> list[str]:
    value = str(line or "").strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|") and not value.endswith("\\|"):
        value = value[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in value:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    cells.append("".join(current).strip())
    return cells


def _render_table_cards(text: str, limit: int, options: BubbleOptions) -> list[str]:
    header, rows = _table_rows(text)
    if not rows:
        return _render_paragraph(text, limit, options)
    labels = [cell or f"列 {index + 1}" for index, cell in enumerate(header)]
    bubbles: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        values = list(row[: len(labels)])
        values.extend([""] * (len(labels) - len(values)))
        pieces: list[str] = []
        for label, value in zip(labels, values):
            label_text = _inline(label, options)
            value_text = _inline(value, options)
            prefix = f"- {label_text}："
            room = max(16, limit - len(prefix) - 32)
            value_parts = _split_text(value_text, room) if value_text else [""]
            for part_index, value_part in enumerate(value_parts):
                suffix = (
                    f"（续 {part_index + 1}/{len(value_parts)}）"
                    if len(value_parts) > 1
                    else ""
                )
                pieces.append(f"{prefix}{value_part}{suffix}")
        header_budget = len(f"**表格 · 第 {row_index} 行（9/9）**") + 1
        groups: list[list[str]] = []
        current: list[str] = []
        size = 0
        for piece in pieces:
            add = len(piece) + (1 if current else 0)
            if current and header_budget + size + add > limit:
                groups.append(current)
                current = []
                size = 0
            current.append(piece)
            size += len(piece) + (1 if len(current) > 1 else 0)
        if current:
            groups.append(current)
        total = len(groups)
        for part, group in enumerate(groups, start=1):
            bubbles.append(_table_card_lines(group, row_index, part, total))
    return bubbles


def _table_card(labels: list[str], values: list[str], row_index: int, options: BubbleOptions) -> str:
    lines = [f"- {_inline(label, options)}：{_inline(value, options)}" for label, value in zip(labels, values)]
    return f"**表格 · 第 {row_index} 行**\n" + "\n".join(lines)


def _table_card_lines(
    lines: list[str],
    row_index: int,
    part: int = 1,
    total: int = 1,
) -> str:
    suffix = f"（{part}/{total}）" if total > 1 else ""
    return f"**表格 · 第 {row_index} 行{suffix}**\n" + "\n".join(lines)


def _render_table_full(text: str, limit: int, options: BubbleOptions) -> list[str]:
    del options
    if len(text) <= limit:
        return [text]
    lines = [line for line in str(text or "").split("\n") if line.strip()]
    if len(lines) < 2:
        return _split_text(text, limit)
    header = lines[0]
    separator = lines[1]
    rows = lines[2:]
    if any(len(row) > limit for row in rows):
        return _render_table_cards(text, limit, BubbleOptions.for_profile("safe"))
    prefix = header + "\n" + separator
    chunks: list[str] = []
    current = prefix
    for row in rows:
        candidate = current + "\n" + row
        if len(candidate) > limit and current != prefix:
            chunks.append(current)
            current = prefix + "\n" + row
        elif len(candidate) > limit:
            chunks.append(prefix)
            current = row
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _render_math(text: str, limit: int, options: BubbleOptions) -> list[str]:
    raw = str(text or "").strip()
    if options.math == "keep" or options.profile == "full":
        return _split_text(raw, limit)
    content = raw.strip("$").strip()
    return _split_text(f"公式：{content}", limit)


def _style_parts(text: str) -> tuple[str, str, list[str]]:
    lines = str(text or "").split("\n")
    opening = lines[0].strip() if lines else ""
    inner = opening[3:].strip() if opening.startswith(":::") else opening
    match = re.match(r"([A-Za-z][\w-]*)", inner)
    kind = match.group(1) if match else ""
    rest = inner[len(kind):].strip() if match else inner
    title = ""
    if rest.startswith("{"):
        title_match = re.search(r'title\s*=\s*"([^"]*)"', rest)
        title = title_match.group(1) if title_match else ""
    else:
        title = rest
    has_closing = bool(lines and _STYLE_CLOSE.match(lines[-1]))
    body = lines[1:-1] if has_closing else lines[1:]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return kind, title, body


def _render_style(text: str, limit: int) -> list[str]:
    """Render Sunday style containers as their readable content for QQ.

    QQ does not understand ``:::note``/``:::details``; sending the raw markers
    is a visible failure.  Keep an explicit title (bold) and the Markdown body,
    but drop the container markers.
    """
    _kind, title, body = _style_parts(text)
    header = f"**{title}**" if title else ""
    body_text = "\n".join(body).strip()
    if not header and not body_text:
        return []
    if not body_text:
        return _split_text(header, limit)
    rendered = f"{header}\n{body_text}" if header else body_text
    if len(rendered) <= limit:
        return [rendered]
    chunks = _split_text(body_text, max(32, limit - len(header) - 1))
    result: list[str] = []
    for index, chunk in enumerate(chunks):
        result.append(f"{header}\n{chunk}" if header and index == 0 else chunk)
    return result


def _split_text(text: str, limit: int) -> list[str]:
    text = str(text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while len(text) > limit:
        cut = limit
        window_start = max(1, int(limit * 0.55))
        for separator in ("\n", "。", "！", "？", "；", ";", "，", ",", " "):
            position = text.rfind(separator, window_start, limit)
            if position > 0:
                cut = position + len(separator)
                break
        chunk = text[:cut].rstrip()
        if not chunk:
            chunk = text[:limit]
            cut = limit
        chunks.append(chunk)
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


__all__ = [
    "Block",
    "BubbleOptions",
    "MarkdownBlockBuilder",
    "chunk_markdown_text",
    "markdown_blocks",
    "render_block",
    "split_bubbles",
]
