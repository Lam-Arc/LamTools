"""Turn cancellation, forced reset and terminal cleanup."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
import contextlib
from typing import Any
from lamtools_core.event import RunItemEvent
from sqlalchemy.ext.asyncio import AsyncSession
from ..event_store import AppEventEnvelope, AppEventInput
from ..live_protocol import INVALID_REQUEST, rpc_error, rpc_result
from ..queue_state import latest_active_turn_id
from .context import CoreLiveContext, CoreLiveOperationOutcome


# user:“该修修，该重构重构，有必要就重新设计架构或者迁到 Rust”+(同一代次的重复终止共用收尾任务，避免堆积数据库等待和会话副本)。
_CANCEL_FINALIZERS: dict[tuple[Any, ...], asyncio.Task[None]] = {}


async def handle_turn_cancel_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
    terminate: bool = False,
) -> CoreLiveOperationOutcome:
    from .background import _spawn_live_background
    from .params import _expected_revision
    thread_id = str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    try:
        expected_revision = _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    requested_turn_id = str(params.get("turn_id") or params.get("turnId") or "")
    registry = context.host.runtime_task_registry
    live_turn_id = registry.active_run_id(thread_id) or ""
    active_turn = getattr(registry, "active_turn_id", None)
    logical_turn_id = (active_turn(thread_id) if callable(active_turn) else "") or live_turn_id
    if requested_turn_id and live_turn_id and requested_turn_id != logical_turn_id:
        return CoreLiveOperationOutcome(response=rpc_result(request_id, {
            "status": "stale_target", "current_turn_id": logical_turn_id, "event": None,
        }))
    generation_getter = getattr(registry, "control_generation", None)
    generation = generation_getter(thread_id) if callable(generation_getter) else None
    key = (registry, thread_id, requested_turn_id or logical_turn_id, generation, terminate)
    existing = _CANCEL_FINALIZERS.get(key)
    if existing is not None and not existing.done():
        return CoreLiveOperationOutcome(response=rpc_result(request_id, {"status": "cancelling", "event": None}))
    # Interrupt provider I/O before any persistence work.  Previously the
    # task was cancelled only after append_batch/load completed, which made
    # Stop appear inert for several seconds under write contention.
    preempted_live_task = False
    request_cancel = getattr(registry, "request_cancel", None)
    if (
        callable(request_cancel)
        and live_turn_id
        and (not requested_turn_id or requested_turn_id == logical_turn_id)
    ):
        preempted_live_task = request_cancel(
            thread_id,
            run_id=live_turn_id,
            force=True,
        )
    # Acknowledge immediately — the durable interrupting record, the watchdog
    # escalation and the claim release all settle in the background task
    # below.  Waiting inline made Stop ride behind the turn's own terminal
    # writes: on a huge session the serialized write queue held the
    # interrupt for minutes and the UI timed out (30s transport limit) while
    # the turn was in fact being torn down.
    matched_live = bool(live_turn_id) and (
        not requested_turn_id or requested_turn_id == logical_turn_id
    )
    finalizer = _spawn_live_background(
        _turn_cancel_finalizer(
            context=context,
            thread_id=thread_id,
            requested_turn_id=requested_turn_id or logical_turn_id,
            expected_revision=expected_revision,
            live_turn_id=live_turn_id,
            preempted_live_task=preempted_live_task,
            terminate=terminate,
            generation=generation,
        ),
        label="turn-cancel-finalizer",
        thread_id=thread_id,
    )
    _CANCEL_FINALIZERS[key] = finalizer

    def forget(done: asyncio.Task[None]) -> None:
        if _CANCEL_FINALIZERS.get(key) is done:
            _CANCEL_FINALIZERS.pop(key, None)

    finalizer.add_done_callback(forget)
    status = "cancelling" if matched_live else "idle"
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, {"status": status, "event": None})
    )


async def handle_turn_terminate_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Terminate the session's live work for good (the long-press action).

    Same contract as ``turn.cancel``: the turn ends terminal (``cancelled``),
    every member is interrupted with it, and nothing is offered to continue it
    later. Named separately so the desktop's long-press confirm has an explicit
    wire method instead of overloading the pause a single click sends.
    """
    return await handle_turn_cancel_operation(
        request_id=request_id, params=params, context=context, terminate=True
    )


