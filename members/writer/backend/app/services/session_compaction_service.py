from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import now
from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.services.session_rollback_markers import is_rolled_back_metadata
from lamtools_core.context_compaction import ContextCompactionRequest, compact_context
from lamtools_core.llm import ChatMessage, LLMClient
from lamtools_core.llm.policy import RetryPolicy
from lamtools_core.llm.retry import ModelRetrySink

MAX_RETAIN_MESSAGE_COUNT = 6
MAX_SUMMARY_CHARS = 20000
MANUAL_COMPACTION_TARGET_TOKENS = 6000
RUNTIME_HISTORY_VISIBLE_MESSAGE_LIMIT = 21


@dataclass(frozen=True)
class SessionCompactionPlan:
    session_id: str
    trigger: str
    existing_summary: str
    existing_state: dict[str, Any]
    existing_compacted_ids: tuple[str, ...]
    message_ids: tuple[str, ...]
    messages: tuple[ChatMessage, ...]


async def prepare_session_context_compaction(
    db: AsyncSession,
    *,
    session_id: str,
    trigger: str = "manual",
) -> SessionCompactionPlan:
    session = await db.get(WriterSession, session_id)
    if session is None:
        raise LookupError("Session not found")
    existing_state = dict(session.runtime_state) if isinstance(session.runtime_state, dict) else {}
    existing_compaction = (
        existing_state.get("manual_compaction")
        if isinstance(existing_state.get("manual_compaction"), dict)
        else {}
    )
    existing_ids = tuple(
        str(value) for value in existing_compaction.get("compacted_message_ids", [])
        if str(value).strip()
    )
    rows = await _load_active_messages(db, session_id=session_id, compacted_ids=set(existing_ids))
    if len(session.context_summary or "") >= MAX_SUMMARY_CHARS:
        raise ValueError("Not enough summary space to compact history")
    return SessionCompactionPlan(
        session_id=session_id,
        trigger=trigger,
        existing_summary=session.context_summary or "",
        existing_state=existing_state,
        existing_compacted_ids=existing_ids,
        message_ids=tuple(row.id for row in rows),
        messages=tuple(_message_to_chat_message(row) for row in rows),
    )


async def execute_session_context_compaction(
    plan: SessionCompactionPlan,
    *,
    llm_client: LLMClient | None,
    model: str = "",
    timeout: float | None = None,
    on_summary_delta: Any | None = None,
    model_retries: int = 1,
    model_timeout_seconds: float | None = None,
    retry_policy: RetryPolicy | None = None,
    on_model_retry: ModelRetrySink | None = None,
) -> tuple[Any, dict[str, Any]]:
    result = await compact_context(
        ContextCompactionRequest(
            trigger=plan.trigger,
            messages=list(plan.messages),
            llm_client=llm_client,
            model=model,
            timeout=timeout,
            target_tokens=MANUAL_COMPACTION_TARGET_TOKENS,
            retain_tail_count=MAX_RETAIN_MESSAGE_COUNT,
            existing_summary=plan.existing_summary,
            on_delta=on_summary_delta,
            model_retries=model_retries,
            model_timeout_seconds=model_timeout_seconds,
            retry_policy=retry_policy or RetryPolicy(),
            on_model_retry=on_model_retry,
        )
    )
    if result.status != "compacted":
        raise ValueError("Context compaction did not produce a summary")
    if len(result.summary) > MAX_SUMMARY_CHARS:
        raise ValueError("Not enough summary space to compact history")
    compacted_ids = list(plan.message_ids[: result.compacted_count])
    retained_ids = list(plan.message_ids[-result.retained_count :]) if result.retained_count else []
    payload = {
        "status": "compacted",
        "session_id": plan.session_id,
        "compacted_messages": len(compacted_ids),
        "retained_messages": len(retained_ids),
        "compacted_message_ids": [*plan.existing_compacted_ids, *compacted_ids],
        "retained_message_ids": retained_ids,
        "before_tokens": result.before_tokens,
        "after_tokens": result.after_tokens,
        "target_tokens": result.target_tokens,
        "trigger": plan.trigger,
        "summary": result.summary,
    }
    return result, payload


async def apply_session_context_compaction(
    db: AsyncSession,
    *,
    plan: SessionCompactionPlan,
    payload: dict[str, Any],
) -> dict[str, Any]:
    session = await db.get(WriterSession, plan.session_id)
    if session is None:
        raise LookupError("Session not found")
    compacted_at = now().astimezone(timezone.utc).isoformat()
    manual = {
        "compacted_at": compacted_at,
        "trigger": plan.trigger,
        "compacted_message_ids": payload["compacted_message_ids"],
        "retained_message_ids": payload["retained_message_ids"],
        "retained_message_count": payload["retained_messages"],
    }
    session.context_summary = str(payload["summary"])
    session.runtime_state = {**plan.existing_state, "manual_compaction": manual}
    return {**payload, "compacted_at": compacted_at}


