"""Workflow mode — fixed node graphs that eliminate agent-loop uncertainty.

A :class:`WorkflowDef` is a user-authored node graph (LLM / Agent / Action
nodes connected by typed named ports). It is persisted as a JSON file (mirrors
the SkillRegistry discovery pattern) and may be *exposed* as a callable agent
tool. The :class:`WorkflowRunner` executes a graph in topological order,
streaming per-node state through the same ``core/runItem`` channel the kernel
uses for turns.

Design mirrors :mod:`lamtools_core.runtime.arrange` (data model + manager +
runner), but workflows are deterministic procedures rather than scheduled
durable jobs — there is no leasing or polling loop.
"""

from __future__ import annotations

import asyncio
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from lamtools_core.event.run_item import RunItemEvent, RunItemStatus


WorkflowNodeKind = Literal["ai", "command", "script", "content", "subgraph"]
PortDirection = Literal["in", "out"]
NodeStateStatus = Literal["idle", "running", "done", "error", "skipped", "cancelled"]

# Sentinel emitted when a node's condition is not met. Downstream nodes whose
# every input is this sentinel are skipped (cascade); mixed inputs run with
# sentinels coerced to None.
SKIP_SENTINEL = "__workflow_skip__"

# Recognised workflow port types. ``"any"`` matches anything.
_WORKFLOW_TYPES = {"string", "number", "boolean", "object", "array", "any"}

# Safe builtins available inside condition expressions (Python ``eval``).
# bound_inputs are passed as locals so conditions like ``len(text) > 100``
# or ``quality >= 0.8 and source in ['A','B']`` work naturally.
_CONDITION_BUILTINS = {
    "len": len, "str": str, "int": int, "float": float, "bool": bool,
    "any": any, "all": all, "min": min, "max": max, "sum": sum,
    "abs": abs, "round": round, "isinstance": isinstance, "True": True,
    "False": False, "None": None,
}

# Whole-token matcher for ``$VAR`` / ``${VAR}`` substitution. Matching the
# complete identifier (not a string prefix) prevents ``$INPUT_A`` from being
# rewritten when ``$INPUT_ABC`` is in the command (audit 07 S4).
_VAR_TOKEN_RE = re.compile(r"\$(?:\{(?P<braced>\w+)\}|(?P<plain>\w+))")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class WorkflowPort:
    """A typed, named port on a node. Data flows out -> in along edges.

    ``value`` holds a constant for ``content`` node output ports (each port
    carries its own value); it is unused for other kinds.
    """

    name: str
    type: str = "any"  # free-form type name; "any" matches anything
    direction: PortDirection = "in"
    description: str = ""
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "direction": self.direction,
            "description": self.description,
        }
        if self.value is not None:
            data["value"] = self.value
        return data

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkflowPort":
        return cls(
            name=str(value.get("name") or ""),
            type=str(value.get("type") or "any"),
            direction="out" if str(value.get("direction") or "in") == "out" else "in",
            description=str(value.get("description") or ""),
            value=value.get("value"),
        )


@dataclass
class WorkflowNode:
    """A single workflow node. ``config`` holds kind-specific fields."""

    id: str
    kind: WorkflowNodeKind
    title: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    ports: list[WorkflowPort] = field(default_factory=list)
    position: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "config": _json_copy(self.config),
            "ports": [p.to_dict() for p in self.ports],
            "position": dict(self.position),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkflowNode":
        ports_raw = value.get("ports")
        if ports_raw is None:
            # Folder layout stores inputs[]/outputs[] separately — accept both.
            ports_raw = _io_to_port_dicts(value.get("inputs"), value.get("outputs"))
        raw_kind = str(value.get("kind") or "command")
        # Migrate legacy "action" kind → command/script by action_type.
        if raw_kind == "action":
            cfg = value.get("config") if isinstance(value.get("config"), dict) else {}
            raw_kind = "script" if str(cfg.get("action_type") or "").lower() == "script" else "command"
        return cls(
            id=str(value.get("id") or ""),
            kind=raw_kind,  # type: ignore[arg-type]
            title=str(value.get("title") or ""),
            config=dict(value.get("config") or {}),
            ports=[WorkflowPort.from_dict(p) for p in ports_raw if isinstance(p, dict)],
            position={k: float(v) for k, v in (value.get("position") or {}).items()} if isinstance(value.get("position"), dict) else {},
        )

    def input_ports(self) -> list[WorkflowPort]:
        return [p for p in self.ports if p.direction == "in"]

    def output_ports(self) -> list[WorkflowPort]:
        return [p for p in self.ports if p.direction == "out"]


@dataclass
class WorkflowEdge:
    """A connection from a source output port to a target input port.

    ``transform`` is an optional JSONPath-style field path (``$.field`` or
    ``$.a.b``) applied to the upstream value before it reaches the target.
    ``condition`` is an optional Python expression evaluated against the
    upstream node's bound inputs (port names as locals); when it evaluates
    False the edge transmits ``SKIP_SENTINEL`` so downstream nodes on that
    path are skipped (cascade). Both default to empty (pass-through / always).
    """

    id: str
    source: str  # node id
    source_port: str
    target: str  # node id
    target_port: str
    transform: str = ""
    condition: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "source": self.source,
            "source_port": self.source_port,
            "target": self.target,
            "target_port": self.target_port,
        }
        if self.transform:
            data["transform"] = self.transform
        if self.condition:
            data["condition"] = self.condition
        return data

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkflowEdge":
        return cls(
            id=str(value.get("id") or _new_id("edge")),
            source=str(value.get("source") or ""),
            source_port=str(value.get("source_port") or ""),
            target=str(value.get("target") or ""),
            target_port=str(value.get("target_port") or ""),
            transform=str(value.get("transform") or ""),
            condition=str(value.get("condition") or ""),
        )


@dataclass
class WorkflowInputParam:
    """A typed workflow input parameter (becomes the tool's input schema)."""

    name: str
    type: str = "any"
    description: str = ""
    required: bool = True
    default: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "required": self.required,
            "default": self.default,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkflowInputParam":
        return cls(
            name=str(value.get("name") or ""),
            type=str(value.get("type") or "any"),
            description=str(value.get("description") or ""),
            required=bool(value.get("required", True)),
            default=value.get("default"),
        )


@dataclass
class WorkflowDef:
    """A complete workflow definition. ``exposed`` gates tool availability."""

    name: str
    description: str = ""
    nodes: list[WorkflowNode] = field(default_factory=list)
    edges: list[WorkflowEdge] = field(default_factory=list)
    input_params: list[WorkflowInputParam] = field(default_factory=list)
    output_port: str = ""  # "nodeId" or "nodeId.portName"
    exposed: bool = False
    tool_name: str = ""
    work_root: str = ""
    # Mermaid-style edge text (``a.port.type -> b.port.type``). The runtime
    # uses ``edges`` directly; the store layer translates edges <-> map.
    map: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "input_params": [p.to_dict() for p in self.input_params],
            "output_port": self.output_port,
            "exposed": self.exposed,
            "tool_name": self.tool_name,
            "work_root": self.work_root,
            "map": self.map,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkflowDef":
        return cls(
            name=str(value.get("name") or ""),
            description=str(value.get("description") or ""),
            nodes=[WorkflowNode.from_dict(n) for n in (value.get("nodes") or []) if isinstance(n, dict)],
            edges=[WorkflowEdge.from_dict(e) for e in (value.get("edges") or []) if isinstance(e, dict)],
            input_params=[WorkflowInputParam.from_dict(p) for p in (value.get("input_params") or value.get("inputParams") or []) if isinstance(p, dict)],
            output_port=str(value.get("output_port") or value.get("outputPort") or ""),
            exposed=bool(value.get("exposed", False)),
            tool_name=str(value.get("tool_name") or value.get("toolName") or ""),
            work_root=str(value.get("work_root") or value.get("workRoot") or ""),
            map=str(value.get("map") or ""),
            created_at=_parse_dt(value.get("created_at")) or _utcnow(),
            updated_at=_parse_dt(value.get("updated_at")) or _utcnow(),
        )

    def effective_tool_name(self) -> str:
        return (self.tool_name or f"workflow_{self.name}").strip()

    def node(self, node_id: str) -> WorkflowNode | None:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None


