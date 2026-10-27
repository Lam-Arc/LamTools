"""Durable approval continuation execution and waiter settlement."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
from typing import Any
from lamtools_core.runtime.goal_continuation import should_continue_goal
from ..runtime_permissions import overlay_runtime_permissions
from .context import CoreLiveContext


def _approval_job_key(
    *,
    thread_id: str,
    run_id: str,
    request_id: str,
    decision: str,
    guidance: str,
) -> str:
    import hashlib
    import json as _json

    material = _json.dumps(
        {
            "thread_id": thread_id,
            "run_id": run_id,
            "request_id": request_id,
            "decision": decision,
            "guidance": guidance,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return "continuation:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _settle_continuation_waiters(
    context: CoreLiveContext, job_id: str, outcome: dict[str, Any]
) -> None:
    # Keep the terminal outcome so a duplicate click that registers a waiter
    # after the first one was resolved still receives an acknowledgement.
    context._job_outcomes[job_id] = outcome
    while len(context._job_outcomes) > 512:
        context._job_outcomes.pop(next(iter(context._job_outcomes)))
    for waiter in context._job_waiters.pop(job_id, []):
        if not waiter.done():
            waiter.set_result(outcome)


def _pending_approval_record(state: Any) -> dict[str, Any] | None:
    metadata = state.metadata if state is not None and isinstance(state.metadata, dict) else {}
    pending = metadata.get("pending_approval")
    if not isinstance(pending, dict):
        pending = metadata.get("pending_waiting_request")
    return pending if isinstance(pending, dict) else None


async def _approval_continuation_params(
    *, context: CoreLiveContext, params: dict[str, Any]
) -> dict[str, Any]:
    """Overlay the session's current permissions onto the parked runtime.

    Model/thinking options stay tied to the paused turn; permission fields must
    reflect the live session, because the user may have changed them after the
    card was opened.
    """
    from .params import _thread_id_from_params
    from .turn_options import _resolve_turn_approval_policy
    approval_params = dict(params)
    approval_thread_id = _thread_id_from_params(approval_params)
    approval_params.setdefault("approval_policy", "require")
    approval_params.setdefault("active_tier", None)
    approval_params.setdefault("tier_tools", None)
    approval_params.setdefault("allow_access_outside_workdir", False)
    state_store = context.host.runtime_state_store
    if state_store is None:
        return approval_params
    approval_state = None
    if approval_thread_id:
        approval_state = await state_store.get(approval_thread_id)
    if approval_state is None:
        approval_request_id = str(
            approval_params.get("request_id")
            or approval_params.get("requestId")
            or ""
        ).strip()
        finder = getattr(state_store, "find_pending_approval", None)
        if approval_request_id and callable(finder):
            approval_state = await finder(approval_request_id)
    if approval_state is not None and not approval_thread_id:
        approval_thread_id = str(approval_state.session_id or "").strip()
    raw_snapshot = (
        approval_state.metadata.get("runtime_snapshot")
        if approval_state is not None and isinstance(approval_state.metadata, dict)
        else None
    )
    if not approval_thread_id:
        return approval_params
    current_permissions = await _resolve_turn_approval_policy(
        context=context,
        params={"thread_id": approval_thread_id},
    )
    current_snapshot = current_permissions["runtime_snapshot"]
    approval_params["runtime_snapshot"] = overlay_runtime_permissions(
        raw_snapshot, current_snapshot
    )
    approval_params.update(overlay_runtime_permissions({}, current_snapshot))
    return approval_params


async def _turn_has_control_decision(
    context: CoreLiveContext, turn_id: str
) -> bool:
    """Whether the turn model already holds the ending of this turn.

    ``paused``/``stopping`` mean a control command owns the turn; terminal
    statuses mean it already ended. Either way a cancelled execution must not
    write a second ending.
    """
    store = getattr(context, "turn_store", None)
    if store is None or not turn_id:
        return False
    try:
        turn = await store.get_turn(turn_id)
    except BaseException:
        return False
    if turn is None:
        return False
    return str(turn.status) in {
        "paused",
        "stopping",
        "completed",
        "failed",
        "cancelled",
    }


async def _continuation_turn_is_settled(
    context: CoreLiveContext, thread_id: str
) -> bool:
    """Whether a pause/terminate/completion already owns this turn.

    A cancelled continuation must not write a second terminal over a paused or
    terminated turn; the control path is the authority for that ending.
    """
    store = context.host.runtime_state_store
    if store is None or not thread_id:
        return False
    try:
        state = await store.get(thread_id)
    except BaseException:
        return False
    return state is not None and str(getattr(state, "status", "") or "") in {
        "paused",
        "cancelled",
        "failed",
        "completed",
    }


async def _execute_continuation_job(
    *, context: CoreLiveContext, job: dict[str, Any]
) -> None:
    """Run one durable approval/question continuation.

    This is the worker half of ``approval.respond``. The RPC only persists the
    job and waits for the durable claim below; the model continuation runs
    here, so a dropped connection or a slow model no longer owns the work.
    """
    from .background import _logger
    from .interactions import _append_interaction_lifecycle_event, _interaction_for_request
    from .queue_dispatch import _dispatch_next_queue_item
    from .terminal_state import _persist_cancelled_terminal
    job_id = str(job.get("job_id") or "")
    kind = str(job.get("kind") or "")
    if kind not in {"approval.respond", "question.respond"}:
        raise RuntimeError(f"unsupported continuation job: {kind}")
    raw_payload = job.get("payload")
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    approval_params = await _approval_continuation_params(
        context=context, params=dict(payload.get("params") or {})
    )
    fallback_thread_id = str(job.get("thread_id") or "")
    fallback_run_id = str(job.get("run_id") or "")
    # A pause or terminate may have settled the turn between enqueue and
    # claim. The answer is then superseded by the resume path, which reopens
    # the card from the parked history.
    if await _continuation_turn_is_settled(context, fallback_thread_id):
        _settle_continuation_waiters(
            context,
            job_id,
            {
                "type": "accepted",
                "info": {
                    "thread_id": fallback_thread_id,
                    "run_id": fallback_run_id,
                    "turn_id": str(job.get("turn_id") or fallback_run_id),
                    "status": "superseded",
                    "snapshot": None,
                },
            },
        )
        return
    lifecycle_interaction = await _interaction_for_request(
        context,
        fallback_thread_id,
        str(
            approval_params.get("request_id")
            or approval_params.get("requestId")
            or ""
        ).strip(),
    )
    if lifecycle_interaction is not None and not lifecycle_interaction.terminal:
        marked = await context.turn_store.mark_interaction_processing(
            lifecycle_interaction.interaction_id
        )
        if marked is not None:
            lifecycle_interaction = marked
            await _append_interaction_lifecycle_event(
                context,
                lifecycle_interaction,
                state="processing",
                reason="answer_accepted",
            )
    info_holder: dict[str, Any] = {}
    lifecycle_ended = False

    async def decision_durable(info: dict[str, Any]) -> None:
        nonlocal lifecycle_ended
        thread_id = str(info.get("thread_id") or "").strip()
        run_id = str(info.get("run_id") or info.get("turn_id") or "").strip()
        # The decision is durable now: the card's job is done. The model
        # continuation that follows is a consequence, not part of the card's
        # lifecycle, so end the card here instead of waiting for the next model
        # request to finish.
        if lifecycle_interaction is not None and not lifecycle_ended:
            decision = str(info.get("decision") or "")
            card_status = (
                "cancelled"
                if decision in {"deny", "denied", "cancel"}
                else "answered"
            )
            resolved_card = await context.turn_store.resolve_interaction(
                lifecycle_interaction.interaction_id, status=card_status
            )
            card = resolved_card or await context.turn_store.get_interaction(
                lifecycle_interaction.interaction_id
            )
            if card is not None:
                await _append_interaction_lifecycle_event(
                    context,
                    card,
                    state="ending",
                    decision=decision,
                    reason="decision_durable",
                )
            lifecycle_ended = True
        # A child continuation is admitted against the CHILD session, not the
        # parent thread: it writes the child's state and only publishes onto
        # the parent's timeline, so claiming the parent would let one child's
        # answer block another child's (and a new parent turn).
        claim_thread_id = str(info.get("claim_thread_id") or "").strip() or thread_id
        task = asyncio.current_task()
        if not bool(info.get("continues", str(info.get("decision") or "") != "deny")):
            # A terminal denial keeps its short final writes inline.
            return
        if task is None or not thread_id or not run_id:
            raise RuntimeError("approval continuation identity is unavailable")
        registry = context.host.runtime_task_registry
        prior_task = registry.task(claim_thread_id, run_id=run_id)
        if prior_task is not None and prior_task is not task:
            registry.release_run(claim_thread_id, run_id=run_id)
        if not registry.accept_run(
            claim_thread_id, run_id, turn_id=str(info.get("turn_id") or "")
        ):
            raise RuntimeError("approval continuation runtime claim failed")
        if not registry.register(
            claim_thread_id, task, run_id=run_id, turn_id=str(info.get("turn_id") or "")
        ):
            registry.release_run(claim_thread_id, run_id=run_id)
            raise RuntimeError("approval continuation task registration failed")
        info_holder.update(dict(info))
        _settle_continuation_waiters(
            context, job_id, {"type": "accepted", "info": dict(info)}
        )

    try:
        result = await context.operations.execute(
            "approval.respond",
            approval_params,
            metadata={
                "source": "core_live",
                "continuation_job_id": job_id,
                "approval_decision_durable": decision_durable,
            },
        )
    except asyncio.CancelledError:
        thread_id = str(info_holder.get("thread_id") or fallback_thread_id)
        # user:“缺失身份应拒绝并记录，不从 run_id 猜 turn_id”+取消只说明这次执行
        # 被取消，不携带用户意图；要不要落终态由控制决定，这里只能用 job 自己的
        # 逻辑回合身份证伪，绝不把 run_id 塞进 turn_id 字段。
        logical_turn_id = str(
            info_holder.get("turn_id") or job.get("turn_id") or ""
        ).strip()
        settled = await _continuation_turn_is_settled(context, thread_id)
        if not settled and logical_turn_id:
            settled = await _turn_has_control_decision(context, logical_turn_id)
        if settled:
            # Pause/terminate already wrote the durable ending. Requeueing
            # this job would replay an approval the control path superseded.
            await context.turn_store.finish_job(
                job_id,
                status="cancelled",
                error="turn control superseded the continuation",
            )
        elif thread_id and logical_turn_id:
            await asyncio.shield(
                _persist_cancelled_terminal(
                    context=context,
                    thread_id=thread_id,
                    turn_id=logical_turn_id,
                )
            )
        else:
            _logger.warning(
                "[live] cancelled continuation without a logical turn job=%s thread=%s",
                job_id,
                thread_id,
            )
        _settle_continuation_waiters(
            context, job_id, {"type": "error", "error": asyncio.CancelledError()}
        )
        raise
    except BaseException as exc:
        _settle_continuation_waiters(
            context, job_id, {"type": "error", "error": exc}
        )
        raise

    payload_result = dict(result.payload or {})
    thread_id = str(
        payload_result.get("thread_id") or info_holder.get("thread_id") or fallback_thread_id
    ).strip()
    run_id = str(
        payload_result.get("run_id")
        or payload_result.get("turn_id")
        or info_holder.get("run_id")
        or fallback_run_id
    ).strip()
    decision = str(payload_result.get("decision") or info_holder.get("decision") or "")
    if (
        result.status != "ok"
        and lifecycle_interaction is not None
    ):
        current_interaction = await context.turn_store.get_interaction(
            lifecycle_interaction.interaction_id
        )
        if (
            current_interaction is not None
            and current_interaction.status == "processing"
        ):
            reverted = await context.turn_store.revert_interaction_processing(
                current_interaction.interaction_id
            )
            if reverted is not None:
                await _append_interaction_lifecycle_event(
                    context,
                    reverted,
                    state="appearing",
                    reason="answer_not_accepted",
                )
    if should_continue_goal(status=str(result.status or ""), decision=decision) and thread_id:
        await _dispatch_next_queue_item(
            context=context,
            thread_id=thread_id,
            work_root=str(info_holder.get("work_root") or ""),
            completed_turn_id=run_id,
            active_goal=payload_result.get("active_goal"),
        )
    if decision in {"deny", "denied"} and thread_id and run_id:
        context.host.runtime_task_registry.release_run(thread_id, run_id=run_id)
    _settle_continuation_waiters(
        context, job_id, {"type": "result", "result": result}
    )


async def _run_continuation_job(
    *,
    context: CoreLiveContext,
    worker: Any,
    job_id: str,
    fallback_info: dict[str, Any],
) -> None:
    try:
        handled = await worker.run_job(job_id)
    except asyncio.CancelledError:
        _settle_continuation_waiters(
            context, job_id, {"type": "error", "error": asyncio.CancelledError()}
        )
        raise
    except BaseException as exc:
        _settle_continuation_waiters(
            context, job_id, {"type": "error", "error": exc}
        )
        return
    if handled:
        return
    # Another task owns the job. If it already finished (duplicate click), do
    # not leave the caller waiting on a handler that will never run again.
    job = await context.turn_store.get_job(job_id)
    if job is None or str(job.get("status") or "") in {"completed", "failed"}:
        _settle_continuation_waiters(
            context, job_id, {"type": "accepted", "info": fallback_info}
        )