async def _turn_cancel_finalizer(
    *,
    context: CoreLiveContext,
    thread_id: str,
    requested_turn_id: str,
    expected_revision: int | None,
    live_turn_id: str,
    preempted_live_task: bool,
    terminate: bool = False,
    generation: int | None = None,
) -> None:
    """Settle a turn interrupt off the RPC critical path.

    Idempotent: concurrent/repeated interrupts re-check inside the write
    transaction, so only the first lands the interrupting record.  A request
    naming a turn that is not the live run never touches the live task — the
    old inline flow returned idle before any registry mutation, and so does
    the finalizer.
    """
    from .interactions import _close_open_interactions
    from .runtime_tasks import _mirror_turn_status
    from .terminal_state import _persist_cancelled_terminal
    from .turn_pause import _settle_thread_continuations
    from .background import _logger
    registry = context.host.runtime_task_registry

    def owns_generation() -> bool:
        return generation is None or registry.control_generation(thread_id) == generation

    if not owns_generation():
        return
    # The handler validated the logical turn; live_turn_id identifies its
    # execution, which changes when a paused turn resumes.
    targets_live_run = bool(live_turn_id)
    task = None
    if targets_live_run:
        task_getter = getattr(registry, "task", None)
        task = task_getter(thread_id, run_id=live_turn_id) if callable(task_getter) else None
    had_live_task = bool(preempted_live_task or task is not None)
    # user:“该修修，该重构重构，有必要就重新设计架构或者迁到 Rust”+(实际停止不依赖数据库成功，每个持久化步骤失败仍继续其他清理)。
    errors: list[Exception] = []

    async def attempt(label: str, operation: Any) -> Any:
        try:
            return await operation
        except Exception as exc:
            errors.append(exc)
            _logger.exception("[live:cancel] %s failed thread_id=%s", label, thread_id)
            return None

    async def settle() -> None:
        if not owns_generation():
            return
        recorded_turn_id = await attempt("interrupting record", _append_interrupting_record(
            context=context, thread_id=thread_id, requested_turn_id=requested_turn_id,
            expected_revision=expected_revision, live_turn_id=live_turn_id,
            generation=generation,
        ))
        turn_id = recorded_turn_id or requested_turn_id
        if not owns_generation():
            return
        if turn_id and (not had_live_task or task is None or task.done()):
            await attempt("terminal state", _persist_cancelled_terminal(
                context=context, thread_id=thread_id, turn_id=turn_id,
            ))
        if not owns_generation():
            return
        await attempt("continuations", _settle_thread_continuations(
            context=context, thread_id=thread_id, reason="turn terminated", turn_id=turn_id or None,
        ))
        if not owns_generation():
            return
        await attempt("interactions", _close_open_interactions(
            context=context, thread_id=thread_id,
            reason="turn_terminated" if terminate else "turn_cancelled",
            include_member_cards=True, turn_id=turn_id or None,
        ))
        if owns_generation() and turn_id and not errors:
            await attempt("mirror status", _mirror_turn_status(
                context=context, thread_id=thread_id, turn_id=turn_id, status="cancelled",
            ))

    try:
        if not owns_generation():
            return
        member_cleanup = attempt("members", _interrupt_session_members(
            context=context, thread_id=thread_id, include_paused=terminate,
            final_status="terminated" if terminate else None,
        ))
        if task is not None and not task.done():
            await asyncio.gather(_escalate_and_wait_cancel(thread_id, task), member_cleanup)
        else:
            await member_cleanup
        # Serialize the short durable controls with start/resume. A generation
        # check after acquiring the actor prevents a late cleanup touching a
        # newly resumed execution of the same logical turn.
        actors = getattr(context.host, "session_actors", None)
        if actors is None:
            await settle()
        else:
            await actors.run(thread_id, settle)
    finally:
        if owns_generation() and targets_live_run:
            registry.cancel(thread_id, run_id=live_turn_id, force=True)
    if errors:
        raise ExceptionGroup("turn cancellation cleanup failed", errors)


