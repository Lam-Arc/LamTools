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

from .registry import WorkflowNodeRegistry


OperationExecutor = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[Any]]


def workflow_build_tool_specs(
    node_registry: WorkflowNodeRegistry | None = None,
) -> list[ToolSpec]:
    """Tool specs for fine-grained workflow-graph editing.

    Node kinds come from the same registry as ``workflow.object_info``.  Hosts
    may pass their trusted-plugin registry so model editing and CLI discovery
    expose the same vocabulary; the default contains all shipped node types.
    """
    registry = node_registry or WorkflowNodeRegistry()
    node_kind = {
        "type": "string",
        "enum": [item.type_id for item in registry.list() if not bool(item.raw.get("hidden"))],
    }
    port_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Stable port id; keep unchanged when renaming the port"},
            "name": {"type": "string"},
            "type": {"type": "string"},
            "direction": {"type": "string", "enum": ["in", "out"]},
            "description": {"type": "string"},
            # Content values are serialized through the model tool boundary.
            # Keep the boundary scalar and let strict_tool_schema make this
            # optional field nullable; an untyped leaf is rejected by strict
            # function-schema validators before the request is sent.
            "value": {
                "type": "string",
                "description": "Constant value for a content node's output port.",
            },
        },
        "required": ["name", "direction"],
    }
    config_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            # AI / agent node settings
            "mode": {"type": "string", "enum": ["single", "loop", "agent"]},
            "instruction": {"type": "string"},
            "system_prompt": {"type": "string"},
            "goal": {"type": "string"},
            "output_format_text": {"type": "string"},
            "model_id": {"type": "string"},
            "agent": {"type": "string"},
            "reasoning_effort": {"type": "string"},
            "temperature": {"type": "number"},
            "top_p": {"type": "number"},
            "max_tokens": {"type": "integer"},
            "loop_max_iterations": {"type": "integer"},
            "tools": {"type": "array", "items": {"type": "string"}},
            "allowed_tools": {"type": "array", "items": {"type": "string"}},
            # Subgraph node settings
            "workflow_name": {"type": "string"},
            "iterate": {"type": "string", "enum": ["none", "loop", "map"]},
            "max_iterations": {"type": "integer"},
            "condition": {"type": "string"},
            # Command / script node settings
            "command": {"type": "string"},
            "cwd": {"type": "string"},
            "env": {"type": "object", "properties": {}},
            "timeout": {"type": "number"},
            "script": {"type": "string"},
            # Deterministic data/control node settings
            "template": {"type": "string"},
            "text": {"type": "string"},
            "content": {"type": "string"},
            "expression": {"type": "string"},
            "value": {"type": "string"},
            # Shared execution/error settings
            "retries": {"type": "integer"},
            "on_error": {
                "type": "object",
                "properties": {
                    "strategy": {"type": "string", "enum": ["abort", "fallback", "skip"]},
                    "fallback_port": {"type": "string"},
                    "error_value": {"type": "string"},
                },
            },
            # Legacy action-node migration field.
            "action_type": {"type": "string"},
        },
        "required": [],
    }
    return [
        ToolSpec(
            name="workflow_graph",
            description=(
                "Read the compact semantic graph (node/link summaries, stable ids and interface). Always call "
                "this before editing to see existing node and port ids and connections. "
                "Returns an empty graph {name,nodes:[],edges:[]} when the workflow does "
                "not exist yet — you can then add the first node."
            ),
            input_schema=_schema({}, required=[]),
            permission=AUTO_ALLOW,
            metadata={"category": "workflow"},
        ),
        ToolSpec(
            name="workflow_add_node",
            description=(
                "Add a node to the current workflow. If the workflow does not exist yet "
                "it is created empty first (lazy bootstrap). Query workflow.object_info "
                "for the current dynamic kind catalog. Core kinds include:\n"
                "- model: one model completion. Named output ports force structured JSON. "
                "Instruction supports {{port_name}} interpolation.\n"
                "- agent: independent tool-capable agent execution; config.allowed_tools can narrow inherited authority.\n"
                "- command: invoke a CLI tool via shell (curl/git/ffmpeg/...). config.command "
                "is the shell command, run in the same shell run_command uses (Git Bash on "
                "Windows). stdin receives {\"inputs\":{port:val}} JSON and INPUT_<PORT> env "
                "vars are set. stdout that is a JSON object is split by key to same-named "
                "output ports, else the whole stdout goes to the default out port. Command "
                "(shell) is Turing-complete — use it for http (curl) and file/data ops too.\n"
                "- python: write Python. config.script is plain Python where INPUT PORT NAMES "
                "are directly usable variables (node IN a, IN b → use a, b in code) and assigning "
                "to an OUTPUT PORT NAME produces that output (OUT y → y = ...). Do NOT print, do "
                "NOT parse stdin — the runtime binds inputs as locals and reads outputs as locals. "
                "A new script node is auto-scaffolded with its port names + comments as a starter.\n"
                "- constant: only output ports, each carrying a constant value (port.value). "
                "Injects constants, runs nothing.\n"
                "- input/output: explicit graph boundary passthroughs.\n"
                "- template/transform: deterministic {{name}} text interpolation.\n"
                "- condition/branch: expression routing; merge selects the first active input and join collects named inputs.\n"
                "- subgraph: references an external workflow by config.workflow_name; "
                "config.iterate = none | loop | map (call once / loop until condition / "
                "fan-out over an array).\n"
                "Edge modifiers: condition (per-edge Python expr; false → skip that path), "
                "transform (per-edge $.field extraction), on_error (node-level "
                "abort/fallback/skip). Each node has in/out ports; one in-port fed by "
                "multiple edges aggregates into an array. position is canvas {x,y}."
            ),
            input_schema=_schema({
                "kind": node_kind,
                "title": {"type": "string"},
                "config": config_schema,
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
                "Prefer source_port_id/target_port_id from workflow_graph; port names remain a legacy fallback."
            ),
            input_schema=_schema({
                "source": {"type": "string"},
                "source_port": {"type": "string"},
                "source_port_id": {"type": "string", "description": "Preferred stable source port id"},
                "target": {"type": "string"},
                "target_port": {"type": "string"},
                "target_port_id": {"type": "string", "description": "Preferred stable target port id"},
            }, required=["source", "target"]),
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
                "config": config_schema,
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

    def _call_work_root(call: ToolCall) -> str:
        metadata = call.metadata if isinstance(call.metadata, dict) else {}
        raw = metadata.get("work_root") or metadata.get("workRoot")
        if not raw:
            session_metadata = metadata.get("_runtime_session_metadata")
            if isinstance(session_metadata, dict):
                raw = session_metadata.get("work_root") or session_metadata.get("workRoot")
        if raw:
            return str(raw)
        return str(work_root or "")

    async def _get_graph(name: str, call: ToolCall) -> dict[str, Any] | None:
        payload: dict[str, Any] = {"name": name}
        active_root = _call_work_root(call)
        if active_root:
            payload["work_root"] = active_root
        result = await execute_operation("workflow.get", payload, {})
        status = str(getattr(result, "status", "error") or "error")
        if status == "ok":
            wf = (getattr(result, "payload", {}) or {}).get("workflow")
            return wf if isinstance(wf, dict) else None
        # "Workflow not found" is expected when bootstrapping from an empty
        # session; surface it as None so callers can lazy-create / return an
        # empty graph. Any other error is a real failure — raise so the caller
        # reports it rather than silently treating it as missing.
        err = str((getattr(result, "payload", {}) or {}).get("error") or "")
        if "not found" in err.lower():
            return None
        raise RuntimeError(err or "workflow.get failed")

    async def _ensure_graph(name: str, call: ToolCall) -> dict[str, Any]:
        """Return the named graph, lazy-creating an empty one if it is missing.

        Used by every write tool (add_node/connect/delete/update) so the agent
        can build a workflow from zero with its natural graph→add→connect flow —
        no separate "create" step or tool required.
        """
        wf = await _get_graph(name, call)
        if wf is not None:
            return wf
        # Bootstrap: create an empty workflow, then re-read it (workflow.create
        # returns the created definition, but re-reading keeps one code path).
        create_payload: dict[str, Any] = {"name": name}
        active_root = _call_work_root(call)
        if active_root:
            create_payload["work_root"] = active_root
        result = await execute_operation("workflow.create", create_payload, {})
        status = str(getattr(result, "status", "error") or "error")
        if status != "ok":
            err = str((getattr(result, "payload", {}) or {}).get("error") or "create failed")
            raise RuntimeError(f"could not bootstrap workflow {name!r}: {err}")
        wf = (getattr(result, "payload", {}) or {}).get("workflow")
        return wf if isinstance(wf, dict) else {"name": name, "nodes": [], "edges": []}

    async def _save_graph(name: str, wf: dict[str, Any], call: ToolCall) -> dict[str, Any]:
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
        active_root = _call_work_root(call)
        if active_root:
            payload["work_root"] = active_root
        result = await execute_operation("workflow.update", payload, {})
        status = str(getattr(result, "status", "error") or "error")
        if status != "ok":
            err = str((getattr(result, "payload", {}) or {}).get("error") or "save failed")
            raise RuntimeError(err)
        saved = (getattr(result, "payload", {}) or {}).get("workflow")
        return saved if isinstance(saved, dict) else wf

    async def _resolve_name(call: ToolCall) -> str:
        session_metadata = call.metadata.get("_runtime_session_metadata")
        if isinstance(session_metadata, dict):
            resource_id = str(session_metadata.get("resource_id") or "").strip()
            if (
                session_metadata.get("owner_plugin") == "workflow"
                and session_metadata.get("resource_type") == "workflow"
                and resource_id
            ):
                payload: dict[str, Any] = {"workflow_id": resource_id}
                scoped_root = str(session_metadata.get("work_root") or _call_work_root(call) or "").strip()
                if scoped_root:
                    payload["work_root"] = scoped_root
                result = await execute_operation("workflow.get", payload, {})
                if str(getattr(result, "status", "error") or "error") == "ok":
                    workflow = (getattr(result, "payload", {}) or {}).get("workflow")
                    if isinstance(workflow, dict):
                        return str(workflow.get("name") or "").strip()
        session = str(call.metadata.get("_runtime_session_id") or "").strip()
        # Legacy sessions used wf_<name>; keep resolving those while old
        # clients migrate to metadata-bound workflow:<id> sessions.
        if session.startswith("wf_"):
            return session[3:]
        return ""

    async def workflow_graph(call: ToolCall) -> ToolResult:
        name = await _resolve_name(call)
        if not name:
            return _failed(call, "no active workflow (session id missing)")
        try:
            wf = await _get_graph(name, call)
        except RuntimeError as exc:
            return _failed(call, str(exc))
        if wf is None:
            # Empty graph so the agent can immediately add the first node —
            # the very first edit (add_node) bootstraps the workflow.
            wf = {"name": name, "nodes": [], "edges": []}
        return _ok(call, _semantic_view(wf))

    async def workflow_add_node(call: ToolCall) -> ToolResult:
        args = _args(call)
        name = await _resolve_name(call)
        if not name:
            return _failed(call, "no active workflow (session metadata missing)")
        try:
            wf = await _ensure_graph(name, call)
        except RuntimeError as exc:
            return _failed(call, str(exc))
        nodes = list(wf.get("nodes") or [])
        kind = str(args.get("kind") or "command")
        import secrets

        node_id = str(args.get("node_id") or "").strip() or f"{kind}-{secrets.token_hex(2)}"
        if any(str(n.get("id")) == node_id for n in nodes if isinstance(n, dict)):
            return _failed(call, f"node id already exists: {node_id}")
        ports = args.get("ports") if isinstance(args.get("ports"), list) else _default_ports(kind)
        ports = _ensure_port_ids(node_id, ports)
        config = args.get("config") if isinstance(args.get("config"), dict) else {}
        # Auto-scaffold a starter script from the port names + comments, so the
        # model opens a ready-to-fill file with the right variable names.
        if kind in {"script", "python"} and not str(config.get("script") or "").strip():
            config = dict(config)
            config["script"] = _scaffold_script(str(args.get("title") or kind.capitalize()), ports)
        node: dict[str, Any] = {
            "id": node_id,
            "kind": kind,
            "title": str(args.get("title") or kind.capitalize()),
            "config": config,
            "ports": ports,
            "position": args.get("position") if isinstance(args.get("position"), dict) else {"x": 120, "y": 120},
        }
        nodes.append(node)
        wf["nodes"] = nodes
        saved = await _save_graph(name, wf, call)
        return _ok(call, {"added": node, "workflow": saved})

    async def workflow_connect(call: ToolCall) -> ToolResult:
        args = _args(call)
        name = await _resolve_name(call)
        if not name:
            return _failed(call, "no active workflow (session metadata missing)")
        try:
            wf = await _ensure_graph(name, call)
        except RuntimeError as exc:
            return _failed(call, str(exc))
        source = str(args.get("source") or "")
        source_port = str(args.get("source_port") or "")
        source_port_id = str(args.get("source_port_id") or "")
        target = str(args.get("target") or "")
        target_port = str(args.get("target_port") or "")
        target_port_id = str(args.get("target_port_id") or "")
        nodes = wf.get("nodes") or []
        node_ids = {str(n.get("id")) for n in nodes if isinstance(n, dict)}
        if source not in node_ids or target not in node_ids:
            return _failed(call, "source or target node id not found")
        source_node = next((n for n in nodes if isinstance(n, dict) and str(n.get("id")) == source), {})
        target_node = next((n for n in nodes if isinstance(n, dict) and str(n.get("id")) == target), {})
        source_ports = _ensure_port_ids(source, source_node.get("ports") or [])
        target_ports = _ensure_port_ids(target, target_node.get("ports") or [])
        source_match = next((p for p in source_ports if str(p.get("id")) == source_port_id), None) if source_port_id else next((p for p in source_ports if str(p.get("name")) == source_port and str(p.get("direction")) == "out"), None)
        target_match = next((p for p in target_ports if str(p.get("id")) == target_port_id), None) if target_port_id else next((p for p in target_ports if str(p.get("name")) == target_port and str(p.get("direction")) == "in"), None)
        # Older graph fixtures omitted ports entirely. Preserve that migration
        # boundary only for name-based connections; canonical V2 callers use
        # stable ids and receive strict endpoint validation.
        if source_ports and source_match is None:
            return _failed(call, "source output port not found")
        if target_ports and target_match is None:
            return _failed(call, "target input port not found")
        if source_match is not None:
            source_port = str(source_match.get("name") or source_port)
            source_port_id = str(source_match.get("id") or source_port_id)
        if target_match is not None:
            target_port = str(target_match.get("name") or target_port)
            target_port_id = str(target_match.get("id") or target_port_id)
        import secrets

        edges = list(wf.get("edges") or [])
        edge_id = f"e-{source}-{source_port}-{target}-{target_port}-{secrets.token_hex(1)}"
        edges.append({
            "id": edge_id,
            "source": source,
            "source_port": source_port,
            "target": target,
            "target_port": target_port,
            "source_port_id": source_port_id,
            "target_port_id": target_port_id,
        })
        wf["edges"] = edges
        saved = await _save_graph(name, wf, call)
        return _ok(call, {"connected": edge_id, "workflow": saved})

    async def workflow_delete_node(call: ToolCall) -> ToolResult:
        args = _args(call)
        name = await _resolve_name(call)
        if not name:
            return _failed(call, "no active workflow (session metadata missing)")
        try:
            wf = await _ensure_graph(name, call)
        except RuntimeError as exc:
            return _failed(call, str(exc))
        node_id = str(args.get("node_id") or "")
        wf["nodes"] = [n for n in (wf.get("nodes") or []) if isinstance(n, dict) and str(n.get("id")) != node_id]
        wf["edges"] = [e for e in (wf.get("edges") or []) if isinstance(e, dict) and str(e.get("source")) != node_id and str(e.get("target")) != node_id]
        saved = await _save_graph(name, wf, call)
        return _ok(call, {"deleted": node_id, "workflow": saved})

    async def workflow_update_node(call: ToolCall) -> ToolResult:
        args = _args(call)
        name = await _resolve_name(call)
        if not name:
            return _failed(call, "no active workflow (session metadata missing)")
        try:
            wf = await _ensure_graph(name, call)
        except RuntimeError as exc:
            return _failed(call, str(exc))
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
                    previous = {str(p.get("name")): str(p.get("id") or "") for p in (n.get("ports") or []) if isinstance(p, dict)}
                    updated = []
                    for raw in args.get("ports"):
                        if not isinstance(raw, dict):
                            continue
                        item = dict(raw)
                        if not item.get("id") and previous.get(str(item.get("name") or "")):
                            item["id"] = previous[str(item.get("name") or "")]
                        updated.append(item)
                    n["ports"] = _ensure_port_ids(node_id, updated)
                if isinstance(args.get("position"), dict):
                    n["position"] = args.get("position")
                found = True
                break
        if not found:
            return _failed(call, f"node not found: {node_id}")
        wf["nodes"] = nodes
        saved = await _save_graph(name, wf, call)
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
    if kind in {"content", "constant"}:
        return [{"name": "out", "type": "string", "direction": "out", "value": ""}]
    if kind == "subgraph":
        return [
            {"name": "in", "type": "any", "direction": "in"},
            {"name": "result", "type": "any", "direction": "out"},
        ]
    if kind in {"condition", "branch"}:
        return [
            {"name": "value", "type": "any", "direction": "in"},
            {"name": "true", "type": "any", "direction": "out"},
            {"name": "false", "type": "any", "direction": "out"},
        ]
    return [
        {"name": "in", "type": "string", "direction": "in"},
        {"name": "out", "type": "string", "direction": "out"},
    ]


def _semantic_view(workflow: dict[str, Any]) -> dict[str, Any]:
    """Compact read shape used by the model before ID-based patches."""
    nodes = []
    for raw in workflow.get("nodes") or []:
        if not isinstance(raw, dict):
            continue
        node_id = str(raw.get("id") or "")
        ports = _ensure_port_ids(node_id, raw.get("ports") or [])
        nodes.append({
            "id": node_id,
            "type_id": str(raw.get("type_id") or raw.get("kind") or ""),
            "title": str(raw.get("title") or ""),
            # Agent graph editing still needs the executable parameters and
            # placement.  Keep the view compact, but do not make a read-before-
            # write client guess the values it is about to preserve or patch.
            "params": dict(raw.get("config") or {}) if isinstance(raw.get("config"), dict) else {},
            "position": dict(raw.get("position") or {}) if isinstance(raw.get("position"), dict) else {},
            "ports": [{
                "id": p.get("id"), "name": p.get("name"),
                "direction": p.get("direction"), "data_type": p.get("type", "any"),
            } for p in ports],
        })
    edges = [{
        "id": raw.get("id"),
        "source": {"node_id": raw.get("source"), "port_id": raw.get("source_port_id"), "port_name": raw.get("source_port")},
        "target": {"node_id": raw.get("target"), "port_id": raw.get("target_port_id"), "port_name": raw.get("target_port")},
        **({"transform": raw.get("transform")} if raw.get("transform") else {}),
        **({"condition": raw.get("condition")} if raw.get("condition") else {}),
    } for raw in (workflow.get("edges") or []) if isinstance(raw, dict)]
    return {
        "format": "lamtools.semantic-graph", "version": 1,
        "name": workflow.get("name"), "revision": workflow.get("revision", 0),
        "description": workflow.get("description", ""),
        "nodes": nodes, "edges": edges,
        "interface": {
            "inputs": workflow.get("input_params") or [],
            "output": workflow.get("output_port") or "",
        },
    }


def _ensure_port_ids(node_id: str, ports: list[Any]) -> list[dict[str, Any]]:
    """Assign deterministic ids only at the legacy/model edit boundary."""
    import uuid

    result: list[dict[str, Any]] = []
    for index, raw in enumerate(ports):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        if not str(item.get("id") or "").strip():
            seed = f"{node_id}\x1f{item.get('direction', 'in')}\x1f{item.get('name', '')}\x1f{index}"
            item["id"] = f"port_{uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:16]}"
        result.append(item)
    return result


def _scaffold_script(title: str, ports: list[Any]) -> str:
    """Starter Python for a freshly created script node.

    Lists input port names (available as variables) and output port names
    (assign to produce output) on two comment lines, plus a `name = None`
    placeholder per output. The runtime binds inputs as locals — inputs are
    only commented (never re-declared, which would clobber the bound value).
    """
    in_ports = [p for p in ports if isinstance(p, dict) and p.get("direction") == "in"]
    out_ports = [p for p in ports if isinstance(p, dict) and p.get("direction") == "out"]
    in_names = [_id(p.get("name")) for p in in_ports]
    out_names = [_id(p.get("name")) for p in out_ports]
    lines = [
        f"# 输入：{', '.join(in_names) if in_names else '（无）'}",
        f"# 输出：{', '.join(out_names) if out_names else '（无）'}",
        "",
    ]
    for name in out_names:
        lines.append(f"{name} = None")
    return "\n".join(lines) + "\n"


def _id(name: Any) -> str:
    """A safe Python identifier fallback for a port name."""
    s = str(name or "value").strip()
    if s.isidentifier():
        return s
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in s) or "value"
    return cleaned if cleaned.isidentifier() else "value"


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
