"""Small, dependency-free helpers shared by the QQ bot modules."""

from __future__ import annotations

import base64
import json
import os
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .constants import IMAGE_EXTS, VIDEO_EXTS, VOICE_EXTS


# ── JSONC ──────────────────────────────────────────────────────────────────

def _strip_jsonc_comments(text: str) -> str:
    """String-aware comment stripper (a URL's ``//`` must survive)."""
    out: list[str] = []
    index = 0
    length = len(text)
    in_string = False
    while index < length:
        char = text[index]
        next_char = text[index + 1] if index + 1 < length else ""
        if in_string:
            out.append(char)
            if char == "\\" and index + 1 < length:
                out.append(next_char)
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            while index < length and text[index] != "\n":
                index += 1
            continue
        if char == "/" and next_char == "*":
            index += 2
            while index + 1 < length and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    out: list[str] = []
    index = 0
    length = len(text)
    in_string = False
    while index < length:
        char = text[index]
        next_char = text[index + 1] if index + 1 < length else ""
        if in_string:
            out.append(char)
            if char == "\\" and index + 1 < length:
                out.append(next_char)
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == ",":
            look = index + 1
            while look < length and text[look].isspace():
                look += 1
            if look < length and text[look] in "}]":
                index += 1
                continue
        out.append(char)
        index += 1
    return "".join(out)


def jsonc_loads(text: str) -> Any:
    """Parse JSONC (comments + trailing commas).  Raises on invalid input."""
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    clean = _strip_trailing_commas(_strip_jsonc_comments(text))
    return json.loads(clean)


_MISSING = object()


def jsonc_load(path: Path, default: Any = _MISSING) -> Any:
    try:
        return jsonc_loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {} if default is _MISSING else default


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


# ── Time / formatting ──────────────────────────────────────────────────────

def now_ms() -> int:
    return int(time.time() * 1000)


def parse_timestamp(value: str | int | float | None) -> int:
    """Parse QQ's ISO timestamp (or an epoch) into milliseconds."""
    if value is None or value == "":
        return now_ms()
    if isinstance(value, (int, float)):
        number = float(value)
        return int(number * 1000) if number < 10_000_000_000 else int(number)
    text = str(value).strip()
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        try:
            return int(float(text) * 1000)
        except Exception:
            return now_ms()


def format_relative_time(timestamp_ms: int | None) -> str:
    if not timestamp_ms:
        return "—"
    diff = max(0, now_ms() - int(timestamp_ms))
    if diff < 60_000:
        return f"{diff // 1000}s 前"
    if diff < 3_600_000:
        return f"{diff // 60_000}m 前"
    if diff < 86_400_000:
        return f"{diff // 3_600_000}h 前"
    return f"{diff // 86_400_000}d 前"


def format_file_size(size: int | float) -> str:
    size = float(size or 0)
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f}MB"
    if size >= 1024:
        return f"{size / 1024:.1f}KB"
    return f"{int(size)}B"


def mask_secret(value: str) -> str:
    value = str(value or "")
    if len(value) <= 6:
        return "*" * len(value)
    return value[:3] + "*" * (len(value) - 6) + value[-3:]


# ── Text ───────────────────────────────────────────────────────────────────

from .bubbles import (
    Block,
    BubbleOptions,
    MarkdownBlockBuilder,
    chunk_markdown_text,
    markdown_blocks,
    render_block,
    split_bubbles,
)


def short_sender_id(sender_id: str, length: int = 8) -> str:
    return str(sender_id or "")[:length]


# ── Files ──────────────────────────────────────────────────────────────────

_ILLEGAL_FILENAME = re.compile(r'[<>:"|?*\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    base = os.path.basename(str(name or "").replace("\\", "/"))
    safe = _ILLEGAL_FILENAME.sub("_", base).strip()
    safe = unicodedata.normalize("NFC", safe)
    return safe or "attachment"


def unique_filename(name: str) -> str:
    base = sanitize_filename(name)
    stem, ext = os.path.splitext(base)
    return f"{stem}_{now_ms()}_{os.urandom(4).hex()}{ext}"


def to_posix_path(path: str | Path) -> str:
    return str(path).replace("\\", "/")


def resolve_plugin_path(file_path: str | Path, work_root: str | Path | None) -> Path:
    """Resolve a tool-reported path against the agent's work root."""
    path = Path(str(file_path)).expanduser()
    if not path.is_absolute() and work_root:
        path = Path(work_root) / path
    return path.resolve()


def is_within_root(file_path: str | Path, root: str | Path) -> bool:
    try:
        candidate = Path(file_path).resolve()
        root_path = Path(root).resolve()
        return candidate == root_path or root_path in candidate.parents
    except Exception:
        return False


def is_path_allowed(file_path: str | Path, roots: Iterable[str | Path], restrict: bool = True) -> bool:
    if not restrict:
        return True
    return any(is_within_root(file_path, root) for root in roots if root)


def classify_media(path_or_name: str) -> str:
    ext = os.path.splitext(str(path_or_name or "").lower())[1]
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in VOICE_EXTS:
        return "voice"
    return "file"


def media_file_type(path_or_name: str) -> int:
    from .constants import MEDIA_TYPE_FILE, MEDIA_TYPE_IMAGE, MEDIA_TYPE_VIDEO, MEDIA_TYPE_VOICE

    return {
        "image": MEDIA_TYPE_IMAGE,
        "video": MEDIA_TYPE_VIDEO,
        "voice": MEDIA_TYPE_VOICE,
        "file": MEDIA_TYPE_FILE,
    }[classify_media(path_or_name)]


def sniff_image_media_type(data: bytes) -> str | None:
    if len(data) < 12:
        return None
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    return None


def data_url(media_type: str, data: bytes) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


def decode_base64_text(value: str) -> str:
    try:
        return base64.b64decode(value).decode("utf-8")
    except Exception:
        return ""


__all__ = [
    "jsonc_loads",
    "jsonc_load",
    "atomic_write_text",
    "write_json",
    "now_ms",
    "parse_timestamp",
    "format_relative_time",
    "format_file_size",
    "mask_secret",
    "Block",
    "BubbleOptions",
    "MarkdownBlockBuilder",
    "chunk_markdown_text",
    "markdown_blocks",
    "render_block",
    "split_bubbles",
    "short_sender_id",
    "sanitize_filename",
    "unique_filename",
    "to_posix_path",
    "is_within_root",
    "is_path_allowed",
    "classify_media",
    "media_file_type",
    "sniff_image_media_type",
    "data_url",
    "decode_base64_text",
]
