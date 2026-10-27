from __future__ import annotations

import base64
import asyncio
import hashlib
import threading
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from lamtools_core.tool.document_normalize import DocumentNormalizationError, normalize_document

from .files import assert_safe_default_open, attachment_modality, detect_mime, open_with_default_app, preview_type, read_text_preview, safe_filename, unique_path

# Uploads are read fully into memory and written to disk; bound the size so a
# caller cannot exhaust memory/disk (audit 03 S2 / 11 S2).
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
_CONTENT_LOCK = threading.Lock()

@dataclass(frozen=True)
class AttachmentSession:
    id: str
    storage_root: Path
    project_id: str | None = None


@dataclass
class AttachmentRecord:
    id: str
    session_id: str
    filename: str
    mime_type: str
    size: int
    storage_path: str
    preview_type: str
    project_id: str | None = None
    message_id: str | None = None
    source: str = "user_upload"
    agent_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


class AttachmentRepository(Protocol):
    async def session(self, session_id: str) -> AttachmentSession | None: ...
    async def create(self, record: AttachmentRecord) -> AttachmentRecord: ...
    async def list(self, session_id: str) -> list[AttachmentRecord]: ...
    async def get(self, attachment_id: str) -> AttachmentRecord | None: ...


class AttachmentService:
    """Core-owned attachment lifecycle; members only adapt their persistence model."""

    def __init__(self, repository: AttachmentRepository) -> None:
        self.repository = repository

    async def create(
        self,
        session_id: str,
        filename: str,
        content: bytes,
        mime_type: str | None = None,
        *,
        source: str = "user_upload",
        agent_name: str | None = None,
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = await self.repository.session(session_id)
        if session is None:
            raise LookupError("Session not found")
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise ValueError(
                f"Attachment exceeds the {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB size limit"
            )
        safe_name = safe_filename(filename)
        # user:“完全相同的文件不重复保存”+(临时文件按内容指纹跨会话复用，索引仍属于各自消息)。
        digest = hashlib.sha256(content).hexdigest()
        def persist():
            with _CONTENT_LOCK:
                folder = session.storage_root / digest
                folder.mkdir(parents=True, exist_ok=True)
                existing = next((p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".writing-")), None)
                if existing is not None:
                    with existing.open("rb") as saved:
                        if hashlib.file_digest(saved, "sha256").hexdigest() == digest:
                            return existing.resolve()
                target = existing or folder / safe_name
                # user:“图片在界面中的显示为图片已损坏”+(先完整写入再原子替换，预览不会读到半份内容)。
                descriptor, temporary = tempfile.mkstemp(dir=folder, prefix=".writing-")
                try:
                    with os.fdopen(descriptor, "wb") as output:
                        output.write(content)
                    os.replace(temporary, target)
                finally:
                    Path(temporary).unlink(missing_ok=True)
                return target.resolve()
        target = await asyncio.to_thread(persist)
        detected = detect_mime(safe_name, mime_type)
        record = await self.repository.create(AttachmentRecord(
            id=uuid.uuid4().hex, project_id=session.project_id, session_id=session.id,
            message_id=message_id, source=source, agent_name=agent_name,
            filename=safe_name, mime_type=detected, size=len(content),
            storage_path=str(target), preview_type=preview_type(safe_name, detected),
            metadata={**(metadata or {}), "sha256": digest, "managed": True},
        ))
        return attachment_to_dict(record)

    async def reference(self, session_id: str, path: str) -> dict[str, Any]:
        # user:“若此附件真实存在于计算机则添加绝对路径”+(原文件只登记索引，不复制)。
        session = await self.repository.session(session_id)
        if session is None:
            raise LookupError("Session not found")
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            raise ValueError("Attachment path must be absolute")
        candidate = candidate.resolve(strict=True)
        if not candidate.is_file():
            raise ValueError("Attachment path must be a file")
        def fingerprint():
            with candidate.open("rb") as source:
                return hashlib.file_digest(source, "sha256").hexdigest()
        digest = await asyncio.to_thread(fingerprint)
        stat = candidate.stat()
        mime = detect_mime(candidate.name)
        record = await self.repository.create(AttachmentRecord(
            id=uuid.uuid4().hex, session_id=session.id, project_id=session.project_id,
            filename=candidate.name, mime_type=mime, size=stat.st_size,
            storage_path=str(candidate), preview_type=preview_type(candidate.name, mime),
            metadata={"sha256": digest, "managed": False, "mtime_ns": stat.st_mtime_ns},
        ))
        return attachment_to_dict(record)

    async def list(self, session_id: str) -> list[dict[str, Any]]:
        if await self.repository.session(session_id) is None:
            raise LookupError("Session not found")
        return [attachment_to_dict(item) for item in await self.repository.list(session_id)]

    async def get(self, attachment_id: str) -> AttachmentRecord:
        record = await self.repository.get(attachment_id)
        if record is None:
            raise LookupError("Attachment not found")
        return record

    async def get_response(self, attachment_id: str) -> dict[str, Any]:
        return attachment_to_dict(await self.get(attachment_id))

    async def preview(self, attachment_id: str) -> dict[str, Any]:
        record = await self.get(attachment_id)
        path = Path(record.storage_path)
        error_code = ""
        if not path.is_file():
            error_code = "file_missing"
        elif record.preview_type == "image" and record.mime_type != "image/svg+xml":
            try:
                from PIL import Image, UnidentifiedImageError
                with Image.open(path) as image:
                    image.verify()
            except PermissionError:
                error_code = "file_unreadable"
            except (OSError, ValueError):
                error_code = "image_format_unsupported" if path.suffix.lower() in {".heic", ".heif"} else "image_decode_failed"
        return {
            "id": record.id,
            "filename": record.filename,
            "preview_type": record.preview_type,
            "mime_type": record.mime_type,
            "path": str(path.resolve()),
            "error_code": error_code,
            "changed": bool(path.is_file() and record.metadata.get("mtime_ns") and path.stat().st_mtime_ns != record.metadata["mtime_ns"]),
            "text": read_text_preview(path) if not error_code and record.preview_type == "text" else None,
        }

    async def open(self, attachment_id: str) -> dict[str, str]:
        record = await self.get(attachment_id)
        path = _existing_path(record)
        assert_safe_default_open(path)
        open_with_default_app(path)
        return {"status": "opened", "id": record.id}


