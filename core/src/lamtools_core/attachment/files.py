from __future__ import annotations

import mimetypes
import os
import re
import subprocess
import sys
from pathlib import Path

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".csv", ".tsv", ".log", ".xml", ".html", ".htm", ".css", ".js", ".ts", ".tsx", ".jsx", ".py", ".ps1", ".bat", ".sh", ".toml", ".ini", ".cfg", ".sql"}
TEXT_MIME_TYPES = {"application/json", "application/xml", "application/x-yaml", "application/yaml"}


def safe_filename(filename: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(filename or "attachment").name.strip()).strip(". ")
    return name or "attachment"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem or 'attachment'}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Cannot allocate attachment filename: {path.name}")


def detect_mime(filename: str, supplied: str | None = None) -> str:
    return supplied or mimetypes.guess_type(filename)[0] or "application/octet-stream"


def preview_type(filename: str, mime_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in TEXT_EXTENSIONS or mime_type in TEXT_MIME_TYPES or mime_type.startswith("text/"):
        return "text"
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("audio/"):
        return "audio"
    if mime_type.startswith("video/"):
        return "video"
    if mime_type == "application/pdf":
        return "pdf"
    return "external"


def attachment_modality(mime_type: str, preview_type: str) -> str:
    """Return the input modality an attachment provides, aligned with model capabilities.

    Maps an attachment's MIME/preview type to one of: ``text``, ``image``,
    ``audio``, ``video``, ``file`` (PDF/binaries/unknown — not directly
    consumable as a model content block). This is the attachment's "own
    attribute" used to match against a model's declared capability.
    """
    if preview_type == "text" or mime_type.startswith("text/"):
        return "text"
    if mime_type.startswith("image/") or preview_type == "image":
        return "image"
    if mime_type.startswith("audio/") or preview_type == "audio":
        return "audio"
    if mime_type.startswith("video/") or preview_type == "video":
        return "video"
    return "file"


def read_text_preview(path: Path, limit: int = 200_000) -> str:
    data = path.read_bytes()[:limit]
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "utf-16"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", errors="replace")
    return f"{text}\n\n... 内容已截断，完整文件请用默认方式打开。" if path.stat().st_size > limit else text


def open_with_default_app(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


__all__ = ["attachment_modality", "detect_mime", "open_with_default_app", "preview_type", "read_text_preview", "safe_filename", "unique_path"]
