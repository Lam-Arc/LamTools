from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.database import async_session, writer_write_coordinator
from app.models.session import WriterSession
from lamtools_core.runtime import default_runtime_task_registry



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


__all__ = ["WriterRuntimeLifecycle"]
