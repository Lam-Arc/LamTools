from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.writer.git import WriterGitManager
from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptBlock, WriterTranscriptTurn
from app.services.session_rollback_markers import is_rolled_back_metadata, with_rolled_back_metadata
from app.services.session_git_operation import (
    SessionGitClaim,
    claim_session_git_operation,
    clear_session_git_claim,
    require_session_git_claim,
)
from app.services.transcript_service import bump_transcript_revision


_git_manager = WriterGitManager()


@dataclass(frozen=True)
class SessionRollbackClaim:
    session: SessionGitClaim
    target_turn_id: str
    target_sequence: int
    affected_turn_ids: list[str]
    restore_ref: str
    checkpoint_commit: str | None
    reason: str


async def claim_session_rollback(
    db: AsyncSession,
    session_id: str,
    *,
    turn_id: str | None = None,
    reason: str = "",
) -> SessionRollbackClaim:
    session = await db.get(WriterSession, session_id)
    if session is None:
        raise LookupError("Session not found")
    turns = (
        await db.execute(
            select(WriterTranscriptTurn)
            .where(WriterTranscriptTurn.session_id == session_id)
            .order_by(WriterTranscriptTurn.sequence.asc())
        )
    ).scalars().all()
    target = _target_turn(turns, turn_id=turn_id)
    if target is None:
        raise LookupError("Turn not found")
    affected = [
        turn for turn in turns
        if turn.sequence >= target.sequence and not is_rolled_back_metadata(turn.metadata_)
    ]
    checkpoint = _select_bound_checkpoint(session, target.id)
    return SessionRollbackClaim(
        session=claim_session_git_operation(session, "session.rollback"),
        target_turn_id=target.id,
        target_sequence=target.sequence,
        affected_turn_ids=[turn.id for turn in affected],
        restore_ref=_checkpoint_restore_ref(checkpoint) if checkpoint else "",
        checkpoint_commit=str(checkpoint.get("commit") or "") if checkpoint else None,
        reason=reason,
    )


async def execute_session_rollback(claim: SessionRollbackClaim) -> dict[str, Any]:
    if not claim.restore_ref:
        return {"status": "skipped", "source": "checkpoint", "ref": None, "message": "No checkpoint bound to turn"}
    if not claim.session.work_root:
        return {"status": "skipped", "source": "checkpoint", "ref": None, "message": "Session has no work_root set"}
    if not await _git_manager.is_repo(claim.session.work_root):
        return {"status": "skipped", "source": "checkpoint", "ref": None, "message": "Not a git repository"}
    if not await _git_manager.restore_checkpoint(claim.session.work_root, claim.restore_ref):
        raise ValueError("Failed to restore checkpoint")
    return {
        "status": "restored",
        "source": "checkpoint",
        "ref": claim.restore_ref,
        "checkpoint": claim.checkpoint_commit,
        "message": "已恢复到该任务前的检查点",
    }


async def persist_session_rollback(
    db: AsyncSession,
    claim: SessionRollbackClaim,
    restore: dict[str, Any],
) -> dict[str, Any]:
    session = await db.get(WriterSession, claim.session.session_id)
    if session is None:
        raise LookupError("Session not found")
    runtime_state = require_session_git_claim(session, claim.session)
    turns = list(
        (
            await db.execute(
                select(WriterTranscriptTurn)
                .where(WriterTranscriptTurn.id.in_(claim.affected_turn_ids))
                .order_by(WriterTranscriptTurn.sequence.asc())
            )
        ).scalars()
    )
    if [turn.id for turn in turns] != claim.affected_turn_ids:
        raise RuntimeError("Session turns changed while Git operation was running")
    target = next((turn for turn in turns if turn.id == claim.target_turn_id), None)
    if target is None or target.sequence != claim.target_sequence:
        raise RuntimeError("Rollback target changed while Git operation was running")
    marker = {
        "reason": claim.reason,
        "rolled_back_at": datetime.now(timezone.utc).isoformat(),
        "target_turn_id": target.id,
    }
    for turn in turns:
        turn.metadata_ = with_rolled_back_metadata(turn.metadata_, marker)
    await _mark_messages_rolled_back(
        db,
        session_id=claim.session.session_id,
        turns=turns,
        marker=marker,
    )
    session.runtime_state = runtime_state
    _append_session_rollback_marker(session, target=target, affected_turns=turns, marker=marker, restore=restore)
    runtime_state = dict(session.runtime_state or {})
    clear_session_git_claim(runtime_state, claim.session)
    session.runtime_state = runtime_state
    await bump_transcript_revision(db, claim.session.session_id)
    return {
        "status": "rolled_back",
        "session_id": claim.session.session_id,
        "target_turn_id": target.id,
        "rolled_back_turn_ids": [turn.id for turn in turns],
        "restore": restore,
        "message": "已回退到所选任务之前",
    }


