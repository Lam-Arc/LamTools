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
import hashlib
import inspect
import json
import math
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from lamtools_core.event.run_item import RunItemEvent, RunItemStatus

from .cache import WorkflowContentCache, WorkflowCacheLookup, content_signature
from .adapters import (
    AgentInvoker,
    AgentInvokerAdapter,
    LLMInvoker,
    LegacyLLMAdapter,
    LegacyAgentInvokerAdapter,
    LegacyModelInvokerAdapter,
    LegacySubAgentAdapter,
    LegacyNodeExecutorAdapter,
    ModelInvokerAdapter,
    ModelInvoker,
    NodeExecutor,
    NodeExecutorAdapter,
    SubAgentInvoker,
    SubAgentInvokerAdapter,
    adapt_agent_invoker,
    adapt_data_packet,
    adapt_model_invoker,
    adapt_node_executor,
)
from .executors import (
    DynamicNodeExpansion,
    Expansion,
    NodeExecutionResult,
    WorkflowExpansion,
    WorkflowDynamicExpansion,
    WorkflowExpansionError,
    WorkflowExecutorError,
    WorkflowExecutorRegistry,
    WorkflowNodeExecutionResult,
    normalize_execution_result,
    normalize_node_result,
    normalize_node_execution_result,
)
from .registry import WorkflowNodeRegistry
from .credentials import CredentialError, CredentialRef, is_credential_ref
from .data_packet import WorkflowDataPacket, is_data_packet, packet_to_legacy
from .snapshots import WorkflowSnapshotStore
from .durable import (
    NodeExecutionPolicy,
    WorkflowRunEvent,
    WorkflowRunEventStore,
    attempt_identity,
    definition_digest,
)
from .claims import WorkflowClaimStore, claim_store_for_runtime
from .flow_control import (
    FlowControlDecision,
    FlowControlLease,
    FlowControlPolicy,
    FlowControlStore,
    stable_scope_key,
)
from .expressions import (
    Expression,
    ExpressionContext,
    ExpressionError,
    evaluate as evaluate_expression,
)


# Node kinds are registry identifiers, not a closed enum.  Keeping this alias
# open is what lets a saved graph retain trusted plugin types without a runtime
# release for every new node (the historical five names remain registered).
WorkflowNodeKind = str
_BUILTIN_EXECUTORS = {
    "ai", "model", "agent", "command", "script", "content", "subgraph",
    "passthrough", "template", "condition", "merge", "join", "wait_event", "approval",
}
PortDirection = Literal["in", "out"]
NodeStateStatus = Literal["idle", "running", "waiting", "done", "error", "skipped", "cancelled"]

# Coordination is process-local by design.  Keys include durable-store
# identity so distinct WorkflowRunner instances serving the same local store
# share one signal claim without serializing unrelated projects/runs.
_PROCESS_SIGNAL_LOCKS: dict[tuple[str, str, str], asyncio.Lock] = {}
_PROCESS_SIGNAL_LOCK_USERS: dict[tuple[str, str, str], int] = {}
_PROCESS_RUN_LOCKS: dict[tuple[str, str, str], asyncio.Lock] = {}
_PROCESS_RUN_LOCK_USERS: dict[tuple[str, str, str], int] = {}


@dataclass(frozen=True)
class WorkflowExecutionContext:
    """Host correlation and authority carried across every workflow boundary.

    The context is the one propagation object shared by AI/Agent nodes,
    nested workflows, and workflow-as-tool calls.  New fields are optional so
    existing direct Runner callers keep their historical construction shape.
    """

    parent_session_id: str = ""
    parent_run_id: str = ""
    parent_turn_id: str = ""
    parent_call_id: str = ""
    cwd: str = ""
    cancellation: Any = None
    # Queue shutdowns use a separate, dynamically-set token so an interrupted
    # run can be persisted and resumed.  A bool is also accepted for direct
    # callers; normal cancellation keeps the historical cancelled contract.
    pause_on_cancel: Any = False
    permissions: dict[str, Any] = field(default_factory=dict)
    event_metadata: dict[str, Any] = field(default_factory=dict)
    attachments: list[Any] = field(default_factory=list)
    runtime_snapshot: Any = None
    environment: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    # Resolved credential material is an execution-only child-context value.
    # It is deliberately excluded from repr/compare and from ``metadata``;
    # ``child()`` constructs a fresh context and therefore clears it.
    runtime_credentials: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    trace_id: str = ""
    # ``lineage`` contains parent call identifiers in order.  ``workflow_stack``
    # is separate because it is used for cycle detection, not presentation.
    lineage: tuple[str, ...] = ()
    workflow_stack: tuple[str, ...] = ()
    depth: int = 0
    max_depth: int = 16
    # Set only by the runner's own child/enter helpers.  A serialized context
    # intentionally omits this marker, so a caller cannot smuggle a stack
    # containing the workflow being invoked past the root cycle guard.
    _workflow_stack_internal: bool = field(default=False, repr=False, compare=False)
    # ``snapshot`` is the short spelling used by a few host adapters.  Keep
    # ``runtime_snapshot`` as the canonical wire key for Core compatibility.
    snapshot: Any = None

    def __post_init__(self) -> None:
        # Older callers put trace information exclusively in
        # ``event_metadata``.  Surface it on the explicit field too so all
        # adapters observe one canonical value while preserving object
        # identity for legacy integration tests.
        if not self.trace_id and isinstance(self.event_metadata, dict):
            trace = self.event_metadata.get("trace_id") or self.event_metadata.get("traceId")
            if trace:
                object.__setattr__(self, "trace_id", str(trace))
        if self.runtime_snapshot is None and self.snapshot is not None:
            object.__setattr__(self, "runtime_snapshot", self.snapshot)
        elif self.snapshot is None and self.runtime_snapshot is not None:
            object.__setattr__(self, "snapshot", self.runtime_snapshot)

    def child(
        self,
        *,
        session_id: str,
        run_id: str,
        call_id: str = "",
        workflow_id: str = "",
    ) -> "WorkflowExecutionContext":
        """Create a nested context while inheriting authority and cancel.

        Child permissions/capabilities are copies, never a fresh unrestricted
        mapping.  ``workflow_id`` is appended only for cycle detection; a
        repeated workflow therefore fails before it can execute a node.
        """
        parent_call = call_id or self.parent_call_id
        lineage = tuple(self.lineage)
        if self.parent_call_id:
            lineage = (*lineage, self.parent_call_id)
        if call_id and (not lineage or lineage[-1] != call_id):
            lineage = (*lineage, call_id)
        stack = tuple(self.workflow_stack)
        if workflow_id:
            stack = (*stack, str(workflow_id))
        return WorkflowExecutionContext(
            parent_session_id=session_id,
            parent_run_id=run_id,
            parent_turn_id=self.parent_turn_id,
            parent_call_id=parent_call,
            cwd=self.cwd,
            cancellation=self.cancellation,
            pause_on_cancel=self.pause_on_cancel,
            permissions=dict(self.permissions),
            event_metadata=dict(self.event_metadata),
            attachments=list(self.attachments),
            runtime_snapshot=_json_copy(self.runtime_snapshot),
            environment=_json_copy(self.environment),
            capabilities=_json_copy(self.capabilities),
            trace_id=self.trace_id,
            lineage=lineage,
            workflow_stack=stack,
            depth=max(0, int(self.depth)) + 1,
            max_depth=max(0, int(self.max_depth)),
            snapshot=_json_copy(self.snapshot),
            _workflow_stack_internal=True,
        )

    def enter_workflow(self, workflow_id: str) -> "WorkflowExecutionContext":
        """Mark a workflow active, rejecting recursive/cyclic invocation."""
        identity = str(workflow_id or "").strip()
        if not identity:
            return self
        if identity in self.workflow_stack:
            raise WorkflowRecursionError(
                f"workflow invocation cycle detected: {' -> '.join((*self.workflow_stack, identity))}"
            )
        # ``depth`` is the number of nested workflow boundaries below the
        # root.  A max depth of zero therefore still permits the root run and
        # rejects its first child; the boundary is exceeded only at ``>``.
        if self.depth > max(0, int(self.max_depth)):
            raise WorkflowNestingError(
                f"workflow nesting depth limit exceeded ({self.max_depth})"
            )
        return replace(
            self,
            workflow_stack=(*self.workflow_stack, identity),
            runtime_credentials={},
            _workflow_stack_internal=True,
        )

    def metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "parent_session_id": self.parent_session_id,
            "parent_run_id": self.parent_run_id,
            "parent_turn_id": self.parent_turn_id,
            "parent_call_id": self.parent_call_id,
            "cwd": self.cwd,
            "pause_on_cancel": _json_copy(self.pause_on_cancel)
            if isinstance(self.pause_on_cancel, (bool, int, float, str, type(None)))
            else False,
            "permissions": _json_copy(self.permissions),
            "runtime_permissions": _json_copy(self.permissions),
            **_json_copy(self.event_metadata),
        }
        if self.attachments:
            metadata["attachments"] = _json_copy(self.attachments)
        if self.runtime_snapshot is not None:
            metadata["runtime_snapshot"] = _json_copy(self.runtime_snapshot)
            if self.snapshot is None:
                metadata["snapshot"] = _json_copy(self.runtime_snapshot)
        elif self.snapshot is not None:
            metadata["snapshot"] = _json_copy(self.snapshot)
        if self.environment:
            metadata["environment"] = _json_copy(self.environment)
        if self.capabilities:
            metadata["capabilities"] = _json_copy(self.capabilities)
        if self.trace_id:
            metadata["trace_id"] = self.trace_id
        if self.lineage:
            metadata["lineage"] = list(self.lineage)
        if self.workflow_stack:
            metadata["workflow_stack"] = list(self.workflow_stack)
        metadata["depth"] = int(self.depth)
        metadata["max_depth"] = int(self.max_depth)
        return metadata

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


class WorkflowValidationError(ValueError):
    """Raised when a workflow graph cannot be executed safely."""


class WorkflowExpressionError(WorkflowExecutorError):
    """A safe expression failure preserved as machine-readable node error."""

    def __init__(self, error: ExpressionError) -> None:
        self.expression_error = error
        super().__init__(error.to_json())


class WorkflowPermissionError(PermissionError):
    """Raised when a command/script node is not allowed by the host gate."""


class WorkflowCapabilityError(PermissionError):
    """Raised when a node declaration is not authorized by its host context."""


class WorkflowRecursionError(WorkflowValidationError):
    """Raised when a nested workflow calls itself through the active chain."""


class WorkflowNestingError(WorkflowValidationError):
    """Raised when the configured nested workflow depth is exceeded."""


class LazyInput:
    """A lazily-resolved workflow input supplied to trusted node executors.

    Lazy inputs are declared on a port (``lazy: true``) or through a node's
    ``config.lazy_inputs`` data.  The resolver is created by the runner from
    the value table; it is never loaded from the workflow document.  Built-in
    executors materialize this object before invoking their host service,
    while a trusted plugin executor may defer or omit the value as needed.
    """

    __slots__ = ("name", "_resolver", "_resolved", "_value")

    def __init__(self, name: str, resolver: Callable[[], Any]) -> None:
        self.name = str(name or "")
        self._resolver = resolver
        self._resolved = False
        self._value: Any = None

    def resolve(self) -> Any:
        if not self._resolved:
            self._value = self._resolver()
            self._resolved = True
        return self._value

    async def aresolve(self) -> Any:
        value = self.resolve()
        if inspect.isawaitable(value):
            try:
                value = await value
            except BaseException:
                # A failed deferred read must remain retryable.  In
                # particular, cancellation should not permanently cache the
                # coroutine object that was interrupted.
                self._resolved = False
                self._value = None
                raise
            self._value = value
        return value

    def __await__(self):
        """Allow trusted executors to use ``await inputs["port"]`` directly."""

        return self.aresolve().__await__()

    @property
    def value(self) -> Any:
        return self.resolve()

    @property
    def resolved(self) -> bool:
        return self._resolved

    def __repr__(self) -> str:
        return f"LazyInput({self.name!r}, resolved={self._resolved})"


# Alias for plugin authors that use the shorter value terminology.
LazyValue = LazyInput


class WorkflowConflictError(RuntimeError):
    """Raised when a compare-and-swap revision no longer matches."""


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


@dataclass
class _ActiveWorkflowRun:
    """Mutable snapshot used to turn an external task cancel into a result."""

    workflow: WorkflowDef
    order: list[str]
    node_states: dict[str, WorkflowNodeState]
    values: dict[str, Any]
    inputs: dict[str, Any] = field(default_factory=dict)
    current_node_id: str = ""
    steps_taken: int = 0
    execution_context: WorkflowExecutionContext | None = None


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str, ensure_ascii=False))
    except (TypeError, ValueError):
        return value


def _claim_request_fingerprint(identity: Mapping[str, Any]) -> str:
    """Hash claim identity so durable coordination never stores resume secrets."""
    canonical = json.dumps(
        dict(identity), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _coordination_store_key(event_store: Any, snapshot_store: Any) -> str:
    parts: list[str] = []
    for store in (event_store, snapshot_store):
        if store is None:
            continue
        candidate = getattr(store, "directory", None) or getattr(store, "path", None)
        if candidate is not None:
            try:
                parts.append(str(Path(candidate).expanduser().resolve()))
            except OSError:
                parts.append(str(candidate))
        else:
            parts.append(f"object:{id(store)}")
    return "|".join(parts) or "unconfigured"


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


def validate_workflow(
    workflow: WorkflowDef,
    *,
    start_node: str | None = None,
    single_node: str | None = None,
    node_registry: Any = None,
) -> None:
    """Validate graph structure and typed connections before execution.

    The validator is intentionally independent of storage and model services.
    Subgraph target existence is checked by the runner at execution time,
    because it depends on the active project scope.
    """
    if not isinstance(workflow, WorkflowDef):
        raise WorkflowValidationError("workflow must be a WorkflowDef")
    if not workflow.name.strip():
        raise WorkflowValidationError("workflow name is required")

    nodes_by_id: dict[str, WorkflowNode] = {}
    for node in workflow.nodes:
        node_id = str(node.id or "").strip()
        if not node_id:
            raise WorkflowValidationError("node id is required")
        if node_id in nodes_by_id:
            raise WorkflowValidationError(f"duplicate node id: {node_id}")
        if node.kind not in _BUILTIN_EXECUTORS:
            schema = node_registry.get(node.kind) if node_registry is not None else None
            execution = node.config.get("execution") if isinstance(node.config.get("execution"), dict) else {}
            if schema is None and not bool(execution.get("schema_only", False)):
                raise WorkflowValidationError(f"unsupported node kind: {node.kind}")
        ports: set[str] = set()
        for port in node.ports:
            port_name = str(port.name or "").strip()
            if not port_name:
                raise WorkflowValidationError(f"node '{node_id}' has a port without a name")
            if port_name in ports:
                raise WorkflowValidationError(f"node '{node_id}' has duplicate port: {port_name}")
            ports.add(port_name)
            if port.direction not in {"in", "out"}:
                raise WorkflowValidationError(
                    f"node '{node_id}' port '{port_name}' has invalid direction"
                )
        nodes_by_id[node_id] = node

    edge_ids: set[str] = set()
    routes: set[tuple[str, str, str, str]] = set()
    for edge in workflow.edges:
        edge_id = str(edge.id or "").strip()
        if not edge_id:
            raise WorkflowValidationError("edge id is required")
        if edge_id in edge_ids:
            raise WorkflowValidationError(f"duplicate edge id: {edge_id}")
        edge_ids.add(edge_id)
        route = (edge.source, edge.source_port, edge.target, edge.target_port)
        if route in routes:
            raise WorkflowValidationError(
                f"duplicate edge: {edge.source}.{edge.source_port} -> "
                f"{edge.target}.{edge.target_port}"
            )
        routes.add(route)
        source = nodes_by_id.get(edge.source)
        target = nodes_by_id.get(edge.target)
        if source is None or target is None:
            raise WorkflowValidationError(
                f"edge '{edge_id}' references an unknown node"
            )
        source_port = next((p for p in source.ports if p.name == edge.source_port), None)
        target_port = next((p for p in target.ports if p.name == edge.target_port), None)
        if source_port is None:
            raise WorkflowValidationError(
                f"edge '{edge_id}' source port not found: {edge.source}.{edge.source_port}"
            )
        if target_port is None:
            raise WorkflowValidationError(
                f"edge '{edge_id}' target port not found: {edge.target}.{edge.target_port}"
            )
        if source_port.direction != "out" or target_port.direction != "in":
            raise WorkflowValidationError(
                f"edge '{edge_id}' must connect an output to an input"
            )
        if not _types_compatible(source_port.type, target_port.type):
            raise WorkflowValidationError(
                f"edge '{edge_id}' has incompatible types: "
                f"{source_port.type} -> {target_port.type}"
            )

    params_seen: set[str] = set()
    for param in workflow.input_params:
        name = str(param.name or "").strip()
        if not name:
            raise WorkflowValidationError("workflow input name is required")
        if name in params_seen:
            raise WorkflowValidationError(f"duplicate workflow input: {name}")
        params_seen.add(name)
        if param.required and param.default is None:
            # The absence is checked against run inputs; this marks the
            # contract without rejecting a valid definition at save time.
            continue

    if workflow.output_port:
        parts = workflow.output_port.split(".", 1)
        output_node = nodes_by_id.get(parts[0])
        if output_node is None:
            raise WorkflowValidationError(
                f"output_port references unknown node: {workflow.output_port}"
            )
        if len(parts) == 2:
            output = next((p for p in output_node.ports if p.name == parts[1]), None)
            if output is None or output.direction != "out":
                raise WorkflowValidationError(
                    f"output_port must reference an output port: {workflow.output_port}"
                )

    for selected in (start_node, single_node):
        if selected and selected not in nodes_by_id:
            raise WorkflowValidationError(f"unknown node: {selected}")


def _validate_run_inputs(
    workflow: WorkflowDef,
    inputs: dict[str, Any],
    prior_values: dict[str, Any],
) -> None:
    for param in workflow.input_params:
        if not param.required or param.default is not None:
            continue
        if param.name in inputs or f"__input__.{param.name}" in prior_values:
            continue
        raise WorkflowValidationError(
            f"required workflow input is missing: {param.name}"
        )


# ---------------------------------------------------------------------------
# WorkflowManager — create / get / list / update / delete over a store
# ---------------------------------------------------------------------------


WorkflowEventCallback = Callable[[RunItemEvent], Awaitable[None] | None]
_WORKFLOW_MUTATION_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}


