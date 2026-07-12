from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_server import WriterAppEvent, WriterArtifact, WriterThreadSnapshot
from app.models.attachment import WriterAttachment
from app.models.message import WriterMessage
from app.models.session import WriterSession


async def delete_writer_session_records(db: AsyncSession, session_id: str) -> None:
    session = await db.get(WriterSession, session_id)
    if session is None:
        raise LookupError("Session not found")
    if str(session.status or "").lower() in {"running", "waiting", "interrupting"}:
        raise ValueError("Stop the active session before deleting it")

    await db.execute(delete(WriterAttachment).where(WriterAttachment.session_id == session_id))
    await db.execute(delete(WriterMessage).where(WriterMessage.session_id == session_id))
    await db.execute(delete(WriterArtifact).where(WriterArtifact.thread_id == session_id))
    await db.execute(delete(WriterAppEvent).where(WriterAppEvent.thread_id == session_id))
    await db.execute(delete(WriterThreadSnapshot).where(WriterThreadSnapshot.thread_id == session_id))
    await db.delete(session)


__all__ = ["delete_writer_session_records"]
