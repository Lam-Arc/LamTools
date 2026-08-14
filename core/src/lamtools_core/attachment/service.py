from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .files import attachment_modality, detect_mime, open_with_default_app, preview_type, read_text_preview, safe_filename, unique_path

# Uploads are read fully into memory and written to disk; bound the size so a
# caller cannot exhaust memory/disk (audit 03 S2 / 11 S2).
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024

# Extensions whose OS default handler executes the file.  ``open`` refuses
# these so an uploaded script/executable cannot be launched through the
# unauthenticated /open endpoint (audit 03 S2).
_DANGEROUS_OPEN_EXTENSIONS = frozenset({
    ".exe", ".bat", ".cmd", ".com", ".scr", ".lnk", ".ps1", ".msi", ".reg",
    ".vbs", ".vbe", ".js", ".jse", ".hta", ".sh", ".jar", ".dll", ".sys",
    ".pif", ".wsf", ".cpl",
})


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
        session.storage_root.mkdir(parents=True, exist_ok=True)
        target = unique_path(session.storage_root / safe_name)
        target.write_bytes(content)
        detected = detect_mime(safe_name, mime_type)
        try:
            record = await self.repository.create(
                AttachmentRecord(
                    id=uuid.uuid4().hex,
                    project_id=session.project_id,
                    session_id=session.id,
                    message_id=message_id,
                    source=source,
                    agent_name=agent_name,
                    filename=safe_name,
                    mime_type=detected,
                    size=len(content),
                    storage_path=str(target),
                    preview_type=preview_type(safe_name, detected),
                    metadata=metadata or {},
                )
            )
        except BaseException:
            target.unlink(missing_ok=True)
            raise
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
        path = _existing_path(record)
        return {
            "id": record.id,
            "filename": record.filename,
            "preview_type": record.preview_type,
            "mime_type": record.mime_type,
            "text": read_text_preview(path) if record.preview_type == "text" else None,
        }

    async def open(self, attachment_id: str) -> dict[str, str]:
        record = await self.get(attachment_id)
        # Opening a file hands it to the OS default handler, which for
        # script/executable types means executing it.  Refuse those so the
        # upload+open chain cannot run attacker-controlled code
        # (audit 03 S2 — the unauthenticated /open endpoint).
        if _DANGEROUS_OPEN_EXTENSIONS.intersection(
            {Path(record.filename).suffix.lower() if record.filename else ""}
        ):
            raise ValueError("This attachment type cannot be opened for safety")
        open_with_default_app(_existing_path(record))
        return {"status": "opened", "id": record.id}


def attachment_to_dict(record: AttachmentRecord) -> dict[str, Any]:
    return {
        "id": record.id,
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


#: Modalities a multimodal model can consume as direct content blocks.
#: (audio/video have no standard OpenAI inline block yet, so they are deferred.)
_MULTIMODAL_DIRECT_MODALTIES = {"image"}


def build_capability_aware_attachment_input(
    records: list[AttachmentRecord],
    current_attachment_ids: list[str],
    capability: str,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Split attachments by model capability — the core of the attachment dispatch.

    Each attachment's own modality (text/image/audio/video/file, derived from
    its MIME type) is matched against the model's declared ``capability``:
    matching attachments become content blocks sent directly to the model;
    non-matching ones are deferred as IDs (for the main agent to delegate to a
    sub-agent via ``sub_agent(attachments=[ids], model=...)``).

    Returns ``(index_text, content_blocks, deferred_attachment_ids)``:
    - ``content_blocks``: model-consumable blocks (e.g. ``image_url`` for a
      multimodal model receiving an image).
    - ``deferred_attachment_ids``: IDs of attachments the model cannot process;
      listed in ``index_text`` with a delegation hint.
    - ``index_text``: a textual index of ALL attachments (current + historical),
      with deferred ones annotated ``[需委派 sub_agent 查看]``.
    """
    current = set(current_attachment_ids)
    cap = (capability or "").strip().lower()
    lines: list[str] = ["", "当前会话附件索引（本地存储路径不会提供给模型）："]
    content_blocks: list[dict[str, Any]] = []
    deferred: list[str] = []
    for record in records:
        marker = "本条消息附件" if record.id in current else "历史附件"
        path = Path(record.storage_path)
        modality = attachment_modality(record.mime_type, record.preview_type)
        is_current = record.id in current
        # Decide whether this attachment can be sent directly to the model.
        can_send = (
            is_current
            and modality == "text"
            and (cap in ("", "text", "multimodal"))
        ) or (
            is_current
            and modality in _MULTIMODAL_DIRECT_MODALTIES
            and cap == "multimodal"
        )
        if can_send and modality == "image" and path.exists():
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            content_blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{record.mime_type};base64,{encoded}", "detail": "auto"},
                }
            )
            lines.append(f"- [{marker}] {record.filename} | {record.mime_type} | {record.size} bytes | 已作为图片输入提供")
            continue
        if can_send and modality == "text" and path.exists():
            lines.append(
                f"- [{marker}] {record.filename} | {record.mime_type} | {record.size} bytes | 文本内容如下：\n"
                f"{read_text_preview(path)}"
            )
            continue
        # Deferred: the model cannot process this attachment's modality.
        if is_current:
            deferred.append(record.id)
            lines.append(
                f"- [{marker}] {record.filename} | {record.mime_type} | {modality} | id={record.id} | "
                f"主模型无法直接处理，需委派 sub_agent(attachments=[\"{record.id}\"], model=<多模态模型>) 查看"
            )
        else:
            lines.append(f"- [{marker}] {record.filename} | {record.mime_type} | {record.size} bytes | {modality}")
    return ("\n".join(lines) if records else ""), content_blocks, deferred


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
