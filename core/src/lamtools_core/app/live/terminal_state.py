"""Terminal state responsibilities."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

from collections.abc import Callable
from typing import Any
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import RuntimeState, RuntimeStateConflictError, RuntimeStateStore
from lamtools_core.runtime.memory_guard import (
    HOST_MEMORY_EXHAUSTED,
    memory_exhausted_message_for,
    state_is_memory_exhaustion,
)
from lamtools_core.snapshot import is_sub_agent_child_item
from lamtools_core.turn.model import TERMINAL_TURN_STATUSES
from sqlalchemy.ext.asyncio import AsyncSession
from ..event_store import AppEventEnvelope
from ..queue_state import latest_active_turn_id
from ..turn_acceptance import build_cancelled_turn_event
from .context import CoreLiveContext


def _paused_turn_id(snapshot: dict[str, Any]) -> str:
    """The turn a session is currently paused on, if any.

    A paused turn is not "active" (nothing is executing), but it still owns the
    session: the next user input continues it instead of starting a new turn.
    """
    core = snapshot.get("core") if isinstance(snapshot, dict) else None
    turns = core.get("turns") if isinstance(core, dict) else None
    if not isinstance(turns, dict):
        return ""
    for turn_id, turn in turns.items():
        if isinstance(turn, dict) and str(turn.get("status") or "") == "paused":
            return str(turn_id)
    return ""


def _collect_non_terminal_turn_item_ids(
    snapshot: dict[str, Any], turn_id: str, *, skip_child_items: bool = False
) -> list[str]:
    """Return item_ids under ``turn_id`` whose status is not terminal.

    Used by the crash-recovery and force-reset paths to find dangling
    tool_call / tool_result / message items left ``running`` / ``waiting``
    when the process died mid-turn. The snapshot projection closes these
    in-memory (``_close_turn_items``) once the turn itself flips terminal,
    but the *event log* retains the orphaned running events — this collects
    them so a terminal ``tool_result`` event can be appended per item,
    making the event stream self-consistent for replay.
    """
    core = snapshot.get("core") if isinstance(snapshot, dict) else None
    if not isinstance(core, dict):
        return []
    turns = core.get("turns") if isinstance(core.get("turns"), dict) else {}
    turn = turns.get(turn_id)
    if not isinstance(turn, dict):
        return []
    items = core.get("items") if isinstance(core.get("items"), dict) else {}
    result: list[str] = []
    for item_id in turn.get("items") or []:
        item = items.get(item_id)
        if not isinstance(item, dict):
            continue
        if skip_child_items and is_sub_agent_child_item(item):
            # A member's timeline outlives the parent turn, exactly as the
            # terminal path already assumes: its waiting question belongs to the
            # user, so a pause must not close it (2026-10-14).
            continue
        if str(item.get("status") or "") not in TERMINAL_TURN_STATUSES:
            result.append(item_id)
    return result


def _build_interrupted_tool_event(
    *,
    thread_id: str,
    turn_id: str,
    item_id: str,
    reason: str = "unexpected_shutdown",
    message: str = "已中断",
) -> RunItemEvent:
    """Build a terminal ``tool_result`` event that closes a dangling tool_call.

    Shares the target item_id so projection (last-write-wins by item_id)
    flips that tool_call item to ``cancelled``. Use ``kind="tool_result"``
    (not ``status``) so the snapshot marks the *item* terminal rather than
    being treated as a turn-status event.
    """
    return RunItemEvent(
        kind="tool_result",
        thread_id=thread_id,
        event_id=f"{item_id}:{reason}",
        run_id=turn_id,
        turn_id=turn_id,
        item_id=item_id,
        status="cancelled",
        payload={
            "type": "dynamicToolCall",
            "status": "cancelled",
            "raw_end_reason": reason,
            "message": message,
        },
    )


async def _persist_cancelled_terminal(
    *,
    context: CoreLiveContext,
    thread_id: str,
    turn_id: str,
) -> AppEventEnvelope | None:
    from .background import _logger
    from .events import _append_run_item
    from .recovery import _turn_execution_id, _turn_is_terminal
    await _persist_cancelled_runtime_state(context=context, thread_id=thread_id, turn_id=turn_id)

    async def write(db: AsyncSession) -> AppEventEnvelope | None:
        snapshot = await context.persistence.load(db, thread_id)
        if _turn_is_terminal(snapshot, turn_id):
            return None
        # user:“结束事件不能创建回合”+没有这个回合就什么都不写：宁可留下一个
        # 未落终态的执行，也不用执行编号造出一个假的逻辑回合（AR-06）。
        known_turns = snapshot.get("turns") if isinstance(snapshot.get("turns"), dict) else {}
        core = snapshot.get("core")
        core_turns = core.get("turns") if isinstance(core, dict) else None
        if turn_id not in known_turns and not (
            isinstance(core_turns, dict) and turn_id in core_turns
        ):
            _logger.warning(
                "[live] refused a terminal for an unknown turn thread=%s turn=%s",
                thread_id,
                turn_id,
            )
            return None
        terminal = build_cancelled_turn_event(thread_id=thread_id, turn_id=turn_id)
        execution_id = _turn_execution_id(snapshot, turn_id)
        terminal.run_id = execution_id
        terminal.event_id = f"{execution_id}:cancelled"
        terminal.item_id = f"{turn_id}:terminal"
        event = await _append_run_item(db, context=context, event=terminal)
        return event

    event = await context.persistence.write(write)
    if event is None:
        return None
    await context.hub.publish(event)
    return event


async def _save_runtime_state_with_retry(
    store: RuntimeStateStore,
    thread_id: str,
    *,
    mutate: "Callable[[RuntimeState], None]",
    max_attempts: int = 5,
) -> None:
    """Load-mutate-save a RuntimeState with optimistic-retry on revision conflict.

    When recover/cancel paths and the main turn loop write the same session
    concurrently, the revision can change between ``get`` and ``save``.
    Instead of crashing, reload the latest state and retry.
    """
    from .background import _logger
    for _ in range(max_attempts):
        state = await store.get(thread_id)
        if state is None:
            return
        mutate(state)
        try:
            await store.save(state)
            return
        except RuntimeStateConflictError:
            continue
    _logger.warning("[live] runtime state save exhausted %d retries thread_id=%s", max_attempts, thread_id)


async def _patch_runtime_state(
    store: RuntimeStateStore,
    thread_id: str,
    *,
    mutate: "Callable[[RuntimeState], None]",
) -> None:
    """Read-modify-write one state row without a stale-adoption window.

    ``get`` + ``save`` is optimistic and, for a row that is no longer "live",
    the store's adoption path can overwrite a newer state with the stale
    snapshot the caller loaded.  Pause/cancel settlement must not do that, so
    it uses the store's transactional patch when available.
    """
    patcher = getattr(store, "patch", None)
    if callable(patcher):
        await patcher(thread_id, mutate)
        return
    await _save_runtime_state_with_retry(store, thread_id, mutate=mutate)


async def _persist_cancelled_runtime_state(
    *, context: CoreLiveContext, thread_id: str, turn_id: str, reason: str = "user_cancelled"
) -> None:
    store = context.runtime_state_store
    if store is None:
        return

    def _mark_cancelled(state: Any) -> None:
        if str(state.metadata.get("turn_id") or state.run_id) != turn_id:
            return
        state.status = "cancelled"
        state.loop_state = "failed"
        state.metadata["cancellation_reason"] = reason
        state.metadata.pop("pending_approval", None)
        state.metadata.pop("pending_waiting_request", None)

    await _patch_runtime_state(store, thread_id, mutate=_mark_cancelled)


async def _reconcile_cancelled_runtime_state(
    *, context: CoreLiveContext, thread_id: str, snapshot: dict[str, Any]
) -> None:
    core = snapshot.get("core")
    projected_status = str(core.get("status") or "") if isinstance(core, dict) else ""
    if projected_status != "cancelled" and str(snapshot.get("status") or "") != "cancelled":
        return
    store = context.runtime_state_store
    if store is None:
        return

    def _mark_cancelled(state: Any) -> None:
        if state.status == "cancelled":
            return
        state.status = "cancelled"
        state.loop_state = "failed"
        state.metadata.pop("pending_approval", None)
        state.metadata.pop("pending_waiting_request", None)

    await _patch_runtime_state(store, thread_id, mutate=_mark_cancelled)


async def _active_thread_ids(*, context: "CoreLiveContext") -> list[str]:
    """Thread ids whose snapshot still holds a non-terminal turn."""
    from .background import _logger
    try:
        async with context.session_factory() as db:
            list_active = getattr(context.persistence, "list_active_thread_ids", None)
            if callable(list_active):
                return list(await list_active(db))
            return list(await context.persistence.list_thread_ids(db))
    except BaseException:
        _logger.exception("[live:reconcile] failed to enumerate threads")
        return []


async def _close_active_turns(
    db: AsyncSession,
    *,
    context: "CoreLiveContext",
    thread_id: str,
    verdict_for: "Callable[[str, dict[str, Any]], tuple[str, str, str] | None]",
) -> list[tuple[str, AppEventEnvelope]]:
    """Close a thread's leftover active turns with the verdict ``verdict_for`` returns.

    The dangling non-terminal items (a half-streamed tool_call, for instance)
    are closed BEFORE the turn-level terminal event: the snapshot reducer's
    turn-terminal lock would otherwise force-override item status on later
    events while the event log still held orphaned ``running`` events, leaving
    replay inconsistent. A ``None`` verdict leaves that turn alone.
    """
    from .events import _append_run_item
    from .recovery import _turn_execution_id
    events: list[tuple[str, AppEventEnvelope]] = []
    seen: set[str] = set()
    while True:
        snapshot = await context.persistence.load(db, thread_id)
        active = latest_active_turn_id(snapshot)
        if not active or active in seen:
            break
        verdict = verdict_for(active, snapshot)
        if verdict is None:
            break
        seen.add(active)
        status, reason, message = verdict
        execution_id = _turn_execution_id(snapshot, active)
        dangling = _collect_non_terminal_turn_item_ids(snapshot, active)
        for item_id in dangling:
            tool_event = await _append_run_item(
                db,
                context=context,
                event=_build_interrupted_tool_event(
                    thread_id=thread_id,
                    turn_id=active,
                    item_id=item_id,
                    reason=reason,
                    message=message,
                ),
            )
            events.append((active, tool_event))
            if len(events) > 50:  # guard against a runaway loop
                break
        if len(events) > 50:
            break
        event = await _append_run_item(
            db,
            context=context,
            event=RunItemEvent(
                kind="status",
                thread_id=thread_id,
                event_id=f"{execution_id}:{reason}",
                run_id=execution_id,
                turn_id=active,
                # Same identity as the kernel's terminal projection: the
                # reaper refreshes the turn's single cancel row rather than
                # appending another "recovered" bubble on every incident.
                item_id=f"{active}:terminal",
                status=status,
                payload={
                    "type": "turn",
                    "status": status,
                    "raw_end_reason": reason,
                    "message": message,
                },
            ),
        )
        events.append((active, event))
        if len(events) > 50:
            break
    return events


def _terminal_verdict(state: Any) -> tuple[str, str, str] | None:
    """Terminal ``(status, reason, message)`` for a state the runtime already ended.

    ``None`` while the state is not terminal: a live turn owns its own ending,
    and a state that has not been written is not evidence of anything.
    """
    status = str(getattr(state, "status", "") or "")
    if status not in {"failed", "cancelled"}:
        return None
    metadata = getattr(state, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    if state_is_memory_exhaustion(state):
        # Includes states written before the code existed: the interruption is
        # still memory, so the user gets the same explanation and the same
        # armed resume rather than a generic "ended unexpectedly".
        message = str(metadata.get("failure_message") or "").strip() or memory_exhausted_message_for(state)
        return status, HOST_MEMORY_EXHAUSTED, message
    code = str(metadata.get("failure_code") or "")
    message = str(metadata.get("failure_message") or "").strip()
    if not message:
        message = "已中断。"
    return status, code or ("user_interrupt" if status == "cancelled" else "failed"), message
