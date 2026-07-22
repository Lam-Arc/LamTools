from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import settings
from app.database import async_session
from app.models.session import WriterSession
from app.services.project_management import create_writer_project_session
from app.app_server.persistence import writer_persistence_host
from lamtools_core.app import OperationCatalog, OperationRequest, OperationResult, open_core_app_db
from lamtools_core.app.durable_operations import register_durable_operations
from lamtools_core.runtime.arrange import ArrangeManager, ArrangeRunner, arranged_operation_payload
from lamtools_core.runtime.goal import GoalManager
from lamtools_core.runtime.observer import ObserverSupervisor


class WriterDurableRuntime:
    def __init__(self) -> None:
        self.db: Any | None = None
        self.catalog = OperationCatalog()
        self.goal_manager: GoalManager | None = None
        self.arrange_manager: ArrangeManager | None = None
        self.runner: ArrangeRunner | None = None
        self.observer_supervisor: ObserverSupervisor | None = None

    async def start(self) -> None:
        if self.db is not None:
            return
        self.db = await open_core_app_db(Path(settings.data_dir) / "core.db")
        self.goal_manager = GoalManager(self.db.goal_store)
        self.arrange_manager = ArrangeManager(self.db.arrange_store)

        async def turn_start(request: OperationRequest) -> OperationResult:
            payload = request.payload
            thread_id = str(payload.get("thread_id") or "").strip()
            message = str(payload.get("message") or "").strip()
            if not thread_id or not message:
                return OperationResult(
                    name=request.name,
                    status="error",
                    payload={"error": "thread_id and message are required"},
                )
            from app.routers import session as session_router

            service = session_router._service
            if not isinstance(service, dict) or not callable(service.get("run_turn")):
                return OperationResult(
                    name=request.name,
                    status="error",
                    payload={"error": "Writer service is unavailable"},
                )
            await service["run_turn"](
                session_id=thread_id,
                user_message=message,
                goal_id=str(payload.get("goal_id") or "").strip(),
            )
            return OperationResult(name=request.name, payload={"thread_id": thread_id})

        self.catalog.register("turn.start", turn_start)

        async def execute_job(job: Any) -> OperationResult:
            payload = arranged_operation_payload(job)
            return await self.catalog.execute(
                job.operation,
                payload,
                metadata={
                    "source": "arrange",
                    "arrange_job_id": job.id,
                    "occurrence_id": job.occurrence_id,
                    **({"arrange_signal": job.signal} if job.signal else {}),
                },
            )

        async def create_execution_thread(source_thread_id: str, instruction: str) -> str:
            async with async_session() as db:
                source = await db.get(WriterSession, source_thread_id)
            if source is None or not source.project_id:
                return source_thread_id
            persistence = writer_persistence_host(async_session)
            session = await persistence.write(
                lambda db: create_writer_project_session(
                    db,
                    source.project_id,
                    title=f"安排 · {instruction[:24]}",
                    mode="EXECUTE",
                )
            )
            return str(session["id"])

        def _instruction_from_job(job: Any) -> str:
            return str((job.payload or {}).get("message") or job.title or "Arrange")

        async def new_thread_for_job(job: Any) -> str:
            return await create_execution_thread(
                job.source_thread_id or job.thread_id,
                _instruction_from_job(job),
            )

        self.runner = ArrangeRunner(
            self.db.arrange_store,
            execute_job,
            new_thread_factory=new_thread_for_job,
        )
        self.observer_supervisor = ObserverSupervisor(
            self.db.arrange_store,
            data_dir=Path(settings.data_dir),
            wake_runner=self.runner.wake,
        )
        register_durable_operations(
            self.catalog,
            goal_manager=self.goal_manager,
            arrange_manager=self.arrange_manager,
            wake_runner=self.runner.wake,
            cancel_running=self.runner.cancel,
            wake_observers=self.observer_supervisor.wake,
            observer_status=self.observer_supervisor.status,
        )
        await self.runner.start()
        await self.observer_supervisor.start()

    async def stop(self) -> None:
        if self.observer_supervisor is not None:
            await self.observer_supervisor.stop()
        if self.runner is not None:
            await self.runner.stop()
        if self.db is not None:
            await self.db.close()
        self.db = None
        self.runner = None
        self.observer_supervisor = None
        self.goal_manager = None
        self.arrange_manager = None
        self.catalog = OperationCatalog()

    async def execute(self, name: str, payload: dict[str, Any], metadata: dict[str, Any] | None = None) -> Any:
        if self.db is None:
            raise RuntimeError("Durable runtime is not started")
        return await self.catalog.execute(name, payload, metadata=metadata)

    async def execute_for_agent(
        self,
        name: str,
        payload: dict[str, Any],
        metadata: dict[str, Any],
    ) -> Any:
        return await self.execute(name, payload, metadata)


_runtime = WriterDurableRuntime()


def writer_durable_runtime() -> WriterDurableRuntime:
    return _runtime


__all__ = ["WriterDurableRuntime", "writer_durable_runtime"]
