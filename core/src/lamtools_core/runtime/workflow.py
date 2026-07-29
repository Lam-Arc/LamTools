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
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from lamtools_core.event.run_item import RunItemEvent, RunItemStatus


WorkflowNodeKind = Literal["llm", "agent", "action"]
ActionKind = Literal["shell", "script", "http", "file-data"]
PortDirection = Literal["in", "out"]
NodeStateStatus = Literal["idle", "running", "done", "error", "skipped", "cancelled"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class WorkflowPort:
    """A typed, named port on a node. Data flows out -> in along edges."""

    name: str
    type: str = "any"  # free-form type name; "any" matches anything
    direction: PortDirection = "in"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "direction": self.direction,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkflowPort":
        return cls(
            name=str(value.get("name") or ""),
            type=str(value.get("type") or "any"),
            direction="out" if str(value.get("direction") or "in") == "out" else "in",
            description=str(value.get("description") or ""),
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
        ports_raw = value.get("ports") or []
        return cls(
            id=str(value.get("id") or ""),
            kind=str(value.get("kind") or "action"),  # type: ignore[arg-type]
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
    """A connection from a source output port to a target input port."""

    id: str
    source: str  # node id
    source_port: str
    target: str  # node id
    target_port: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "source_port": self.source_port,
            "target": self.target,
            "target_port": self.target_port,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkflowEdge":
        return cls(
            id=str(value.get("id") or _new_id("edge")),
            source=str(value.get("source") or ""),
            source_port=str(value.get("source_port") or ""),
            target=str(value.get("target") or ""),
            target_port=str(value.get("target_port") or ""),
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
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.llm_client = llm_client
        self.sub_agent_runner = sub_agent_runner
        self.emit = emit
        self.runtime_task_registry = runtime_task_registry
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
    ) -> WorkflowRunResult:
        """Run the workflow.

        ``max_steps=None`` runs to completion (整跑); an integer runs at most
        that many *ready* nodes then returns ``status="paused"`` (单步调试).
        ``prior_values`` / ``prior_node_states`` resume a paused run.
        """
        inputs = dict(inputs or {})
        work_root = work_root or workflow.work_root
        run_id = run_id or _new_id("wfrun")
        thread_id = thread_id or f"workflow_thread_{uuid.uuid4().hex}"

        order = _topological_order(workflow)
        if order is None:
            return WorkflowRunResult(status="failed", error="workflow graph has a cycle", run_id=run_id)

        values: dict[str, Any] = dict(prior_values or {})
        # Bind workflow inputs under the __input__ namespace.
        for param in workflow.input_params:
            key = f"__input__.{param.name}"
            if param.name in inputs:
                values[key] = inputs[param.name]
            elif key not in values:
                values[key] = param.default

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
            await self._emit_state(node, "running", thread_id, run_id)
            state.status = "running"
            state.started_at = self.clock()

            try:
                outputs = await self._execute_with_retries(node, bound_inputs, work_root, state)
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
                state.status = "error"
                state.error = str(exc) or type(exc).__name__
                state.finished_at = self.clock()
                await self._emit_state(node, "failed", thread_id, run_id, error=state.error)
                return WorkflowRunResult(
                    status="failed",
                    node_states=node_states,
                    values=values,
                    error=f"Node '{node.title or node.id}' failed: {state.error}",
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
    ) -> dict[str, Any]:
        retries = _as_int(node.config.get("retries"), default=0)
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            state.attempts = attempt + 1
            try:
                if node.kind == "llm":
                    return await self._execute_llm(node, bound_inputs, work_root)
                if node.kind == "agent":
                    return await self._execute_agent(node, bound_inputs, work_root)
                return await self._execute_action(node, bound_inputs, work_root)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — retry boundary
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(0.1 * (attempt + 1))
        raise last_exc if last_exc is not None else RuntimeError("node execution failed")

    async def _execute_llm(
        self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str
    ) -> dict[str, Any]:
        cfg = node.config
        instruction = str(cfg.get("instruction") or cfg.get("system_prompt") or "")
        output_format_text = str(cfg.get("output_format_text") or "")
        output_format_schema = cfg.get("output_format_schema")
        mode = str(cfg.get("mode") or "single")
        allow_tools = bool(cfg.get("allow_tools", False))
        allowed_tools = cfg.get("allowed_tools") or []
        model_id = str(cfg.get("model_id") or "")
        temperature = cfg.get("temperature")
        reasoning_effort = str(cfg.get("reasoning_effort") or "")
        max_tokens = cfg.get("max_tokens")
        top_p = cfg.get("top_p")

        if self.llm_client is None:
            raise RuntimeError("LLM node requires an LLM client (none configured)")
        from lamtools_core.llm import ChatMessage, LLMRequest

        system_parts: list[str] = [instruction]
        if output_format_text:
            system_parts.append(f"Output format:\n{output_format_text}")
        system_prompt = "\n\n".join(p for p in system_parts if p).strip()

        # Turn bound inputs + prior values into a user message describing context.
        context_lines = [f"- {k}: {_summarize(v)}" for k, v in bound_inputs.items() if v is not None]
        user_content = "\n".join(context_lines) if context_lines else "(no additional input)"

        messages: list[ChatMessage] = []
        if system_prompt:
            messages.append(ChatMessage(role="system", content=system_prompt))
        messages.append(ChatMessage(role="user", content=user_content))

        response_format = output_format_schema if isinstance(output_format_schema, dict) and output_format_schema else None

        if mode == "loop":
            max_iter = max(1, _as_int(cfg.get("loop_max_iterations"), default=3))
            return await self._run_llm_loop(
                messages=messages,
                model_id=model_id,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                max_tokens=max_tokens,
                top_p=top_p,
                response_format=response_format,
                max_iter=max_iter,
                node=node,
                allow_tools=allow_tools,
                allowed_tools=allowed_tools,
            )

        request = LLMRequest(
            messages=messages,
            model=model_id,
            temperature=float(temperature) if temperature is not None else None,
            max_tokens=int(max_tokens) if max_tokens is not None else None,
            top_p=float(top_p) if top_p is not None else None,
            response_format=response_format,
            metadata={"reasoning_effort": reasoning_effort} if reasoning_effort else {},
        )
        response = await self.llm_client.complete(request)
        out_port = _default_output_port(node) or "output"
        return {out_port: response.content}

    async def _run_llm_loop(
        self,
        *,
        messages: list[Any],
        model_id: str,
        temperature: Any,
        reasoning_effort: str,
        max_tokens: Any,
        top_p: Any,
        response_format: dict[str, Any] | None,
        max_iter: int,
        node: WorkflowNode,
        allow_tools: bool,
        allowed_tools: list[Any],
    ) -> dict[str, Any]:
        from lamtools_core.llm import ChatMessage, LLMRequest

        # Simple self-judging loop: each iteration the model decides whether to
        # continue. We ask it to prefix the final answer with "[DONE]". This is
        # the LLM-node loop (distinct from the Agent node's full sub-agent loop).
        transcript = list(messages)
        last_content = ""
        for _ in range(max_iter):
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
            if "[DONE]" in last_content:
                last_content = last_content.replace("[DONE]", "").strip()
                break
            transcript.append(ChatMessage(role="assistant", content=last_content))
            transcript.append(
                ChatMessage(role="user", content="If the result is final, prefix your next message with [DONE]. Otherwise continue refining.")
            )
        out_port = _default_output_port(node) or "output"
        return {out_port: last_content}

    async def _execute_agent(
        self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str
    ) -> dict[str, Any]:
        cfg = node.config
        goal = str(cfg.get("instruction") or cfg.get("goal") or "")
        context_lines = [f"- {k}: {_summarize(v)}" for k, v in bound_inputs.items() if v is not None]
        task = goal + ("\n\nContext:\n" + "\n".join(context_lines) if context_lines else "")
        if self.sub_agent_runner is None:
            raise RuntimeError("Agent node requires a sub_agent_runner (none configured)")
        result = await self.sub_agent_runner.run(task=task)
        out_port = _default_output_port(node) or "output"
        # SubAgentRunResult exposes .content / .final_message
        content = getattr(result, "content", None) or getattr(result, "final_message", None) or ""
        return {out_port: content}

    async def _execute_action(
        self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str
    ) -> dict[str, Any]:
        cfg = node.config
        action_type = str(cfg.get("action_type") or "shell")
        out_port = _default_output_port(node) or "output"
        if action_type == "shell":
            return {out_port: await self._action_shell(cfg, bound_inputs, work_root)}
        if action_type == "script":
            return {out_port: await self._action_script(cfg, bound_inputs, work_root)}
        if action_type == "http":
            return {out_port: await self._action_http(cfg, bound_inputs)}
        if action_type == "file-data":
            return {out_port: await self._action_file_data(cfg, bound_inputs, work_root)}
        raise ValueError(f"unsupported action_type: {action_type}")

    async def _action_shell(
        self, cfg: dict[str, Any], bound_inputs: dict[str, Any], work_root: str
    ) -> str:
        command = str(cfg.get("command") or "")
        if not command:
            raise ValueError("shell action requires a command")
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
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
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

    async def _action_script(
        self, cfg: dict[str, Any], bound_inputs: dict[str, Any], work_root: str
    ) -> str:
        language = str(cfg.get("language") or "python").lower()
        script = str(cfg.get("script") or "")
        if not script:
            raise ValueError("script action requires script content")
        runner = {"python": sys.executable, "python3": sys.executable, "js": "node", "node": "node", "javascript": "node"}.get(language)
        if runner is None:
            raise ValueError(f"unsupported script language: {language}")
        suffix = ".py" if language in {"python", "python3"} else ".js"
        stdin_payload = json.dumps({"inputs": bound_inputs}, ensure_ascii=False, default=str)
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as fh:
            fh.write(script)
            script_path = fh.name
        try:
            proc = await asyncio.create_subprocess_exec(
                runner,
                script_path,
                cwd=str(cfg.get("cwd") or work_root or "."),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            timeout = _as_float(cfg.get("timeout"), default=60.0)
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(stdin_payload.encode("utf-8")), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                raise RuntimeError(f"script timed out after {timeout}s")
            text_out = stdout.decode("utf-8", errors="replace") if stdout else ""
            text_err = stderr.decode("utf-8", errors="replace") if stderr else ""
            if proc.returncode != 0:
                raise RuntimeError(f"script exited with code {proc.returncode}\nstderr:\n{text_err}")
            return text_out.strip()
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    async def _action_http(self, cfg: dict[str, Any], bound_inputs: dict[str, Any]) -> str:
        url = str(cfg.get("url") or "")
        if not url:
            raise ValueError("http action requires a url")
        method = str(cfg.get("method") or "GET").upper()
        headers = dict(cfg.get("headers") or {})
        body = cfg.get("body")
        if body is None and bound_inputs:
            body = json.dumps(bound_inputs, ensure_ascii=False, default=str)
            headers.setdefault("Content-Type", "application/json")
        timeout = _as_float(cfg.get("timeout"), default=30.0)
        data = body.encode("utf-8") if isinstance(body, str) else (json.dumps(body).encode("utf-8") if body is not None else None)
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — user-authored URL
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise RuntimeError(f"HTTP {exc.code} {exc.reason}\n{detail}") from exc

    async def _action_file_data(
        self, cfg: dict[str, Any], bound_inputs: dict[str, Any], work_root: str
    ) -> Any:
        op = str(cfg.get("operation") or cfg.get("op") or "read").lower()
        path = cfg.get("path") or ""
        base = Path(work_root or ".")
        target = Path(str(path)) if path else None
        if target is not None and not target.is_absolute():
            target = base / target
        if op == "read":
            if target is None:
                raise ValueError("file-data read requires a path")
            return target.read_text(encoding="utf-8", errors="replace")
        if op == "write":
            if target is None:
                raise ValueError("file-data write requires a path")
            content = cfg.get("content")
            if content is None and bound_inputs:
                content = next(iter(bound_inputs.values()))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(content), encoding="utf-8")
            return f"wrote {len(str(content))} bytes to {target}"
        if op in {"json_get", "json_set", "transform"}:
            # Minimal JSON transform: read a JSON file, optionally set a key.
            if target is None:
                raise ValueError("file-data transform requires a path")
            data = json.loads(target.read_text(encoding="utf-8", errors="replace") or "null")
            if op == "json_set":
                key = str(cfg.get("key") or "")
                value = cfg.get("value")
                if value is None and bound_inputs:
                    value = next(iter(bound_inputs.values()))
                if key:
                    data[key] = value
                target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                return data
            return data
        raise ValueError(f"unsupported file-data operation: {op}")

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


def _inputs_ready(node: WorkflowNode, workflow: WorkflowDef, values: dict[str, Any]) -> bool:
    for port in node.input_ports():
        key = _input_value_key(node, port.name, workflow)
        if key is None or key not in values:
            return False
    return True


def _bind_inputs(node: WorkflowNode, workflow: WorkflowDef, values: dict[str, Any]) -> dict[str, Any]:
    bound: dict[str, Any] = {}
    for port in node.input_ports():
        key = _input_value_key(node, port.name, workflow)
        if key is not None and key in values:
            bound[port.name] = values[key]
    return bound


def _input_value_key(node: WorkflowNode, port_name: str, workflow: WorkflowDef) -> str | None:
    """Resolve the value-table key feeding a node's input port.

    Edge-bound ports read ``{source}.{source_port}``; unbound ports fall back to
    a workflow input of the same name (``__input__.{name}``).
    """
    for edge in workflow.edges:
        if edge.target == node.id and edge.target_port == port_name:
            return f"{edge.source}.{edge.source_port}"
    if any(p.name == port_name for p in workflow.input_params):
        return f"__input__.{port_name}"
    return None


def _default_output_port(node: WorkflowNode) -> str:
    outs = node.output_ports()
    if outs:
        return outs[0].name
    return ""


def _resolve_output(workflow: WorkflowDef, values: dict[str, Any]) -> Any:
    spec = workflow.output_port.strip()
    if not spec:
        # Default: the last node's default output.
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
    if not substitutions:
        return command
    result = command
    # ${VAR} form first (longer token), then $VAR form.
    for var, value in substitutions.items():
        result = result.replace("${" + var + "}", value)
    for var, value in substitutions.items():
        result = result.replace("$" + var, value)
    return result


__all__ = [
    "ActionKind",
    "NodeStateStatus",
    "PortDirection",
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
