from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.writer.git import WriterGitManager
from app.models.base import gen_uuid
from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptBlock, WriterTranscriptModelCall, WriterTranscriptTurn
from app.services.session_projection import session_response_projected
from app.services.session_rollback_markers import is_rolled_back_metadata


_git_manager = WriterGitManager()


async def fork_session_response(
    db: AsyncSession,
    session_id: str,
    *,
    after_turn_id: str | None = None,
    title: str | None = None,
    isolated_worktree: bool = False,
) -> dict[str, Any]:
    source = await db.get(WriterSession, session_id)
    if source is None:
        raise LookupError("Session not found")

    source_turns = (
        await db.execute(
            select(WriterTranscriptTurn)
            .where(WriterTranscriptTurn.session_id == session_id)
            .order_by(WriterTranscriptTurn.sequence.asc())
        )
    ).scalars().all()
    visible_turns = [turn for turn in source_turns if not is_rolled_back_metadata(turn.metadata_)]
    included_turns = _included_turns(visible_turns, after_turn_id=after_turn_id)

    fork_id = gen_uuid()
    work_root = source.work_root or ""
    branch = source.branch
    worktree: dict[str, str] | None = None
    if isolated_worktree:
        worktree = await _create_isolated_worktree(work_root, fork_id)
        work_root = worktree["work_root"]
        branch = worktree["branch"]

    fork = WriterSession(
        id=fork_id,
        title=(title or f"{source.title} fork").strip() or "Forked Session",
        work_root=work_root,
        branch=branch,
        phase="idle",
        mode=source.mode or "EXECUTE",
        status="active",
        project_id=source.project_id,
        loop_position=source.loop_position or "execute",
        task_complexity=source.task_complexity or "simple",
        planning_depth=source.planning_depth,
        todos=list(source.todos or []) if isinstance(source.todos, list) else None,
        open_loops=list(source.open_loops or []) if isinstance(source.open_loops, list) else None,
        context_summary=source.context_summary,
        task_plan=dict(source.task_plan or {}) if isinstance(source.task_plan, dict) else None,
        runtime_state={
            "forked_from": {
                "session_id": source.id,
                "after_turn_id": after_turn_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "isolated_worktree": isolated_worktree,
                "worktree": worktree,
            }
        },
        metadata_={
            **(dict(source.metadata_ or {}) if isinstance(source.metadata_, dict) else {}),
            "forked_from_session_id": source.id,
            "forked_after_turn_id": after_turn_id,
        },
    )
    db.add(fork)
    await db.flush()

    message_clock = datetime.now(timezone.utc)
    for index, source_turn in enumerate(included_turns):
        await _copy_turn(db, source_turn=source_turn, fork_session_id=fork.id, message_clock=message_clock, index=index)

    fork.transcript_revision = len(included_turns)
    return await session_response_projected(db, fork)


async def _create_isolated_worktree(source_work_root: str, fork_id: str) -> dict[str, str]:
    if not source_work_root:
        raise ValueError("Session has no work_root set")
    root = Path(source_work_root).resolve()
    if not await _git_manager.is_repo(str(root)):
        raise ValueError("Not a git repository")
    branch = f"writer/session/{fork_id[:12]}"
    worktree_path = root / ".writer" / "worktrees" / f"session-{fork_id[:12]}"
    created = await _git_manager.create_worktree(
        str(root),
        branch=branch,
        path=str(worktree_path),
        start_point="HEAD",
    )
    if not created:
        raise ValueError("Failed to create isolated worktree")
    return {"branch": branch, "work_root": str(worktree_path)}


def _included_turns(
    visible_turns: list[WriterTranscriptTurn],
    *,
    after_turn_id: str | None,
) -> list[WriterTranscriptTurn]:
    if not after_turn_id:
        return visible_turns
    for index, turn in enumerate(visible_turns):
        if turn.id == after_turn_id:
            return visible_turns[: index + 1]
    raise LookupError("Turn not found")


