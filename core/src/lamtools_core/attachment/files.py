from __future__ import annotations

import mimetypes
import os
import re
import subprocess
import sys
from pathlib import Path

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".csv", ".tsv", ".log", ".xml", ".html", ".htm", ".css", ".js", ".ts", ".tsx", ".jsx", ".py", ".ps1", ".bat", ".sh", ".toml", ".ini", ".cfg", ".sql"}
TEXT_MIME_TYPES = {"application/json", "application/xml", "application/x-yaml", "application/yaml"}
# user:“附件预览给做好”+(很多上传通道用通用二进制 MIME 兜底；它不能
# 覆盖扩展名，否则 PDF、Office 与音视频都会退化成“外部文件”)。
GENERIC_MIME_TYPES = frozenset({
    "",
    "application/octet-stream",
    "binary/octet-stream",
    "application/unknown",
})
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".oga", ".m4a", ".flac", ".aac", ".opus"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v", ".ogv", ".mkv", ".avi"}
DANGEROUS_OPEN_EXTENSIONS = frozenset({
    ".exe", ".bat", ".cmd", ".com", ".scr", ".lnk", ".ps1", ".msi", ".reg",
    ".vbs", ".vbe", ".js", ".jse", ".hta", ".sh", ".jar", ".dll", ".sys",
    ".pif", ".wsf", ".cpl",
})


def safe_filename(filename: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(filename or "attachment").name.strip()).strip(". ")
    return name or "attachment"


def decode_transport_filename(filename: str) -> str:
    """Undo the latin-1 decode that RFC 7613 header parsing applies to filenames.

    user:“附件预览给做好”+(浏览器把中文文件名按 UTF-8 字节塞进 multipart 头，
    ASGI 按 latin-1 解出来就是乱码；保存前还原成用户真正看到的文件名)。
    Windows 下的旧式客户端/命令行会把文件名按 GBK 发送，同样在这里还原。
    """
    if not filename:
        return filename
    try:
        raw = filename.encode("latin-1")
    except UnicodeEncodeError:
        # Already a real Unicode string (JSON/API callers), nothing to undo.
        return filename
    try:
        return raw.decode("utf-8") or filename
    except UnicodeDecodeError:
        pass
    # A genuine latin-1 filename such as café.txt must stay as typed; only take
    # the GB18030 reading when it actually produces CJK text.
    try:
        decoded = raw.decode("gb18030")
    except UnicodeDecodeError:
        return filename
    if any("\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff" for char in decoded):
        return decoded
    return filename


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem or 'attachment'}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Cannot allocate attachment filename: {path.name}")


def detect_mime(filename: str, supplied: str | None = None) -> str:
    # user:“附件预览给做好”+(通用二进制 MIME 视为“没给”：优先按扩展名判断，
    # 否则 PDF/Office/音视频都会显示成外部文件)。
    if supplied and supplied.strip().lower() not in GENERIC_MIME_TYPES:
        return supplied
    return mimetypes.guess_type(filename)[0] or supplied or "application/octet-stream"


def preview_type(filename: str, mime_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in TEXT_EXTENSIONS or mime_type in TEXT_MIME_TYPES or mime_type.startswith("text/"):
        return "text"
    if mime_type.startswith("image/"):
        return "image"
    if mime_type.startswith("audio/") or suffix in AUDIO_EXTENSIONS:
        return "audio"
    if mime_type.startswith("video/") or suffix in VIDEO_EXTENSIONS:
        return "video"
    if mime_type == "application/pdf" or suffix == ".pdf":
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


def assert_safe_default_open(path: Path) -> None:
    if path.suffix.lower() in DANGEROUS_OPEN_EXTENSIONS:
        raise ValueError("This file type cannot be opened for safety")


def open_with_default_app(path: Path) -> None:
    assert_safe_default_open(path)
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


__all__ = ["assert_safe_default_open", "attachment_modality", "decode_transport_filename", "detect_mime", "open_with_default_app", "preview_type", "read_text_preview", "safe_filename", "unique_path"]
