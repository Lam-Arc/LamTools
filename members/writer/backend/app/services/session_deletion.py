from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import WriterAttachment
from app.models.message import WriterMessage
from app.models.queued_input import WriterQueuedInput
from app.models.session import WriterSession


async def delete_writer_session_records(db: AsyncSession, session_id: str) -> None:
    session = await db.get(WriterSession, session_id)
    if session is None:
        raise LookupError("Session not found")

    await db.execute(delete(WriterAttachment).where(WriterAttachment.session_id == session_id))
    await db.execute(delete(WriterMessage).where(WriterMessage.session_id == session_id))
    await db.execute(delete(WriterQueuedInput).where(WriterQueuedInput.session_id == session_id))
    await db.delete(session)


__all__ = ["delete_writer_session_records"]