async def rollback_session_turn_response(
    db: AsyncSession,
    session_id: str,
    *,
    turn_id: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    session = await db.get(WriterSession, session_id)
    if session is None:
        raise LookupError("Session not found")

    turns = (
        await db.execute(
            select(WriterTranscriptTurn)
            .where(WriterTranscriptTurn.session_id == session_id)
            .order_by(WriterTranscriptTurn.sequence.asc())
        )
    ).scalars().all()
    target = _target_turn(turns, turn_id=turn_id)
    if target is None:
        raise LookupError("Turn not found")

    affected_turns = [
        turn
        for turn in turns
        if turn.sequence >= target.sequence and not is_rolled_back_metadata(turn.metadata_)
    ]
    now = datetime.now(timezone.utc)
    marker = {
        "reason": reason,
        "rolled_back_at": now.isoformat(),
        "target_turn_id": target.id,
    }
    for turn in affected_turns:
        turn.metadata_ = with_rolled_back_metadata(turn.metadata_, marker)

    restore = await _restore_bound_checkpoint(session, target)
    await _mark_messages_rolled_back(db, session_id=session_id, turns=affected_turns, marker=marker)
    _append_session_rollback_marker(session, target=target, affected_turns=affected_turns, marker=marker, restore=restore)
    await bump_transcript_revision(db, session_id)
    return {
        "status": "rolled_back",
        "session_id": session_id,
        "target_turn_id": target.id,
        "rolled_back_turn_ids": [turn.id for turn in affected_turns],
        "restore": restore,
        "message": "已回退到所选任务之前",
    }


def _target_turn(turns: list[WriterTranscriptTurn], *, turn_id: str | None) -> WriterTranscriptTurn | None:
    if turn_id:
        for turn in turns:
            if turn.id == turn_id and not is_rolled_back_metadata(turn.metadata_):
                return turn
        return None
    for turn in reversed(turns):
        if is_rolled_back_metadata(turn.metadata_):
            continue
        if str(turn.status_cache or "").lower() == "completed" or turn.final_reply_block_id:
            return turn
    return None


async def _mark_messages_rolled_back(
    db: AsyncSession,
    *,
    session_id: str,
    turns: list[WriterTranscriptTurn],
    marker: dict[str, Any],
) -> None:
    if not turns:
        return
    user_message_ids = {turn.user_message_id for turn in turns if turn.user_message_id}
    final_reply_ids = {turn.final_reply_block_id for turn in turns if turn.final_reply_block_id}
    final_reply_texts: set[str] = set()
    if final_reply_ids:
        blocks = (
            await db.execute(select(WriterTranscriptBlock).where(WriterTranscriptBlock.id.in_(final_reply_ids)))
        ).scalars().all()
        final_reply_texts = {str(block.content or "") for block in blocks if str(block.content or "")}

    messages = (
        await db.execute(
            select(WriterMessage)
            .where(WriterMessage.session_id == session_id)
            .where(WriterMessage.role.in_(("user", "assistant")))
            .order_by(WriterMessage.created_at.asc())
        )
    ).scalars().all()
    for message in messages:
        should_mark = message.id in user_message_ids
        if message.role == "assistant" and message.content and message.content in final_reply_texts:
            should_mark = True
        if should_mark:
            message.metadata_ = with_rolled_back_metadata(message.metadata_, marker)


def _append_session_rollback_marker(
    session: WriterSession,
    *,
    target: WriterTranscriptTurn,
    affected_turns: list[WriterTranscriptTurn],
    marker: dict[str, Any],
    restore: dict[str, Any],
) -> None:
    runtime_state = dict(session.runtime_state or {})
    history = runtime_state.get("rollback_history")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            **marker,
            "target_turn_id": target.id,
            "target_sequence": target.sequence,
            "rolled_back_turn_ids": [turn.id for turn in affected_turns],
            "restore": restore,
        }
    )
    runtime_state["rollback_history"] = history[-50:]
    git_state = runtime_state.get("git_state")
    if isinstance(git_state, dict) and restore.get("status") == "restored":
        git_state["last_restore"] = {
            "commit": restore.get("ref"),
            "restored_at": marker.get("rolled_back_at"),
            "source": "session.rollback_turn",
            "target_turn_id": target.id,
        }
        runtime_state["git_state"] = git_state
    session.runtime_state = runtime_state
    session.updated_at = datetime.now(timezone.utc)


async def _restore_bound_checkpoint(session: WriterSession, target: WriterTranscriptTurn) -> dict[str, Any]:
    if not session.work_root:
        return {"status": "skipped", "source": "checkpoint", "ref": None, "message": "Session has no work_root set"}
    if not await _git_manager.is_repo(session.work_root):
        return {"status": "skipped", "source": "checkpoint", "ref": None, "message": "Not a git repository"}

    checkpoint = _select_bound_checkpoint(session, target.id)
    if checkpoint is None:
        return {"status": "skipped", "source": "checkpoint", "ref": None, "message": "No checkpoint bound to turn"}

    restore_ref = _checkpoint_restore_ref(checkpoint)
    if not restore_ref:
        return {"status": "skipped", "source": "checkpoint", "ref": None, "message": "Checkpoint has no restore ref"}
    restored = await _git_manager.restore_checkpoint(session.work_root, restore_ref)
    if not restored:
        raise ValueError("Failed to restore checkpoint")
    return {
        "status": "restored",
        "source": "checkpoint",
        "ref": restore_ref,
        "checkpoint": checkpoint.get("commit"),
        "message": "已恢复到该任务前的检查点",
    }


def _select_bound_checkpoint(session: WriterSession, turn_id: str) -> dict[str, Any] | None:
    runtime_state = dict(session.runtime_state or {})
    git_state = runtime_state.get("git_state")
    checkpoints = git_state.get("checkpoints") if isinstance(git_state, dict) else None
    if not isinstance(checkpoints, list):
        return None
    for item in reversed(checkpoints):
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        item_turn_id = item.get("turn_id") or item.get("transcript_turn_id") or metadata.get("turn_id")
        if str(item_turn_id or "") == turn_id:
            return dict(item)
    return None


def _checkpoint_restore_ref(checkpoint: dict[str, Any]) -> str:
    stage = str(checkpoint.get("stage") or checkpoint.get("checkpoint_stage") or "")
    if stage == "after_turn":
        for key in ("rollback_ref", "before_commit", "base_head", "commit"):
            value = str(checkpoint.get(key) or "").strip()
            if value:
                return value
        return ""
    for key in ("rollback_ref", "commit", "base_head"):
        value = str(checkpoint.get(key) or "").strip()
        if value:
            return value
    return ""
