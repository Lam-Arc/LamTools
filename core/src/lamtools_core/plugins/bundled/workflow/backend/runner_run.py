"""Workflow admission, single-flight ownership and run lifecycle."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
import uuid
from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from .durable import WorkflowRunEvent, definition_digest
from .flow_control import FlowControlLease
from .models import WorkflowDef, WorkflowNodeState, WorkflowRunResult, _as_int, _new_id, ensure_workflow_id
from .persistence import WorkflowPersistenceError
from .runner_context import WorkflowExecutionContext


async def run(
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
    from .runner_cancellation import _pause_requested
    from .runner_context import WorkflowNestingError, WorkflowRecursionError
    from .runner_state import _PROCESS_RUN_LOCKS, _PROCESS_RUN_LOCK_USERS, _claim_request_fingerprint, _coordination_store_key
    from .runner_values import _cache_facts
    effective_run_id = run_id or _new_id("wfrun")
    effective_thread_id = thread_id or f"workflow_thread_{uuid.uuid4().hex}"
    key = (effective_thread_id, effective_run_id)
    if not _run_lock_held:
        run_lock = runner._run_locks.setdefault(key, asyncio.Lock())
        runner._run_lock_users[key] = runner._run_lock_users.get(key, 0) + 1
        try:
            async with run_lock:
                return await runner.run(
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
            remaining_users = runner._run_lock_users.get(key, 1) - 1
            if remaining_users <= 0:
                runner._run_lock_users.pop(key, None)
                if runner._run_locks.get(key) is run_lock:
                    runner._run_locks.pop(key, None)
            else:
                runner._run_lock_users[key] = remaining_users
    started_at = runner.clock()
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
    cached_terminal = runner._terminal_results.get(key)
    if cached_terminal is not None and (
        cached_terminal.workflow_id == workflow_identity
        and cached_terminal.workflow_revision == workflow_revision
        and cached_terminal.definition_digest == workflow_digest
    ):
        runner._terminal_results.move_to_end(key)
        return WorkflowRunResult.from_dict(cached_terminal.to_dict())
    previous = runner._run_snapshots.get(key)
    snapshot_envelope: dict[str, Any] | None = None
    if previous is None and runner.snapshot_store is not None:
        snapshot_envelope = await runner.snapshot_store.get_dict(effective_thread_id, effective_run_id)
        previous = await runner.snapshot_store.get(effective_thread_id, effective_run_id)
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
    if runner.event_store is not None:
        journal_events = await runner.event_store.list(effective_run_id)
        if not _process_run_lock_held:
            process_key = (
                _coordination_store_key(runner.event_store, runner.snapshot_store),
                effective_thread_id,
                effective_run_id,
            )
            process_lock = _PROCESS_RUN_LOCKS.setdefault(process_key, asyncio.Lock())
            _PROCESS_RUN_LOCK_USERS[process_key] = _PROCESS_RUN_LOCK_USERS.get(process_key, 0) + 1
            try:
                async with process_lock:
                    return await runner.run(
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
        if runner.claim_store is not None and not _durable_run_claim_held:
            return await runner._execute_durable_claim(
                "run",
                effective_thread_id,
                effective_run_id,
                lambda: runner.run(
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
                runner._remember_terminal(key, terminal_result)
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
        cancellation=runner._cancel_event(effective_thread_id),
        max_depth=runner.max_nesting_depth,
    )
    # A caller-created context may carry a larger limit than this runner;
    # an embedded runner must not be able to widen the host's bound.
    context_max_depth = max(0, int(execution_context.max_depth))
    effective_max_depth = min(runner.max_nesting_depth, context_max_depth)
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
        ) = await runner._flow_control_admit(
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
            runner._run_snapshots[key] = WorkflowRunResult.from_dict(blocked_result.to_dict())
            return blocked_result
        if current_task is not None:
            runner._active_tasks[key] = current_task
        await runner._append_durable_event(
            WorkflowRunEvent(
                event_id=f"{effective_run_id}:run:started",
                run_id=effective_run_id,
                kind="run.started",
                workflow_id=workflow_identity,
                workflow_revision=workflow_revision,
                payload={"definition_digest": workflow_digest, "thread_id": effective_thread_id},
            )
        )
        result = await runner._run_impl(
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
        result.started_at = previous.started_at if previous and previous.started_at else started_at
        result.finished_at = None if result.status == "paused" else runner.clock()
        await runner._append_durable_event(
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
            runner._run_snapshots[key] = WorkflowRunResult.from_dict(result.to_dict())
            await runner._persist_snapshot(
                effective_thread_id,
                effective_run_id,
                result,
                workflow=workflow,
                inputs=inputs,
            )
        else:
            runner._remember_terminal(key, result)
            runner._run_snapshots.pop(key, None)
            if runner.snapshot_store is not None:
                try:
                    await runner.snapshot_store.delete(effective_thread_id, effective_run_id)
                except Exception:  # noqa: BLE001 - cleanup is best effort
                    pass
        if runner.emit_lifecycle_events and result.status in {"completed", "failed", "cancelled"}:
            await runner._emit_run_status(
                result.status,
                effective_thread_id,
                effective_run_id,
                workflow_id=workflow.id,
                node_id="",
                error=result.error,
            )
        return result
    except asyncio.CancelledError:
        if _pause_requested(execution_context):
            result = runner._paused_result(key)
            result.started_at = previous.started_at if previous and previous.started_at else started_at
            result.finished_at = None
            runner._run_snapshots[key] = WorkflowRunResult.from_dict(result.to_dict())
            active = runner._active_runs.get(key)
            if active is not None:
                await runner._persist_snapshot(
                    effective_thread_id,
                    effective_run_id,
                    result,
                    workflow=active.workflow,
                    inputs=active.inputs,
                )
            return result
        result = runner._cancelled_result(key)
        result.started_at = previous.started_at if previous and previous.started_at else started_at
        result.finished_at = runner.clock()
        runner._run_snapshots.pop(key, None)
        runner._remember_terminal(key, result)
        return result
    except WorkflowPersistenceError as exc:
        # Persist a terminal failure in the independent journal when it
        # remains available. A stale checkpoint must not replay completed
        # side effects after a required snapshot commit fails.
        active = runner._active_runs.get(key)
        failed = WorkflowRunResult(
            status="failed", error=str(exc), run_id=effective_run_id,
            node_states=dict(active.node_states) if active else {},
            values=dict(active.values) if active else {},
            workflow_id=workflow_identity, workflow_revision=workflow_revision,
            definition_digest=workflow_digest,
        )
        if runner.event_store is not None:
            try:
                await runner._append_durable_event(WorkflowRunEvent(
                    event_id=f"{effective_run_id}:run:failed", run_id=effective_run_id,
                    kind="run.failed", workflow_id=workflow_identity,
                    workflow_revision=workflow_revision,
                    payload={"error": failed.error, "result": failed.to_dict()},
                ))
            except WorkflowPersistenceError:
                pass  # Preserve the original failure; never report success.
        runner._remember_terminal(key, failed)
        raise
    finally:
        await runner._flow_control_release(
            flow_control_store,
            flow_control_lease,
            flow_control_heartbeat,
        )
        runner._active_tasks.pop(key, None)
        runner._active_runs.pop(key, None)
