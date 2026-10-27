"""Startup recovery and reconciliation of persisted turn state."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

from typing import Any
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime.memory_guard import HOST_MEMORY_EXHAUSTED, ensure_pending_memory_resume
from lamtools_core.turn.model import TERMINAL_TURN_STATUSES
from sqlalchemy.ext.asyncio import AsyncSession
from ..event_store import AppEventEnvelope
from ..queue_state import latest_active_turn_id
from .context import CoreLiveContext


async def _arm_pending_memory_resume(
    *,
    context: "CoreLiveContext",
    thread_id: str,
    state: Any,
    verdict: tuple[str, str, str] | None,
) -> bool:
    """Arm the auto resume for a turn whose recorded ending was memory exhaustion.

    Idempotent and best-effort: arming is what lets the watchdog continue the
    turn once the machine can afford it, so it must survive the restart that
    interrupted the write.
    """
    from .background import _logger
    from .terminal_state import _patch_runtime_state
    if verdict is None or verdict[1] != HOST_MEMORY_EXHAUSTED:
        return False
    store = context.runtime_state_store
    if store is None:
        return False
    try:
        if not ensure_pending_memory_resume(state):
            return False
        await _patch_runtime_state(
            store, thread_id, mutate=ensure_pending_memory_resume
        )
    except BaseException:
        _logger.exception("[live:reconcile] arming the memory resume failed thread_id=%s", thread_id)
        return False
    _logger.warning("[live:reconcile] armed the memory resume thread_id=%s", thread_id)
    return True


async def _recover_missing_approval_card(
    *, context: "CoreLiveContext", thread_id: str
) -> bool:
    """Re-emit a waiting card that never reached the event log.

    The kernel commits ``pending_approval`` and then emits the card. A crash in
    between leaves a turn that is durably waiting and can still be answered by
    ``approval.respond``, but the interface has no card. Recovery rebuilds the
    card from the recorded request payload; it never invents a second request
    for one the event log already contains.
    """
    from .background import _logger
    from .events import _append_run_item
    store = context.runtime_state_store
    if store is None or not thread_id:
        return False
    try:
        state = await store.get(thread_id)
    except BaseException:
        _logger.exception("[live:recover] runtime-state read failed thread_id=%s", thread_id)
        return False
    if state is None:
        return False
    metadata = state.metadata if isinstance(state.metadata, dict) else {}
    pending = metadata.get("pending_approval")
    if not isinstance(pending, dict) or str(pending.get("status") or "") != "waiting":
        return False
    request_id = str(pending.get("request_id") or "")
    if not request_id:
        return False
    try:
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, thread_id)
    except BaseException:
        _logger.exception("[live:recover] snapshot read failed thread_id=%s", thread_id)
        return False
    core = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
    requests = core.get("requests") if isinstance(core.get("requests"), dict) else {}
    outer_requests = snapshot.get("requests") if isinstance(snapshot.get("requests"), dict) else {}
    if request_id in requests or request_id in outer_requests:
        # The card exists (open or already answered); do not create a second
        # request identity for it.
        return False

    tool_call = pending.get("tool_call") if isinstance(pending.get("tool_call"), dict) else {}
    tool_call_id = str(tool_call.get("id") or "")
    turn_id = str(metadata.get("turn_id") or state.run_id)
    run_id = str(getattr(state, "run_id", "") or turn_id)
    payload = pending.get("request_payload") if isinstance(pending.get("request_payload"), dict) else None
    if not isinstance(payload, dict):
        waiting = metadata.get("pending_waiting_request")
        waiting = waiting if isinstance(waiting, dict) else {}
        tool_name = str(waiting.get("tool_name") or tool_call.get("name") or "")
        is_question = tool_name == "question"
        payload = {
            "request_id": request_id,
            "tool_name": tool_name,
            "arguments": waiting.get("arguments") if isinstance(waiting.get("arguments"), dict) else {},
            "request_kind": "question" if is_question else "permission",
            "message": str(
                waiting.get("message")
                or (
                    f"需要授权后才能执行工具：{tool_name}"
                    if tool_name
                    else "等待用户确认"
                )
            ),
            "metadata": dict(waiting.get("metadata") or {}),
            "options": (
                [
                    {"id": "option-confirm", "label": "确认并继续", "description": "确认继续", "response": "确认并继续"},
                    {"id": "option-skip", "label": "跳过问题", "description": "不回答，按合理默认继续", "response": "（用户跳过了这个问题，未提供回答。）"},
                ]
                if is_question
                else [
                    {"id": "approve", "label": "批准执行", "description": "允许后端继续执行这个工具调用。", "response": "approve"},
                    {"id": "deny", "label": "拒绝执行", "description": "不执行这个工具调用，本轮停在等待点。", "response": "deny"},
                ]
            ),
        }
    event = RunItemEvent(
        kind="approval_request",
        thread_id=thread_id,
        event_id=f"{request_id}:recovered",
        run_id=run_id,
        turn_id=turn_id,
        item_id=f"{thread_id}:{run_id}:{tool_call_id}:tool",
        status="waiting",
        payload={
            "type": "serverRequest",
            "request_id": request_id,
            "kind": str(payload.get("request_kind") or "permission"),
            "message": str(payload.get("message") or ""),
            "tool_name": str(payload.get("tool_name") or tool_call.get("name") or ""),
            "options": payload.get("options") if isinstance(payload.get("options"), list) else [],
            "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            **({"context": str(payload.get("context"))} if payload.get("context") else {}),
        },
    )

    async def write(db: AsyncSession):
        return await _append_run_item(db, context=context, event=event)

    try:
        appended = await context.persistence.write(write)
    except BaseException:
        _logger.exception("[live:recover] could not rebuild the approval card thread_id=%s", thread_id)
        return False
    try:
        await context.hub.publish(appended)
    except BaseException:
        pass
    _logger.warning(
        "[live:recover] rebuilt a missing approval card thread_id=%s request_id=%s",
        thread_id,
        request_id,
    )
    return True


async def recover_stale_active_turns(*, context: "CoreLiveContext") -> int:
    """Startup reaper mirroring ``ArrangeJobStore.recover_running``.

    An unexpected shutdown can leave a turn durably marked ``running`` /
    ``waiting`` / ``interrupting`` in the snapshot (the ``turn/accepted`` +
    ``running`` events commit before any terminal status is written). On
    restart the in-memory registry is empty, so the durable-snapshot guard in
    ``handle_turn_start_operation`` blocks every subsequent ``turn.start`` on
    that thread with "active turn already exists". This writes a ``cancelled``
    terminal run-item for every leftover active turn and reconciles the
    runtime state, unblocking the thread. Best-effort: never raises.

    A turn parked on a user decision (tool approval / question) is exempt: its
    approval is durable and ``approval.respond`` can still resume it, so the
    user can answer it after the restart. Reaping that turn wrote a cancelled
    terminal over the request the user was about to answer, which is how
    closing Sunday mid-approval lost the approval entirely (2026-10-01).

    ``reconcile_terminal_turns`` runs after this and repairs the turns whose
    runtime state already recorded *why* they ended.
    """
    from .background import _logger
    from .continuations import _pending_approval_record
    from .interactions import _cancel_superseded_interactions, _close_open_interactions
    from .terminal_state import _active_thread_ids, _close_active_turns, _persist_cancelled_runtime_state, _terminal_verdict
    recovered = 0
    for thread_id in await _active_thread_ids(context=context):
        # Upgrade path: derive the new turn/interaction read models from the
        # snapshot an older build already persisted. Idempotent and best-effort;
        # a failure here must not block the reaper.
        try:
            async with context.session_factory() as db:
                upgrade_snapshot = await context.persistence.load(db, thread_id)
            from lamtools_core.turn.migrate import backfill_snapshot

            await backfill_snapshot(context.turn_store, thread_id, upgrade_snapshot)
            project_id = ""
            try:
                session = (
                    upgrade_snapshot.get("session")
                    if isinstance(upgrade_snapshot, dict)
                    else None
                )
                metadata = (
                    session.get("metadata")
                    if isinstance(session, dict)
                    and isinstance(session.get("metadata"), dict)
                    else {}
                )
                project_id = str(metadata.get("project_id") or "")
            except BaseException:
                project_id = ""
            await context.turn_store.backfill_interaction_pool(
                thread_id, project_id=project_id
            )
        except BaseException:
            _logger.exception(
                "[live:recover] turn read-model backfill failed thread_id=%s", thread_id
            )
        paused_state = None
        try:
            if context.runtime_state_store is not None:
                paused_state = await context.runtime_state_store.get(thread_id)
        except BaseException:
            paused_state = None
        if paused_state is not None and str(
            getattr(paused_state, "status", "") or ""
        ) == "paused":
            # A paused turn keeps its place, but its cards do not: resume
            # re-asks, and an old open card otherwise appeared as a queued
            # backup behind the new question.
            await _close_open_interactions(
                context=context, thread_id=thread_id, reason="turn_paused_restart"
            )
            _logger.info(
                "[live:recover] closed paused turn cards thread_id=%s", thread_id
            )
            continue
        if paused_state is not None:
            pending = _pending_approval_record(paused_state)
            if pending is not None:
                pending_call = (
                    pending.get("tool_call")
                    if isinstance(pending.get("tool_call"), dict)
                    else {}
                )
                await _cancel_superseded_interactions(
                    context,
                    thread_id,
                    keep_request_id=str(pending.get("request_id") or ""),
                    keep_tool_call_id=str(pending_call.get("id") or ""),
                    reason="superseded_restart",
                )
        if await _active_turn_awaits_user_decision(context=context, thread_id=thread_id):
            # The request is answerable, but the process may have died between
            # the checkpoint and the card event. Rebuild the card before the
            # user sees a waiting turn with nothing to click.
            await _recover_missing_approval_card(context=context, thread_id=thread_id)
            _logger.info(
                "[live:recover] keeping thread_id=%s parked on a user decision", thread_id
            )
            continue
        try:
            if await context.turn_store.has_pending_jobs(thread_id):
                # A durable continuation was accepted and has not finished.
                # Reaping the turn here would race the worker that is about to
                # write its terminal status.
                _logger.info(
                    "[live:recover] keeping thread_id=%s owned by a continuation job",
                    thread_id,
                )
                continue
        except BaseException:
            _logger.exception(
                "[live:recover] continuation job lookup failed thread_id=%s", thread_id
            )

        # Ask the durable state first. When the runtime already recorded why the
        # turn ended (a memory exhaustion, for instance) that reason is the
        # truth; stamping the generic "unexpected shutdown" over it buried the
        # cause AND swallowed the auto resume — the interrupted PV session was
        # closed as an anonymous cancellation that way (2026-10-10).
        store = context.runtime_state_store
        state = None
        try:
            if store is not None:
                state = await store.get(thread_id)
        except BaseException:
            _logger.exception("[live:recover] runtime-state read failed thread_id=%s", thread_id)
            continue
        from lamtools_core.runtime_owner import LIVE_RUN_STATES, owner_is_live, read_owner
        if (state is not None and state.status in LIVE_RUN_STATES
                and owner_is_live(read_owner(state.metadata))):
            _logger.info("[live:recover] keeping thread_id=%s owned by a live process", thread_id)
            continue
        state_verdict = _terminal_verdict(state) if state is not None else None
        recorded_run_id = str(state.metadata.get("turn_id") or state.run_id or "") if state is not None else ""
        fallback_verdict = ("cancelled", "unexpected_shutdown", "已中断。")
        from_record = False

        def _verdict_for(active: str, _snapshot: dict[str, Any]) -> tuple[str, str, str] | None:
            nonlocal from_record
            if state_verdict is not None and (not recorded_run_id or active == recorded_run_id):
                from_record = True
                return state_verdict
            return fallback_verdict

        async def write(
            db: AsyncSession, *, thread_id: str = thread_id
        ) -> list[tuple[str, AppEventEnvelope]]:
            return await _close_active_turns(
                db,
                context=context,
                thread_id=thread_id,
                verdict_for=_verdict_for,
            )

        try:
            items = await context.persistence.write(write)
        except BaseException:
            _logger.exception("[live:recover] failed thread_id=%s", thread_id)
            continue
        if state_verdict is not None and state is not None:
            await _arm_pending_memory_resume(
                context=context, thread_id=thread_id, state=state, verdict=state_verdict
            )
        for turn_id, event in items:
            if not from_record:
                # Only a turn we closed ourselves needs the state reconciled to
                # "cancelled"; a verdict that came from the state must not be
                # overwritten by the very cleanup that reads it.
                try:
                    await _persist_cancelled_runtime_state(
                        context=context, thread_id=thread_id, turn_id=turn_id, reason="unexpected_shutdown"
                    )
                except BaseException:
                    _logger.exception(
                        "[live:recover] runtime-state reconcile failed thread_id=%s turn_id=%s",
                        thread_id, turn_id,
                    )
            try:
                await context.hub.publish(event)
            except BaseException:
                pass
        recovered += len(items)
    if recovered:
        _logger.info(
            "[live:recover] recovered %d stale active turn(s) after unexpected shutdown",
            recovered,
        )
    return recovered


async def reconcile_terminal_turns(*, context: "CoreLiveContext") -> int:
    """Close turns the runtime already ended but the snapshot still calls active.

    The runtime writes its terminal state (``failed`` / ``cancelled``) before it
    writes the terminal event, so anything that stops it in between leaves the
    durable state terminal and the snapshot ``running`` forever: the session
    keeps showing a spinner and a half-finished tool row, no error is ever
    shown, and the pending guidance is never handed back. A host-memory crash
    during that write is the usual cause (2026-10-10), and nothing repaired it
    short of the next restart.

    Only states the runtime itself declared terminal are reconciled — never a
    guess based on how long a turn has been quiet, which would kill legitimate
    long tools (a 25-minute video generation looks identical from the outside).
    Best-effort: never raises.
    """
    from .background import _logger
    from .terminal_state import _active_thread_ids, _close_active_turns, _terminal_verdict
    store = context.runtime_state_store
    if store is None:
        return 0
    registry = context.runtime_task_registry
    reconciled = 0
    for thread_id in await _active_thread_ids(context=context):
        try:
            if registry is not None and registry.is_running(thread_id):
                continue  # a live turn owns this thread and will write its own ending
            state = await store.get(thread_id)
            if state is None:
                continue
            verdict = _terminal_verdict(state)
            if verdict is None:
                continue
            await _arm_pending_memory_resume(
                context=context, thread_id=thread_id, state=state, verdict=verdict
            )

            async def write(
                db: AsyncSession,
                *,
                thread_id: str = thread_id,
                verdict: tuple[str, str, str] = verdict,
                expected_run_id: str = str(state.metadata.get("turn_id") or state.run_id or ""),
            ) -> list[tuple[str, AppEventEnvelope]]:
                return await _close_active_turns(
                    db,
                    context=context,
                    thread_id=thread_id,
                    verdict_for=lambda active, _snapshot: (
                        None if expected_run_id and active != expected_run_id else verdict
                    ),
                )

            items = await context.persistence.write(write)
        except BaseException:
            _logger.exception("[live:reconcile] failed thread_id=%s", thread_id)
            continue
        for _turn_id, event in items:
            try:
                await context.hub.publish(event)
            except BaseException:
                pass
        if items:
            reconciled += len(items)
            _logger.warning(
                "[live:reconcile] closed %d item(s) of an already-terminal turn thread_id=%s reason=%s",
                len(items), thread_id, verdict[1],
            )
    return reconciled


async def _active_turn_awaits_user_decision(*, context: "CoreLiveContext", thread_id: str) -> bool:
    """Whether the thread's active turn is durably waiting for the user.

    Only a turn whose runtime state still holds a *resumable* pending approval
    qualifies — that is exactly what ``approval.respond`` continues from. Every
    other leftover (a turn stuck mid-execution, a wait with no answerable
    request, or one whose approval is already past the point of no return)
    stays a crash leftover for the reaper.
    """
    from .background import _logger
    store = context.runtime_state_store
    if store is None:
        return False
    try:
        state = await store.get(thread_id)
    except BaseException:
        _logger.exception("[live:recover] runtime-state read failed thread_id=%s", thread_id)
        return False
    if state is None or str(getattr(state, "loop_state", "") or "") != "wait":
        return False
    metadata = state.metadata if isinstance(getattr(state, "metadata", None), dict) else {}
    # ``state.run_id`` is the execution attempt, not the logical turn.  A
    # resumed turn keeps its turn id but receives a fresh run id, so comparing
    # the snapshot's turn id against run_id lost every resumed decision on the
    # next restart.
    recorded_turn_id = str(metadata.get("turn_id") or getattr(state, "run_id", "") or "")
    if not recorded_turn_id:
        return False
    pending = metadata.get("pending_approval")
    if not isinstance(pending, dict):
        return False
    if not isinstance(pending.get("tool_call"), dict):
        return False
    # "executing" means the decision was already recorded durably and only the
    # continuation was cut short. approval.respond refuses that state, so
    # keeping it would block the thread with nothing the user could answer.
    if str(pending.get("status") or "waiting") != "waiting":
        return False
    try:
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, thread_id)
    except BaseException:
        _logger.exception("[live:recover] snapshot read failed thread_id=%s", thread_id)
        return False
    return latest_active_turn_id(snapshot) == recorded_turn_id


def _turn_execution_id(snapshot: dict[str, Any], turn_id: str) -> str:
    turn = (snapshot.get("turns") or {}).get(turn_id) or {}
    core_turn = ((snapshot.get("core") or {}).get("turns") or {}).get(turn_id) or {}
    return str(turn.get("run_id") or core_turn.get("run_id") or turn_id)


def _turn_is_terminal(snapshot: dict[str, Any], turn_id: str) -> bool:
    core = snapshot.get("core")
    core_turns = core.get("turns") if isinstance(core, dict) else None
    core_turn = core_turns.get(turn_id) if isinstance(core_turns, dict) else None
    if isinstance(core_turn, dict) and str(core_turn.get("status") or "") in TERMINAL_TURN_STATUSES:
        return True
    turns = snapshot.get("turns")
    turn = turns.get(turn_id) if isinstance(turns, dict) else None
    return isinstance(turn, dict) and str(turn.get("status") or "") in TERMINAL_TURN_STATUSES


def _latest_turn_id_any_status(snapshot: dict[str, Any]) -> str:
    """Return the most recently created turn id, regardless of status.

    Unlike ``latest_active_turn_id`` this ignores the active-status guard —
    ``turn.force_reset`` must reach a turn even after recovery has marked it
    ``cancelled`` (the exact stuck-state where ``turn.cancel`` no-ops).
    """
    from ..queue_state import _merged_turns  # local import to avoid cycle
    turns = _merged_turns(snapshot)
    best_id = ""
    best_seq = -1
    for turn_id, turn in turns.items():
        if not isinstance(turn, dict):
            continue
        seq = int(turn.get("last_seq") or 0)
        if seq > best_seq:
            best_seq = seq
            best_id = str(turn.get("turn_id") or turn_id)
    return best_id
