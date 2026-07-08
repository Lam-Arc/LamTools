from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptBlock, WriterTranscriptTurn
from app.services.app_projection_sink import AppProjectionSink
from app.services.checkpoint_service import WriterCheckpointService
from app.services.commit_review_service import WriterCommitReviewService
from app.services.runtime_fact_recorder import RuntimeFactRecorder
from app.services.runtime_finalization_sink import RuntimeFinalizationSink
from app.services.runtime_input_context import prepare_runtime_input_context
from lamtools_core.event.runtime_projection import runtime_group_from_event_name
from lamtools_core.kernel import KernelResult

logger = logging.getLogger(__name__)

RunCoreKernel = Callable[..., Awaitable[KernelResult]]
SummarizeKernelResult = Callable[[KernelResult], dict[str, Any]]
SchedulePrewarm = Callable[[str], None]
RuntimeTaskRegistryFactory = Callable[[], Any]
SubAgentLLMClientFactory = Callable[[Any, Any], Awaitable[Any]]


def _current_user_content(
    text: str,
    extra_blocks: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    if not extra_blocks:
        return None
    return [{"type": "text", "text": text}, *extra_blocks]


class WriterRuntimeRunner:
    def __init__(
        self,
        *,
        app_projection_sink: AppProjectionSink,
        state_store: Any,
        checkpoint_service: WriterCheckpointService,
        commit_review_service: WriterCommitReviewService,
        run_core_kernel: RunCoreKernel,
        summarize_result: SummarizeKernelResult,
        schedule_prewarm: SchedulePrewarm,
        runtime_task_registry: RuntimeTaskRegistryFactory,
    ) -> None:
        self._app_projection_sink = app_projection_sink
        self._state_store = state_store
        self._checkpoint_service = checkpoint_service
        self._commit_review_service = commit_review_service
        self._run_core_kernel = run_core_kernel
        self._summarize_result = summarize_result
        self._schedule_prewarm = schedule_prewarm
        self._runtime_task_registry = runtime_task_registry

    async def run(
        self,
        *,
        db: AsyncSession,
        session_id: str,
        transcript_turn_id: str,
        user_message: str,
        raw_user_message: str,
        user_content_blocks: list[dict[str, Any]] | None = None,
        llm_client: Any,
        work_root: str,
        runtime_controls: dict[str, dict[str, bool]] | None = None,
        sub_agent_llm_client_factory: SubAgentLLMClientFactory | None = None,
        model_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        input_context = await prepare_runtime_input_context(
            db,
            session_id=session_id,
            transcript_turn_id=transcript_turn_id,
            user_message=user_message,
            raw_user_message=raw_user_message,
        )
        turn = input_context.turn
        logger.info(
            "Session %s: using core kernel path with %d history entries",
            session_id,
            len(input_context.history),
        )

        recorder = RuntimeFactRecorder(
            db=db,
            session_id=session_id,
            turn=turn,
            app_projection_sink=self._app_projection_sink,
            model_context=model_context,
        )
        await recorder.start_runtime_producer()

        try:
            result = await self._run_core_kernel(
                goal=input_context.goal,
                user_content=_current_user_content(input_context.goal, user_content_blocks),
                session_id=session_id,
                llm_client=llm_client,
                work_root=work_root,
                history=input_context.history,
                state_store=self._state_store,
                live_event_callback=recorder.record_core_event,
                runtime_controls=runtime_controls,
                sub_agent_llm_client_factory=sub_agent_llm_client_factory,
                cancel_event=self._runtime_task_registry().get_cancel_event(session_id),
            )
        except Exception as exc:
            return await self._record_failure(db, session_id=session_id, recorder=recorder, exc=exc)

        summary = await self._finalize_run(
            db,
            session_id=session_id,
            turn=turn,
            result=result,
            recorder=recorder,
        )
        await self._checkpoint_and_review(
            db,
            session_id=session_id,
            turn=turn,
            summary=summary,
            result=result,
        )
        await self._record_terminal_fallback(
            db,
            turn=turn,
            result=result,
            summary=summary,
            recorder=recorder,
        )
        self._schedule_prewarm(work_root)
        return summary

    async def _record_failure(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        recorder: RuntimeFactRecorder,
        exc: Exception,
    ) -> dict[str, Any]:
        logger.error("Core kernel path failed for session %s: %s", session_id, exc, exc_info=True)
        try:
            await db.rollback()
        except Exception:
            logger.debug(
                "Unexpected error rolling back failed Writer runtime DB session for %s",
                session_id,
                exc_info=True,
            )
        await recorder.record(
            group="system",
            source="core",
            phase="runtime.failed",
            status="failed",
            summary=str(exc) or "运行失败",
            preview=str(exc),
            metadata={"payload": {"error": str(exc), "source": "service_exception"}},
        )
        return {"decision": "failed", "error": str(exc)}

    async def _finalize_run(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        turn: WriterTranscriptTurn,
        result: KernelResult,
        recorder: RuntimeFactRecorder,
    ) -> dict[str, Any]:
        summary = self._summarize_result(result)
        finalization_sink = RuntimeFinalizationSink(
            db=db,
            session_id=session_id,
            turn=turn,
            transcript_sink=recorder.transcript_sink,
        )
        finalized = await finalization_sink.persist_result(result, runtime_fact_sequence=recorder.sequence)
        if finalized.final_answer:
            summary["message"] = finalized.final_answer
            summary["final_answer"] = finalized.final_answer
        elif finalized.failure_summary:
            summary["message"] = finalized.failure_summary
            summary["failure_summary"] = finalized.failure_summary
        if finalized.message is not None:
            finalized.message.parts = {
                **(finalized.message.parts or {}),
                "core_kernel_summary": summary,
            }
            await db.commit()
        runtime_metrics = summary.get("runtime_metrics")
        if isinstance(runtime_metrics, dict) and runtime_metrics:
            await recorder.record(
                group="usage",
                source="core",
                phase="runtime.metrics",
                status="completed",
                summary="runtime.metrics",
                preview="",
                metadata={
                    "payload": {
                        "turn_id": turn.id,
                        "runtime_metrics": runtime_metrics,
                    }
                },
            )
        return summary

    async def _checkpoint_and_review(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        turn: WriterTranscriptTurn,
        summary: dict[str, Any],
        result: KernelResult,
    ) -> None:
        session = await db.get(WriterSession, session_id)
        if session is None:
            return
        checkpoint_reason = "本轮完成自动存档" if result.decision == "done" else "本轮结束自动存档"
        try:
            await self._checkpoint_service.checkpoint_if_dirty(
                db,
                session,
                reason=checkpoint_reason,
                turn_id=turn.id,
                stage="after_turn",
            )
            await db.refresh(session)
        except Exception:
            logger.debug("Unexpected error during Writer checkpoint for session %s", session_id, exc_info=True)

        review_request = self._commit_review_service.latest_request(summary)
        if not review_request:
            return
        try:
            await self._commit_review_service.persist_request(db, session, review_request)
        except Exception:
            logger.debug("Unexpected error while recording commit review for session %s", session_id, exc_info=True)

    async def _record_terminal_fallback(
        self,
        db: AsyncSession,
        *,
        turn: WriterTranscriptTurn,
        result: KernelResult,
        summary: dict[str, Any],
        recorder: RuntimeFactRecorder,
    ) -> None:
        final_decision = str(result.decision or "")
        if not recorder.seen_terminal_core_event and final_decision == "wait":
            if await self._has_open_waiting_request(db, turn):
                recorder.seen_terminal_core_event = True
        if recorder.seen_terminal_core_event:
            return

        terminal_phase = {
            "done": "runtime.done",
            "failed": "runtime.failed",
            "wait": "runtime.waiting",
        }.get(final_decision, "runtime.done")
        terminal_status = {
            "done": "completed",
            "failed": "failed",
            "wait": "waiting",
        }.get(final_decision, "completed")
        terminal_summary = (
            str(result.error or "").strip()
            or str(summary.get("message") or "").strip()
            or str(summary.get("decision") or "").strip()
            or "本轮运行结束"
        )
        await recorder.record(
            group=runtime_group_from_event_name(terminal_phase),
            source="core",
            phase=terminal_phase,
            status=terminal_status,
            summary=terminal_summary,
            preview=terminal_summary,
            metadata={
                "payload": {
                    "decision": final_decision,
                    "message": str(summary.get("message") or ""),
                    "error": str(result.error or ""),
                    "runtime_metrics": summary.get("runtime_metrics")
                    if isinstance(summary.get("runtime_metrics"), dict)
                    else {},
                    "source": "service_terminal_fallback",
                }
            },
        )

    async def _has_open_waiting_request(self, db: AsyncSession, turn: WriterTranscriptTurn) -> bool:
        result = await db.execute(
            select(WriterTranscriptBlock.id)
            .where(WriterTranscriptBlock.turn_id == turn.id)
            .where(WriterTranscriptBlock.type == "waiting_request")
            .where(WriterTranscriptBlock.completed_at.is_(None))
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
