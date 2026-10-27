"""Approval decisions and durable continuation scheduling."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
from typing import Any
from ..live_protocol import INVALID_REQUEST, rpc_error, rpc_result
from ..operation_catalog import OperationResult
from .context import CoreLiveContext, CoreLiveOperationOutcome


async def handle_approval_respond_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    from .background import _logger
    from .continuations import _approval_job_key, _pending_approval_record, _run_continuation_job, _settle_continuation_waiters
    from .interactions import _append_interaction_lifecycle_event, _execute_inline_approval_operation, _interaction_for_request, _resolved_interaction_for_request
    from .params import _expected_revision, _thread_id_from_params
    if not context.operations.has("approval.respond"):
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="approval.respond operation is unavailable")
        )
    try:
        expected_revision = _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    thread_id = _thread_id_from_params(params)
    approval_request_id = str(
        params.get("request_id") or params.get("requestId") or ""
    ).strip()
    state_store = context.host.runtime_state_store
    state = None
    if state_store is not None and thread_id:
        state = await state_store.get(thread_id)
    pending = _pending_approval_record(state)
    if (
        state_store is not None
        and approval_request_id
        and (state is None or pending is None)
    ):
        # The card's owner may be a child session, or an older run whose
        # request id routes to a different runtime state. The pool must send
        # the answer back to its own owner, not assume the parent thread.
        finder = getattr(state_store, "find_pending_approval", None)
        if callable(finder):
            matched_state = await finder(approval_request_id)
            if matched_state is not None:
                state = matched_state
                pending = _pending_approval_record(state)
    if state is None or pending is None:
        resolved = await _resolved_interaction_for_request(
            context, thread_id, approval_request_id
        )
        if resolved is not None:
            # A repeated click on a card whose answer already landed is a
            # duplicate acknowledgement, not an error. Returning success lets
            # every window clear the stale card.
            return CoreLiveOperationOutcome(
                response=rpc_result(
                    request_id,
                    {
                        "thread_id": resolved.thread_id or thread_id,
                        "turn_id": resolved.turn_id,
                        "request_id": approval_request_id,
                        "status": "resolved",
                        "duplicate": True,
                    },
                )
            )
        stale = await _interaction_for_request(
            context, thread_id, approval_request_id
        )
        if stale is not None:
            # The interaction outlived its runtime pending (a completed turn,
            # a restart, or an old run). It can never be answered; close it as
            # superseded instead of returning a raw backend error.
            if not stale.terminal:
                await context.turn_store.resolve_interaction(
                    stale.interaction_id, status="cancelled"
                )
                try:
                    await _append_interaction_lifecycle_event(
                        context,
                        stale,
                        state="ending",
                        decision="superseded",
                        reason="no_live_pending",
                    )
                except BaseException:
                    _logger.exception(
                        "[live:approval] failed to close stale interaction thread_id=%s id=%s",
                        thread_id,
                        stale.interaction_id,
                    )
            return CoreLiveOperationOutcome(
                response=rpc_result(
                    request_id,
                    {
                        "thread_id": stale.thread_id or thread_id,
                        "turn_id": stale.turn_id,
                        "request_id": approval_request_id,
                        "status": "resolved" if stale.terminal else "superseded",
                        "duplicate": True,
                    },
                )
            )
        if context.host.runtime_state_store is None:
            # Focused/embedded hosts without the turn-control tables keep the
            # direct catalog contract.
            return await _execute_inline_approval_operation(
                request_id=request_id, params=params, context=context
            )
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="approval.respond requires a runtime with a pending approval",
                data={"error": "no pending approval"},
            )
        )
    pending_call = pending.get("tool_call") if isinstance(pending.get("tool_call"), dict) else {}
    expected_request_id = str(pending.get("request_id") or "").strip()
    expected_tool_call_id = str(pending_call.get("id") or "").strip()
    if (
        approval_request_id
        and approval_request_id not in {expected_request_id, expected_tool_call_id}
    ):
        # A stale card from an old run can stay visible after pause/resume or
        # after the model re-asks. It is no longer the active request: close it
        # instead of returning "approval request mismatch" to the user.
        stale = await _interaction_for_request(context, thread_id, approval_request_id)
        if stale is not None:
            if not stale.terminal:
                await context.turn_store.resolve_interaction(
                    stale.interaction_id, status="cancelled"
                )
                try:
                    await _append_interaction_lifecycle_event(
                        context,
                        stale,
                        decision="superseded",
                        reason="superseded_by_active_request",
                    )
                except BaseException:
                    _logger.exception(
                        "[live:approval] failed to close stale interaction thread_id=%s id=%s",
                        thread_id,
                        stale.interaction_id,
                    )
            return CoreLiveOperationOutcome(
                response=rpc_result(
                    request_id,
                    {
                        "thread_id": stale.thread_id or thread_id,
                        "turn_id": stale.turn_id,
                        "request_id": approval_request_id,
                        "status": "resolved" if stale.terminal else "superseded",
                        "duplicate": True,
                    },
                )
            )
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="approval request mismatch",
                data={"error": "approval request mismatch"},
            )
        )
    if str(pending.get("status") or "") == "executing":
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="approval already resolving",
                data={"error": "approval already resolving"},
            )
        )
    if str(getattr(state, "status", "") or "") == "paused":
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="turn is paused",
                data={"error": "turn is paused", "code": "turn_paused"},
            )
        )
    if thread_id and expected_revision is not None:
        await context.persistence.write(
            lambda db: context.persistence.assert_revision(
                db, thread_id, expected_revision
            )
        )
    # Child approvals are queued on the child session: that is also the claim
    # the continuation serializes against, and it keeps two children from
    # blocking each other or a new parent turn.
    job_thread_id = str(getattr(state, "session_id", "") or thread_id or approval_request_id)
    run_id = str(getattr(state, "run_id", "") or "")
    state_metadata = state.metadata if isinstance(state.metadata, dict) else {}
    turn_id = str(state_metadata.get("turn_id") or run_id)
    decision = str(params.get("decision") or params.get("action") or "")
    guidance = str(params.get("guidance") or params.get("response") or "")
    worker = context.turn_worker
    job = await worker.enqueue(
        thread_id=job_thread_id,
        turn_id=turn_id,
        run_id=run_id,
        kind="approval.respond",
        payload={"params": dict(params)},
        idempotency_key=_approval_job_key(
            thread_id=job_thread_id,
            run_id=run_id,
            request_id=approval_request_id or str(pending.get("request_id") or ""),
            decision=decision,
            guidance=guidance,
        ),
    )
    job_id = str(job.get("job_id") or "")
    fallback_info = {
        "thread_id": thread_id or job_thread_id,
        "run_id": run_id,
        "turn_id": turn_id,
        "decision": decision,
        "status": "accepted",
        "snapshot": None,
    }
    waiter: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
    context._job_waiters.setdefault(job_id, []).append(waiter)
    recorded_outcome = context._job_outcomes.get(job_id)
    if recorded_outcome is not None:
        _settle_continuation_waiters(context, job_id, recorded_outcome)
    task = asyncio.create_task(
        _run_continuation_job(
            context=context,
            worker=worker,
            job_id=job_id,
            fallback_info=fallback_info,
        ),
        name=f"turn-continuation:{job_id}",
    )

    def _log_background_failure(done: asyncio.Task[Any]) -> None:
        if done.cancelled():
            return
        exc = done.exception()
        if exc is not None:
            _logger.error(
                "[live:approval] durable continuation failed thread_id=%s job_id=%s: %s",
                job_thread_id,
                job_id,
                exc,
            )

    task.add_done_callback(_log_background_failure)
    try:
        outcome = await waiter
    except asyncio.CancelledError:
        # The continuation task must outlive the RPC that asked for it.
        raise
    outcome_type = str(outcome.get("type") or "")
    if outcome_type == "error":
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=str(outcome.get("error") or "approval continuation failed"),
            )
        )
    if outcome_type == "accepted":
        info = dict(outcome.get("info") or {})
        return CoreLiveOperationOutcome(
            response=rpc_result(
                request_id,
                {
                    "thread_id": info.get("thread_id"),
                    "run_id": info.get("run_id"),
                    "turn_id": info.get("turn_id"),
                    "decision": info.get("decision"),
                    "status": "accepted",
                    "snapshot": info.get("snapshot"),
                },
            )
        )
    result = outcome.get("result")
    if not isinstance(result, OperationResult):
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="approval continuation produced no result",
            )
        )
    payload_result = dict(result.payload or {})
    if result.status != "ok":
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=str(payload_result.get("error") or result.status),
                data=payload_result,
            )
        )
    return CoreLiveOperationOutcome(response=rpc_result(request_id, payload_result))
