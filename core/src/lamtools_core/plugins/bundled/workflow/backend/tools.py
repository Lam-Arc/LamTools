"""Model-facing tools backed by exposed workflows.

Mirrors :mod:`lamtools_core.tool.durable_tools`: each exposed workflow becomes
a ``ToolSpec`` (input schema derived from its typed ``input_params``) plus an
async handler that dispatches to the ``workflow.run`` operation via the shared
``operation_executor`` — the handler holds no runner reference, exactly like
the ``arrange``/``goal`` tools.

Because workflows are enrolled at runtime, the toolbox cannot merge them once
at construction. Instead :func:`workflow_tool_provider` returns a cached,
synchronously-callable provider that re-scans the :class:`WorkflowStore` (by
mtime signature, like ``SkillRegistry``) so newly-exposed workflows appear on
the agent's next turn automatically. ``CoreToolbox`` consults the provider in
``tool_specs``/``execute``.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lamtools_core.plugins.bundled.workflow.backend.runtime import WorkflowDef
from lamtools_core.tool import ToolCall, ToolResult, ToolSpec
from lamtools_core.tool.permission import ASK_USER


OperationExecutor = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[Any]]


async def workflow_manifest_tool_handler(call: ToolCall) -> ToolResult:
    """Safe manifest fallback when the plugin backend is not initialized.

    The normal plugin lifecycle supplies the context-bound handlers through
    the generic runtime contribution map. Keeping a real ``module:function``
    target in ``tools.jsonc`` means the manifest remains valid even for hosts
    that only load declarative plugin tools; such hosts receive a clear,
    bounded failure instead of an import error.
    """
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="failed",
        error="Workflow plugin runtime is not available",
    )


@dataclass
class WorkflowToolBundle:
    """A snapshot of currently-enrolled workflow tools."""

    specs: list[ToolSpec] = field(default_factory=list)
    handlers: dict[str, Callable[[ToolCall], Awaitable[ToolResult]]] = field(default_factory=dict)
    # tool_name -> workflow name
    names: dict[str, str] = field(default_factory=dict)


def workflow_tool_specs(enrolled: list[WorkflowDef]) -> list[ToolSpec]:
    specs: list[ToolSpec] = []
    for wf in enrolled:
        tool_name = wf.effective_tool_name()
        properties: dict[str, Any] = {}
        required: list[str] = []
        # Workflow inputs come from each node's orphaned input ports
        # (in-ports no edge feeds), named "{nodeId}.{portName}".
        input_ports = _workflow_input_ports(wf)
        for name, ptype, desc, is_required, default in input_ports:
            entry: dict[str, Any] = {}
            if desc:
                entry["description"] = desc
            # ``any`` is a runtime compatibility type, not a JSON Schema
            # type.  Use a concrete, provider-compatible fallback at the
            # model boundary instead of emitting an untyped property.
            entry["type"] = _json_type(ptype)
            if default is not None:
                entry["default"] = deepcopy(default)
            properties[name] = entry
            if is_required and default is None:
                required.append(name)
        schema: dict[str, Any] = {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required,
        }
        specs.append(
            ToolSpec(
                name=tool_name,
                description=(
                    wf.description.strip()
                    or f"Run the '{wf.name}' workflow ({len(wf.nodes)} nodes) and return its output."
                ),
                input_schema=schema,
                # A workflow can execute command/script/AI nodes.  Exposing it
                # as a model tool must therefore use the normal approval gate.
                permission=ASK_USER,
                metadata={
                    "category": "workflow",
                    "workflow_name": wf.name,
                    "plugin": "workflow",
                    "plugin_dynamic": True,
                    "plugin_mode": "workflow:workflow",
                },
            )
        )
    return specs


def _workflow_input_ports(wf: WorkflowDef) -> list[tuple[str, str, str, bool, Any]]:
    """Return ``(name, type, description, required, default)`` inputs.

    An input is any node input port that no edge feeds (an orphaned in-port),
    named ``{nodeId}.{portName}``. The legacy ``input_params`` array is merged
    in for backward compatibility.
    """
    fed: set[tuple[str, str]] = {(e.target, e.target_port) for e in wf.edges}
    params = {param.name: param for param in wf.input_params if param.name}
    seen: set[str] = set()
    result: list[tuple[str, str, str, bool, Any]] = []
    for node in wf.nodes:
        for port in node.input_ports():
            if (node.id, port.name) in fed:
                continue
            name = f"{node.id}.{port.name}"
            if name not in seen:
                seen.add(name)
                param = params.get(name)
                result.append(
                    (
                        name,
                        port.type,
                        port.description or (param.description if param else ""),
                        bool(param.required) if param is not None else True,
                        param.default if param is not None else None,
                    )
                )
    for param in wf.input_params:
        if param.name and param.name not in seen:
            seen.add(param.name)
            result.append(
                (
                    param.name,
                    param.type,
                    param.description,
                    bool(param.required),
                    param.default,
                )
            )
    return result


def workflow_tool_handlers(
    enrolled: list[WorkflowDef],
    execute_operation: OperationExecutor,
    *,
    work_root: str | Path | None = None,
) -> dict[str, Callable[[ToolCall], Awaitable[ToolResult]]]:
    handlers: dict[str, Callable[[ToolCall], Awaitable[ToolResult]]] = {}
    for wf in enrolled:
        tool_name = wf.effective_tool_name()
        workflow_name = wf.name
        handlers[tool_name] = _make_workflow_handler(workflow_name, execute_operation, work_root)
    return handlers


def _make_workflow_handler(
    workflow_name: str,
    execute_operation: OperationExecutor,
    work_root: str | Path | None,
) -> Callable[[ToolCall], Awaitable[ToolResult]]:
    async def handler(call: ToolCall) -> ToolResult:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        # All call arguments become workflow inputs.
        inputs = {k: v for k, v in args.items()}
        payload: dict[str, Any] = {"name": workflow_name, "inputs": inputs}
        metadata = call.metadata if isinstance(call.metadata, dict) else {}
        active_root_raw = metadata.get("work_root") or metadata.get("workRoot")
        if not active_root_raw:
            session_metadata = metadata.get("_runtime_session_metadata")
            if isinstance(session_metadata, dict):
                active_root_raw = session_metadata.get("work_root") or session_metadata.get("workRoot")
        active_root = str(active_root_raw or work_root or "").strip()
        if active_root:
            payload["work_root"] = active_root
        # Preserve the parent execution envelope so workflow-as-tool calls
        # retain attachments, snapshots, capabilities, cancellation lineage,
        # and permission authority at the operation boundary.  Unknown tool
        # metadata is intentionally not copied into the execution context.
        inherited_keys = {
            "session_id", "thread_id", "turn_id", "parent_session_id",
            "parent_run_id", "parent_turn_id", "parent_call_id", "trace_id",
            "correlation_id", "actor_id", "actor_kind", "attachments",
            "runtime_snapshot", "snapshot", "environment", "capabilities", "permissions",
            "runtime_permissions", "lineage", "parent_lineage", "workflow_stack",
            "active_workflows", "depth", "nesting_depth", "max_depth",
            "max_nesting_depth", "execution_context", "_runtime_session_metadata",
        }
        forwarded = {key: metadata[key] for key in inherited_keys if key in metadata}
        metadata = {
            **forwarded,
            "source": "agent_tool",
            "run_id": str(metadata.get("_runtime_run_id") or metadata.get("run_id") or ""),
            "tool_call_id": call.id,
            **({"work_root": active_root} if active_root else {}),
        }
        result = await execute_operation("workflow.run", payload, metadata)
        return _from_operation(call, result)

    return handler


def workflow_tool_provider(
    store: Any,
    execute_operation: OperationExecutor,
    *,
    work_root: str | Path | None = None,
) -> Callable[[], WorkflowToolBundle]:
    """Return a cached, sync callable producing the current workflow tools.

    Re-scans the store's exposed workflows only when the on-disk signature
    changes, so per-turn ``CoreToolbox.tool_specs`` calls are cheap.
    """
    cache: dict[str, Any] = {"signature": None, "bundle": None}

    def get() -> WorkflowToolBundle:
        try:
            signature = store._signature(work_root)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 — provider must never break the toolbox
            signature = None
        if cache["signature"] == signature and cache["bundle"] is not None:
            return cache["bundle"]
        try:
            enrolled = store.list_exposed_sync(work_root=work_root)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            enrolled = []
        specs = workflow_tool_specs(enrolled)
        handlers = workflow_tool_handlers(enrolled, execute_operation, work_root=work_root)
        names = {wf.effective_tool_name(): wf.name for wf in enrolled}
        bundle = WorkflowToolBundle(specs=specs, handlers=handlers, names=names)
        cache["signature"] = signature
        cache["bundle"] = bundle
        return bundle

    return get


def _json_type(type_name: str) -> str:
    mapping = {
        "text": "string",
        "string": "string",
        "number": "number",
        "integer": "integer",
        "int": "integer",
        "boolean": "boolean",
        "bool": "boolean",
        "array": "array",
        "json": "object",
        "object": "object",
    }
    # ``any`` (and legacy/unknown type names) has no direct JSON Schema type.
    # A string is the safest provider-compatible fallback; the workflow
    # runtime still accepts richer values when called internally.
    return mapping.get(str(type_name or "").strip().lower(), "string")


def _from_operation(call: ToolCall, result: Any) -> ToolResult:
    status = str(getattr(result, "status", "error") or "error")
    payload = deepcopy(getattr(result, "payload", {}) or {})
    if status != "ok":
        return _failed(call, str(payload.get("error") or "workflow run failed"), payload=payload)
    run = payload.get("run") or {}
    output = run.get("output") if isinstance(run, dict) else None
    content = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str)
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="ok",
        content=content,
        metadata={"workflow_run": run, "operation_payload": payload},
    )


def _failed(call: ToolCall, error: str, *, payload: dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="failed",
        error=error,
        content=error,
        metadata={"operation_payload": payload or {}},
    )


__all__ = [
    "OperationExecutor",
    "WorkflowToolBundle",
    "workflow_manifest_tool_handler",
    "workflow_tool_handlers",
    "workflow_tool_provider",
    "workflow_tool_specs",
]
