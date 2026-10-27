"""Flow-control leases, heartbeat and durable claim admission."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from .durable import WorkflowRunEvent
from .flow_control import (
    FlowControlDecision,
    FlowControlLease,
    FlowControlPolicy,
    FlowControlStore,
    stable_scope_key,
)
from .models import WorkflowDef, WorkflowNodeState, WorkflowRunResult, _json_copy


def _flow_control_policy(runner, workflow: WorkflowDef) -> FlowControlPolicy:
    """Read the canonical V2 scheduling policy, if this is a V2 run."""
    if not isinstance(workflow.document, Mapping):
        return FlowControlPolicy.empty()
    # Import lazily: document.py uses runtime data-model classes at its
    # conversion boundary, so importing it at module load would create a
    # cycle for embedders importing WorkflowRunner directly.
    from .document import workflow_flow_control_policy

    return workflow_flow_control_policy(workflow)


def _flow_control_store_for_run(
    runner,
    workflow: WorkflowDef,
    work_root: str,
) -> Any:
    if runner.flow_control_store is not None:
        return runner.flow_control_store
    effective_root = str(work_root or workflow.work_root or "").strip()
    if effective_root:
        try:
            cache_key = str(Path(effective_root).expanduser().resolve())
        except OSError:
            cache_key = effective_root
    else:
        cache_key = "<default>"
    store = runner._flow_control_stores.get(cache_key)
    if store is None:
        store = FlowControlStore(root=effective_root or None)
        runner._flow_control_stores[cache_key] = store
    return store


def _flow_control_scope_key(
    workflow: WorkflowDef,
    workflow_identity: str,
    work_root: str,
) -> str:
    try:
        root = str(Path(work_root or workflow.work_root or "").expanduser().resolve())
    except OSError:
        root = str(work_root or workflow.work_root or "")
    return stable_scope_key({"workflow_id": workflow_identity, "work_root": root})


def _flow_control_lease_id(
    workflow_identity: str,
    thread_id: str,
    run_id: str,
) -> str:
    return stable_scope_key(
        {"workflow_id": workflow_identity, "thread_id": thread_id, "run_id": run_id},
        key="run",
    )


def _normalize_flow_control_decision(value: Any) -> FlowControlDecision:
    if isinstance(value, FlowControlDecision):
        return value
    if isinstance(value, FlowControlLease):
        return FlowControlDecision("acquired", lease=value)
    if isinstance(value, Mapping):
        lease_value = value.get("lease")
        lease = (
            lease_value
            if isinstance(lease_value, FlowControlLease)
            else FlowControlLease.from_dict(lease_value)
            if isinstance(lease_value, Mapping)
            else None
        )
        allowed = bool(value.get("acquired", value.get("allowed", value.get("state") == "acquired")))
        if allowed:
            return FlowControlDecision("acquired", lease=lease)
        return FlowControlDecision(
            "blocked",
            reason=str(value.get("reason") or "flow_control"),
            retry_at=float(value["retry_at"]) if value.get("retry_at") is not None else None,
            reserved=bool(value.get("reserved", False)),
        )
    if isinstance(value, bool):
        return FlowControlDecision("acquired" if value else "blocked", reason="flow_control" if not value else "")
    allowed = bool(getattr(value, "acquired", getattr(value, "allowed", False)))
    if allowed:
        lease_value = getattr(value, "lease", None)
        return FlowControlDecision("acquired", lease=lease_value if isinstance(lease_value, FlowControlLease) else None)
    retry_value = getattr(value, "retry_at", None)
    try:
        retry_at = float(retry_value) if retry_value is not None else None
    except (TypeError, ValueError):
        retry_at = None
    return FlowControlDecision(
        "blocked",
        reason=str(getattr(value, "reason", "") or "flow_control"),
        retry_at=retry_at,
        reserved=bool(getattr(value, "reserved", False)),
    )


async def _flow_control_admit(
    runner,
    workflow: WorkflowDef,
    *,
    workflow_identity: str,
    work_root: str,
    thread_id: str,
    run_id: str,
    workflow_revision: int,
    workflow_digest: str,
    previous: WorkflowRunResult | None,
    prior_values: dict[str, Any] | None,
    prior_node_states: dict[str, WorkflowNodeState] | None,
    started_at: datetime,
    inputs: dict[str, Any] | None,
) -> tuple[FlowControlPolicy, Any, FlowControlLease | Mapping[str, Any] | None, asyncio.Task[Any] | None, asyncio.Event | None, WorkflowRunResult | None]:
    """Admit one actual run, returning a paused result when blocked."""
    from .runner_cancellation import _call_with_supported_kwargs
    policy = runner._flow_control_policy(workflow)
    if not policy.enabled:
        return policy, None, None, None, None, None
    store = runner._flow_control_store_for_run(workflow, work_root)
    scope_key = runner._flow_control_scope_key(workflow, workflow_identity, work_root)
    lease_id = runner._flow_control_lease_id(workflow_identity, thread_id, run_id)
    decision_raw = await _call_with_supported_kwargs(
        store.acquire,
        {
            "policy": policy,
            "scope_key": scope_key,
            "lease_id": lease_id,
        },
    )
    decision = runner._normalize_flow_control_decision(decision_raw)
    if not decision.acquired:
        retry_at = decision.retry_at
        descriptor: dict[str, Any] = {
            "kind": "flow_control",
            "type": "flow_control",
            "reason": decision.reason or "flow_control",
            "blocked_by": decision.reason or "flow_control",
            "scope_key": scope_key,
            "lease_id": lease_id,
            "workflow_id": workflow_identity,
            "workflow_revision": workflow_revision,
            "definition_digest": workflow_digest,
            "thread_id": thread_id,
            "run_id": run_id,
            "retry_at": retry_at,
            "policy": policy.to_dict(),
        }
        if decision.reserved:
            descriptor["reserved"] = True
        preserved_values = (
            dict(previous.values)
            if previous is not None
            else dict(prior_values or {})
        )
        preserved_states = (
            previous.node_states
            if previous is not None
            else (prior_node_states or {})
        )
        result = WorkflowRunResult(
            status="paused",
            run_id=run_id,
            workflow_id=workflow_identity,
            workflow_revision=workflow_revision,
            definition_digest=workflow_digest,
            wait_descriptor=descriptor,
            output=previous.output if previous is not None else None,
            values=preserved_values,
            node_states={
                node_id: WorkflowNodeState.from_dict(state.to_dict(), node_id=node_id)
                for node_id, state in preserved_states.items()
            },
            steps_remaining=previous.steps_remaining if previous is not None else 0,
            started_at=previous.started_at if previous is not None and previous.started_at else started_at,
            finished_at=None,
        )
        await runner._append_durable_event(
            WorkflowRunEvent(
                event_id=f"{run_id}:flow-control:{descriptor['reason']}:{retry_at}",
                run_id=run_id,
                kind="run.flow_control_blocked",
                workflow_id=workflow_identity,
                workflow_revision=workflow_revision,
                payload={"wait_descriptor": _json_copy(descriptor)},
            )
        )
        await runner._persist_snapshot(
            thread_id,
            run_id,
            result,
            workflow=workflow,
            inputs=inputs,
        )
        return policy, store, None, None, None, result
    lease = decision.lease
    if lease is None:
        # A host may provide a boolean admission adapter.  It can grant
        # admission, but without a lease there is nothing to heartbeat or
        # release; preserve that adapter contract.
        return policy, store, None, None, None, None
    lost = asyncio.Event()
    heartbeat = asyncio.create_task(
        runner._flow_control_heartbeat(store, lease, lost),
        name=f"workflow:flow-control:{run_id}",
    )
    return policy, store, lease, heartbeat, lost, None


async def _flow_control_heartbeat(
    runner,
    store: Any,
    lease: FlowControlLease | Mapping[str, Any],
    lost: asyncio.Event,
) -> None:
    from .runner_cancellation import _call_with_supported_kwargs
    current = lease
    try:
        try:
            lease_seconds = float(getattr(store, "lease_seconds", 30.0))
        except (TypeError, ValueError):
            lease_seconds = 30.0
        interval = max(0.01, min(5.0, lease_seconds / 3.0))
        while True:
            await asyncio.sleep(interval)
            renewed = await _call_with_supported_kwargs(store.renew, {"lease": current})
            if renewed is None or renewed is False:
                lost.set()
                return
            # Some host adapters return a boolean acknowledgement instead
            # of a refreshed lease.  Keep the original fencing token in
            # that case; the built-in store returns a new lease object.
            if renewed is not True:
                current = renewed
    except asyncio.CancelledError:
        raise
    except Exception:
        lost.set()


async def _flow_control_release(
    runner,
    store: Any,
    lease: FlowControlLease | Mapping[str, Any] | None,
    heartbeat: asyncio.Task[Any] | None,
) -> None:
    from .runner_cancellation import _call_with_supported_kwargs
    if heartbeat is not None and not heartbeat.done():
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
    if store is not None and lease is not None:
        try:
            await _call_with_supported_kwargs(store.release, {"lease": lease})
        except Exception:
            # Lease release is best effort during cancellation/shutdown;
            # expiry cleanup/fencing prevents a stale lease from granting
            # indefinite capacity.
            pass


async def _execute_durable_claim(
    runner,
    kind: Literal["run", "signal"],
    thread_id: str,
    run_id: str,
    operation: Callable[[], Awaitable[WorkflowRunResult]],
    *,
    request_fingerprint: str,
    mismatch_result: Callable[[], WorkflowRunResult] | None = None,
) -> WorkflowRunResult:
    """Execute under a SQLite lease and fence; waiters observe its result."""
    from .runner_cancellation import _call_with_supported_kwargs
    if runner.claim_store is None:
        return await operation()
    while True:
        acquired = await _call_with_supported_kwargs(
            runner.claim_store.acquire,
            {
                "kind": kind,
                "thread_id": thread_id,
                "run_id": run_id,
                "request_fingerprint": request_fingerprint,
            },
        )
        if acquired.state == "completed" and isinstance(acquired.result, dict):
            return WorkflowRunResult.from_dict(acquired.result)
        if acquired.state == "mismatch":
            if mismatch_result is not None:
                return mismatch_result()
            raise ValueError("workflow signal request does not match the completed claim")
        if acquired.state == "busy":
            delay = max(0.01, min(0.2, acquired.retry_at - datetime.now(timezone.utc).timestamp()))
            await asyncio.sleep(delay)
            continue
        lease = acquired.lease
        if lease is None:
            raise RuntimeError("workflow durable claim acquisition failed")
        operation_task = asyncio.create_task(operation())

        async def _heartbeat() -> bool:
            current_lease = lease
            interval = max(0.25, runner.claim_store.lease_seconds / 3)
            while not operation_task.done():
                await asyncio.sleep(interval)
                if operation_task.done():
                    return True
                renewed = await runner.claim_store.renew(current_lease)
                if renewed is None:
                    return False
                current_lease = renewed
            return True

        heartbeat_task = asyncio.create_task(_heartbeat())
        try:
            done, _ = await asyncio.wait(
                {operation_task, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if heartbeat_task in done and heartbeat_task.result() is False:
                operation_task.cancel()
                await asyncio.gather(operation_task, return_exceptions=True)
                raise RuntimeError("workflow durable claim lease was lost")
            result = await operation_task
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            if result.status in {"completed", "failed", "cancelled"}:
                if not await runner.claim_store.complete(lease, result.to_dict()):
                    raise RuntimeError("workflow durable claim fence was lost before commit")
            elif not await runner.claim_store.release(lease):
                raise RuntimeError("workflow durable claim fence was lost before release")
            return result
        except BaseException:
            if not heartbeat_task.done():
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            if not operation_task.done():
                operation_task.cancel()
                await asyncio.gather(operation_task, return_exceptions=True)
            try:
                await runner.claim_store.release(lease)
            except Exception:
                pass
            raise
