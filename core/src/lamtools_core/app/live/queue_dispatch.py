"""Dispatch of queued input and goal continuations after a turn."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import uuid
from typing import Any
from lamtools_core.runtime.goal_continuation import goal_continuation_text
from sqlalchemy.ext.asyncio import AsyncSession
from ..event_store import AppEventInput
from ..live_member import PreparedLiveInput
from ..queue_state import (
    input_items_text,
    next_dispatchable_queue_item,
    queue_delete_payload,
    queue_dispatch_payload,
    queue_item_payload,
)
from ..runtime_permissions import overlay_runtime_permissions
from ..turn_acceptance import build_turn_acceptance_plan
from .context import CoreLiveContext


async def _session_current_model(context: CoreLiveContext, thread_id: str) -> str:
    """Return the model the session is currently using (its last turn's model)."""
    store = context.runtime_state_store
    if store is None or not thread_id:
        return ""
    try:
        state = await store.get(thread_id)
    except Exception:
        return ""
    metadata = getattr(state, "metadata", None)
    if not isinstance(metadata, dict):
        return ""
    snapshot = metadata.get("runtime_snapshot")
    if isinstance(snapshot, dict):
        model = str(snapshot.get("model_id") or "").strip()
        if model:
            return model
    return str(metadata.get("model_id") or "").strip()


def _goal_reminder(active_goal: dict[str, Any] | None) -> str:
    """Return the continuation reminder for an active goal, or ""."""
    if not isinstance(active_goal, dict):
        return ""
    objective = str(active_goal.get("objective") or "").strip()
    return goal_continuation_text(objective) if objective else ""


async def _dispatch_next_queue_item(
    *,
    context: CoreLiveContext,
    thread_id: str,
    work_root: str,
    completed_turn_id: str,
    active_goal: dict[str, Any] | None = None,
) -> None:
    from .events import _app_event_input, _append_app_event
    from .runtime_tasks import _mirror_turn_started, _start_runtime_task
    from .turn_options import _queue_runtime_snapshot, _resolve_turn_approval_policy
    live_permissions = await _resolve_turn_approval_policy(
        context=context,
        params={"thread_id": thread_id},
    )
    live_permission_snapshot = live_permissions["runtime_snapshot"]
    context.host.runtime_task_registry.release_run(thread_id, run_id=completed_turn_id)
    claimed_turn_id = ""

    async def write(db: AsyncSession):
        nonlocal claimed_turn_id
        snapshot = await context.persistence.load(db, thread_id)
        # user:“界面上的引导队列里面，还是有一条”+(自动目标提醒不占用户队列，旧提醒一并作废)。
        cleanup_events = []
        for item in snapshot.get("queue") or []:
            if isinstance(item, dict) and item.get("goal_continuation"):
                item_id = str(item.get("queue_item_id") or "")
                if item_id:
                    cleanup_events.append(await _append_app_event(
                        db, context=context, event=AppEventInput(
                            thread_id=thread_id, method="queue/itemDeleted", item_id=item_id,
                            payload=queue_delete_payload(queue_item_id=item_id),
                        ),
                    ))
        if cleanup_events:
            snapshot = await context.persistence.load(db, thread_id)
        current_goal = active_goal
        manager = context.host.goal_manager
        if manager is not None and isinstance(current_goal, dict):
            goal = await manager.get(str(current_goal.get("id") or ""))
            current_goal = (
                {"id": goal.id, "objective": goal.objective}
                if goal is not None and goal.status == "active" and goal.thread_id == thread_id
                else None
            )
        reminder = _goal_reminder(current_goal)
        queued = next_dispatchable_queue_item(snapshot)
        automatic_goal_turn = queued is None
        if automatic_goal_turn:
            if not reminder:
                return cleanup_events, None
            # Construct the next turn's input locally, never a durable queue item.
            candidate = queue_item_payload(
                queue_item_id=f"goal:{uuid.uuid4().hex}",
                input_items=[{"type": "text", "text": reminder}],
                runtime_snapshot=live_permission_snapshot,
            )
            queued = next_dispatchable_queue_item({**snapshot, "queue": [candidate]})
        dispatch = queue_dispatch_payload(queued) if queued is not None else None
        if dispatch is None:
            return cleanup_events, None
        queue_item_id, visible_input, runtime_input, dispatch_payload = dispatch
        turn_id = f"{thread_id}:turn:{uuid.uuid4().hex[:12]}"
        user_item_id = f"{turn_id}:user"
        if not context.host.runtime_task_registry.accept_run(thread_id, turn_id, turn_id=turn_id):
            return cleanup_events, None
        claimed_turn_id = turn_id
        try:
            queued_work_root = str(queued.get("work_root") or work_root)
            runtime_snapshot = _queue_runtime_snapshot(queued)
            # A queued message carries a snapshot from the moment it was queued.
            # If the session's model changed since then, the queued snapshot's
            # model must not win: the turn runs with the model the session is
            # currently on (what the UI shows), and the alignment is announced.
            queued_model = str(runtime_snapshot.get("model_id") or "").strip()
            current_model = await _session_current_model(context, thread_id)
            if current_model and current_model != queued_model:
                runtime_snapshot["model_id"] = current_model
                if queued_model:
                    from lamtools_core.config.model_selection import record_model_notice

                    record_model_notice(
                        f"排队消息原定的模型「{queued_model}」与当前模型不一致，"
                        f"已按当前模型「{current_model}」执行"
                    )
            runtime_snapshot = overlay_runtime_permissions(
                runtime_snapshot, live_permission_snapshot
            )
            prepared = PreparedLiveInput(
                visible_input=visible_input,
                runtime_input=runtime_input,
                visible_text=input_items_text(visible_input),
                runtime_text=input_items_text(runtime_input),
                work_root=queued_work_root,
                # user:“是否会把附件带上”+(出队时恢复附件 ID，交给统一路径解析)。
                runtime_extras={"attachment_ids": [str(i.get("attachment_id") or i.get("attachmentId") or i.get("id")) for i in runtime_input if i.get("type") == "attachment"]},
            )
            materialized = await context.host.member_hooks.materialize_turn(
                db=db,
                thread_id=thread_id,
                turn_id=turn_id,
                user_item_id=user_item_id,
                client_message_id=f"dispatch:{queue_item_id}",
                prepared=prepared,
                params={"work_root": queued_work_root, **runtime_snapshot},
            )
            dispatched_input = AppEventInput(
                thread_id=thread_id,
                method="queue/itemDispatched",
                item_id=queue_item_id,
                client_message_id=f"dispatch:{queue_item_id}",
                payload=dispatch_payload,
            )
            plan = build_turn_acceptance_plan(
                thread_id=thread_id,
                turn_id=turn_id,
                user_item_id=user_item_id,
                client_message_id=f"dispatch:{queue_item_id}",
                input_items=prepared.visible_input,
                work_root=prepared.work_root,
                turn_payload_extra={
                    **materialized.turn_payload_extra,
                    "runtime_snapshot": runtime_snapshot,
                },
                user_payload_extra=materialized.user_payload_extra,
                include_turn_status=materialized.include_turn_status,
            )
            envelopes = await context.persistence.append_batch(
                db,
                app_events=[
                    *([] if automatic_goal_turn else [dispatched_input]),
                    _app_event_input(plan.turn_accepted), _app_event_input(plan.user_item),
                ],
                run_item_events=[plan.running_status],
            )
            runtime_start = {
                "thread_id": thread_id,
                "turn_id": turn_id,
                "user_message_id": user_item_id,
                # user:“不是合并成一条消息，是都追加进去，但不是同一条消息”
                # +排队消息照常作为本回合输入；目标提醒作为单独一条消息追加。
                **(
                    {"goal_id": str(current_goal.get("id") or "")}
                    if isinstance(current_goal, dict) and current_goal.get("id")
                    else {}
                ),
                **(
                    {"goal_continuation": True}
                    if automatic_goal_turn
                    else {}
                ),
                **(
                    {"goal_continuation_text": reminder}
                    if reminder and not (automatic_goal_turn)
                    else {}
                ),
                "text": prepared.runtime_text,
                "input": prepared.runtime_input,
                "work_root": prepared.work_root,
                "approval_policy": runtime_snapshot.get("approval_policy", "require"),
                "active_tier": runtime_snapshot.get("active_tier"),
                "tier_tools": runtime_snapshot.get("tier_tools"),
                "active_mode": runtime_snapshot.get("active_mode"),
                "instructions": str(runtime_snapshot.get("instructions") or ""),
                "request_local_late_context": str(
                    runtime_snapshot.get("request_local_late_context") or ""
                ),
                "allow_access_outside_workdir": bool(
                    runtime_snapshot.get("allow_access_outside_workdir", False)
                ),
                "permission_preset": runtime_snapshot.get("permission_preset", "ask"),
                "runtime_snapshot": runtime_snapshot,
                **prepared.runtime_extras,
                **materialized.runtime_extras,
            }
            for key in (
                "model_id",
                "reasoning_level",
                "thinking_enabled",
                "thinking_budget",
                "reasoning_effort",
                "shallow_thinking_enabled",
                "context_window_tokens",
                "max_tokens",
                "temperature",
                "compact_trigger_tokens",
                "compact_limit_tokens",
            ):
                if key in runtime_snapshot:
                    runtime_start[key] = runtime_snapshot[key]
            return [*cleanup_events, *envelopes], runtime_start
        except BaseException:
            context.host.runtime_task_registry.release_run(thread_id, run_id=turn_id)
            claimed_turn_id = ""
            raise

    try:
        result = await context.persistence.write(write)
    except BaseException:
        if claimed_turn_id:
            context.host.runtime_task_registry.release_run(thread_id, run_id=claimed_turn_id)
        raise
    if result is None:
        return
    events, next_runtime_start = result
    for event in events:
        await context.hub.publish(event)
    if next_runtime_start is None:
        return
    await _mirror_turn_started(
        context=context,
        thread_id=thread_id,
        turn_id=str(next_runtime_start.get("turn_id") or ""),
        run_id=str(next_runtime_start.get("turn_id") or ""),
        input_payload={"text": str(next_runtime_start.get("text") or "")},
        resumed=False,
    )
    await _start_runtime_task(context=context, runtime_start=next_runtime_start)