async def _interrupt_session_members(
    *,
    context: CoreLiveContext,
    thread_id: str,
    include_paused: bool = False,
    final_status: str | None = None,
) -> None:
    """Interrupt every active member of a session after a user Stop.

    The supervisor owns member tasks, and only the process that owns them can
    cancel them; a session whose members live in another process keeps them
    (that process settles its own work). Failures are logged, never raised: a
    Stop must not fail because a member could not be interrupted.
    """
    from .background import _logger
    from lamtools_core.sub_agent_supervisor import find_sub_agent_supervisor

    supervisor = find_sub_agent_supervisor(thread_id)
    if supervisor is None:
        # user:“修 问题严重的话 就重新设计”+(终止也必须覆盖重启后只存在于持久记录中的成员)。
        operation = "sub_agent.terminate" if include_paused else "sub_agent.interrupt"
        if context.operations.has(operation):
            await context.operations.execute(operation, {"thread_id": thread_id})
        return
    try:
        # user:“终止不能复用可恢复的 interrupted”+会话终止与普通停止必须落
        # 不同的成员状态，Resume 才不会把用户已终止的成员拉回来（AR-02）。
        victims = await supervisor.interrupt_active(
            include_paused=include_paused,
            final_status=final_status,
        )
    except BaseException:
        _logger.exception("[live:cancel] member interruption failed thread_id=%s", thread_id)
        return
    if victims:
        _logger.info(
            "[live:cancel] interrupted %d member(s) thread_id=%s names=%s",
            len(victims),
            thread_id,
            ",".join(str(record.get("name") or "") for record in victims),
        )


async def _append_interrupting_record(
    *,
    context: CoreLiveContext,
    thread_id: str,
    requested_turn_id: str,
    expected_revision: int | None,
    live_turn_id: str,
    generation: int | None = None,
) -> str:
    """Durably record the user interrupt for the active turn and publish it.

    Returns the resolved turn id, or "" when nothing was recorded (turn
    already terminal, already recorded as interrupting, or the requested id
    does not match an active turn).

    The client revision CAS is intentionally absent here: by the time the
    background finalizer runs, the turn itself has written new revisions, so
    the request-time revision is always stale.  Idempotency comes from the
    interrupting-record check inside the transaction instead.
    """
    from .params import _is_stoppable_turn
    from .recovery import _turn_execution_id, _turn_is_terminal
    from .terminal_state import _paused_turn_id
    del expected_revision  # validated at request time only

    async def write_action(db: AsyncSession):
        loader = getattr(context.persistence, "load_metadata", context.persistence.load)
        snapshot = await loader(db, thread_id)
        if generation is not None and context.host.runtime_task_registry.control_generation(thread_id) != generation:
            return "", []
        turn_id = requested_turn_id or latest_active_turn_id(snapshot) or _paused_turn_id(snapshot) or live_turn_id
        # Fallback to the in-memory registry: when the snapshot has lost the
        # active turn (e.g. a sub-agent DB-lock error rewrote state before the
        # terminal event landed) the background task can still be running. The
        # registry is the source of truth for "is there a live task", so a
        # Stop click must still be able to target it — otherwise the user can
        # only kill the process (the 2b34c636 deadlock).
        if not turn_id:
            turn_id = context.host.runtime_task_registry.active_run_id(thread_id) or ""
        if requested_turn_id and not _is_stoppable_turn(snapshot, requested_turn_id):
            turn_id = ""
        if not turn_id:
            return "", []
        if _turn_is_terminal(snapshot, turn_id):
            return "", []
        core = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
        turns = core.get("turns") if isinstance(core.get("turns"), dict) else {}
        turn_view = turns.get(turn_id) if isinstance(turns.get(turn_id), dict) else {}
        if str(turn_view.get("status") or "") == "interrupting":
            # A previous interrupt (this one or a duplicate click) already
            # recorded the interrupting state — do not append it twice.
            return turn_id, []
        interrupted_input = AppEventInput(
            thread_id=thread_id,
            method="turn/interrupted",
            turn_id=turn_id,
            payload={"type": "turn", "reason": "user_interrupt"},
        )
        execution_id = _turn_execution_id(snapshot, turn_id)
        status_event = RunItemEvent(
            kind="status",
            thread_id=thread_id,
            event_id=f"{execution_id}:interrupting",
            run_id=execution_id,
            turn_id=turn_id,
            item_id=f"{turn_id}:interrupting",
            status="interrupting",
            payload={"type": "turn", "status": "interrupting", "raw_end_reason": "user_interrupt"},
        )
        envelopes = await context.persistence.append_batch(
            db,
            app_events=[interrupted_input],
            run_item_events=[status_event],
        )
        return turn_id, list(envelopes)

    turn_id, envelopes = await context.persistence.write(write_action)
    # Publish after the write transaction committed, matching the old inline
    # ordering so hub subscribers never observe an uncommitted record.
    for envelope in envelopes:
        await context.hub.publish(envelope)
    return turn_id


