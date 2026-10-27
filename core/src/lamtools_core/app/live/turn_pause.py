"""Resumable pause control and settlement of paused sessions."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import uuid
from dataclasses import dataclass
from typing import Any
from lamtools_core.event import RunItemEvent
from sqlalchemy.ext.asyncio import AsyncSession
from ..live_protocol import INVALID_REQUEST, rpc_error, rpc_result
from ..queue_state import latest_active_turn_id
from .context import CoreLiveContext, CoreLiveOperationOutcome


@dataclass(frozen=True)
class _PauseTarget:
    # user:“修 问题严重的话 就重新设计”+(控制目标固定回合、执行和代次，任何异步收尾都不得重新猜目标)。
    turn_id: str
    registry_run_id: str
    runtime_run_id: str
    generation: int
    members_only: bool = False

    def owns_registry(self, context: CoreLiveContext, thread_id: str) -> bool:
        registry = context.host.runtime_task_registry
        return registry.control_generation(thread_id) == self.generation

    def owns_state(self, state: Any) -> bool:
        return bool(state is None or (
            str(state.metadata.get("turn_id") or state.run_id) == self.turn_id
            and (not self.runtime_run_id or state.run_id == self.runtime_run_id)
        ))


async def _pause_target_current(context: CoreLiveContext, thread_id: str, target: _PauseTarget) -> bool:
    if not target.owns_registry(context, thread_id):
        return False
    state = await context.runtime_state_store.get(thread_id) if context.runtime_state_store else None
    return target.owns_registry(context, thread_id) and target.owns_state(state) and (
        target.members_only or state is None or state.status not in {"completed", "failed", "cancelled"}
    )


async def handle_turn_pause_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Pause the session's live turn instead of stopping it.

    A pause keeps the turn's place: the step it cut leaves no half-written
    answer, the tools that already produced a result stay, and the durable state
    becomes ``paused`` so ``turn.resume`` continues the same turn from the
    committed history. Members are parked the same way, and a member waiting on
    a question keeps its card, that answer is still the user's to give.
    """
    from .background import _logger, _spawn_live_background
    from .params import _expected_revision, _thread_id_from_params
    from .recovery import _latest_turn_id_any_status
    from .terminal_state import _paused_turn_id
    thread_id = _thread_id_from_params(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    try:
        _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    reason = str(params.get("reason") or params.get("pause_reason") or "user_pause").strip() or "user_pause"
    registry = context.host.runtime_task_registry
    requested_turn_id = str(params.get("turn_id") or params.get("turnId") or "").strip()
    live_turn_id = registry.active_run_id(thread_id) or ""
    # user:“旧回合的暂停不能取消当前新执行”+请求点名的回合若不是这条执行的回合，
    # 只回报现状，不下发暂停也不取消任务：控制动作必须绑定它自己的目标。
    active_turn_id = getattr(registry, "active_turn_id", None)
    live_logical_turn = active_turn_id(thread_id) if callable(active_turn_id) else ""
    if requested_turn_id and live_turn_id and requested_turn_id != live_logical_turn:
        _logger.info(
            "[live:pause] stale target ignored thread_id=%s requested=%s live_turn=%s live_run=%s",
            thread_id,
            requested_turn_id,
            live_logical_turn,
            live_turn_id,
        )
        return CoreLiveOperationOutcome(
            response=rpc_result(request_id, {
                "status": "stale_target",
                "requested_turn_id": requested_turn_id,
                "current_turn_id": live_logical_turn,
                "event": None,
            })
        )
    generation = registry.control_generation(thread_id)
    logical_turn_id = live_logical_turn or requested_turn_id
    if not logical_turn_id:
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, thread_id)
        logical_turn_id = latest_active_turn_id(snapshot) or _paused_turn_id(snapshot) or _latest_turn_id_any_status(snapshot) or ""
    if not logical_turn_id:
        return CoreLiveOperationOutcome(response=rpc_result(request_id, {"status": "idle", "event": None}))
    state = await context.runtime_state_store.get(thread_id) if context.runtime_state_store else None
    target = _PauseTarget(
        turn_id=logical_turn_id, registry_run_id=live_turn_id,
        runtime_run_id=state.run_id if state is not None and str(state.metadata.get("turn_id") or state.run_id) == logical_turn_id else "",
        generation=generation,
        members_only=not live_turn_id and state is not None and state.status in {"completed", "failed", "cancelled"},
    )
    if not await _pause_target_current(context, thread_id, target):
        return CoreLiveOperationOutcome(response=rpc_result(request_id, {"status": "stale_target", "event": None}))
    request_pause = getattr(registry, "request_pause", None)
    if callable(request_pause) and live_turn_id:
        # ``force`` aborts a tool that never checks the pause event; the kernel
        # tells that teardown apart from a cancel and still parks the turn.
        request_pause(
            thread_id,
            run_id=live_turn_id,
            turn_id=requested_turn_id or None,
            force=True,
            reason=reason,
        )
    elif callable(getattr(registry, "get_pause_event", None)):
        # No live task: members may still be working, and a pause must stop them
        # too. Setting the event covers the kernels that pick it up later.
        registry.get_pause_event(thread_id).set()
    _spawn_live_background(
        _turn_pause_finalizer(
            context=context,
            thread_id=thread_id,
            target=target,
            reason=reason,
        ),
        label="turn-pause-finalizer",
        thread_id=thread_id,
    )
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, {"status": "pausing" if live_turn_id else "paused", "event": None})
    )