@dataclass
class WorkflowNodeState:
    """Runtime state of a single node during/after a run."""

    node_id: str
    status: NodeStateStatus = "idle"
    output: Any = None
    error: str = ""
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "attempts": self.attempts,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


@dataclass
class WorkflowRunResult:
    """Result of a workflow run (full or single-step)."""

    status: Literal["completed", "failed", "cancelled", "paused"] = "completed"
    output: Any = None
    node_states: dict[str, WorkflowNodeState] = field(default_factory=dict)
    # Per-port values produced so far: {"nodeId.portName": value}.
    values: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    run_id: str = ""
    steps_remaining: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "output": self.output,
            "node_states": {k: v.to_dict() for k, v in self.node_states.items()},
            "values": _json_copy(self.values),
            "error": self.error,
            "run_id": self.run_id,
            "steps_remaining": self.steps_remaining,
        }


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str, ensure_ascii=False))
    except (TypeError, ValueError):
        return value


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# WorkflowManager — create / get / list / update / delete over a store
# ---------------------------------------------------------------------------


WorkflowEventCallback = Callable[[RunItemEvent], Awaitable[None] | None]


class WorkflowManager:
    """Coordinates workflow definitions with a :class:`WorkflowStore`-like store.

    The store protocol mirrors :class:`ArrangeStore`: async ``list`` / ``get`` /
    ``save`` / ``delete``. The file-backed implementation lives in
    :mod:`lamtools_core.project.workflow_store`.
    """

    def __init__(self, store: Any) -> None:
        self.store = store

    async def create(self, definition: WorkflowDef) -> WorkflowDef:
        return await self.store.save(definition)

    async def get(self, name: str, *, work_root: str | None = None) -> WorkflowDef | None:
        return await self.store.get(name, work_root=work_root)

    async def list(self, *, work_root: str | None = None) -> list[WorkflowDef]:
        return await self.store.list(work_root=work_root)

    async def list_grouped(self, *, work_roots: list[str]) -> dict[str, list[WorkflowDef]]:
        """Return workflows bucketed by source: ``"global"`` + per ``work_root``."""
        grouped = getattr(self.store, "list_grouped", None)
        if grouped is None:
            return {"global": await self.store.list(work_root=None)}
        return await grouped(work_roots=work_roots)

    async def update_fields(
        self,
        name: str,
        *,
        work_root: str | None = None,
        description: str | None = None,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
        input_params: list[dict[str, Any]] | None = None,
        output_port: str | None = None,
        exposed: bool | None = None,
        tool_name: str | None = None,
    ) -> WorkflowDef:
        current = await self.store.get(name, work_root=work_root)
        if current is None:
            raise LookupError(f"Workflow not found: {name}")
        if description is not None:
            current.description = description
        if nodes is not None:
            current.nodes = [WorkflowNode.from_dict(n) for n in nodes]
        if edges is not None:
            current.edges = [WorkflowEdge.from_dict(e) for e in edges]
        if input_params is not None:
            current.input_params = [WorkflowInputParam.from_dict(p) for p in input_params]
        if output_port is not None:
            current.output_port = output_port
        if exposed is not None:
            current.exposed = exposed
        if tool_name is not None:
            current.tool_name = tool_name
        current.updated_at = _utcnow()
        return await self.store.save(current)

    async def delete(self, name: str, *, work_root: str | None = None) -> bool:
        return await self.store.delete(name, work_root=work_root)

    async def set_exposed(self, name: str, exposed: bool, *, work_root: str | None = None) -> WorkflowDef:
        return await self.update_fields(name, work_root=work_root, exposed=exposed)

    async def list_exposed(self, *, work_root: str | None = None) -> list[WorkflowDef]:
        return [w for w in await self.store.list(work_root=work_root) if w.exposed]


# ---------------------------------------------------------------------------
# WorkflowRunner — executes a graph in topological order
# ---------------------------------------------------------------------------


