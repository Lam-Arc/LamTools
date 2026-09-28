"""Plan-package operations shared by the desktop UI, the CLI and the phone.

A plan package is the durable document the phone authors and either host can
open, revise or execute. These handlers are thin on purpose: every rule lives in
`runtime/plan_package.py`, which is also what the mobile host ports, so the two
implementations answer the same payloads with the same wording.
"""

from __future__ import annotations

from typing import Any

from lamtools_core.app.project_store import normalize_workspace_root
from lamtools_core.runtime.plan_package import (
    PLAN_STATUSES,
    PlanManager,
    revision_summaries,
)

from .operation_catalog import OperationCatalog, OperationRequest, OperationResult
from .operation_groups import CORE_PLAN_OPERATION_NAMES


def register_plan_operations(
    catalog: OperationCatalog,
    *,
    plan_manager: PlanManager,
    project_store: Any = None,
) -> None:
    async def plan_save(request: OperationRequest) -> OperationResult:
        payload = dict(request.payload or {})
        try:
            await _resolve_project(payload, project_store)
            plan = await plan_manager.save(
                payload,
                source="desktop",
                expected_revision=_optional_revision(payload),
            )
        except (LookupError, RuntimeError, TypeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"plan": plan.to_dict()})

    async def plan_get(request: OperationRequest) -> OperationResult:
        plan = await plan_manager.get(_plan_id(request.payload))
        if plan is None:
            return _error(request, f"Plan not found: {_plan_id(request.payload)}")
        return OperationResult(name=request.name, payload={"plan": plan.to_dict()})

    async def plan_list(request: OperationRequest) -> OperationResult:
        payload = request.payload
        status = str(payload.get("status") or "").strip()
        if status and status not in PLAN_STATUSES:
            return _error(request, f"invalid plan status: {status}")
        try:
            plans = await plan_manager.list(
                project_id=str(payload.get("project_id") or payload.get("projectId") or "").strip() or None,
                status=status or None,  # type: ignore[arg-type]
                include_deleted=_truthy(payload.get("include_deleted") or payload.get("includeDeleted")),
            )
        except (TypeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(
            name=request.name,
            payload={"plans": [plan.to_dict() for plan in plans]},
        )

    async def plan_delete(request: OperationRequest) -> OperationResult:
        try:
            plan = await plan_manager.delete(_plan_id(request.payload))
        except (LookupError, TypeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"plan": plan.to_dict()})

    async def plan_restore(request: OperationRequest) -> OperationResult:
        try:
            plan = await plan_manager.restore(_plan_id(request.payload))
        except (LookupError, TypeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"plan": plan.to_dict()})

    async def plan_revert(request: OperationRequest) -> OperationResult:
        payload = request.payload
        try:
            revision = int(payload.get("revision") or payload.get("to_revision") or 0)
        except (TypeError, ValueError):
            return _error(request, "plan revision must be a number")
        if revision <= 0:
            return _error(request, "plan revision must be a number")
        try:
            plan = await plan_manager.revert(_plan_id(payload), revision, source="desktop")
        except (LookupError, RuntimeError, TypeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"plan": plan.to_dict()})

    async def plan_revisions(request: OperationRequest) -> OperationResult:
        try:
            history = await plan_manager.revisions(_plan_id(request.payload))
        except (LookupError, TypeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"revisions": revision_summaries(history)})

    handlers = {
        "plan.save": plan_save,
        "plan.get": plan_get,
        "plan.list": plan_list,
        "plan.delete": plan_delete,
        "plan.restore": plan_restore,
        "plan.revert": plan_revert,
        "plan.revisions": plan_revisions,
    }
    for name in CORE_PLAN_OPERATION_NAMES:
        catalog.register(name, handlers[name])


def _plan_id(payload: dict[str, Any]) -> str:
    return str(payload.get("plan_id") or payload.get("planId") or payload.get("id") or "").strip()


async def _resolve_project(payload: dict[str, Any], project_store: Any) -> None:
    """Accept a plan pointed at a workspace instead of at a project id.

    The store keys plans by the host's project id, which a model tool rarely
    knows but a running turn always does (its workspace). When the project is
    still missing, the refusal comes from the package rules, not from here, so
    direct callers keep the wording the shared fixtures pin.
    """

    project_id = str(payload.get("project_id") or payload.get("projectId") or "").strip()
    if project_id:
        payload["project_id"] = project_id
        return
    work_root = str(payload.get("work_root") or payload.get("workRoot") or "").strip()
    if not work_root or project_store is None:
        return
    target = normalize_workspace_root(work_root)
    for project in await project_store.list():
        if normalize_workspace_root(project.work_root) == target:
            payload["project_id"] = project.id
            return


def _optional_revision(payload: dict[str, Any]) -> int | None:
    """`expected_revision` is the optimistic-concurrency token; absent means no check."""

    for key in ("expected_revision", "expectedRevision"):
        if key in payload and payload[key] not in (None, ""):
            try:
                return int(payload[key])
            except (TypeError, ValueError) as exc:
                raise ValueError("plan expected_revision must be a number") from exc
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _error(request: OperationRequest, error: object) -> OperationResult:
    return OperationResult(name=request.name, status="error", payload={"error": str(error)})


__all__ = ["register_plan_operations"]