async def _copy_turn(
    db: AsyncSession,
    *,
    source_turn: WriterTranscriptTurn,
    fork_session_id: str,
    message_clock: datetime,
    index: int,
) -> None:
    source_user = await db.get(WriterMessage, source_turn.user_message_id) if source_turn.user_message_id else None
    user_message_id = gen_uuid()
    if source_user is not None:
        db.add(
            WriterMessage(
                id=user_message_id,
                session_id=fork_session_id,
                role="user",
                content=source_user.content,
                parts=source_user.parts,
                turn_data=source_user.turn_data,
                metadata_=source_user.metadata_,
                run_id=source_user.run_id,
                created_at=message_clock + timedelta(microseconds=index * 2),
            )
        )

    new_turn = WriterTranscriptTurn(
        id=gen_uuid(),
        session_id=fork_session_id,
        sequence=source_turn.sequence,
        user_text=source_turn.user_text,
        user_message_id=user_message_id if source_user is not None else None,
        status_cache=source_turn.status_cache,
        started_at=source_turn.started_at,
        last_state_changed_at=source_turn.last_state_changed_at,
        terminal_at=source_turn.terminal_at,
        terminal_reason=source_turn.terminal_reason,
        error=source_turn.error,
        metadata_={
            **(dict(source_turn.metadata_ or {}) if isinstance(source_turn.metadata_, dict) else {}),
            "forked_from_turn_id": source_turn.id,
        },
    )
    db.add(new_turn)
    await db.flush()

    call_id_map = await _copy_model_calls(db, source_turn=source_turn, new_turn_id=new_turn.id)
    final_block_id, final_text = await _copy_blocks(
        db,
        source_turn=source_turn,
        new_turn_id=new_turn.id,
        call_id_map=call_id_map,
    )
    new_turn.final_reply_block_id = final_block_id
    if final_text:
        await _copy_assistant_message(
            db,
            session_id=source_turn.session_id,
            fork_session_id=fork_session_id,
            final_text=final_text,
            created_at=message_clock + timedelta(microseconds=index * 2 + 1),
        )


async def _copy_model_calls(
    db: AsyncSession,
    *,
    source_turn: WriterTranscriptTurn,
    new_turn_id: str,
) -> dict[str, str]:
    rows = (
        await db.execute(
            select(WriterTranscriptModelCall)
            .where(WriterTranscriptModelCall.turn_id == source_turn.id)
            .order_by(WriterTranscriptModelCall.sequence.asc())
        )
    ).scalars().all()
    mapping: dict[str, str] = {}
    for call in rows:
        new_id = f"{new_turn_id}:call:{call.sequence}"
        mapping[call.id] = new_id
        db.add(
            WriterTranscriptModelCall(
                id=new_id,
                turn_id=new_turn_id,
                sequence=call.sequence,
                provider=call.provider,
                model=call.model,
                status=call.status,
                started_at=call.started_at,
                completed_at=call.completed_at,
                input_tokens=call.input_tokens,
                output_tokens=call.output_tokens,
                error=call.error,
                metadata_=call.metadata_,
            )
        )
    return mapping


async def _copy_blocks(
    db: AsyncSession,
    *,
    source_turn: WriterTranscriptTurn,
    new_turn_id: str,
    call_id_map: dict[str, str],
) -> tuple[str | None, str]:
    rows = (
        await db.execute(
            select(WriterTranscriptBlock)
            .where(WriterTranscriptBlock.turn_id == source_turn.id)
            .order_by(WriterTranscriptBlock.event_sequence.asc(), WriterTranscriptBlock.sequence.asc())
        )
    ).scalars().all()
    block_id_map: dict[str, str] = {}
    final_block_id: str | None = None
    final_text = ""
    for block in rows:
        new_id = f"{new_turn_id}:block:{block.event_sequence}:{block.sequence}"
        block_id_map[block.id] = new_id
        if block.id == source_turn.final_reply_block_id:
            final_block_id = new_id
            final_text = block.content or ""
        db.add(
            WriterTranscriptBlock(
                id=new_id,
                turn_id=new_turn_id,
                model_call_id=call_id_map.get(block.model_call_id or "") if block.model_call_id else None,
                parent_block_id=block_id_map.get(block.parent_block_id or "") if block.parent_block_id else None,
                producer_id=block.producer_id,
                sequence=block.sequence,
                event_sequence=block.event_sequence,
                type=block.type,
                status=block.status,
                content=block.content,
                request_kind=block.request_kind,
                response_json=block.response_json,
                tool_name=block.tool_name,
                tool_call_id=block.tool_call_id,
                tool_args_json=block.tool_args_json,
                tool_result_preview=block.tool_result_preview,
                error=block.error,
                started_at=block.started_at,
                updated_at=block.updated_at,
                completed_at=block.completed_at,
                duration_ms=block.duration_ms,
                metadata_=block.metadata_,
            )
        )
    return final_block_id, final_text


async def _copy_assistant_message(
    db: AsyncSession,
    *,
    session_id: str,
    fork_session_id: str,
    final_text: str,
    created_at: datetime,
) -> None:
    source = (
        await db.execute(
            select(WriterMessage)
            .where(WriterMessage.session_id == session_id)
            .where(WriterMessage.role == "assistant")
            .where(WriterMessage.content == final_text)
            .order_by(WriterMessage.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if source is None:
        return
    db.add(
        WriterMessage(
            id=gen_uuid(),
            session_id=fork_session_id,
            role="assistant",
            content=source.content,
            parts=source.parts,
            turn_data=source.turn_data,
            metadata_=source.metadata_,
            run_id=source.run_id,
            created_at=created_at,
        )
    )
