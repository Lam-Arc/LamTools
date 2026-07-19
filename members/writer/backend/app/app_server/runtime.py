from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import logging
from typing import Any
import uuid

from app.database import async_session, writer_write_coordinator
from app.models.session import WriterSession
from lamtools_core.runtime import default_runtime_task_registry


logger = logging.getLogger(__name__)


class WriterRuntimeLifecycle:
    def __init__(
        self,
        *,
        session_factory: Any = async_session,
        service_provider: Callable[[], Mapping[str, Any] | None] | None = None,
        runtime_task_registry: Any = None,
        write_coordinator: Any | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._service_provider = service_provider or _default_service_provider
        self._runtime_task_registry = runtime_task_registry or default_runtime_task_registry()
        self._write_coordinator = write_coordinator or writer_write_coordinator(session_factory)

    def _writer_service(self) -> Mapping[str, Any]:
        service = self._service_provider()
        if service is None:
            raise RuntimeError("Writer service is unavailable")
        return service

    def writer_service_or_none(self) -> Mapping[str, Any] | None:
        return self._service_provider()

    @property
    def runtime_task_registry(self) -> Any:
        return self._runtime_task_registry

    async def approval_coordinator(self, thread_id: str) -> Any:
        service = self._writer_service()
        return await service["create_approval_coordinator"](thread_id)

    async def list_sub_agents(self, thread_id: str) -> list[dict[str, Any]]:
        records = await self._writer_service()["list_sub_agents"](session_id=thread_id)
        return [self._with_live_sub_agent_status(record) for record in records]

    async def get_sub_agent(self, thread_id: str, sub_session_id: str) -> dict[str, Any]:
        record = await self._writer_service()["get_sub_agent"](
            session_id=thread_id,
            sub_session_id=sub_session_id,
        )
        return self._with_live_sub_agent_status(record)

    async def delete_session(self, thread_id: str) -> None:
        service = self._writer_service()
        delete_session = service.get("delete_session")
        if not callable(delete_session):
            raise RuntimeError("Writer session deletion is unavailable")
        await delete_session(None, thread_id)

    def _with_live_sub_agent_status(self, record: dict[str, Any]) -> dict[str, Any]:
        sub_session_id = str(record.get("session_id") or "").strip()
        active_run_id = self._runtime_task_registry.active_run_id(sub_session_id) if sub_session_id else None
        if not active_run_id:
            return record
        return {**record, "status": "running", "active_run_id": active_run_id}

    async def start_sub_agent_turn(
        self,
        *,
        thread_id: str,
        sub_session_id: str,
        prompt: str,
        model_id: str | None = None,
        thinking_enabled: bool | None = None,
        thinking_budget: int | None = None,
        shallow_thinking_enabled: bool | None = None,
    ) -> dict[str, Any]:
        service = self._writer_service()
        record = await service["get_sub_agent"](
            session_id=thread_id,
            sub_session_id=sub_session_id,
        )
        if record.get("can_continue") is False or str(record.get("status") or "") in {"pending", "waiting"}:
            raise ValueError("Sub-agent is waiting for user approval")
        if self._runtime_task_registry.active_run_id(sub_session_id):
            raise ValueError("Sub-agent session has an active turn")
        if self._runtime_task_registry.active_run_id(thread_id):
            raise ValueError("Main session has an active turn")
        run_id = f"{sub_session_id}:turn:{uuid.uuid4().hex[:12]}"
        if not self._runtime_task_registry.accept_run(thread_id, run_id):
            raise ValueError("Main session has an active turn")
        if not self._runtime_task_registry.accept_run(sub_session_id, run_id):
            self._runtime_task_registry.release_run(thread_id, run_id=run_id)
            raise ValueError("Sub-agent session has an active turn")

        async def execute() -> None:
            try:
                await service["run_sub_agent_turn"](
                    session_id=thread_id,
                    sub_session_id=sub_session_id,
                    prompt=prompt,
                    model_id=model_id,
                    thinking_enabled=thinking_enabled,
                    thinking_budget=thinking_budget,
                    shallow_thinking_enabled=shallow_thinking_enabled,
                )
            except BaseException as error:
                mark_failed = service.get("mark_sub_agent_failed")
                if callable(mark_failed):
                    try:
                        await mark_failed(
                            session_id=thread_id,
                            sub_session_id=sub_session_id,
                            error=str(error) or type(error).__name__,
                        )
                    except BaseException:
                        logger.exception("Failed to persist Sub-agent failure: session=%s", sub_session_id)
                raise

        coroutine = execute()
        try:
            task = asyncio.get_running_loop().create_task(coroutine)
        except BaseException:
            coroutine.close()
            self._runtime_task_registry.release_run(thread_id, run_id=run_id)
            self._runtime_task_registry.release_run(sub_session_id, run_id=run_id)
            raise
        parent_registered = not task.done() and self._runtime_task_registry.register(
            thread_id,
            task,
            run_id=run_id,
        )
        child_registered = parent_registered and self._runtime_task_registry.register(
            sub_session_id,
            task,
            run_id=run_id,
        )
        if not parent_registered or not child_registered:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self._runtime_task_registry.release_run(thread_id, run_id=run_id)
            self._runtime_task_registry.release_run(sub_session_id, run_id=run_id)
            raise ValueError("Sub-agent session has an active turn")
        task.add_done_callback(
            lambda done_task: _consume_sub_agent_task_result(
                done_task,
                sub_session_id=sub_session_id,
                run_id=run_id,
            )
        )
        return {"accepted": True, "session_id": sub_session_id, "run_id": run_id}

    async def run_accepted_turn(
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
        service = self._writer_service()
        async with self._session_factory() as db:
            session = await db.get(WriterSession, thread_id)
        if session is None:
            raise RuntimeError("Thread/session not found")
        if isinstance(work_root, str) and work_root:
            from app.services.session_management import update_writer_session

            async def update_work_root(db):
                try:
                    await update_writer_session(db, thread_id, {"work_root": work_root})
                except LookupError as exc:
                    raise RuntimeError("Thread/session not found") from exc

            await self._write_coordinator.run(update_work_root)
        await service["run_turn"](
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

def _default_service_provider() -> Mapping[str, Any] | None:
    from app.routers import session as session_router

    return session_router._service


def _consume_sub_agent_task_result(
    task: asyncio.Task[Any],
    *,
    sub_session_id: str,
    run_id: str,
) -> None:
    if task.cancelled():
        return
    try:
        error = task.exception()
    except asyncio.CancelledError:
        return
    if error is not None:
        logger.error(
            "Sub-agent turn failed: session=%s run=%s",
            sub_session_id,
            run_id,
            exc_info=(type(error), error, error.__traceback__),
        )


__all__ = ["WriterRuntimeLifecycle"]
