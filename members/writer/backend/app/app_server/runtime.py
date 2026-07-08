from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import select

from app.database import async_session
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptBlock, WriterTranscriptTurn
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import default_runtime_task_registry

from .hub import hub
from .queue import dispatch_next_queue_item, input_attachment_ids
from .runtime_bridge import persist_run_item_events_as_app_events
from .runtime_context import input_text, runtime_context_from_events


class WriterRuntimeLifecycle:
    def __init__(
        self,
        *,
        session_factory: Any = async_session,
        service_provider: Callable[[], Mapping[str, Any] | None] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._service_provider = service_provider or _default_service_provider

    def _writer_service(self) -> Mapping[str, Any]:
        service = self._service_provider()
        if service is None:
            raise RuntimeError("Writer service is unavailable")
        return service

    def writer_service_or_none(self) -> Mapping[str, Any] | None:
        return self._service_provider()

    def start(
        self,
        *,
        thread_id: str,
        turn_id: str,
        user_message_id: str,
        text: str,
        work_root: object = None,
        thinking_enabled: bool | None = None,
        thinking_budget: int | None = None,
        shallow_thinking_enabled: bool | None = None,
        model_id: str | None = None,
        attachment_ids: list[str] | None = None,
    ) -> None:
        runtime_tasks = default_runtime_task_registry()
        if runtime_tasks.task(thread_id, run_id=turn_id) is not None:
            return
        runtime_tasks.reset_cancel_event(thread_id)
        task = asyncio.create_task(
            self._run(
                thread_id=thread_id,
                turn_id=turn_id,
                user_message_id=user_message_id,
                text=text,
                work_root=work_root,
                thinking_enabled=thinking_enabled,
                thinking_budget=thinking_budget,
                shallow_thinking_enabled=shallow_thinking_enabled,
                model_id=model_id,
                attachment_ids=attachment_ids,
            )
        )
        runtime_tasks.register(thread_id, task, run_id=turn_id)

    async def continue_resolved_approval(
        self,
        *,
        request_id: str,
        thread_id: str,
        decision: str,
        guidance: str = "",
    ) -> None:
        action = {
            "approve_once": "approve",
            "approve_for_session": "approve",
            "deny": "deny",
            "other_guidance": "guide",
        }.get(decision)
        if action is None:
            return
        async with self._session_factory() as db:
            block_id = await self._find_single_open_waiting_block(db, thread_id=thread_id)
        if not block_id:
            await self._publish_approval_continuation_error(
                thread_id=thread_id,
                request_id=request_id,
                message="Cannot continue approval: no unique open waiting request.",
            )
            return

        try:
            service = self._writer_service()
            async with self._session_factory() as db:
                await service["respond_waiting_request"](
                    db=db,
                    session_id=thread_id,
                    block_id=block_id,
                    action=action,
                    response=guidance or action,
                )
            await self.dispatch_next_queue_item(thread_id=thread_id)
        except Exception as exc:
            await self._publish_approval_continuation_error(
                thread_id=thread_id,
                request_id=request_id,
                message=str(exc),
            )

    async def dispatch_next_queue_item(self, *, thread_id: str, work_root: object = None) -> None:
        async with self._session_factory() as db:
            dispatched = await dispatch_next_queue_item(
                db,
                thread_id=thread_id,
                work_root=work_root if isinstance(work_root, str) else None,
            )
            if dispatched is None:
                await db.commit()
                return
            _queue_item_id, input_items, events = dispatched
            await db.commit()
        for event in events:
            await hub.publish(event)
        turn_id, user_message_id = runtime_context_from_events(events)
        if turn_id and user_message_id:
            self.start(
                thread_id=thread_id,
                turn_id=turn_id,
                user_message_id=user_message_id,
                text=input_text(input_items),
                work_root=work_root,
                attachment_ids=input_attachment_ids(input_items),
            )

    async def _run(
        self,
        *,
        thread_id: str,
        turn_id: str,
        user_message_id: str,
        text: str,
        work_root: object = None,
        thinking_enabled: bool | None = None,
        thinking_budget: int | None = None,
        shallow_thinking_enabled: bool | None = None,
        model_id: str | None = None,
        attachment_ids: list[str] | None = None,
    ) -> None:
        try:
            service = self._writer_service()
            async with self._session_factory() as db:
                session = await db.get(WriterSession, thread_id)
                if session is None:
                    raise RuntimeError("Thread/session not found")
                if isinstance(work_root, str) and work_root:
                    from app.routers.path_utils import normalize_work_root

                    session.work_root = normalize_work_root(work_root)
                    await db.commit()
                await service["run_turn"](
                    db=db,
                    session_id=thread_id,
                    user_message=text,
                    thinking_enabled=thinking_enabled,
                    thinking_budget=thinking_budget,
                    shallow_thinking_enabled=shallow_thinking_enabled,
                    model_id=model_id,
                    user_message_id=user_message_id,
                    transcript_turn_id=turn_id,
                    attachment_ids=attachment_ids,
                )
            await self.dispatch_next_queue_item(thread_id=thread_id, work_root=work_root)
        except asyncio.CancelledError:
            await self._finish_failed(
                thread_id=thread_id,
                turn_id=turn_id,
                message="用户已停止本轮任务",
                reason="user_interrupt",
            )
            raise
        except Exception as exc:
            await self._finish_failed(
                thread_id=thread_id,
                turn_id=turn_id,
                message=str(exc),
                reason="runtime_error",
                include_error_event=True,
            )

    async def _finish_failed(
        self,
        *,
        thread_id: str,
        turn_id: str,
        message: str,
        reason: str,
        include_error_event: bool = False,
    ) -> None:
        run_item_events: list[RunItemEvent] = []
        if include_error_event:
            run_item_events.append(
                RunItemEvent(
                    kind="error",
                    thread_id=thread_id,
                    event_id=f"{turn_id}:runtime-error",
                    turn_id=turn_id,
                    item_id=f"{turn_id}:runtime-error",
                    status="failed",
                    payload={"type": "runtime", "message": message},
                )
            )
        run_item_events.append(
            RunItemEvent(
                kind="status",
                thread_id=thread_id,
                event_id=f"{turn_id}:runtime-failed",
                turn_id=turn_id,
                status="failed",
                payload={
                    "type": "turn",
                    "status": "failed",
                    "raw_end_reason": reason,
                    "message": message,
                },
            )
        )
        async with self._session_factory() as db:
            await self._persist_and_publish_run_item_events(db, run_item_events)

    async def _publish_approval_continuation_error(
        self,
        *,
        thread_id: str,
        request_id: str,
        message: str,
    ) -> None:
        run_item_events = [
            RunItemEvent(
                kind="error",
                thread_id=thread_id,
                event_id=f"{request_id}:approval-continuation-error",
                item_id=f"{request_id}:approval-continuation-error",
                status="failed",
                payload={"type": "approval", "request_id": request_id, "message": message},
            ),
            RunItemEvent(
                kind="status",
                thread_id=thread_id,
                event_id=f"{request_id}:approval-continuation-failed",
                status="failed",
                payload={
                    "type": "approval",
                    "status": "failed",
                    "request_id": request_id,
                    "raw_end_reason": "approval_continuation_error",
                    "message": message,
                },
            ),
        ]
        async with self._session_factory() as db:
            await self._persist_and_publish_run_item_events(db, run_item_events)

    async def _persist_and_publish_run_item_events(self, db, events: list[RunItemEvent]) -> None:
        envelopes = await persist_run_item_events_as_app_events(db, events)
        await db.commit()
        for envelope in envelopes:
            await hub.publish(envelope)

    async def _find_single_open_waiting_block(self, db, *, thread_id: str) -> str | None:
        rows = await db.execute(
            select(WriterTranscriptBlock)
            .join(WriterTranscriptTurn, WriterTranscriptTurn.id == WriterTranscriptBlock.turn_id)
            .where(
                WriterTranscriptTurn.session_id == thread_id,
                WriterTranscriptBlock.type == "waiting_request",
                WriterTranscriptBlock.completed_at.is_(None),
            )
            .order_by(WriterTranscriptTurn.sequence.desc(), WriterTranscriptBlock.sequence.desc())
            .limit(2)
        )
        blocks = list(rows.scalars().all())
        if len(blocks) != 1:
            return None
        return blocks[0].id


def _default_service_provider() -> Mapping[str, Any] | None:
    from app.routers import session as session_router

    return session_router._service


__all__ = ["WriterRuntimeLifecycle"]
