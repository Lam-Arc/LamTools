"""Dynamic expansion, nested workflow execution and input mapping."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
from collections.abc import Mapping
from typing import Any
from .executors import WorkflowExecutorError, WorkflowExpansion, WorkflowExpansionError
from .models import WorkflowDef, WorkflowEdge, WorkflowNode, _as_int, ensure_workflow_id
from .runner_context import WorkflowExecutionContext


async def _execute_expansion(
    runner,
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
    from .runner_context import WorkflowValidationError
    from .runner_graph import _default_output_port
    from .runner_validation import validate_workflow
    from .runner_values import _assert_json_value, _assert_json_workflow_data
    try:
        _assert_json_value(expansion.to_dict())
    except (TypeError, ValueError) as exc:
        raise WorkflowExpansionError(
            "workflow expansion must contain JSON-compatible data only"
        ) from exc
    sub_def = runner._expansion_definition(node, expansion)
    if len(sub_def.nodes) > runner.max_expansion_nodes:
        raise WorkflowExpansionError(
            f"workflow expansion exceeds node limit ({runner.max_expansion_nodes})"
        )
    if len(sub_def.edges) > runner.max_expansion_edges:
        raise WorkflowExpansionError(
            f"workflow expansion exceeds edge limit ({runner.max_expansion_edges})"
        )
    _assert_json_workflow_data(sub_def)
    try:
        validate_workflow(sub_def, node_registry=runner.node_registry)
        runner._validate_executable_nodes(sub_def)
    except (WorkflowValidationError, WorkflowExecutorError) as exc:
        raise WorkflowExpansionError(str(exc)) from exc
    inputs = dict(expansion.inputs or {})
    if not inputs:
        inputs = runner._map_entry_inputs(sub_def, bound_inputs)
    active_parent = runner._active_runs.get((thread_id, run_id))
    parent_workflow_id = str(
        active_parent.workflow.id or active_parent.workflow.name
        if active_parent is not None
        else ""
    )
    child_context = runner._child_context(
        execution_context,
        session_id=thread_id,
        run_id=run_id,
        call_id=node.id,
        child_workflow_id=str(sub_def.id or sub_def.name),
        parent_workflow_id=parent_workflow_id,
    )
    result = await runner.run(
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
    runner,
    node: WorkflowNode,
    expansion: WorkflowExpansion,
) -> WorkflowDef:
    """Convert a ``WorkflowExpansion`` wire object to a WorkflowDef."""
    from .runner_values import _coerce_expansion_input_param
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


async def _execute_subgraph(
    runner,
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
    from .runner_expressions import _eval_condition
    from .runner_graph import SKIP_SENTINEL, _default_output_port
    cfg = node.config
    target_name = str(cfg.get("workflow_name") or "")
    if not target_name:
        raise ValueError("subgraph node requires config.workflow_name")
    if runner.workflow_store is None:
        raise RuntimeError("subgraph node requires a workflow_store (none configured)")
    sub_def = await runner.workflow_store.get(target_name, work_root=work_root or None)
    if sub_def is None:
        raise ValueError(f"subgraph target workflow '{target_name}' not found")

    iterate = str(cfg.get("iterate") or "none")
    out_port = _default_output_port(node) or "result"
    active_parent = runner._active_runs.get((thread_id, run_id))
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
            sub_inputs = runner._map_entry_inputs(sub_def, {"__item__": item})
            child_thread = f"{thread_id}.map{i}"
            child_run = f"{run_id}.map{i}"
            child_context = runner._child_context(
                execution_context,
                session_id=thread_id,
                run_id=run_id,
                call_id=node.id,
                child_workflow_id=str(sub_def.id or sub_def.name),
                parent_workflow_id=parent_workflow_id,
            )
            sub = await runner.run(sub_def, inputs=sub_inputs, work_root=work_root,
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
        sub_inputs = runner._map_entry_inputs(sub_def, bound_inputs)
        output: Any = None
        for i in range(max_iter):
            child_context = runner._child_context(
                execution_context,
                session_id=thread_id,
                run_id=run_id,
                call_id=node.id,
                child_workflow_id=str(sub_def.id or sub_def.name),
                parent_workflow_id=parent_workflow_id,
            )
            sub = await runner.run(sub_def, inputs=sub_inputs, work_root=work_root,
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
                sub_inputs = runner._map_entry_inputs(sub_def, output)
            else:
                sub_inputs = runner._map_entry_inputs(sub_def, {"__value__": output})
        return {out_port: output}

    # iterate == "none": run once.
    sub_inputs = runner._map_entry_inputs(sub_def, bound_inputs)
    child_context = runner._child_context(
        execution_context,
        session_id=thread_id,
        run_id=run_id,
        call_id=node.id,
        child_workflow_id=str(sub_def.id or sub_def.name),
        parent_workflow_id=parent_workflow_id,
    )
    result = await runner.run(sub_def, inputs=sub_inputs, work_root=work_root,
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


def _map_entry_inputs(sub_def: WorkflowDef, bound_inputs: dict[str, Any]) -> dict[str, Any]:
    """Map bound inputs to a sub-workflow's orphaned in-port names.

    If the sub-workflow has exactly one orphaned input, all bound values
    are flattened into it (first non-sentinel). Otherwise, bound input port
    names are matched directly to sub-workflow input names.
    """
    from .runner_graph import SKIP_SENTINEL
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
        else:
            # 未连接的多输入端口留空：此前会填上第一个绑定值，等于把 A 的
            # 输入悄悄喂给 B（2026-09-25 审计 P3）。
            result[name] = None
    return result
