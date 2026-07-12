from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import gen_uuid
from app.models.attachment import WriterAttachment
from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.models.transcript import (
    WriterActiveProducer,
    WriterTranscriptArtifact,
    WriterTranscriptBlock,
    WriterTranscriptModelCall,
    WriterTranscriptTurn,
)
from app.services.session_rollback_markers import is_rolled_back_metadata


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _duration_ms(started_at: datetime | None, ended_at: datetime | None) -> int | None:
    if started_at is None:
        return None
    end = ended_at or utc_now()
    if started_at.tzinfo is None and end.tzinfo is not None:
        end = end.replace(tzinfo=None)
    elif started_at.tzinfo is not None and end.tzinfo is None:
        started_at = started_at.replace(tzinfo=None)
    return max(0, int((end - started_at).total_seconds() * 1000))


TERMINAL_BLOCK_STATUSES = {"completed", "done", "ok", "failed", "error", "cancelled"}


def _is_terminal_block_status(status: str | None) -> bool:
    return str(status or "").lower() in TERMINAL_BLOCK_STATUSES


def _project_duration_ms(started_at: datetime | None, completed_at: datetime | None, status: str | None) -> int | None:
    if completed_at is not None:
        return _duration_ms(started_at, completed_at)
    if str(status or "").lower() in {"running", "pending", "waiting"}:
        return _duration_ms(started_at, None)
    return None


async def bump_transcript_revision(db: AsyncSession, session_id: str) -> int:
    session = await db.get(WriterSession, session_id)
    if session is None:
        return 0
    session.transcript_revision = int(session.transcript_revision or 0) + 1
    session.updated_at = utc_now()
    return session.transcript_revision


async def create_turn(
    db: AsyncSession,
    *,
    session_id: str,
    user_text: str,
    user_message_id: str | None,
    turn_id: str | None = None,
) -> WriterTranscriptTurn:
    max_sequence = await db.execute(
        select(func.max(WriterTranscriptTurn.sequence)).where(WriterTranscriptTurn.session_id == session_id)
    )
    sequence = int(max_sequence.scalar() or 0) + 1
    now = utc_now()
    turn = WriterTranscriptTurn(
        id=turn_id or gen_uuid(),
        session_id=session_id,
        sequence=sequence,
        user_text=user_text,
        user_message_id=user_message_id,
        status_cache="running",
        started_at=now,
        last_state_changed_at=now,
    )
    db.add(turn)
    await bump_transcript_revision(db, session_id)
    return turn


async def create_user_message_turn(
    db: AsyncSession,
    *,
    session_id: str,
    user_text: str,
    message_id: str | None = None,
    message_parts: dict[str, Any] | None = None,
    attachment_ids: list[str] | None = None,
    turn_id: str | None = None,
) -> tuple[WriterTranscriptTurn, WriterMessage]:
    user_message = WriterMessage(
        id=message_id or gen_uuid(),
        session_id=session_id,
        role="user",
        content=user_text,
        parts=message_parts,
    )
    db.add(user_message)
    turn = await create_turn(
        db,
        session_id=session_id,
        user_text=user_text,
        user_message_id=user_message.id,
        turn_id=turn_id,
    )
    if attachment_ids:
        result = await db.execute(
            select(WriterAttachment).where(
                WriterAttachment.session_id == session_id,
                WriterAttachment.id.in_(attachment_ids),
            )
        )
        attachments = {attachment.id: attachment for attachment in result.scalars().all()}
        missing = [attachment_id for attachment_id in attachment_ids if attachment_id not in attachments]
        if missing:
            raise ValueError(f"Attachment not found in session: {', '.join(missing)}")
        for attachment in attachments.values():
            attachment.message_id = user_message.id
    return turn, user_message


