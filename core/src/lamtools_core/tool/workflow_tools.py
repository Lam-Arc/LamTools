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

from lamtools_core.runtime.workflow import WorkflowDef
from lamtools_core.tool import ToolCall, ToolResult, ToolSpec
from lamtools_core.tool.permission import AUTO_ALLOW


OperationExecutor = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[Any]]


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
        # Input params come from the Input system node's output ports
        # (preferred), falling back to the legacy input_params array.
        input_ports = _workflow_input_ports(wf)
        for name, ptype, desc in input_ports:
            entry: dict[str, Any] = {}
            if desc:
                entry["description"] = desc
            json_type = _json_type(ptype)
            if json_type:
                entry["type"] = json_type
            properties[name] = entry
            required.append(name)
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        specs.append(
            ToolSpec(
                name=tool_name,
                description=(
                    wf.description.strip()
                    or f"Run the '{wf.name}' workflow ({len(wf.nodes)} nodes) and return its output."
                ),
                input_schema=schema,
                permission=AUTO_ALLOW,
                metadata={"category": "workflow", "workflow_name": wf.name},
            )
        )
    return specs


def _workflow_input_ports(wf: WorkflowDef) -> list[tuple[str, str, str]]:
    """Return (name, type, description) for workflow inputs, sourced from Input
    nodes' output ports (plus legacy input_params)."""
    seen: set[str] = set()
    result: list[tuple[str, str, str]] = []
    for node in wf.nodes:
        if node.kind == "input":
            for port in node.output_ports():
                if port.name and port.name not in seen:
                    seen.add(port.name)
                    result.append((port.name, port.type, port.description))
    for param in wf.input_params:
        if param.name and param.name not in seen:
            seen.add(param.name)
            result.append((param.name, param.type, param.description))
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
        if work_root:
            payload["work_root"] = str(work_root)
        metadata = {
            "source": "agent_tool",
            "run_id": str(call.metadata.get("_runtime_run_id") or ""),
            "tool_call_id": call.id,
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


def _json_type(type_name: str) -> str | None:
    mapping = {
        "text": "string",
        "string": "string",
        "number": "number",
        "integer": "integer",
        "int": "integer",
        "boolean": "boolean",
        "bool": "boolean",
        "json": "object",
        "object": "object",
    }
    return mapping.get(str(type_name or "").strip().lower())  # "any" -> None


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
    "workflow_tool_handlers",
    "workflow_tool_provider",
    "workflow_tool_specs",
]
