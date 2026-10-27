"""Workflow graph and input validation before execution."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

from typing import Any
from .models import WorkflowDef, WorkflowNode


_WORKFLOW_TYPES = {"string", "number", "boolean", "object", "array", "any"}


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
    from .runner_authority import _BUILTIN_EXECUTORS
    from .runner_context import WorkflowValidationError
    from .runner_process import _types_compatible
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
    from .runner_context import WorkflowValidationError
    for param in workflow.input_params:
        if not param.required or param.default is not None:
            continue
        if param.name in inputs or f"__input__.{param.name}" in prior_values:
            continue
        raise WorkflowValidationError(
            f"required workflow input is missing: {param.name}"
        )
