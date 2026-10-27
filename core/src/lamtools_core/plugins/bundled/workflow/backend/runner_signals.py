"""Wait descriptors, signal resumption, interruption and shutdown."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
import secrets
from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from .durable import WorkflowRunEvent, definition_digest
from .models import WorkflowDef, WorkflowNode, WorkflowRunResult, _as_int, _json_copy, _parse_dt


async def interrupt(runner, thread_id: str, run_id: str) -> WorkflowRunResult | None:
    """Persist a resumable snapshot for a queue/process shutdown.

    This is intentionally separate from user cancellation: queue shutdown
    asks the runner to preserve progress, while an explicit cancel keeps
    the terminal ``cancelled`` result.
    """
    key = (str(thread_id or ""), str(run_id or ""))
    active = runner._active_runs.get(key)
    if active is None:
        return None
    result = runner._paused_result(key)
    runner._run_snapshots[key] = WorkflowRunResult.from_dict(result.to_dict())
    await runner._persist_snapshot(
        key[0],
        key[1],
        result,
        workflow=active.workflow,
        inputs=active.inputs,
    )
    return result


def _wait_descriptor(
    runner,
    node: WorkflowNode,
    *,
    workflow: WorkflowDef,
    thread_id: str,
    run_id: str,
    kind: str,
) -> dict[str, Any]:
    created_at = runner.clock()
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
    runner,
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
    from .runner_graph import _default_output_port
    from .runner_state import _PROCESS_SIGNAL_LOCKS, _PROCESS_SIGNAL_LOCK_USERS, _claim_request_fingerprint, _coordination_store_key
    thread_id = str(thread_id or "").strip()
    run_id = str(run_id or "").strip()
    resume_token = str(resume_token or "")
    event_type = str(event_type or "").strip()
    if not thread_id or not run_id or not resume_token or not event_type:
        raise ValueError("thread_id, run_id, resume_token and event_type are required")
    if not _signal_lock_held:
        signal_key = (thread_id, run_id)
        signal_lock = runner._signal_locks.setdefault(signal_key, asyncio.Lock())
        runner._signal_lock_users[signal_key] = runner._signal_lock_users.get(signal_key, 0) + 1
        try:
            async with signal_lock:
                return await runner.signal(
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
            remaining_users = runner._signal_lock_users.get(signal_key, 1) - 1
            if remaining_users <= 0:
                runner._signal_lock_users.pop(signal_key, None)
                if runner._signal_locks.get(signal_key) is signal_lock:
                    runner._signal_locks.pop(signal_key, None)
            else:
                runner._signal_lock_users[signal_key] = remaining_users

    journal_events = await runner.event_store.list(run_id) if runner.event_store is not None else []
    if not _process_signal_lock_held:
        process_key = (
            _coordination_store_key(runner.event_store, runner.snapshot_store),
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
                return await runner.signal(
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
    if runner.claim_store is not None and not _durable_signal_claim_held:
        return await runner._execute_durable_claim(
            "signal",
            thread_id,
            run_id,
            lambda: runner.signal(
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

    if runner.snapshot_store is None:
        raise LookupError("workflow durable snapshot store is not configured")
    envelope = await runner.snapshot_store.get_dict(thread_id, run_id)
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
    if deadline is not None and runner.clock() >= deadline:
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
        await runner._append_durable_event(
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
    state.finished_at = runner.clock()
    return await runner.run(
        workflow,
        inputs=dict(envelope.get("inputs") or {}),
        work_root=workflow.work_root,
        thread_id=thread_id,
        run_id=run_id,
        prior_values=previous.values,
        prior_node_states=previous.node_states,
    )


async def shutdown(runner) -> None:
    """Cancel and join Runner-owned workflow tasks during plugin unload."""
    current = asyncio.current_task()
    tasks = [
        task
        for task in runner._active_tasks.values()
        if task is not current and not task.done()
    ]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    runner._active_tasks.clear()
    runner._active_runs.clear()
    runner._terminal_results.clear()
    for key in [key for key, users in runner._run_lock_users.items() if users <= 0]:
        runner._run_lock_users.pop(key, None)
        runner._run_locks.pop(key, None)
    for key in [key for key, users in runner._signal_lock_users.items() if users <= 0]:
        runner._signal_lock_users.pop(key, None)
        runner._signal_locks.pop(key, None)
