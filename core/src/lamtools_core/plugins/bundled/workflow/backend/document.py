"""Versioned workflow documents, execution prompts and interchange adapters.

The editable document is intentionally distinct from the canvas-free prompt
consumed by an executor.  This mirrors the useful part of ComfyUI's public
workflow/prompt split without depending on its implementation.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import uuid
from typing import Any, Iterable

from .credentials import CredentialError, serialize_workflow_value
from .flow_control import (
    FlowControlError,
    FlowControlPolicy,
    canonicalize_flow_control,
    canonicalize_flow_control_policy,
    flow_control_from_document,
)
from .node_versions import NodeVersionError, parse_node_version
from .expressions import ExpressionError, validate as validate_expression


DOCUMENT_FORMAT = "lamtools.workflow"
DOCUMENT_VERSION = 2
PROMPT_FORMAT = "lamtools.execution-prompt"
PROMPT_VERSION = 1
SEMANTIC_FORMAT = "lamtools.semantic-graph"
SEMANTIC_VERSION = 1
TRIGGER_TYPES = frozenset({"manual", "once", "interval", "calendar", "event"})


class WorkflowDocumentError(ValueError):
    """Raised when a V2 document or interchange payload is invalid."""


def _copy(value: Any) -> Any:
    return deepcopy(value)


def _stable_id(prefix: str, *parts: object) -> str:
    seed = "\x1f".join(str(part) for part in parts)
    return f"{prefix}_{uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:16]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _contract_copy(value: Any, *, path: str) -> Any:
    """Copy persisted JSON while rejecting embedded workflow secrets."""

    try:
        return serialize_workflow_value(value, path=path)
    except CredentialError as exc:
        raise WorkflowDocumentError(str(exc)) from exc


def _normalize_triggers(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise WorkflowDocumentError("triggers must be an array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise WorkflowDocumentError(f"trigger {index} must be an object")
        kind = str(raw.get("type") or raw.get("kind") or "").strip().lower()
        if kind not in TRIGGER_TYPES:
            raise WorkflowDocumentError(
                f"trigger {index} has unsupported type {kind!r}; expected one of {sorted(TRIGGER_TYPES)}"
            )
        trigger_id = str(raw.get("id") or _stable_id("trigger", index, kind)).strip()
        if not trigger_id or trigger_id in seen:
            raise WorkflowDocumentError(f"missing or duplicate trigger id: {trigger_id!r}")
        seen.add(trigger_id)
        item = _contract_copy(raw, path=f"triggers[{index}]")
        # Keep unknown extension fields for forward-compatible round trips,
        # while normalising the two aliases used by early prototypes.
        item.pop("kind", None)
        item["id"] = trigger_id
        item["type"] = kind
        item["enabled"] = bool(raw.get("enabled", True))
        if kind == "once":
            when = raw.get("at", raw.get("run_at"))
            if not isinstance(when, (str, int, float)) or isinstance(when, bool) or not str(when).strip():
                raise WorkflowDocumentError("once trigger requires a non-empty at/run_at value")
            item["at"] = when
            item.pop("run_at", None)
        elif kind == "interval":
            raw_seconds = raw.get(
                "every_seconds",
                raw.get("interval_seconds", raw.get("seconds", raw.get("every"))),
            )
            if isinstance(raw_seconds, bool) or not isinstance(raw_seconds, (int, float)) or raw_seconds <= 0:
                raise WorkflowDocumentError("interval trigger requires positive every_seconds")
            item["every_seconds"] = raw_seconds
            item.pop("interval_seconds", None)
            item.pop("seconds", None)
            item.pop("every", None)
        elif kind == "calendar":
            frequency = str(raw.get("frequency") or "daily").strip().lower()
            if frequency not in {"daily", "monthly"}:
                raise WorkflowDocumentError("calendar frequency must be daily or monthly")
            wall_time = str(raw.get("time") or "").strip()
            if not wall_time:
                raise WorkflowDocumentError("calendar trigger requires time")
            item["frequency"] = frequency
            item["time"] = wall_time
            item["timezone"] = str(raw.get("timezone") or "Asia/Shanghai").strip()
            if frequency == "monthly":
                raw_day = raw.get("day")
                if isinstance(raw_day, bool):
                    raise WorkflowDocumentError("monthly calendar trigger requires day")
                try:
                    day = int(raw_day)
                except (TypeError, ValueError) as exc:
                    raise WorkflowDocumentError("monthly calendar trigger requires day") from exc
                if not 1 <= day <= 31:
                    raise WorkflowDocumentError("monthly calendar day must be between 1 and 31")
                item["day"] = day
            else:
                item.pop("day", None)
            item.pop("rrule", None)
            item.pop("schedule", None)
        elif kind == "event":
            event_name = raw.get("event_type", raw.get("event", raw.get("event_name")))
            if not isinstance(event_name, str) or not event_name.strip():
                raise WorkflowDocumentError("event trigger requires a non-empty event_type")
            item["event_type"] = event_name.strip()
            item.pop("event", None)
            item.pop("event_name", None)
        result.append(item)
    return result


def _normalize_policies(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise WorkflowDocumentError("policies must be an object")
    item = _contract_copy(value, path="policies")
    # Policy keys are defaults for an execution engine, not execution itself.
    # Unknown JSON keys are retained for host extensions; known keys receive
    # shape/range checks so malformed policy data cannot be silently ignored.
    for key in ("timeout_seconds", "max_concurrency", "retry_attempts"):
        if key not in item:
            continue
        raw = item[key]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw < 0:
            raise WorkflowDocumentError(f"policies.{key} must be a non-negative number")
        if key != "timeout_seconds" and int(raw) != raw:
            raise WorkflowDocumentError(f"policies.{key} must be an integer")
        if key != "timeout_seconds" and raw < 1:
            raise WorkflowDocumentError(f"policies.{key} must be positive")
    if "permissions" in item:
        if not isinstance(item["permissions"], list) or not all(isinstance(value, str) and value.strip() for value in item["permissions"]):
            raise WorkflowDocumentError("policies.permissions must be an array of names")
        item["permissions"] = [value.strip() for value in item["permissions"]]
    if "on_error" in item and not isinstance(item["on_error"], (str, dict)):
        raise WorkflowDocumentError("policies.on_error must be a string or object")
    if "retry" in item and not isinstance(item["retry"], dict):
        raise WorkflowDocumentError("policies.retry must be an object")
    if "cache" in item and not isinstance(item["cache"], str):
        raise WorkflowDocumentError("policies.cache must be a string")
    if "resource_class" in item and not isinstance(item["resource_class"], str):
        raise WorkflowDocumentError("policies.resource_class must be a string")
    # Flow-control policy is a first-class, engine-facing contract.  Keep the
    # older extension/timeout fields above lossless, but canonicalise and
    # validate the scheduling fields strictly so a malformed strategy cannot
    # be silently ignored by a later runtime integration.
    flow_aliases = {
        "flow_control": "flow_control",
        "flowControl": "flow_control",
        "rateLimit": "rate_limit",
        "rate-limit": "rate_limit",
        "rateLimitPolicy": "rate_limit",
        "minInterval": "throttle",
        "minIntervalSeconds": "throttle",
        "debouncePolicy": "debounce",
    }
    flow_keys = {"concurrency", "rate_limit", "throttle", "debounce", "priority", *flow_aliases}
    flow_raw: dict[str, Any] = {}
    for key in tuple(item):
        if key in flow_keys:
            canonical_key = flow_aliases.get(key, key)
            if canonical_key in flow_raw and flow_raw[canonical_key] != item[key]:
                raise WorkflowDocumentError(
                    f"policies contains conflicting aliases for {canonical_key}"
                )
            flow_raw[canonical_key] = item[key]
            item.pop(key, None)
    if flow_raw:
        try:
            if "flow_control" in flow_raw:
                if len(flow_raw) != 1:
                    raise FlowControlError("flow_control wrapper cannot be combined with sibling fields")
                item.update(canonicalize_flow_control(flow_raw["flow_control"]))
            else:
                item.update(canonicalize_flow_control(flow_raw))
        except FlowControlError as exc:
            raise WorkflowDocumentError(f"invalid flow-control policy: {exc}") from exc
    return item


def _migrate_document_node(raw: dict[str, Any], node_registry: Any | None) -> dict[str, Any]:
    """Apply a host-registered node migration chain when one is requested."""

    if node_registry is None:
        return raw
    type_ref = raw.get("type")
    if not isinstance(type_ref, dict):
        return raw
    type_id = str(type_ref.get("id") or "").strip()
    if not type_id:
        return raw
    try:
        spec = node_registry.get(type_id)
    except (AttributeError, TypeError):
        spec = None
    if spec is None:
        # Unknown node types remain readable/schema-only; no migration can be
        # inferred without a registered target schema.
        return raw
    try:
        source_version = parse_node_version(type_ref.get("version", 1))
        target_version = parse_node_version(getattr(spec, "type_version", source_version))
    except NodeVersionError as exc:
        raise WorkflowDocumentError(f"node {type_id!r} has invalid type.version") from exc
    if target_version <= source_version:
        return raw
    candidate = _copy(raw)
    candidate["type_id"] = type_id
    candidate["type_version"] = source_version
    try:
        migrated = node_registry.migrate_node(candidate, target_version=target_version)
    except (KeyError, NodeVersionError, ValueError) as exc:
        raise WorkflowDocumentError(
            f"no explicit migration chain for node {type_id!r}: {source_version} -> {target_version}"
        ) from exc
    if not isinstance(migrated, dict):
        raise WorkflowDocumentError(f"node migration for {type_id!r} did not return an object")
    result = _copy(migrated)
    nested_type = result.get("type") if isinstance(result.get("type"), dict) else {}
    result["type"] = {
        **nested_type,
        "id": type_id,
        "version": target_version,
    }
    # A few legacy migration functions naturally return ``config`` or
    # ``parameters``; map those aliases into the canonical V2 params field.
    if "params" not in result:
        if isinstance(result.get("config"), dict):
            result["params"] = result["config"]
        elif isinstance(result.get("parameters"), dict):
            result["params"] = result["parameters"]
    return result


def is_v2_document(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.get("format") == DOCUMENT_FORMAT
        and value.get("version") == DOCUMENT_VERSION
    )


def canonicalize_document(
    value: dict[str, Any],
    *,
    node_registry: Any | None = None,
) -> dict[str, Any]:
    """Validate and normalize the canonical V2 envelope.

    Compatibility aliases belong at import boundaries.  This serializer only
    emits the documented snake_case V2 keys.
    """
    if not is_v2_document(value):
        raise WorkflowDocumentError(
            f"expected {DOCUMENT_FORMAT!r} version {DOCUMENT_VERSION}"
        )
    # Normalize CredentialRef instances and reject secret material before any
    # field-level projection can accidentally persist it.
    value = _contract_copy(value, path="document")
    resource = value.get("resource")
    graph = value.get("graph")
    interface = value.get("interface")
    exposure = value.get("exposure")
    canvas = value.get("canvas")
    if not isinstance(resource, dict) or not str(resource.get("name") or "").strip():
        raise WorkflowDocumentError("resource.name is required")
    if not isinstance(graph, dict):
        raise WorkflowDocumentError("graph must be an object")
    nodes = graph.get("nodes", [])
    links = graph.get("links", [])
    if not isinstance(nodes, list) or not isinstance(links, list):
        raise WorkflowDocumentError("graph.nodes and graph.links must be arrays")

    normalized_nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    port_index: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in nodes:
        if not isinstance(raw, dict):
            raise WorkflowDocumentError("every graph node must be an object")
        raw = _migrate_document_node(raw, node_registry)
        node_id = str(raw.get("id") or "").strip()
        if not node_id or node_id in node_ids:
            raise WorkflowDocumentError(f"missing or duplicate node id: {node_id!r}")
        node_ids.add(node_id)
        type_ref = raw.get("type")
        if not isinstance(type_ref, dict) or not str(type_ref.get("id") or "").strip():
            raise WorkflowDocumentError(f"node {node_id!r} requires type.id")
        try:
            type_version = parse_node_version(type_ref.get("version", 1))
        except NodeVersionError as exc:
            raise WorkflowDocumentError(f"node {node_id!r} has invalid type.version") from exc
        ports: list[dict[str, Any]] = []
        port_ids: set[str] = set()
        for port_raw in raw.get("ports", []):
            if not isinstance(port_raw, dict):
                raise WorkflowDocumentError(f"node {node_id!r} has an invalid port")
            port_id = str(port_raw.get("id") or "").strip()
            direction = str(port_raw.get("direction") or "")
            if not port_id or port_id in port_ids:
                raise WorkflowDocumentError(f"node {node_id!r} has a missing/duplicate port id")
            if direction not in {"in", "out"}:
                raise WorkflowDocumentError(f"port {node_id}.{port_id} has invalid direction")
            port_ids.add(port_id)
            port = {
                "id": port_id,
                "name": str(port_raw.get("name") or port_id),
                "direction": direction,
                "data_type": str(port_raw.get("data_type") or "any"),
                "description": str(port_raw.get("description") or ""),
                "required": bool(port_raw.get("required", False)),
                "lazy": bool(port_raw.get("lazy", False)),
            }
            if "default" in port_raw:
                port["default"] = _copy(port_raw["default"])
            ports.append(port)
            port_index[(node_id, port_id)] = port
        execution_raw = raw.get("execution") if isinstance(raw.get("execution"), dict) else {}
        normalized_nodes.append({
            "id": node_id,
            "type": {
                "id": str(type_ref.get("id")),
                "version": type_version,
            },
            "title": str(raw.get("title") or ""),
            "ports": ports,
            "params": _contract_copy(raw.get("params"), path=f"node {node_id}.params")
            if isinstance(raw.get("params"), dict) else {},
            "execution": {
                "enabled": bool(execution_raw.get("enabled", True)),
                "schema_only": bool(execution_raw.get("schema_only", False)),
                "cache": str(execution_raw.get("cache") or "auto"),
                "on_error": _contract_copy(execution_raw.get("on_error"), path=f"node {node_id}.execution.on_error")
                if isinstance(execution_raw.get("on_error"), dict) else {"strategy": "abort"},
                "permissions": [str(item) for item in execution_raw.get("permissions", [])]
                if isinstance(execution_raw.get("permissions"), list) else [],
            },
        })

    normalized_links: list[dict[str, Any]] = []
    link_ids: set[str] = set()
    routes: set[tuple[str, str, str, str]] = set()
    for raw in links:
        if not isinstance(raw, dict):
            raise WorkflowDocumentError("every graph link must be an object")
        link_id = str(raw.get("id") or "").strip()
        source = raw.get("source")
        target = raw.get("target")
        if not link_id or link_id in link_ids:
            raise WorkflowDocumentError(f"missing or duplicate link id: {link_id!r}")
        if not isinstance(source, dict) or not isinstance(target, dict):
            raise WorkflowDocumentError(f"link {link_id!r} endpoints must be objects")
        source_key = (str(source.get("node_id") or ""), str(source.get("port_id") or ""))
        target_key = (str(target.get("node_id") or ""), str(target.get("port_id") or ""))
        if source_key not in port_index or target_key not in port_index:
            raise WorkflowDocumentError(f"link {link_id!r} references an unknown endpoint")
        if port_index[source_key]["direction"] != "out" or port_index[target_key]["direction"] != "in":
            raise WorkflowDocumentError(f"link {link_id!r} must connect output to input")
        source_type = str(port_index[source_key]["data_type"] or "any")
        target_type = str(port_index[target_key]["data_type"] or "any")
        # Keep document validation aligned with the established runtime seam,
        # including its aliases and scalar-to-string coercion.
        from .runtime import _types_compatible

        if not _types_compatible(source_type, target_type):
            raise WorkflowDocumentError(
                f"link {link_id!r} has incompatible types: {source_type} -> {target_type}"
            )
        route = (*source_key, *target_key)
        if route in routes:
            raise WorkflowDocumentError(f"duplicate link route: {route}")
        routes.add(route)
        link_ids.add(link_id)
        item = {
            "id": link_id,
            "source": {"node_id": source_key[0], "port_id": source_key[1]},
            "target": {"node_id": target_key[0], "port_id": target_key[1]},
        }
        for expression_key in ("transform", "condition"):
            expression = raw.get(expression_key)
            if expression in (None, ""):
                continue
            if isinstance(expression, dict):
                try:
                    item[expression_key] = validate_expression(expression)
                except ExpressionError as exc:
                    raise WorkflowDocumentError(
                        f"link {link_id!r} has invalid {expression_key}: {exc}"
                    ) from exc
            elif isinstance(expression, str):
                item[expression_key] = expression
            else:
                raise WorkflowDocumentError(
                    f"link {link_id!r} {expression_key} must be a string or expression AST"
                )
        normalized_links.append(item)

    result = {
        "format": DOCUMENT_FORMAT,
        "version": DOCUMENT_VERSION,
        "resource": {
            "id": str(resource.get("id") or uuid.uuid4().hex),
            "name": str(resource.get("name")).strip(),
            "description": str(resource.get("description") or ""),
            "work_root": str(resource.get("work_root") or ""),
            "revision": max(0, int(resource.get("revision") or 0)),
            "created_at": str(resource.get("created_at") or _now()),
            "updated_at": str(resource.get("updated_at") or _now()),
        },
        "graph": {"nodes": normalized_nodes, "links": normalized_links},
        "interface": _normalize_interface(interface, port_index),
        "exposure": {
            "enabled": bool(exposure.get("enabled", False)) if isinstance(exposure, dict) else False,
            "tool_name": str(exposure.get("tool_name") or "") if isinstance(exposure, dict) else "",
        },
        "canvas": _normalize_canvas(canvas, node_ids),
        "triggers": _normalize_triggers(value.get("triggers")),
        "policies": _normalize_policies(value.get("policies")),
    }
    _topological_order(result)  # deterministic cycle validation
    return result


def _normalize_interface(
    value: object, port_index: dict[tuple[str, str], dict[str, Any]]
) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    inputs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value.get("inputs", []):
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("id") or "").strip()
        if not item_id or item_id in seen:
            raise WorkflowDocumentError("workflow interface input ids must be unique")
        seen.add(item_id)
        item = {
            "id": item_id,
            "name": str(raw.get("name") or item_id),
            "data_type": str(raw.get("data_type") or "any"),
            "description": str(raw.get("description") or ""),
            "required": bool(raw.get("required", True)),
        }
        if "default" in raw:
            item["default"] = _copy(raw["default"])
        target = raw.get("target")
        if isinstance(target, dict):
            key = (str(target.get("node_id") or ""), str(target.get("port_id") or ""))
            if key not in port_index or port_index[key]["direction"] != "in":
                raise WorkflowDocumentError(f"interface input {item_id!r} has invalid target")
            item["target"] = {"node_id": key[0], "port_id": key[1]}
        inputs.append(item)
    outputs: list[dict[str, Any]] = []
    seen.clear()
    for raw in value.get("outputs", []):
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("id") or "").strip()
        source = raw.get("source")
        if not item_id or item_id in seen or not isinstance(source, dict):
            raise WorkflowDocumentError("workflow interface output id/source is invalid")
        key = (str(source.get("node_id") or ""), str(source.get("port_id") or ""))
        if key not in port_index or port_index[key]["direction"] != "out":
            raise WorkflowDocumentError(f"interface output {item_id!r} has invalid source")
        seen.add(item_id)
        outputs.append({
            "id": item_id,
            "name": str(raw.get("name") or item_id),
            "data_type": str(raw.get("data_type") or port_index[key]["data_type"]),
            "description": str(raw.get("description") or ""),
            "source": {"node_id": key[0], "port_id": key[1]},
        })
    return {"inputs": inputs, "outputs": outputs}


def _normalize_canvas(value: object, node_ids: set[str]) -> dict[str, Any]:
    value = value if isinstance(value, dict) else {}
    raw_views = value.get("node_views") if isinstance(value.get("node_views"), dict) else {}
    node_views = {
        str(node_id): _normalize_node_view(view)
        for node_id, view in raw_views.items()
        if str(node_id) in node_ids and isinstance(view, dict)
    }
    viewport = value.get("viewport") if isinstance(value.get("viewport"), dict) else {}
    normalized = {
        "viewport": {
            "x": float(viewport.get("x") or 0),
            "y": float(viewport.get("y") or 0),
            "zoom": float(viewport.get("zoom") or 1),
        },
        "node_views": node_views,
        "groups": _copy(value.get("groups")) if isinstance(value.get("groups"), list) else [],
        "reroutes": _copy(value.get("reroutes")) if isinstance(value.get("reroutes"), list) else [],
        "annotations": _copy(value.get("annotations")) if isinstance(value.get("annotations"), list) else [],
    }
    # Foreign editor metadata belongs to canvas state, never to execution.
    if isinstance(value.get("comfyui"), dict):
        normalized["comfyui"] = _copy(value["comfyui"])
    return normalized


def _parent_id_from_view(value: object) -> str | None:
    """Read the canonical/legacy canvas parent key as one optional string."""
    if not isinstance(value, dict):
        return None
    # Presence of the canonical key is authoritative, including an explicit
    # null/empty value used to clear a relationship.  Only legacy views with
    # no snake_case key consult ``parentId``.
    raw = value["parent_id"] if "parent_id" in value else value.get("parentId")
    if raw is None:
        return None
    parent_id = str(raw).strip()
    return parent_id or None


def _normalize_node_view(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize node view aliases without moving parent data into the graph."""
    view = _copy(value)
    parent_id = _parent_id_from_view(view)
    # V2 has one canonical spelling.  Explicitly remove both empty and legacy
    # values so a cleared parent cannot reappear through a stale alias.
    view.pop("parentId", None)
    if parent_id is None:
        view.pop("parent_id", None)
    else:
        view["parent_id"] = parent_id
    return view


