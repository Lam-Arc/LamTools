from __future__ import annotations

from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import WriterAttachment
from app.models.session import WriterSession
from lamtools_core.attachment import (
    AttachmentRecord,
    AttachmentService,
    AttachmentSession,
)


class WriterAttachmentRepository:
    """Writer persistence adapter for the Core attachment service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def session(self, session_id: str) -> AttachmentSession | None:
        writer_session = await self.db.get(WriterSession, session_id)
        if writer_session is None:
            return None
        return AttachmentSession(
            id=writer_session.id,
            project_id=writer_session.project_id,
            storage_root=Path(writer_session.work_root).resolve() / ".lamwriter" / "attachments" / writer_session.id,
        )

    async def create(self, record: AttachmentRecord) -> AttachmentRecord:
        row = WriterAttachment(
            id=record.id,
            project_id=record.project_id,
            session_id=record.session_id,
            message_id=record.message_id,
            source=record.source,
            agent_name=record.agent_name,
            filename=record.filename,
            mime_type=record.mime_type,
            size=record.size,
            storage_path=record.storage_path,
            preview_type=record.preview_type,
            metadata_=record.metadata,
        )
        self.db.add(row)
        await self.db.flush()
        return _record(row)

    async def list(self, session_id: str) -> list[AttachmentRecord]:
        rows = (
            await self.db.execute(
                select(WriterAttachment)
                .where(WriterAttachment.session_id == session_id)
                .order_by(WriterAttachment.created_at.asc())
            )
        ).scalars().all()
        return [self._record(row) for row in rows]

    async def get(self, attachment_id: str) -> AttachmentRecord | None:
        row = await self.db.get(WriterAttachment, attachment_id)
        return self._record(row) if row is not None else None

    @staticmethod
    def _record(row: WriterAttachment) -> AttachmentRecord:
        return _record(row)


def writer_attachment_service(db: AsyncSession) -> AttachmentService:
    return AttachmentService(WriterAttachmentRepository(db))


def _record(row: WriterAttachment) -> AttachmentRecord:
    return AttachmentRecord(
        id=row.id,
        project_id=row.project_id,
        session_id=row.session_id,
        message_id=row.message_id,
        source=row.source,
        agent_name=row.agent_name,
        filename=row.filename,
        mime_type=row.mime_type,
        size=row.size,
        storage_path=row.storage_path,
        preview_type=row.preview_type,
        metadata=row.metadata_ or {},
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


__all__ = [
    "WriterAttachmentRepository",
    "writer_attachment_service",
]