async def ensure_model_call(
    db: AsyncSession,
    *,
    turn: WriterTranscriptTurn,
    run_id: str | None,
    model_context: dict[str, Any] | None = None,
) -> WriterTranscriptModelCall:
    call_id = run_id or f"{turn.id}:model-call-1"
    existing = await db.get(WriterTranscriptModelCall, call_id)
    if existing is not None:
        if _apply_model_context(existing, model_context):
            await bump_transcript_revision(db, turn.session_id)
        return existing
    max_sequence = await db.execute(
        select(func.max(WriterTranscriptModelCall.sequence)).where(
            WriterTranscriptModelCall.turn_id == turn.id
        )
    )
    call = WriterTranscriptModelCall(
        id=call_id,
        turn_id=turn.id,
        sequence=int(max_sequence.scalar() or 0) + 1,
        status="running",
        started_at=utc_now(),
    )
    _apply_model_context(call, model_context)
    db.add(call)
    await bump_transcript_revision(db, turn.session_id)
    return call


def _apply_model_context(call: WriterTranscriptModelCall, model_context: dict[str, Any] | None) -> bool:
    if not isinstance(model_context, dict) or not model_context:
        return False
    changed = False
    provider = str(
        model_context.get("provider")
        or model_context.get("provider_name")
        or model_context.get("provider_id")
        or ""
    ).strip()
    model = str(
        model_context.get("model")
        or model_context.get("model_id")
        or model_context.get("model_record_id")
        or ""
    ).strip()
    if provider and call.provider != provider[:100]:
        call.provider = provider[:100]
        changed = True
    if model and call.model != model[:255]:
        call.model = model[:255]
        changed = True
    metadata = dict(call.metadata_ or {})
    context = dict(model_context)
    if metadata.get("model_context") != context:
        metadata["model_context"] = context
        call.metadata_ = metadata
        changed = True
    return changed


async def ensure_active_producer(
    db: AsyncSession,
    *,
    turn: WriterTranscriptTurn,
    producer_id: str,
    model_call_id: str | None = None,
    parent_block_id: str | None = None,
    kind: str = "runtime",
) -> WriterActiveProducer:
    now = utc_now()
    if turn.status_cache != "running":
        turn.status_cache = "running"
        turn.last_state_changed_at = now
    existing = await db.get(WriterActiveProducer, producer_id)
    if existing is not None:
        existing.heartbeat_at = now
        if existing.closed_at is not None:
            existing.closed_at = None
            existing.close_reason = None
            await bump_transcript_revision(db, turn.session_id)
        return existing
    producer = WriterActiveProducer(
        id=producer_id,
        turn_id=turn.id,
        model_call_id=model_call_id,
        parent_block_id=parent_block_id,
        kind=kind,
        started_at=now,
        heartbeat_at=now,
        recoverable=False,
    )
    db.add(producer)
    await bump_transcript_revision(db, turn.session_id)
    return producer


async def close_active_producers(
    db: AsyncSession,
    *,
    turn_id: str,
    reason: str,
    producer_id: str | None = None,
) -> None:
    query = select(WriterActiveProducer).where(
        WriterActiveProducer.turn_id == turn_id,
        WriterActiveProducer.closed_at.is_(None),
    )
    if producer_id:
        query = query.where(WriterActiveProducer.id == producer_id)
    result = await db.execute(query)
    now = utc_now()
    changed_turn_ids: set[str] = set()
    for producer in result.scalars().all():
        producer.closed_at = now
        producer.heartbeat_at = now
        producer.close_reason = reason
        changed_turn_ids.add(producer.turn_id)
    if changed_turn_ids:
        turn_rows = await db.execute(select(WriterTranscriptTurn).where(WriterTranscriptTurn.id.in_(changed_turn_ids)))
        for turn in turn_rows.scalars().all():
            await bump_transcript_revision(db, turn.session_id)


