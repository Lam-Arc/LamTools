"""Graph traversal, edge binding and workflow input/output mapping."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import re
from collections.abc import Callable
from dataclasses import field
from typing import Any
from .models import WorkflowDef, WorkflowEdge, WorkflowNode, WorkflowPort
from .runner_context import LazyInput, WorkflowExecutionContext


SKIP_SENTINEL = "__workflow_skip__"


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
    from .runner_expressions import _eval_condition, _source_node
    from .runner_process import _coerce_value
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
    from .runner_expressions import _evaluate_workflow_expression, _is_structured_expression
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