class WorkflowManager:
    """Coordinates workflow definitions with a :class:`WorkflowStore`-like store.

    The store protocol mirrors :class:`ArrangeStore`: async ``list`` / ``get`` /
    ``save`` / ``delete``. The file-backed implementation lives in
    :mod:`lamtools_core.plugins.bundled.workflow.backend.store`.
    """

    def __init__(self, store: Any, node_registry: Any = None) -> None:
        self.store = store
        self.node_registry = node_registry

    def _mutation_lock(self, work_root: str | None) -> asyncio.Lock:
        provider = getattr(self.store, "mutation_lock", None)
        if callable(provider):
            return provider(work_root)
        # Store-compatible test/embedding implementations may not expose a
        # lock provider.  Still serialize all managers sharing that store and
        # scope so expected_revision remains a real compare-and-swap.
        try:
            scope = str(Path(work_root).expanduser().resolve()) if work_root else ""
        except (OSError, TypeError, ValueError):
            scope = str(work_root or "")
        key = (id(self.store), scope.casefold())
        lock = _WORKFLOW_MUTATION_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _WORKFLOW_MUTATION_LOCKS[key] = lock
        return lock

    async def create(self, definition: WorkflowDef) -> WorkflowDef:
        async with self._mutation_lock(definition.work_root):
            ensure_workflow_id(definition)
            definition.revision = max(1, definition.revision)
            validate_workflow(definition, node_registry=self.node_registry)
            return await self.store.save(definition)

    async def get(self, name: str, *, work_root: str | None = None) -> WorkflowDef | None:
        return await self.store.get(name, work_root=work_root)

    async def get_by_id(self, workflow_id: str, *, work_root: str | None = None) -> WorkflowDef | None:
        """Resolve a workflow ID within one repository scope.

        File-backed stores provide an exact scoped lookup.  Keep the
        list-and-filter fallback for store-compatible integrations that have
        not adopted the optional ``get_by_id`` seam yet.
        """
        provider = getattr(self.store, "get_by_id", None)
        if callable(provider):
            result = provider(workflow_id, work_root=work_root)
            if inspect.isawaitable(result):
                return await result
            return result
        definitions = await self.store.list(work_root=work_root)
        target = str(workflow_id or "").strip()
        if not target:
            return None
        return next((item for item in definitions if item.id == target), None)

    async def get_document(self, name: str, *, work_root: str | None = None) -> dict[str, Any] | None:
        from .document import document_from_workflow_def

        definition = await self.get(name, work_root=work_root)
        return document_from_workflow_def(definition) if definition is not None else None

    async def save_document(
        self,
        document: dict[str, Any],
        *,
        work_root: str | None = None,
        expected_revision: int | None = None,
    ) -> WorkflowDef:
        """CAS-save one canonical V2 document through the runtime seam."""
        from .document import canonicalize_document, workflow_def_from_document

        doc = canonicalize_document(document)
        resource = doc["resource"]
        active_root = str(work_root if work_root is not None else resource["work_root"])
        async with self._mutation_lock(active_root):
            current = await self.store.get(resource["name"], work_root=active_root or None)
            if current is not None:
                if expected_revision is not None and current.revision != expected_revision:
                    raise WorkflowConflictError(
                        f"workflow revision conflict: expected {expected_revision}, current {current.revision}"
                    )
                resource["id"] = current.id
                resource["created_at"] = current.created_at.isoformat()
                resource["revision"] = max(1, current.revision + 1)
            else:
                if expected_revision not in (None, 0):
                    raise WorkflowConflictError(
                        f"workflow revision conflict: expected {expected_revision}, current 0"
                    )
                resource["revision"] = max(1, int(resource.get("revision") or 0))
            resource["work_root"] = active_root
            resource["updated_at"] = _utcnow().isoformat()
            definition = workflow_def_from_document(doc)
            validate_workflow(definition, node_registry=self.node_registry)
            return await self.store.save(definition)

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
        expected_revision: int | None = None,
    ) -> WorkflowDef:
        async with self._mutation_lock(work_root):
            current = await self.store.get(name, work_root=work_root)
            if current is None:
                raise LookupError(f"Workflow not found: {name}")
            if expected_revision is not None and current.revision != expected_revision:
                raise WorkflowConflictError(
                    f"workflow revision conflict: expected {expected_revision}, current {current.revision}"
                )
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
            current.revision = max(1, current.revision + 1)
            validate_workflow(current, node_registry=self.node_registry)
            return await self.store.save(current)

    async def rename(
        self,
        name: str,
        new_name: str,
        *,
        work_root: str | None = None,
    ) -> WorkflowDef:
        """Rename a workflow while preserving its stable resource id."""
        clean_name = str(new_name or "").strip()
        if not clean_name:
            raise ValueError("new workflow name is required")
        async with self._mutation_lock(work_root):
            current = await self.store.get(name, work_root=work_root)
            if current is None:
                raise LookupError(f"Workflow not found: {name}")
            if clean_name == current.name:
                return current
            collision = await self.store.get(clean_name, work_root=work_root)
            if collision is not None and collision.id != current.id:
                raise ValueError(f"Workflow already exists: {clean_name}")
            current.name = clean_name
            current.updated_at = _utcnow()
            validate_workflow(current, node_registry=self.node_registry)
            return await self.store.save(current)

    async def delete(self, name: str, *, work_root: str | None = None) -> bool:
        async with self._mutation_lock(work_root):
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
        model_invoker: ModelInvoker | Any = None,
        agent_invoker: AgentInvoker | Any = None,
        emit: WorkflowEventCallback | None = None,
        runtime_task_registry: Any = None,
        workflow_store: Any = None,
        permission_service: Any = None,
        snapshot_store: WorkflowSnapshotStore | None = None,
        event_store: WorkflowRunEventStore | None = None,
        claim_store: WorkflowClaimStore | None = None,
        flow_control_store: FlowControlStore | Any = None,
        flow_store: FlowControlStore | Any = None,
        cache_store: WorkflowContentCache | None = None,
        credential_resolver: Any = None,
        node_registry: WorkflowNodeRegistry | None = None,
        executor_registry: WorkflowExecutorRegistry | Any = None,
        node_executors: dict[str, Any] | None = None,
        node_executor: Any = None,
        max_nesting_depth: int = 16,
        max_depth: int | None = None,
        max_expansion_nodes: int = 128,
        max_expansion_edges: int = 512,
        emit_lifecycle_events: bool = False,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        # Keep the legacy attributes public for embedders that inspect them,
        # but make all actual service calls through the explicit adapters.
        self.llm_client = llm_client
        self.sub_agent_runner = sub_agent_runner
        self.model_invoker = adapt_model_invoker(model_invoker if model_invoker is not None else llm_client)
        self.agent_invoker = adapt_agent_invoker(agent_invoker if agent_invoker is not None else sub_agent_runner)
        self.emit = emit
        self.runtime_task_registry = runtime_task_registry
        # ``workflow_store`` enables subworkflow nodes to resolve and run other
        # workflow definitions by name.
        self.workflow_store = workflow_store
        self.permission_service = permission_service
        self.snapshot_store = snapshot_store
        self.event_store = event_store
        self.claim_store = claim_store or claim_store_for_runtime(event_store, snapshot_store)
        # Flow-control is opt-in at the document boundary.  Keep an explicitly
        # supplied store for hosts/tests; otherwise run-scoped stores are
        # lazily created from the workflow root so separate projects do not
        # share a coordinator file accidentally.
        self.flow_control_store = flow_control_store if flow_control_store is not None else flow_store
        self._flow_control_stores: dict[str, FlowControlStore] = {}
        self.cache_store = cache_store or WorkflowContentCache()
        self.credential_resolver = credential_resolver
        supplied_schema_registry = getattr(executor_registry, "schema_registry", None)
        # Older embedders passed the schema registry itself through the
        # ``executor_registry`` slot.  It already exposes ``get_executor``
        # and ``register_executor``; preserve that shape instead of silently
        # constructing a second schema registry that cannot see its custom
        # node types.
        executor_is_schema_registry = (
            supplied_schema_registry is None
            and callable(getattr(executor_registry, "get_executor", None))
            and callable(getattr(executor_registry, "register_executor", None))
        )
        self.node_registry = (
            node_registry
            if node_registry is not None
            else supplied_schema_registry
            if supplied_schema_registry is not None
            else executor_registry
            if executor_is_schema_registry
            else WorkflowNodeRegistry()
        )
        self.executor_registry = (
            executor_registry
            if executor_registry is not None
            else WorkflowExecutorRegistry(self.node_registry)
        )
        self.max_nesting_depth = max(
            0,
            int(max_depth if max_depth is not None else max_nesting_depth),
        )
        # Zero is useful as a host policy to disable dynamic expansion while
        # retaining ordinary registered nodes.  Keep that explicit setting
        # instead of silently widening it to one node.
        self.max_expansion_nodes = max(0, int(max_expansion_nodes))
        self.max_expansion_edges = max(0, int(max_expansion_edges))
        # A singular host executor is a convenience for embedding and is still
        # subject to the same schema/trust checks when a node has a custom kind.
        self.node_executor = adapt_node_executor(node_executor) if node_executor is not None else None
        if node_executors:
            for type_id, executor in node_executors.items():
                self._register_node_executor_compat(type_id, executor)
        # Existing direct Runner consumers receive the historical per-node
        # event stream. Queue-backed runs opt into lifecycle events (queued is
        # emitted by the queue itself; Runner emits progress/paused).
        self.emit_lifecycle_events = emit_lifecycle_events
        self.clock = clock
        self._active_runs: dict[tuple[str, str], _ActiveWorkflowRun] = {}
        self._active_tasks: dict[tuple[str, str], asyncio.Task[Any]] = {}
        self._run_snapshots: dict[tuple[str, str], WorkflowRunResult] = {}
        self._run_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._signal_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._run_lock_users: dict[tuple[str, str], int] = {}
        self._signal_lock_users: dict[tuple[str, str], int] = {}
        self._terminal_results: OrderedDict[tuple[str, str], WorkflowRunResult] = OrderedDict()
        self._max_terminal_results = 1024

    def _register_node_executor_compat(self, type_id: str, executor: Any) -> None:
        """Install a host-supplied executor while preserving old registries."""
        # ``WorkflowNodeRegistry`` calls this operation ``register_executor``;
        # ``WorkflowExecutorRegistry`` uses ``register`` for the same action.
        # Prefer the explicit name so a schema registry passed for legacy
        # compatibility is not mistaken for its schema-only ``register``
        # alias.
        register = getattr(self.executor_registry, "register_executor", None)
        if not callable(register):
            register = getattr(self.executor_registry, "register", None)
        if not callable(register):
            raise TypeError("workflow executor registry must expose register()")
        clean_type = str(type_id or "").strip()
        # ``node_executors`` is an explicit host-owned surface, so it is
        # trusted by definition.  The registry still requires a matching
        # schema, preventing an unregistered node from reaching execution.
        register(clean_type, executor, plugin_id="workflow", trusted=True)

    def _remember_terminal(
        self, key: tuple[str, str], result: WorkflowRunResult
    ) -> None:
        self._terminal_results[key] = WorkflowRunResult.from_dict(result.to_dict())
        self._terminal_results.move_to_end(key)
        while len(self._terminal_results) > self._max_terminal_results:
            self._terminal_results.popitem(last=False)

    def _flow_control_policy(self, workflow: WorkflowDef) -> FlowControlPolicy:
        """Read the canonical V2 scheduling policy, if this is a V2 run."""
        if not isinstance(workflow.document, Mapping):
            return FlowControlPolicy.empty()
        # Import lazily: document.py uses runtime data-model classes at its
        # conversion boundary, so importing it at module load would create a
        # cycle for embedders importing WorkflowRunner directly.
        from .document import workflow_flow_control_policy

        return workflow_flow_control_policy(workflow)

    def _flow_control_store_for_run(
        self,
        workflow: WorkflowDef,
        work_root: str,
    ) -> Any:
        if self.flow_control_store is not None:
            return self.flow_control_store
        effective_root = str(work_root or workflow.work_root or "").strip()
        if effective_root:
            try:
                cache_key = str(Path(effective_root).expanduser().resolve())
            except OSError:
                cache_key = effective_root
        else:
            cache_key = "<default>"
        store = self._flow_control_stores.get(cache_key)
        if store is None:
            store = FlowControlStore(root=effective_root or None)
            self._flow_control_stores[cache_key] = store
        return store

    @staticmethod
    def _flow_control_scope_key(
        workflow: WorkflowDef,
        workflow_identity: str,
        work_root: str,
    ) -> str:
        try:
            root = str(Path(work_root or workflow.work_root or "").expanduser().resolve())
        except OSError:
            root = str(work_root or workflow.work_root or "")
        return stable_scope_key({"workflow_id": workflow_identity, "work_root": root})

    @staticmethod
    def _flow_control_lease_id(
        workflow_identity: str,
        thread_id: str,
        run_id: str,
    ) -> str:
        return stable_scope_key(
            {"workflow_id": workflow_identity, "thread_id": thread_id, "run_id": run_id},
            key="run",
        )

    @staticmethod
    def _normalize_flow_control_decision(value: Any) -> FlowControlDecision:
        if isinstance(value, FlowControlDecision):
            return value
        if isinstance(value, FlowControlLease):
            return FlowControlDecision("acquired", lease=value)
        if isinstance(value, Mapping):
            lease_value = value.get("lease")
            lease = (
                lease_value
                if isinstance(lease_value, FlowControlLease)
                else FlowControlLease.from_dict(lease_value)
                if isinstance(lease_value, Mapping)
                else None
            )
            allowed = bool(value.get("acquired", value.get("allowed", value.get("state") == "acquired")))
            if allowed:
                return FlowControlDecision("acquired", lease=lease)
            return FlowControlDecision(
                "blocked",
                reason=str(value.get("reason") or "flow_control"),
                retry_at=float(value["retry_at"]) if value.get("retry_at") is not None else None,
                reserved=bool(value.get("reserved", False)),
            )
        if isinstance(value, bool):
            return FlowControlDecision("acquired" if value else "blocked", reason="flow_control" if not value else "")
        allowed = bool(getattr(value, "acquired", getattr(value, "allowed", False)))
        if allowed:
            lease_value = getattr(value, "lease", None)
            return FlowControlDecision("acquired", lease=lease_value if isinstance(lease_value, FlowControlLease) else None)
        retry_value = getattr(value, "retry_at", None)
        try:
            retry_at = float(retry_value) if retry_value is not None else None
        except (TypeError, ValueError):
            retry_at = None
        return FlowControlDecision(
            "blocked",
            reason=str(getattr(value, "reason", "") or "flow_control"),
            retry_at=retry_at,
            reserved=bool(getattr(value, "reserved", False)),
        )

    async def _flow_control_admit(
        self,
        workflow: WorkflowDef,
        *,
        workflow_identity: str,
        work_root: str,
        thread_id: str,
        run_id: str,
        workflow_revision: int,
        workflow_digest: str,
        previous: WorkflowRunResult | None,
        prior_values: dict[str, Any] | None,
        prior_node_states: dict[str, WorkflowNodeState] | None,
        started_at: datetime,
        inputs: dict[str, Any] | None,
    ) -> tuple[FlowControlPolicy, Any, FlowControlLease | Mapping[str, Any] | None, asyncio.Task[Any] | None, asyncio.Event | None, WorkflowRunResult | None]:
        """Admit one actual run, returning a paused result when blocked."""
        policy = self._flow_control_policy(workflow)
        if not policy.enabled:
            return policy, None, None, None, None, None
        store = self._flow_control_store_for_run(workflow, work_root)
        scope_key = self._flow_control_scope_key(workflow, workflow_identity, work_root)
        lease_id = self._flow_control_lease_id(workflow_identity, thread_id, run_id)
        decision_raw = await _call_with_supported_kwargs(
            store.acquire,
            {
                "policy": policy,
                "scope_key": scope_key,
                "lease_id": lease_id,
            },
        )
        decision = self._normalize_flow_control_decision(decision_raw)
        if not decision.acquired:
            retry_at = decision.retry_at
            descriptor: dict[str, Any] = {
                "kind": "flow_control",
                "type": "flow_control",
                "reason": decision.reason or "flow_control",
                "blocked_by": decision.reason or "flow_control",
                "scope_key": scope_key,
                "lease_id": lease_id,
                "workflow_id": workflow_identity,
                "workflow_revision": workflow_revision,
                "definition_digest": workflow_digest,
                "thread_id": thread_id,
                "run_id": run_id,
                "retry_at": retry_at,
                "policy": policy.to_dict(),
            }
            if decision.reserved:
                descriptor["reserved"] = True
            preserved_values = (
                dict(previous.values)
                if previous is not None
                else dict(prior_values or {})
            )
            preserved_states = (
                previous.node_states
                if previous is not None
                else (prior_node_states or {})
            )
            result = WorkflowRunResult(
                status="paused",
                run_id=run_id,
                workflow_id=workflow_identity,
                workflow_revision=workflow_revision,
                definition_digest=workflow_digest,
                wait_descriptor=descriptor,
                output=previous.output if previous is not None else None,
                values=preserved_values,
                node_states={
                    node_id: WorkflowNodeState.from_dict(state.to_dict(), node_id=node_id)
                    for node_id, state in preserved_states.items()
                },
                steps_remaining=previous.steps_remaining if previous is not None else 0,
                started_at=previous.started_at if previous is not None and previous.started_at else started_at,
                finished_at=None,
            )
            await self._append_durable_event(
                WorkflowRunEvent(
                    event_id=f"{run_id}:flow-control:{descriptor['reason']}:{retry_at}",
                    run_id=run_id,
                    kind="run.flow_control_blocked",
                    workflow_id=workflow_identity,
                    workflow_revision=workflow_revision,
                    payload={"wait_descriptor": _json_copy(descriptor)},
                )
            )
            await self._persist_snapshot(
                thread_id,
                run_id,
                result,
                workflow=workflow,
                inputs=inputs,
            )
            return policy, store, None, None, None, result
        lease = decision.lease
        if lease is None:
            # A host may provide a boolean admission adapter.  It can grant
            # admission, but without a lease there is nothing to heartbeat or
            # release; preserve that adapter contract.
            return policy, store, None, None, None, None
        lost = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._flow_control_heartbeat(store, lease, lost),
            name=f"workflow:flow-control:{run_id}",
        )
        return policy, store, lease, heartbeat, lost, None

    async def _flow_control_heartbeat(
        self,
        store: Any,
        lease: FlowControlLease | Mapping[str, Any],
        lost: asyncio.Event,
    ) -> None:
        current = lease
        try:
            try:
                lease_seconds = float(getattr(store, "lease_seconds", 30.0))
            except (TypeError, ValueError):
                lease_seconds = 30.0
            interval = max(0.01, min(5.0, lease_seconds / 3.0))
            while True:
                await asyncio.sleep(interval)
                renewed = await _call_with_supported_kwargs(store.renew, {"lease": current})
                if renewed is None or renewed is False:
                    lost.set()
                    return
                # Some host adapters return a boolean acknowledgement instead
                # of a refreshed lease.  Keep the original fencing token in
                # that case; the built-in store returns a new lease object.
                if renewed is not True:
                    current = renewed
        except asyncio.CancelledError:
            raise
        except Exception:
            lost.set()

    async def _flow_control_release(
        self,
        store: Any,
        lease: FlowControlLease | Mapping[str, Any] | None,
        heartbeat: asyncio.Task[Any] | None,
    ) -> None:
        if heartbeat is not None and not heartbeat.done():
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        if store is not None and lease is not None:
            try:
                await _call_with_supported_kwargs(store.release, {"lease": lease})
            except Exception:
                # Lease release is best effort during cancellation/shutdown;
                # expiry cleanup/fencing prevents a stale lease from granting
                # indefinite capacity.
                pass

    async def _execute_durable_claim(
        self,
        kind: Literal["run", "signal"],
        thread_id: str,
        run_id: str,
        operation: Callable[[], Awaitable[WorkflowRunResult]],
        *,
        request_fingerprint: str,
        mismatch_result: Callable[[], WorkflowRunResult] | None = None,
    ) -> WorkflowRunResult:
        """Execute under a SQLite lease and fence; waiters observe its result."""
        if self.claim_store is None:
            return await operation()
        while True:
            acquired = await _call_with_supported_kwargs(
                self.claim_store.acquire,
                {
                    "kind": kind,
                    "thread_id": thread_id,
                    "run_id": run_id,
                    "request_fingerprint": request_fingerprint,
                },
            )
            if acquired.state == "completed" and isinstance(acquired.result, dict):
                return WorkflowRunResult.from_dict(acquired.result)
            if acquired.state == "mismatch":
                if mismatch_result is not None:
                    return mismatch_result()
                raise ValueError("workflow signal request does not match the completed claim")
            if acquired.state == "busy":
                delay = max(0.01, min(0.2, acquired.retry_at - datetime.now(timezone.utc).timestamp()))
                await asyncio.sleep(delay)
                continue
            lease = acquired.lease
            if lease is None:
                raise RuntimeError("workflow durable claim acquisition failed")
            operation_task = asyncio.create_task(operation())

            async def _heartbeat() -> bool:
                current_lease = lease
                interval = max(0.25, self.claim_store.lease_seconds / 3)
                while not operation_task.done():
                    await asyncio.sleep(interval)
                    if operation_task.done():
                        return True
                    renewed = await self.claim_store.renew(current_lease)
                    if renewed is None:
                        return False
                    current_lease = renewed
                return True

            heartbeat_task = asyncio.create_task(_heartbeat())
            try:
                done, _ = await asyncio.wait(
                    {operation_task, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if heartbeat_task in done and heartbeat_task.result() is False:
                    operation_task.cancel()
                    await asyncio.gather(operation_task, return_exceptions=True)
                    raise RuntimeError("workflow durable claim lease was lost")
                result = await operation_task
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
                if result.status in {"completed", "failed", "cancelled"}:
                    if not await self.claim_store.complete(lease, result.to_dict()):
                        raise RuntimeError("workflow durable claim fence was lost before commit")
                elif not await self.claim_store.release(lease):
                    raise RuntimeError("workflow durable claim fence was lost before release")
                return result
            except BaseException:
                if not heartbeat_task.done():
                    heartbeat_task.cancel()
                    await asyncio.gather(heartbeat_task, return_exceptions=True)
                if not operation_task.done():
                    operation_task.cancel()
                    await asyncio.gather(operation_task, return_exceptions=True)
                try:
                    await self.claim_store.release(lease)
                except Exception:
                    pass
                raise

    def _executor_for_node(self, node: WorkflowNode) -> NodeExecutor | None:
        """Resolve a plugin executor from the schema/execution registry."""
        getter = getattr(self.executor_registry, "get", None)
        executor = getter(node.kind) if callable(getter) else None
        # ``WorkflowNodeRegistry.get`` returns a schema, not an executor.  A
        # host may intentionally pass that schema registry in the executor
        # slot for backwards compatibility, so never adapt a descriptive
        # schema object into a callable bridge.
        if executor is not None and not _is_executor_surface(executor):
            executor = None
        if executor is None:
            getter = getattr(self.node_registry, "get_executor", None)
            executor = getter(node.kind) if callable(getter) else None
        if executor is None and self.node_executor is not None:
            # A singular executor may only handle a declared custom type.  It
            # is never used to bypass schema validation for arbitrary kinds.
            spec = self.node_registry.get(node.kind) if self.node_registry is not None else None
            if spec is not None and self._builtin_executor_name(node) is None:
                executor = self.node_executor
        return adapt_node_executor(executor) if executor is not None else None

    def _validate_executable_nodes(self, workflow: WorkflowDef) -> None:
        """Reject schema-only or unknown custom nodes before any side effect."""
        for node in workflow.nodes:
            if self._builtin_executor_name(node) is not None:
                continue
            spec = self.node_registry.get(node.kind) if self.node_registry is not None else None
            if spec is None:
                raise WorkflowExecutorError(
                    f"workflow node type is not registered: {node.kind}"
                )
            if self._executor_for_node(node) is None:
                raise WorkflowExecutorError(
                    f"workflow node executor is not registered: {node.kind}"
                )

    def _check_node_authority(
        self,
        node: WorkflowNode,
        execution_context: WorkflowExecutionContext | None,
    ) -> None:
        """Enforce registry declarations against host grants, fail closed.

        A registry declaration describes requirements; it is never itself a
        grant.  Empty declarations retain the historical compatibility path.
        """

        spec = self.node_registry.get(node.kind) if self.node_registry is not None else None
        if spec is None:
            return
        required_capabilities = tuple(
            str(value).strip()
            for value in (getattr(spec, "capabilities", ()) or ())
            if str(value).strip()
        )
        resource_class = str(getattr(spec, "resource_class", "default") or "default").strip()
        requirements = getattr(spec, "resource_requirements", {}) or {}
        if not required_capabilities and resource_class in {"", "default"} and not requirements:
            return
        if execution_context is None:
            raise WorkflowCapabilityError(
                f"workflow node '{node.kind}' requires an authorized execution context"
            )
        grants = _workflow_authorization_grants(execution_context)
        missing = [name for name in required_capabilities if name not in grants.capabilities]
        if missing:
            raise WorkflowCapabilityError(
                f"workflow node '{node.kind}' requires capabilities: {', '.join(missing)}"
            )
        if resource_class not in {"", "default"} or requirements:
            if not _workflow_resource_authorized(
                resource_class or "default", requirements, grants.resources
            ):
                detail = resource_class or "default"
                raise WorkflowCapabilityError(
                    f"workflow node '{node.kind}' requires authorized resource class: {detail}"
                )

    def _builtin_executor_name(self, node: WorkflowNode) -> str | None:
        """Resolve only host-owned built-in executor aliases from node schema."""
        spec = self.node_registry.get(node.kind) if self.node_registry is not None else None
        if spec is None or not bool(getattr(spec, "builtin", False)):
            return None
        name = str(getattr(spec, "executor", "") or "")
        return name if name in _BUILTIN_EXECUTORS else None

    @staticmethod
    def _child_context(
        context: WorkflowExecutionContext | None,
        *,
        session_id: str,
        run_id: str,
        call_id: str,
        child_workflow_id: str,
        parent_workflow_id: str,
    ) -> WorkflowExecutionContext | None:
        """Build a nested context and seed the root workflow stack lazily.

        Explicit root contexts are passed unchanged to the first Agent/Model
        invocation for legacy identity compatibility.  The stack is seeded at
        the first nested boundary, where it is needed for cycle detection.
        """
        if context is None:
            return None
        base = context
        if not base.workflow_stack and parent_workflow_id:
            base = replace(base, workflow_stack=(str(parent_workflow_id),))
        return base.child(
            session_id=session_id,
            run_id=run_id,
            call_id=call_id,
            workflow_id=child_workflow_id,
        )

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
        execution_context: WorkflowExecutionContext | None = None,
        _run_lock_held: bool = False,
        _process_run_lock_held: bool = False,
        _durable_run_claim_held: bool = False,
    ) -> WorkflowRunResult:
        """Run a workflow and convert caller cancellation to a stable result.

        The operation layer deliberately uses task cancellation for prompt
        interruption (especially while a command/script subprocess is
        blocked).  Keeping this conversion at the public Runner boundary
        means callers still receive the same ``status=cancelled`` contract and
        the node state that was in flight is not lost.
        """
        effective_run_id = run_id or _new_id("wfrun")
        effective_thread_id = thread_id or f"workflow_thread_{uuid.uuid4().hex}"
        key = (effective_thread_id, effective_run_id)
        if not _run_lock_held:
            run_lock = self._run_locks.setdefault(key, asyncio.Lock())
            self._run_lock_users[key] = self._run_lock_users.get(key, 0) + 1
            try:
                async with run_lock:
                    return await self.run(
                        workflow,
                        inputs=inputs,
                        work_root=work_root,
                        thread_id=effective_thread_id,
                        run_id=effective_run_id,
                        prior_values=prior_values,
                        prior_node_states=prior_node_states,
                        max_steps=max_steps,
                        start_node=start_node,
                        single_node=single_node,
                        execution_context=execution_context,
                        _run_lock_held=True,
                        _process_run_lock_held=_process_run_lock_held,
                        _durable_run_claim_held=_durable_run_claim_held,
                    )
            finally:
                remaining_users = self._run_lock_users.get(key, 1) - 1
                if remaining_users <= 0:
                    self._run_lock_users.pop(key, None)
                    if self._run_locks.get(key) is run_lock:
                        self._run_locks.pop(key, None)
                else:
                    self._run_lock_users[key] = remaining_users
        started_at = self.clock()
        workflow_identity = ensure_workflow_id(workflow)
        for identity_node in workflow.nodes:
            for identity_port in identity_node.ports:
                if not identity_port.id:
                    identity_port.id = (
                        "port_"
                        + uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"{identity_node.id}\x1f{identity_port.direction}\x1f{identity_port.name}",
                        ).hex[:16]
                    )
        workflow_revision = max(0, int(workflow.revision))
        workflow_digest = definition_digest(workflow.to_dict())
        cached_terminal = self._terminal_results.get(key)
        if cached_terminal is not None and (
            cached_terminal.workflow_id == workflow_identity
            and cached_terminal.workflow_revision == workflow_revision
            and cached_terminal.definition_digest == workflow_digest
        ):
            self._terminal_results.move_to_end(key)
            return WorkflowRunResult.from_dict(cached_terminal.to_dict())
        previous = self._run_snapshots.get(key)
        snapshot_envelope: dict[str, Any] | None = None
        if previous is None and self.snapshot_store is not None:
            try:
                snapshot_envelope = await self.snapshot_store.get_dict(effective_thread_id, effective_run_id)
                previous = await self.snapshot_store.get(effective_thread_id, effective_run_id)
            except Exception:  # noqa: BLE001 - damaged snapshots are disposable
                previous = None
        if snapshot_envelope:
            pinned_id = str(snapshot_envelope.get("workflow_id") or (previous.workflow_id if previous else ""))
            has_revision = "workflow_revision" in snapshot_envelope or bool(previous and previous.workflow_revision)
            pinned_revision = _as_int(snapshot_envelope.get("workflow_revision"), default=previous.workflow_revision if previous else 0)
            pinned_digest = str(snapshot_envelope.get("definition_digest") or (previous.definition_digest if previous else ""))
            if (
                (pinned_id and pinned_id != workflow_identity)
                or (has_revision and pinned_revision != workflow_revision)
                or (pinned_digest and pinned_digest != workflow_digest)
            ):
                return WorkflowRunResult(
                    status="failed",
                    error="workflow definition changed since this run started",
                    run_id=effective_run_id,
                    workflow_id=pinned_id or workflow_identity,
                    workflow_revision=pinned_revision,
                    definition_digest=pinned_digest or workflow_digest,
                )
        if self.event_store is not None:
            journal_events = await self.event_store.list(effective_run_id)
            if not _process_run_lock_held:
                process_key = (
                    _coordination_store_key(self.event_store, self.snapshot_store),
                    effective_thread_id,
                    effective_run_id,
                )
                process_lock = _PROCESS_RUN_LOCKS.setdefault(process_key, asyncio.Lock())
                _PROCESS_RUN_LOCK_USERS[process_key] = _PROCESS_RUN_LOCK_USERS.get(process_key, 0) + 1
                try:
                    async with process_lock:
                        return await self.run(
                            workflow,
                            inputs=inputs,
                            work_root=work_root,
                            thread_id=effective_thread_id,
                            run_id=effective_run_id,
                            prior_values=prior_values,
                            prior_node_states=prior_node_states,
                            max_steps=max_steps,
                            start_node=start_node,
                            single_node=single_node,
                            execution_context=execution_context,
                            _run_lock_held=True,
                            _process_run_lock_held=True,
                            _durable_run_claim_held=_durable_run_claim_held,
                        )
                finally:
                    remaining_users = _PROCESS_RUN_LOCK_USERS.get(process_key, 1) - 1
                    if remaining_users <= 0:
                        _PROCESS_RUN_LOCK_USERS.pop(process_key, None)
                        if _PROCESS_RUN_LOCKS.get(process_key) is process_lock:
                            _PROCESS_RUN_LOCKS.pop(process_key, None)
                    else:
                        _PROCESS_RUN_LOCK_USERS[process_key] = remaining_users
            if self.claim_store is not None and not _durable_run_claim_held:
                return await self._execute_durable_claim(
                    "run",
                    effective_thread_id,
                    effective_run_id,
                    lambda: self.run(
                        workflow,
                        inputs=inputs,
                        work_root=work_root,
                        thread_id=effective_thread_id,
                        run_id=effective_run_id,
                        prior_values=prior_values,
                        prior_node_states=prior_node_states,
                        max_steps=max_steps,
                        start_node=start_node,
                        single_node=single_node,
                        execution_context=execution_context,
                        _run_lock_held=True,
                        _process_run_lock_held=True,
                        _durable_run_claim_held=True,
                    ),
                    request_fingerprint=_claim_request_fingerprint(
                        {
                            "workflow_id": workflow_identity,
                            "workflow_revision": workflow_revision,
                            "definition_digest": workflow_digest,
                        }
                    ),
                    mismatch_result=lambda: WorkflowRunResult(
                        status="failed",
                        error="workflow definition changed since this run completed",
                        run_id=effective_run_id,
                        workflow_id=workflow_identity,
                        workflow_revision=workflow_revision,
                        definition_digest=workflow_digest,
                    ),
                )
            if journal_events:
                started = next((event for event in journal_events if event.kind == "run.started"), None)
                if started is not None and (
                    (started.workflow_id and started.workflow_id != workflow_identity)
                    or started.workflow_revision != workflow_revision
                    or (
                        started.payload.get("definition_digest")
                        and started.payload.get("definition_digest") != workflow_digest
                    )
                ):
                    return WorkflowRunResult(
                        status="failed",
                        error="workflow definition changed since this run started",
                        run_id=effective_run_id,
                        workflow_id=started.workflow_id or workflow_identity,
                        workflow_revision=started.workflow_revision,
                        definition_digest=str(started.payload.get("definition_digest") or ""),
                    )
                terminal = next(
                    (
                        event for event in reversed(journal_events)
                        if event.kind in {"run.completed", "run.failed", "run.cancelled"}
                    ),
                    None,
                )
                if terminal is not None and isinstance(terminal.payload.get("result"), dict):
                    # Retrying the same RPC/run id is an idempotent read, not a
                    # second execution of already-completed side effects.
                    terminal_result = WorkflowRunResult.from_dict(terminal.payload["result"])
                    self._remember_terminal(key, terminal_result)
                    return terminal_result
                crossed_effect_boundary = any(
                    event.kind.startswith(("attempt.", "node.")) for event in journal_events
                )
                if previous is None and crossed_effect_boundary:
                    return WorkflowRunResult(
                        status="failed",
                        error="durable run snapshot is unavailable; refusing to replay an uncertain side effect",
                        run_id=effective_run_id,
                        workflow_id=workflow_identity,
                        workflow_revision=workflow_revision,
                        definition_digest=workflow_digest,
                    )
        if previous is not None and previous.status == "paused":
            if prior_values is None:
                prior_values = dict(previous.values)
            if prior_node_states is None:
                prior_node_states = {
                    node_id: WorkflowNodeState.from_dict(state.to_dict(), node_id=node_id)
                    for node_id, state in previous.node_states.items()
                }
                for state in prior_node_states.values():
                    if state.status == "running":
                        state.status = "idle"
                        state.error = "interrupted"
                        state.finished_at = None
        execution_context = execution_context or WorkflowExecutionContext(
            parent_session_id=effective_thread_id,
            parent_run_id=effective_run_id,
            cwd=work_root or workflow.work_root,
            cancellation=self._cancel_event(effective_thread_id),
            max_depth=self.max_nesting_depth,
        )
        # A caller-created context may carry a larger limit than this runner;
        # an embedded runner must not be able to widen the host's bound.
        context_max_depth = max(0, int(execution_context.max_depth))
        effective_max_depth = min(self.max_nesting_depth, context_max_depth)
        if context_max_depth != effective_max_depth:
            execution_context = replace(execution_context, max_depth=effective_max_depth)
        identity = str(workflow.id or workflow.name or "").strip()
        workflow_identities = {
            value
            for value in (str(workflow.id or "").strip(), str(workflow.name or "").strip())
            if value
        }
        try:
            # Canonical V2 documents are compiled at the execution boundary.
            # The current runtime consumes WorkflowDef through a compatibility
            # seam, while compilation enforces editor-only/disabled/schema-only
            # policy and validates the canvas-free prompt first.
            if workflow.document is not None:
                from .document import compile_document, document_from_workflow_def

                compile_document(document_from_workflow_def(workflow))
            # ``_execute_subgraph`` records the target identity while creating
            # the child context.  Do not append it twice when that internal
            # child Runner starts.  A root/operation context, however, is an
            # external boundary: even a stack ending in the current workflow
            # must be rejected rather than treated as an already-entered child.
            if execution_context.workflow_stack:
                stack = execution_context.workflow_stack
                matching_entries = [entry for entry in stack if entry in workflow_identities]
                if matching_entries:
                    if not (
                        execution_context._workflow_stack_internal
                        and stack[-1] in workflow_identities
                        and len(matching_entries) == 1
                    ):
                        raise WorkflowRecursionError(
                            f"workflow invocation cycle detected: {' -> '.join((*stack, identity))}"
                        )
                elif stack[-1] not in workflow_identities:
                    execution_context = execution_context.enter_workflow(identity)
            if execution_context.depth > execution_context.max_depth:
                raise WorkflowNestingError(
                    f"workflow nesting depth limit exceeded ({execution_context.max_depth})"
                )
        except (WorkflowRecursionError, WorkflowNestingError, ValueError) as exc:
            return WorkflowRunResult(
                status="failed",
                error=str(exc),
                run_id=effective_run_id,
            )
        flow_control_store: Any = None
        flow_control_lease: FlowControlLease | Mapping[str, Any] | None = None
        flow_control_heartbeat: asyncio.Task[Any] | None = None
        flow_control_lost: asyncio.Event | None = None
        current_task = asyncio.current_task()
        try:
            (
                _flow_policy,
                flow_control_store,
                flow_control_lease,
                flow_control_heartbeat,
                flow_control_lost,
                blocked_result,
            ) = await self._flow_control_admit(
                workflow,
                workflow_identity=workflow_identity,
                work_root=work_root,
                thread_id=effective_thread_id,
                run_id=effective_run_id,
                workflow_revision=workflow_revision,
                workflow_digest=workflow_digest,
                previous=previous,
                prior_values=prior_values,
                prior_node_states=prior_node_states,
                started_at=started_at,
                inputs=inputs,
            )
            if blocked_result is not None:
                # Admission pauses before the run enters the active map or
                # emits run.started.  Keep an in-memory copy as well as the
                # durable snapshot so a same-run retry can resume without
                # rebuilding the caller's prior state.
                blocked_result.cache = _cache_facts(blocked_result.node_states)
                self._run_snapshots[key] = WorkflowRunResult.from_dict(blocked_result.to_dict())
                return blocked_result
            if current_task is not None:
                self._active_tasks[key] = current_task
            await self._append_durable_event(
                WorkflowRunEvent(
                    event_id=f"{effective_run_id}:run:started",
                    run_id=effective_run_id,
                    kind="run.started",
                    workflow_id=workflow_identity,
                    workflow_revision=workflow_revision,
                    payload={"definition_digest": workflow_digest, "thread_id": effective_thread_id},
                )
            )
            result = await self._run_impl(
                workflow,
                inputs=inputs,
                work_root=work_root,
                thread_id=effective_thread_id,
                run_id=effective_run_id,
                prior_values=prior_values,
                prior_node_states=prior_node_states,
                max_steps=max_steps,
                start_node=start_node,
                single_node=single_node,
                execution_context=execution_context,
            )
            if flow_control_lost is not None and flow_control_lost.is_set():
                # A lost lease means admission can no longer be proven for
                # the side effects just attempted.  Do not expose a terminal
                # success (or a resumable wait) to the caller.
                result = WorkflowRunResult(
                    status="failed",
                    output=None,
                    node_states=result.node_states,
                    values=result.values,
                    error="workflow flow-control lease was lost",
                    run_id=effective_run_id,
                    steps_remaining=result.steps_remaining,
                    cache=result.cache,
                )
            result.cache = _cache_facts(result.node_states)
            result.workflow_id = workflow_identity
            result.workflow_revision = workflow_revision
            result.definition_digest = workflow_digest
            if self.emit_lifecycle_events and result.status in {"completed", "failed", "cancelled"}:
                await self._emit_run_status(
                    result.status,
                    effective_thread_id,
                    effective_run_id,
                    workflow_id=workflow.id,
                    node_id="",
                    error=result.error,
                )
            result.started_at = previous.started_at if previous and previous.started_at else started_at
            result.finished_at = None if result.status == "paused" else self.clock()
            await self._append_durable_event(
                WorkflowRunEvent(
                    event_id=f"{effective_run_id}:run:{result.status}",
                    run_id=effective_run_id,
                    kind=f"run.{result.status}",
                    workflow_id=workflow_identity,
                    workflow_revision=workflow_revision,
                    payload={"error": result.error, "result": result.to_dict()},
                )
            )
            if result.status == "paused":
                self._run_snapshots[key] = WorkflowRunResult.from_dict(result.to_dict())
                await self._persist_snapshot(
                    effective_thread_id,
                    effective_run_id,
                    result,
                    workflow=workflow,
                    inputs=inputs,
                )
            else:
                self._remember_terminal(key, result)
                self._run_snapshots.pop(key, None)
                if self.snapshot_store is not None:
                    try:
                        await self.snapshot_store.delete(effective_thread_id, effective_run_id)
                    except Exception:  # noqa: BLE001 - cleanup is best effort
                        pass
            return result
        except asyncio.CancelledError:
            if _pause_requested(execution_context):
                result = self._paused_result(key)
                result.started_at = previous.started_at if previous and previous.started_at else started_at
                result.finished_at = None
                self._run_snapshots[key] = WorkflowRunResult.from_dict(result.to_dict())
                active = self._active_runs.get(key)
                if active is not None:
                    await self._persist_snapshot(
                        effective_thread_id,
                        effective_run_id,
                        result,
                        workflow=active.workflow,
                        inputs=active.inputs,
                    )
                return result
            result = self._cancelled_result(key)
            result.started_at = previous.started_at if previous and previous.started_at else started_at
            result.finished_at = self.clock()
            self._run_snapshots.pop(key, None)
            self._remember_terminal(key, result)
            return result
        finally:
            await self._flow_control_release(
                flow_control_store,
                flow_control_lease,
                flow_control_heartbeat,
            )
            self._active_tasks.pop(key, None)
            self._active_runs.pop(key, None)

    async def _persist_snapshot(
        self,
        thread_id: str,
        run_id: str,
        result: WorkflowRunResult,
        *,
        workflow: WorkflowDef,
        inputs: dict[str, Any] | None,
    ) -> None:
        """Persist the latest resumable state when a store is configured."""
        if self.snapshot_store is None:
            return
        try:
            await self.snapshot_store.save(
                thread_id,
                run_id,
                result,
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                workflow_revision=max(0, int(workflow.revision)),
                definition_digest=definition_digest(workflow.to_dict()),
                workflow_definition={
                    **workflow.to_dict(),
                    **({"document": _json_copy(workflow.document)} if workflow.document is not None else {}),
                },
                inputs=inputs,
            )
        except Exception:  # noqa: BLE001 - snapshot persistence is non-fatal
            pass

    async def _append_durable_event(self, event: WorkflowRunEvent) -> None:
        """Append before/after side effects when durable journaling is enabled.

        Unlike GUI emission, journal failure is not swallowed: executing a
        side effect without a durable attempt identity would make recovery
        unsafe and must fail closed.
        """
        if self.event_store is not None:
            await self.event_store.append(event)

    async def _persist_active_snapshot(
        self,
        *,
        workflow: WorkflowDef,
        thread_id: str,
        run_id: str,
        inputs: dict[str, Any],
        node_states: dict[str, WorkflowNodeState],
        values: dict[str, Any],
        steps_remaining: int,
    ) -> None:
        """Write a resumable snapshot after each observable node transition."""
        await self._persist_snapshot(
            thread_id,
            run_id,
            WorkflowRunResult(
                status="paused",
                node_states={
                    node_id: WorkflowNodeState.from_dict(state.to_dict(), node_id=node_id)
                    for node_id, state in node_states.items()
                },
                values=_json_copy(values),
                run_id=run_id,
                steps_remaining=max(0, steps_remaining),
                cache={
                    node_id: {
                        "status": state.cache_status,
                        "key": state.cache_key,
                        "hit": state.cache_status == "hit",
                    }
                    for node_id, state in node_states.items()
                    if state.cache_status != "bypass" or state.cache_key
                },
            ),
            workflow=workflow,
            inputs=inputs,
        )

    async def _run_impl(
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
        execution_context: WorkflowExecutionContext | None = None,
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
        if workflow.document is not None:
            # V2 workflow-interface names are independent of internal node and
            # port display names. Bind declared targets into the legacy value
            # namespace consumed by this runtime seam.
            document = workflow.document
            port_names = {
                (node.get("id"), port.get("id")): port.get("name")
                for node in document.get("graph", {}).get("nodes", [])
                if isinstance(node, dict)
                for port in node.get("ports", [])
                if isinstance(port, dict)
            }
            for item in document.get("interface", {}).get("inputs", []):
                if not isinstance(item, dict) or item.get("name") not in inputs:
                    continue
                target = item.get("target")
                if not isinstance(target, dict):
                    continue
                node_id = str(target.get("node_id") or "")
                port_name = str(port_names.get((node_id, target.get("port_id"))) or "")
                if node_id and port_name:
                    inputs.setdefault(f"{node_id}.{port_name}", inputs[item["name"]])
        work_root = work_root or workflow.work_root
        run_id = run_id or _new_id("wfrun")
        thread_id = thread_id or f"workflow_thread_{uuid.uuid4().hex}"
        workflow_id = ensure_workflow_id(workflow)

        try:
            validate_workflow(
                workflow,
                start_node=start_node,
                single_node=single_node,
                node_registry=self.node_registry,
            )
            _validate_run_inputs(workflow, inputs, dict(prior_values or {}))
            self._validate_executable_nodes(workflow)
        except (WorkflowValidationError, WorkflowExecutorError) as exc:
            return WorkflowRunResult(
                status="failed",
                error=str(exc),
                run_id=run_id,
            )

        order = _topological_order(workflow)
        if order is None:
            return WorkflowRunResult(status="failed", error="workflow graph has a cycle", run_id=run_id)
        if single_node:
            order = [single_node]
        elif start_node:
            idx = order.index(start_node)
            # From-node execution is a deliberate subgraph boundary. Mark the
            # prefix skipped so a resumed/partial result never presents those
            # nodes as idle or accidentally tries to execute them later.
            for skipped_id in order[:idx]:
                state = (prior_node_states or {}).get(skipped_id) or None
                if state is None:
                    # ``node_states`` is initialized below; retain a marker in
                    # a temporary map by seeding ``prior_node_states``.
                    if prior_node_states is None:
                        prior_node_states = {}
                    prior_node_states.setdefault(
                        skipped_id,
                        WorkflowNodeState(node_id=skipped_id, status="skipped", finished_at=self.clock()),
                    )
                elif state.status == "idle":
                    state.status = "skipped"
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
            elif "." in name and name.rsplit(".", 1)[-1] in inputs:
                # Convenience for partial execution: callers may provide a
                # single unambiguous port name (``value``) instead of the
                # canonical ``node.value`` input key.
                values[key] = inputs[name.rsplit(".", 1)[-1]]
            elif key not in values:
                values[key] = _workflow_input_default(workflow, name)

        node_states: dict[str, WorkflowNodeState] = dict(prior_node_states or {})
        for node in workflow.nodes:
            node_states.setdefault(node.id, WorkflowNodeState(node_id=node.id))

        active = _ActiveWorkflowRun(
            workflow=workflow,
            order=order,
            node_states=node_states,
            values=values,
            inputs=dict(inputs),
            execution_context=execution_context,
        )
        active_key = (thread_id, run_id)
        self._active_runs[active_key] = active
        if self.emit_lifecycle_events:
            await self._emit_run_status(
                "running",
                thread_id,
                run_id,
                workflow_id=workflow_id,
            )
        cancel_event = (
            execution_context.cancellation
            if execution_context is not None and execution_context.cancellation is not None
            else self._cancel_event(thread_id)
        )
        steps_taken = 0

        for node_id in order:
            active.current_node_id = node_id
            active.steps_taken = steps_taken
            if _cancellation_requested(cancel_event):
                _mark_cancelled(node_states, workflow, order, order.index(node_id))
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
                await self._persist_active_snapshot(
                    workflow=workflow,
                    thread_id=thread_id,
                    run_id=run_id,
                    inputs=inputs,
                    node_states=node_states,
                    values=values,
                    steps_remaining=len(order) - steps_taken,
                )
                if self.emit_lifecycle_events:
                    await self._emit_run_status(
                        "paused",
                        thread_id,
                        run_id,
                        workflow_id=workflow_id,
                        node_id=node.id,
                        steps_remaining=len(order) - steps_taken,
                    )
                return WorkflowRunResult(
                    status="paused",
                    node_states=node_states,
                    values=values,
                    run_id=run_id,
                    steps_remaining=len(order) - steps_taken,
                )

            try:
                bound_inputs = _bind_inputs(
                    node,
                    workflow,
                    values,
                    execution_context=execution_context,
                )
            except WorkflowExpressionError as exc:
                # Edge expressions run while inputs are bound, before the
                # normal node retry boundary.  Preserve the same failed-node
                # shape used by builtin executor errors instead of leaking an
                # exception out of the public Runner API.
                error_msg = str(exc)
                state.status = "error"
                state.error = error_msg
                state.finished_at = self.clock()
                await self._emit_state(
                    node,
                    "failed",
                    thread_id,
                    run_id,
                    workflow_id=workflow_id,
                    error=error_msg,
                )
                await self._persist_active_snapshot(
                    workflow=workflow,
                    thread_id=thread_id,
                    run_id=run_id,
                    inputs=inputs,
                    node_states=node_states,
                    values=values,
                    steps_remaining=max(0, len(order) - steps_taken - 1),
                )
                return WorkflowRunResult(
                    status="failed",
                    node_states=node_states,
                    values=values,
                    run_id=run_id,
                    error=error_msg,
                    steps_remaining=max(0, len(order) - steps_taken - 1),
                )

            # Skip cascade: when every bound input is the sentinel, this node
            # sits on a skipped path — skip it and propagate the sentinel.
            if bound_inputs and all(v == SKIP_SENTINEL for v in bound_inputs.values()):
                state.status = "skipped"
                state.finished_at = self.clock()
                for port in node.output_ports():
                    values[f"{node.id}.{port.name}"] = SKIP_SENTINEL
                await self._emit_state(node, "skipped", thread_id, run_id, workflow_id=workflow_id)
                await self._persist_active_snapshot(
                    workflow=workflow,
                    thread_id=thread_id,
                    run_id=run_id,
                    inputs=inputs,
                    node_states=node_states,
                    values=values,
                    steps_remaining=len(order) - steps_taken - 1,
                )
                continue

            builtin_executor = self._builtin_executor_name(node)
            if builtin_executor in {"wait_event", "approval"}:
                if state.status == "waiting" and state.wait_descriptor:
                    return WorkflowRunResult(
                        status="paused",
                        node_states=node_states,
                        values=values,
                        run_id=run_id,
                        steps_remaining=max(0, len(order) - steps_taken),
                        wait_descriptor=dict(state.wait_descriptor),
                    )
                descriptor = self._wait_descriptor(
                    node,
                    workflow=workflow,
                    thread_id=thread_id,
                    run_id=run_id,
                    kind=builtin_executor,
                )
                state.status = "waiting"
                state.started_at = state.started_at or self.clock()
                state.finished_at = None
                state.wait_descriptor = descriptor
                await self._emit_state(node, "waiting", thread_id, run_id, workflow_id=workflow_id)
                await self._append_durable_event(
                    WorkflowRunEvent(
                        event_id=f"{run_id}:wait:{node.id}:created",
                        run_id=run_id,
                        kind="wait.created",
                        workflow_id=workflow_id,
                        workflow_revision=workflow.revision,
                        node_id=node.id,
                        payload=_json_copy(descriptor),
                    )
                )
                await self._persist_active_snapshot(
                    workflow=workflow,
                    thread_id=thread_id,
                    run_id=run_id,
                    inputs=inputs,
                    node_states=node_states,
                    values=values,
                    steps_remaining=max(0, len(order) - steps_taken),
                )
                return WorkflowRunResult(
                    status="paused",
                    node_states=node_states,
                    values=values,
                    run_id=run_id,
                    steps_remaining=max(0, len(order) - steps_taken),
                    wait_descriptor=descriptor,
                )

            state.status = "running"
            state.started_at = self.clock()
            await self._emit_state(node, "running", thread_id, run_id, workflow_id=workflow_id)

            try:
                outputs = await self._execute_with_retries(
                    node, bound_inputs, work_root, state, values,
                    thread_id=thread_id, run_id=run_id,
                    execution_context=execution_context,
                )
            except asyncio.CancelledError:
                if _pause_requested(execution_context):
                    state.status = "idle"
                    state.error = state.error or "interrupted"
                    state.finished_at = None
                    steps_remaining = max(0, len(order) - steps_taken)
                    await self._persist_active_snapshot(
                        workflow=workflow,
                        thread_id=thread_id,
                        run_id=run_id,
                        inputs=inputs,
                        node_states=node_states,
                        values=values,
                        steps_remaining=steps_remaining,
                    )
                    if self.emit_lifecycle_events:
                        await self._emit_run_status(
                            "paused",
                            thread_id,
                            run_id,
                            workflow_id=workflow_id,
                            node_id=node.id,
                            steps_remaining=steps_remaining,
                        )
                    return WorkflowRunResult(
                        status="paused",
                        node_states=node_states,
                        values=values,
                        run_id=run_id,
                        steps_remaining=steps_remaining,
                    )
                state.status = "cancelled"
                state.finished_at = self.clock()
                _mark_cancelled(node_states, workflow, order, order.index(node_id) + 1)
                await self._emit_state(
                    node, "cancelled", thread_id, run_id,
                    workflow_id=workflow_id, error="cancelled",
                )
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
                    state.output = outputs.get(fb_port)
                    state.finished_at = self.clock()
                    await self._emit_state(
                        node, "completed", thread_id, run_id,
                        workflow_id=workflow_id, error=error_msg,
                    )
                    for port_name, value in outputs.items():
                        values[f"{node.id}.{port_name}"] = value
                    steps_taken += 1
                    await self._persist_active_snapshot(
                        workflow=workflow,
                        thread_id=thread_id,
                        run_id=run_id,
                        inputs=inputs,
                        node_states=node_states,
                        values=values,
                        steps_remaining=len(order) - steps_taken,
                    )
                    continue
                if strategy == "skip":
                    state.status = "skipped"
                    state.error = error_msg
                    state.finished_at = self.clock()
                    for port in node.output_ports():
                        values[f"{node.id}.{port.name}"] = SKIP_SENTINEL
                    await self._emit_state(
                        node, "skipped", thread_id, run_id,
                        workflow_id=workflow_id, error=error_msg,
                    )
                    await self._persist_active_snapshot(
                        workflow=workflow,
                        thread_id=thread_id,
                        run_id=run_id,
                        inputs=inputs,
                        node_states=node_states,
                        values=values,
                        steps_remaining=len(order) - steps_taken,
                    )
                    continue
                # Default: abort the whole run.
                state.status = "error"
                state.error = error_msg
                state.finished_at = self.clock()
                await self._emit_state(
                    node, "failed", thread_id, run_id,
                    workflow_id=workflow_id, error=error_msg,
                )
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
            default_port = _default_output_port(node)
            if default_port in outputs:
                state.output = outputs[default_port]
            else:
                state.output = outputs[next(iter(outputs))] if outputs else None
            state.finished_at = self.clock()
            await self._emit_state(
                node,
                "completed",
                thread_id,
                run_id,
                workflow_id=workflow_id,
                cache_status=state.cache_status,
                cache_key=state.cache_key,
            )
            steps_taken += 1
            await self._persist_active_snapshot(
                workflow=workflow,
                thread_id=thread_id,
                run_id=run_id,
                inputs=inputs,
                node_states=node_states,
                values=values,
                steps_remaining=len(order) - steps_taken,
            )
            if self.emit_lifecycle_events:
                await self._emit_run_status(
                    "progress",
                    thread_id,
                    run_id,
                    workflow_id=workflow_id,
                    node_id=node.id,
                    steps_completed=steps_taken,
                    steps_remaining=len(order) - steps_taken,
                    cache_status=state.cache_status,
                    cache_key=state.cache_key,
                )

        unresolved = [
            node_id
            for node_id in order
            if node_states.get(node_id) is not None
            and node_states[node_id].status == "idle"
        ]
        if unresolved:
            missing = unresolved[0]
            return WorkflowRunResult(
                status="failed",
                node_states=node_states,
                values=values,
                error=f"inputs are not ready for node '{missing}'",
                run_id=run_id,
                steps_remaining=len(unresolved),
            )
        output = _resolve_output(workflow, values)
        return WorkflowRunResult(
            status="completed",
            output=output,
            node_states=node_states,
            values=values,
            run_id=run_id,
            steps_remaining=0,
        )

    def _cancelled_result(self, key: tuple[str, str]) -> WorkflowRunResult:
        """Build a complete cancellation result from the in-flight snapshot."""
        active = self._active_runs.get(key)
        if active is None:
            return WorkflowRunResult(
                status="cancelled",
                error="cancelled",
                run_id=key[1],
            )
        current_id = active.current_node_id
        current = active.node_states.get(current_id)
        if current is not None and current.status in {"idle", "running"}:
            current.status = "cancelled"
            current.error = current.error or "cancelled"
            current.finished_at = current.finished_at or self.clock()
        for node_id in active.order:
            state = active.node_states.get(node_id)
            if state is not None and state.status == "idle":
                state.status = "cancelled"
                state.error = state.error or "cancelled"
                state.finished_at = state.finished_at or self.clock()
        remaining = sum(
            1
            for node_id in active.order
            if active.node_states.get(node_id) is not None
            and active.node_states[node_id].status not in {"done", "skipped", "error"}
        )
        return WorkflowRunResult(
            status="cancelled",
            node_states=active.node_states,
            values=active.values,
            error="cancelled",
            run_id=key[1],
            steps_remaining=remaining,
        )

    def _paused_result(self, key: tuple[str, str]) -> WorkflowRunResult:
        """Build a resumable result from an in-flight run after shutdown."""
        active = self._active_runs.get(key)
        if active is None:
            return WorkflowRunResult(status="paused", run_id=key[1])
        current = active.node_states.get(active.current_node_id)
        # The interrupted node may have performed a partial side effect.  Keep
        # its attempt count but make it runnable again on the next invocation;
        # completed/skipped nodes remain durable and are not re-executed.
        if current is not None and current.status == "running":
            current.status = "idle"
            current.error = current.error or "interrupted"
            current.finished_at = None
        return WorkflowRunResult(
            status="paused",
            node_states=active.node_states,
            values=active.values,
            run_id=key[1],
            steps_remaining=max(0, len(active.order) - active.steps_taken),
        )

    async def interrupt(self, thread_id: str, run_id: str) -> WorkflowRunResult | None:
        """Persist a resumable snapshot for a queue/process shutdown.

        This is intentionally separate from user cancellation: queue shutdown
        asks the runner to preserve progress, while an explicit cancel keeps
        the terminal ``cancelled`` result.
        """
        key = (str(thread_id or ""), str(run_id or ""))
        active = self._active_runs.get(key)
        if active is None:
            return None
        result = self._paused_result(key)
        self._run_snapshots[key] = WorkflowRunResult.from_dict(result.to_dict())
        await self._persist_snapshot(
            key[0],
            key[1],
            result,
            workflow=active.workflow,
            inputs=active.inputs,
        )
        return result

    def _wait_descriptor(
        self,
        node: WorkflowNode,
        *,
        workflow: WorkflowDef,
        thread_id: str,
        run_id: str,
        kind: str,
    ) -> dict[str, Any]:
        created_at = self.clock()
        raw_timeout = node.config.get("timeout_seconds", node.config.get("timeout"))
        try:
            timeout_seconds = float(raw_timeout) if raw_timeout not in (None, "") else None
        except (TypeError, ValueError):
            timeout_seconds = None
        if timeout_seconds is not None and timeout_seconds <= 0:
            timeout_seconds = None
        event_type = str(
            node.config.get("event_type")
            or node.config.get("eventType")
            or ("approval" if kind == "approval" else "event")
        ).strip()
        return {
            "kind": kind,
            "thread_id": thread_id,
            "run_id": run_id,
            "workflow_id": workflow.id,
            "workflow_revision": workflow.revision,
            "definition_digest": definition_digest(workflow.to_dict()),
            "node_id": node.id,
            "event_type": event_type,
            "resume_token": secrets.token_urlsafe(24),
            "created_at": created_at.isoformat(),
            "deadline": (
                (created_at + timedelta(seconds=timeout_seconds)).isoformat()
                if timeout_seconds is not None
                else None
            ),
        }

    async def signal(
        self,
        *,
        thread_id: str,
        run_id: str,
        resume_token: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        decision: str = "",
        _signal_lock_held: bool = False,
        _process_signal_lock_held: bool = False,
        _durable_signal_claim_held: bool = False,
    ) -> WorkflowRunResult:
        """Resume a persisted wait without polling or occupying a worker."""
        thread_id = str(thread_id or "").strip()
        run_id = str(run_id or "").strip()
        resume_token = str(resume_token or "")
        event_type = str(event_type or "").strip()
        if not thread_id or not run_id or not resume_token or not event_type:
            raise ValueError("thread_id, run_id, resume_token and event_type are required")
        if not _signal_lock_held:
            signal_key = (thread_id, run_id)
            signal_lock = self._signal_locks.setdefault(signal_key, asyncio.Lock())
            self._signal_lock_users[signal_key] = self._signal_lock_users.get(signal_key, 0) + 1
            try:
                async with signal_lock:
                    return await self.signal(
                        thread_id=thread_id,
                        run_id=run_id,
                        resume_token=resume_token,
                        event_type=event_type,
                        payload=payload,
                        decision=decision,
                        _signal_lock_held=True,
                        _process_signal_lock_held=_process_signal_lock_held,
                        _durable_signal_claim_held=_durable_signal_claim_held,
                    )
            finally:
                remaining_users = self._signal_lock_users.get(signal_key, 1) - 1
                if remaining_users <= 0:
                    self._signal_lock_users.pop(signal_key, None)
                    if self._signal_locks.get(signal_key) is signal_lock:
                        self._signal_locks.pop(signal_key, None)
                else:
                    self._signal_lock_users[signal_key] = remaining_users

        journal_events = await self.event_store.list(run_id) if self.event_store is not None else []
        if not _process_signal_lock_held:
            process_key = (
                _coordination_store_key(self.event_store, self.snapshot_store),
                thread_id,
                run_id,
            )
            process_lock = _PROCESS_SIGNAL_LOCKS.setdefault(process_key, asyncio.Lock())
            _PROCESS_SIGNAL_LOCK_USERS[process_key] = _PROCESS_SIGNAL_LOCK_USERS.get(process_key, 0) + 1
            try:
                async with process_lock:
                    # Re-enter and refresh journal/snapshot visibility after
                    # acquiring the shared claim; the pre-claim read is only
                    # advisory and may race another Runner instance.
                    return await self.signal(
                        thread_id=thread_id,
                        run_id=run_id,
                        resume_token=resume_token,
                        event_type=event_type,
                        payload=payload,
                        decision=decision,
                        _signal_lock_held=True,
                        _process_signal_lock_held=True,
                        _durable_signal_claim_held=_durable_signal_claim_held,
                    )
            finally:
                remaining_users = _PROCESS_SIGNAL_LOCK_USERS.get(process_key, 1) - 1
                if remaining_users <= 0:
                    _PROCESS_SIGNAL_LOCK_USERS.pop(process_key, None)
                    if _PROCESS_SIGNAL_LOCKS.get(process_key) is process_lock:
                        _PROCESS_SIGNAL_LOCKS.pop(process_key, None)
                else:
                    _PROCESS_SIGNAL_LOCK_USERS[process_key] = remaining_users
        if self.claim_store is not None and not _durable_signal_claim_held:
            return await self._execute_durable_claim(
                "signal",
                thread_id,
                run_id,
                lambda: self.signal(
                    thread_id=thread_id,
                    run_id=run_id,
                    resume_token=resume_token,
                    event_type=event_type,
                    payload=payload,
                    decision=decision,
                    _signal_lock_held=True,
                    _process_signal_lock_held=True,
                    _durable_signal_claim_held=True,
                ),
                request_fingerprint=_claim_request_fingerprint(
                    {"resume_token": resume_token, "event_type": event_type}
                ),
            )
        accepted = next(
            (
                event for event in reversed(journal_events)
                if event.kind == "wait.signalled"
                and secrets.compare_digest(
                    str(event.payload.get("resume_token") or ""), resume_token
                )
            ),
            None,
        )
        if accepted is not None:
            if str(accepted.payload.get("event_type") or "") != event_type:
                raise ValueError("workflow signal event type mismatch")
            terminal = next(
                (
                    event for event in reversed(journal_events)
                    if event.kind in {"run.completed", "run.failed", "run.cancelled"}
                    and isinstance(event.payload.get("result"), dict)
                ),
                None,
            )
            if terminal is not None:
                return WorkflowRunResult.from_dict(terminal.payload["result"])

        if self.snapshot_store is None:
            raise LookupError("workflow durable snapshot store is not configured")
        envelope = await self.snapshot_store.get_dict(thread_id, run_id)
        if not envelope:
            if any(event.kind == "wait.signalled" for event in journal_events):
                raise ValueError("invalid workflow resume token")
            raise LookupError(f"waiting workflow run not found: {run_id}")
        previous = WorkflowRunResult.from_dict(envelope.get("result", envelope))
        descriptor = dict(previous.wait_descriptor or {})
        if not descriptor:
            waiting_state = next(
                (state for state in previous.node_states.values() if state.status == "waiting"),
                None,
            )
            descriptor = dict(waiting_state.wait_descriptor) if waiting_state is not None else {}
        if not descriptor or descriptor.get("run_id") != run_id or descriptor.get("thread_id") != thread_id:
            raise ValueError("workflow run is not waiting for a signal")
        if accepted is not None and accepted.node_id != str(descriptor.get("node_id") or ""):
            # This signal was already consumed and the run has advanced to a
            # later wait. Return the current projection without replaying it.
            return previous
        if not secrets.compare_digest(str(descriptor.get("resume_token") or ""), resume_token):
            raise ValueError("invalid workflow resume token")
        if str(descriptor.get("event_type") or "") != event_type:
            raise ValueError("workflow signal event type mismatch")

        raw_definition = envelope.get("workflow_definition")
        if not isinstance(raw_definition, Mapping) or not raw_definition:
            raise LookupError("pinned workflow definition is unavailable for this waiting run")
        workflow = WorkflowDef.from_dict(dict(raw_definition))
        if isinstance(raw_definition.get("document"), Mapping):
            workflow.document = _json_copy(raw_definition["document"])
        pinned_revision = _as_int(envelope.get("workflow_revision"), default=workflow.revision)
        pinned_digest = str(envelope.get("definition_digest") or "")
        pinned_payload = {key: value for key, value in raw_definition.items() if key != "document"}
        if workflow.revision != pinned_revision or (
            pinned_digest and definition_digest(pinned_payload) != pinned_digest
        ):
            raise ValueError("pinned workflow definition identity is invalid")

        node_id = str(descriptor.get("node_id") or "")
        node = workflow.node(node_id)
        state = previous.node_states.get(node_id)
        if node is None or state is None or state.status != "waiting":
            raise ValueError("workflow waiting node is unavailable")
        deadline = _parse_dt(descriptor.get("deadline"))
        signal_payload = dict(payload or {})
        if deadline is not None and self.clock() >= deadline:
            wait_result: dict[str, Any] = {
                "status": "timed_out",
                "event_type": event_type,
                "payload": None,
            }
        elif descriptor.get("kind") == "approval":
            normalized = str(decision or signal_payload.get("decision") or "").strip().lower()
            aliases = {"approved": "approve", "accepted": "approve", "rejected": "reject", "denied": "reject"}
            normalized = aliases.get(normalized, normalized)
            if normalized not in {"approve", "reject"}:
                raise ValueError("approval decision must be approve or reject")
            wait_result = {
                "status": "approved" if normalized == "approve" else "rejected",
                "decision": normalized,
                "event_type": event_type,
                "payload": signal_payload,
            }
        else:
            wait_result = {"status": "received", "event_type": event_type, "payload": signal_payload}

        if accepted is None:
            await self._append_durable_event(
                WorkflowRunEvent(
                    event_id=f"{run_id}:wait:{node_id}:signalled",
                    run_id=run_id,
                    kind="wait.signalled",
                    workflow_id=workflow.id,
                    workflow_revision=workflow.revision,
                    node_id=node_id,
                    payload={
                        "resume_token": resume_token,
                        "event_type": event_type,
                        "result": _json_copy(wait_result),
                    },
                )
            )
        else:
            wait_result = dict(accepted.payload.get("result") or wait_result)

        output_port = _default_output_port(node) or "output"
        previous.values[f"{node.id}.{output_port}"] = _json_copy(wait_result)
        state.status = "done"
        state.output = _json_copy(wait_result)
        state.error = ""
        state.finished_at = self.clock()
        return await self.run(
            workflow,
            inputs=dict(envelope.get("inputs") or {}),
            work_root=workflow.work_root,
            thread_id=thread_id,
            run_id=run_id,
            prior_values=previous.values,
            prior_node_states=previous.node_states,
        )

    async def shutdown(self) -> None:
        """Cancel and join Runner-owned workflow tasks during plugin unload."""
        current = asyncio.current_task()
        tasks = [
            task
            for task in self._active_tasks.values()
            if task is not current and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._active_tasks.clear()
        self._active_runs.clear()
        self._terminal_results.clear()
        for key in [key for key, users in self._run_lock_users.items() if users <= 0]:
            self._run_lock_users.pop(key, None)
            self._run_locks.pop(key, None)
        for key in [key for key, users in self._signal_lock_users.items() if users <= 0]:
            self._signal_lock_users.pop(key, None)
            self._signal_locks.pop(key, None)

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
        execution_context: WorkflowExecutionContext | None = None,
    ) -> dict[str, Any]:
        policy = NodeExecutionPolicy.from_config(node.config)
        cache_key = ""
        # A lazy value has deliberately not been observed yet.  Including the
        # resolver object in a cache key would be unstable and, more
        # importantly, would turn a declared lazy input into an eager read.
        cache_enabled = (
            self._cache_enabled(node)
            and not _contains_lazy_input(bound_inputs)
            and not _contains_credential_ref(node.config)
            and not _contains_credential_ref(bound_inputs)
        )
        # Capability/resource declarations are checked before the first
        # durable attempt event or executor side effect.
        self._check_node_authority(node, execution_context)
        if cache_enabled:
            workflow_id = ""
            workflow_revision = 0
            active = self._active_runs.get((thread_id, run_id))
            if active is not None:
                workflow_id = active.workflow.id
                workflow_revision = active.workflow.revision
            cache_key = content_signature(
                workflow_id=workflow_id,
                workflow_revision=workflow_revision,
                node_id=node.id,
                node_kind=node.kind,
                node_config=node.config,
                bound_inputs=bound_inputs,
            )
            state.cache_key = cache_key
            lookup = await self.cache_store.lookup(cache_key)
            if lookup.hit:
                state.cache_status = "hit"
                state.attempts = max(1, state.attempts)
                now = self.clock()
                state.attempt_history.append({
                    "number": state.attempts,
                    "status": "cache_hit",
                    "started_at": now.isoformat(),
                    "finished_at": now.isoformat(),
                    "cache_status": "hit",
                    "cache_key": cache_key,
                })
                return dict(lookup.value) if isinstance(lookup.value, dict) else {"output": lookup.value}
            state.cache_status = "miss"
        else:
            state.cache_status = "bypass"
            state.cache_key = ""
        last_exc: Exception | None = None
        resuming_attempt = bool(state.attempt_id and state.idempotency_key and state.error == "interrupted")
        first_number = max(1, state.attempts if resuming_attempt else state.attempts + 1)
        # A persisted in-flight attempt is always allowed to finish once with
        # the same idempotency key, even when its configured retry budget is 0.
        final_number = max(first_number, policy.max_attempts)
        for number in range(first_number, final_number + 1):
            if resuming_attempt and number == first_number:
                attempt_id, idempotency_key = state.attempt_id, state.idempotency_key
            else:
                attempt_id, idempotency_key = attempt_identity(run_id, node.id, number)
            state.attempts = number
            state.attempt_id = attempt_id
            state.idempotency_key = idempotency_key
            state.error = ""
            attempt_started_at = self.clock()
            attempt_audit: dict[str, Any] = {}
            attempt_record: dict[str, Any] = {
                "attempt_id": attempt_id,
                "number": number,
                "status": "started",
                "started_at": attempt_started_at.isoformat(),
                "finished_at": None,
            }
            state.attempt_history.append(attempt_record)
            attempt_context = execution_context
            builtin_name = self._builtin_executor_name(node)
            engine_timeout = None if builtin_name in {"command", "script"} else policy.timeout_seconds
            # Preserve the legacy adapter's execution-context object identity
            # for direct, non-durable callers. Durable/plugin runs receive the
            # explicit attempt/idempotency boundary.
            if execution_context is not None and (self.event_store is not None or "execution" in node.config):
                attempt_context = replace(
                    execution_context,
                    event_metadata={
                        **execution_context.event_metadata,
                        "workflow_attempt_id": attempt_id,
                        "idempotency_key": idempotency_key,
                    },
                    environment={
                        **execution_context.environment,
                        "__workflow_timeout_seconds": engine_timeout,
                    },
                )
            if attempt_context is not None and attempt_context.runtime_credentials:
                attempt_context = replace(attempt_context, runtime_credentials={})
            await self._append_durable_event(
                WorkflowRunEvent(
                    event_id=f"{attempt_id}:started",
                    run_id=run_id,
                    kind="attempt.started",
                    workflow_id=self._active_runs.get((thread_id, run_id)).workflow.id if self._active_runs.get((thread_id, run_id)) else "",
                    workflow_revision=self._active_runs.get((thread_id, run_id)).workflow.revision if self._active_runs.get((thread_id, run_id)) else 0,
                    node_id=node.id,
                    attempt_id=attempt_id,
                    payload={"number": number, "idempotency_key": idempotency_key},
                )
            )
            active_run = self._active_runs.get((thread_id, run_id))
            if active_run is not None:
                await self._persist_active_snapshot(
                    workflow=active_run.workflow,
                    thread_id=thread_id,
                    run_id=run_id,
                    inputs=active_run.inputs,
                    node_states=active_run.node_states,
                    values=active_run.values,
                    steps_remaining=max(0, len(active_run.order) - active_run.steps_taken),
                )
            try:
                # Resolve each attempt into a fresh node/context pair.  The
                # caller's node/context are shared graph inputs and remain
                # reference-only, while a retry receives a new short-lived
                # credential scope.
                attempt_execution_context = attempt_context
                execution_node = node
                execution_inputs = bound_inputs
                resolved_credentials: dict[str, Any] = {}
                resolved_secrets: list[Any] = []
                if _contains_credential_ref(node.config) or _contains_credential_ref(bound_inputs):
                    base_context = attempt_context or WorkflowExecutionContext()
                    resolved_config = await _resolve_workflow_credentials(
                        node.config,
                        self.credential_resolver,
                        execution_context,
                        resolved_credentials,
                        resolved_secrets,
                        path=f"node[{node.id}].config",
                    )
                    resolved_inputs = await _resolve_workflow_credentials(
                        bound_inputs,
                        self.credential_resolver,
                        execution_context,
                        resolved_credentials,
                        resolved_secrets,
                        path=f"node[{node.id}].inputs",
                    )
                    execution_node = replace(node, config=resolved_config)
                    attempt_execution_context = replace(
                        base_context,
                        runtime_credentials=dict(resolved_credentials),
                    )
                    execution_inputs = resolved_inputs
                executor = self._executor_for_node(execution_node)
                builtin_executor = self._builtin_executor_name(execution_node)
                if executor is not None and builtin_executor is None:
                    # LazyInput objects are intentionally preserved for trusted
                    # plugin executors; they decide whether/when to resolve.
                    raw_result = await _await_with_context_cancel(
                        self._invoke_node_executor(
                            executor, execution_node, execution_inputs, attempt_execution_context
                        ),
                        attempt_execution_context,
                    )
                    normalized = normalize_node_execution_result(
                        _executor_result_to_legacy(raw_result, node=execution_node)
                    )
                    outputs = dict(normalized.outputs)
                    expansion = normalized.normalized_expansion()
                    if expansion is not None:
                        expanded_outputs = await _await_with_context_cancel(
                            self._execute_expansion(
                                execution_node,
                                expansion,
                                execution_inputs,
                                work_root,
                                thread_id,
                                run_id,
                                attempt_execution_context,
                            ),
                            attempt_execution_context,
                        )
                        outputs = {**outputs, **expanded_outputs}
                elif builtin_executor == "ai":
                    outputs = await _await_with_context_cancel(
                        self._execute_ai(
                            execution_node,
                            await _materialize_inputs(execution_inputs),
                            work_root,
                            attempt_execution_context,
                            audit=attempt_audit,
                        ),
                        attempt_execution_context,
                    )
                elif builtin_executor == "model":
                    outputs = await _await_with_context_cancel(
                        self._execute_ai_llm(
                            execution_node, await _materialize_inputs(execution_inputs), work_root,
                            str(execution_node.config.get("mode") or "single") == "loop",
                            attempt_execution_context, audit=attempt_audit,
                        ), attempt_execution_context,
                    )
                elif builtin_executor == "agent":
                    outputs = await _await_with_context_cancel(
                        self._execute_ai_agent(
                            execution_node, await _materialize_inputs(execution_inputs), work_root,
                            attempt_execution_context, audit=attempt_audit,
                        ), attempt_execution_context,
                    )
                elif builtin_executor == "content":
                    outputs = await _await_with_context_cancel(
                        self._execute_content(
                            execution_node,
                            await _materialize_inputs(execution_inputs),
                            work_root,
                        ),
                        attempt_execution_context,
                    )
                elif builtin_executor == "subgraph":
                    outputs = await _await_with_context_cancel(
                        self._execute_subgraph(
                            execution_node,
                            await _materialize_inputs(execution_inputs),
                            work_root,
                            thread_id,
                            run_id,
                            attempt_execution_context,
                        ),
                        attempt_execution_context,
                    )
                elif builtin_executor == "command":
                    outputs = await _await_with_context_cancel(
                        self._execute_command(
                            execution_node,
                            await _materialize_inputs(execution_inputs),
                            work_root,
                            attempt_execution_context,
                        ),
                        attempt_execution_context,
                    )
                elif builtin_executor == "script":
                    outputs = await _await_with_context_cancel(
                        self._execute_script(
                            execution_node,
                            await _materialize_inputs(execution_inputs),
                            work_root,
                            attempt_execution_context,
                        ),
                        attempt_execution_context,
                    )
                elif builtin_executor == "passthrough":
                    outputs = self._execute_passthrough(execution_node, await _materialize_inputs(execution_inputs))
                elif builtin_executor == "template":
                    outputs = self._execute_template(
                        execution_node,
                        await _materialize_inputs(execution_inputs),
                        execution_context=attempt_execution_context,
                    )
                elif builtin_executor == "condition":
                    outputs = self._execute_condition(
                        execution_node,
                        await _materialize_inputs(execution_inputs),
                        execution_context=attempt_execution_context,
                    )
                elif builtin_executor == "merge":
                    outputs = self._execute_merge(execution_node, await _materialize_inputs(execution_inputs))
                elif builtin_executor == "join":
                    outputs = self._execute_join(execution_node, await _materialize_inputs(execution_inputs))
                else:
                    raise WorkflowExecutorError(
                        f"workflow node executor is not registered: {node.kind}"
                    )
                safe_outputs = _redact_runtime_secrets(outputs, resolved_secrets)
                outputs = (
                    dict(safe_outputs)
                    if isinstance(safe_outputs, Mapping)
                    else {"output": safe_outputs}
                )
                if cache_enabled:
                    await self.cache_store.set(cache_key, outputs)
                await self._append_durable_event(
                    WorkflowRunEvent(
                        event_id=f"{attempt_id}:completed",
                        run_id=run_id,
                        kind="attempt.completed",
                        node_id=node.id,
                        attempt_id=attempt_id,
                        payload={"number": number, "idempotency_key": idempotency_key},
                    )
                )
                attempt_record["status"] = "completed"
                attempt_record["finished_at"] = self.clock().isoformat()
                if attempt_audit:
                    safe_audit = public_workflow_value(attempt_audit)
                    attempt_record["audit"] = safe_audit
                    state.audit = safe_audit
                return outputs
            except asyncio.CancelledError:
                attempt_record["status"] = "interrupted"
                attempt_record["finished_at"] = self.clock().isoformat()
                raise
            except Exception as exc:  # noqa: BLE001 — retry boundary
                timed_out = isinstance(exc, TimeoutError)
                error_text = _redact_exception_text(exc, locals().get("resolved_secrets", []))
                last_exc = (
                    RuntimeError(f"node execution timed out after {policy.timeout_seconds}s")
                    if timed_out and policy.timeout_seconds is not None
                    else RuntimeError(error_text)
                )
                attempt_record["status"] = "timed_out" if timed_out else "failed"
                attempt_record["finished_at"] = self.clock().isoformat()
                attempt_record["error"] = _redact_exception_text(
                    last_exc, locals().get("resolved_secrets", [])
                )
                await self._append_durable_event(
                    WorkflowRunEvent(
                        event_id=f"{attempt_id}:{'timed_out' if timed_out else 'failed'}",
                        run_id=run_id,
                        kind=f"attempt.{'timed_out' if timed_out else 'failed'}",
                        node_id=node.id,
                        attempt_id=attempt_id,
                        payload={
                            "number": number,
                            "idempotency_key": idempotency_key,
                            "error": _redact_exception_text(last_exc, locals().get("resolved_secrets", [])),
                        },
                    )
                )
                if number < final_number:
                    await asyncio.sleep(policy.delay_after(number - first_number))
        raise last_exc if last_exc is not None else RuntimeError("node execution failed")

    def _cache_enabled(self, node: WorkflowNode) -> bool:
        """Return true only for an explicit pure + deterministic declaration."""
        if node.config.get("cache") is False or node.config.get("cache_enabled") is False:
            return False
        spec = self.node_registry.get(node.kind) if self.node_registry is not None else None
        pure = node.config.get("pure") if "pure" in node.config else (spec.pure if spec else False)
        deterministic = (
            node.config.get("deterministic")
            if "deterministic" in node.config
            else (spec.deterministic if spec else False)
        )
        return pure is True and deterministic is True

    async def _invoke_node_executor(
        self,
        executor: NodeExecutor,
        node: WorkflowNode,
        bound_inputs: dict[str, Any],
        execution_context: WorkflowExecutionContext | None,
    ) -> Any:
        """Call a registered executor through the explicit adapter boundary."""
        # ``LegacyNodeExecutorAdapter`` accepts both modern ``context`` and
        # legacy ``execution_context`` call signatures.  Adapters supplied by
        # a host may expose the protocol directly, so keep a small fallback
        # for objects that implement the method but are not wrapped.
        call = getattr(executor, "execute", None)
        if not callable(call):
            raise WorkflowExecutorError("workflow node executor has no execute()")
        packet = _packet_view_for_inputs(bound_inputs)
        return await _call_with_supported_kwargs(
            call,
            {
                "node": node,
                "inputs": bound_inputs,
                "bound_inputs": bound_inputs,
                "packet": packet,
                "data_packet": packet,
                "context": execution_context,
                "execution_context": execution_context,
            },
        )

    async def _execute_expansion(
        self,
        node: WorkflowNode,
        expansion: WorkflowExpansion,
        bound_inputs: dict[str, Any],
        work_root: str,
        thread_id: str,
        run_id: str,
        execution_context: WorkflowExecutionContext | None,
    ) -> dict[str, Any]:
        """Run a trusted executor's bounded declarative expansion.

        Expansion data is converted to the normal workflow model and then
        passes through the same validation, cycle, depth, permission, and
        cancellation gates as a saved subgraph.  There is no import/eval path
        from the expansion payload.
        """
        try:
            _assert_json_value(expansion.to_dict())
        except (TypeError, ValueError) as exc:
            raise WorkflowExpansionError(
                "workflow expansion must contain JSON-compatible data only"
            ) from exc
        sub_def = self._expansion_definition(node, expansion)
        if len(sub_def.nodes) > self.max_expansion_nodes:
            raise WorkflowExpansionError(
                f"workflow expansion exceeds node limit ({self.max_expansion_nodes})"
            )
        if len(sub_def.edges) > self.max_expansion_edges:
            raise WorkflowExpansionError(
                f"workflow expansion exceeds edge limit ({self.max_expansion_edges})"
            )
        _assert_json_workflow_data(sub_def)
        try:
            validate_workflow(sub_def, node_registry=self.node_registry)
            self._validate_executable_nodes(sub_def)
        except (WorkflowValidationError, WorkflowExecutorError) as exc:
            raise WorkflowExpansionError(str(exc)) from exc
        inputs = dict(expansion.inputs or {})
        if not inputs:
            inputs = self._map_entry_inputs(sub_def, bound_inputs)
        active_parent = self._active_runs.get((thread_id, run_id))
        parent_workflow_id = str(
            active_parent.workflow.id or active_parent.workflow.name
            if active_parent is not None
            else ""
        )
        child_context = self._child_context(
            execution_context,
            session_id=thread_id,
            run_id=run_id,
            call_id=node.id,
            child_workflow_id=str(sub_def.id or sub_def.name),
            parent_workflow_id=parent_workflow_id,
        )
        result = await self.run(
            sub_def,
            inputs=inputs,
            work_root=work_root,
            thread_id=f"{thread_id}.expand",
            run_id=f"{run_id}.expand",
            execution_context=child_context,
        )
        if result.status == "cancelled":
            raise asyncio.CancelledError()
        if result.status != "completed":
            raise WorkflowExpansionError(
                f"workflow expansion failed: {result.error or result.status}"
            )
        value: Any = result.output
        if expansion.output_port:
            value = result.values.get(expansion.output_port, value)
        out_ports = node.output_ports()
        if out_ports and isinstance(value, dict):
            return {port.name: value.get(port.name) for port in out_ports}
        return {_default_output_port(node) or "output": value}

    def _expansion_definition(
        self,
        node: WorkflowNode,
        expansion: WorkflowExpansion,
    ) -> WorkflowDef:
        """Convert a ``WorkflowExpansion`` wire object to a WorkflowDef."""
        raw_subgraph = expansion.subgraph
        if raw_subgraph is not None:
            if isinstance(raw_subgraph, WorkflowDef):
                # Copy the definition so an executor cannot mutate the host's
                # saved object while the ephemeral graph runs.
                return WorkflowDef.from_dict(raw_subgraph.to_dict())
            if not isinstance(raw_subgraph, Mapping):
                raise WorkflowExpansionError("workflow expansion subgraph must be an object")
            try:
                return WorkflowDef.from_dict(dict(raw_subgraph))
            except (TypeError, ValueError) as exc:
                raise WorkflowExpansionError("workflow expansion subgraph is invalid") from exc
        raw_nodes = list(expansion.nodes or ())
        raw_edges = list(expansion.edges or ())
        if not raw_nodes:
            raise WorkflowExpansionError("workflow expansion requires nodes or subgraph")
        nodes: list[WorkflowNode] = []
        for raw in raw_nodes:
            if isinstance(raw, WorkflowNode):
                nodes.append(WorkflowNode.from_dict(raw.to_dict()))
            elif isinstance(raw, dict):
                nodes.append(WorkflowNode.from_dict(raw))
            else:
                raise WorkflowExpansionError("workflow expansion node must be an object")
        edges: list[WorkflowEdge] = []
        for raw in raw_edges:
            if isinstance(raw, WorkflowEdge):
                edges.append(WorkflowEdge.from_dict(raw.to_dict()))
            elif isinstance(raw, dict):
                edges.append(WorkflowEdge.from_dict(raw))
            else:
                raise WorkflowExpansionError("workflow expansion edge must be an object")
        name = str(expansion.name or f"{node.id}:expansion").strip()
        definition = WorkflowDef(
            name=name,
            nodes=nodes,
            edges=edges,
            input_params=[
                _coerce_expansion_input_param(item)
                for item in expansion.input_params
            ],
            output_port=expansion.output_port,
        )
        ensure_workflow_id(definition, seed=f"workflow-expansion:{name}:{node.id}")
        return definition

    async def _execute_ai(
        self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str,
        execution_context: WorkflowExecutionContext | None = None,
        audit: dict[str, Any] | None = None,
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
            return await self._execute_ai_agent(
                node, bound_inputs, work_root, execution_context, audit=audit
            )
        return await self._execute_ai_llm(
            node, bound_inputs, work_root, mode == "loop", execution_context, audit=audit
        )

    async def _execute_ai_llm(
        self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str, is_loop: bool,
        execution_context: WorkflowExecutionContext | None = None,
        audit: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cfg = node.config
        instruction = str(cfg.get("instruction") or cfg.get("system_prompt") or "")
        output_format_text = str(cfg.get("output_format_text") or "")
        model_id = str(cfg.get("model_id") or _execution_model_id(execution_context) or "")
        temperature = cfg.get("temperature")
        reasoning_effort = str(cfg.get("reasoning_effort") or "")
        max_tokens = cfg.get("max_tokens")
        top_p = cfg.get("top_p")

        if self.model_invoker is None:
            raise RuntimeError("AI node requires a model invoker (none configured)")
        from lamtools_core.llm import ChatMessage, LLMRequest

        out_ports = node.output_ports()
        structured = bool(out_ports)

        def _interpolate(text: str) -> str:
            def _repl(m: re.Match) -> str:
                key = m.group(1).strip()
                val = bound_inputs.get(key)
                if val is None or val == SKIP_SENTINEL:
                    return ""
                return _serialize_prompt_value(val) if not isinstance(val, str) else val
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
            context_lines = [f"- {k}: {_serialize_prompt_value(v)}" for k, v in bound_inputs.items() if v is not None and v != SKIP_SENTINEL]
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
                metadata={
                    **({"reasoning_effort": reasoning_effort} if reasoning_effort else {}),
                    **(execution_context.metadata() if execution_context else {}),
                },
            )
            response = await self.model_invoker.invoke(
                request,
                context=execution_context,
                attachments=list(execution_context.attachments) if execution_context else [],
                runtime_snapshot=execution_context.runtime_snapshot if execution_context else None,
                snapshot=execution_context.snapshot if execution_context else None,
                environment=dict(execution_context.environment) if execution_context else {},
                capabilities=dict(execution_context.capabilities) if execution_context else {},
                trace_id=execution_context.trace_id if execution_context else "",
                lineage=list(execution_context.lineage) if execution_context else [],
            )
            if audit is not None:
                audit.update(_model_audit_metadata(response, model_id=model_id, rounds=i + 1))
            last_content = _response_content(response)
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
        self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str,
        execution_context: WorkflowExecutionContext | None = None,
        audit: dict[str, Any] | None = None,
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
                return _serialize_prompt_value(val) if not isinstance(val, str) else val
            return re.sub(r"\{\{(\w+)\}\}", _repl, text)

        goal_rendered = _interpolate(goal)
        context_lines = [f"- {k}: {_serialize_prompt_value(v)}" for k, v in bound_inputs.items() if v is not None and v != SKIP_SENTINEL and f"{{{{{k}}}}}" not in goal]
        task = goal_rendered + ("\n\nContext:\n" + "\n".join(context_lines) if context_lines else "")
        if structured:
            field_desc = ", ".join(f"{p.name}({_normalise_type(p.type)})" for p in out_ports)
            task += (
                f"\n\nYou MUST finish with a single JSON object containing these fields: {field_desc}. "
                "Output only the JSON."
            )
        raw_allowed = cfg.get("tools") or cfg.get("allowed_tools")
        allowed_tools = (
            [str(item) for item in raw_allowed if str(item).strip()]
            if isinstance(raw_allowed, list)
            else None
        )
        # Child agents inherit the parent's authority.  A node may narrow an
        # allow-list, but it cannot request tools outside a parent capability
        # declaration.
        inherited_allowed = _inherited_allowed_tools(execution_context)
        if inherited_allowed is not None:
            if allowed_tools is None:
                allowed_tools = list(inherited_allowed)
            else:
                allowed_tools = [name for name in allowed_tools if name in inherited_allowed]
        if self.agent_invoker is None:
            raise RuntimeError("AI agent mode requires an agent invoker (none configured)")
        kwargs: dict[str, Any] = {
            "task": task, "agent": str(cfg.get("agent") or ""),
            "model": str(cfg.get("model_id") or _execution_model_id(execution_context) or ""), "mode": str(cfg.get("mode") or ""),
            "attachments": list(execution_context.attachments) if execution_context else [],
            "allowed_tools": allowed_tools,
            "context": execution_context,
            "runtime_snapshot": execution_context.runtime_snapshot if execution_context else None,
            "snapshot": execution_context.snapshot if execution_context else None,
            "environment": dict(execution_context.environment) if execution_context else {},
            "capabilities": dict(execution_context.capabilities) if execution_context else {},
            "permissions": dict(execution_context.permissions) if execution_context else {},
            "trace_id": execution_context.trace_id if execution_context else "",
            "lineage": list(execution_context.lineage) if execution_context else [],
        }
        if execution_context is not None:
            kwargs.update({
                "parent_call_id": execution_context.parent_call_id or node.id,
                "parent_run_id": execution_context.parent_run_id,
                "parent_turn_id": execution_context.parent_turn_id,
                "execution_context": execution_context,
            })
        result = await _call_with_supported_kwargs(self.agent_invoker.invoke, kwargs)
        if audit is not None:
            audit.update(_agent_audit_metadata(result, node=node, configured_model=kwargs["model"]))
        if isinstance(result, str):
            content = result
        elif isinstance(result, dict):
            content = result.get(
                "message",
                result.get(
                    "content",
                    result.get("text", result.get("output", result.get("result", ""))),
                ),
            )
        else:
            content = getattr(result, "message", None) or getattr(result, "content", None) or ""
        if not isinstance(content, str):
            content = _summarize(content)
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

    def _execute_passthrough(self, node: WorkflowNode, bound_inputs: dict[str, Any]) -> dict[str, Any]:
        """Map same-name inputs to outputs, with a predictable single-value fallback."""
        active = {key: value for key, value in bound_inputs.items() if value != SKIP_SENTINEL}
        fallback = next(iter(active.values()), node.config.get("value"))
        outputs = node.output_ports()
        if not outputs:
            return {_default_output_port(node) or "output": fallback}
        return {port.name: active.get(port.name, fallback) for port in outputs}

    def _execute_template(
        self,
        node: WorkflowNode,
        bound_inputs: dict[str, Any],
        *,
        execution_context: WorkflowExecutionContext | None = None,
    ) -> dict[str, Any]:
        raw_template = node.config.get("template", node.config.get("text", node.config.get("content", "")))
        if _is_structured_expression(raw_template):
            rendered_value = _evaluate_workflow_expression(
                raw_template,
                node=node,
                bound_inputs=bound_inputs,
                execution_context=execution_context,
            )
            rendered = rendered_value if isinstance(rendered_value, str) else _summarize(rendered_value)
            return {port.name: rendered for port in node.output_ports()} or {
                _default_output_port(node) or "output": rendered
            }

        template = str(raw_template)

        def replace(match: re.Match[str]) -> str:
            value = bound_inputs.get(match.group(1).strip(), "")
            if value in (None, SKIP_SENTINEL):
                return ""
            return value if isinstance(value, str) else _summarize(value)

        rendered = re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", replace, template)
        return {port.name: rendered for port in node.output_ports()} or {
            _default_output_port(node) or "output": rendered
        }

    def _execute_condition(
        self,
        node: WorkflowNode,
        bound_inputs: dict[str, Any],
        *,
        execution_context: WorkflowExecutionContext | None = None,
    ) -> dict[str, Any]:
        raw_expression = node.config.get("condition") or node.config.get("expression") or "value"
        matched = _eval_condition(
            raw_expression,
            bound_inputs,
            node=node,
            execution_context=execution_context,
        )
        value = bound_inputs.get("value", next(iter(bound_inputs.values()), None))
        result: dict[str, Any] = {}
        for port in node.output_ports():
            lowered = port.name.strip().lower()
            if lowered in {"true", "yes", "then", "matched"}:
                result[port.name] = value if matched else SKIP_SENTINEL
            elif lowered in {"false", "no", "else", "unmatched"}:
                result[port.name] = value if not matched else SKIP_SENTINEL
            elif lowered in {"result", "condition", "matched_bool"}:
                result[port.name] = matched
            else:
                result[port.name] = value if matched else SKIP_SENTINEL
        return result or {"true": value if matched else SKIP_SENTINEL, "false": value if not matched else SKIP_SENTINEL}

    def _execute_merge(self, node: WorkflowNode, bound_inputs: dict[str, Any]) -> dict[str, Any]:
        active: list[Any] = []
        for value in bound_inputs.values():
            items = value if isinstance(value, list) else [value]
            active.extend(item for item in items if item != SKIP_SENTINEL)
        selected = active[0] if active else SKIP_SENTINEL
        return {port.name: selected for port in node.output_ports()} or {
            _default_output_port(node) or "output": selected
        }

    def _execute_join(self, node: WorkflowNode, bound_inputs: dict[str, Any]) -> dict[str, Any]:
        joined = {key: value for key, value in bound_inputs.items() if value != SKIP_SENTINEL}
        return {port.name: joined for port in node.output_ports()} or {
            _default_output_port(node) or "output": joined
        }

    async def _execute_subgraph(
        self,
        node: WorkflowNode,
        bound_inputs: dict[str, Any],
        work_root: str,
        thread_id: str,
        run_id: str,
        execution_context: WorkflowExecutionContext | None = None,
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
        active_parent = self._active_runs.get((thread_id, run_id))
        parent_workflow_id = str(
            active_parent.workflow.id or active_parent.workflow.name
            if active_parent is not None
            else ""
        )

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
                child_thread = f"{thread_id}.map{i}"
                child_run = f"{run_id}.map{i}"
                child_context = self._child_context(
                    execution_context,
                    session_id=thread_id,
                    run_id=run_id,
                    call_id=node.id,
                    child_workflow_id=str(sub_def.id or sub_def.name),
                    parent_workflow_id=parent_workflow_id,
                )
                sub = await self.run(sub_def, inputs=sub_inputs, work_root=work_root,
                                      thread_id=child_thread, run_id=child_run, execution_context=child_context)
                if sub.status == "cancelled":
                    raise asyncio.CancelledError()
                if sub.status != "completed":
                    raise RuntimeError(
                        f"subgraph workflow '{target_name}' failed: "
                        f"{sub.error or sub.status}"
                    )
                results.append(sub.output)
            return {out_port: results}

        if iterate == "loop":
            max_iter = max(1, _as_int(cfg.get("max_iterations"), default=5))
            condition_expr = cfg.get("condition") or ""
            # Seed entry inputs from bound_inputs.
            sub_inputs = self._map_entry_inputs(sub_def, bound_inputs)
            output: Any = None
            for i in range(max_iter):
                child_context = self._child_context(
                    execution_context,
                    session_id=thread_id,
                    run_id=run_id,
                    call_id=node.id,
                    child_workflow_id=str(sub_def.id or sub_def.name),
                    parent_workflow_id=parent_workflow_id,
                )
                sub = await self.run(sub_def, inputs=sub_inputs, work_root=work_root,
                                      thread_id=f"{thread_id}.loop{i}", run_id=f"{run_id}.loop{i}", execution_context=child_context)
                output = sub.output
                if sub.status == "cancelled":
                    raise asyncio.CancelledError()
                if sub.status != "completed":
                    raise RuntimeError(
                        f"subgraph workflow '{target_name}' failed: "
                        f"{sub.error or sub.status}"
                    )
                # Exit condition: evaluate against the output wrapped as locals.
                if condition_expr:
                    cond_locals = output if isinstance(output, dict) else {"value": output}
                    if _eval_condition(
                        condition_expr,
                        cond_locals,
                        node=node,
                        execution_context=execution_context,
                        item=output,
                    ):
                        break
                # Feed output back for next iteration.
                if isinstance(output, dict):
                    # The previous implementation merged the original input
                    # first and then relied on the child's port names.  For a
                    # single-input child that selected the stale seed on every
                    # iteration.  Feed the actual iteration output as the new
                    # input source.
                    sub_inputs = self._map_entry_inputs(sub_def, output)
                else:
                    sub_inputs = self._map_entry_inputs(sub_def, {"__value__": output})
            return {out_port: output}

        # iterate == "none": run once.
        sub_inputs = self._map_entry_inputs(sub_def, bound_inputs)
        child_context = self._child_context(
            execution_context,
            session_id=thread_id,
            run_id=run_id,
            call_id=node.id,
            child_workflow_id=str(sub_def.id or sub_def.name),
            parent_workflow_id=parent_workflow_id,
        )
        result = await self.run(sub_def, inputs=sub_inputs, work_root=work_root,
                                thread_id=f"{thread_id}.sub", run_id=f"{run_id}.sub",
                                execution_context=child_context)
        if result.status == "cancelled":
            raise asyncio.CancelledError()
        if result.status != "completed":
            raise RuntimeError(
                f"subgraph workflow '{target_name}' failed: "
                f"{result.error or result.status}"
            )
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
        from lamtools_core.plugins.bundled.workflow.backend.runtime import _workflow_input_names  # local import; defined later
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
        self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str,
        execution_context: WorkflowExecutionContext | None = None,
    ) -> dict[str, Any]:
        """command node: run a shell command (invoke CLI tools).

        Uses the same shell resolution as run_command (Git Bash on Windows),
        feeds bound inputs as stdin JSON + INPUT_<PORT> env vars, and splits
        JSON stdout to same-named output ports (else whole stdout to default).
        """
        await self._check_execution_permission(
            str(node.config.get("command") or ""),
            work_root=work_root,
            node=node,
            execution_context=execution_context,
        )
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
        proc = await _create_workflow_process(
            argv,
            cwd=cwd,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(stdin_payload), timeout=timeout)
        except asyncio.TimeoutError:
            await _terminate_workflow_process(proc)
            raise RuntimeError(f"shell command timed out after {timeout}s")
        except asyncio.CancelledError:
            await _terminate_workflow_process(proc)
            raise
        text_out = stdout.decode("utf-8", errors="replace") if stdout else ""
        text_err = stderr.decode("utf-8", errors="replace") if stderr else ""
        if proc.returncode != 0:
            raise RuntimeError(
                f"shell command exited with code {proc.returncode}\nstderr:\n{text_err}"
            )
        return text_out.strip()

    async def _execute_script(
        self, node: WorkflowNode, bound_inputs: dict[str, Any], work_root: str,
        execution_context: WorkflowExecutionContext | None = None,
    ) -> dict[str, Any]:
        """script node: Python binder. Runs the script via a generated runner
        that binds input-port names as locals and reads output-port names back;
        stdout JSON flows through _split_or_fallback to the output ports.
        """
        await self._check_execution_permission(
            str(node.config.get("script") or ""),
            work_root=work_root,
            node=node,
            execution_context=execution_context,
        )
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

        proc = await _create_workflow_process(
            [sys.executable, str(runner_path)],
            cwd=cwd,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(stdin_payload), timeout=timeout)
        except asyncio.TimeoutError:
            await _terminate_workflow_process(proc)
            raise RuntimeError(f"script timed out after {timeout}s")
        except asyncio.CancelledError:
            await _terminate_workflow_process(proc)
            raise
        text_out = stdout.decode("utf-8", errors="replace") if stdout else ""
        text_err = stderr.decode("utf-8", errors="replace") if stderr else ""
        if proc.returncode != 0:
            raise RuntimeError(f"script exited with code {proc.returncode}\nstderr:\n{text_err}")
        return text_out.strip()

    # -- streaming + cancel helpers ---------------------------------------

    async def _check_execution_permission(
        self,
        command: str,
        *,
        work_root: str,
        node: WorkflowNode,
        execution_context: WorkflowExecutionContext | None = None,
    ) -> None:
        permissions = execution_context.permissions if execution_context is not None else {}
        explicit = permissions.get("run_command")
        if explicit is None:
            allowed_operations = permissions.get("allowed_operations")
            if isinstance(allowed_operations, (list, tuple, set)):
                explicit = "run_command" in allowed_operations
        if explicit is not None:
            if not bool(explicit):
                raise WorkflowPermissionError("workflow command blocked by execution context")
            return
        service = self.permission_service
        if service is None:
            if execution_context is not None and execution_context.event_metadata.get("permission_policy_required"):
                raise WorkflowPermissionError("workflow command requires an explicit permission policy")
            return
        payload = {
            "command": command,
            "work_root": work_root,
            "source": "workflow",
            "node_id": node.id,
            "node_kind": node.kind,
            "execution_context": execution_context.metadata() if execution_context else {},
        }
        checker = getattr(service, "check", None)
        if callable(checker):
            decision = checker("run_command", payload)
        elif callable(service):
            decision = service("run_command", payload)
        else:
            raise WorkflowPermissionError("Workflow execution permission service is invalid")
        if asyncio.iscoroutine(decision):
            decision = await decision
        allowed = bool(getattr(decision, "allowed", decision.get("allowed", False) if isinstance(decision, dict) else decision))
        blocked = bool(getattr(decision, "blocked", decision.get("blocked", False) if isinstance(decision, dict) else False))
        requires_approval = bool(
            getattr(
                decision,
                "requires_approval",
                decision.get("requires_approval", False) if isinstance(decision, dict) else False,
            )
        )
        if not allowed or blocked or requires_approval:
            reason = str(
                getattr(
                    decision,
                    "reason",
                    decision.get("reason", "") if isinstance(decision, dict) else "",
                )
                or "workflow command requires permission",
            )
            raise WorkflowPermissionError(reason)

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
        workflow_id: str = "",
        error: str = "",
        cache_status: str = "",
        cache_key: str = "",
    ) -> None:
        active = self._active_runs.get((thread_id, run_id))
        workflow_revision = active.workflow.revision if active is not None else 0
        state = active.node_states.get(node.id) if active is not None else None
        occurred_at = self.clock()
        event_kind = {
            "running": "started",
            "completed": "completed",
            "failed": "failed",
            "skipped": "skipped",
            "cancelled": "cancelled",
        }.get(str(status), str(status))
        await self._append_durable_event(
            WorkflowRunEvent(
                event_id=f"{run_id}:node:{node.id}:{event_kind}",
                run_id=run_id,
                kind=f"node.{event_kind}",
                workflow_id=workflow_id,
                workflow_revision=workflow_revision,
                node_id=node.id,
                occurred_at=occurred_at,
                payload={
                    "error": error or (state.error if state is not None else ""),
                    "output": public_workflow_value(state.output) if state is not None else None,
                    "attempts": state.attempts if state is not None else 0,
                    "attempt_history": public_workflow_value(state.attempt_history) if state is not None else [],
                    "started_at": state.started_at.isoformat() if state is not None and state.started_at else None,
                    "finished_at": state.finished_at.isoformat() if state is not None and state.finished_at else None,
                    "cache_status": cache_status or (state.cache_status if state is not None else ""),
                    "cache_key": cache_key or (state.cache_key if state is not None else ""),
                    "audit": public_workflow_value(state.audit) if state is not None else {},
                },
            )
        )
        if self.emit is None:
            return
        payload: dict[str, Any] = {
            "plugin_id": "workflow",
            "workflow_id": workflow_id,
            "run_id": run_id,
            "node_id": node.id,
            "status": status,
            "title": node.title,
            "kind": node.kind,
            "occurred_at": occurred_at.isoformat(),
            **({"error": error} if error else {}),
        }
        if state is not None:
            payload.update({
                "attempts": state.attempts,
                "attempt_history": public_workflow_value(state.attempt_history),
                "started_at": state.started_at.isoformat() if state.started_at else None,
                "finished_at": state.finished_at.isoformat() if state.finished_at else None,
                "output": public_workflow_value(state.output),
                "audit": public_workflow_value(state.audit),
            })
        if cache_status:
            payload["cache_status"] = cache_status
        if cache_key:
            payload["cache_key"] = cache_key
        event_metadata: dict[str, Any] = {
            "plugin_id": "workflow",
            "workflow_id": workflow_id,
            "run_id": run_id,
            "node_id": node.id,
        }
        execution_context = getattr(self._active_runs.get((thread_id, run_id)), "execution_context", None)
        # Preserve the old event envelope when no explicit parent/correlation
        # lineage was supplied.  Nested/host-integrated runs include the
        # lineage IDs so event consumers can follow the call tree.
        if execution_context is not None and (
            execution_context.parent_call_id or execution_context.event_metadata
        ):
            context_metadata = execution_context.metadata()
            event_metadata.update({
                key: context_metadata[key]
                for key in ("parent_session_id", "parent_run_id", "parent_turn_id", "parent_call_id", "trace_id", "correlation_id")
                if context_metadata.get(key)
            })
        event = RunItemEvent(
            kind="status",
            thread_id=thread_id,
            run_id=run_id,
            turn_id=run_id,
            item_id=node.id,
            status=status,
            payload=payload,
            source="plugin:workflow",
            metadata=event_metadata,
        )
        try:
            result = self.emit(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception:  # noqa: BLE001 — streaming must never break execution
            pass

    async def _emit_run_status(
        self,
        status: str,
        thread_id: str,
        run_id: str,
        *,
        workflow_id: str = "",
        node_id: str = "",
        **details: Any,
    ) -> None:
        """Emit lifecycle progress without changing legacy node events."""
        if self.emit is None:
            return
        event_status = status
        payload: dict[str, Any] = {
            "plugin_id": "workflow",
            "workflow_id": workflow_id,
            "run_id": run_id,
            "node_id": node_id,
            "status": status,
            "occurred_at": self.clock().isoformat(),
            **details,
        }
        metadata = {
            "plugin_id": "workflow",
            "workflow_id": workflow_id,
            "run_id": run_id,
            "node_id": node_id,
        }
        execution_context = getattr(
            self._active_runs.get((thread_id, run_id)),
            "execution_context",
            None,
        )
        if execution_context is not None and (
            execution_context.parent_call_id
            or execution_context.event_metadata
            or execution_context.trace_id
            or execution_context.lineage
        ):
            context_metadata = execution_context.metadata()
            for key in (
                "parent_session_id", "parent_run_id", "parent_turn_id",
                "parent_call_id", "trace_id", "correlation_id", "lineage",
                "depth", "workflow_stack",
            ):
                if context_metadata.get(key):
                    metadata[key] = context_metadata[key]
        try:
            result = self.emit(
                RunItemEvent(
                    kind="status",
                    thread_id=thread_id,
                    run_id=run_id,
                    turn_id=run_id,
                    item_id=node_id or run_id,
                    status=event_status,  # type: ignore[arg-type]
                    payload=payload,
                    source="plugin:workflow",
                    metadata=metadata,
                )
            )
            if asyncio.iscoroutine(result):
                await result
        except Exception:  # noqa: BLE001 - events are observational
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


def _is_lazy_port(node: WorkflowNode, port: WorkflowPort) -> bool:
    """Read the declarative lazy-input flag from a port or node config."""
    if port.lazy:
        return True
    declaration = node.config.get("lazy_inputs", node.config.get("lazyInputs"))
    if declaration is True:
        return True
    if isinstance(declaration, (list, tuple, set)):
        return port.name in declaration
    if isinstance(declaration, dict) and port.name in declaration:
        value = declaration[port.name]
        if isinstance(value, dict):
            return bool(value.get("lazy", value.get("enabled", True)))
        return bool(value)
    # A node may expose an input schema with per-field lazy declarations.
    schema = node.config.get("input_schema", node.config.get("inputSchema"))
    if isinstance(schema, dict):
        field = schema.get(port.name)
        if isinstance(field, dict):
            return bool(field.get("lazy", field.get("deferred", False)))
    return False


def _lazy_input(
    name: str,
    resolver: Callable[[], Any],
) -> LazyInput:
    return LazyInput(name, resolver)


def _bind_inputs(
    node: WorkflowNode,
    workflow: WorkflowDef,
    values: dict[str, Any],
    *,
    execution_context: WorkflowExecutionContext | None = None,
) -> dict[str, Any]:
    """Bind input values from the value table.

    For each edge: if the edge has a structured ``condition`` AST, it is
    evaluated through the safe evaluator against the *source node's* bound
    inputs. Legacy string conditions continue through the Python fallback.
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
            source_bound[src_id] = (
                _bind_inputs(src_node, workflow, values, execution_context=execution_context)
                if src_node
                else {}
            )
        return source_bound[src_id]

    bound: dict[str, Any] = {}
    for port in node.input_ports():
        edges = _feeding_edges(node, port.name, workflow)
        if not edges:
            # Orphaned input port → workflow input slot.
            key = f"__input__.{node.id}.{port.name}"
            if _is_lazy_port(node, port):
                bound[port.name] = _lazy_input(
                    key,
                    lambda key=key, port=port: _coerce_value(values.get(key), port.type),
                )
            elif key in values:
                bound[port.name] = _coerce_value(values[key], port.type)
        elif len(edges) == 1:
            edge = edges[0]
            key = f"{edge.source}.{edge.source_port}"
            if key in values:
                raw = values[key]
                if _is_lazy_port(node, port):
                    def resolve_edge(
                        edge: WorkflowEdge = edge,
                        key: str = key,
                        port: WorkflowPort = port,
                    ) -> Any:
                        raw_value = values.get(key)
                        # Edge condition is part of the deferred read.  This
                        # prevents a lazy declaration from evaluating a
                        # source object merely to decide whether it is used.
                        if edge.condition and not _eval_condition(
                            edge.condition,
                            _get_source_bound(edge.source),
                            node=_source_node(edge.source, workflow),
                            execution_context=execution_context,
                        ):
                            return SKIP_SENTINEL
                        return _coerce_value(
                            _apply_transform(
                                raw_value,
                                edge.transform,
                                node=node,
                                bound_inputs=_get_source_bound(edge.source),
                                execution_context=execution_context,
                            ),
                            port.type,
                        )

                    bound[port.name] = _lazy_input(key, resolve_edge)
                else:
                    # Edge condition: evaluate against source node's bound inputs.
                    if edge.condition and not _eval_condition(
                        edge.condition,
                        _get_source_bound(edge.source),
                        node=_source_node(edge.source, workflow),
                        execution_context=execution_context,
                    ):
                        bound[port.name] = SKIP_SENTINEL
                    else:
                        val = _apply_transform(
                            raw,
                            edge.transform,
                            node=node,
                            bound_inputs=_get_source_bound(edge.source),
                            execution_context=execution_context,
                        )
                        bound[port.name] = _coerce_value(val, port.type)
        else:
            # Multiple edges → aggregate into a list (sentinels filtered).
            if _is_lazy_port(node, port):
                def resolve_edges(
                    edges: list[WorkflowEdge] = edges,
                    port: WorkflowPort = port,
                ) -> list[Any]:
                    vals: list[Any] = []
                    for edge in edges:
                        key = f"{edge.source}.{edge.source_port}"
                        if key not in values:
                            continue
                        raw = values[key]
                        if edge.condition and not _eval_condition(
                            edge.condition,
                            _get_source_bound(edge.source),
                            node=_source_node(edge.source, workflow),
                            execution_context=execution_context,
                        ):
                            continue
                        if raw is not None and raw != SKIP_SENTINEL:
                            vals.append(
                                _coerce_value(
                                    _apply_transform(
                                        raw,
                                        edge.transform,
                                        node=node,
                                        bound_inputs=_get_source_bound(edge.source),
                                        execution_context=execution_context,
                                    ),
                                    port.type,
                                )
                            )
                    return vals

                bound[port.name] = _lazy_input(
                    f"{node.id}.{port.name}",
                    resolve_edges,
                )
            else:
                vals = []
                for edge in edges:
                    key = f"{edge.source}.{edge.source_port}"
                    if key in values:
                        raw = values[key]
                        if edge.condition and not _eval_condition(
                            edge.condition,
                            _get_source_bound(edge.source),
                            node=_source_node(edge.source, workflow),
                            execution_context=execution_context,
                        ):
                            continue  # edge blocked → skip this value
                        if raw is not None and raw != SKIP_SENTINEL:
                            vals.append(
                                _coerce_value(
                                    _apply_transform(
                                        raw,
                                        edge.transform,
                                        node=node,
                                        bound_inputs=_get_source_bound(edge.source),
                                        execution_context=execution_context,
                                    ),
                                    port.type,
                                )
                            )
                bound[port.name] = vals
    return bound


def _apply_transform(
    value: Any,
    transform: Any,
    *,
    node: WorkflowNode | None = None,
    bound_inputs: dict[str, Any] | None = None,
    execution_context: WorkflowExecutionContext | None = None,
) -> Any:
    """Apply a legacy JSONPath or a versioned expression AST.

    Legacy strings retain their pass-through behaviour for empty/non-``$.``
    values.  Structured ASTs are evaluated with ``item`` bound to the raw
    upstream value, ``input`` to source-node bound inputs, and a sanitized
    ``env`` snapshot.
    """
    if _is_structured_expression(transform):
        return _evaluate_workflow_expression(
            transform,
            node=node,
            bound_inputs=bound_inputs or {},
            execution_context=execution_context,
            item=value,
        )
    if type(transform) is not str:
        return value
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
    if workflow.document is not None:
        outputs = workflow.document.get("interface", {}).get("outputs", [])
        if outputs:
            port_names = {
                (node.get("id"), port.get("id")): port.get("name")
                for node in workflow.document.get("graph", {}).get("nodes", [])
                if isinstance(node, dict)
                for port in node.get("ports", [])
                if isinstance(port, dict)
            }
            resolved: dict[str, Any] = {}
            for item in outputs:
                if not isinstance(item, dict) or not isinstance(item.get("source"), dict):
                    continue
                source = item["source"]
                node_id = str(source.get("node_id") or "")
                port_name = str(port_names.get((node_id, source.get("port_id"))) or "")
                resolved[str(item.get("name") or item.get("id") or port_name)] = values.get(
                    f"{node_id}.{port_name}"
                )
            if len(resolved) == 1:
                return next(iter(resolved.values()))
            if resolved:
                return resolved
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
    if isinstance(value, LazyInput):
        return repr(value)
    if isinstance(value, str):
        return value if len(value) <= 500 else value[:500] + "…"
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= 500 else text[:500] + "…"


def _serialize_prompt_value(value: Any) -> str:
    """Serialize an executable AI-node input without applying UI preview limits."""
    if isinstance(value, LazyInput):
        return repr(value)
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


_PUBLIC_PRIVATE_KEYS = {
    "password", "passwd", "secret", "secrets", "token", "access_token",
    "refresh_token", "id_token", "api_key", "apikey", "private_key",
    "client_secret", "authorization", "cookie", "resume_token",
    "continuation_token", "runtime_credentials", "credential_secret",
}


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


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def _safe_tool_calls(value: Any) -> list[dict[str, Any]]:
    raw_calls = _field(value, "tool_calls", [])
    if not isinstance(raw_calls, (list, tuple)):
        return []
    calls: list[dict[str, Any]] = []
    for raw in raw_calls:
        name = str(_field(raw, "name", "") or "").strip()
        status = str(_field(raw, "status", "") or "").strip()
        if name or status:
            calls.append({**({"name": name} if name else {}), **({"status": status} if status else {})})
    return calls


def _model_audit_metadata(response: Any, *, model_id: str, rounds: int) -> dict[str, Any]:
    metadata: dict[str, Any] = {"kind": "model", "model_id": model_id, "rounds": rounds}
    finish_reason = str(_field(response, "finish_reason", "") or "").strip()
    if finish_reason:
        metadata["finish_reason"] = finish_reason
    calls = _safe_tool_calls(response)
    if calls:
        metadata["tool_calls"] = calls
    usage = _field(response, "usage")
    if isinstance(usage, Mapping):
        safe_usage = {
            str(key): nested for key, nested in usage.items()
            if isinstance(nested, (int, float)) and not isinstance(nested, bool)
        }
        if safe_usage:
            metadata["usage"] = safe_usage
    return metadata


def _agent_audit_metadata(
    result: Any, *, node: WorkflowNode, configured_model: Any
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "kind": "agent",
        "agent": str(node.config.get("agent") or ""),
        "model_id": str(_field(result, "model_id", configured_model) or configured_model or ""),
    }
    for key in (
        "session_id", "run_id", "decision", "tool_call_count", "model_rounds",
        "ended_with_final_response",
    ):
        value = _field(result, key)
        if value not in (None, ""):
            metadata[key] = value
    breakdown = _field(result, "tool_call_breakdown")
    if isinstance(breakdown, Mapping):
        metadata["tool_calls"] = [
            {"name": str(name), "count": int(count)}
            for name, count in breakdown.items()
            if str(name).strip() and isinstance(count, int) and not isinstance(count, bool)
        ]
    elif _safe_tool_calls(result):
        metadata["tool_calls"] = _safe_tool_calls(result)
    return metadata


async def _materialize_inputs(values: dict[str, Any]) -> dict[str, Any]:
    """Resolve lazy values at a built-in service boundary."""
    result: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, LazyInput):
            result[key] = await value.aresolve()
        else:
            result[key] = value
    return result


def _contains_lazy_input(value: Any) -> bool:
    if isinstance(value, LazyInput):
        return True
    if isinstance(value, dict):
        return any(_contains_lazy_input(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_lazy_input(item) for item in value)
    return False


def _is_executor_surface(value: Any) -> bool:
    """Return whether a value can be adapted as a trusted node executor."""

    return (
        callable(value)
        or callable(getattr(value, "execute", None))
        or callable(getattr(value, "run", None))
    )


def _inherited_allowed_tools(
    context: WorkflowExecutionContext | None,
) -> set[str] | None:
    if context is None:
        return None
    candidates: list[Any] = [
        context.permissions.get("allowed_tools"),
        context.capabilities.get("allowed_tools"),
        context.capabilities.get("tools"),
    ]
    for candidate in candidates:
        if isinstance(candidate, (list, tuple, set, frozenset)):
            result = {str(item).strip() for item in candidate if str(item).strip()}
            return result
    return None


def _execution_model_id(context: WorkflowExecutionContext | None) -> str:
    """Resolve the run-level model inherited by model and agent nodes."""
    if context is None:
        return ""
    for source in (context.event_metadata, context.runtime_snapshot, context.snapshot):
        if isinstance(source, dict):
            model_id = str(source.get("model_id") or source.get("modelId") or "").strip()
            if model_id:
                return model_id
    return ""


@dataclass(frozen=True, slots=True)
class _WorkflowAuthorizationGrants:
    capabilities: frozenset[str] = frozenset()
    resources: dict[str, Any] = field(default_factory=dict, compare=False)


def _grant_names(value: Any) -> set[str]:
    """Collect explicit names from a host grant value."""

    result: set[str] = set()
    if isinstance(value, str):
        name = value.strip()
        if name:
            result.add(name)
    elif isinstance(value, Mapping):
        for key, nested in value.items():
            name = str(key).strip()
            if isinstance(nested, bool):
                if nested and name:
                    result.add(name)
            elif isinstance(nested, (list, tuple, set, frozenset)):
                result.update(_grant_names(nested))
            elif isinstance(nested, Mapping):
                # ``{"network": {"allowed": true}}`` is a common host shape.
                enabled = nested.get("allowed", nested.get("granted", nested.get("enabled")))
                if enabled is True and name:
                    result.add(name)
        # A mapping may itself be one compact declaration, e.g.
        # ``{"allowed": ["network"]}``.
        for key in ("allowed", "granted", "capabilities", "requires", "names"):
            if key in value:
                result.update(_grant_names(value[key]))
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            result.update(_grant_names(item))
    return result


def _workflow_authorization_grants(
    context: WorkflowExecutionContext,
) -> _WorkflowAuthorizationGrants:
    """Read only explicit capability/resource grants from host context."""

    capability_names: set[str] = set()
    resource_names: set[str] = set()
    resource_specs: dict[str, Any] = {}
    containers = (
        context.capabilities if isinstance(context.capabilities, Mapping) else {},
        context.permissions if isinstance(context.permissions, Mapping) else {},
    )
    capability_keys = {
        "capabilities", "allowed_capabilities", "allow_capabilities", "grants",
        "allowed", "enabled_capabilities", "requires",
    }
    resource_keys = {
        "resources", "resource", "resource_classes", "allowed_resources",
        "allowed_resource_classes", "resource_class", "allowed_resource_class",
    }
    for container in containers:
        # Direct boolean maps (``{"network": true}``) are explicit grants.
        capability_names.update(
            name for name, value in container.items()
            if isinstance(value, bool) and value and str(name).strip()
        )
        for key, value in container.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in capability_keys:
                capability_names.update(_grant_names(value))
            if normalized in resource_keys:
                if normalized in {"resource_class", "allowed_resource_class"} and isinstance(value, str):
                    resource_names.add(value.strip())
                elif isinstance(value, Mapping):
                    for resource_name, resource_value in value.items():
                        clean_name = str(resource_name).strip()
                        if not clean_name:
                            continue
                        resource_names.add(clean_name)
                        resource_specs[clean_name] = resource_value
                else:
                    resource_names.update(_grant_names(value))
        # Some hosts expose the resource grant as a nested capability map.
        nested_resources = container.get("resource_capabilities")
        if isinstance(nested_resources, Mapping):
            for resource_name, resource_value in nested_resources.items():
                clean_name = str(resource_name).strip()
                if clean_name:
                    resource_names.add(clean_name)
                    resource_specs[clean_name] = resource_value
    return _WorkflowAuthorizationGrants(
        capabilities=frozenset(capability_names),
        resources={name: resource_specs.get(name, True) for name in resource_names},
    )


def _workflow_resource_authorized(
    resource_class: str,
    requirements: Any,
    resources: Mapping[str, Any],
) -> bool:
    """Check class and declared data-only limits against host grants."""

    available = resources.get(resource_class)
    if available is None:
        return False
    if not requirements:
        return True
    if not isinstance(requirements, Mapping) or not isinstance(available, Mapping):
        return False
    for key, required in requirements.items():
        if key not in available:
            return False
        actual = available[key]
        if isinstance(required, (int, float)) and not isinstance(required, bool):
            if not isinstance(actual, (int, float)) or isinstance(actual, bool) or actual < required:
                return False
        elif actual != required:
            return False
    return True


def _credential_ref(value: Any) -> CredentialRef | None:
    if isinstance(value, CredentialRef):
        return value
    if isinstance(value, Mapping) and is_credential_ref(value):
        return CredentialRef.from_dict(value)
    return None


async def _resolve_workflow_credentials(
    value: Any,
    resolver: Any,
    context: WorkflowExecutionContext | None,
    resolved: dict[str, Any],
    secrets: list[Any],
    *,
    path: str = "workflow",
) -> Any:
    """Resolve explicit credential references without mutating source data."""

    ref = _credential_ref(value)
    if ref is not None:
        # The transient context is intentionally keyed by the public
        # credential identifier; provider/scope remain part of the ref sent to
        # the resolver, but are never exposed as a persistence key.
        cache_key = ref.credential_id
        if cache_key not in resolved:
            if resolver is None:
                raise CredentialError(
                    f"credential reference at {path} requires a credential resolver"
                )
            if isinstance(resolver, Mapping):
                if ref.credential_id not in resolver:
                    raise CredentialError(f"credential not found: {ref.credential_id}")
                result = resolver[ref.credential_id]
            else:
                result = await ref.aresolve(resolver, context=context)
            resolved[cache_key] = result
            secrets.append(result)
        return resolved[cache_key]
    if isinstance(value, Mapping):
        return {
            key: await _resolve_workflow_credentials(
                nested, resolver, context, resolved, secrets, path=f"{path}.{key}"
            )
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [
            await _resolve_workflow_credentials(
                nested, resolver, context, resolved, secrets, path=f"{path}[{index}]"
            )
            for index, nested in enumerate(value)
        ]
    if isinstance(value, tuple):
        return tuple(
            [
                await _resolve_workflow_credentials(
                    nested, resolver, context, resolved, secrets, path=f"{path}[{index}]"
                )
                for index, nested in enumerate(value)
            ]
        )
    return value


def _contains_credential_ref(value: Any) -> bool:
    if _credential_ref(value) is not None:
        return True
    if isinstance(value, Mapping):
        return any(_contains_credential_ref(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_credential_ref(item) for item in value)
    return False


def _redact_runtime_secrets(value: Any, secrets: list[Any]) -> Any:
    """Prevent resolved values from crossing result/event/snapshot boundaries."""

    if not secrets:
        return value
    for secret in secrets:
        if secret is None:
            continue
        try:
            if type(value) is type(secret) and value == secret:
                return "[REDACTED]"
        except Exception:  # noqa: BLE001 - hostile host value comparison
            pass
        if isinstance(value, str) and isinstance(secret, str) and secret:
            if secret in value:
                return value.replace(secret, "[REDACTED]")
    if isinstance(value, Mapping):
        return {
            key: _redact_runtime_secrets(nested, secrets)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [_redact_runtime_secrets(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_runtime_secrets(item, secrets) for item in value)
    return value


def _redact_exception_text(exc: BaseException, secrets: list[Any]) -> str:
    return str(_redact_runtime_secrets(str(exc), secrets)) or type(exc).__name__


def _executor_result_to_legacy(
    value: Any,
    *,
    node: WorkflowNode | None = None,
) -> Any:
    """Accept an explicit packet result while retaining the old result shape."""

    if isinstance(value, WorkflowDataPacket) or is_data_packet(value):
        legacy = packet_to_legacy(value)
        output_ports = node.output_ports() if node is not None else []
        if len(output_ports) == 1:
            return {output_ports[0].name: legacy}
        if isinstance(legacy, Mapping) and output_ports:
            names = {port.name for port in output_ports}
            if set(legacy).issubset(names):
                return dict(legacy)
        # A scalar/object/array legacy result maps to the conventional output
        # port; existing mapping results are otherwise left untouched.
        return {"output": legacy}
    return value


def _packet_view_for_inputs(value: Mapping[str, Any]) -> WorkflowDataPacket:
    """Preserve an already-canonical single input packet's item metadata."""

    if len(value) == 1:
        candidate = next(iter(value.values()))
        if isinstance(candidate, WorkflowDataPacket) or is_data_packet(candidate):
            return WorkflowDataPacket.coerce(candidate)
    candidate = value.get("packet") if isinstance(value, Mapping) else None
    if isinstance(candidate, WorkflowDataPacket) or is_data_packet(candidate):
        return WorkflowDataPacket.coerce(candidate)
    return adapt_data_packet(value)


def _assert_json_workflow_data(workflow: WorkflowDef) -> None:
    """Reject callable/non-JSON values in a dynamic expansion contract."""
    try:
        _assert_json_value(workflow.to_dict())
    except (TypeError, ValueError) as exc:
        raise WorkflowExpansionError(
            "workflow expansion must contain JSON-compatible data only"
        ) from exc
    # ``to_dict`` intentionally uses ``default=str`` for durable legacy data;
    # inspect the live model as well so a callable cannot be stringified past
    # this security boundary.
    for node in workflow.nodes:
        try:
            _assert_json_value(node.config)
            _assert_json_value(node.position)
        except (TypeError, ValueError) as exc:
            raise WorkflowExpansionError(
                "workflow expansion node config must contain JSON values only"
            ) from exc
        for port in node.ports:
            try:
                _assert_json_value(port.value)
            except (TypeError, ValueError) as exc:
                raise WorkflowExpansionError(
                    "workflow expansion port values must contain JSON values only"
                ) from exc
    for param in workflow.input_params:
        try:
            _assert_json_value(param.name)
            _assert_json_value(param.type)
            _assert_json_value(param.description)
            _assert_json_value(param.required)
            _assert_json_value(param.default)
        except (TypeError, ValueError) as exc:
            raise WorkflowExpansionError(
                "workflow expansion input defaults must contain JSON values only"
            ) from exc


def _coerce_expansion_input_param(value: Any) -> WorkflowInputParam:
    """Normalize one ephemeral input declaration or raise a clear error."""

    if isinstance(value, WorkflowInputParam):
        return value
    if isinstance(value, dict):
        return WorkflowInputParam.from_dict(value)
    raise WorkflowExpansionError(
        f"workflow expansion input parameter must be an object: {type(value).__name__}"
    )


def _assert_json_value(value: Any) -> None:
    """Strictly validate JSON data without ``default=str`` coercion."""
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            _assert_json_value(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_json_value(item)
        return
    raise TypeError(f"non-JSON value: {type(value).__name__}")


def _cache_facts(node_states: dict[str, WorkflowNodeState]) -> dict[str, dict[str, Any]]:
    return {
        node_id: {
            "status": state.cache_status,
            "key": state.cache_key,
            "hit": state.cache_status == "hit",
        }
        for node_id, state in node_states.items()
        if state.cache_status != "bypass" or state.cache_key
    }


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


async def _create_workflow_process(
    argv: list[str],
    *,
    cwd: str,
    env: dict[str, str],
) -> asyncio.subprocess.Process:
    """Start a node process in its own group so cancellation reaches children."""
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "env": env,
        "stdin": asyncio.subprocess.PIPE,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    return await asyncio.create_subprocess_exec(*argv, **kwargs)


async def _terminate_workflow_process(proc: asyncio.subprocess.Process) -> None:
    """Terminate a command/script process tree and drain its pipes."""
    if proc.returncode is None:
        if sys.platform == "win32" and getattr(proc, "pid", None):
            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/PID",
                    str(proc.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await killer.communicate()
            except (OSError, ValueError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        else:
            try:
                # ``start_new_session=True`` gives the command its own process
                # group.  Killing only the shell would leave descendants such
                # as ``sleep``/``python`` alive after a cancelled workflow.
                if getattr(proc, "pid", None):
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except ProcessLookupError:
                pass
            except OSError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
    try:
        await asyncio.wait_for(proc.communicate(), timeout=2.0)
    except (asyncio.TimeoutError, ProcessLookupError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


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
        entry: dict[str, Any] = {"name": p.name, "type": p.type, "description": p.description}
        if p.lazy:
            entry["lazy"] = True
        inputs.append(entry)
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


def _response_content(response: Any) -> str:
    """Extract provider-neutral text from modern and legacy model responses."""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        value = response.get("content", response.get("text", ""))
        return value if isinstance(value, str) else _summarize(value)
    value = getattr(response, "content", None)
    if value is None:
        value = getattr(response, "text", "")
    return value if isinstance(value, str) else _summarize(value)


_EXPRESSION_NO_ITEM = object()
_EXPRESSION_SECRET_FIELDS = {
    "password",
    "passwd",
    "secret",
    "secrets",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "client_secret",
    "authorization",
    "cookie",
    "credential_secret",
}
_EXPRESSION_CREDENTIAL_FIELDS = {
    "id",
    "name",
    "label",
    "display_name",
    "provider",
    "provider_id",
    "type",
    "kind",
    "ref",
    "reference",
    "credential_ref",
    "credential_id",
    "masked",
    "redacted",
    "status",
}


def _is_structured_expression(value: Any) -> bool:
    return type(value) is dict or type(value) is Expression


def _expression_secret_field(name: str) -> bool:
    lowered = name.casefold()
    return lowered in _EXPRESSION_SECRET_FIELDS or lowered.endswith(("_password", "_secret", "_token", "_api_key"))


def _expression_safe_value(value: Any, *, credential_metadata: bool = False) -> Any:
    """Copy only plain JSON data, removing secret-bearing fields.

    Runtime node configs and upstream values are host-owned objects, so the
    safe expression context is built as a fresh tree.  Unsupported values
    (including ``LazyInput``) become ``None`` and are never exposed through a
    Python object attribute or protocol method.
    """
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        return value if math.isfinite(value) else None
    if type(value) is list:
        return [_expression_safe_value(item) for item in value]
    if type(value) is not dict:
        return None
    copied: dict[str, Any] = {}
    for key, item in value.items():
        if type(key) is not str or not key or key.startswith("__") or key.endswith("__"):
            continue
        lowered = key.casefold()
        if _expression_secret_field(key):
            continue
        if lowered in {"credential", "credentials"}:
            if type(item) is not dict:
                continue
            metadata: dict[str, Any] = {}
            for metadata_key, metadata_value in item.items():
                if (
                    type(metadata_key) is str
                    and metadata_key.casefold() in _EXPRESSION_CREDENTIAL_FIELDS
                ):
                    metadata[metadata_key] = _expression_safe_value(metadata_value, credential_metadata=True)
            copied[key] = metadata
            continue
        if credential_metadata and lowered not in _EXPRESSION_CREDENTIAL_FIELDS:
            continue
        copied[key] = _expression_safe_value(item, credential_metadata=credential_metadata)
    return copied


def _expression_item(bound_inputs: dict[str, Any], item: Any = _EXPRESSION_NO_ITEM) -> Any:
    if item is not _EXPRESSION_NO_ITEM:
        return item
    if "item" in bound_inputs:
        return bound_inputs["item"]
    if "value" in bound_inputs:
        return bound_inputs["value"]
    if len(bound_inputs) == 1:
        return next(iter(bound_inputs.values()))
    return bound_inputs


def _evaluate_workflow_expression(
    expression: dict[str, Any] | Expression,
    *,
    node: WorkflowNode | None,
    bound_inputs: dict[str, Any],
    execution_context: WorkflowExecutionContext | None = None,
    item: Any = _EXPRESSION_NO_ITEM,
) -> Any:
    """Evaluate an AST with the documented runtime roots.

    ``input`` is the current node/source bound-input map, ``item`` is the
    current singular value (or raw transform value), ``node`` is non-secret
    node metadata, and ``env`` is a redacted execution environment.
    """
    raw_environment = execution_context.environment if execution_context is not None else {}
    context_node = (
        {
            "id": node.id,
            "kind": node.kind,
            "type_id": node.type_id or node.kind,
            "title": node.title,
        }
        if node is not None
        else None
    )
    context = ExpressionContext(
        input=_expression_safe_value(bound_inputs),
        item=_expression_safe_value(_expression_item(bound_inputs, item)),
        node=_expression_safe_value(context_node),
        env=_expression_safe_value(raw_environment),
    )
    try:
        return evaluate_expression(expression, context)
    except ExpressionError as exc:
        # The JSON payload becomes the node-state error and can be parsed by
        # API/CLI consumers without scraping a human-formatted message.
        raise WorkflowExpressionError(exc) from exc


def _source_node(source_id: str, workflow: WorkflowDef) -> WorkflowNode | None:
    return workflow.node(source_id)


def _eval_condition(
    expr: Any,
    bound_inputs: dict[str, Any],
    *,
    node: WorkflowNode | None = None,
    execution_context: WorkflowExecutionContext | None = None,
    item: Any = _EXPRESSION_NO_ITEM,
) -> bool:
    """Evaluate an AST safely or retain the explicit Python legacy fallback.

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
    if _is_structured_expression(expr):
        return bool(
            _evaluate_workflow_expression(
                expr,
                node=node,
                bound_inputs=bound_inputs,
                execution_context=execution_context,
                item=item,
            )
        )
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


async def _call_with_supported_kwargs(call: Callable[..., Any], kwargs: dict[str, Any]) -> Any:
    """Invoke old and new agent adapters without hiding exceptions from the call."""
    try:
        signature = inspect.signature(call)
    except (TypeError, ValueError):
        selected = kwargs
    else:
        accepts_extra = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
        selected = kwargs if accepts_extra else {key: value for key, value in kwargs.items() if key in signature.parameters}
    result = call(**selected)
    return await result if inspect.isawaitable(result) else result


def _cancellation_requested(token: Any) -> bool:
    if token is None:
        return False
    if isinstance(token, bool):
        return token
    is_set = getattr(token, "is_set", None)
    if callable(is_set):
        try:
            return bool(is_set())
        except Exception:  # noqa: BLE001 — optional host token
            return False
    if callable(token):
        try:
            return bool(token())
        except Exception:  # noqa: BLE001 — optional host token
            return False
    return False


async def _await_with_context_cancel(
    awaitable: Awaitable[dict[str, Any]],
    context: WorkflowExecutionContext | None,
) -> dict[str, Any]:
    timeout_seconds: float | None = None
    if context is not None and isinstance(context.environment, dict):
        raw_timeout = context.environment.get("__workflow_timeout_seconds")
        try:
            timeout_seconds = float(raw_timeout) if raw_timeout not in (None, "") else None
        except (TypeError, ValueError):
            timeout_seconds = None
    if timeout_seconds is not None and timeout_seconds > 0:
        awaitable = asyncio.wait_for(awaitable, timeout=timeout_seconds)
    token = context.cancellation if context is not None else None
    if token is None:
        return await awaitable
    if _cancellation_requested(token):
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        raise asyncio.CancelledError()
    is_set = getattr(token, "is_set", None)
    if callable(is_set) and is_set():
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        raise asyncio.CancelledError()
    wait = getattr(token, "wait", None)
    if not callable(wait):
        return await awaitable
    cancellation_wait = wait()
    if not inspect.isawaitable(cancellation_wait):
        return await awaitable
    node_task = asyncio.ensure_future(awaitable)
    cancel_task = asyncio.ensure_future(cancellation_wait)
    done, _ = await asyncio.wait({node_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED)
    if cancel_task in done and not node_task.done():
        node_task.cancel()
        await asyncio.gather(node_task, return_exceptions=True)
        raise asyncio.CancelledError()
    cancel_task.cancel()
    await asyncio.gather(cancel_task, return_exceptions=True)
    return await node_task


def _pause_requested(context: WorkflowExecutionContext | None) -> bool:
    """Read a static or dynamically-set pause-on-cancel token."""
    if context is None:
        return False
    token = context.pause_on_cancel
    if isinstance(token, bool):
        return token
    is_set = getattr(token, "is_set", None)
    if callable(is_set):
        try:
            return bool(is_set())
        except Exception:  # noqa: BLE001 - optional host token
            return False
    if callable(token):
        try:
            return bool(token())
        except Exception:  # noqa: BLE001 - optional host token
            return False
    return bool(token)


__all__ = [
    "AgentInvoker",
    "AgentInvokerAdapter",
    "LLMInvoker",
    "LegacyLLMAdapter",
    "LegacyAgentInvokerAdapter",
    "LegacyModelInvokerAdapter",
    "LegacySubAgentAdapter",
    "LegacyNodeExecutorAdapter",
    "ModelInvoker",
    "ModelInvokerAdapter",
    "NodeExecutionResult",
    "WorkflowNodeExecutionResult",
    "Expansion",
    "DynamicNodeExpansion",
    "NodeExecutor",
    "NodeExecutorAdapter",
    "SubAgentInvoker",
    "SubAgentInvokerAdapter",
    "LazyInput",
    "LazyValue",
    "NodeStateStatus",
    "PortDirection",
    "SKIP_SENTINEL",
    "WorkflowDef",
    "WorkflowConflictError",
    "WorkflowCapabilityError",
    "WorkflowExpansion",
    "WorkflowDynamicExpansion",
    "WorkflowExpansionError",
    "WorkflowExecutorError",
    "WorkflowExpressionError",
    "WorkflowExecutorRegistry",
    "WorkflowExecutionContext",
    "WorkflowEdge",
    "WorkflowInputParam",
    "WorkflowManager",
    "WorkflowNode",
    "WorkflowNodeKind",
    "WorkflowNodeState",
    "WorkflowPort",
    "WorkflowRunResult",
    "WorkflowRunner",
    "normalize_execution_result",
    "normalize_node_result",
    "WorkflowNestingError",
    "WorkflowPermissionError",
    "WorkflowRecursionError",
]
