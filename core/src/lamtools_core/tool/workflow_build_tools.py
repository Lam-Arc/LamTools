"""Model-facing workflow-graph editing tools (fine-grained node operations).

Backed by the existing workflow.get / workflow.update operations: each
handler reads the current graph, mutates it in memory, and writes it back.
The workflow name is derived from the run's session id (``wf_<name>``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from lamtools_core.tool import ToolCall, ToolResult, ToolSpec
from lamtools_core.tool.permission import ASK_USER, AUTO_ALLOW


OperationExecutor = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[Any]]


def workflow_build_tool_specs() -> list[ToolSpec]:
    """Tool specs for fine-grained workflow-graph editing."""
    node_kind = {"type": "string", "enum": ["llm", "agent", "action"]}
    port_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "type": {"type": "string"},
            "direction": {"type": "string", "enum": ["in", "out"]},
            "description": {"type": "string"},
        },
        "required": ["name", "direction"],
    }
    return [
        ToolSpec(
            name="workflow_graph",
            description=(
                "Read the current workflow graph (nodes + edges) as JSON. Use this "
                "before editing to see the existing nodes, ids, ports, and connections."
            ),
            input_schema=_schema({}, required=[]),
            permission=AUTO_ALLOW,
            metadata={"category": "workflow"},
        ),
        ToolSpec(
            name="workflow_add_node",
            description=(
                "Add a node to the current workflow. kind is 'llm' | 'agent' | 'action'. "
                "Each node carries in/out ports; a new node usually gets one 'in' and "
                "one 'out' port. config is kind-specific (action: action_type/command; "
                "llm: instruction/mode/allowed_tools; agent: tools). position is canvas {x,y}."
            ),
            input_schema=_schema({
                "kind": node_kind,
                "title": {"type": "string"},
                "config": {"type": "object"},
                "ports": {"type": "array", "items": port_schema},
                "position": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}}},
                "node_id": {"type": "string", "description": "Optional explicit node id (auto-generated if omitted)"},
            }, required=["kind"]),
            permission=ASK_USER,
            metadata={"category": "workflow"},
        ),
        ToolSpec(
            name="workflow_connect",
            description=(
                "Connect a source node's output port to a target node's input port. "
                "source/source_port/target/target_port must reference real node ids and ports."
            ),
            input_schema=_schema({
                "source": {"type": "string"},
                "source_port": {"type": "string"},
                "target": {"type": "string"},
                "target_port": {"type": "string"},
            }, required=["source", "source_port", "target", "target_port"]),
            permission=ASK_USER,
            metadata={"category": "workflow"},
        ),
        ToolSpec(
            name="workflow_delete_node",
            description=(
                "Delete a node from the current workflow by node id. Connected edges "
                "are removed too."
            ),
            input_schema=_schema({
                "node_id": {"type": "string"},
            }, required=["node_id"]),
            permission=ASK_USER,
            metadata={"category": "workflow"},
        ),
        ToolSpec(
            name="workflow_update_node",
            description=(
                "Update fields of an existing node (title/config/ports/position) by node id. "
                "Only provided fields are replaced."
            ),
            input_schema=_schema({
                "node_id": {"type": "string"},
                "title": {"type": "string"},
                "config": {"type": "object"},
                "ports": {"type": "array", "items": port_schema},
                "position": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}}},
            }, required=["node_id"]),
            permission=ASK_USER,
            metadata={"category": "workflow"},
        ),
    ]


def workflow_build_tool_handlers(
    execute_operation: OperationExecutor,
    work_root: str | Path | None = None,
) -> dict[str, Callable[[ToolCall], Awaitable[ToolResult]]]:
    """Handlers that edit the current workflow graph via workflow.get/update."""

    async def _get_graph(name: str) -> dict[str, Any] | None:
        payload: dict[str, Any] = {"name": name}
        if work_root:
            payload["work_root"] = str(work_root)
        result = await execute_operation("workflow.get", payload, {})
        status = str(getattr(result, "status", "error") or "error")
        if status != "ok":
            return None
        wf = (getattr(result, "payload", {}) or {}).get("workflow")
        return wf if isinstance(wf, dict) else None

    async def _save_graph(name: str, wf: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "description": wf.get("description") or "",
            "nodes": wf.get("nodes") or [],
            "edges": wf.get("edges") or [],
            "input_params": wf.get("input_params") or [],
            "output_port": wf.get("output_port") or "",
            "exposed": bool(wf.get("exposed")),
            "tool_name": wf.get("tool_name") or "",
        }
        if work_root:
            payload["work_root"] = str(work_root)
        result = await execute_operation("workflow.update", payload, {})
        status = str(getattr(result, "status", "error") or "error")
        if status != "ok":
            err = str((getattr(result, "payload", {}) or {}).get("error") or "save failed")
            raise RuntimeError(err)
        saved = (getattr(result, "payload", {}) or {}).get("workflow")
        return saved if isinstance(saved, dict) else wf

    def _resolve_name(call: ToolCall) -> str:
        session = str(call.metadata.get("_runtime_session_id") or "").strip()
        # thread id is wf_<name>; strip the prefix.
        if session.startswith("wf_"):
            return session[3:]
        return session

    async def workflow_graph(call: ToolCall) -> ToolResult:
        name = _resolve_name(call)
        if not name:
            return _failed(call, "no active workflow (session id missing)")
        wf = await _get_graph(name)
        if wf is None:
            return _failed(call, f"workflow not found: {name}")
        return _ok(call, wf)

    async def workflow_add_node(call: ToolCall) -> ToolResult:
        args = _args(call)
        name = _resolve_name(call)
        wf = await _get_graph(name)
        if wf is None:
            return _failed(call, f"workflow not found: {name}")
        nodes = list(wf.get("nodes") or [])
        kind = str(args.get("kind") or "action")
        import secrets

        node_id = str(args.get("node_id") or "").strip() or f"{kind}-{secrets.token_hex(2)}"
        if any(str(n.get("id")) == node_id for n in nodes if isinstance(n, dict)):
            return _failed(call, f"node id already exists: {node_id}")
        node: dict[str, Any] = {
            "id": node_id,
            "kind": kind,
            "title": str(args.get("title") or kind.capitalize()),
            "config": args.get("config") if isinstance(args.get("config"), dict) else {},
            "ports": args.get("ports") if isinstance(args.get("ports"), list) else _default_ports(kind),
            "position": args.get("position") if isinstance(args.get("position"), dict) else {"x": 120, "y": 120},
        }
        nodes.append(node)
        wf["nodes"] = nodes
        saved = await _save_graph(name, wf)
        return _ok(call, {"added": node, "workflow": saved})

    async def workflow_connect(call: ToolCall) -> ToolResult:
        args = _args(call)
        name = _resolve_name(call)
        wf = await _get_graph(name)
        if wf is None:
            return _failed(call, f"workflow not found: {name}")
        source = str(args.get("source") or "")
        source_port = str(args.get("source_port") or "")
        target = str(args.get("target") or "")
        target_port = str(args.get("target_port") or "")
        nodes = wf.get("nodes") or []
        node_ids = {str(n.get("id")) for n in nodes if isinstance(n, dict)}
        if source not in node_ids or target not in node_ids:
            return _failed(call, "source or target node id not found")
        import secrets

        edges = list(wf.get("edges") or [])
        edge_id = f"e-{source}-{source_port}-{target}-{target_port}-{secrets.token_hex(1)}"
        edges.append({
            "id": edge_id,
            "source": source,
            "source_port": source_port,
            "target": target,
            "target_port": target_port,
        })
        wf["edges"] = edges
        saved = await _save_graph(name, wf)
        return _ok(call, {"connected": edge_id, "workflow": saved})

    async def workflow_delete_node(call: ToolCall) -> ToolResult:
        args = _args(call)
        name = _resolve_name(call)
        wf = await _get_graph(name)
        if wf is None:
            return _failed(call, f"workflow not found: {name}")
        node_id = str(args.get("node_id") or "")
        wf["nodes"] = [n for n in (wf.get("nodes") or []) if isinstance(n, dict) and str(n.get("id")) != node_id]
        wf["edges"] = [e for e in (wf.get("edges") or []) if isinstance(e, dict) and str(e.get("source")) != node_id and str(e.get("target")) != node_id]
        saved = await _save_graph(name, wf)
        return _ok(call, {"deleted": node_id, "workflow": saved})

    async def workflow_update_node(call: ToolCall) -> ToolResult:
        args = _args(call)
        name = _resolve_name(call)
        wf = await _get_graph(name)
        if wf is None:
            return _failed(call, f"workflow not found: {name}")
        node_id = str(args.get("node_id") or "")
        nodes = wf.get("nodes") or []
        found = False
        for n in nodes:
            if isinstance(n, dict) and str(n.get("id")) == node_id:
                if "title" in args:
                    n["title"] = str(args.get("title") or "")
                if isinstance(args.get("config"), dict):
                    n["config"] = args.get("config")
                if isinstance(args.get("ports"), list):
                    n["ports"] = args.get("ports")
                if isinstance(args.get("position"), dict):
                    n["position"] = args.get("position")
                found = True
                break
        if not found:
            return _failed(call, f"node not found: {node_id}")
        wf["nodes"] = nodes
        saved = await _save_graph(name, wf)
        return _ok(call, {"updated": node_id, "workflow": saved})

    return {
        "workflow_graph": workflow_graph,
        "workflow_add_node": workflow_add_node,
        "workflow_connect": workflow_connect,
        "workflow_delete_node": workflow_delete_node,
        "workflow_update_node": workflow_update_node,
    }


# ---- helpers -------------------------------------------------------------

def _default_ports(kind: str) -> list[dict[str, Any]]:
    """Sensible default ports per node kind for newly created nodes."""
    if kind == "content":
        return [{"name": "out", "type": "string", "direction": "out", "value": ""}]
    if kind == "subgraph":
        return [
            {"name": "in", "type": "any", "direction": "in"},
            {"name": "result", "type": "any", "direction": "out"},
        ]
    return [
        {"name": "in", "type": "string", "direction": "in"},
        {"name": "out", "type": "string", "direction": "out"},
    ]


def _args(call: ToolCall) -> dict[str, Any]:
    return call.arguments if isinstance(call.arguments, dict) else {}


def _schema(properties: dict[str, Any], *, required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


def _ok(call: ToolCall, payload: dict[str, Any]) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="ok",
        content=json.dumps(payload, ensure_ascii=False, default=str),
        metadata={"operation_payload": payload},
    )


def _failed(call: ToolCall, error: str) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="failed",
        error=error,
    )


__all__ = ["workflow_build_tool_specs", "workflow_build_tool_handlers", "OperationExecutor"]