def document_from_workflow_def(definition: Any) -> dict[str, Any]:
    """Losslessly migrate the runtime/legacy definition into V2 in memory."""
    existing = getattr(definition, "document", None)
    existing_triggers: object = []
    existing_policies: object = {}
    if is_v2_document(existing):
        doc = _copy(existing)
        # Runtime mutations remain authoritative for execution/meta while
        # canvas-only data survives unchanged.
        canvas = _copy(doc.get("canvas"))
        existing_triggers = _copy(doc.get("triggers", []))
        existing_policies = _copy(doc.get("policies", {}))
    else:
        canvas = {"viewport": {"x": 0, "y": 0, "zoom": 1}, "node_views": {}, "groups": [], "reroutes": [], "annotations": []}
    nodes: list[dict[str, Any]] = []
    port_ids: dict[tuple[str, str, str], str] = {}
    for node in definition.nodes:
        ports: list[dict[str, Any]] = []
        for port in node.ports:
            port_id = str(getattr(port, "id", "") or _stable_id("port", definition.id, node.id, port.direction, port.name))
            port_ids[(node.id, port.direction, port.name)] = port_id
            item = {
                "id": port_id,
                "name": port.name,
                "direction": port.direction,
                "data_type": port.type,
                "description": port.description,
                "required": False,
                "lazy": bool(port.lazy),
            }
            if port.value is not None:
                item["default"] = _copy(port.value)
            ports.append(item)
        config = _copy(node.config)
        execution = config.pop("execution", {}) if isinstance(config.get("execution"), dict) else {}
        legacy_on_error = config.pop("on_error", None)
        if isinstance(legacy_on_error, dict):
            execution = {**execution, "on_error": legacy_on_error}
        nodes.append({
            "id": node.id,
            "type": {"id": str(getattr(node, "type_id", "") or node.kind), "version": max(1, int(getattr(node, "type_version", 1) or 1))},
            "title": node.title,
            "ports": ports,
            "params": config,
            "execution": {
                "enabled": bool(execution.get("enabled", True)),
                "schema_only": bool(execution.get("schema_only", False)),
                "cache": str(execution.get("cache") or "auto"),
                "on_error": _copy(execution.get("on_error")) if isinstance(execution.get("on_error"), dict) else {"strategy": "abort"},
                "permissions": list(execution.get("permissions") or []),
            },
        })
        node_view = {
            **_copy(canvas.get("node_views", {}).get(node.id, {})),
            "position": _copy(node.position),
        }
        parent_id = getattr(node, "parent_id", None)
        if parent_id is None or not str(parent_id).strip():
            # A definition projection is authoritative for the editable
            # parent relationship.  Do not let an older document view revive
            # a parent that the caller cleared.
            node_view.pop("parent_id", None)
            node_view.pop("parentId", None)
        else:
            node_view["parent_id"] = str(parent_id).strip()
            node_view.pop("parentId", None)
        canvas.setdefault("node_views", {})[node.id] = node_view
    links = []
    for edge in definition.edges:
        source_id = str(getattr(edge, "source_port_id", "") or port_ids.get((edge.source, "out", edge.source_port), ""))
        target_id = str(getattr(edge, "target_port_id", "") or port_ids.get((edge.target, "in", edge.target_port), ""))
        links.append({
            "id": edge.id,
            "source": {"node_id": edge.source, "port_id": source_id},
            "target": {"node_id": edge.target, "port_id": target_id},
            **({"transform": edge.transform} if edge.transform else {}),
            **({"condition": edge.condition} if edge.condition else {}),
        })
    interface_inputs = []
    for param in definition.input_params:
        item = {
            "id": _stable_id("input", definition.id, param.name),
            "name": param.name,
            "data_type": param.type,
            "description": param.description,
            "required": param.required,
        }
        if param.default is not None:
            item["default"] = _copy(param.default)
        input_node, separator, input_port = param.name.rpartition(".")
        target_port_id = port_ids.get((input_node, "in", input_port)) if separator else None
        if target_port_id:
            item["target"] = {"node_id": input_node, "port_id": target_port_id}
        interface_inputs.append(item)
    interface_outputs = []
    if definition.output_port:
        node_id, _, port_name = definition.output_port.partition(".")
        node = next((item for item in definition.nodes if item.id == node_id), None)
        if node is not None:
            if not port_name:
                output = next(iter(node.output_ports()), None)
                port_name = output.name if output else ""
            port_id = port_ids.get((node_id, "out", port_name))
            if port_id:
                interface_outputs.append({
                    "id": _stable_id("output", definition.id, node_id, port_id),
                    "name": port_name or "result",
                    "data_type": next((p.type for p in node.output_ports() if p.name == port_name), "any"),
                    "description": "",
                    "source": {"node_id": node_id, "port_id": port_id},
                })
    return canonicalize_document({
        "format": DOCUMENT_FORMAT,
        "version": DOCUMENT_VERSION,
        "resource": {
            "id": definition.id,
            "name": definition.name,
            "description": definition.description,
            "work_root": definition.work_root,
            "revision": definition.revision,
            "created_at": definition.created_at.isoformat(),
            "updated_at": definition.updated_at.isoformat(),
        },
        "graph": {"nodes": nodes, "links": links},
        "interface": {"inputs": interface_inputs, "outputs": interface_outputs},
        "exposure": {"enabled": definition.exposed, "tool_name": definition.tool_name},
        "canvas": canvas,
        "triggers": existing_triggers,
        "policies": existing_policies,
    })


