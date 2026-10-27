"""Queue acceptance, editing, deletion and guidance operations."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import uuid
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from ..event_store import AppEventEnvelope, AppEventInput
from ..live_protocol import INVALID_REQUEST, rpc_error, rpc_result
from ..queue_state import (
    build_queue_guidance_plan,
    build_queue_update_plan,
    input_items_text,
    queue_delete_payload,
    queue_item_payload,
)
from ..turn_acceptance import QUEUE_ITEM_ACCEPTED_METHODS
from .context import CoreLiveContext, CoreLiveOperationOutcome


async def handle_queue_create_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    from .events import _append_app_event
    from .params import _expected_revision, _include_snapshot_param, _load_snapshot_outside_write_lock
    from .turn_options import _resolve_turn_approval_policy, _runtime_snapshot_with_turn_options
    thread_id = str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()
    input_items = params.get("input")
    if not thread_id or not isinstance(input_items, list):
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id and input are required")
        )
    try:
        # 仅校验参数形状；排队是幂等追加，不参与修订号 CAS（见下方 write 的说明）。
        _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    queue_item_id = str(params.get("queue_item_id") or params.get("queueItemId") or f"queue:{uuid.uuid4().hex[:12]}")
    client_message_id = str(params.get("client_message_id") or params.get("clientMessageId") or uuid.uuid4().hex)
    # Resolve permissions at queue acceptance time.  The queue item must carry
    # its own immutable runtime snapshot because Composer/session settings may
    # change before this item is dispatched.
    try:
        resolved = await _resolve_turn_approval_policy(
            context=context,
            params={**params, "thread_id": thread_id},
        )
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    if not (params.get("work_root") or params.get("workRoot")) and resolved.get("work_root"):
        params = {**params, "work_root": resolved["work_root"]}
    try:
        prepared = await context.host.member_hooks.prepare_queue_input(
            thread_id=thread_id, params=params, input_items=input_items,
        )
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    queue_runtime_snapshot = _runtime_snapshot_with_turn_options(
        resolved["runtime_snapshot"],
        params=params,
        active_mode=resolved.get("active_mode"),
    )
    payload = queue_item_payload(
        queue_item_id=queue_item_id,
        input_items=prepared.visible_input,
        runtime_input_items=prepared.runtime_input,
        mode=str(params.get("mode") or "next_turn"),
        runtime_snapshot=queue_runtime_snapshot,
    )
    payload["work_root"] = prepared.work_root
    if params.get("goal_continuation"):
        payload["goal_continuation"] = True
    async def write(db: AsyncSession):
        existing = await context.persistence.find_client_event(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            methods=QUEUE_ITEM_ACCEPTED_METHODS,
        )
        if existing is not None:
            return existing, None
        # 排队是"只增"的幂等追加：条目自带 queue_item_id 与 runtime_snapshot，
        # 写入在事务内读的是最新快照，客户端传进来的期望修订号不参与任何读改写。
        # 因此这里刻意不做 CAS：主回合等待后台子代理期间，会话修订号会被持续追加
        # 的事件推高（本轮事件、成员转发事件），客户端在发起 RPC 前读到的修订号
        # 几乎必然落后，CAS 会把一条完全合法的消息打成"Revision conflict"（用户
        # 只能刷新重试才能发出）。真正需要乐观锁的是读改写类变更（turn.start、
        # command.execute、queue.update/delete/guide、会话设置），它们各自的 CAS
        # 一个都没有动，这里移除的只针对幂等追加。expected_revision 仍按参数校验
        # （见本函数入口），但不再作为拒绝依据（2026-10-12）。
        materialized = await context.host.member_hooks.materialize_queue(
            db=db,
            thread_id=thread_id,
            queue_item_id=queue_item_id,
            client_message_id=client_message_id,
            prepared=prepared,
            params=params,
        )
        event = await _append_app_event(
            db,
            context=context,
            event=AppEventInput(
                thread_id=thread_id,
                method="queue/itemAccepted",
                item_id=queue_item_id,
                client_message_id=client_message_id,
                payload={**payload, **materialized.payload_extra},
            ),
        )
        return event, materialized

    event, materialized = await context.persistence.write(write)
    await context.hub.publish(event)
    # Response queue item is rebuilt from the payload we just wrote; the queue
    # lives in the metadata row, so no full snapshot assembly is required.
    queue_item = {
        **payload,
        **(materialized.payload_extra if materialized is not None else {}),
        "queue_item_id": queue_item_id,
        "status": "queued",
        "mode": str(payload.get("mode") or "next_turn"),
        "input": prepared.visible_input,
        "seq": event.seq,
        "last_method": "queue/itemAccepted",
    }
    response_payload: dict[str, Any] = {"queue_item": queue_item, "events": [event.to_dict()]}
    if _include_snapshot_param(params):
        response_payload["snapshot"] = await _load_snapshot_outside_write_lock(context, thread_id)
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, response_payload),
        publish_events=[event],
    )


async def handle_queue_update_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    from .events import _append_app_event
    from .params import _expected_revision, _include_snapshot_param, _load_snapshot_outside_write_lock
    thread_id = str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()
    queue_item_id = str(params.get("queue_item_id") or params.get("queueItemId") or "").strip()
    if not thread_id or not queue_item_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="thread_id, queue_item_id and text are required",
            )
        )
    try:
        _expected_revision(params)  # 形状校验；写事件是幂等追加，见 write 说明
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    input_items = params.get("input")
    if not isinstance(input_items, list):
        text = str(params.get("text") or "").strip()
        if not text:
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message="thread_id, queue_item_id and text are required",
                )
            )
        input_items = [{"type": "text", "text": text}]
    try:
        prepared = await context.host.member_hooks.prepare_queue_input(
            thread_id=thread_id,
            params=params,
            input_items=input_items,
        )
    except ValueError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    async def write(
        db: AsyncSession,
    ) -> tuple[str, AppEventEnvelope | None]:
        # 队列条目本身存放在元数据行；更新计划不需要逐条装配会话内容。
        snapshot = await context.persistence.load_metadata(db, thread_id)
        plan = build_queue_update_plan(
            snapshot,
            queue_item_id=queue_item_id,
            input_items=prepared.visible_input,
            runtime_input_items=prepared.runtime_input,
            mode=str(params.get("mode") or "").strip() or None,
        )
        if not plan.applied:
            return plan.reason, None
        # 更新排队条目是幂等追加（queue_item_id 为键），计划在事务内基于最新元数据
        # 行构建，客户端期望修订号不参与任何读改写。这里不做 CAS：活跃回合持续追加
        # 事件会让客户端读到的修订号必然落后，CAS 会把合法的编辑打成修订冲突
        # （2026-10-12，与 queue.create 同一原因）。
        event = await _append_app_event(
            db,
            context=context,
            event=AppEventInput(
                thread_id=thread_id,
                method="queue/itemUpdated",
                item_id=queue_item_id,
                payload=plan.payload or {},
            ),
        )
        return "applied", event

    outcome_kind, payload = await context.persistence.write(write)
    if outcome_kind != "applied":
        response_payload = {"applied": False, "reason": outcome_kind, "events": []}
        if _include_snapshot_param(params):
            response_payload["snapshot"] = await _load_snapshot_outside_write_lock(context, thread_id)
        return CoreLiveOperationOutcome(response=rpc_result(request_id, response_payload))
    event = payload
    await context.hub.publish(event)
    response_payload = {"events": [event.to_dict()]}
    if _include_snapshot_param(params):
        response_payload["snapshot"] = await _load_snapshot_outside_write_lock(context, thread_id)
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, response_payload),
        publish_events=[event],
    )


async def handle_queue_delete_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    from .events import _append_app_event
    from .params import _expected_revision, _include_snapshot_param, _load_snapshot_outside_write_lock
    thread_id = str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()
    queue_item_id = str(params.get("queue_item_id") or params.get("queueItemId") or "").strip()
    if not thread_id or not queue_item_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id and queue_item_id are required")
        )
    try:
        _expected_revision(params)  # 形状校验；删除是幂等追加，见 write 说明
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    async def write(db: AsyncSession) -> AppEventEnvelope:
        # 删除排队条目只追加一个 queue_item_id 为键的 tombstone 事件，不读改写任何
        # 共享字段；活跃回合持续追加事件时客户端修订号必然落后，CAS 会让用户根本删
        # 不掉这条排队消息（2026-10-12）。因此与 queue.create 一致，不做修订号 CAS。
        return await _append_app_event(
            db,
            context=context,
            event=AppEventInput(
                thread_id=thread_id,
                method="queue/itemDeleted",
                item_id=queue_item_id,
                payload=queue_delete_payload(queue_item_id=queue_item_id, status="deleted"),
            ),
        )

    event = await context.persistence.write(write)
    await context.hub.publish(event)
    response_payload: dict[str, Any] = {"events": [event.to_dict()]}
    if _include_snapshot_param(params):
        response_payload["snapshot"] = await _load_snapshot_outside_write_lock(context, thread_id)
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, response_payload),
        publish_events=[event],
    )


async def handle_queue_guidance_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    from .events import _app_event_input
    from .params import _expected_revision, _include_snapshot_param, _load_snapshot_outside_write_lock
    from .steering import _activate_stored_guidance, _reference_input
    thread_id = str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()
    turn_id = str(params.get("turn_id") or params.get("turnId") or "").strip()
    queue_item_id = str(params.get("queue_item_id") or params.get("queueItemId") or "").strip()
    if not thread_id or not turn_id or not queue_item_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="thread_id, turn_id and queue_item_id are required",
            )
        )
    try:
        _expected_revision(params)  # 形状校验；引导是幂等追加，见 write 说明
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    client_message_id = str(
        params.get("client_message_id") or params.get("clientMessageId") or f"queue-guide:{queue_item_id}"
    )
    replacement_text = params.get("text") if isinstance(params.get("text"), str) else None
    guidance_accepted = False

    async def write(
        db: AsyncSession,
    ) -> tuple[str, Any, Any]:
        """Return (kind, payload, plan): kind is existing/mismatch/applied/not_applied."""
        nonlocal guidance_accepted
        existing = await context.persistence.find_client_event(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            methods={"turn/steered"},
        )
        if existing is not None:
            return "existing", existing, None
        # 引导计划只需要队列与轮次状态（元数据行），不需要装配全部会话条目。
        snapshot = await context.persistence.load_metadata(db, thread_id)
        plan = build_queue_guidance_plan(
            snapshot,
            thread_id=thread_id,
            turn_id=turn_id,
            queue_item_id=queue_item_id,
            client_message_id=client_message_id,
            replacement_text=replacement_text,
        )
        if plan.applied:
            # 引导把排队条目转成两枚追加事件（turn/steered + itemDeleted）并在内存
            # 注册表登记，不读改写共享的持久字段。活跃回合持续追加事件会让客户端修订
            # 号落后，CAS 会把合法的引导打成修订冲突（2026-10-12，同 queue.create）。
            runtime_items = await _reference_input(db, plan.runtime_input_items)
            guidance_text = input_items_text(runtime_items)
            guidance_status = context.host.runtime_task_registry.accept_guidance(
                thread_id,
                guidance_text,
                run_id=turn_id,
                guidance_id=client_message_id,
                ready=False,
            )
            if guidance_status not in {"accepted", "duplicate"}:
                return "run_not_active", None, plan
            if guidance_status == "accepted":
                guidance_accepted = True
            try:
                app_event_inputs = [_app_event_input(spec) for spec in plan.events]
                for event_input in app_event_inputs:
                    if event_input.method == "turn/steered":
                        event_input.payload["guidance_id"] = client_message_id
                        event_input.payload["runtime_input"] = runtime_items
                        event_input.payload["runtime_text"] = guidance_text
                events: list[AppEventEnvelope] = []
                if app_event_inputs:
                    events = await context.persistence.append_batch(db, app_events=app_event_inputs)
            except BaseException:
                context.host.runtime_task_registry.retract_guidance(
                    thread_id, run_id=turn_id, guidance_id=client_message_id
                )
                guidance_accepted = False
                raise
            return "applied", events, plan
        return "not_applied", None, plan

    try:
        write_result = await context.persistence.write(write)
    except BaseException:
        if guidance_accepted:
            context.host.runtime_task_registry.retract_guidance(
                thread_id, run_id=turn_id, guidance_id=client_message_id
            )
        raise
    outcome_kind, payload, plan = write_result
    if outcome_kind == "existing":
        _activate_stored_guidance(context, payload)
    elif outcome_kind == "applied":
        for stored_event in payload:
            if stored_event.method == "turn/steered":
                _activate_stored_guidance(context, stored_event)
    snapshot: dict[str, Any] | None = None
    if _include_snapshot_param(params):
        snapshot = await _load_snapshot_outside_write_lock(context, thread_id)

    def _guidance_response(**extra: Any) -> CoreLiveOperationOutcome:
        response_payload: dict[str, Any] = {
            "applied": plan.applied if plan is not None else outcome_kind == "applied",
            "reason": plan.reason if plan is not None else "",
            **extra,
        }
        if snapshot is not None:
            response_payload["snapshot"] = snapshot
        return CoreLiveOperationOutcome(response=rpc_result(request_id, response_payload))

    if outcome_kind == "existing":
        assert isinstance(payload, AppEventEnvelope)
        return _guidance_response(applied=True, reason="already_applied", events=[payload.to_dict()])
    if outcome_kind == "run_not_active":
        return _guidance_response(applied=False, reason="run_not_active", events=[])
    events = payload if outcome_kind == "applied" else []
    for event in events:
        await context.hub.publish(event)
    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "applied": plan.applied,
                "reason": plan.reason,
                "events": [event.to_dict() for event in events],
                **({"snapshot": snapshot} if snapshot is not None else {}),
            },
        ),
        publish_events=events,
    )
