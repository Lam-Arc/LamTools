from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import WriterAttachment
from app.models.base import gen_uuid
from app.models.session import WriterSession
from lamtools_core.attachment import detect_mime, open_with_default_app, preview_type, read_text_preview, safe_filename, unique_path


def attachment_to_dict(attachment: WriterAttachment) -> dict[str, Any]:
    return {
        "id": attachment.id,
        "project_id": attachment.project_id,
        "session_id": attachment.session_id,
        "message_id": attachment.message_id,
        "source": attachment.source,
        "agent_name": attachment.agent_name,
        "filename": attachment.filename,
        "label": attachment.filename,
        "mime_type": attachment.mime_type,
        "size": attachment.size,
        "preview_type": attachment.preview_type,
        "metadata": attachment.metadata_ or {},
        "created_at": attachment.created_at.isoformat() if attachment.created_at else "",
    }


async def list_session_attachment_responses(db: AsyncSession, session_id: str) -> list[dict[str, Any]]:
    session = await get_session_or_404(db, session_id)
    if session is None:
        raise LookupError("Session not found")
    result = await db.execute(
        select(WriterAttachment)
        .where(WriterAttachment.session_id == session_id)
        .order_by(WriterAttachment.created_at.asc())
    )
    return [attachment_to_dict(item) for item in result.scalars().all()]


async def get_attachment_response(db: AsyncSession, attachment_id: str) -> dict[str, Any]:
    attachment = await db.get(WriterAttachment, attachment_id)
    if attachment is None:
        raise LookupError("Attachment not found")
    return attachment_to_dict(attachment)


async def preview_attachment_response(db: AsyncSession, attachment_id: str) -> dict[str, Any]:
    attachment = await db.get(WriterAttachment, attachment_id)
    if attachment is None:
        raise LookupError("Attachment not found")
    path = Path(attachment.storage_path)
    if not path.exists():
        raise FileNotFoundError("Attachment file not found")
    text = read_text_preview(path) if attachment.preview_type == "text" else None
    return {
        "id": attachment.id,
        "filename": attachment.filename,
        "preview_type": attachment.preview_type,
        "mime_type": attachment.mime_type,
        "text": text,
    }


async def open_attachment_response(
    db: AsyncSession,
    attachment_id: str,
    *,
    opener: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    attachment = await db.get(WriterAttachment, attachment_id)
    if attachment is None:
        raise LookupError("Attachment not found")
    path = Path(attachment.storage_path)
    if not path.exists():
        raise FileNotFoundError("Attachment file not found")
    (opener or open_with_default_app)(path)
    return {"status": "opened", "id": attachment.id}


async def create_attachment_from_bytes(
    *,
    db: AsyncSession,
    session: WriterSession,
    filename: str,
    content: bytes,
    source: str,
    agent_name: str | None = None,
    mime_type: str | None = None,
    message_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> WriterAttachment:
    safe_name = safe_filename(filename)
    root = attachment_dir(session.work_root, session.id)
    root.mkdir(parents=True, exist_ok=True)
    target = unique_path(root / safe_name)
    target.write_bytes(content)

    detected_mime = detect_mime(safe_name, mime_type)
    attachment = WriterAttachment(
        id=gen_uuid(),
        project_id=session.project_id,
        session_id=session.id,
        message_id=message_id,
        source=source,
        agent_name=agent_name,
        filename=safe_name,
        mime_type=detected_mime,
        size=len(content),
        storage_path=str(target),
        preview_type=preview_type(safe_name, detected_mime),
        metadata_=metadata or {},
    )
    db.add(attachment)
    await db.flush()
    return attachment


async def get_session_or_404(db: AsyncSession, session_id: str) -> WriterSession | None:
    result = await db.execute(select(WriterSession).where(WriterSession.id == session_id))
    return result.scalar_one_or_none()


def attachment_dir(work_root: str, session_id: str) -> Path:
    base = Path(work_root).resolve()
    return base / ".lamwriter" / "attachments" / session_id