async def _settle_thread_continuations(
    *, context: CoreLiveContext, thread_id: str, reason: str, turn_id: str | None = None
) -> None:
    """Close pending continuation jobs when a control action owns the turn.

    A pause is resumed from the parked runtime state, not by replaying the
    approval job. A terminate never resumes at all. Leaving either job
    ``pending`` would make startup recovery re-run a superseded decision.
    """
    from .background import _logger
    if not thread_id:
        return
    try:
        await context.turn_store.settle_thread_jobs(
            thread_id, status="cancelled", error=reason, turn_id=turn_id
        )
    except BaseException:
        _logger.exception(
            "[live] failed to settle continuation jobs thread_id=%s", thread_id
        )


async def _turn_pause_finalizer(
    *, context: CoreLiveContext, thread_id: str, target: _PauseTarget, reason: str,
) -> None:
    from .interactions import _close_open_interactions
    from .runtime_tasks import _mirror_turn_status
    from .turn_cancel import _escalate_and_wait_cancel
    registry = context.host.runtime_task_registry
    if target.members_only:
        if await _pause_target_current(context, thread_id, target):
            await _pause_session_members(context=context, thread_id=thread_id, reason=reason, target=target)
        return
    task = registry.task(thread_id, run_id=target.registry_run_id) if target.registry_run_id else None
    if task is not None and not task.done():
        await _escalate_and_wait_cancel(thread_id, task)

    async def settle() -> None:
        # user:“修 问题严重的话 就重新设计”+(短控制提交与新建/恢复/终止串行，所有写入固定到同一目标)。
        if not await _pause_target_current(context, thread_id, target):
            return
        await _settle_paused_runtime_state(context=context, thread_id=thread_id, reason=reason, target=target)
        if not await _pause_target_current(context, thread_id, target):
            return
        await _settle_thread_continuations(context=context, thread_id=thread_id,
            reason=f"turn paused: {reason}", turn_id=target.turn_id)
        await _close_open_interactions(context=context, thread_id=thread_id,
            reason="turn_paused", turn_id=target.turn_id)
        await _ensure_paused_status(context=context, thread_id=thread_id,
            live_turn_id=target.turn_id, reason=reason, target=target)
        if await _pause_target_current(context, thread_id, target):
            await _mirror_turn_status(context=context, thread_id=thread_id,
                turn_id=target.turn_id, status="paused")

    await context.session_actors.run(thread_id, settle)
    if await _pause_target_current(context, thread_id, target):
        await _pause_session_members(context=context, thread_id=thread_id, reason=reason, target=target)


