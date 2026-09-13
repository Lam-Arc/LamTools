"""Trusted Workflow node execution and expansion contracts.

Workflow documents are data.  A document may name a node type, but it may not
name a Python module, import path, or callback.  Hosts explicitly register a
schema and an executor together (after making their plugin trust decision),
then :class:`WorkflowRunner` dispatches through this registry.

The expansion types below are intentionally JSON-shaped.  They are suitable
for an executor to return a small ephemeral subgraph without handing the
runner an arbitrary Python object to import or evaluate.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime, time
from typing import Any

from .adapters import NodeExecutor, adapt_node_executor


class WorkflowExecutorError(RuntimeError):
    """Raised when a node has no trusted, registered executable contract."""


class WorkflowExpansionError(ValueError):
    """Raised when an executor returns an unsafe or malformed expansion."""


@dataclass(frozen=True)
class WorkflowExpansion:
    """A bounded, declarative ephemeral subgraph.

    ``nodes`` and ``edges`` may be dictionaries (the wire representation) or
    the runner's ``WorkflowNode``/``WorkflowEdge`` data objects.  The runtime
    validates and converts them before execution.  ``subgraph`` is an
    alternative single ``WorkflowDef``-shaped mapping for executors that
    already have a complete graph.  No field contains an import path or a
    callable.
    """

    nodes: Sequence[Any] = field(default_factory=tuple)
    edges: Sequence[Any] = field(default_factory=tuple)
    input_params: Sequence[Any] = field(default_factory=tuple)
    output_port: str = ""
    inputs: Mapping[str, Any] = field(default_factory=dict)
    subgraph: Any = None
    name: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowExpansion":
        if not isinstance(value, Mapping):
            raise WorkflowExpansionError("workflow expansion must be an object")
        # Permit both the compact ``workflow`` spelling and the explicit
        # ``subgraph`` spelling.  A complete WorkflowDef mapping is accepted
        # directly as a convenience for remote plugin executors.
        raw_subgraph = value.get("subgraph", value.get("workflow"))
        nodes = value.get("nodes", ())
        edges = value.get("edges", ())
        if raw_subgraph is None and not nodes and not edges and "name" in value:
            raw_subgraph = dict(value)
        input_params = value.get("input_params", value.get("inputParams", ()))
        inputs = value.get("inputs", value.get("input_mapping", value.get("inputMapping", {})))
        metadata = value.get("metadata", {})
        if not isinstance(nodes, Sequence) or isinstance(nodes, (str, bytes, bytearray)):
            raise WorkflowExpansionError("workflow expansion nodes must be an array")
        if not isinstance(edges, Sequence) or isinstance(edges, (str, bytes, bytearray)):
            raise WorkflowExpansionError("workflow expansion edges must be an array")
        if not isinstance(input_params, Sequence) or isinstance(input_params, (str, bytes, bytearray)):
            raise WorkflowExpansionError("workflow expansion input_params must be an array")
        if not isinstance(inputs, Mapping):
            raise WorkflowExpansionError("workflow expansion inputs must be an object")
        if not isinstance(metadata, Mapping):
            raise WorkflowExpansionError("workflow expansion metadata must be an object")
        return cls(
            nodes=tuple(nodes),
            edges=tuple(edges),
            input_params=tuple(input_params),
            output_port=str(value.get("output_port", value.get("outputPort", "")) or ""),
            inputs=dict(inputs),
            subgraph=raw_subgraph,
            name=str(value.get("name") or ""),
            metadata=dict(metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "nodes": [_data_dict(item) for item in self.nodes],
            "edges": [_data_dict(item) for item in self.edges],
            "input_params": [_data_dict(item) for item in self.input_params],
            "output_port": self.output_port,
            "inputs": _json_copy(_data_dict(dict(self.inputs))),
            "name": self.name,
            "metadata": _json_copy(_data_dict(dict(self.metadata))),
        }
        if self.subgraph is not None:
            value["subgraph"] = _data_dict(self.subgraph)
        return value


# Names used in early host integrations and by plugin authors.
DynamicExpansion = WorkflowExpansion
NodeExpansion = WorkflowExpansion
WorkflowNodeExpansion = WorkflowExpansion


@dataclass(frozen=True)
class NodeExecutionResult:
    """A node output plus an optional declarative expansion."""

    outputs: Mapping[str, Any] = field(default_factory=dict)
    expansion: WorkflowExpansion | Mapping[str, Any] | None = None

    def normalized_expansion(self) -> WorkflowExpansion | None:
        if self.expansion is None:
            return None
        if isinstance(self.expansion, WorkflowExpansion):
            return self.expansion
        return WorkflowExpansion.from_dict(self.expansion)


# Alternative spelling retained for adapters and external plugins.
NodeExecutorResult = NodeExecutionResult


def normalize_node_execution_result(raw: Any) -> NodeExecutionResult:
    """Normalize a trusted executor result without executing arbitrary data."""

    if isinstance(raw, NodeExecutionResult):
        result = raw
    elif isinstance(raw, WorkflowExpansion):
        result = NodeExecutionResult(expansion=raw)
    elif isinstance(raw, Mapping):
        has_expansion_field = "__workflow_expansion__" in raw or "expansion" in raw
        marker = raw.get("__workflow_expansion__", raw.get("expansion"))
        # A plugin may use the wire form ``{outputs: {...}, expansion: None}``
        # when it has no dynamic graph for a particular invocation.  Treat it
        # as the result envelope, while preserving a legitimate output port
        # literally named ``outputs`` when no envelope marker is present.
        if has_expansion_field or ("outputs" in raw and "result" in raw):
            outputs = raw.get("outputs", raw.get("result", {}))
            if outputs is None:
                outputs = {}
            if not isinstance(outputs, Mapping):
                raise WorkflowExecutorError("node executor outputs must be an object")
            result = NodeExecutionResult(outputs=dict(outputs), expansion=marker)
        else:
            result = NodeExecutionResult(outputs=dict(raw))
    else:
        raise WorkflowExecutorError("node executor must return an object or NodeExecutionResult")
    if not isinstance(result.outputs, Mapping):
        raise WorkflowExecutorError("node executor outputs must be an object")
    # Validate the wire shape now so a malformed result cannot reach a later
    # graph operation and be mistaken for a host callback.
    if result.expansion is not None:
        expansion = result.normalized_expansion()
        if expansion is None:
            raise WorkflowExpansionError("invalid workflow expansion")
    return NodeExecutionResult(outputs=dict(result.outputs), expansion=result.expansion)


@dataclass(frozen=True)
class ExecutorRegistration:
    type_id: str
    executor: NodeExecutor
    plugin_id: str = "workflow"
    trusted: bool = False


class WorkflowExecutorRegistry:
    """Execution registry keyed by the same type IDs as the schema registry.

    The registry is deliberately independent of plugin discovery.  A host can
    construct it with an existing ``WorkflowNodeRegistry`` and register a
    callable only after the host has explicitly established trust.
    """

    def __init__(self, schema_registry: Any = None) -> None:
        if schema_registry is None:
            # Keep the registry useful as a standalone host integration while
            # avoiding a module-level cycle with ``backend.registry``.  The
            # runner still passes its shared schema registry explicitly.
            from .registry import WorkflowNodeRegistry

            schema_registry = WorkflowNodeRegistry()
        self.schema_registry = schema_registry
        self._executors: dict[str, ExecutorRegistration] = {}

    def get(self, type_id: str) -> NodeExecutor | None:
        registration = self._executors.get(str(type_id or "").strip())
        return registration.executor if registration is not None else None

    def require(self, type_id: str) -> NodeExecutor:
        result = self.get(type_id)
        if result is None:
            raise WorkflowExecutorError(f"workflow node executor is not registered: {type_id}")
        return result

    def registration(self, type_id: str) -> ExecutorRegistration | None:
        return self._executors.get(str(type_id or "").strip())

    def list(self) -> list[ExecutorRegistration]:
        return sorted(self._executors.values(), key=lambda item: item.type_id)

    def register(
        self,
        type_id: str,
        executor: Any,
        *,
        plugin_id: str = "",
        trusted: bool = False,
        replace: bool = False,
    ) -> NodeExecutor:
        clean_type = str(type_id or "").strip()
        if not clean_type:
            raise WorkflowExecutorError("workflow executor type_id is required")
        clean_plugin = str(plugin_id or "workflow").strip() or "workflow"
        if clean_plugin != "workflow" and not trusted:
            raise PermissionError("workflow node executors require a trusted plugin")
        if not _is_executor(executor):
            raise WorkflowExecutorError("workflow node executor has no execute() or callable surface")
        schema_getter = getattr(self.schema_registry, "get", None)
        schema = schema_getter(clean_type) if callable(schema_getter) else None
        if schema is None:
            raise WorkflowExecutorError(
                f"workflow node schema is not registered for executor: {clean_type}"
            )
        schema_plugin = str(getattr(schema, "plugin_id", "workflow") or "workflow")
        if schema_plugin != clean_plugin and clean_plugin != "workflow":
            raise PermissionError(
                f"workflow executor plugin does not match schema: {clean_type}"
            )
        if clean_type in self._executors and not replace:
            raise ValueError(f"workflow node executor already registered: {clean_type}")
        adapted = adapt_node_executor(executor)
        self._executors[clean_type] = ExecutorRegistration(
            type_id=clean_type,
            executor=adapted,
            plugin_id=clean_plugin,
            trusted=bool(trusted or clean_plugin == "workflow"),
        )
        # Keep a schema registry that supports execution lookups in sync too.
        setter = getattr(self.schema_registry, "_set_executor", None)
        if callable(setter):
            setter(clean_type, adapted)
        return adapted

    register_executor = register

    def register_plugin(
        self,
        plugin_id: str,
        executors: Mapping[str, Any] | Sequence[Mapping[str, Any]],
        *,
        trusted: bool = False,
        replace: bool = False,
    ) -> list[NodeExecutor]:
        if not trusted:
            raise PermissionError("workflow node executors require a trusted plugin")
        # Accept the convenient ``[{"schema": {...}, "executor": obj}]``
        # form as well as a pre-registered ``{type_id: executor}`` map.  Both
        # paths still install schema and execution entries together.
        if isinstance(executors, Mapping) and "executor" in executors and (
            "schema" in executors or "name" in executors or "type_id" in executors
        ):
            executors = [executors]
        if not isinstance(executors, Mapping):
            installed: list[NodeExecutor] = []
            for item in executors:
                if not isinstance(item, Mapping):
                    raise WorkflowExecutorError("workflow plugin node entry must be an object")
                raw_schema = item.get("schema", item)
                executor = item.get("executor")
                if executor is None:
                    raise WorkflowExecutorError("workflow plugin node entry requires executor")
                if raw_schema is item:
                    raw_schema = {key: value for key, value in item.items() if key != "executor"}
                if self.schema_registry is None:
                    raise WorkflowExecutorError("workflow executor registry has no schema registry")
                register_schema = getattr(self.schema_registry, "register_schema", None)
                if not callable(register_schema):
                    raise WorkflowExecutorError("workflow schema registry is invalid")
                spec = register_schema(
                    raw_schema,
                    plugin_id=plugin_id,
                    trusted=True,
                    replace=replace,
                )
                installed.append(
                    self.register(
                        spec.type_id,
                        executor,
                        plugin_id=plugin_id,
                        trusted=True,
                        replace=replace,
                    )
                )
            return installed
        return [
            self.register(
                type_id,
                executor,
                plugin_id=plugin_id,
                trusted=True,
                replace=replace,
            )
            for type_id, executor in executors.items()
        ]

    def unregister(self, type_id: str) -> bool:
        clean_type = str(type_id or "").strip()
        registration = self._executors.pop(clean_type, None)
        remover = getattr(self.schema_registry, "_remove_executor", None)
        if callable(remover):
            remover(clean_type)
        return registration is not None


# Friendly aliases for hosts using the shorter name.
NodeExecutorRegistry = WorkflowExecutorRegistry
WorkflowNodeExecutorRegistry = WorkflowExecutorRegistry
WorkflowNodeExecutor = NodeExecutor


def _is_executor(value: Any) -> bool:
    return callable(getattr(value, "execute", None)) or callable(getattr(value, "run", None)) or callable(value)


def _data_dict(value: Any) -> Any:
    # Convert known dataclass/data-container values recursively before JSON
    # serialization.  This deliberately preserves unsupported objects (such
    # as callables) so the runner's strict expansion validator can reject
    # them; ``default=str`` would accidentally turn them into trusted data.
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _data_dict(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {key: _data_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_data_dict(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _data_dict(value.to_dict())
    return value


def _json_copy(value: Any) -> Any:
    try:
        # Expansion data is a trust boundary.  Do not stringify a callable or
        # arbitrary host object into apparently valid JSON here; the runtime
        # must be able to reject it instead.
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return value


# Additional descriptive spellings used by external plugin hosts.  Keep the
# canonical names above stable while making the wire contract discoverable.
Expansion = WorkflowExpansion
DynamicNodeExpansion = WorkflowExpansion
WorkflowDynamicExpansion = WorkflowExpansion
WorkflowNodeExecutionResult = NodeExecutionResult
normalize_execution_result = normalize_node_execution_result
normalize_node_result = normalize_node_execution_result


__all__ = [
    "DynamicExpansion",
    "DynamicNodeExpansion",
    "ExecutorRegistration",
    "Expansion",
    "NodeExecutionResult",
    "NodeExecutor",
    "NodeExecutorRegistry",
    "NodeExecutorResult",
    "NodeExpansion",
    "WorkflowExpansion",
    "WorkflowExpansionError",
    "WorkflowExecutorError",
    "WorkflowExecutorRegistry",
    "WorkflowDynamicExpansion",
    "WorkflowNodeExecutionResult",
    "WorkflowNodeExpansion",
    "WorkflowNodeExecutorRegistry",
    "WorkflowNodeExecutor",
    "normalize_node_execution_result",
    "normalize_execution_result",
    "normalize_node_result",
]