def workflow_def_from_document(
    value: dict[str, Any],
    *,
    node_registry: Any | None = None,
) -> Any:
    """Compile document structure to the existing runtime definition seam."""
    from .runtime import WorkflowDef

    doc = canonicalize_document(value, node_registry=node_registry)
    resource = doc["resource"]
    port_names: dict[tuple[str, str], str] = {}
    legacy_nodes: list[dict[str, Any]] = []
    for node in doc["graph"]["nodes"]:
        legacy_ports = []
        for port in node["ports"]:
            port_names[(node["id"], port["id"])] = port["name"]
            legacy_port = {
                "id": port["id"], "name": port["name"], "type": port["data_type"],
                "direction": port["direction"], "description": port["description"], "lazy": port["lazy"],
            }
            if "default" in port:
                legacy_port["value"] = _copy(port["default"])
            legacy_ports.append(legacy_port)
        execution = node["execution"]
        config = _copy(node["params"])
        config["execution"] = _copy(execution)
        config["on_error"] = _copy(execution["on_error"])
        view = doc["canvas"]["node_views"].get(node["id"], {})
        legacy_node = {
            "id": node["id"], "kind": node["type"]["id"], "type_id": node["type"]["id"],
            "type_version": node["type"]["version"], "title": node["title"], "config": config,
            "ports": legacy_ports, "position": _copy(view.get("position") or {}),
        }
        parent_id = _parent_id_from_view(view)
        if parent_id is not None:
            legacy_node["parent_id"] = parent_id
        legacy_nodes.append(legacy_node)
    edges = []
    for link in doc["graph"]["links"]:
        source = link["source"]
        target = link["target"]
        edges.append({
            "id": link["id"], "source": source["node_id"],
            "source_port": port_names[(source["node_id"], source["port_id"])],
            "source_port_id": source["port_id"], "target": target["node_id"],
            "target_port": port_names[(target["node_id"], target["port_id"])],
            "target_port_id": target["port_id"], "transform": link.get("transform", ""),
            "condition": link.get("condition", ""),
        })
    inputs = [{
        "name": item["name"], "type": item["data_type"], "description": item["description"],
        "required": item["required"], "default": item.get("default"),
    } for item in doc["interface"]["inputs"]]
    output = doc["interface"]["outputs"][:1]
    output_port = ""
    if output:
        source = output[0]["source"]
        output_port = f"{source['node_id']}.{port_names[(source['node_id'], source['port_id'])]}"
    definition = WorkflowDef.from_dict({
        "id": resource["id"], "name": resource["name"], "description": resource["description"],
        "work_root": resource["work_root"], "revision": resource["revision"],
        "created_at": resource["created_at"], "updated_at": resource["updated_at"],
        "nodes": legacy_nodes, "edges": edges, "input_params": inputs, "output_port": output_port,
        "exposed": doc["exposure"]["enabled"], "tool_name": doc["exposure"]["tool_name"],
    })
    definition.document = doc
    return definition