class WorkflowRunner:
    """Executes a :class:`WorkflowDef` deterministically.

    Execution order is the topological sort of the node graph. Data flows along
    typed named ports. Each node may retry up to ``config.retries`` times before
    the run aborts (failure-as-abort is the core guarantee that workflows
    "eliminate uncertainty"). Per-node state is streamed via an injected
    ``emit`` callback as :class:`RunItemEvent` objects (``kind="status"``,
    ``item_id=<node_id>``) so the existing ``core/runItem`` GUI reducer renders
    node state without a new channel.
    """

    def __init__(
        self,
        *,
        llm_client: Any = None,
        sub_agent_runner: Any = None,
        emit: WorkflowEventCallback | None = None,
        runtime_task_registry: Any = None,
        workflow_store: Any = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.llm_client = llm_client
        self.sub_agent_runner = sub_agent_runner
        self.emit = emit
        self.runtime_task_registry = runtime_task_registry
        # ``workflow_store`` enables subworkflow nodes to resolve and run other
        # workflow definitions by name.
        self.workflow_store = workflow_store
        self.clock = clock

    async def run(
        self,
        workflow: WorkflowDef,
        *,
        inputs: dict[str, Any] | None = None,
        work_root: str = "",
        thread_id: str = "",
        run_id: str = "",
        prior_values: dict[str, Any] | None = None,
        prior_node_states: dict[str, WorkflowNodeState] | None = None,
        max_steps: int | None = None,
        start_node: str | None = None,
        single_node: str | None = None,
    ) -> WorkflowRunResult:
        """Run the workflow.

        ``max_steps=None`` runs to completion (整跑); an integer runs at most
        that many *ready* nodes then returns ``status="paused"`` (单步调试).
        ``prior_values`` / ``prior_node_states`` resume a paused run.
        ``start_node`` runs the subgraph from that node onward (nodes before it
        are skipped; their outputs must be in ``prior_values``).
        ``single_node`` runs exactly one node in isolation.
        """
        inputs = dict(inputs or {})
        work_root = work_root or workflow.work_root
        run_id = run_id or _new_id("wfrun")
        thread_id = thread_id or f"workflow_thread_{uuid.uuid4().hex}"

        order = _topological_order(workflow)
        if order is None:
            return WorkflowRunResult(status="failed", error="workflow graph has a cycle", run_id=run_id)
        if single_node:
            if single_node not in order:
                return WorkflowRunResult(status="failed", error=f"unknown node: {single_node}", run_id=run_id)
            order = [single_node]
        elif start_node:
            if start_node not in order:
                return WorkflowRunResult(status="failed", error=f"unknown node: {start_node}", run_id=run_id)
            idx = order.index(start_node)
            order = order[idx:]

        values: dict[str, Any] = dict(prior_values or {})
        # Bind workflow inputs under the __input__ namespace. An input is any
        # node input port that no edge feeds (an "orphaned" in-port); it is
        # exposed as a workflow input named "{nodeId}.{portName}". The legacy
        # input_params array is merged in for backward compatibility.
        input_names = _workflow_input_names(workflow)
        for name in input_names:
            key = f"__input__.{name}"
            if name in inputs:
                values[key] = inputs[name]
            elif key not in values:
                values[key] = _workflow_input_default(workflow, name)

        node_states: dict[str, WorkflowNodeState] = dict(prior_node_states or {})
        for node in workflow.nodes:
            node_states.setdefault(node.id, WorkflowNodeState(node_id=node.id))

        cancel_event = self._cancel_event(thread_id)
        steps_taken = 0

        for node_id in order:
            if cancel_event is not None and cancel_event.is_set():
                _mark_cancelled(node_states, workflow, order, node_id)
                return WorkflowRunResult(
                    status="cancelled",
                    node_states=node_states,
                    values=values,
                    run_id=run_id,
                    steps_remaining=len(order) - steps_taken,
                )
            node = workflow.node(node_id)
            if node is None:
                continue
            state = node_states[node_id]
            if state.status in {"done", "cancelled"}:
                continue  # already executed (resumed run)
            if not _inputs_ready(node, workflow, values):
                continue  # not yet satisfiable; skip (shouldn't happen in topo order unless input gaps)

            if max_steps is not None and steps_taken >= max_steps:
                return WorkflowRunResult(
                    status="paused",
                    node_states=node_states,
                    values=values,
                    run_id=run_id,
                    steps_remaining=len(order) - steps_taken,
                )

            bound_inputs = _bind_inputs(node, workflow, values)

            # Skip cascade: when every bound input is the sentinel, this node
            # sits on a skipped path — skip it and propagate the sentinel.
            if bound_inputs and all(v == SKIP_SENTINEL for v in bound_inputs.values()):
                state.status = "skipped"
                state.finished_at = self.clock()
                for port in node.output_ports():
                    values[f"{node.id}.{port.name}"] = SKIP_SENTINEL
                await self._emit_state(node, "skipped", thread_id, run_id)
                continue

            await self._emit_state(node, "running", thread_id, run_id)
            state.status = "running"
            state.started_at = self.clock()

            try:
                outputs = await self._execute_with_retries(
                    node, bound_inputs, work_root, state, values,
                    thread_id=thread_id, run_id=run_id,
                )
            except asyncio.CancelledError:
                state.status = "cancelled"
                state.finished_at = self.clock()
                await self._emit_state(node, "cancelled", thread_id, run_id, error="cancelled")
                return WorkflowRunResult(
                    status="cancelled",
                    node_states=node_states,
                    values=values,
                    run_id=run_id,
                    steps_remaining=len(order) - steps_taken - 1,
                )
            except Exception as exc:  # retries exhausted
                error_msg = str(exc) or type(exc).__name__
                on_error = node.config.get("on_error") or {}
                strategy = str(on_error.get("strategy") or "abort") if isinstance(on_error, dict) else "abort"
                if strategy == "fallback":
                    # Emit a value on the fallback port so downstream can proceed.
                    fb_port = str(on_error.get("fallback_port") or _default_output_port(node) or "error")
                    fb_value = on_error.get("error_value")
                    if fb_value is None:
                        fb_value = SKIP_SENTINEL
                    outputs = {fb_port: fb_value}
                    state.status = "done"
                    state.error = error_msg
                    state.finished_at = self.clock()
                    await self._emit_state(node, "completed", thread_id, run_id, error=error_msg)
                    for port_name, value in outputs.items():
                        values[f"{node.id}.{port_name}"] = value
                    steps_taken += 1
                    continue
                if strategy == "skip":
                    state.status = "skipped"
                    state.error = error_msg
                    state.finished_at = self.clock()
                    for port in node.output_ports():
                        values[f"{node.id}.{port.name}"] = SKIP_SENTINEL
                    await self._emit_state(node, "skipped", thread_id, run_id, error=error_msg)
                    continue
                # Default: abort the whole run.
                state.status = "error"
                state.error = error_msg
                state.finished_at = self.clock()
                await self._emit_state(node, "failed", thread_id, run_id, error=error_msg)
                return WorkflowRunResult(
                    status="failed",
                    node_states=node_states,
                    values=values,
                    error=f"Node '{node.title or node.id}' failed: {error_msg}",
                    run_id=run_id,
                    steps_remaining=len(order) - steps_taken - 1,
                )

            # Publish outputs to the value table.
            for port_name, value in outputs.items():
                values[f"{node.id}.{port_name}"] = value
            state.status = "done"
            state.output = outputs.get(_default_output_port(node)) or (
                outputs[next(iter(outputs))] if outputs else None
            )
            state.finished_at = self.clock()
            await self._emit_state(node, "completed", thread_id, run_id)
            steps_taken += 1

        output = _resolve_output(workflow, values)
        return WorkflowRunResult(
            status="completed",
            output=output,
            node_states=node_states,
            values=values,
            run_id=run_id,
            steps_remaining=0,
        )

    # -- node execution ----------------------------------------------------

    async def _execute_with_retries(
        self,
        node: WorkflowNode,
        bound_inputs: dict[str, Any],
        work_root: str,
        state: WorkflowNodeState,
        values: dict[str, Any] | None = None,
        *,
        thread_id: str = "",
        run_id: str = "",
    ) -> dict[str, Any]:
        retries = _as_int(node.config.get("retries"), default=0)
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            state.attempts = attempt + 1
            try:
                if node.kind == "ai":
                    return await self._execute_ai(node, bound_inputs, work_root)
                if node.kind == "content":
                    return await self._execute_content(node, bound_inputs, work_root)
                if node.kind == "subgraph":
                    return await self._execute_subgraph(node, bound_inputs, work_root, thread_id, run_id)
                if node.kind == "command":
                    return await self._execute_command(node, bound_inputs, work_root)
                if node.kind == "script":
                    return await self._execute_script(node, bound_inputs, work_root)
                raise ValueError(f"unsupported node kind: {node.kind}")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — retry boundary
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(0.1 * (attempt + 1))
        raise last_exc if last_exc is not None else RuntimeError("node execution failed")

    async def _execute_ai(
        self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str
    ) -> dict[str, Any]:
        """Unified AI node. ``config.mode`` selects the execution strategy:

        * ``single`` (default) — one LLM completion call.
        * ``loop`` — self-judging loop: the model prefixes its final answer
          with ``[DONE]``; iterate up to ``loop_max_iterations``.
        * ``agent`` — full sub-agent with tools and multi-turn decision.
        """
        cfg = node.config
        mode = str(cfg.get("mode") or "single")
        if mode == "agent":
            return await self._execute_ai_agent(node, bound_inputs, work_root)
        return await self._execute_ai_llm(node, bound_inputs, work_root, mode == "loop")

    async def _execute_ai_llm(
        self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str, is_loop: bool
    ) -> dict[str, Any]:
        cfg = node.config
        instruction = str(cfg.get("instruction") or cfg.get("system_prompt") or "")
        output_format_text = str(cfg.get("output_format_text") or "")
        model_id = str(cfg.get("model_id") or "")
        temperature = cfg.get("temperature")
        reasoning_effort = str(cfg.get("reasoning_effort") or "")
        max_tokens = cfg.get("max_tokens")
        top_p = cfg.get("top_p")

        if self.llm_client is None:
            raise RuntimeError("AI node requires an LLM client (none configured)")
        from lamtools_core.llm import ChatMessage, LLMRequest

        out_ports = node.output_ports()
        structured = bool(out_ports)

        def _interpolate(text: str) -> str:
            def _repl(m: re.Match) -> str:
                key = m.group(1).strip()
                val = bound_inputs.get(key)
                if val is None or val == SKIP_SENTINEL:
                    return ""
                return _summarize(val) if not isinstance(val, str) else val
            return re.sub(r"\{\{(\w+)\}\}", _repl, text)

        instruction_rendered = _interpolate(instruction)
        has_tokens = "{{" in instruction and instruction_rendered != instruction
        system_parts: list[str] = [instruction_rendered]
        if output_format_text:
            system_parts.append(f"Output format:\n{output_format_text}")
        if structured:
            field_desc = ", ".join(
                f"{p.name}({_normalise_type(p.type)})"
                + (f": {p.description}" if p.description else "")
                for p in out_ports
            )
            system_parts.append(
                f"You MUST respond with a single JSON object containing these fields: {field_desc}. "
                "Do not wrap it in markdown fences. Output only the JSON."
            )
        system_prompt = "\n\n".join(p for p in system_parts if p).strip()

        if has_tokens:
            user_content = "(rendered from template — see system prompt)" if not bound_inputs else "(inputs embedded in instruction)"
        else:
            context_lines = [f"- {k}: {_summarize(v)}" for k, v in bound_inputs.items() if v is not None and v != SKIP_SENTINEL]
            user_content = "\n".join(context_lines) if context_lines else "(no additional input)"

        messages: list[ChatMessage] = []
        if system_prompt:
            messages.append(ChatMessage(role="system", content=system_prompt))
        messages.append(ChatMessage(role="user", content=user_content))

        response_format: dict[str, Any] | None = {"type": "json_object"} if structured else None
        max_iter = max(1, _as_int(cfg.get("loop_max_iterations"), default=3)) if is_loop else 1

        transcript = list(messages)
        last_content = ""
        for i in range(max_iter):
            request = LLMRequest(
                messages=transcript,
                model=model_id,
                temperature=float(temperature) if temperature is not None else None,
                max_tokens=int(max_tokens) if max_tokens is not None else None,
                top_p=float(top_p) if top_p is not None else None,
                response_format=response_format,
                metadata={"reasoning_effort": reasoning_effort} if reasoning_effort else {},
            )
            response = await self.llm_client.complete(request)
            last_content = response.content or ""
            if is_loop and "[DONE]" in last_content:
                last_content = last_content.replace("[DONE]", "").strip()
                break
            if is_loop:
                transcript.append(ChatMessage(role="assistant", content=last_content))
                transcript.append(
                    ChatMessage(role="user", content="If the result is final, prefix your next message with [DONE]. Otherwise continue refining.")
                )
        return self._split_or_fallback(node, last_content)

    async def _execute_ai_agent(
        self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str
    ) -> dict[str, Any]:
        cfg = node.config
        goal = str(cfg.get("instruction") or cfg.get("goal") or "")
        out_ports = node.output_ports()
        structured = bool(out_ports)

        def _interpolate(text: str) -> str:
            def _repl(m: re.Match) -> str:
                val = bound_inputs.get(m.group(1).strip())
                if val is None or val == SKIP_SENTINEL:
                    return ""
                return _summarize(val) if not isinstance(val, str) else val
            return re.sub(r"\{\{(\w+)\}\}", _repl, text)

        goal_rendered = _interpolate(goal)
        context_lines = [f"- {k}: {_summarize(v)}" for k, v in bound_inputs.items() if v is not None and v != SKIP_SENTINEL and f"{{{{{k}}}}}" not in goal]
        task = goal_rendered + ("\n\nContext:\n" + "\n".join(context_lines) if context_lines else "")
        if structured:
            field_desc = ", ".join(f"{p.name}({_normalise_type(p.type)})" for p in out_ports)
            task += (
                f"\n\nYou MUST finish with a single JSON object containing these fields: {field_desc}. "
                "Output only the JSON."
            )
        if self.sub_agent_runner is None:
            raise RuntimeError("AI agent mode requires a sub_agent_runner (none configured)")
        raw_allowed = cfg.get("tools") or cfg.get("allowed_tools")
        allowed_tools = (
            [str(item) for item in raw_allowed if str(item).strip()]
            if isinstance(raw_allowed, list)
            else None
        )
        result = await self.sub_agent_runner.run(
            task=task,
            agent=str(cfg.get("agent") or ""),
            model=str(cfg.get("model_id") or ""),
            mode=str(cfg.get("mode") or ""),
            allowed_tools=allowed_tools,
        )
        content = getattr(result, "message", None) or ""
        return self._split_or_fallback(node, content)

    def _split_or_fallback(self, node: WorkflowNode, raw: str) -> dict[str, Any]:
        """Distribute structured JSON output across named ports, else fall back.

        When the node has named output ports and ``raw`` parses to a JSON object,
        each key matching a port name flows to that port (missing keys default to
        None). When there are no named ports, or parsing fails, the entire value
        goes to the default output port as a string.
        """
        out_ports = node.output_ports()
        default_port = _default_output_port(node) or "output"
        if not out_ports:
            return {default_port: raw}
        parsed = _json_object(raw)
        if parsed is None:
            # Fallback: whole value to the first output port.
            return {out_ports[0].name: raw}
        result: dict[str, Any] = {}
        for port in out_ports:
            if port.name in parsed:
                result[port.name] = _coerce_value(parsed[port.name], port.type)
            else:
                result[port.name] = None
        return result

    async def _execute_content(
        self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str
    ) -> dict[str, Any]:
        """Content nodes emit each output port's configured constant value."""
        result: dict[str, Any] = {}
        for port in node.output_ports():
            result[port.name] = port.value
        return result

    async def _execute_subgraph(
        self,
        node: WorkflowNode,
        bound_inputs: dict[str, Any],
        work_root: str,
        thread_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        """Execute a referenced workflow with an optional iteration mode.

        ``config.workflow_name`` selects the target workflow definition.
        ``config.iterate`` selects how the sub-workflow is run:

        * ``none`` (default) — run once; bound inputs feed the sub-workflow's
          orphaned in-ports.
        * ``loop`` — run repeatedly; the sub-workflow's output feeds back into
          the next iteration's inputs; exits when ``config.condition`` (a Python
          expression evaluated against the last output) is true, or
          ``config.max_iterations`` is reached.
        * ``map`` — the first bound input value (expected to be a list) provides
          the elements; the sub-workflow runs once per element; results are
          collected into an array.
        """
        cfg = node.config
        target_name = str(cfg.get("workflow_name") or "")
        if not target_name:
            raise ValueError("subgraph node requires config.workflow_name")
        if self.workflow_store is None:
            raise RuntimeError("subgraph node requires a workflow_store (none configured)")
        sub_def = await self.workflow_store.get(target_name, work_root=work_root or None)
        if sub_def is None:
            raise ValueError(f"subgraph target workflow '{target_name}' not found")

        iterate = str(cfg.get("iterate") or "none")
        out_port = _default_output_port(node) or "result"

        if iterate == "map":
            # Collect the iterable from the first non-sentinel bound input.
            items: list[Any] = []
            for v in bound_inputs.values():
                if v is not None and v != SKIP_SENTINEL:
                    items = v if isinstance(v, list) else [v]
                    break
            results: list[Any] = []
            for i, item in enumerate(items):
                sub_inputs = self._map_entry_inputs(sub_def, {"__item__": item})
                sub = await self.run(sub_def, inputs=sub_inputs, work_root=work_root,
                                      thread_id=f"{thread_id}.map{i}", run_id=f"{run_id}.map{i}")
                results.append(sub.output)
            return {out_port: results}

        if iterate == "loop":
            max_iter = max(1, _as_int(cfg.get("max_iterations"), default=5))
            condition_expr = str(cfg.get("condition") or "")
            # Seed entry inputs from bound_inputs.
            sub_inputs = self._map_entry_inputs(sub_def, bound_inputs)
            output: Any = None
            for i in range(max_iter):
                sub = await self.run(sub_def, inputs=sub_inputs, work_root=work_root,
                                      thread_id=f"{thread_id}.loop{i}", run_id=f"{run_id}.loop{i}")
                output = sub.output
                if sub.status != "completed":
                    break
                # Exit condition: evaluate against the output wrapped as locals.
                if condition_expr:
                    cond_locals = output if isinstance(output, dict) else {"value": output}
                    if _eval_condition(condition_expr, cond_locals):
                        break
                # Feed output back for next iteration.
                if isinstance(output, dict):
                    sub_inputs = {**self._map_entry_inputs(sub_def, bound_inputs), **output}
                else:
                    sub_inputs = self._map_entry_inputs(sub_def, {**bound_inputs, "__value__": output})
            return {out_port: output}

        # iterate == "none": run once.
        sub_inputs = self._map_entry_inputs(sub_def, bound_inputs)
        result = await self.run(sub_def, inputs=sub_inputs, work_root=work_root,
                                thread_id=f"{thread_id}.sub", run_id=f"{run_id}.sub")
        output = result.output
        out_ports = node.output_ports()
        if out_ports and isinstance(output, dict):
            return {p.name: output.get(p.name) for p in out_ports}
        return {out_port: output}

    @staticmethod
    def _map_entry_inputs(sub_def: WorkflowDef, bound_inputs: dict[str, Any]) -> dict[str, Any]:
        """Map bound inputs to a sub-workflow's orphaned in-port names.

        If the sub-workflow has exactly one orphaned input, all bound values
        are flattened into it (first non-sentinel). Otherwise, bound input port
        names are matched directly to sub-workflow input names.
        """
        from lamtools_core.runtime.workflow import _workflow_input_names  # local import; defined later
        input_names = _workflow_input_names(sub_def)
        # Flatten: pick first non-sentinel value for single-input sub-workflows.
        first_val: Any = None
        for v in bound_inputs.values():
            if v is not None and v != SKIP_SENTINEL:
                first_val = v
                break
        if len(input_names) <= 1 and input_names:
            return {input_names[0]: first_val}
        # Multi-input: match by name.
        result: dict[str, Any] = {}
        for name in input_names:
            # name is "{nodeId}.{portName}" — try matching port name.
            port_key = name.split(".", 1)[-1] if "." in name else name
            if port_key in bound_inputs:
                result[name] = bound_inputs[port_key]
            elif first_val is not None and name not in result:
                result[name] = first_val
        return result

    async def _execute_command(
        self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str
    ) -> dict[str, Any]:
        """command node: run a shell command (invoke CLI tools).

        Uses the same shell resolution as run_command (Git Bash on Windows),
        feeds bound inputs as stdin JSON + INPUT_<PORT> env vars, and splits
        JSON stdout to same-named output ports (else whole stdout to default).
        """
        raw = await self._run_command(node.config, bound_inputs, work_root)
        return self._split_or_fallback(node, raw)

    async def _run_command(
        self, cfg: dict[str, Any], bound_inputs: dict[str, Any], work_root: str
    ) -> str:
        command = str(cfg.get("command") or "")
        if not command:
            raise ValueError("command node requires config.command")
        cwd = str(cfg.get("cwd") or work_root or ".")
        env = dict(os.environ)
        extra_env = cfg.get("env") or {}
        if isinstance(extra_env, dict):
            env.update({str(k): str(v) for k, v in extra_env.items()})
        # Bind inputs as INPUT_<PORTNAME> env vars AND substitute ${VAR}/$VAR
        # tokens in the command ourselves — Windows cmd.exe does not expand
        # $VAR, so relying on the shell would break portability.
        substitutions: dict[str, str] = {}
        for name, value in bound_inputs.items():
            if value is None:
                continue
            env_name = f"INPUT_{name.upper()}"
            env[env_name] = str(value)
            substitutions[env_name] = str(value)
        command = _substitute_env_vars(command, substitutions)
        timeout = _as_float(cfg.get("timeout"), default=60.0)
        # Feed bound inputs as a JSON object on stdin ({port:val}) so a command
        # that wants structured input can read it; INPUT_<PORT> env vars + ${VAR}
        # substitution are a convenience for shells that prefer them.
        stdin_payload = json.dumps({"inputs": bound_inputs}, ensure_ascii=False, default=str).encode("utf-8")
        # Run the command through the SAME shell run_command uses
        # (resolve_command_shell → Git Bash on Windows), so command nodes behave
        # identically to the rest of the product. create_subprocess_shell would
        # otherwise fall back to COMSPEC (cmd.exe) on Windows, breaking bash
        # syntax (single quotes, pipes) the model may write.
        argv: list[str]
        if sys.platform == "win32":
            from lamtools_core.tool.command_runner import resolve_command_shell

            shell = resolve_command_shell()
            argv = shell.argv(command)
            # On a python.org install of Windows, `python3` resolves to the
            # Microsoft Store redirect stub (exits non-zero / opens Store).
            # Prepend a shim directory mapping python3 → the real interpreter
            # so model-written `python3 ...` commands actually run. This is a
            # platform-defect workaround, not behaviour fabrication.
            shim_dir = _python3_shim_dir()
            if shim_dir is not None:
                env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")
        else:
            argv = ["sh", "-lc", command]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(stdin_payload), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(f"shell command timed out after {timeout}s")
        text_out = stdout.decode("utf-8", errors="replace") if stdout else ""
        text_err = stderr.decode("utf-8", errors="replace") if stderr else ""
        if proc.returncode != 0:
            raise RuntimeError(
                f"shell command exited with code {proc.returncode}\nstderr:\n{text_err}"
            )
        return text_out.strip()

    async def _execute_script(
        self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str
    ) -> dict[str, Any]:
        """script node: Python binder. Runs the script via a generated runner
        that binds input-port names as locals and reads output-port names back;
        stdout JSON flows through _split_or_fallback to the output ports.
        """
        raw = await self._run_script(node, node.config, bound_inputs, work_root)
        return self._split_or_fallback(node, raw)

    async def _run_script(
        self, node: WorkflowNode, cfg: dict[str, Any], bound_inputs: dict[str, Any], work_root: str
    ) -> str:
        """Python binder: input/output PORT NAMES are program variables.

        The user's ``config.script`` is plain Python. Input-port names are
        available as variables (node ``IN x`` → ``x`` in code); assigning to an
        output-port name produces that output (``OUT y`` → ``y = ...``). No
        stdin parsing, no print, no JSON, no shell, no quoting — the model just
        writes ``y = x * 2``.

        Implementation: persist the user source to a real file under
        ``work_root/.lam/workflow_scripts/<nodeId>.py`` (config.script is the
        source of truth; rewritten only when its content hash changes), then
        run a generated ``<nodeId>.runner.py`` via ``sys.executable`` as an
        isolated subprocess. The runner binds inputs as locals, execs the user
        file (redirecting stray prints so they don't corrupt the output JSON),
        then prints a JSON object mapping each output-port name to its bound
        value. That stdout flows through ``_split_or_fallback`` unchanged.
        """
        import hashlib

        script = str(cfg.get("script") or "")
        if not script:
            raise ValueError("script node requires config.script")

        scripts_dir = Path(work_root or ".") / ".lam" / "workflow_scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        safe_id = "".join(c if c.isalnum() or c in {"-", "_"} else "_" for c in (node.id or "node")).strip("_") or "node"
        src_path = scripts_dir / f"{safe_id}.py"
        runner_path = scripts_dir / f"{safe_id}.runner.py"

        # Persist user source (rewrite only on content change).
        content_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()[:16]
        hash_path = scripts_dir / f"{safe_id}.hash"
        if not (src_path.exists() and hash_path.exists() and _read_hash(hash_path) == content_hash):
            src_path.write_text(script, encoding="utf-8")
            try:
                hash_path.write_text(content_hash, encoding="utf-8")
            except OSError:
                pass

        # Output port names drive the emitted JSON keys.
        out_port_names = [p.name for p in node.output_ports()]
        _write_runner(runner_path, src_path, out_port_names)

        cwd = str(cfg.get("cwd") or work_root or ".")
        timeout = _as_float(cfg.get("timeout"), default=60.0)
        # Inputs reach the user code as locals (via the runner reading stdin);
        # INPUT_<PORT> env vars are also set as a convenience.
        env = dict(os.environ)
        for name, value in bound_inputs.items():
            if value is None:
                continue
            env[f"INPUT_{name.upper()}"] = str(value)
        stdin_payload = json.dumps(bound_inputs, ensure_ascii=False, default=str).encode("utf-8")

        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(runner_path),
            cwd=cwd, env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(stdin_payload), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(f"script timed out after {timeout}s")
        text_out = stdout.decode("utf-8", errors="replace") if stdout else ""
        text_err = stderr.decode("utf-8", errors="replace") if stderr else ""
        if proc.returncode != 0:
            raise RuntimeError(f"script exited with code {proc.returncode}\nstderr:\n{text_err}")
        return text_out.strip()

    # -- streaming + cancel helpers ---------------------------------------

    def _cancel_event(self, thread_id: str) -> Any:
        if self.runtime_task_registry is None or not thread_id:
            return None
        try:
            return self.runtime_task_registry.get_cancel_event(thread_id)
        except Exception:  # noqa: BLE001 — registry optional
            return None

    async def _emit_state(
        self,
        node: WorkflowNode,
        status: RunItemStatus,
        thread_id: str,
        run_id: str,
        *,
        error: str = "",
    ) -> None:
        if self.emit is None:
            return
        event = RunItemEvent(
            kind="status",
            thread_id=thread_id,
            run_id=run_id,
            turn_id=run_id,
            item_id=node.id,
            status=status,
            payload={"node_id": node.id, "title": node.title, "kind": node.kind, "error": error} if error else {"node_id": node.id, "title": node.title, "kind": node.kind},
            source="workflow",
        )
        try:
            result = self.emit(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception:  # noqa: BLE001 — streaming must never break execution
            pass


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------


def _topological_order(workflow: WorkflowDef) -> list[str] | None:
    """Kahn's algorithm. Returns None if a cycle is detected."""
    incoming: dict[str, int] = {n.id: 0 for n in workflow.nodes}
    outgoing: dict[str, list[str]] = {n.id: [] for n in workflow.nodes}
    for edge in workflow.edges:
        if edge.source in incoming and edge.target in incoming:
            incoming[edge.target] += 1
            outgoing[edge.source].append(edge.target)
    queue = [nid for nid, count in incoming.items() if count == 0]
    order: list[str] = []
    while queue:
        current = queue.pop(0)
        order.append(current)
        for nxt in outgoing[current]:
            incoming[nxt] -= 1
            if incoming[nxt] == 0:
                queue.append(nxt)
    if len(order) != len(workflow.nodes):
        return None
    return order


def _feeding_edges(node: WorkflowNode, port_name: str, workflow: WorkflowDef) -> list[WorkflowEdge]:
    """All edges feeding a node's input port."""
    return [e for e in workflow.edges if e.target == node.id and e.target_port == port_name]


def _inputs_ready(node: WorkflowNode, workflow: WorkflowDef, values: dict[str, Any]) -> bool:
    """A port is ready when every edge feeding it has its source value in the
    table (multiple edges → all must be present). Orphaned ports are always
    ready (workflow input slot, seeded by the runner)."""
    for port in node.input_ports():
        edges = _feeding_edges(node, port.name, workflow)
        if not edges:
            continue  # orphaned → seeded by runner
        for edge in edges:
            key = f"{edge.source}.{edge.source_port}"
            if key not in values:
                return False
    return True


def _bind_inputs(node: WorkflowNode, workflow: WorkflowDef, values: dict[str, Any]) -> dict[str, Any]:
    """Bind input values from the value table.

    For each edge: if the edge has a ``condition`` (Python expression), it is
    evaluated against the *source node's* bound inputs (port names as locals).
    When False, the edge transmits ``SKIP_SENTINEL`` instead of the value, so
    downstream nodes on that path are skipped (cascade). ``transform`` and type
    coercion are applied as before. Multiple edges → values aggregated into a
    list. Orphaned ports read the ``__input__.{nodeId}.{portName}`` slot.
    """
    # Pre-compute each source node's bound inputs for edge condition evaluation.
    source_bound: dict[str, dict[str, Any]] = {}

    def _get_source_bound(src_id: str) -> dict[str, Any]:
        if src_id not in source_bound:
            src_node = workflow.node(src_id)
            source_bound[src_id] = _bind_inputs(src_node, workflow, values) if src_node else {}
        return source_bound[src_id]

    bound: dict[str, Any] = {}
    for port in node.input_ports():
        edges = _feeding_edges(node, port.name, workflow)
        if not edges:
            # Orphaned input port → workflow input slot.
            key = f"__input__.{node.id}.{port.name}"
            if key in values:
                bound[port.name] = _coerce_value(values[key], port.type)
        elif len(edges) == 1:
            edge = edges[0]
            key = f"{edge.source}.{edge.source_port}"
            if key in values:
                raw = values[key]
                # Edge condition: evaluate against source node's bound inputs.
                if edge.condition and not _eval_condition(edge.condition, _get_source_bound(edge.source)):
                    bound[port.name] = SKIP_SENTINEL
                else:
                    val = _apply_transform(raw, edge.transform)
                    bound[port.name] = _coerce_value(val, port.type)
        else:
            # Multiple edges → aggregate into a list (sentinels filtered).
            vals: list[Any] = []
            for edge in edges:
                key = f"{edge.source}.{edge.source_port}"
                if key in values:
                    raw = values[key]
                    if edge.condition and not _eval_condition(edge.condition, _get_source_bound(edge.source)):
                        continue  # edge blocked → skip this value
                    if raw is not None and raw != SKIP_SENTINEL:
                        vals.append(_coerce_value(_apply_transform(raw, edge.transform), port.type))
            bound[port.name] = vals
    return bound


def _apply_transform(value: Any, transform: str) -> Any:
    """Apply a JSONPath-style field path (``$.field`` or ``$.a.b``) to extract
    a sub-value. Empty or non-``$.`` transforms pass through unchanged."""
    if not transform or not transform.startswith("$."):
        return value
    path = transform[2:]
    if not path:
        return value
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.lstrip("-").isdigit():
            idx = int(part)
            value = value[idx] if -len(value) <= idx < len(value) else None
        else:
            return None
    return value


def _input_value_key(node: WorkflowNode, port_name: str, workflow: WorkflowDef) -> str | None:
    """Resolve the value-table key feeding a node's input port (first edge).

    Edge-bound ports read ``{source}.{source_port}``; an orphaned port (no
    edge feeds it) is a workflow input named ``{nodeId}.{portName}``, read
    from the ``__input__.{nodeId}.{portName}`` slot bound by the runner.

    .. deprecated:: retained for backward compat with single-edge lookups;
       prefer ``_feeding_edges`` + ``_bind_inputs`` for multi-edge support.
    """
    for edge in workflow.edges:
        if edge.target == node.id and edge.target_port == port_name:
            return f"{edge.source}.{edge.source_port}"
    return f"__input__.{node.id}.{port_name}"


def _default_output_port(node: WorkflowNode) -> str:
    outs = node.output_ports()
    if outs:
        return outs[0].name
    return ""


def _resolve_output(workflow: WorkflowDef, values: dict[str, Any]) -> Any:
    """Workflow output = the values on terminal output ports (out-ports with no
    outgoing edge). One terminal port → its value; several → a dict keyed by
    ``{nodeId}.{portName}``. Falls back to the legacy ``output_port`` spec."""
    outgoing = {f"{e.source}.{e.source_port}" for e in workflow.edges}
    terminal: dict[str, Any] = {}
    for node in workflow.nodes:
        for port in node.output_ports():
            key = f"{node.id}.{port.name}"
            if key not in outgoing:
                terminal[key] = values.get(key)
    if terminal:
        if len(terminal) == 1:
            return next(iter(terminal.values()))
        return terminal
    # Legacy output_port spec ("nodeId" or "nodeId.portName").
    spec = workflow.output_port.strip()
    if not spec:
        if not workflow.nodes:
            return None
        last = workflow.nodes[-1]
        port = _default_output_port(last)
        return values.get(f"{last.id}.{port}" if port else last.id)
    if "." in spec:
        return values.get(spec)
    node = workflow.node(spec)
    if node is None:
        return values.get(spec)
    port = _default_output_port(node)
    return values.get(f"{spec}.{port}" if port else spec)


# Mermaid-style map text. Each non-comment line is ``src.src_port[.type] ->
# tgt.tgt_port[.type]``; the optional type tokens are documentation only and
# ignored when reconstructing edges. Malformed lines are skipped so a single
# bad line never breaks the whole graph (folder-isolation design goal).
_MAP_LINE_RE = re.compile(
    r"^(\S+?)\.([^.>\s]+)(?:\.[^.>\s]+)?\s*->\s*(\S+?)\.([^.>\s]+)(?:\.[^.>\s]+)?\s*$"
)


def _parse_map(text: str) -> list[WorkflowEdge]:
    """Parse Mermaid-style edge text into a list of WorkflowEdge."""
    edges: list[WorkflowEdge] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _MAP_LINE_RE.match(line)
        if not m:
            continue
        src, sp, tgt, tp = m.groups()
        edges.append(
            WorkflowEdge(
                id=f"e-{src}-{sp}-{tgt}-{tp}",
                source=src,
                source_port=sp,
                target=tgt,
                target_port=tp,
            )
        )
    return edges


def _port_type(nodes_by_id: dict[str, WorkflowNode], node_id: str, port_name: str, direction: str) -> str:
    node = nodes_by_id.get(node_id)
    if node is None:
        return "any"
    for port in node.ports:
        if port.name == port_name and port.direction == direction:
            return port.type or "any"
    return "any"


def _serialize_map(edges: list[WorkflowEdge], nodes: list[WorkflowNode]) -> str:
    """Render edges as Mermaid-style ``src.port.type -> tgt.port.type`` text."""
    nodes_by_id: dict[str, WorkflowNode] = {n.id: n for n in nodes}
    lines: list[str] = []
    for e in edges:
        src_type = _port_type(nodes_by_id, e.source, e.source_port, "out")
        tgt_type = _port_type(nodes_by_id, e.target, e.target_port, "in")
        lines.append(f"{e.source}.{e.source_port}.{src_type} -> {e.target}.{e.target_port}.{tgt_type}")
    return "\n".join(lines)


def _workflow_input_names(workflow: WorkflowDef) -> list[str]:
    """Workflow input names: each node input port that no edge feeds (an
    orphaned in-port), named ``{nodeId}.{portName}``, plus the legacy
    ``input_params`` array (backward compatible)."""
    fed: set[tuple[str, str]] = {(e.target, e.target_port) for e in workflow.edges}
    names: list[str] = []
    seen: set[str] = set()
    for node in workflow.nodes:
        for port in node.input_ports():
            if (node.id, port.name) in fed:
                continue
            name = f"{node.id}.{port.name}"
            if name not in seen:
                seen.add(name)
                names.append(name)
    for param in workflow.input_params:
        if param.name and param.name not in seen:
            seen.add(param.name)
            names.append(param.name)
    return names


def _workflow_input_default(workflow: WorkflowDef, name: str) -> Any:
    for param in workflow.input_params:
        if param.name == name:
            return param.default
    return None


def _mark_cancelled(
    node_states: dict[str, WorkflowNodeState],
    workflow: WorkflowDef,
    order: list[str],
    from_index: int,
) -> None:
    for node_id in order[from_index:]:
        state = node_states.get(node_id)
        if state is not None and state.status == "idle":
            state.status = "cancelled"


def _as_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _summarize(value: Any) -> str:
    if isinstance(value, str):
        return value if len(value) <= 500 else value[:500] + "…"
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= 500 else text[:500] + "…"


def _substitute_env_vars(command: str, substitutions: dict[str, str]) -> str:
    """Replace ${VAR} and $VAR tokens in ``command`` with the given values.

    Shell-agnostic: Windows cmd.exe does not expand ``$VAR``, so we substitute
    the known INPUT_<PORT> variables ourselves before handing the command to the
    shell. Unknown ``$tokens`` are left untouched.
    """
    if not substitutions or not command:
        return command

    def _replace(match: re.Match[str]) -> str:
        name = match.group("braced") or match.group("plain")
        value = substitutions.get(name)
        if value is None:
            return match.group(0)
        return value

    return _VAR_TOKEN_RE.sub(_replace, command)


_PYTHON3_SHIM_DIR: str | None = None


def _python3_shim_dir() -> str | None:
    """Return a PATH dir mapping ``python3`` → the real interpreter on Windows.

    On a python.org install, ``python3`` is the Microsoft Store redirect stub
    (exits non-zero / pops the Store). We drop two tiny wrappers (``python3``
    and ``python3.exe``) into a temp dir and let callers prepend it to PATH so
    model-written ``python3 ...`` commands run. The wrappers exec
    ``sys.executable`` (the host's own interpreter), preserving argv. No-op on
    POSIX, where ``python3`` is the correct native name. Cached per process.
    """
    global _PYTHON3_SHIM_DIR
    if sys.platform != "win32":
        return None
    if _PYTHON3_SHIM_DIR is not None:
        return _PYTHON3_SHIM_DIR
    interpreter = sys.executable
    if not interpreter:
        return None
    # Bare wrapper (no extension) for sh/git-bash; .exe wrapper for cmd-style
    # resolution. Both exec the real interpreter, passing argv through.
    wrapper = (
        "#!/bin/sh\n"
        f'exec "{interpreter}" "$@"\n'
    )
    try:
        d = tempfile.mkdtemp(prefix="lamtools_py3shim_")
        Path(d, "python3").write_text(wrapper, encoding="utf-8")
        # Git Bash needs the bare script executable; mark it on POSIX.
        try:
            os.chmod(Path(d, "python3").as_posix(), 0o755)
        except OSError:
            pass
        # .exe not strictly required under bash (it finds the bare script),
        # but write a Windows-batch echo-through so direct .exe lookups resolve.
        Path(d, "python3.bat").write_text(
            f'@"{interpreter}" %*\r\n', encoding="utf-8"
        )
        _PYTHON3_SHIM_DIR = d
        return d
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Type system + shared helpers (LLM/Agent/Action executors, branch/loop)
# ---------------------------------------------------------------------------


def _read_hash(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _write_runner(runner_path: Path, user_file: Path, out_port_names: list[str]) -> None:
    """Write the binder runner that turns port-names-as-variables into JSON.

    Binds stdin inputs as locals, execs the user file (stray stdout captured so
    it can't corrupt the emitted JSON), then prints a JSON object mapping each
    output-port name to the value bound to that name in the user's namespace.
    Overwritten each run so out_port_names stay current with the node config.
    """
    import json as _json

    src_repr = repr(str(user_file))
    names_repr = repr(out_port_names)
    runner = (
        "import json, sys, io\n"
        "_IN = json.load(sys.stdin) if not sys.stdin.isatty() else {}\n"
        "_NS = dict(_IN); _NS.setdefault('__name__', '__main__')\n"
        "_buf = io.StringIO(); _real = sys.stdout; sys.stdout = _buf\n"
        "try:\n"
        f"    with open({src_repr}, 'r', encoding='utf-8') as _f:\n"
        f"        exec(compile(_f.read(), {src_repr}, 'exec'), _NS)\n"
        "finally:\n"
        "    sys.stdout = _real\n"
        f"_OUT = {{p: _NS.get(p) for p in {names_repr}}}\n"
        "print(json.dumps(_OUT, default=str))\n"
    )
    runner_path.write_text(runner, encoding="utf-8")


def _io_to_port_dicts(inputs: Any, outputs: Any) -> list[dict[str, Any]]:
    """Merge separate ``inputs[]``/``outputs[]`` arrays into ``ports[]`` dicts.

    Folder-layout node JSON stores inputs/outputs apart; the runtime model uses
    a single ``ports`` list tagged with ``direction``. Each entry keeps its
    ``value`` (content node constants) when present.
    """
    ports: list[dict[str, Any]] = []
    if isinstance(inputs, list):
        for item in inputs:
            if isinstance(item, dict):
                ports.append({**item, "direction": "in"})
    if isinstance(outputs, list):
        for item in outputs:
            if isinstance(item, dict):
                ports.append({**item, "direction": "out"})
    return ports


def _ports_to_io(node: WorkflowNode) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a node's ports into ``inputs[]``/``outputs[]`` dicts for storage."""
    inputs: list[dict[str, Any]] = []
    for p in node.input_ports():
        inputs.append({"name": p.name, "type": p.type, "description": p.description})
    outputs: list[dict[str, Any]] = []
    for p in node.output_ports():
        entry: dict[str, Any] = {"name": p.name, "type": p.type, "description": p.description}
        if p.value is not None:
            entry["value"] = p.value
        outputs.append(entry)
    return inputs, outputs


def _normalise_type(type_name: str) -> str:
    t = (type_name or "any").strip().lower()
    aliases = {"text": "string", "str": "string", "int": "number", "integer": "number", "float": "number", "bool": "boolean", "dict": "object", "list": "array"}
    return aliases.get(t, t) if t in aliases or t in _WORKFLOW_TYPES else "any"


def _types_compatible(src: str, dst: str) -> bool:
    """True when a value of type ``src`` may flow into a port of type ``dst``.

    Same type, either side ``any``, or number/boolean -> string are accepted.
    """
    s = _normalise_type(src)
    d = _normalise_type(dst)
    if s == "any" or d == "any" or s == d:
        return True
    if s in {"number", "boolean"} and d == "string":
        return True
    return False


def _coerce_value(value: Any, target_type: str) -> Any:
    """Best-effort coercion of a value to ``target_type``; failures keep the
    original value (runtime never aborts on coercion). Sentinels pass through."""
    if value is None or value == SKIP_SENTINEL:
        return value
    t = _normalise_type(target_type)
    if t == "any":
        return value
    try:
        if t == "string":
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        if t == "number":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return value
            return float(value)
        if t == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                low = value.strip().lower()
                if low in {"true", "1", "yes", "y"}:
                    return True
                if low in {"false", "0", "no", "n", ""}:
                    return False
            return bool(value)
        if t in {"object", "array"}:
            if isinstance(value, (dict, list)):
                return value
            return json.loads(value)
    except (TypeError, ValueError):
        return value
    return value


def _json_object(content: str) -> dict[str, Any] | None:
    """Parse a JSON object from model/shell output, tolerating ```json fences."""
    candidate = (content or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    try:
        value = json.loads(candidate)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _eval_condition(expr: str, bound_inputs: dict[str, Any]) -> bool:
    """Evaluate a Python expression condition.

    ``bound_inputs`` (port name → value) are injected as local variables so
    expressions like ``len(text) > 100`` or ``quality >= 0.8 and source in
    ['A','B']`` work naturally. A restricted set of builtins (``len``, ``str``,
    ``int``, ``float``, ``bool``, ``any``, ``all``, ``min``, ``max``, ``sum``,
    ``abs``, ``round``, ``isinstance``) is available. Empty/missing condition →
    always True (execute). Evaluation errors → False (skip).

    Trust boundary: conditions are written by the workflow author, who can
    already run arbitrary shell/Python nodes, so ``eval`` here is not a
    security boundary (audit 07 S4). As defensive hardening, any attribute
    access on a name starting with ``_`` is rejected, which blocks the classic
    ``x.__class__.__mro__...`` sandbox-escape chain while allowing benign
    method calls like ``text.strip()``.
    """
    if not expr or not str(expr).strip():
        return True
    source = str(expr).strip()
    try:
        tree = ast.parse(source, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                return False
        return bool(eval(source, {"__builtins__": _CONDITION_BUILTINS}, dict(bound_inputs)))  # noqa: S307 — trusted user-authored workflow condition
    except Exception:
        return False


__all__ = [
    "NodeStateStatus",
    "PortDirection",
    "SKIP_SENTINEL",
    "WorkflowDef",
    "WorkflowEdge",
    "WorkflowInputParam",
    "WorkflowManager",
    "WorkflowNode",
    "WorkflowNodeKind",
    "WorkflowNodeState",
    "WorkflowPort",
    "WorkflowRunResult",
    "WorkflowRunner",
]