async def upsert_block(
    db: AsyncSession,
    *,
    turn: WriterTranscriptTurn,
    block_id: str,
    model_call_id: str | None,
    block_type: str,
    sequence: int,
    event_sequence: int,
    status: str = "running",
    content: str = "",
    producer_id: str | None = None,
    parent_block_id: str | None = None,
    request_kind: str | None = None,
    response_json: dict[str, Any] | None = None,
    tool_name: str | None = None,
    tool_call_id: str | None = None,
    tool_args_json: dict[str, Any] | None = None,
    tool_result_preview: str | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> WriterTranscriptBlock:
    now = utc_now()
    block = await db.get(WriterTranscriptBlock, block_id)
    terminal = _is_terminal_block_status(status)
    if block is None:
        block = WriterTranscriptBlock(
            id=block_id,
            turn_id=turn.id,
            model_call_id=model_call_id,
            parent_block_id=parent_block_id,
            producer_id=producer_id,
            sequence=sequence,
            event_sequence=event_sequence,
            type=block_type,
            status=status,
            content=content,
            request_kind=request_kind,
            response_json=response_json,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args_json=tool_args_json,
            tool_result_preview=tool_result_preview,
            error=error,
            started_at=now,
            updated_at=now,
            completed_at=now if terminal else None,
            duration_ms=_duration_ms(now, now) if terminal else None,
            metadata_=metadata,
        )
        db.add(block)
        await bump_transcript_revision(db, turn.session_id)
        return block
    block.status = status or block.status
    block.content = content if content else block.content
    block.request_kind = request_kind or block.request_kind
    block.response_json = response_json or block.response_json
    block.tool_name = tool_name or block.tool_name
    block.tool_call_id = tool_call_id or block.tool_call_id
    block.tool_args_json = tool_args_json or block.tool_args_json
    block.tool_result_preview = tool_result_preview or block.tool_result_preview
    block.error = error or block.error
    block.metadata_ = metadata or block.metadata_
    block.updated_at = now
    if terminal and block.completed_at is None:
        block.completed_at = now
        block.duration_ms = _duration_ms(block.started_at, block.completed_at)
    await bump_transcript_revision(db, turn.session_id)
    return block


async def close_open_blocks(
    db: AsyncSession,
    *,
    turn: WriterTranscriptTurn,
    model_call_id: str | None = None,
    status: str = "completed",
    include_waiting: bool = False,
) -> None:
    query = select(WriterTranscriptBlock).where(
        WriterTranscriptBlock.turn_id == turn.id,
        WriterTranscriptBlock.completed_at.is_(None),
    )
    if model_call_id is not None:
        query = query.where(WriterTranscriptBlock.model_call_id == model_call_id)
    result = await db.execute(query)
    now = utc_now()
    changed = False
    for block in result.scalars().all():
        if block.type == "waiting_request" and not include_waiting:
            continue
        if block.status in {"completed", "failed", "error", "cancelled"}:
            continue
        block.status = status
        block.completed_at = now
        block.updated_at = now
        block.duration_ms = _duration_ms(block.started_at, block.completed_at)
        changed = True
    if changed:
        await bump_transcript_revision(db, turn.session_id)


async def record_artifacts(
    db: AsyncSession,
    *,
    turn_id: str,
    block_id: str,
    artifacts: Any,
) -> None:
    if not isinstance(artifacts, list):
        return
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        raw_path = str(item.get("path") or item.get("file_path") or "").strip()
        if not raw_path:
            continue
        path = Path(raw_path)
        artifact = WriterTranscriptArtifact(
            turn_id=turn_id,
            block_id=block_id,
            file_name=str(item.get("name") or path.name or raw_path),
            file_path=raw_path,
            file_type=str(item.get("type") or item.get("kind") or path.suffix.lstrip(".") or "file"),
            mime_type=str(item.get("mime_type") or "") or None,
            size_bytes=item.get("size_bytes") if isinstance(item.get("size_bytes"), int) else None,
            metadata_=item,
        )
        db.add(artifact)
        turn = await db.get(WriterTranscriptTurn, turn_id)
        if turn is not None:
            await bump_transcript_revision(db, turn.session_id)


async def mark_turn_terminal(
    db: AsyncSession,
    *,
    turn: WriterTranscriptTurn,
    reason: str,
    error: str = "",
) -> None:
    now = utc_now()
    turn.terminal_at = now
    turn.last_state_changed_at = now
    turn.terminal_reason = reason
    turn.error = error or None
    turn.status_cache = "failed"
    await close_open_blocks(db, turn=turn, status="failed", include_waiting=True)
    await close_active_producers(db, turn_id=turn.id, reason=reason)
    await bump_transcript_revision(db, turn.session_id)


async def derive_turn_status(db: AsyncSession, turn: WriterTranscriptTurn) -> str:
    if turn.final_reply_block_id:
        block = await db.get(WriterTranscriptBlock, turn.final_reply_block_id)
        if block is not None and block.type == "model_text" and block.status == "completed":
            return "completed"
    if turn.terminal_reason:
        return "failed"
    # If there's any open waiting request, the turn is blocked and explicitly waiting.
    waiting = await db.execute(
        select(WriterTranscriptBlock.id).where(
            WriterTranscriptBlock.turn_id == turn.id,
            WriterTranscriptBlock.type == "waiting_request",
            WriterTranscriptBlock.completed_at.is_(None),
        ).limit(1)
    )
    if waiting.scalar_one_or_none() is not None:
        return "waiting"
    # If there are active producers, runtime is still producing transcript facts.
    active = await db.execute(
        select(WriterActiveProducer.id).where(
            WriterActiveProducer.turn_id == turn.id,
            WriterActiveProducer.closed_at.is_(None),
        ).limit(1)
    )
    if active.scalar_one_or_none() is not None:
        return "running"
    return "failed"


async def sync_turn_status_cache(db: AsyncSession, turn: WriterTranscriptTurn) -> str:
    status = await derive_turn_status(db, turn)
    if turn.status_cache != status:
        turn.status_cache = status
        turn.last_state_changed_at = utc_now()
        await bump_transcript_revision(db, turn.session_id)
    return status


async def latest_turn_status(db: AsyncSession, session_id: str) -> str:
    result = await db.execute(
        select(WriterTranscriptTurn)
        .where(WriterTranscriptTurn.session_id == session_id)
        .order_by(WriterTranscriptTurn.sequence.desc())
    )
    for turn in result.scalars().all():
        if is_rolled_back_metadata(turn.metadata_):
            continue
        return await sync_turn_status_cache(db, turn)
    return "idle"


async def project_transcript(db: AsyncSession, session_id: str) -> dict[str, Any]:
    session = await db.get(WriterSession, session_id)
    turns_result = await db.execute(
        select(WriterTranscriptTurn)
        .where(WriterTranscriptTurn.session_id == session_id)
        .order_by(WriterTranscriptTurn.sequence.asc())
    )
    turns = turns_result.scalars().all()
    revision = int(session.transcript_revision or 0) if session is not None else 0
    projected_turns: list[dict[str, Any]] = []
    for turn in turns:
        if is_rolled_back_metadata(turn.metadata_):
            continue
        status = await sync_turn_status_cache(db, turn)
        revision = max(revision, turn.sequence)
        call_rows = (
            await db.execute(
                select(WriterTranscriptModelCall)
                .where(WriterTranscriptModelCall.turn_id == turn.id)
                .order_by(WriterTranscriptModelCall.sequence.asc())
            )
        ).scalars().all()
        block_rows = (
            await db.execute(
                select(WriterTranscriptBlock)
                .where(WriterTranscriptBlock.turn_id == turn.id)
                .order_by(WriterTranscriptBlock.event_sequence.asc(), WriterTranscriptBlock.sequence.asc())
            )
        ).scalars().all()
        artifacts_by_block: dict[str, list[dict[str, Any]]] = {}
        artifact_rows = (
            await db.execute(
                select(WriterTranscriptArtifact).where(WriterTranscriptArtifact.turn_id == turn.id)
            )
        ).scalars().all()
        for artifact in artifact_rows:
            artifacts_by_block.setdefault(artifact.block_id, []).append({
                "artifact_id": artifact.id,
                "file_name": artifact.file_name,
                "file_path": artifact.file_path,
                "file_type": artifact.file_type,
                "mime_type": artifact.mime_type,
                "size_bytes": artifact.size_bytes,
            })
        blocks_by_call: dict[str | None, list[WriterTranscriptBlock]] = {}
        for block in block_rows:
            blocks_by_call.setdefault(block.model_call_id, []).append(block)
        model_calls = []
        for call in call_rows:
            blocks = [_project_block(block, turn.final_reply_block_id, artifacts_by_block) for block in blocks_by_call.get(call.id, [])]
            model_calls.append({
                "model_call_id": call.id,
                "sequence": call.sequence,
                "provider": call.provider,
                "model": call.model,
                "status": call.status,
                "metadata": call.metadata_ if isinstance(call.metadata_, dict) else {},
                "metrics": {
                    "input_tokens": call.input_tokens,
                    "output_tokens": call.output_tokens,
                    "duration_ms": _project_duration_ms(call.started_at, call.completed_at, call.status),
                },
                "blocks": blocks,
            })
        orphan_blocks = [_project_block(block, turn.final_reply_block_id, artifacts_by_block) for block in blocks_by_call.get(None, [])]
        if orphan_blocks:
            model_calls.append({
                "model_call_id": f"{turn.id}:orphan",
                "sequence": len(model_calls) + 1,
                "status": "completed",
                "metrics": {"input_tokens": None, "output_tokens": None, "duration_ms": None},
                "blocks": orphan_blocks,
            })
        started_at = turn.started_at
        ended_at = turn.terminal_at if status in {"completed", "failed"} else None
        duration_ms = _duration_ms(started_at, ended_at) if ended_at is not None or status in {"running", "waiting"} else None
        projected_turns.append({
            "turn_id": turn.id,
            "sequence": turn.sequence,
            "status": status,
            "user_text": turn.user_text,
            "final_reply_block_id": turn.final_reply_block_id,
            "metrics": {
                "duration_ms": duration_ms,
                "model_call_count": len(call_rows),
                "input_tokens": _sum_known([call.input_tokens for call in call_rows]),
                "output_tokens": _sum_known([call.output_tokens for call in call_rows]),
            },
            "model_calls": model_calls,
        })
    status = "idle"
    if turns:
        latest_status = projected_turns[-1]["status"]
        status = "idle" if latest_status == "completed" else latest_status
    return {
        "session_id": session_id,
        "status": status,
        "revision": revision,
        "turns": projected_turns,
    }


def _project_block(
    block: WriterTranscriptBlock,
    final_reply_block_id: str | None,
    artifacts_by_block: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    metadata = block.metadata_ if isinstance(block.metadata_, dict) else {}
    waiting_options = metadata.get("options") if isinstance(metadata.get("options"), list) else []
    waiting_permission = metadata.get("permission") if isinstance(metadata.get("permission"), dict) else {}
    return {
        "block_id": block.id,
        "parent_block_id": block.parent_block_id,
        "producer_id": block.producer_id,
        "sequence": block.sequence,
        "event_sequence": block.event_sequence,
        "type": block.type,
        "status": block.status,
        "content": block.content or "",
        "is_final_reply": bool(final_reply_block_id and block.id == final_reply_block_id),
        "duration_ms": block.duration_ms if block.duration_ms is not None else _project_duration_ms(block.started_at, block.completed_at, block.status),
        "tool": {
            "name": block.tool_name,
            "call_id": block.tool_call_id,
            "args": block.tool_args_json,
            "result_preview": block.tool_result_preview,
            "error": block.error,
        } if block.tool_name or block.tool_call_id or block.tool_result_preview else None,
        "waiting_request": {
            "kind": block.request_kind,
            "response": block.response_json,
            "tool_call_id": block.tool_call_id,
            "tool_name": block.tool_name,
            "args": block.tool_args_json or {},
            "options": waiting_options,
            "permission": waiting_permission,
        } if block.type == "waiting_request" else None,
        "artifacts": artifacts_by_block.get(block.id, []),
    }


def _sum_known(values: list[int | None]) -> int | None:
    known = [value for value in values if isinstance(value, int)]
    if not known:
        return None
    return sum(known)
