"""Workflow graph and run-state models, including durable/public serialization."""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

# user:“审查后端大文件并拆分”+(按职责独立维护实现，原模块保留导入入口以兼容现有调用。)

# Node kinds remain open registry identifiers so trusted plugin kinds round-trip.
WorkflowNodeKind = str
PortDirection = Literal["in", "out"]
NodeStateStatus = Literal["idle", "running", "waiting", "done", "error", "skipped", "cancelled"]

_PUBLIC_PRIVATE_KEYS = {
    "password", "passwd", "secret", "secrets", "token", "access_token",
    "refresh_token", "id_token", "api_key", "apikey", "private_key",
    "client_secret", "authorization", "cookie", "resume_token",
    "continuation_token", "runtime_credentials", "credential_secret",
}

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


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


def _as_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


def ensure_workflow_id(definition: "WorkflowDef", *, seed: str = "") -> str:
    """Assign and return the stable identity of a workflow.

    New definitions receive a UUID.  Legacy files are given a deterministic
    UUID by the store, using their resolved path as the seed, so merely
    reading an old workflow never changes the session it is bound to.
    """
    if definition.id:
        return definition.id
    if seed:
        definition.id = uuid.uuid5(uuid.NAMESPACE_URL, seed).hex
    else:
        definition.id = uuid.uuid4().hex
    return definition.id


@dataclass
class WorkflowPort:
    """A typed, named port on a node. Data flows out -> in along edges.

    ``value`` holds a constant for ``content`` node output ports (each port
    carries its own value); it is unused for other kinds.
    """

    name: str
    # Stable identity is separate from the display/binding name.  Legacy
    # definitions receive a deterministic id in WorkflowNode.from_dict.
    id: str = ""
    type: str = "any"  # free-form type name; "any" matches anything
    direction: PortDirection = "in"
    description: str = ""
    value: Any = None
    # A lazy input is handed to trusted plugin executors as ``LazyInput``.
    # Built-in executors resolve it at their service boundary.
    lazy: bool = False

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "direction": self.direction,
            "description": self.description,
        }
        if self.value is not None:
            data["value"] = self.value
        if self.lazy:
            data["lazy"] = True
        return data

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkflowPort":
        return cls(
            name=str(value.get("name") or ""),
            id=str(value.get("id") or value.get("port_id") or value.get("portId") or ""),
            type=str(value.get("type") or "any"),
            direction="out" if str(value.get("direction") or "in") == "out" else "in",
            description=str(value.get("description") or ""),
            value=value.get("value"),
            lazy=bool(value.get("lazy", value.get("is_lazy", value.get("isLazy", False)))),
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
    type_id: str = ""
    type_version: int = 1
    # Canvas-only container relationship.  It is intentionally kept out of
    # the executable node config/prompt; V2 documents persist it under
    # ``canvas.node_views[node_id].parent_id``.
    parent_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "config": _json_copy(self.config),
            "ports": [p.to_dict() for p in self.ports],
            "position": dict(self.position),
            "type_id": self.type_id or self.kind,
            "type_version": self.type_version,
        }
        if self.parent_id:
            data["parent_id"] = self.parent_id
        return data

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
        node_id = str(value.get("id") or "")
        ports = [WorkflowPort.from_dict(p) for p in ports_raw if isinstance(p, dict)]
        for port in ports:
            if not port.id:
                port.id = f"port_{uuid.uuid5(uuid.NAMESPACE_URL, f'{node_id}\x1f{port.direction}\x1f{port.name}').hex[:16]}"
        raw_parent_id = value["parent_id"] if "parent_id" in value else value.get("parentId")
        parent_id = str(raw_parent_id).strip() if raw_parent_id is not None and str(raw_parent_id).strip() else None
        return cls(
            id=node_id,
            kind=raw_kind,  # type: ignore[arg-type]
            title=str(value.get("title") or ""),
            config=dict(value.get("config") or {}),
            ports=ports,
            position={k: float(v) for k, v in (value.get("position") or {}).items()} if isinstance(value.get("position"), dict) else {},
            parent_id=parent_id,
            type_id=str(value.get("type_id") or value.get("typeId") or raw_kind),
            type_version=max(1, _as_int(value.get("type_version", value.get("typeVersion")), default=1)),
        )

    def input_ports(self) -> list[WorkflowPort]:
        return [p for p in self.ports if p.direction == "in"]

    def output_ports(self) -> list[WorkflowPort]:
        return [p for p in self.ports if p.direction == "out"]