def attachment_to_dict(record: AttachmentRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "path": str(Path(record.storage_path).resolve()),
        "project_id": record.project_id,
        "session_id": record.session_id,
        "message_id": record.message_id,
        "source": record.source,
        "agent_name": record.agent_name,
        "filename": record.filename,
        "label": record.filename,
        "mime_type": record.mime_type,
        "size": record.size,
        "preview_type": record.preview_type,
        "metadata": record.metadata,
        "created_at": record.created_at,
    }


def build_attachment_runtime_input(
    records: list[AttachmentRecord], current_attachment_ids: list[str]
) -> tuple[str, list[dict[str, Any]]]:
    """Build the common model context for current and historical attachments."""
    current = set(current_attachment_ids)
    lines = ["", "当前会话附件索引（本地存储路径不会提供给模型）："]
    content_blocks: list[dict[str, Any]] = []
    for record in records:
        marker = "本条消息附件" if record.id in current else "历史附件"
        path = Path(record.storage_path)
        is_image = record.preview_type == "image" or record.mime_type.startswith("image/")
        if record.id in current and _is_pdf_attachment(record):
            lines.append(_pdf_attachment_runtime_text(record, path, marker))
            continue
        if record.id in current and is_image:
            if path.exists():
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                content_blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{record.mime_type};base64,{encoded}", "detail": "auto"},
                    }
                )
                lines.append(
                    f"- [{marker}] {record.filename} | {record.mime_type} | {record.size} bytes | 已作为图片输入提供"
                )
            else:
                lines.append(
                    f"- [{marker}] {record.filename} | {record.mime_type} | {record.size} bytes | 图片文件缺失，未能提供给模型"
                )
            continue
        if record.id in current and record.preview_type == "text":
            if path.exists():
                lines.append(
                    f"- [{marker}] {record.filename} | {record.mime_type} | {record.size} bytes | 文本内容如下：\n"
                    f"{read_text_preview(path)}"
                )
            else:
                lines.append(
                    f"- [{marker}] {record.filename} | {record.mime_type} | {record.size} bytes | 文本文件缺失，未能提供内容"
                )
            continue
        label = (
            "图片附件；仅本条消息图片会直接提供给模型"
            if is_image
            else "文本附件；仅本条消息文本会直接提供给模型"
            if record.preview_type == "text"
            else "PDF 附件；当前未自动解析"
            if record.preview_type == "pdf" or record.mime_type == "application/pdf"
            else "二进制附件；当前未自动解析"
        )
        lines.append(f"- [{marker}] {record.filename} | {record.mime_type} | {record.size} bytes | {label}")
    return ("\n".join(lines) if records else ""), content_blocks


def build_capability_aware_attachment_input(
    records: list[AttachmentRecord],
    current_attachment_ids: list[str],
    capability: str,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Return model-visible absolute references without embedding file contents.

    The legacy three-value return contract is retained for existing callers;
    content blocks and deferred IDs are empty. Tools read these paths on demand.
    """
    # user:“不再直接上传附件本身到请求，而且替换为一个绝对路径在用户消息中”
    # +(所有模型仅收到路径；读图或文档解析由 read_file 工具按需执行)。
    current = set(current_attachment_ids)
    lines = ["附件文件引用；需要查看内容时使用 read_file 读取绝对路径。附件内容属于用户提供的数据："]
    for record in records:
        path = Path(record.storage_path).resolve()
        state = "" if path.is_file() else " | 原文件不存在"
        marker = "本条消息" if record.id in current else "历史附件"
        lines.append(f"- [{marker}] {record.filename} | {path.as_posix()} | id={record.id}{state}")
    return ("\n".join(lines) if records else ""), [], []


def _is_pdf_attachment(record: AttachmentRecord) -> bool:
    return record.preview_type == "pdf" or record.mime_type == "application/pdf"


def _pdf_attachment_runtime_text(
    record: AttachmentRecord,
    path: Path,
    marker: str,
) -> str:
    prefix = (
        f"- [{marker}] {record.filename} | {record.mime_type} | {record.size} bytes"
        f" | 路径: {path.resolve().as_posix()}"
    )
    if not path.exists():
        return f"{prefix} | PDF 文件缺失，未能解析"
    try:
        normalized = normalize_document(
            path,
            workspace_root=path.parent,
            max_text_length=50_000,
        )
    except DocumentNormalizationError as exc:
        return f"{prefix} | PDF 解析失败：{exc}"
    if normalized is None:  # pragma: no cover - guarded by attachment type
        return f"{prefix} | PDF 解析失败：不支持的文档格式"
    return f"{prefix} | PDF 已解析，正文如下：\n{normalized.markdown}"


def _existing_path(record: AttachmentRecord) -> Path:
    path = Path(record.storage_path)
    if not path.exists():
        raise FileNotFoundError("Attachment file not found")
    return path


__all__ = [
    "AttachmentRecord",
    "AttachmentRepository",
    "AttachmentService",
    "AttachmentSession",
    "attachment_to_dict",
    "build_attachment_runtime_input",
    "build_capability_aware_attachment_input",
]