async def _escalate_and_wait_cancel(thread_id: str, task: asyncio.Task[Any]) -> None:
    """Give the cancelled turn task a short grace, then break through shields.

    The terminal persistence now runs as detached tasks, so a second
    ``task.cancel()`` can no longer strand the interrupting state — it only
    breaks the task out of an await that ignored the first cancel.
    """
    from .background import CANCEL_ESCALATION_DELAYS_SECONDS, CANCEL_FINALIZER_TASK_WAIT_CAP_SECONDS, _logger
    async def _escalate() -> None:
        for delay in CANCEL_ESCALATION_DELAYS_SECONDS:
            await asyncio.sleep(delay)
            if not task.done():
                _logger.warning(
                    "[live] turn task still running %ss after cancel; escalating thread_id=%s",
                    delay,
                    thread_id,
                )
                task.cancel()

    escalation = asyncio.create_task(_escalate())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=CANCEL_FINALIZER_TASK_WAIT_CAP_SECONDS)
    except asyncio.CancelledError:
        # Normal exit path: the turn task ends cancelled. (Also covers the
        # finalizer itself being cancelled — cleanup below still runs.)
        pass
    except asyncio.TimeoutError:
        pass
    except Exception:
        _logger.exception("[live] turn task raised during cancel unwind thread_id=%s", thread_id)
    finally:
        escalation.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await escalation
    if not task.done():
        _logger.warning(
            "[live] turn task did not exit within %ss of cancel; releasing claim anyway thread_id=%s",
            CANCEL_FINALIZER_TASK_WAIT_CAP_SECONDS,
            thread_id,
        )
        task.cancel()


