"""Schema-only workflow node type registry.

The registry deliberately contains *descriptions*, not import paths or Python
callbacks.  This is the boundary that lets a Workflow document offer a
ComfyUI-like ``object_info`` query without recreating ComfyUI's unrestricted
custom-node loader.  Built-in executors remain owned by :mod:`runtime`; an
installed plugin may contribute additional schemas only after the host has
marked that plugin trusted.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from .capabilities import (
    CapabilityError,
    WorkflowCapabilityRegistry,
    WorkflowNodeCapabilities,
)
from .node_versions import NodeMigration, NodeMigrationRegistry, NodeVersionError, parse_node_version


class NodeSchemaError(ValueError):
    """Raised when a node type schema is malformed or unsafe."""


@dataclass(frozen=True)
class WorkflowNodeType:
    """A data-only node type description.

    ``input_schema`` and ``output_schema`` use JSON Schema-like objects.  The
    runtime does not execute an arbitrary value from a schema; ``executor`` is
    informational and may only be one of the host-owned built-in executors.
    """

    type_id: str
    title: str = ""
    description: str = ""
    category: str = "workflow"
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    pure: bool = False
    deterministic: bool = False
    executor: str = "builtin"
    plugin_id: str = "workflow"
    builtin: bool = False
    type_version: int = 1
    capabilities: tuple[str, ...] = ()
    resource_class: str = "default"
    resource_requirements: dict[str, Any] = field(default_factory=dict, compare=False)
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        # Keep direct dataclass construction as safe as ``from_dict``.  A
        # schema can describe requirements but cannot grant those resources.
        declaration = WorkflowNodeCapabilities(
            self.capabilities,
            self.resource_class,
            self.resource_requirements,
        )
        object.__setattr__(self, "type_version", parse_node_version(self.type_version))
        object.__setattr__(self, "capabilities", declaration.capabilities)
        object.__setattr__(self, "resource_class", declaration.resource_class)
        object.__setattr__(self, "resource_requirements", declaration.resource_requirements)

    @property
    def name(self) -> str:
        return self.type_id

    @property
    def kind(self) -> str:
        return self.type_id

    def to_dict(self) -> dict[str, Any]:
        result = {
            "name": self.type_id,
            "type_id": self.type_id,
            "display_name": self.title or self.type_id,
            "title": self.title or self.type_id,
            "description": self.description,
            "category": self.category,
            "input": _json_copy(self.input_schema),
            "output": _json_copy(self.output_schema),
            "input_schema": _json_copy(self.input_schema),
            "output_schema": _json_copy(self.output_schema),
            "pure": self.pure,
            "deterministic": self.deterministic,
            "executor": self.executor,
            "plugin_id": self.plugin_id,
            "builtin": self.builtin,
            "type_version": self.type_version,
            "version": self.type_version,
            "capabilities": list(self.capabilities),
            "resource_class": self.resource_class,
            "resource_requirements": _json_copy(self.resource_requirements),
        }
        # Catalog lifecycle metadata is data, not executable behavior.  Keep
        # it available to every object_info client so legacy aliases remain
        # loadable without cluttering the default add-node catalog.
        for key in ("legacy", "deprecated", "hidden", "canonical_type"):
            if key in self.raw:
                result[key] = _json_copy(self.raw[key])
        return result

    def object_info(self) -> dict[str, Any]:
        """Return a ComfyUI-style object-info entry.

        ``input`` and ``output`` are preserved as declared, while the
        additional fields make the trust/cache contract discoverable to a
        client.  No executable Python reference is included.
        """

        info = self.to_dict()
        info.pop("input_schema", None)
        info.pop("output_schema", None)
        info["output_name"] = list(self.output_schema) if isinstance(self.output_schema, dict) else []
        info["output_is_list"] = [False for _ in info["output_name"]]
        return info

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        plugin_id: str = "workflow",
        builtin: bool = False,
    ) -> "WorkflowNodeType":
        if not isinstance(value, Mapping):
            raise NodeSchemaError("node type schema must be an object")
        type_id = str(value.get("type_id") or value.get("name") or value.get("kind") or "").strip()
        if not type_id:
            raise NodeSchemaError("node type schema requires name")
        if any(char.isspace() for char in type_id) or ":" in type_id:
            raise NodeSchemaError("node type name must be a single safe token")
        for forbidden in ("handler", "module", "python", "import", "entrypoint", "loader"):
            if value.get(forbidden) not in (None, "", False, []):
                raise NodeSchemaError(f"node type schema cannot load executable field: {forbidden}")
        # ``executor`` is descriptive only.  Reject import-looking values and
        # callables so a schema cannot become an arbitrary Python loader.
        raw_executor = value.get("executor", "builtin")
        if callable(raw_executor):
            raise NodeSchemaError("node type executor must be data, not a callable")
        executor = str(raw_executor or "builtin").strip()
        if not executor or "." in executor or ":" in executor or "/" in executor or "\\" in executor:
            raise NodeSchemaError("node type executor must not contain a Python import path")

        input_schema = value.get("input", value.get("input_schema", {}))
        output_schema = value.get("output", value.get("output_schema", {}))
        if not isinstance(input_schema, Mapping) or not isinstance(output_schema, Mapping):
            raise NodeSchemaError("node type input/output must be objects")
        # Ensure the schemas are JSON data.  In particular this excludes
        # callable/default object values supplied by an untrusted extension.
        try:
            json.dumps(dict(value), ensure_ascii=False)
            json.dumps(input_schema, ensure_ascii=False)
            json.dumps(output_schema, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise NodeSchemaError("node type schema must contain JSON values only") from exc
        try:
            declaration = WorkflowNodeCapabilities.from_dict(value)
            type_version = parse_node_version(
                value.get("type_version", value.get("typeVersion", value.get("version", 1)))
            )
        except (CapabilityError, NodeVersionError) as exc:
            raise NodeSchemaError(str(exc)) from exc
        return cls(
            type_id=type_id,
            title=str(value.get("display_name") or value.get("title") or type_id),
            description=str(value.get("description") or ""),
            category=str(value.get("category") or "workflow"),
            input_schema=dict(input_schema),
            output_schema=dict(output_schema),
            pure=bool(value.get("pure", False)),
            deterministic=bool(value.get("deterministic", False)),
            executor=executor,
            plugin_id=str(value.get("plugin_id") or plugin_id or "workflow"),
            builtin=bool(value.get("builtin", builtin)),
            type_version=type_version,
            capabilities=declaration.capabilities,
            resource_class=declaration.resource_class,
            resource_requirements=declaration.resource_requirements,
            raw=dict(value),
        )


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return value


def _has_executor_surface(value: Any) -> bool:
    """Return whether a trusted plugin supplied an executable object.

    Executors are commonly instances with an ``execute`` method rather than
    function objects, so checking only ``callable(value)`` would reject a
    valid object before the explicit trust boundary gets a chance to adapt it.
    """

    return (
        callable(value)
        or callable(getattr(value, "execute", None))
        or callable(getattr(value, "run", None))
    )


_BUILTIN_SCHEMAS: tuple[dict[str, Any], ...] = (
    {
        "name": "model",
        "display_name": "Model",
        "description": "Run one model completion with typed inputs and outputs",
        "category": "workflow/model",
        "input": {"required": {}, "optional": {"instruction": {"type": "string"}}},
        "output": {"output": {"type": "any"}},
        "executor": "model",
        "pure": False,
        "deterministic": False,
    },
    {
        "name": "agent",
        "display_name": "Agent",
        "description": "Run an independent tool-capable agent",
        "category": "workflow/agent",
        "input": {"required": {}, "optional": {"instruction": {"type": "string"}}},
        "output": {"output": {"type": "any"}},
        "executor": "agent",
        "pure": False,
        "deterministic": False,
    },
    {
        "name": "ai",
        "display_name": "AI",
        "description": "Legacy Model/Agent compatibility node",
        "category": "workflow/legacy",
        "legacy": True,
        "deprecated": True,
        "hidden": True,
        "input": {"required": {}, "optional": {"instruction": {"type": "string"}}},
        "output": {"output": {"type": "any"}},
        "executor": "ai",
        "pure": False,
        "deterministic": False,
    },
    {
        "name": "command",
        "display_name": "Command",
        "description": "Execute a host-approved shell command",
        "category": "workflow/runtime",
        "input": {"required": {}, "optional": {"stdin": {"type": "any"}}},
        "output": {"output": {"type": "string"}},
        "executor": "command",
        "pure": False,
        "deterministic": False,
    },
    {
        "name": "script",
        "display_name": "Script",
        "description": "Execute a host-approved Python script",
        "category": "workflow/runtime",
        "legacy": True,
        "deprecated": True,
        "hidden": True,
        "canonical_type": "python",
        "input": {"required": {}, "optional": {"inputs": {"type": "object"}}},
        "output": {"output": {"type": "any"}},
        "executor": "script",
        "pure": False,
        "deterministic": False,
    },
    {
        "name": "python",
        "display_name": "Python Script",
        "description": "Execute a host-approved Python script",
        "category": "workflow/runtime",
        "input": {"required": {}, "optional": {"inputs": {"type": "object"}}},
        "output": {"output": {"type": "any"}},
        "executor": "script",
        "pure": False,
        "deterministic": False,
    },
    {
        "name": "content",
        "display_name": "Content",
        "description": "Emit a constant content value",
        "category": "workflow/data",
        "legacy": True,
        "deprecated": True,
        "hidden": True,
        "canonical_type": "constant",
        "input": {"required": {}, "optional": {}},
        "output": {"output": {"type": "any"}},
        "executor": "content",
        # Content is the one built-in whose semantics are intrinsically pure
        # and deterministic.  A node may opt out with config flags.
        "pure": True,
        "deterministic": True,
    },
    {
        "name": "constant",
        "display_name": "Constant",
        "description": "Emit a constant JSON-compatible value",
        "category": "workflow/data",
        "input": {"required": {}, "optional": {}},
        "output": {"output": {"type": "any"}},
        "executor": "content",
        "pure": True,
        "deterministic": True,
    },
    {
        "name": "input",
        "display_name": "Input",
        "description": "Expose workflow inputs to the graph",
        "category": "workflow/io",
        "input": {"required": {}, "optional": {"value": {"type": "any"}}},
        "output": {"output": {"type": "any"}},
        "executor": "passthrough",
        "pure": True,
        "deterministic": True,
    },
    {
        "name": "output",
        "display_name": "Output",
        "description": "Expose a graph value as workflow output",
        "category": "workflow/io",
        "input": {"required": {"value": {"type": "any"}}, "optional": {}},
        "output": {"output": {"type": "any"}},
        "executor": "passthrough",
        "pure": True,
        "deterministic": True,
    },
    {
        "name": "template",
        "display_name": "Template",
        "description": "Render a text template from named inputs",
        "category": "workflow/transform",
        "input": {"required": {}, "optional": {"values": {"type": "object"}}},
        "output": {"output": {"type": "string"}},
        "executor": "template",
        "pure": True,
        "deterministic": True,
    },
    {
        "name": "transform",
        "display_name": "Transform",
        "description": "Render a deterministic template transform",
        "category": "workflow/transform",
        "legacy": True,
        "deprecated": True,
        "hidden": True,
        "canonical_type": "template",
        "input": {"required": {}, "optional": {"values": {"type": "object"}}},
        "output": {"output": {"type": "string"}},
        "executor": "template",
        "pure": True,
        "deterministic": True,
    },
    {
        "name": "condition",
        "display_name": "Condition",
        "description": "Route a value to true/false outputs using an expression",
        "category": "workflow/control",
        "input": {"required": {"value": {"type": "any"}}, "optional": {}},
        "output": {"true": {"type": "any"}, "false": {"type": "any"}},
        "executor": "condition",
        "pure": True,
        "deterministic": True,
    },
    {
        "name": "branch",
        "display_name": "Branch",
        "description": "Alias of Condition for branch-oriented graphs",
        "category": "workflow/control",
        "legacy": True,
        "deprecated": True,
        "hidden": True,
        "canonical_type": "condition",
        "input": {"required": {"value": {"type": "any"}}, "optional": {}},
        "output": {"true": {"type": "any"}, "false": {"type": "any"}},
        "executor": "condition",
        "pure": True,
        "deterministic": True,
    },
    {
        "name": "merge",
        "display_name": "Merge",
        "description": "Emit the first active input",
        "category": "workflow/control",
        "input": {"required": {}, "optional": {"values": {"type": "any"}}},
        "output": {"output": {"type": "any"}},
        "executor": "merge",
        "pure": True,
        "deterministic": True,
    },
    {
        "name": "join",
        "display_name": "Join",
        "description": "Collect active named inputs into one object",
        "category": "workflow/control",
        "input": {"required": {}, "optional": {"values": {"type": "any"}}},
        "output": {"output": {"type": "object"}},
        "executor": "join",
        "pure": True,
        "deterministic": True,
    },
    {
        "name": "wait_event",
        "display_name": "Wait for Event",
        "description": "Pause durably until a matching workflow.signal event arrives",
        "category": "workflow/control",
        "input": {"required": {}, "optional": {}},
        "output": {"result": {"type": "object"}},
        "executor": "wait_event",
        "pure": False,
        "deterministic": False,
    },
    {
        "name": "approval",
        "display_name": "Approval",
        "description": "Pause durably for an approve or reject decision",
        "category": "workflow/control",
        "input": {"required": {}, "optional": {"request": {"type": "any"}}},
        "output": {"result": {"type": "object"}},
        "executor": "approval",
        "pure": False,
        "deterministic": False,
    },
    {
        "name": "subgraph",
        "display_name": "Subgraph",
        "description": "Invoke another saved workflow",
        "category": "workflow/composition",
        "input": {"required": {}, "optional": {"inputs": {"type": "object"}}},
        "output": {"output": {"type": "any"}},
        "executor": "subgraph",
        "pure": False,
        "deterministic": False,
    },
)


class WorkflowNodeRegistry:
    """Registry for host and trusted-plugin node schemas.

    The only extension API accepts JSON-compatible schema data.  There is no
    ``load``/``import`` method by design; callers must explicitly pass
    ``trusted=True`` after their own plugin trust decision.
    """

    def __init__(self, schemas: Iterable[Mapping[str, Any]] | None = None) -> None:
        self._types: dict[str, WorkflowNodeType] = {}
        self._capabilities = WorkflowCapabilityRegistry()
        self._migrations = NodeMigrationRegistry()
        # Execution is kept alongside schemas so a plugin cannot accidentally
        # advertise a node type in one registry while installing its executor
        # in another.  The value is populated only by the explicit trusted
        # executor registration APIs below; schema-only registrations remain
        # valid for object-info/catalog use but are not executable.
        self._executors: dict[str, Any] = {}
        for raw in _BUILTIN_SCHEMAS:
            spec = WorkflowNodeType.from_dict(raw, plugin_id="workflow", builtin=True)
            self._types[spec.type_id] = spec
            self._capabilities.register(
                spec.type_id,
                WorkflowNodeCapabilities(
                    spec.capabilities,
                    spec.resource_class,
                    spec.resource_requirements,
                ),
                replace=True,
            )
        for raw in schemas or ():
            self.register_schema(raw, plugin_id="workflow", trusted=True)

    def register_schema(
        self,
        schema: Mapping[str, Any] | WorkflowNodeType,
        *,
        plugin_id: str = "",
        trusted: bool = False,
        replace: bool = False,
        executor: Any = None,
    ) -> WorkflowNodeType:
        if not trusted:
            raise PermissionError("workflow node schema extensions require a trusted plugin")
        spec = schema if isinstance(schema, WorkflowNodeType) else WorkflowNodeType.from_dict(
            schema, plugin_id=plugin_id or "plugin"
        )
        if not spec.plugin_id or spec.plugin_id == "workflow" and plugin_id:
            spec = replace(spec, plugin_id=plugin_id or spec.plugin_id)
        existing = self._types.get(spec.type_id)
        if existing is not None and not replace:
            raise ValueError(f"workflow node type already registered: {spec.type_id}")
        if existing is not None and existing.builtin and spec.plugin_id != "workflow":
            raise ValueError(f"cannot replace built-in workflow node type: {spec.type_id}")
        self._types[spec.type_id] = spec
        self._capabilities.register(
            spec.type_id,
            WorkflowNodeCapabilities(
                spec.capabilities,
                spec.resource_class,
                spec.resource_requirements,
            ),
            replace=True,
        )
        if executor is not None:
            self.register_executor(
                spec.type_id,
                executor,
                plugin_id=spec.plugin_id,
                trusted=trusted,
                replace=replace,
            )
        return spec

    # Friendly alias used by plugin hosts.
    register = register_schema

    def register_plugin(
        self,
        plugin_id: str,
        schemas: Iterable[Mapping[str, Any]] | Mapping[str, Any],
        *,
        trusted: bool = False,
        replace: bool = False,
        executors: Mapping[str, Any] | None = None,
    ) -> list[WorkflowNodeType]:
        if not trusted:
            raise PermissionError("workflow node schema extensions require a trusted plugin")
        if isinstance(schemas, Mapping):
            raw_items = schemas.get("nodes", schemas.get("node_types", schemas.get("schemas", [])))
            if isinstance(raw_items, Mapping):
                raw_items = list(raw_items.values())
            if not isinstance(raw_items, list):
                raw_items = [schemas]
        else:
            raw_items = list(schemas)
        registered: list[WorkflowNodeType] = []
        for item in raw_items:
            # A trusted plugin may provide a callable beside its data schema
            # through this explicit API.  ``WorkflowNodeType.from_dict`` still
            # rejects executable values when called directly, preserving the
            # schema-only trust boundary.
            raw_schema = dict(item) if isinstance(item, Mapping) else item
            inline_executor = None
            if isinstance(raw_schema, dict) and _has_executor_surface(raw_schema.get("executor")):
                inline_executor = raw_schema.pop("executor")
            spec = self.register_schema(raw_schema, plugin_id=plugin_id, trusted=True, replace=replace)
            registered.append(spec)
            if inline_executor is not None:
                self.register_executor(
                    spec.type_id,
                    inline_executor,
                    plugin_id=plugin_id,
                    trusted=True,
                    replace=replace,
                )
        if executors:
            for type_id, executor in executors.items():
                self.register_executor(
                    type_id,
                    executor,
                    plugin_id=plugin_id,
                    trusted=True,
                    replace=replace,
                )
        return registered

    def register_executor(
        self,
        type_id: str,
        executor: Any,
        *,
        plugin_id: str = "",
        trusted: bool = False,
        replace: bool = False,
    ) -> Any:
        """Install an executor for an already-registered node schema.

        The registry intentionally does not import or resolve executor paths.
        Callers pass the host-created object after their plugin trust check;
        untrusted plugins and schema-less types are rejected at this boundary.
        """
        clean_type = str(type_id or "").strip()
        clean_plugin = str(plugin_id or "workflow").strip() or "workflow"
        if clean_plugin != "workflow" and not trusted:
            raise PermissionError("workflow node executors require a trusted plugin")
        if not (callable(getattr(executor, "execute", None)) or callable(getattr(executor, "run", None)) or callable(executor)):
            raise TypeError("workflow node executor has no execute() or callable surface")
        spec = self.get(clean_type)
        if spec is None:
            raise KeyError(f"workflow node schema is not registered: {clean_type}")
        if clean_plugin != "workflow" and spec.plugin_id != clean_plugin:
            raise PermissionError(f"workflow executor plugin does not match schema: {clean_type}")
        if clean_type in self._executors and not replace:
            raise ValueError(f"workflow node executor already registered: {clean_type}")
        self._executors[clean_type] = executor
        return executor

    # Short aliases used by host/plugin adapters.
    register_node_executor = register_executor
    set_executor = register_executor

    def get_executor(self, type_id: str) -> Any | None:
        return self._executors.get(str(type_id or "").strip())

    executor_for = get_executor

    def require_executor(self, type_id: str) -> Any:
        clean_type = str(type_id or "").strip()
        executor = self.get_executor(clean_type)
        if executor is None:
            raise KeyError(f"workflow node executor is not registered: {clean_type}")
        return executor

    def has_executor(self, type_id: str) -> bool:
        return self.get_executor(type_id) is not None

    def _set_executor(self, type_id: str, executor: Any) -> None:
        """Internal synchronization hook for ``WorkflowExecutorRegistry``."""
        self._executors[str(type_id or "").strip()] = executor

    def _remove_executor(self, type_id: str) -> None:
        self._executors.pop(str(type_id or "").strip(), None)

    # ── node version and capability contracts ──────────────────────────────

    @property
    def migrations(self) -> NodeMigrationRegistry:
        """The explicit host/plugin-owned migration registry."""

        return self._migrations

    @property
    def capability_registry(self) -> WorkflowCapabilityRegistry:
        """Data-only capability declarations keyed by node type."""

        return self._capabilities

    def register_migration(
        self,
        type_id: str,
        from_version: int,
        to_version: int,
        migrate: Any,
        *,
        plugin_id: str = "workflow",
        trusted: bool = False,
        replace: bool = False,
    ) -> NodeMigration:
        """Register one explicit node-version migration.

        Built-in/host migrations use the default ``workflow`` owner.  A
        plugin migration must be installed by a caller that has already made
        its trust decision; workflow documents cannot register migrations.
        """

        clean_plugin = str(plugin_id or "workflow").strip() or "workflow"
        if clean_plugin != "workflow" and not trusted:
            raise PermissionError("workflow node migrations require a trusted plugin")
        spec = self.get(type_id)
        if spec is None:
            raise KeyError(f"workflow node schema is not registered: {type_id}")
        if clean_plugin != "workflow" and spec.plugin_id != clean_plugin:
            raise PermissionError(f"workflow migration plugin does not match schema: {type_id}")
        return self._migrations.register(
            type_id,
            from_version,
            to_version,
            migrate,
            replace=replace,
        )

    register_node_migration = register_migration

    def migrate_node(
        self,
        node: Mapping[str, Any],
        *,
        target_version: int | None = None,
    ) -> dict[str, Any]:
        """Apply only explicitly registered migrations to one node."""

        nested_type = node.get("type") if isinstance(node, Mapping) and isinstance(node.get("type"), Mapping) else {}
        type_id = (
            node.get("type_id")
            or node.get("typeId")
            or node.get("kind")
            or nested_type.get("id")
            if isinstance(node, Mapping)
            else ""
        )
        return self._migrations.migrate_node(
            node,
            target_version=target_version,
            type_id=str(type_id or ""),
        )

    resolve_node = migrate_node

    def register_capabilities(
        self,
        type_id: str,
        declaration: WorkflowNodeCapabilities | Mapping[str, Any],
        *,
        plugin_id: str = "workflow",
        trusted: bool = False,
        replace: bool = False,
    ) -> WorkflowNodeCapabilities:
        """Update a schema's data-only capability/resource declaration."""

        clean_plugin = str(plugin_id or "workflow").strip() or "workflow"
        if clean_plugin != "workflow" and not trusted:
            raise PermissionError("workflow capability extensions require a trusted plugin")
        spec = self.require(type_id)
        if clean_plugin != "workflow" and spec.plugin_id != clean_plugin:
            raise PermissionError(f"workflow capability plugin does not match schema: {type_id}")
        if self._capabilities.get(spec.type_id) is not None and not replace:
            raise ValueError(f"workflow node capabilities already registered: {spec.type_id}")
        result = declaration if isinstance(declaration, WorkflowNodeCapabilities) else WorkflowNodeCapabilities.from_dict(declaration)
        self._capabilities.register(spec.type_id, result, replace=True)
        # Keep object_info and the capability registry in sync.  The schema
        # remains data-only and replacing it does not alter its executor.
        self._types[spec.type_id] = replace(
            spec,
            capabilities=result.capabilities,
            resource_class=result.resource_class,
            resource_requirements=result.resource_requirements,
        )
        return result

    def capabilities_for(self, type_id: str) -> tuple[str, ...]:
        return self.require(type_id).capabilities

    node_capabilities = capabilities_for

    def resource_class_for(self, type_id: str) -> str:
        return self.require(type_id).resource_class

    def resource_requirements_for(self, type_id: str) -> dict[str, Any]:
        return _json_copy(self.require(type_id).resource_requirements)

    def get(self, type_id: str) -> WorkflowNodeType | None:
        return self._types.get(str(type_id or "").strip())

    def require(self, type_id: str) -> WorkflowNodeType:
        result = self.get(type_id)
        if result is None:
            raise KeyError(type_id)
        return result

    def list(self, *, plugin_id: str | None = None) -> list[WorkflowNodeType]:
        values = list(self._types.values())
        if plugin_id is not None:
            values = [item for item in values if item.plugin_id == plugin_id]
        return sorted(values, key=lambda item: item.type_id)

    def object_info(self, type_id: str | None = None) -> dict[str, Any]:
        """Return all entries or a single entry keyed by node type name."""
        if type_id:
            spec = self.require(type_id)
            return {spec.type_id: spec.object_info()}
        return {spec.type_id: spec.object_info() for spec in self.list()}

    def get_object_info(self, type_id: str) -> dict[str, Any]:
        """Return one object-info entry without its type-name wrapper."""
        return self.require(type_id).object_info()

    node_info = get_object_info

    # ComfyUI clients often call this query ``object_info``; ``query`` keeps a
    # compact host-side spelling while retaining the same return contract.
    query = object_info

    def schemas(self) -> list[dict[str, Any]]:
        return [spec.to_dict() for spec in self.list()]


# Names used by early workflow prototypes and by external plugin adapters.
NodeTypeRegistry = WorkflowNodeRegistry
WorkflowNodeSchema = WorkflowNodeType

# Re-export the execution registry from the schema module for callers that
# treat the two registries as one plugin boundary.  The implementation itself
# lives in ``executors`` to keep runtime dispatch dependencies directional.
from .executors import (  # noqa: E402  — intentional late import
    ExecutorRegistration,
    NodeExecutorRegistry,
    WorkflowExecutorRegistry,
    WorkflowNodeExecutor,
    WorkflowNodeExecutorRegistry,
)


__all__ = [
    "CapabilityError",
    "NodeSchemaError",
    "NodeMigration",
    "NodeMigrationRegistry",
    "NodeVersionError",
    "NodeTypeRegistry",
    "ExecutorRegistration",
    "NodeExecutorRegistry",
    "WorkflowNodeRegistry",
    "WorkflowNodeSchema",
    "WorkflowNodeType",
    "WorkflowCapabilityRegistry",
    "WorkflowNodeCapabilities",
    "WorkflowExecutorRegistry",
    "WorkflowNodeExecutorRegistry",
    "WorkflowNodeExecutor",
]
