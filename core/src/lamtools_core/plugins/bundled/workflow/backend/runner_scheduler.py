"""Topological workflow scheduling and per-node state transitions."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
import uuid
from typing import Any
from .durable import WorkflowRunEvent
from .executors import WorkflowExecutorError
from .models import WorkflowDef, WorkflowNodeState, WorkflowRunResult, _json_copy, _new_id, ensure_workflow_id
from .persistence import WorkflowPersistenceError
from .runner_context import WorkflowExecutionContext


async def _run_impl(
    runner,
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
    from .runner_cancellation import _cancellation_requested, _pause_requested
    from .runner_context import WorkflowExpressionError, WorkflowValidationError
    from .runner_graph import SKIP_SENTINEL, _bind_inputs, _default_output_port, _inputs_ready, _resolve_output, _topological_order, _workflow_input_default, _workflow_input_names
    from .runner_state import _ActiveWorkflowRun
    from .runner_validation import _validate_run_inputs, validate_workflow
    from .runner_values import _mark_cancelled
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
            node_registry=runner.node_registry,
        )
        _validate_run_inputs(workflow, inputs, dict(prior_values or {}))
        runner._validate_executable_nodes(workflow)
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
                    WorkflowNodeState(node_id=skipped_id, status="skipped", finished_at=runner.clock()),
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
    runner._active_runs[active_key] = active
    if runner.emit_lifecycle_events:
        await runner._emit_run_status(
            "running",
            thread_id,
            run_id,
            workflow_id=workflow_id,
        )
    cancel_event = (
        execution_context.cancellation
        if execution_context is not None and execution_context.cancellation is not None
        else runner._cancel_event(thread_id)
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
            await runner._persist_active_snapshot(
                workflow=workflow,
                thread_id=thread_id,
                run_id=run_id,
                inputs=inputs,
                node_states=node_states,
                values=values,
                steps_remaining=len(order) - steps_taken,
            )
            if runner.emit_lifecycle_events:
                await runner._emit_run_status(
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
            state.finished_at = runner.clock()
            await runner._emit_state(
                node,
                "failed",
                thread_id,
                run_id,
                workflow_id=workflow_id,
                error=error_msg,
            )
            await runner._persist_active_snapshot(
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
            state.finished_at = runner.clock()
            for port in node.output_ports():
                values[f"{node.id}.{port.name}"] = SKIP_SENTINEL
            await runner._emit_state(node, "skipped", thread_id, run_id, workflow_id=workflow_id)
            await runner._persist_active_snapshot(
                workflow=workflow,
                thread_id=thread_id,
                run_id=run_id,
                inputs=inputs,
                node_states=node_states,
                values=values,
                steps_remaining=len(order) - steps_taken - 1,
            )
            continue

        builtin_executor = runner._builtin_executor_name(node)
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
            descriptor = runner._wait_descriptor(
                node,
                workflow=workflow,
                thread_id=thread_id,
                run_id=run_id,
                kind=builtin_executor,
            )
            state.status = "waiting"
            state.started_at = state.started_at or runner.clock()
            state.finished_at = None
            state.wait_descriptor = descriptor
            await runner._emit_state(node, "waiting", thread_id, run_id, workflow_id=workflow_id)
            await runner._append_durable_event(
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
            await runner._persist_active_snapshot(
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
        state.started_at = runner.clock()
        await runner._emit_state(node, "running", thread_id, run_id, workflow_id=workflow_id)

        try:
            outputs = await runner._execute_with_retries(
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
                await runner._persist_active_snapshot(
                    workflow=workflow,
                    thread_id=thread_id,
                    run_id=run_id,
                    inputs=inputs,
                    node_states=node_states,
                    values=values,
                    steps_remaining=steps_remaining,
                )
                if runner.emit_lifecycle_events:
                    await runner._emit_run_status(
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
            state.finished_at = runner.clock()
            _mark_cancelled(node_states, workflow, order, order.index(node_id) + 1)
            await runner._emit_state(
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
        except WorkflowPersistenceError:
            raise
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
                state.finished_at = runner.clock()
                await runner._emit_state(
                    node, "completed", thread_id, run_id,
                    workflow_id=workflow_id, error=error_msg,
                )
                for port_name, value in outputs.items():
                    values[f"{node.id}.{port_name}"] = value
                steps_taken += 1
                await runner._persist_active_snapshot(
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
                state.finished_at = runner.clock()
                for port in node.output_ports():
                    values[f"{node.id}.{port.name}"] = SKIP_SENTINEL
                await runner._emit_state(
                    node, "skipped", thread_id, run_id,
                    workflow_id=workflow_id, error=error_msg,
                )
                await runner._persist_active_snapshot(
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
            state.finished_at = runner.clock()
            await runner._emit_state(
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
        state.finished_at = runner.clock()
        await runner._emit_state(
            node,
            "completed",
            thread_id,
            run_id,
            workflow_id=workflow_id,
            cache_status=state.cache_status,
            cache_key=state.cache_key,
        )
        steps_taken += 1
        await runner._persist_active_snapshot(
            workflow=workflow,
            thread_id=thread_id,
            run_id=run_id,
            inputs=inputs,
            node_states=node_states,
            values=values,
            steps_remaining=len(order) - steps_taken,
        )
        if runner.emit_lifecycle_events:
            await runner._emit_run_status(
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