async def handle_turn_force_reset_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Force a turn back to a terminal/standby state, bypassing the
    active-turn guards that make ``turn.cancel`` a no-op once recovery has
    marked the turn ``cancelled``.

    This is the escape hatch for the stuck-state where the turn is durably
    terminal but trailing ``running`` tool_call events (e.g. a half-baked
    call left by an unexpected shutdown) keep the UI believing the turn is
    active. It unconditionally closes dangling items and writes/refreshes a
    terminal turn status, then reconciles the runtime state and cancels any
    in-memory task (a safe no-op when none exists).
    """
    from .events import _append_run_item
    from .interactions import _close_open_interactions
    from .params import _expected_revision, _thread_id_from_params
    from .recovery import _latest_turn_id_any_status, _turn_is_terminal
    from .runtime_tasks import _mirror_turn_status
    from .terminal_state import _build_interrupted_tool_event, _collect_non_terminal_turn_item_ids, _persist_cancelled_runtime_state
    from .turn_pause import _settle_thread_continuations
    thread_id = _thread_id_from_params(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    try:
        expected_revision = _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    requested_turn_id = str(params.get("turn_id") or params.get("turnId") or "").strip()

    async def write(db: AsyncSession) -> tuple[list[AppEventEnvelope], dict[str, Any]]:
        snapshot = await context.persistence.load(db, thread_id)
        turn_id = requested_turn_id or _latest_turn_id_any_status(snapshot)
        if not turn_id:
            return [], snapshot
        await context.persistence.assert_revision(db, thread_id, expected_revision)
        events: list[AppEventEnvelope] = []
        # 1. Close dangling non-terminal items (half-baked tool_calls etc.)
        # before the turn-level terminal event, so the per-item cancelled
        # status is recorded in the event log rather than masked by the
        # turn-terminal projection lock.
        for item_id in _collect_non_terminal_turn_item_ids(snapshot, turn_id):
            events.append(
                await _append_run_item(
                    db,
                    context=context,
                    event=_build_interrupted_tool_event(
                        thread_id=thread_id,
                        turn_id=turn_id,
                        item_id=item_id,
                        reason="force_reset",
                        message="已中断",
                    ),
                )
            )
        # 2. Write/refresh a turn-level cancelled status (skip if already
        # terminal AND we appended no per-item events — a terminal turn with
        # no dangling items needs no new turn event).
        already_terminal = _turn_is_terminal(snapshot, turn_id)
        if not already_terminal or events:
            status_event = await _append_run_item(
                db,
                context=context,
                event=RunItemEvent(
                    kind="status",
                    thread_id=thread_id,
                    event_id=f"{turn_id}:force_reset",
                    run_id=turn_id,
                    turn_id=turn_id,
                    # Same identity as the kernel's terminal projection: a
                    # force reset refreshes the turn's single cancel row
                    # instead of stacking a second one.
                    item_id=f"{turn_id}:terminal",
                    status="cancelled",
                    payload={
                        "type": "turn",
                        "status": "cancelled",
                        "raw_end_reason": "force_reset",
                        "message": "已中断。",
                    },
                ),
            )
            events.append(status_event)
        snapshot = await context.persistence.load(db, thread_id)
        return events, snapshot

    write_result = await context.persistence.write(write)
    events, snapshot = write_result
    turn_id = requested_turn_id or _latest_turn_id_any_status(snapshot)
    if turn_id:
        await _persist_cancelled_runtime_state(context=context, thread_id=thread_id, turn_id=turn_id)
        context.host.runtime_task_registry.cancel(thread_id, run_id=turn_id or None, force=True)
        await _settle_thread_continuations(
            context=context, thread_id=thread_id, reason="turn force reset"
        )
        await _close_open_interactions(
            context=context, thread_id=thread_id, reason="turn_force_reset"
        )
    # Force reset is the strongest Stop: the session's active members stop with
    # it, including members parked on a question.
    await _interrupt_session_members(
        context=context, thread_id=thread_id, include_paused=True
    )
    await _mirror_turn_status(
        context=context,
        thread_id=thread_id,
        turn_id=turn_id,
        status="cancelled",
    )
    for event in events:
        await context.hub.publish(event)
    response_payload: dict[str, Any] = {"status": "reset", "events": [event.to_dict() for event in events]}
    if params.get("include_snapshot") is not False:
        response_payload["snapshot"] = snapshot
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, response_payload),
        publish_events=events,
    )
