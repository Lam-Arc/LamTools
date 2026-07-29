"""Workflow operations shared by HTTP, GUI, and CLI.

Mirrors :mod:`lamtools_core.app.durable_operations`: a single
``register_workflow_operations`` function that installs handlers for every name
in :data:`CORE_WORKFLOW_OPERATION_NAMES` onto an :class:`OperationCatalog`.

``workflow.run`` executes the graph inline (the runner streams per-node state
through the injected ``emit`` callback *during* the run, so a subscribed GUI
receives ``core/runItem`` events before the request returns). Cooperative
cancellation is wired through ``RuntimeTaskRegistry.get_cancel_event`` so a
concurrent ``workflow.cancel`` aborts at the next node boundary.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from lamtools_core.runtime.workflow import WorkflowDef, WorkflowManager, WorkflowRunner

from .operation_catalog import OperationCatalog, OperationRequest, OperationResult
from .operation_groups import CORE_WORKFLOW_OPERATION_NAMES


def register_workflow_operations(
    catalog: OperationCatalog,
    *,
    workflow_manager: WorkflowManager,
    runner: WorkflowRunner,
    runtime_task_registry: Any = None,
    list_tool_specs: Callable[[], list[Any]] | None = None,
) -> None:
    """Register all workflow.* operations onto ``catalog``."""

    async def workflow_create(request: OperationRequest) -> OperationResult:
        payload = request.payload
        try:
            definition = WorkflowDef.from_dict(dict(payload))
            if not definition.name:
                return _error(request, "name is required")
            definition = await workflow_manager.create(definition)
        except (TypeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"workflow": definition.to_dict()})

    async def workflow_get(request: OperationRequest) -> OperationResult:
        name = _name(request.payload)
        if not name:
            return _error(request, "name is required")
        work_root = _optional_text(request.payload, "work_root", "workRoot")
        definition = await workflow_manager.get(name, work_root=work_root)
        if definition is None:
            return _error(request, f"Workflow not found: {name}")
        return OperationResult(name=request.name, payload={"workflow": definition.to_dict()})

    async def workflow_list(request: OperationRequest) -> OperationResult:
        work_root = _optional_text(request.payload, "work_root", "workRoot")
        defs = await workflow_manager.list(work_root=work_root)
        return OperationResult(
            name=request.name,
            payload={"workflows": [d.to_dict() for d in defs]},
        )

    async def workflow_update(request: OperationRequest) -> OperationResult:
        payload = request.payload
        name = _name(payload)
        if not name:
            return _error(request, "name is required")
        work_root = _optional_text(payload, "work_root", "workRoot")
        try:
            definition = await workflow_manager.update_fields(
                name,
                work_root=work_root,
                description=(str(payload.get("description") or "") if "description" in payload else None),
                nodes=list(payload.get("nodes") or []) if "nodes" in payload else None,
                edges=list(payload.get("edges") or []) if "edges" in payload else None,
                input_params=list(payload.get("input_params") or payload.get("inputParams") or []) if "input_params" in payload or "inputParams" in payload else None,
                output_port=(str(payload.get("output_port") or payload.get("outputPort") or "") if "output_port" in payload or "outputPort" in payload else None),
                exposed=bool(payload.get("exposed")) if "exposed" in payload else None,
                tool_name=(str(payload.get("tool_name") or payload.get("toolName") or "") if "tool_name" in payload or "toolName" in payload else None),
            )
        except (LookupError, TypeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"workflow": definition.to_dict()})

    async def workflow_delete(request: OperationRequest) -> OperationResult:
        name = _name(request.payload)
        if not name:
            return _error(request, "name is required")
        work_root = _optional_text(request.payload, "work_root", "workRoot")
        removed = await workflow_manager.delete(name, work_root=work_root)
        return OperationResult(name=request.name, payload={"deleted": removed, "name": name})

    async def workflow_expose(request: OperationRequest, exposed: bool) -> OperationResult:
        name = _name(request.payload)
        if not name:
            return _error(request, "name is required")
        work_root = _optional_text(request.payload, "work_root", "workRoot")
        try:
            definition = await workflow_manager.set_exposed(name, exposed, work_root=work_root)
        except LookupError as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"workflow": definition.to_dict()})

    async def workflow_run(request: OperationRequest) -> OperationResult:
        payload = request.payload
        name = _name(payload)
        if not name:
            return _error(request, "name is required")
        work_root = _optional_text(payload, "work_root", "workRoot")
        definition = await workflow_manager.get(name, work_root=work_root)
        if definition is None:
            return _error(request, f"Workflow not found: {name}")
        if not work_root:
            work_root = definition.work_root
        thread_id = str(payload.get("thread_id") or payload.get("threadId") or f"workflow_thread_{uuid.uuid4().hex}")
        run_id = str(payload.get("run_id") or payload.get("runId") or f"workflow_run_{uuid.uuid4().hex[:12]}")
        inputs = dict(payload.get("inputs") or {})
        max_steps = payload.get("max_steps", payload.get("maxSteps"))
        if max_steps in ("", None):
            max_steps = None
        else:
            try:
                max_steps = int(max_steps)
            except (TypeError, ValueError):
                max_steps = None
        start_node = str(payload.get("start_node") or payload.get("startNode") or "") or None
        single_node = str(payload.get("single_node") or payload.get("singleNode") or "") or None
        prior_values = dict(payload.get("prior_values") or payload.get("priorValues") or {})
        prior_states_raw = payload.get("prior_node_states") or payload.get("priorNodeStates") or {}
        prior_states: dict[str, Any] = {}
        if isinstance(prior_states_raw, dict):
            from lamtools_core.runtime.workflow import WorkflowNodeState

            for nid, raw in prior_states_raw.items():
                prior_states[nid] = (
                    raw if isinstance(raw, WorkflowNodeState)
                    else WorkflowNodeState(node_id=nid, status=str((raw or {}).get("status") or "idle"), output=(raw or {}).get("output"), error=str((raw or {}).get("error") or ""))
                )

        # Accept a runtime_task_registry to enable cooperative cancellation.
        registry = runtime_task_registry
        if registry is not None:
            try:
                registry.accept_run(thread_id, run_id)
            except Exception:  # noqa: BLE001 — cancellation is best-effort
                pass

        try:
            result = await runner.run(
                definition,
                inputs=inputs,
                work_root=work_root or "",
                thread_id=thread_id,
                run_id=run_id,
                prior_values=prior_values,
                prior_node_states=prior_states or None,
                max_steps=max_steps,
                start_node=start_node,
                single_node=single_node,
            )
        except Exception as exc:  # noqa: BLE001 — surface as operation error
            return _error(request, exc)
        return OperationResult(
            name=request.name,
            payload={"run": result.to_dict(), "thread_id": thread_id, "run_id": run_id},
        )

    async def workflow_cancel(request: OperationRequest) -> OperationResult:
        thread_id = str(request.payload.get("thread_id") or request.payload.get("threadId") or "")
        run_id = str(request.payload.get("run_id") or request.payload.get("runId") or "")
        if not thread_id:
            return _error(request, "thread_id is required")
        if runtime_task_registry is None:
            return _error(request, "cancellation not available in this host")
        try:
            runtime_task_registry.cancel(thread_id, run_id=run_id or None, force=True)
        except Exception as exc:  # noqa: BLE001
            return _error(request, exc)
        return OperationResult(
            name=request.name,
            payload={"cancelled": True, "thread_id": thread_id, "run_id": run_id},
        )

    async def workflow_tools_list(request: OperationRequest) -> OperationResult:
        specs: list[Any] = []
        if list_tool_specs is not None:
            try:
                raw = list_tool_specs()
                if raw:
                    specs = [
                        {"name": getattr(s, "name", ""), "description": getattr(s, "description", "")}
                        for s in raw
                    ]
            except Exception:  # noqa: BLE001 — listing must not fail the op
                specs = []
        return OperationResult(name=request.name, payload={"tools": specs})

    handlers = {
        "workflow.create": workflow_create,
        "workflow.get": workflow_get,
        "workflow.list": workflow_list,
        "workflow.update": workflow_update,
        "workflow.delete": workflow_delete,
        "workflow.run": workflow_run,
        "workflow.cancel": workflow_cancel,
        "workflow.expose": lambda req: workflow_expose(req, True),
        "workflow.unexpose": lambda req: workflow_expose(req, False),
        "workflow.tools.list": workflow_tools_list,
    }
    for name in CORE_WORKFLOW_OPERATION_NAMES:
        catalog.register(name, handlers[name])


def _name(payload: dict[str, Any]) -> str:
    return str(payload.get("name") or "").strip()


def _optional_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key in payload:
            value = str(payload.get(key) or "").strip()
            return value or None
    return None


def _error(request: OperationRequest, error: object) -> OperationResult:
    return OperationResult(name=request.name, status="error", payload={"error": str(error)})


__all__ = ["register_workflow_operations"]