def workflow_flow_control_policy(value: Any) -> FlowControlPolicy:
    """Return the validated scheduling policy without invoking the runner.

    ``value`` may be a canonical document, a ``policies`` object, or a
    ``WorkflowDef`` carrying its canonical document.  This explicit adapter is
    the intended seam for a future runtime integration; merely loading a
    document never starts or reserves any flow-control lease.
    """

    document = getattr(value, "document", None) if not isinstance(value, dict) else value
    return flow_control_from_document(document if isinstance(document, dict) else value)


def compile_document(
    value: dict[str, Any],
    *,
    node_registry: Any | None = None,
) -> dict[str, Any]:
    """Compile a V2 editor document into a deterministic canvas-free prompt."""
    doc = canonicalize_document(value, node_registry=node_registry)
    order = _topological_order(doc)
    incoming: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for link in doc["graph"]["links"]:
        target = link["target"]
        incoming.setdefault((target["node_id"], target["port_id"]), []).append(link)
    prompt_nodes: dict[str, Any] = {}
    for node in doc["graph"]["nodes"]:
        execution = node["execution"]
        if not execution["enabled"]:
            raise WorkflowDocumentError(f"node {node['id']!r} is disabled and cannot be compiled")
        if execution["schema_only"]:
            raise WorkflowDocumentError(f"node {node['id']!r} ({node['type']['id']}) is schema-only and cannot execute")
        inputs: dict[str, Any] = {}
        for port in node["ports"]:
            if port["direction"] != "in":
                continue
            links = sorted(incoming.get((node["id"], port["id"]), []), key=lambda item: item["id"])
            if links:
                sources = [{
                    "node_id": item["source"]["node_id"], "port_id": item["source"]["port_id"],
                    **({"transform": item["transform"]} if item.get("transform") else {}),
                    **({"condition": item["condition"]} if item.get("condition") else {}),
                } for item in links]
                inputs[port["id"]] = {"links": sources}
            elif "default" in port:
                inputs[port["id"]] = {"literal": _copy(port["default"])}
            elif port["required"]:
                raise WorkflowDocumentError(f"required input is unbound: {node['id']}.{port['id']}")
        prompt_nodes[node["id"]] = {
            "type_id": node["type"]["id"], "type_version": node["type"]["version"],
            "params": _copy(node["params"]), "inputs": inputs,
            "outputs": [port["id"] for port in node["ports"] if port["direction"] == "out"],
            "execution": _copy(execution),
        }
    return {
        "format": PROMPT_FORMAT, "version": PROMPT_VERSION,
        "workflow": {"id": doc["resource"]["id"], "revision": doc["resource"]["revision"]},
        "nodes": prompt_nodes, "order": order, "interface": _copy(doc["interface"]),
        # Policies are execution defaults consumed by a separate engine.  They
        # do not cause scheduling here and remain absent only from the legacy
        # runtime execution node payload.
        "policies": _copy(doc["policies"]),
    }