@dataclass
class WorkflowEdge:
    """A connection from a source output port to a target input port.

    ``transform`` is an optional JSONPath-style field path (``$.field`` or
    ``$.a.b``), or a versioned expression AST, applied to the upstream value
    before it reaches the target. ``condition`` may likewise be a safe AST;
    legacy strings remain Python conditions evaluated against the upstream
    node's bound inputs (port names as locals). When false, the edge transmits
    ``SKIP_SENTINEL`` so downstream nodes on that path are skipped (cascade).
    Both default to empty (pass-through / always).
    """

    id: str
    source: str  # node id
    source_port: str
    target: str  # node id
    target_port: str
    source_port_id: str = ""
    target_port_id: str = ""
    # Structured expression ASTs are accepted alongside legacy strings.  The
    # wire model must retain dictionaries rather than coercing them to text so
    # runtime can route them through the safe evaluator.
    transform: Any = ""
    condition: Any = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "source": self.source,
            "source_port": self.source_port,
            "target": self.target,
            "target_port": self.target_port,
        }
        if self.source_port_id:
            data["source_port_id"] = self.source_port_id
        if self.target_port_id:
            data["target_port_id"] = self.target_port_id
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
            source_port_id=str(value.get("source_port_id") or value.get("sourcePortId") or ""),
            target_port_id=str(value.get("target_port_id") or value.get("targetPortId") or ""),
            transform=value.get("transform") or "",
            condition=value.get("condition") or "",
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
    # Stable resource identity.  The display/file name may change during a
    # rename; sessions and run events bind to this id instead.
    id: str = ""
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
    revision: int = 0
    # Canonical editable V2 document.  It is deliberately excluded from the
    # legacy to_dict payload; document APIs expose it explicitly.
    document: dict[str, Any] | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
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
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkflowDef":
        return cls(
            name=str(value.get("name") or ""),
            id=str(value.get("id") or value.get("workflow_id") or ""),
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
            revision=max(0, _as_int(value.get("revision"), default=0)),
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
    # The in-flight attempt identity survives interruption.  Recovery reuses
    # its idempotency key instead of inventing a second side-effect identity.
    attempt_id: str = ""
    idempotency_key: str = ""
    wait_descriptor: dict[str, Any] = field(default_factory=dict)
    # Cache facts are part of the durable node state so a UI/CLI can explain
    # whether a result was reused.  ``bypass`` means the node did not declare
    # both pure and deterministic semantics.
    cache_status: str = "bypass"
    cache_key: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Stable, secret-safe execution evidence for run inspectors.  This is
    # intentionally summary metadata: never provider reasoning, raw prompts,
    # credentials, or bearer tokens.
    attempt_history: list[dict[str, Any]] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "attempts": self.attempts,
            "attempt_id": self.attempt_id,
            "idempotency_key": self.idempotency_key,
            "wait_descriptor": _json_copy(self.wait_descriptor),
            "cache_status": self.cache_status,
            "cache_key": self.cache_key,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "attempt_history": _json_copy(self.attempt_history),
            "audit": _json_copy(self.audit),
        }

    def to_public_dict(self) -> dict[str, Any]:
        return public_workflow_value(self.to_dict())

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, node_id: str = "") -> "WorkflowNodeState":
        status = str(value.get("status") or "idle")
        if status == "completed":
            status = "done"
        if status == "failed":
            status = "error"
        if status not in {"idle", "running", "waiting", "done", "error", "skipped", "cancelled"}:
            status = "idle"
        return cls(
            node_id=str(value.get("node_id") or value.get("nodeId") or node_id),
            status=status,  # type: ignore[arg-type]
            output=value.get("output"), error=str(value.get("error") or ""),
            attempts=max(0, _as_int(value.get("attempts"), default=0)),
            attempt_id=str(value.get("attempt_id") or value.get("attemptId") or ""),
            idempotency_key=str(value.get("idempotency_key") or value.get("idempotencyKey") or ""),
            wait_descriptor=dict(value.get("wait_descriptor") or value.get("waitDescriptor") or {}),
            cache_status=str(value.get("cache_status") or value.get("cache") or "bypass"),
            cache_key=str(value.get("cache_key") or value.get("cacheKey") or ""),
            started_at=_parse_dt(value.get("started_at") or value.get("startedAt")),
            finished_at=_parse_dt(value.get("finished_at") or value.get("finishedAt")),
            attempt_history=[
                dict(item) for item in (value.get("attempt_history") or value.get("attemptHistory") or [])
                if isinstance(item, Mapping)
            ],
            audit=dict(value.get("audit") or {}),
        )


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
    workflow_id: str = ""
    workflow_revision: int = 0
    definition_digest: str = ""
    wait_descriptor: dict[str, Any] = field(default_factory=dict)
    steps_remaining: int = 0
    # Per-node cache facts.  Values mirror ``WorkflowNodeState`` for callers
    # that need run-level aggregation without walking node states.
    cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "output": self.output,
            "node_states": {k: v.to_dict() for k, v in self.node_states.items()},
            "values": _json_copy(self.values),
            "error": self.error,
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_revision": self.workflow_revision,
            "definition_digest": self.definition_digest,
            "wait_descriptor": _json_copy(self.wait_descriptor),
            "steps_remaining": self.steps_remaining,
            "cache": _json_copy(self.cache),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }

    def to_public_dict(self) -> dict[str, Any]:
        """Return the RPC/event view without credentials or resume bearers."""
        result = self.to_dict()
        result["node_states"] = {
            key: state.to_public_dict() for key, state in self.node_states.items()
        }
        return public_workflow_value(result)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkflowRunResult":
        states = {
            str(node_id): WorkflowNodeState.from_dict(raw, node_id=str(node_id))
            for node_id, raw in (value.get("node_states") or {}).items()
            if isinstance(raw, dict)
        }
        return cls(
            status=str(value.get("status") or "completed"),  # type: ignore[arg-type]
            output=value.get("output"), node_states=states,
            values=dict(value.get("values") or {}), error=str(value.get("error") or ""),
            run_id=str(value.get("run_id") or ""),
            workflow_id=str(value.get("workflow_id") or value.get("workflowId") or ""),
            workflow_revision=max(0, _as_int(value.get("workflow_revision", value.get("workflowRevision")), default=0)),
            definition_digest=str(value.get("definition_digest") or value.get("definitionDigest") or ""),
            wait_descriptor=dict(value.get("wait_descriptor") or value.get("waitDescriptor") or {}),
            steps_remaining=_as_int(value.get("steps_remaining"), default=0),
            cache={str(key): dict(raw) for key, raw in (value.get("cache") or {}).items() if isinstance(raw, dict)},
            started_at=_parse_dt(value.get("started_at")),
            finished_at=_parse_dt(value.get("finished_at")),
        )


def _public_key(value: Any) -> str:
    text = str(value).strip().replace("-", "_")
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text).lower()


def _is_private_public_key(normalized: str) -> bool:
    if normalized in _PUBLIC_PRIVATE_KEYS or normalized.endswith(
        ("_password", "_secret", "_token", "_api_key")
    ):
        return True
    if normalized in {
        "reasoning", "reasoning_content", "thinking", "thought", "thoughts",
        "chain_of_thought", "chainofthought", "cot", "hidden_reasoning",
        "internal_reasoning", "analysis", "analysis_content", "thought_signature",
    }:
        return True
    return (
        normalized.startswith(("reasoning_", "thinking_", "analysis_", "chain_of_thought_"))
        or normalized.endswith(("_reasoning", "_thinking", "_analysis", "_chain_of_thought"))
    )


def public_workflow_value(value: Any) -> Any:
    """Copy a public run/event value while removing bearer and secret fields."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            name = str(key)
            normalized = _public_key(name)
            if _is_private_public_key(normalized):
                continue
            result[name] = public_workflow_value(nested)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [public_workflow_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
