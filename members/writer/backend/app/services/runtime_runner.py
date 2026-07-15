from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.writer.llm_bridge import WriterLLMClientAdapter
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptTurn
from app.services.app_projection_sink import AppProjectionSink
from app.services.checkpoint_service import WriterCheckpointService
from app.services.commit_review_service import WriterCommitReviewService
from app.services.runtime_fact_recorder import RuntimeFactRecorder
from app.services.runtime_finalization_sink import RuntimeFinalizationSink
from app.services.runtime_input_context import prepare_runtime_input_context
from app.services.session_compaction_service import (
    apply_session_context_compaction,
    execute_session_context_compaction,
    prepare_session_context_compaction,
    session_needs_context_compaction,
)
from lamtools_core.event import CoreEvent
from lamtools_core.event.runtime_projection import runtime_group_from_event_name
from lamtools_core.kernel import KernelResult, LoopPolicy
from lamtools_core.llm.policy import RetryPolicy

logger = logging.getLogger(__name__)

RunCoreKernel = Callable[..., Awaitable[KernelResult]]
SummarizeKernelResult = Callable[[KernelResult], dict[str, Any]]
SchedulePrewarm = Callable[[str], None]
RuntimeTaskRegistryFactory = Callable[[], Any]
def _current_user_content(
    text: str,
    extra_blocks: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    if not extra_blocks:
        return None
    return [{"type": "text", "text": text}, *extra_blocks]


def _int_result(result: dict[str, Any], key: str) -> int:
    value = result.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def _string_list_result(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


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
        write_coordinator: Any | None = None,
    ) -> None:
        self._app_projection_sink = app_projection_sink
        self._state_store = state_store
        self._checkpoint_service = checkpoint_service
        self._commit_review_service = commit_review_service
        self._run_core_kernel = run_core_kernel
        self._summarize_result = summarize_result
        self._schedule_prewarm = schedule_prewarm
        self._runtime_task_registry = runtime_task_registry
        self._write_coordinator = write_coordinator

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
        model_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pre_run_compaction = await self._compact_before_history_cap(
            db,
            session_id=session_id,
            llm_client=llm_client,
            model_context=model_context,
        )
        async def load_input(read_db: AsyncSession):
            return await prepare_runtime_input_context(
                read_db,
                session_id=session_id,
                transcript_turn_id=transcript_turn_id,
                user_message=user_message,
                raw_user_message=raw_user_message,
            )

        if self._write_coordinator is not None:
            async with self._write_coordinator.session_factory() as read_db:
                input_context = await load_input(read_db)
        else:
            input_context = await load_input(db)
        turn = input_context.turn
        logger.info(
            "Session %s: using core kernel path with %d history entries",
            session_id,
            len(input_context.history),
        )

        recorder = RuntimeFactRecorder(
            db=db if self._write_coordinator is None else None,
            session_id=session_id,
            turn=turn if self._write_coordinator is None else None,
            turn_id=turn.id,
            app_projection_sink=self._app_projection_sink,
            model_context=model_context,
            write_coordinator=self._write_coordinator,
        )
        await recorder.start_runtime_producer()
        if pre_run_compaction is not None:
            try:
                await self._record_pre_run_compaction(
                    recorder,
                    session_id=session_id,
                    result=pre_run_compaction,
                )
            except Exception:
                logger.warning(
                    "Session %s: context pre-compaction visibility event failed",
                    session_id,
                    exc_info=True,
                )

        runtime_task_registry = self._runtime_task_registry()
        guidance_source_factory = getattr(runtime_task_registry, "guidance_source", None)
        guidance_source = (
            guidance_source_factory(session_id, run_id=turn.id)
            if callable(guidance_source_factory)
            else None
        )
        guidance_finalizer_factory = getattr(runtime_task_registry, "guidance_finalizer", None)
        guidance_finalizer = (
            guidance_finalizer_factory(session_id, run_id=turn.id)
            if callable(guidance_finalizer_factory)
            else None
        )
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
                cancel_event=runtime_task_registry.get_cancel_event(session_id),
                run_id=turn.id,
                turn_id=turn.id,
                guidance_source=guidance_source,
                guidance_finalizer=guidance_finalizer,
            )
        except BaseException:
            raise

        replay_events = (
            []
            if recorder.has_recorded_core_events
            else list((getattr(result, "metadata", {}) or {}).get("core_events") or [])
        )
        for raw in replay_events:
            if not isinstance(raw, dict):
                continue
            event_name = str(raw.get("name") or raw.get("event_name") or "")
            if not event_name:
                continue
            await recorder.record_core_event(CoreEvent(
                name=event_name,
                category=str(raw.get("category") or "progress"),
                payload=dict(raw.get("payload") or {
                    "summary": raw.get("summary") or "",
                    "status": raw.get("status") or "",
                }),
                event_id=str(raw.get("event_id") or f"{turn.id}:{event_name}:{raw.get('sequence', '')}"),
                session_id=session_id,
                run_id=str(raw.get("run_id") or turn.id),
                turn_id=str(raw.get("turn_id") or turn.id),
                sequence=raw.get("sequence") if isinstance(raw.get("sequence"), int) else None,
            ))

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
        self._schedule_prewarm(work_root)
        return summary

    async def _compact_before_history_cap(
        self,
        db: AsyncSession,
        *,
        session_id: str,
        llm_client: Any,
        model_context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        try:
            read_db = db
            if self._write_coordinator is not None:
                async with self._write_coordinator.session_factory() as candidate:
                    should_compact = await session_needs_context_compaction(candidate, session_id=session_id)
                    plan = (
                        await prepare_session_context_compaction(candidate, session_id=session_id, trigger="auto")
                        if should_compact else None
                    )
            else:
                should_compact = await session_needs_context_compaction(read_db, session_id=session_id)
                plan = (
                    await prepare_session_context_compaction(read_db, session_id=session_id, trigger="auto")
                    if should_compact else None
                )
            if not should_compact:
                return None
            loop_policy = LoopPolicy()
            _result, payload = await execute_session_context_compaction(
                plan,
                llm_client=self._compaction_llm_client(llm_client),
                model=str((model_context or {}).get("model") or ""),
                model_retries=loop_policy.model_retries,
                model_timeout_seconds=loop_policy.model_timeout_seconds,
                retry_policy=RetryPolicy(),
            )
            if self._write_coordinator is not None:
                return await self._write_coordinator.run(
                    lambda write_db: apply_session_context_compaction(write_db, plan=plan, payload=payload)
                )
            return await apply_session_context_compaction(db, plan=plan, payload=payload)
        except Exception:
            logger.warning(
                "Session %s: context pre-compaction failed; falling back to recent-history cap",
                session_id,
                exc_info=True,
            )
            return None

    @staticmethod
    def _compaction_llm_client(llm_client: Any) -> Any:
        if hasattr(llm_client, "complete"):
            return llm_client
        if hasattr(llm_client, "chat_full"):
            return WriterLLMClientAdapter(writer_client=llm_client)
        return None

    async def _record_pre_run_compaction(
        self,
        recorder: RuntimeFactRecorder,
        *,
        session_id: str,
        result: dict[str, Any],
    ) -> None:
        summary = str(result.get("summary") or result.get("content") or "").strip()
        compaction_status = str(result.get("status") or "failed")
        run_id = f"{session_id}:pre-run-compaction"
        compacted_messages = _int_result(result, "compacted_messages")
        retained_messages = _int_result(result, "retained_messages")
        before_tokens = _int_result(result, "before_tokens")
        after_tokens = _int_result(result, "after_tokens")
        limit_tokens = _int_result(result, "limit_tokens")
        common_payload = {
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "limit_tokens": limit_tokens,
            "trigger_tokens": 0,
            "window_tokens": 0,
            "trigger": "auto",
            "compacted_message_ids": _string_list_result(result.get("compacted_message_ids")),
            "retained_message_ids": _string_list_result(result.get("retained_message_ids")),
        }
        await recorder.record_core_event(
            CoreEvent(
                name="runtime.part",
                category="progress",
                payload={
                    **common_payload,
                    "part_id": f"{run_id}:context-compaction",
                    "part_type": "compaction",
                    "status": "completed" if compaction_status in {"compacted", "not_needed"} else "failed",
                    "compaction_status": compaction_status,
                    "label": str(result.get("label") or ("无需压缩" if compaction_status == "not_needed" else "压缩未完成" if compaction_status == "failed" else "上下文已压缩")),
                    "detail": f"{before_tokens} -> {after_tokens} tokens",
                    "content": summary[:20_000],
                    "compacted_messages": compacted_messages,
                    "retained_messages": retained_messages,
                    "removed_messages": compacted_messages,
                },
                session_id=session_id,
                run_id=run_id,
                tags=["compaction", "token_budget", "part"],
            )
        )
        if compaction_status != "compacted":
            return
        await recorder.record_core_event(
            CoreEvent(
                name="runtime.context_compacted",
                category="progress",
                payload={
                    **common_payload,
                    "removed": compacted_messages,
                    "before_messages": compacted_messages + retained_messages,
                    "after_messages": retained_messages + 1,
                    "summary": summary[:20_000],
                },
                session_id=session_id,
                run_id=run_id,
                tags=["compaction", "token_budget"],
            )
        )

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
        async def write(write_db: AsyncSession):
            persisted_turn = await write_db.get(WriterTranscriptTurn, turn.id)
            if persisted_turn is None:
                raise RuntimeError("Transcript turn was not created")
            from app.services.runtime_transcript_sink import RuntimeTranscriptSink
            sink = RuntimeFinalizationSink(
                db=write_db,
                session_id=session_id,
                turn=persisted_turn,
                transcript_sink=RuntimeTranscriptSink(db=write_db, turn=persisted_turn),
            )
            finalized = await sink.persist_result(result, runtime_fact_sequence=recorder.sequence)
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
            return finalized

        finalized = (
            await self._write_coordinator.run(write)
            if self._write_coordinator is not None
            else await write(db)
        )
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
        if self._write_coordinator is not None:
            async with self._write_coordinator.session_factory() as read_db:
                session = await read_db.get(WriterSession, session_id)
                session_info = (
                    {"id": session.id, "work_root": session.work_root or ""}
                    if session is not None else None
                )
            if session_info is None:
                return
            checkpoint_reason = "本轮完成自动存档" if result.decision == "done" else "本轮结束自动存档"
            create_checkpoint = getattr(self._checkpoint_service, "create_checkpoint_if_dirty", None)
            persist_checkpoint = getattr(self._checkpoint_service, "persist_checkpoint", None)
            if not callable(create_checkpoint) or not callable(persist_checkpoint):
                return
            record = await create_checkpoint(
                session_id=session_id,
                work_root=session_info["work_root"],
                reason=checkpoint_reason,
                turn_id=turn.id,
                stage="after_turn",
            )
            if record is not None:
                await self._write_coordinator.run(
                    lambda write_db: persist_checkpoint(
                        write_db, session_id=session_id, record=record,
                    )
                )
            return

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
