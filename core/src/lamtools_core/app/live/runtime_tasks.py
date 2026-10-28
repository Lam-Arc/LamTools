"""Runtime task startup, completion, failures and turn mirroring."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
import time as time_module
from typing import Any
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime.goal_continuation import should_continue_goal
from sqlalchemy.ext.asyncio import AsyncSession
from ..event_store import AppEventEnvelope, CORE_RUN_ITEM_METHOD
from ..live_member import DefaultCoreLiveMemberHooks
from ..operation_catalog import OperationResult
from ..queue_state import effective_thread_status, latest_active_turn_id
from ..session_autotitle import generate_session_title, is_default_title
from .context import CoreLiveContext


async def _mirror_turn_started(
    *,
    context: "CoreLiveContext",
    thread_id: str,
    turn_id: str,
    run_id: str,
    input_payload: dict[str, Any] | None = None,
    resumed: bool = False,
) -> None:
    """Record the turn/run in the new read model (best-effort mirror)."""
    from .background import _logger
    if not thread_id or not turn_id:
        return
    try:
        from lamtools_core.turn.coordinator import TurnCoordinator

        coordinator = TurnCoordinator(context.turn_store)
        if await context.turn_store.get_turn(turn_id) is None:
            await coordinator.ensure_turn(
                thread_id=thread_id,
                turn_id=turn_id,
                input_payload=input_payload,
                status="queued",
            )
        if resumed:
            await coordinator.begin_resumed_run(turn_id, run_id)
        else:
            await coordinator.start_run(turn_id, run_id)
    except BaseException:
        _logger.exception(
            "[live:mirror] turn start failed thread_id=%s turn_id=%s", thread_id, turn_id
        )


async def _mirror_turn_status(
    *,
    context: "CoreLiveContext",
    thread_id: str,
    turn_id: str,
    status: str,
    run_id: str = "",
) -> None:
    """Mirror a settled status into the new read model (best-effort)."""
    from .background import _logger
    if not thread_id or not turn_id:
        return
    try:
        from lamtools_core.turn.model import Turn, now_ms as turn_now_ms

        store = context.turn_store
        turn = await store.get_turn(turn_id)
        if turn is None:
            await store.create_turn(
                Turn(
                    turn_id=turn_id,
                    thread_id=thread_id,
                    status=status,  # type: ignore[arg-type]
                    epoch=0,
                    created_seq=turn_now_ms(),
                    updated_seq=turn_now_ms(),
                )
            )
            return
        if turn.status == status:
            return
        if turn.status in {"completed", "failed", "cancelled"}:
            return
        if turn.status in {"paused", "waiting", "stopping"} and status in {
            "completed",
            "failed",
            "running",
        }:
            # A control intent owns these states; a late run result must not
            # overwrite it.
            return
        if turn.status == "waiting" and status == "paused":
            pass
        transitioned = await store.transition_turn(
            turn_id,
            expected_epoch=turn.epoch,
            expected_status=turn.status,
            status=status,
            event="mirror_status",
            active_run_id=run_id or turn.active_run_id,
            bump_epoch=True,
        )
        # user:“修 问题严重的话 就重新设计”+(比较写入失败说明控制权已改变，镜像不得绕过版本约束强写)。
        if transitioned is None:
            return
    except BaseException:
        _logger.exception(
            "[live:mirror] turn status failed thread_id=%s turn_id=%s status=%s",
            thread_id,
            turn_id,
            status,
        )


async def _auto_title_session(
    *,
    context: CoreLiveContext,
    thread_id: str,
    first_message: str,
    model_id: str = "",
) -> None:
    """Background task: derive a short title from the first user message.

    Best-effort — any failure is logged and swallowed so it can never affect
    the ongoing turn. Persists the title via the session store (when available)
    and broadcasts ``session/updated`` so frontends refresh their sidebar.
    """
    from .background import _logger
    llm_client = context.host.llm_client
    session_store = context.host.session_store
    if llm_client is None:
        return
    try:
        # Don't clobber a title the user already set manually.
        existing_title: str | None = None
        existing: Any = None
        if session_store is not None:
            existing = await session_store.get(thread_id)
            existing_title = getattr(existing, "title", None) if existing else None
        if not is_default_title(existing_title, session_id=thread_id):
            return

        resolved_model = model_id
        if not resolved_model and existing is not None:
            metadata = getattr(existing, "metadata", None)
            if isinstance(metadata, dict):
                resolved_model = str(metadata.get("model_id") or "").strip()
        if not resolved_model:
            # Background work follows the background scene, never the main
            # conversation's model and never a boot-time "default".
            from lamtools_core.config.model_selection import (
                ModelResolutionError,
                SCENE_BACKGROUND,
                record_model_notice,
                resolve_scene_model,
            )

            try:
                resolved_model = resolve_scene_model(SCENE_BACKGROUND).model_id
            except ModelResolutionError:
                # Auto-title is best-effort and must not fail the turn; make the
                # skipped title visible instead of borrowing another model.
                record_model_notice("后台任务没有可用模型，已跳过会话标题生成；请先添加供应商/模型")
                return

        title = await generate_session_title(
            llm_client,
            resolved_model,
            first_message,
            session_id=thread_id,
        )
        if not title:
            return

        if session_store is not None:
            # Conditional patch: the earlier guard checked the title before the
            # LLM call, but the user may have renamed the session meanwhile.
            # only_if_title_default makes the check atomic with the write, so a
            # manual rename in that window is never clobbered. None means the
            # title was no longer default (or the session is gone) — nothing to
            # broadcast.
            patched = await session_store.patch(
                thread_id,
                title=title,
                only_if_title_default=True,
            )
            if patched is None:
                return

        await context.hub.publish({
            "method": "session/updated",
            "thread_id": thread_id,
            "payload": {"session": {"title": title}},
        })
        _logger.info("[autotitle] generated title for thread=%s title=%r", thread_id, title)
    except Exception:  # noqa: BLE001 — must never break the turn
        _logger.warning("[autotitle] failed for thread=%s", thread_id, exc_info=True)


async def _start_runtime_task(
    *, context: CoreLiveContext, runtime_start: dict[str, Any]
) -> tuple[AppEventEnvelope, dict[str, Any]] | None:
    from .events import _get_running_loop
    thread_id = str(runtime_start.get("thread_id") or "")
    turn_id = str(runtime_start.get("turn_id") or "")
    if isinstance(context.host.member_hooks, DefaultCoreLiveMemberHooks) and not context.operations.has("turn.start"):
        return await _fail_runtime_start(
            context=context,
            thread_id=thread_id,
            turn_id=turn_id,
            message="turn.start operation is unavailable",
        )
    message = str(runtime_start.get("text") or "")
    # A continuation of a paused turn carries no new text on purpose: the
    # committed history already holds the task and every finished step. Only a
    # turn that has nothing else to run on is an error.
    continuation = str(runtime_start.get("origin") or "") == "turn_resume"
    if not thread_id or (not message and not continuation and not runtime_start.get("attachment_ids")):
        return await _fail_runtime_start(
            context=context,
            thread_id=thread_id,
            turn_id=turn_id,
            message="runtime input is empty",
        )

    try:
        loop = _get_running_loop()
    except RuntimeError as exc:
        return await _fail_runtime_start(
            context=context,
            thread_id=thread_id,
            turn_id=turn_id,
            message=str(exc) or "no running event loop",
        )
    coroutine = _run_core_turn(context=context, runtime_start=runtime_start)
    try:
        task = loop.create_task(coroutine)
    except BaseException as exc:
        coroutine.close()
        return await _fail_runtime_start(
            context=context,
            thread_id=thread_id,
            turn_id=turn_id,
            message=str(exc) or "runtime task creation failed",
        )
    if task.done() or not context.host.runtime_task_registry.register(
        thread_id, task, run_id=turn_id, turn_id=turn_id
    ):
        return await _fail_runtime_start(
            context=context,
            thread_id=thread_id,
            turn_id=turn_id,
            message="runtime task registration failed",
            task=task,
        )
    return None


async def _fail_runtime_start(
    *,
    context: CoreLiveContext,
    thread_id: str,
    turn_id: str,
    message: str,
    task: asyncio.Future[Any] | None = None,
) -> tuple[AppEventEnvelope, dict[str, Any]]:
    from .events import _append_run_item
    from .recovery import _turn_is_terminal
    if task is not None:
        if not task.done():
            task.cancel()
        try:
            await task
        except BaseException:
            pass
    # Defer release_run until *after* the terminal event is durably
    # persisted. Releasing first opens a window where the registry no longer
    # reports an active run but the snapshot has no terminal status yet — a
    # subsequent turn.start then passes both the snapshot guard and the
    # registry guard and is accepted while the old turn's background work is
    # still flushing, which is exactly the race that deadlocked session
    # 2b34c636 (new turn's runtime_start raced the old turn's final
    # replace_history for the DB write lock). If the write itself fails we
    # still must release so the thread is not permanently stuck.
    async def write(
        db: AsyncSession,
    ) -> tuple[AppEventEnvelope, dict[str, Any]]:
        snapshot = await context.persistence.load(db, thread_id)
        if _turn_is_terminal(snapshot, turn_id):
            # user:“该修修，相关插件也要修”+(长会话也必须保留真实终态，后来的工具事件不是回合终态)。
            event = await context.persistence.find_turn_event(
                db, thread_id=thread_id, turn_id=turn_id, terminal_only=True,
            )
            if event is not None:
                return event, snapshot
            # Fall through to the normal failed-event write below.
        core = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
        requests = core.get("requests") if isinstance(core, dict) else {}
        denied_request = any(
            isinstance(pending, dict)
            and str(pending.get("turn_id") or "") == turn_id
            and str(pending.get("status") or "") == "resolved"
            and str(pending.get("decision") or pending.get("action") or "") in {"deny", "denied"}
            for pending in (requests.values() if isinstance(requests, dict) else [])
        )
        if denied_request:
            prior = await context.persistence.find_turn_event(
                db, thread_id=thread_id, turn_id=turn_id,
            )
            if prior is not None:
                return prior, snapshot
            # Fall through to the normal failed-event write below.
        event = await _append_run_item(
            db,
            context=context,
            event=RunItemEvent(
                kind="status",
                thread_id=thread_id,
                event_id=f"{turn_id}:runtime-start-failed",
                run_id=turn_id,
                turn_id=turn_id,
                item_id=f"{turn_id}:runtime-start-failed",
                status="failed",
                payload={
                    "type": "turn",
                    "status": "failed",
                    "raw_end_reason": "runtime_start_failed",
                    "message": message,
                },
            ),
        )
        snapshot = await context.persistence.load(db, thread_id)
        return event, snapshot

    # user:“失败回合结束后会话仍被判为‘有活跃回合’”+(终态写入失败时保留待修复记录，不能只释放运行登记而遗留 running 快照)。
    pending_key = (thread_id, turn_id)
    context.host.pending_terminal_failures[pending_key] = message
    try:
        event, snapshot = await context.persistence.write(write)
        context.host.pending_terminal_failures.pop(pending_key, None)
    finally:
        # Release the run claim only once the terminal event is durably
        # written (or the write failed — either way the claim must not
        # outlive this function, or the thread would be stuck "active").
        context.host.runtime_task_registry.release_run(thread_id, run_id=turn_id)
    turns = snapshot.get("turns") or {}
    if str((turns.get(turn_id) or {}).get("status") or "") == "failed":
        await _mirror_turn_status(context=context, thread_id=thread_id, turn_id=turn_id, status="failed")
    await context.hub.publish(event)
    return event, snapshot


async def _run_core_turn(*, context: CoreLiveContext, runtime_start: dict[str, Any]) -> None:
    from .background import _logger, _spawn_live_background
    from .events import _persist_operation_result
    from .interactions import reconcile_open_interactions
    from .queue_dispatch import _dispatch_next_queue_item
    from .terminal_state import _persist_cancelled_terminal
    thread_id = str(runtime_start.get("thread_id") or "")
    turn_id = str(runtime_start.get("turn_id") or "")
    _start_ts = time_module.time()
    _logger.info("[live:_run_core_turn] background task started thread_id=%s turn_id=%s", thread_id, turn_id)
    try:
        payload = {
            **runtime_start,
            "session_id": thread_id,
            "message": str(runtime_start.get("text") or ""),
        }

        async def execute_core_operation(operation_payload: dict[str, Any]) -> OperationResult:
            return await context.operations.execute(
                "turn.start", operation_payload, metadata={"source": "core_live"}
            )

        if isinstance(context.host.member_hooks, DefaultCoreLiveMemberHooks):
            payload["_core_operation"] = execute_core_operation
        _logger.info("[live:_run_core_turn] entering member_hooks.start_runtime thread_id=%s turn_id=%s",
                      thread_id, turn_id)
        result = await context.host.member_hooks.start_runtime(
            runtime_start=payload,
        )
        # Release the registry claim as soon as start_runtime returns — the
        # runtime has finished (terminal events are already persisted live)
        # and trailing cleanup (_persist_operation_result,
        # _ensure_turn_terminal, _dispatch_next_queue_item) must not keep the
        # active-turn guard blocking a subsequent turn.start from the client.
        # These steps do DB I/O that can yield the event loop, letting an SSE
        # round-trip race ahead and unblock the UI before release_run.
        context.host.runtime_task_registry.release_run(thread_id, run_id=turn_id)
        if isinstance(result, OperationResult):
            _elapsed = time_module.time() - _start_ts
            _logger.info("[live:_run_core_turn] turn completed thread_id=%s turn_id=%s status=%s elapsed=%.2fs",
                          thread_id, turn_id, result.status, _elapsed)
            await _persist_operation_result(context=context, thread_id=thread_id, turn_id=turn_id, result=result)
            if result.status != "ok":
                # Setup/validation can return an error before the kernel emits
                # any terminal event. Never leave that accepted turn running.
                # Existing recorded terminal reasons are preserved by this helper.
                await _fail_runtime_start(
                    context=context, thread_id=thread_id, turn_id=turn_id,
                    message=str(result.payload.get("error") or result.status),
                )
            await _ensure_turn_terminal(context=context, thread_id=thread_id, turn_id=turn_id)
            await _mirror_turn_status(
                context=context,
                thread_id=thread_id,
                turn_id=turn_id,
                status="completed" if result.status == "ok" else "failed",
            )
            # A card that outlived its turn must not stay answerable. Child
            # cards survive while their own child session is active.
            try:
                await reconcile_open_interactions(
                    context=context, thread_id=thread_id
                )
            except BaseException:
                _logger.exception(
                    "[live] post-turn interaction reconciliation failed thread_id=%s",
                    thread_id,
                )
        await _dispatch_next_queue_item(
            context=context,
            thread_id=thread_id,
            work_root=str(runtime_start.get("work_root") or ""),
            completed_turn_id=turn_id,
            # user:“只有在模型像是自然终止的时候，才会给目标开一个新回合”
            # +错误、重试、暂停和停止都不续跑，避免卡在供应商错误上无限循环。
            active_goal=(
                result.payload.get("active_goal")
                if isinstance(result, OperationResult)
                and should_continue_goal(
                    status=str(result.status or ""),
                    decision=str(result.payload.get("decision") or ""),
                )
                else None
            ),
        )
    except BaseException as exc:
        _elapsed = time_module.time() - _start_ts
        get_cancel_event = getattr(context.host.runtime_task_registry, "get_cancel_event", None)
        cancel_requested = bool(callable(get_cancel_event) and get_cancel_event(thread_id).is_set())
        get_pause_event = getattr(context.host.runtime_task_registry, "get_pause_event", None)
        pause_requested = bool(callable(get_pause_event) and get_pause_event(thread_id).is_set())
        if pause_requested and not cancel_requested:
            # The pause aborted the task (a tool that never checks the pause
            # event). The kernel's detached pause finalizer writes the resumable
            # state; marking the turn failed here would overwrite it.
            _logger.info(
                "[live:_run_core_turn] turn paused thread_id=%s turn_id=%s elapsed=%.2fs",
                thread_id,
                turn_id,
                _elapsed,
            )
            raise
        if cancel_requested:
            _logger.info(
                "[live:_run_core_turn] turn cancelled thread_id=%s turn_id=%s elapsed=%.2fs",
                thread_id,
                turn_id,
                _elapsed,
            )
            # Detached: the turn task must exit now so the registry claim is
            # released immediately; the terminal record settles in the
            # background like every other cancel-path write.
            _spawn_live_background(
                _persist_cancelled_terminal(
                    context=context,
                    thread_id=thread_id,
                    turn_id=turn_id,
                ),
                label="turn-cancelled-terminal",
                thread_id=thread_id,
            )
            raise
        _logger.exception(
            "[live:_run_core_turn] turn failed thread_id=%s turn_id=%s elapsed=%.2fs",
            thread_id,
            turn_id,
            _elapsed,
        )
        await asyncio.shield(
            _fail_runtime_start(
                context=context,
                thread_id=thread_id,
                turn_id=turn_id,
                message=str(exc) or "member runtime failed",
            )
        )


async def _ensure_turn_terminal(
    *,
    context: CoreLiveContext,
    thread_id: str,
    turn_id: str,
) -> None:
    """After a normal turn completion, ensure the thread status reflects completion
    so that queued items can be dispatched.  This covers the case where member
    hooks persist events live and the terminal status may not be reflected in the
    snapshot store yet."""
    from .background import _logger
    from .events import _append_run_item
    from .recovery import _turn_is_terminal
    async with context.session_factory() as db:
        snapshot = await context.persistence.load(db, thread_id)
    queue = snapshot.get("queue")
    if not isinstance(queue, list) or not queue:
        return
    if effective_thread_status(snapshot) in {"completed", "idle", "waiting", "paused"}:
        return
    # Check if the current turn is the last active turn
    core_state = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
    latest_active = latest_active_turn_id({"core": core_state, "turns": snapshot.get("turns", {})})
    if latest_active is not None and latest_active != turn_id:
        return
    # The turn itself must already be terminal before we backfill a completed
    # status — a turn still waiting for approval (or otherwise non-terminal)
    # must never be marked completed, or the queue would dispatch the next
    # item without approval and two kernels would run concurrently
    # (audit 01 S1).
    if _turn_is_terminal(snapshot, turn_id):
        return
    # Write a completed terminal status event
    terminal = RunItemEvent(
        kind="status",
        thread_id=thread_id,
        event_id=f"{turn_id}:terminal",
        run_id=turn_id,
        turn_id=turn_id,
        item_id=f"{turn_id}:terminal",
        status="completed",
    )

    async def write(db):
        return await _append_run_item(db, context=context, event=terminal)

    try:
        event = await context.persistence.write(write)
        await context.hub.publish(event)
    except BaseException:
        _logger.exception(
            "[live:_ensure_turn_terminal] failed thread_id=%s turn_id=%s",
            thread_id, turn_id,
        )