async def _settle_paused_runtime_state(
    *, context: CoreLiveContext, thread_id: str, reason: str, target: _PauseTarget
) -> None:
    """Move the thread's runtime state to ``paused`` unless it already ended.

    Idempotent and conservative: a state the runtime already declared terminal
    is never rewritten, so a pause racing a completion cannot revive a turn that
    finished on its own.
    """
    from .background import _logger
    from .terminal_state import _patch_runtime_state
    store = context.runtime_state_store
    if store is None or not thread_id:
        return

    def _mutate(state: Any) -> None:
        if not target.owns_registry(context, thread_id) or not target.owns_state(state):
            return
        status = str(getattr(state, "status", "") or "")
        if status in {"completed", "failed", "cancelled"}:
            return
        if status != "paused":
            state.status = "paused"
            state.loop_state = "paused"
        if not isinstance(getattr(state, "metadata", None), dict):
            state.metadata = {}
        state.metadata["pause_reason"] = reason
        # The card was closed by the pause; leaving the durable request behind
        # let a stale client (or the five-minute auto-continue) answer a turn
        # the user had already parked, silently reviving it.
        state.metadata.pop("pending_approval", None)
        state.metadata.pop("pending_waiting_request", None)

    try:
        await _patch_runtime_state(store, thread_id, mutate=_mutate)
    except BaseException:
        _logger.exception("[live:pause] failed to settle the runtime state thread_id=%s", thread_id)


async def _ensure_paused_status(
    *,
    context: CoreLiveContext,
    thread_id: str,
    live_turn_id: str,
    reason: str,
    target: _PauseTarget,
) -> None:
    """Close the paused turn's dangling step and make sure it reads ``paused``.

    Two writes, both idempotent: a terminal ``tool_result`` per tool row the
    pause cut, so the transcript shows an interrupted step instead of a row that
    spins forever, then the paused status item itself. That second write is a
    no-op when the kernel already wrote it, and the only writer when no live task
    existed to park.
    """
    from .events import _append_run_item
    from .recovery import _turn_is_terminal
    from .terminal_state import _build_interrupted_tool_event, _collect_non_terminal_turn_item_ids, _paused_turn_id
    async with context.session_factory() as session:
        snapshot = await context.persistence.load(session, thread_id)
    core = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
    turns = core.get("turns") if isinstance(core.get("turns"), dict) else {}
    # A repeat pause finds the turn already paused, which is not an "active"
    # turn: without the paused fallback the second press resolves no turn at all
    # and writes nothing, so the live client never learns about it.
    turn_id = live_turn_id or latest_active_turn_id(snapshot) or _paused_turn_id(snapshot) or ""
    if not turn_id or _turn_is_terminal(snapshot, turn_id):
        return

    async def write(db: AsyncSession):
        appended = []
        current = await context.persistence.load(db, thread_id)
        known = {**(current.get("turns") or {}), **((current.get("core") or {}).get("turns") or {})}
        if not target.owns_registry(context, thread_id) or turn_id not in known or _turn_is_terminal(current, turn_id):
            return []
        current_core = current.get("core") if isinstance(current.get("core"), dict) else {}
        current_items = current_core.get("items") if isinstance(current_core.get("items"), dict) else {}
        for item_id in _collect_non_terminal_turn_item_ids(current, turn_id, skip_child_items=True):
            existing_item = current_items.get(item_id) if isinstance(current_items.get(item_id), dict) else {}
            existing_payload = (
                existing_item.get("payload")
                if isinstance(existing_item.get("payload"), dict)
                else {}
            )
            original = str(
                existing_payload.get("message")
                or existing_payload.get("content")
                or existing_item.get("content")
                or ""
            ).strip()
            # The pause cuts the step, but the user must still be able to read
            # what was being asked. The card becomes a cancelled row, and that
            # row now carries the original question instead of a generic note.
            message = (
                f"已暂停：{original}"
                if original
                else "已暂停，未完成的步骤会在继续后重新执行。"
            )
            appended.append(
                await _append_run_item(
                    db,
                    context=context,
                    event=_build_interrupted_tool_event(
                        thread_id=thread_id,
                        turn_id=turn_id,
                        item_id=item_id,
                        reason="user_pause",
                        message=message,
                    ),
                )
            )
        # Always written. This write is also the projection for the paused turn:
        # nothing else projects it, because a paused turn is not terminal and the
        # streaming path deliberately keeps the snapshot out of its hot loop. A
        # skipped write therefore left the transcript ending at the previous
        # 已中断 row, with no paused row for a reload to serve (2026-10-14).
        appended.append(
            await _append_run_item(
                db,
                context=context,
                event=_build_paused_status_event(
                    snapshot, thread_id=thread_id, turn_id=turn_id, reason=reason,
                    execution_id=target.runtime_run_id or None,
                ),
            )
        )
        return appended

    published = await context.persistence.write(write)
    for event in published:
        try:
            await context.hub.publish(event)
        except BaseException:
            pass


