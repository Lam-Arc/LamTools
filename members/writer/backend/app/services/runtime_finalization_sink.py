from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import gen_uuid
from app.models.message import WriterMessage
from app.models.transcript import WriterTranscriptBlock, WriterTranscriptModelCall, WriterTranscriptTurn
from app.services.runtime_transcript_sink import RuntimeTranscriptSink
from app.services.transcript_service import (
    bump_transcript_revision,
    upsert_block,
    utc_now,
)


@dataclass
class FinalizedRun:
    final_answer: str = ""
    failure_summary: str = ""
    turn_number: int = 0
    message: WriterMessage | None = None


class RuntimeFinalizationSink:
    def __init__(
        self,
        *,
        db: AsyncSession,
        session_id: str,
        turn: WriterTranscriptTurn,
        transcript_sink: RuntimeTranscriptSink,
    ) -> None:
        self._db = db
        self._session_id = session_id
        self._turn = turn
        self._transcript_sink = transcript_sink

    async def persist_result(self, result: Any, *, runtime_fact_sequence: int) -> FinalizedRun:
        final = _finalized_run_from_result(result)
        if final.final_answer:
            final.message = await self._persist_final_answer(final.final_answer, final.turn_number, runtime_fact_sequence)
            return final
        if final.failure_summary:
            final.message = await self._persist_failure_summary(final.failure_summary, final.turn_number)
        return final

    async def _persist_final_answer(
        self,
        final_answer: str,
        turn_number: int,
        runtime_fact_sequence: int,
    ) -> WriterMessage:
        existing_final_block = await self._find_final_reply_block(final_answer)
        final_call = (
            await self._db.get(WriterTranscriptModelCall, existing_final_block.model_call_id)
            if existing_final_block and existing_final_block.model_call_id
            else None
        ) or await self._transcript_sink.latest_model_call()
        if existing_final_block is not None:
            final_block = await upsert_block(
                self._db,
                turn=self._turn,
                block_id=existing_final_block.id,
                model_call_id=existing_final_block.model_call_id or final_call.id,
                block_type="model_text",
                sequence=existing_final_block.sequence,
                event_sequence=existing_final_block.event_sequence,
                status="completed",
                content=final_answer,
                producer_id=existing_final_block.producer_id or final_call.id,
                metadata=existing_final_block.metadata_,
            )
        else:
            final_block = await upsert_block(
                self._db,
                turn=self._turn,
                block_id=f"{final_call.id}:final-text",
                model_call_id=final_call.id,
                block_type="model_text",
                sequence=runtime_fact_sequence + 1,
                event_sequence=runtime_fact_sequence + 1,
                status="completed",
                content=final_answer,
                producer_id=final_call.id,
                metadata={"source": "final_reply_fallback"},
            )
        self._turn.final_reply_block_id = final_block.id
        final_call.status = "completed"
        final_call.completed_at = final_call.completed_at or utc_now()
        await bump_transcript_revision(self._db, self._turn.session_id)
        message = WriterMessage(
            id=gen_uuid(),
            session_id=self._session_id,
            role="assistant",
            content=final_answer,
            parts={
                "final_answer": True,
                "turn_number": turn_number,
            },
        )
        self._db.add(message)
        return message

    async def _persist_failure_summary(self, failure_summary: str, turn_number: int) -> WriterMessage:
        message = WriterMessage(
            id=gen_uuid(),
            session_id=self._session_id,
            role="assistant",
            content=failure_summary,
            parts={
                "failure_summary": failure_summary,
                "turn_number": turn_number,
            },
        )
        self._db.add(message)
        return message

    async def _find_final_reply_block(self, final_answer: str) -> WriterTranscriptBlock | None:
        normalized_answer = final_answer.strip()
        result = await self._db.execute(
            select(WriterTranscriptBlock)
            .where(WriterTranscriptBlock.turn_id == self._turn.id)
            .where(WriterTranscriptBlock.type == "model_text")
            .order_by(WriterTranscriptBlock.event_sequence.desc(), WriterTranscriptBlock.sequence.desc())
        )
        fallback: WriterTranscriptBlock | None = None
        for block in result.scalars().all():
            metadata = block.metadata_ if isinstance(block.metadata_, dict) else {}
            runtime_fact = metadata.get("runtime_fact") if isinstance(metadata, dict) else {}
            payload = runtime_fact.get("payload") if isinstance(runtime_fact, dict) else {}
            if isinstance(payload, dict) and payload.get("final_response") is True and fallback is None:
                fallback = block
            if str(block.content or "").strip() == normalized_answer:
                return block
        return fallback


def _finalized_run_from_result(result: Any) -> FinalizedRun:
    final_answer = ""
    failure_summary = ""
    turn_number = 0
    if result.decision == "done":
        for ks in reversed(result.steps):
            turn_reply = (ks.turn.reply if ks.turn else "") or ""
            has_tools = bool(ks.turn and ks.turn.tool_calls)
            if turn_reply and not has_tools:
                final_answer = turn_reply
                turn_number = ks.index + 1
                break
        if not final_answer:
            final_answer = _fallback_delivery_answer(result)
            turn_number = len(result.steps)
    elif result.decision == "failed":
        failure_summary = str(result.message or "").strip() or str(result.error or "").strip()
        turn_number = len(result.steps)
    return FinalizedRun(final_answer=final_answer, failure_summary=failure_summary, turn_number=turn_number)


def _fallback_delivery_answer(result: Any) -> str:
    metadata = getattr(result, "metadata", {}) or {}
    state = getattr(result, "state", None)
    state_metadata = getattr(state, "metadata", {}) if state is not None else {}
    if not isinstance(state_metadata, dict):
        state_metadata = {}
    written_files = metadata.get("written_files") or state_metadata.get("written_files")
    files = [str(item) for item in written_files if str(item).strip()] if isinstance(written_files, list) else []
    if not files:
        return str(getattr(result, "message", "") or "").strip()

    lines = ["任务已完成，但模型没有返回最终正文。已检测到交付文件："]
    for path in files[:12]:
        lines.append(f"- {path}")
    if len(files) > 12:
        lines.append(f"- 另有 {len(files) - 12} 个文件")

    verification = metadata.get("verification_summaries")
    if isinstance(verification, list) and verification:
        last = verification[-1]
        if isinstance(last, dict):
            summary = str(last.get("summary") or "").strip()
            if summary:
                lines.append(f"\n验证结果：{summary}")
    return "\n".join(lines)
