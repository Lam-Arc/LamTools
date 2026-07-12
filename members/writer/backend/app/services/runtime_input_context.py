from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptTurn
from app.services.session_rollback_markers import is_rolled_back_metadata


@dataclass(frozen=True)
class RuntimeInputContext:
    turn: WriterTranscriptTurn
    goal: str
    history: list[dict[str, str]]


async def prepare_runtime_input_context(
    db: AsyncSession,
    *,
    session_id: str,
    transcript_turn_id: str,
    user_message: str,
    raw_user_message: str,
) -> RuntimeInputContext:
    turn = await db.get(WriterTranscriptTurn, transcript_turn_id)
    if turn is None:
        raise RuntimeError("Transcript turn was not created")

    history = await _load_recent_history(
        db,
        session_id=session_id,
        raw_user_message=raw_user_message,
    )
    return RuntimeInputContext(turn=turn, goal=user_message, history=history)
async def _load_recent_history(
    db: AsyncSession,
    *,
    session_id: str,
    raw_user_message: str,
) -> list[dict[str, str]]:
    session = await db.get(WriterSession, session_id)
    runtime_state = session.runtime_state if session and isinstance(session.runtime_state, dict) else {}
    manual_compaction = (
        runtime_state.get("manual_compaction") if isinstance(runtime_state.get("manual_compaction"), dict) else {}
    )
    compacted_ids = {
        str(message_id)
        for message_id in (manual_compaction.get("compacted_message_ids") or [])
        if str(message_id).strip()
    }
    result = await db.execute(
        select(WriterMessage)
        .where(WriterMessage.session_id == session_id)
        .where(WriterMessage.role.in_(("user", "assistant")))
        .order_by(WriterMessage.created_at.desc(), WriterMessage.id.desc())
        .limit(50)
    )
    db_messages = [
        message
        for message in reversed(result.scalars().all())
        if message.id not in compacted_ids and not is_rolled_back_metadata(message.metadata_)
    ][-21:]
    history = [
        {"role": message.role, "content": message.content, "id": message.id}
        for message in db_messages
        if message.content
    ]
    if history and history[-1]["role"] == "user" and history[-1]["content"] == raw_user_message:
        history.pop()
    if session and session.context_summary:
        history.insert(0, {"role": "system", "content": session.context_summary})
    return history