def semantic_graph(
    value: dict[str, Any], *, node_ids: Iterable[str] | None = None,
    offset: int = 0, limit: int = 100,
) -> dict[str, Any]:
    """Return a compact, optionally focused model-facing topology."""
    doc = canonicalize_document(value)
    all_nodes = doc["graph"]["nodes"]
    selected = {str(item) for item in node_ids or []}
    focused = bool(selected)
    if focused:
        # One-hop context makes focused reads useful without returning the graph.
        existing_ids = {node["id"] for node in all_nodes}
        focus = selected & existing_ids
        selected = set(focus)
        for link in doc["graph"]["links"]:
            # Compare against the immutable explicit focus.  Mutating the set
            # being tested here turns link ordering into accidental multi-hop
            # expansion.
            if link["source"]["node_id"] in focus or link["target"]["node_id"] in focus:
                selected.add(link["source"]["node_id"])
                selected.add(link["target"]["node_id"])
        all_nodes = [node for node in all_nodes if node["id"] in selected]
    total = len(all_nodes)
    start = max(0, int(offset))
    page = all_nodes[start:start + max(1, min(int(limit), 500))]
    visible = {node["id"] for node in page}
    node_summaries = [{
        "id": node["id"], "type_id": node["type"]["id"], "title": node["title"],
        "inputs": [{"id": p["id"], "name": p["name"], "type": p["data_type"]} for p in node["ports"] if p["direction"] == "in"],
        "outputs": [{"id": p["id"], "name": p["name"], "type": p["data_type"]} for p in node["ports"] if p["direction"] == "out"],
        "executable": bool(node["execution"]["enabled"] and not node["execution"]["schema_only"]),
    } for node in page]
    adjacency = [{
        "link_id": link["id"], "from": [link["source"]["node_id"], link["source"]["port_id"]],
        "to": [link["target"]["node_id"], link["target"]["port_id"]],
    } for link in doc["graph"]["links"] if link["source"]["node_id"] in visible and link["target"]["node_id"] in visible]
    interface = _copy(doc["interface"])
    if focused:
        interface["inputs"] = [
            item for item in interface["inputs"]
            if not isinstance(item.get("target"), dict) or item["target"].get("node_id") in visible
        ]
        interface["outputs"] = [
            item for item in interface["outputs"]
            if not isinstance(item.get("source"), dict) or item["source"].get("node_id") in visible
        ]
    visible_order = [node_id for node_id in _topological_order(doc) if node_id in visible]
    return {
        "format": SEMANTIC_FORMAT, "version": SEMANTIC_VERSION,
        "workflow": {k: doc["resource"][k] for k in ("id", "name", "description", "revision")},
        "interface": interface, "nodes": node_summaries,
        "adjacency": adjacency, "topological_order": visible_order,
        "page": {"offset": start, "limit": max(1, min(int(limit), 500)), "total": total, "has_more": start + len(page) < total},
    }