async def compact_session_context_response(
    db: AsyncSession,
    *,
    session_id: str,
    llm_client: LLMClient | None = None,
    model: str = "",
    timeout: float | None = None,
    on_summary_delta: Any | None = None,
    model_retries: int = 1,
    model_timeout_seconds: float | None = None,
    retry_policy: RetryPolicy | None = None,
    on_model_retry: ModelRetrySink | None = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    session = await db.get(WriterSession, session_id)
    if session is None:
        raise LookupError("Session not found")

    existing_state = session.runtime_state if isinstance(session.runtime_state, dict) else {}
    existing_compaction = (
        existing_state.get("manual_compaction") if isinstance(existing_state.get("manual_compaction"), dict) else {}
    )
    existing_compacted_ids = [
        str(message_id)
        for message_id in (existing_compaction.get("compacted_message_ids") or [])
        if str(message_id).strip()
    ]
    compacted_ids = set(existing_compacted_ids)
    messages = await _load_active_messages(db, session_id=session_id, compacted_ids=compacted_ids)

    if len(session.context_summary or "") >= MAX_SUMMARY_CHARS:
        raise ValueError("Not enough summary space to compact history")
    result = await compact_context(
        ContextCompactionRequest(
            trigger=trigger,
            messages=[_message_to_chat_message(message) for message in messages],
            llm_client=llm_client,
            model=model,
            timeout=timeout,
            target_tokens=MANUAL_COMPACTION_TARGET_TOKENS,
            retain_tail_count=MAX_RETAIN_MESSAGE_COUNT,
            existing_summary=session.context_summary or "",
            on_delta=on_summary_delta,
            model_retries=model_retries,
            model_timeout_seconds=model_timeout_seconds,
            retry_policy=retry_policy or RetryPolicy(),
            on_model_retry=on_model_retry,
        )
    )
    if result.status != "compacted":
        raise ValueError("Context compaction did not produce a summary")
    compacted = messages[: result.compacted_count]
    retained = messages[-result.retained_count :] if result.retained_count else []
    summary = result.summary
    if len(summary) > MAX_SUMMARY_CHARS:
        raise ValueError("Not enough summary space to compact history")
    manual_compaction = {
        "compacted_at": now().astimezone(timezone.utc).isoformat(),
        "trigger": trigger,
        "compacted_message_ids": [
            *existing_compacted_ids,
            *[message.id for message in compacted if message.id not in compacted_ids],
        ],
        "retained_message_ids": [message.id for message in retained],
        "retained_message_count": len(retained),
    }
    session.context_summary = summary
    session.runtime_state = {**existing_state, "manual_compaction": manual_compaction}
    await db.flush()
    return {
        "status": "compacted",
        "session_id": session_id,
        "compacted_at": manual_compaction["compacted_at"],
        "compacted_messages": len(compacted),
        "retained_messages": len(retained),
        "compacted_message_ids": manual_compaction["compacted_message_ids"],
        "retained_message_ids": manual_compaction["retained_message_ids"],
        "before_tokens": result.before_tokens,
        "after_tokens": result.after_tokens,
        "target_tokens": result.target_tokens,
        "trigger": trigger,
        "summary": session.context_summary,
    }


async def session_needs_context_compaction(
    db: AsyncSession,
    *,
    session_id: str,
    active_message_limit: int = RUNTIME_HISTORY_VISIBLE_MESSAGE_LIMIT,
) -> bool:
    session = await db.get(WriterSession, session_id)
    if session is None:
        return False
    existing_state = session.runtime_state if isinstance(session.runtime_state, dict) else {}
    existing_compaction = (
        existing_state.get("manual_compaction") if isinstance(existing_state.get("manual_compaction"), dict) else {}
    )
    compacted_ids = {
        str(message_id)
        for message_id in (existing_compaction.get("compacted_message_ids") or [])
        if str(message_id).strip()
    }
    messages = await _load_active_messages(db, session_id=session_id, compacted_ids=compacted_ids)
    return len(messages) > active_message_limit


async def _load_active_messages(
    db: AsyncSession,
    *,
    session_id: str,
    compacted_ids: set[str],
) -> list[WriterMessage]:
    result = await db.execute(
        select(WriterMessage)
        .where(WriterMessage.session_id == session_id)
        .where(WriterMessage.role.in_(("user", "assistant")))
        .order_by(WriterMessage.created_at.asc(), WriterMessage.id.asc())
    )
    return [
        message
        for message in result.scalars().all()
        if message.content
        and message.id not in compacted_ids
        and not is_rolled_back_metadata(message.metadata_)
    ]


def _message_to_chat_message(message: WriterMessage) -> ChatMessage:
    role = "assistant" if message.role == "assistant" else "user"
    return ChatMessage(role=role, content=str(message.content or ""))
