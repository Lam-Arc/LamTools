"""Workflow snapshots, lifecycle events and terminal result construction."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
from typing import Any
from lamtools_core.event.run_item import RunItemEvent, RunItemStatus
from .durable import WorkflowRunEvent, definition_digest
from .models import (
    WorkflowDef,
    WorkflowNode,
    WorkflowNodeState,
    WorkflowRunResult,
    _json_copy,
    public_workflow_value,
)


async def _persist_snapshot(
    runner,
    thread_id: str,
    run_id: str,
    result: WorkflowRunResult,
    *,
    workflow: WorkflowDef,
    inputs: dict[str, Any] | None,
) -> None:
    """Persist the latest resumable state when a store is configured."""
    if runner.snapshot_store is None:
        return
    await runner.snapshot_store.save(
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


async def _append_durable_event(runner, event: WorkflowRunEvent) -> None:
    """Append before/after side effects when durable journaling is enabled.

    Unlike GUI emission, journal failure is not swallowed: executing a
    side effect without a durable attempt identity would make recovery
    unsafe and must fail closed.
    """
    if runner.event_store is not None:
        await runner.event_store.append(event)


async def _persist_active_snapshot(
    runner,
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
    await runner._persist_snapshot(
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


def _cancelled_result(runner, key: tuple[str, str]) -> WorkflowRunResult:
    """Build a complete cancellation result from the in-flight snapshot."""
    active = runner._active_runs.get(key)
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
        current.finished_at = current.finished_at or runner.clock()
    for node_id in active.order:
        state = active.node_states.get(node_id)
        if state is not None and state.status == "idle":
            state.status = "cancelled"
            state.error = state.error or "cancelled"
            state.finished_at = state.finished_at or runner.clock()
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


def _paused_result(runner, key: tuple[str, str]) -> WorkflowRunResult:
    """Build a resumable result from an in-flight run after shutdown."""
    active = runner._active_runs.get(key)
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


def _cancel_event(runner, thread_id: str) -> Any:
    if runner.runtime_task_registry is None or not thread_id:
        return None
    try:
        return runner.runtime_task_registry.get_cancel_event(thread_id)
    except Exception:  # noqa: BLE001 — registry optional
        return None


async def _emit_state(
    runner,
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
    active = runner._active_runs.get((thread_id, run_id))
    workflow_revision = active.workflow.revision if active is not None else 0
    state = active.node_states.get(node.id) if active is not None else None
    occurred_at = runner.clock()
    event_kind = {
        "running": "started",
        "completed": "completed",
        "failed": "failed",
        "skipped": "skipped",
        "cancelled": "cancelled",
    }.get(str(status), str(status))
    await runner._append_durable_event(
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
    if runner.emit is None:
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
    execution_context = getattr(runner._active_runs.get((thread_id, run_id)), "execution_context", None)
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
        result = runner.emit(event)
        if asyncio.iscoroutine(result):
            await result
    except Exception:  # noqa: BLE001 — streaming must never break execution
        pass


async def _emit_run_status(
    runner,
    status: str,
    thread_id: str,
    run_id: str,
    *,
    workflow_id: str = "",
    node_id: str = "",
    **details: Any,
) -> None:
    """Emit lifecycle progress without changing legacy node events."""
    if runner.emit is None:
        return
    event_status = status
    payload: dict[str, Any] = {
        "plugin_id": "workflow",
        "workflow_id": workflow_id,
        "run_id": run_id,
        "node_id": node_id,
        "status": status,
        "occurred_at": runner.clock().isoformat(),
        **details,
    }
    metadata = {
        "plugin_id": "workflow",
        "workflow_id": workflow_id,
        "run_id": run_id,
        "node_id": node_id,
    }
    execution_context = getattr(
        runner._active_runs.get((thread_id, run_id)),
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
        result = runner.emit(
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
