"""Product-neutral Goal and Arrange operations shared by HTTP, GUI, and CLI."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
import uuid

from lamtools_core.runtime.arrange import ArrangeManager
from lamtools_core.runtime.goal import GoalManager
from lamtools_core.runtime.observer import prepare_observer

from .operation_catalog import OperationCatalog, OperationRequest, OperationResult
from .operation_groups import CORE_DURABLE_OPERATION_NAMES


def register_durable_operations(
    catalog: OperationCatalog,
    *,
    goal_manager: GoalManager,
    arrange_manager: ArrangeManager,
    wake_runner: Callable[[], Any] | None = None,
    cancel_running: Callable[[str], Any] | None = None,
    create_execution_thread: Callable[[str, str], Any] | None = None,
    wake_observers: Callable[[], Any] | None = None,
    observer_status: Callable[[str], dict[str, Any]] | None = None,
) -> None:
    def wake() -> None:
        if wake_runner is not None:
            wake_runner()

    def reconcile_observers() -> None:
        if wake_observers is not None:
            wake_observers()

    def job_payload(job: Any) -> dict[str, Any]:
        result = job.to_dict()
        if job.observer and observer_status is not None:
            result["observer_runtime"] = observer_status(job.id)
        return result

    async def goal_create(request: OperationRequest) -> OperationResult:
        payload = request.payload
        try:
            goal = await goal_manager.create(
                thread_id=_thread_id(payload),
                objective=str(payload.get("objective") or ""),
                completion_criteria=payload.get("completion_criteria") or payload.get("completionCriteria") or (),
                metadata=dict(payload.get("metadata") or {}),
                goal_id=str(payload.get("goal_id") or payload.get("goalId") or payload.get("id") or ""),
            )
        except (TypeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"goal": goal.to_dict()})

    async def goal_get(request: OperationRequest) -> OperationResult:
        goal = await goal_manager.get(_goal_id(request.payload))
        if goal is None:
            return _error(request, "Goal not found")
        return OperationResult(name=request.name, payload={"goal": goal.to_dict()})

    async def goal_list(request: OperationRequest) -> OperationResult:
        payload = request.payload
        try:
            goals = await goal_manager.list(
                thread_id=_optional_text(payload, "thread_id", "threadId"),
                status=_optional_text(payload, "status"),  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(
            name=request.name,
            payload={"goals": [goal.to_dict() for goal in goals]},
        )

    async def goal_update(request: OperationRequest) -> OperationResult:
        payload = request.payload
        try:
            goal = await goal_manager.update(
                _goal_id(payload),
                objective=(str(payload.get("objective") or "") if "objective" in payload else None),
                completion_criteria=(
                    payload.get("completion_criteria", payload.get("completionCriteria"))
                    if "completion_criteria" in payload or "completionCriteria" in payload
                    else None
                ),
                status=_optional_text(payload, "status"),  # type: ignore[arg-type]
                status_reason=(
                    str(payload.get("status_reason") or payload.get("statusReason") or "")
                    if "status_reason" in payload or "statusReason" in payload
                    else None
                ),
                metadata=dict(payload.get("metadata") or {}) if "metadata" in payload else None,
            )
        except (LookupError, TypeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"goal": goal.to_dict()})

    async def arrange_create(request: OperationRequest) -> OperationResult:
        payload = request.payload
        operation = str(payload.get("operation") or "").strip()
        source_thread_id = _thread_id(payload)
        thread_id = source_thread_id
        goal_id = str(payload.get("goal_id") or payload.get("goalId") or "").strip()
        if operation.startswith("arrange."):
            return _error(request, "Arrange control operations cannot schedule themselves")
        if not catalog.has(operation):
            return _error(request, f"Operation is not registered: {operation or '-'}")
        if goal_id:
            goal = await goal_manager.get(goal_id)
            if goal is None:
                return _error(request, f"Goal not found: {goal_id}")
            if goal.thread_id != source_thread_id:
                return _error(request, "Goal belongs to a different thread")
            if goal.status in {"completed", "failed", "cancelled"}:
                return _error(request, f"Goal is terminal: {goal_id}")
        try:
            raw_observer = dict(payload.get("observer") or {})
            observer = (
                prepare_observer(
                    raw_observer,
                    work_root=str(payload.get("work_root") or payload.get("workRoot") or ""),
                )
                if raw_observer
                else {}
            )
            if (
                not goal_id
                and str(request.metadata.get("source") or "") == "agent_tool"
            ):
                instruction = str(dict(payload.get("payload") or {}).get("message") or "Arrange")
                if create_execution_thread is None:
                    thread_id = f"arrange_thread_{uuid.uuid4().hex}"
                else:
                    created = create_execution_thread(source_thread_id, instruction)
                    if inspect.isawaitable(created):
                        created = await created
                    thread_id = str(created or "").strip()
                    if not thread_id:
                        raise ValueError("Arrange execution thread was not created")
            job = await arrange_manager.create(
                thread_id=thread_id,
                source_thread_id=source_thread_id,
                kind=str(payload.get("kind") or ""),  # type: ignore[arg-type]
                operation=operation,
                payload=dict(payload.get("payload") or {}),
                trigger=dict(payload.get("trigger") or {}),
                observer=observer,
                goal_id=goal_id,
                max_runs=_optional_positive_int(payload.get("max_runs", payload.get("maxRuns"))),
                job_id=str(payload.get("job_id") or payload.get("jobId") or payload.get("id") or ""),
            )
        except (TypeError, ValueError) as exc:
            return _error(request, exc)
        wake()
        reconcile_observers()
        return OperationResult(name=request.name, payload={"job": job_payload(job)})

    async def arrange_get(request: OperationRequest) -> OperationResult:
        job = await arrange_manager.get(_job_id(request.payload))
        if job is None:
            return _error(request, "Arrange job not found")
        return OperationResult(name=request.name, payload={"job": job_payload(job)})

    async def arrange_list(request: OperationRequest) -> OperationResult:
        payload = request.payload
        try:
            jobs = await arrange_manager.list(
                thread_id=_optional_text(payload, "thread_id", "threadId"),
                status=_optional_text(payload, "status"),  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(
            name=request.name,
            payload={"jobs": [job_payload(job) for job in jobs]},
        )

    async def arrange_status(request: OperationRequest, status: str) -> OperationResult:
        try:
            job_id = _job_id(request.payload)
            current = await arrange_manager.get(job_id)
            if current is None:
                raise LookupError(f"Arrange job not found: {job_id}")
            if current.status == "running" and status in {"paused", "cancelled"}:
                if cancel_running is None:
                    raise RuntimeError("Running Arrange job cannot be stopped by this host")
                stopped = cancel_running(job_id)
                if inspect.isawaitable(stopped):
                    stopped = await stopped
                if not stopped:
                    raise RuntimeError(f"Arrange job execution already finished: {job_id}")
            job = await arrange_manager.update_status(
                job_id, status  # type: ignore[arg-type]
            )
        except (LookupError, RuntimeError, ValueError) as exc:
            return _error(request, exc)
        if status == "scheduled":
            wake()
        reconcile_observers()
        return OperationResult(name=request.name, payload={"job": job_payload(job)})

    async def arrange_pause(request: OperationRequest) -> OperationResult:
        return await arrange_status(request, "paused")

    async def arrange_resume(request: OperationRequest) -> OperationResult:
        return await arrange_status(request, "scheduled")

    async def arrange_cancel(request: OperationRequest) -> OperationResult:
        return await arrange_status(request, "cancelled")

    async def arrange_signal(request: OperationRequest) -> OperationResult:
        try:
            payload = dict(request.payload)
            event_type = str(
                payload.get("event_type") or payload.get("eventType") or payload.get("key") or ""
            ).strip()
            now = datetime.now(timezone.utc)
            payload.setdefault("event_id", f"evt_{uuid.uuid4().hex}")
            payload.setdefault("event_type", event_type)
            payload.setdefault("occurred_at", now.isoformat())
            emission = await arrange_manager.emit_signal(payload, now=now)
        except ValueError as exc:
            return _error(request, exc)
        if emission.occurrences:
            wake()
        return OperationResult(
            name=request.name,
            payload={
                "signal": emission.signal,
                "created": emission.created,
                "signalled": len(emission.occurrences),
                "occurrences": [item.to_dict() for item in emission.occurrences],
            },
        )

    async def arrange_occurrence_get(request: OperationRequest) -> OperationResult:
        occurrence = await arrange_manager.get_occurrence(
            str(request.payload.get("occurrence_id") or request.payload.get("occurrenceId") or "")
        )
        if occurrence is None:
            return _error(request, "Arrange occurrence not found")
        return OperationResult(name=request.name, payload={"occurrence": occurrence.to_dict()})

    async def arrange_occurrence_list(request: OperationRequest) -> OperationResult:
        occurrences = await arrange_manager.list_occurrences(
            job_id=_optional_text(request.payload, "job_id", "jobId")
        )
        return OperationResult(
            name=request.name,
            payload={"occurrences": [item.to_dict() for item in occurrences]},
        )

    handlers = {
        "goal.create": goal_create,
        "goal.get": goal_get,
        "goal.list": goal_list,
        "goal.update": goal_update,
        "arrange.create": arrange_create,
        "arrange.get": arrange_get,
        "arrange.list": arrange_list,
        "arrange.pause": arrange_pause,
        "arrange.resume": arrange_resume,
        "arrange.cancel": arrange_cancel,
        "arrange.signal": arrange_signal,
        "arrange.occurrence.get": arrange_occurrence_get,
        "arrange.occurrence.list": arrange_occurrence_list,
    }
    for name in CORE_DURABLE_OPERATION_NAMES:
        catalog.register(name, handlers[name])


def _thread_id(payload: dict[str, Any]) -> str:
    return str(payload.get("thread_id") or payload.get("threadId") or payload.get("session_id") or "").strip()


def _goal_id(payload: dict[str, Any]) -> str:
    return str(payload.get("goal_id") or payload.get("goalId") or payload.get("id") or "").strip()


def _job_id(payload: dict[str, Any]) -> str:
    return str(payload.get("job_id") or payload.get("jobId") or payload.get("id") or "").strip()


def _optional_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key in payload:
            value = str(payload.get(key) or "").strip()
            return value or None
    return None


def _optional_positive_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("max_runs must be positive")
    return parsed


def _error(request: OperationRequest, error: object) -> OperationResult:
    return OperationResult(
        name=request.name,
        status="error",
        payload={"error": str(error)},
    )


__all__ = ["register_durable_operations"]