def _build_paused_status_event(
    snapshot: dict[str, Any],
    *,
    thread_id: str,
    turn_id: str,
    reason: str,
    execution_id: str | None = None,
) -> RunItemEvent:
    """Status item that moves a turn to ``paused`` without ending it."""
    from .recovery import _turn_execution_id
    execution_id = execution_id or _turn_execution_id(snapshot, turn_id)
    return RunItemEvent(
        kind="status",
        thread_id=thread_id,
        # A fresh event id per pause, a stable item id. Pausing the same turn
        # twice (pause, continue, pause) otherwise reuses the identity of the
        # first pause: the live client drops the repeat as already seen, the
        # button never leaves the state of the previous run, and only a reload
        # shows the truth (2026-10-14). The item id stays stable so the row is
        # replaced instead of stacking.
        event_id=f"{execution_id}:paused:{uuid.uuid4().hex[:8]}",
        run_id=execution_id,
        turn_id=turn_id,
        item_id=f"{turn_id}:paused:{execution_id}",
        status="paused",
        payload={
            "type": "turn",
            "status": "paused",
            "raw_end_reason": "user_pause",
            "pause_reason": reason,
            "message": "已暂停。",
        },
    )


async def _resume_session_members(*, context: CoreLiveContext, thread_id: str) -> None:
    """Continue the members a pause parked, after the turn itself resumed."""
    from .background import _logger
    from .turn_options import _resolve_turn_approval_policy
    from lamtools_core.sub_agent_supervisor import find_sub_agent_supervisor

    supervisor = find_sub_agent_supervisor(thread_id)
    if supervisor is None:
        # user:“修 问题严重的话 就重新设计”+(重启后通过执行器工厂重建，不能把投影器当成运行器)。
        if context.operations.has("sub_agent.resume"):
            resolved = await _resolve_turn_approval_policy(context=context, params={"thread_id": thread_id, "origin": "member_resume"})
            result = await context.operations.execute("sub_agent.resume", {
                "thread_id": thread_id, "suspended_only": True,
                "runtime_snapshot": resolved["runtime_snapshot"], "work_root": resolved.get("work_root"),
            })
            if result.status != "ok":
                _logger.warning("[live:resume] member reconstruction failed thread_id=%s", thread_id)
        return
    resume_suspended = getattr(supervisor, "resume_suspended", None)
    if not callable(resume_suspended):
        return
    try:
        resumed = await resume_suspended()
    except BaseException:
        _logger.exception("[live:resume] failed to continue members thread_id=%s", thread_id)
        return
    if resumed:
        _logger.info(
            "[live:resume] continued %d member(s) thread_id=%s", len(resumed), thread_id
        )


async def _pause_session_members(*, context: CoreLiveContext, thread_id: str, reason: str, target: _PauseTarget | None = None) -> None:
    """Park every active member of a paused session.

    Members waiting on an unanswered question are left alone: their card is
    still the user's, and the answer queues until the session continues.
    Failures are logged, never raised, because a pause must not fail just
    because a member could not be parked.
    """
    from .background import _logger
    from lamtools_core.sub_agent_supervisor import find_sub_agent_supervisor

    supervisor = find_sub_agent_supervisor(thread_id)
    control_guard = (lambda: target.owns_registry(context, thread_id)) if target is not None else None
    if supervisor is None:
        if context.operations.has("sub_agent.pause"):
            await context.operations.execute("sub_agent.pause", {"thread_id": thread_id}, metadata={"control_guard": control_guard})
        return
    pause_active = getattr(supervisor, "pause_active", None)
    if not callable(pause_active):
        return
    try:
        parked = await pause_active(control_guard=control_guard)
    except BaseException:
        _logger.exception("[live:pause] failed to park members thread_id=%s", thread_id)
        return
    if parked:
        _logger.info(
            "[live:pause] parked %d member(s) thread_id=%s reason=%s",
            len(parked),
            thread_id,
            reason,
        )