def _topological_order(doc: dict[str, Any]) -> list[str]:
    nodes = [node["id"] for node in doc["graph"]["nodes"]]
    indegree = {node_id: 0 for node_id in nodes}
    downstream: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for link in doc["graph"]["links"]:
        source = link["source"]["node_id"]
        target = link["target"]["node_id"]
        indegree[target] += 1
        downstream[source].append(target)
    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for target in sorted(downstream[node_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    if len(order) != len(nodes):
        raise WorkflowDocumentError("workflow graph contains a cycle")
    return order


def import_comfyui(value: dict[str, Any], *, name: str = "") -> dict[str, Any]:
    """Import ComfyUI editor workflow v0.4/v1 concepts into V2.

    Unknown class types are retained as schema-only nodes.  They are visible
    and round-trippable but never misrepresented as executable Sunday nodes.
    """
    raw_nodes = value.get("nodes")
    if not isinstance(raw_nodes, list):
        raise WorkflowDocumentError("ComfyUI workflow requires nodes[]")
    wf_id = str(value.get("id") or uuid.uuid4().hex)
    nodes: list[dict[str, Any]] = []
    views: dict[str, Any] = {}
    slot_ports: dict[tuple[str, str, int], str] = {}
    # Types shipped by the host are executable after import.  Foreign ComfyUI
    # classes remain schema-only and round-trip through canvas.comfyui.raw.
    from .registry import WorkflowNodeRegistry

    known = {item.type_id for item in WorkflowNodeRegistry().list()}
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue
        node_id = str(raw.get("id"))
        class_type = str(raw.get("type") or raw.get("class_type") or "unknown")
        mapped = str((raw.get("properties") or {}).get("lamtools_type_id") or class_type)
        port_items: list[dict[str, Any]] = []
        for direction, key in (("in", "inputs"), ("out", "outputs")):
            slots = raw.get(key) if isinstance(raw.get(key), list) else []
            for index, slot in enumerate(slots):
                slot = slot if isinstance(slot, dict) else {}
                port_id = _stable_id("port", wf_id, node_id, direction, index)
                slot_ports[(node_id, direction, index)] = port_id
                port_items.append({
                    "id": port_id, "name": str(slot.get("name") or f"{direction}{index}"),
                    "direction": direction, "data_type": str(slot.get("type") or "any").lower(),
                    "description": "", "required": False, "lazy": False,
                })
        nodes.append({
            "id": node_id, "type": {"id": mapped, "version": 1},
            "title": str(raw.get("title") or class_type), "ports": port_items,
            # ComfyUI widget/editor state is not an execution parameter.  Keep
            # the complete foreign node under canvas.comfyui.raw so compiling
            # an imported document cannot accidentally pass adapter metadata
            # to a Sunday executor.
            "params": {},
            "execution": {"enabled": True, "schema_only": mapped not in known, "cache": "auto", "on_error": {"strategy": "abort"}, "permissions": []},
        })
        pos = raw.get("pos") if isinstance(raw.get("pos"), (list, tuple)) else [0, 0]
        size = raw.get("size") if isinstance(raw.get("size"), (list, tuple)) else []
        views[node_id] = {
            "position": {"x": float(pos[0] if len(pos) > 0 else 0), "y": float(pos[1] if len(pos) > 1 else 0)},
            **({"size": {"width": float(size[0]), "height": float(size[1])}} if len(size) >= 2 else {}),
            # Preserve the complete editor node payload under canvas-only
            # state.  Export overlays canonical graph fields onto this raw
            # value, retaining third-party widget/shape/property extensions.
            "comfyui": {
                "order": raw.get("order"), "mode": raw.get("mode"),
                "flags": _copy(raw.get("flags") or {}), "raw": _copy(raw),
            },
        }
    links: list[dict[str, Any]] = []
    raw_link_metadata: dict[str, dict[str, Any]] = {}
    raw_links = value.get("links") if isinstance(value.get("links"), list) else []
    for index, raw in enumerate(raw_links):
        if isinstance(raw, (list, tuple)) and len(raw) >= 5:
            link_id, source_node, source_slot, target_node, target_slot = raw[:5]
        elif isinstance(raw, dict):
            link_id = raw.get("id", index)
            source_node = raw.get("origin_id", raw.get("source_id"))
            source_slot = raw.get("origin_slot", raw.get("source_slot", 0))
            target_node = raw.get("target_id")
            target_slot = raw.get("target_slot", 0)
        else:
            continue
        source_key = (str(source_node), "out", int(source_slot))
        target_key = (str(target_node), "in", int(target_slot))
        if source_key not in slot_ports or target_key not in slot_ports:
            raise WorkflowDocumentError(f"ComfyUI link {link_id!r} references an unknown slot")
        links.append({
            "id": str(link_id),
            "source": {"node_id": source_key[0], "port_id": slot_ports[source_key]},
            "target": {"node_id": target_key[0], "port_id": slot_ports[target_key]},
        })
        if isinstance(raw, dict):
            raw_link_metadata[str(link_id)] = _copy(raw)
    extra = value.get("extra") if isinstance(value.get("extra"), dict) else {}
    viewport = extra.get("ds") if isinstance(extra.get("ds"), dict) else {}
    lamtools_meta = extra.get("lamtools") if isinstance(extra.get("lamtools"), dict) else {}
    is_legacy = str(value.get("version") or "").startswith("0.")
    reroutes = extra.get("reroutes", []) if is_legacy else value.get("reroutes", [])
    return canonicalize_document({
        "format": DOCUMENT_FORMAT, "version": DOCUMENT_VERSION,
        "resource": {"id": wf_id, "name": name or str(value.get("name") or "Imported ComfyUI workflow"), "description": "", "work_root": "", "revision": 0, "created_at": _now(), "updated_at": _now()},
        "graph": {"nodes": nodes, "links": links}, "interface": {"inputs": [], "outputs": []},
        "exposure": {"enabled": False, "tool_name": ""},
        # ComfyUI has no trigger/policy vocabulary.  A LamTools export keeps
        # the optional V2 declarations under an explicit extension envelope so
        # a ComfyUI round trip does not silently discard them.
        "triggers": _copy(lamtools_meta.get("triggers", [])),
        "policies": _copy(lamtools_meta.get("policies", {})),
        "canvas": {
            "viewport": {"x": viewport.get("offset", [0, 0])[0] if isinstance(viewport.get("offset"), list) else 0, "y": viewport.get("offset", [0, 0])[1] if isinstance(viewport.get("offset"), list) else 0, "zoom": viewport.get("scale", 1)},
            "node_views": views, "groups": _copy(value.get("groups") or []),
            "reroutes": _copy(reroutes) if isinstance(reroutes, list) else [], "annotations": [],
            "comfyui": {"links": raw_link_metadata},
        },
    })


def export_comfyui(value: dict[str, Any], *, version: str = "1") -> dict[str, Any]:
    """Export a V2 editor document using ComfyUI's public workflow shape."""
    doc = canonicalize_document(value)
    is_v1 = str(version).startswith("1")
    used_link_ids: set[int] = set()
    link_number: dict[str, int] = {}
    next_link_id = 1
    for link in doc["graph"]["links"]:
        candidate = _numeric_id(link["id"])
        if candidate is None or candidate in used_link_ids:
            while next_link_id in used_link_ids:
                next_link_id += 1
            candidate = next_link_id
        used_link_ids.add(candidate)
        next_link_id = max(next_link_id, candidate + 1)
        link_number[link["id"]] = candidate
    links_by_port: dict[tuple[str, str], list[int]] = {}
    node_ports: dict[tuple[str, str], tuple[str, int]] = {}
    port_types: dict[tuple[str, str], str] = {}
    external_node_ids: dict[str, Any] = {}
    for node in doc["graph"]["nodes"]:
        view = doc["canvas"]["node_views"].get(node["id"], {})
        comfy = view.get("comfyui") if isinstance(view.get("comfyui"), dict) else {}
        raw = comfy.get("raw") if isinstance(comfy.get("raw"), dict) else {}
        raw_id = raw.get("id")
        external_node_ids[node["id"]] = raw_id if str(raw_id) == node["id"] else node["id"]
        for direction in ("in", "out"):
            for index, port in enumerate(p for p in node["ports"] if p["direction"] == direction):
                node_ports[(node["id"], port["id"])] = (direction, index)
                port_types[(node["id"], port["id"])] = str(port["data_type"] or "*").upper()
    link_rows: list[Any] = []
    canvas_comfy = doc["canvas"].get("comfyui") if isinstance(doc["canvas"].get("comfyui"), dict) else {}
    raw_link_metadata = canvas_comfy.get("links") if isinstance(canvas_comfy.get("links"), dict) else {}
    for link in doc["graph"]["links"]:
        source = link["source"]; target = link["target"]
        source_slot = node_ports[(source["node_id"], source["port_id"])][1]
        target_slot = node_ports[(target["node_id"], target["port_id"])][1]
        numeric = link_number[link["id"]]
        source_id = external_node_ids[source["node_id"]]
        target_id = external_node_ids[target["node_id"]]
        link_type = port_types.get((source["node_id"], source["port_id"]), "*")
        if is_v1:
            raw_link = _copy(raw_link_metadata.get(link["id"])) if isinstance(raw_link_metadata.get(link["id"]), dict) else {}
            raw_link.update({
                "id": numeric, "origin_id": source_id, "origin_slot": source_slot,
                "target_id": target_id, "target_slot": target_slot, "type": link_type,
            })
            link_rows.append(raw_link)
        else:
            link_rows.append([numeric, source_id, source_slot, target_id, target_slot, link_type])
        links_by_port.setdefault((source["node_id"], source["port_id"]), []).append(numeric)
        links_by_port.setdefault((target["node_id"], target["port_id"]), []).append(numeric)
    nodes = []
    for order, node in enumerate(doc["graph"]["nodes"]):
        view = doc["canvas"]["node_views"].get(node["id"], {})
        position = view.get("position") if isinstance(view.get("position"), dict) else {}
        size = view.get("size") if isinstance(view.get("size"), dict) else {}
        # Read the former params.comfyui location only as an export-time
        # compatibility fallback for documents produced by early V2 builds.
        # New imports retain all ComfyUI-only data in canvas state.
        comfy_params = node["params"].get("comfyui") if isinstance(node["params"].get("comfyui"), dict) else {}
        comfy_view = view.get("comfyui") if isinstance(view.get("comfyui"), dict) else {}
        raw_node = _copy(comfy_view.get("raw")) if isinstance(comfy_view.get("raw"), dict) else {}
        raw_inputs = raw_node.get("inputs") if isinstance(raw_node.get("inputs"), list) else []
        raw_outputs = raw_node.get("outputs") if isinstance(raw_node.get("outputs"), list) else []
        inputs = []
        outputs = []
        for port in node["ports"]:
            linked = links_by_port.get((node["id"], port["id"]), [])
            if port["direction"] == "in":
                raw_slot = raw_inputs[len(inputs)] if len(inputs) < len(raw_inputs) else {}
                slot = _copy(raw_slot) if isinstance(raw_slot, dict) else {}
                slot.update({
                    "name": port["name"], "type": port["data_type"].upper(),
                    "link": linked[0] if linked else None,
                })
                inputs.append(slot)
            else:
                raw_slot = raw_outputs[len(outputs)] if len(outputs) < len(raw_outputs) else {}
                slot = _copy(raw_slot) if isinstance(raw_slot, dict) else {}
                slot.update({
                    "name": port["name"], "type": port["data_type"].upper(),
                    "links": linked or None,
                })
                outputs.append(slot)
        raw_properties = raw_node.get("properties") if isinstance(raw_node.get("properties"), dict) else {}
        properties = {
            **_copy(raw_properties),
            "lamtools_type_id": node["type"]["id"],
            "lamtools_type_version": node["type"]["version"],
        }
        raw_node.update({
            "id": external_node_ids[node["id"]],
            "type": str(raw_node.get("type") or comfy_params.get("class_type") or node["type"]["id"]),
            "pos": [float(position.get("x") or 0), float(position.get("y") or 0)],
            "size": [float(size.get("width") or 240), float(size.get("height") or 120)],
            "flags": _copy(comfy_view.get("flags", {})),
            "order": order, "mode": int(comfy_view.get("mode") or 0),
            "inputs": inputs, "outputs": outputs, "title": node["title"],
            "properties": properties,
            "widgets_values": _copy(
                raw_node["widgets_values"]
                if "widgets_values" in raw_node
                else comfy_params.get("widgets_values") or []
            ),
        })
        nodes.append(raw_node)
    viewport = doc["canvas"]["viewport"]
    max_node_id = max((_numeric_id(node["id"]) or 0 for node in nodes), default=0)
    max_link_id = max(used_link_ids, default=0)
    max_group_id = max((_numeric_id(group.get("id")) or 0 for group in doc["canvas"]["groups"] if isinstance(group, dict)), default=0)
    max_reroute_id = max((_numeric_id(reroute.get("id")) or 0 for reroute in doc["canvas"]["reroutes"] if isinstance(reroute, dict)), default=0)
    extra = {"ds": {"scale": viewport["zoom"], "offset": [viewport["x"], viewport["y"]]}}
    if doc["triggers"] or doc["policies"]:
        extra["lamtools"] = {
            "triggers": _copy(doc["triggers"]),
            "policies": _copy(doc["policies"]),
        }
    if not is_v1:
        extra["reroutes"] = _copy(doc["canvas"]["reroutes"])
        return {
            "version": 0.4, "last_node_id": max_node_id, "last_link_id": max_link_id,
            "nodes": nodes, "links": link_rows, "groups": _copy(doc["canvas"]["groups"]),
            "extra": extra,
        }
    return {
        "version": 1,
        "state": {
            "lastGroupId": max_group_id,
            "lastNodeId": max_node_id,
            "lastLinkId": max_link_id,
            "lastRerouteId": max_reroute_id,
        },
        "nodes": nodes, "links": link_rows,
        "groups": _copy(doc["canvas"]["groups"]),
        "reroutes": _copy(doc["canvas"]["reroutes"]),
        "extra": extra,
    }


def _numeric_id(value: Any) -> int | None:
    """Return a non-negative integer id without accepting lossy strings."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    return None


__all__ = [
    "DOCUMENT_FORMAT", "DOCUMENT_VERSION", "PROMPT_FORMAT", "PROMPT_VERSION",
    "SEMANTIC_FORMAT", "SEMANTIC_VERSION", "TRIGGER_TYPES", "WorkflowDocumentError",
    "FlowControlPolicy", "canonicalize_flow_control", "canonicalize_flow_control_policy",
    "flow_control_from_document",
    "canonicalize_document", "compile_document", "document_from_workflow_def",
    "export_comfyui", "import_comfyui", "is_v2_document", "semantic_graph",
    "workflow_def_from_document", "workflow_flow_control_policy",
]
