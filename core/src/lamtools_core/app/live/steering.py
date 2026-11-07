"""Guidance delivery to active and interrupted turns."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import json
import uuid
from pathlib import Path
from typing import Any
from lamtools_core.runtime import normalize_run_id
from ..event_store import AppEventEnvelope, AppEventInput
from ..live_protocol import INVALID_REQUEST, rpc_error, rpc_result
from ..queue_state import input_items_text, latest_active_turn_id
from .context import CoreLiveContext, CoreLiveOperationOutcome


async def _reference_input(db: Any, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # user:“不再直接上传附件本身到请求，而且替换为一个绝对路径在用户消息中”
    # +(从已登记附件解析路径，排队和引导使用相同的可持久化文字引用)。
    from ..core_db import CoreAttachment
    result = [dict(item) for item in items]
    text = input_items_text(items)
    for item in items:
        if item.get("type") != "attachment":
            continue
        attachment_id = str(item.get("attachment_id") or item.get("attachmentId") or item.get("id") or "")
        record = await db.get(CoreAttachment, attachment_id)
        if record is None:
            raise ValueError("Attachment not found: " + attachment_id)
        path = Path(record.storage_path).resolve().as_posix()
        if path not in text and str(Path(record.storage_path).resolve()) not in text:
            result.append({"type": "text", "text": "\n@" + json.dumps(path, ensure_ascii=False)})
    return result


def _activate_stored_guidance(context: "CoreLiveContext", event: AppEventEnvelope) -> None:
    """Idempotently activate only durably accepted steering (also on RPC retry)."""
    registry = context.host.runtime_task_registry
    guidance_id = str(event.client_message_id or "")
    if not registry.has_guidance(event.thread_id, run_id=str(event.turn_id or ""), guidance_id=guidance_id):
        registry.accept_guidance(
            event.thread_id, str(event.payload.get("runtime_text") or input_items_text(event.payload.get("runtime_input") or event.payload.get("input") or [])),
            run_id=str(event.turn_id or ""), guidance_id=guidance_id,
        )
    registry.publish_guidance(event.thread_id, run_id=str(event.turn_id or ""), guidance_id=guidance_id)


async def _turn_has_ended(
    context: CoreLiveContext, thread_id: str, turn_id: str
) -> bool:
    """Whether a steer target is a finished turn rather than a paused one."""
    store = context.host.runtime_state_store
    if store is None:
        return True
    try:
        state = await store.get(thread_id)
    except BaseException:
        return False
    if state is None:
        return True
    status = str(getattr(state, "status", "") or "")
    if status == "paused":
        return False
    if status in {"completed", "failed", "cancelled"}:
        return True
    try:
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, thread_id)
        core = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
        turn = (
            (snapshot.get("turns") or {}).get(turn_id)
            or (core.get("turns") or {}).get(turn_id)
            or {}
        )
        return str(turn.get("status") or "") in {
            "completed",
            "failed",
            "cancelled",
            "skipped",
        }
    except BaseException:
        return False


#: Runtime options a refused steer carries into the new user turn, so the text
#: runs with the same model/permissions the client sent it with. Kept in one
#: place: the queue fallback and the direct start must agree.
_FORWARDED_TURN_KEYS = (
    "work_root",
    "workRoot",
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
    "permission_preset",
    "approval_policy",
    "active_tier",
    "tier_tools",
    "allow_access_outside_workdir",
    "active_mode",
    "origin",
)


def _forwarded_turn_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        key: params[key]
        for key in _FORWARDED_TURN_KEYS
        if params.get(key) is not None
    }


def _accepted_turn_id(result: dict[str, Any]) -> str:
    """Read the turn a ``turn/start`` response committed (new or deduplicated)."""
    runtime_start = result.get("runtime_start")
    if isinstance(runtime_start, dict) and runtime_start.get("turn_id"):
        return str(runtime_start["turn_id"])
    for event in result.get("events") or []:
        if not isinstance(event, dict):
            continue
        if str(event.get("method") or "") not in {"turn/accepted", "turn/started"}:
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        turn_id = str(event.get("turn_id") or payload.get("turn_id") or "")
        if turn_id:
            return turn_id
    return ""


async def _submitted_receipt(
    *,
    context: CoreLiveContext,
    thread_id: str,
    client_message_id: str,
) -> dict[str, Any] | None:
    """Durable proof that this client message already became a turn or a queue item.

    user:“保证请求幂等，消息恰好提交一次”+(同一请求的重发、断线重连都读这条
    回执：已经开出去的回合/已经排上的条目不再写第二遍，也不会因为响应丢失而
    被当成新消息重复执行)。
    """
    factory = getattr(context, "session_factory", None)
    persistence = getattr(context, "persistence", None)
    if factory is None or persistence is None:
        return None
    async with factory() as db:
        receipt = await persistence.find_client_event(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            methods={"turn/accepted", "turn/started", "queue/itemAccepted"},
        )
        if receipt is None:
            return None
        if receipt.method == "queue/itemAccepted":
            dispatched = await persistence.find_client_event(
                db,
                thread_id=thread_id,
                client_message_id=f"dispatch:{receipt.item_id}",
                methods={"turn/accepted"},
            )
            if dispatched is None:
                return {"submitted": False, "queued": True, "turn_id": "", "events": []}
            return {
                "submitted": True,
                "queued": False,
                "turn_id": str(dispatched.turn_id or ""),
                "events": [dispatched.to_dict()],
            }
        return {
            "submitted": True,
            "queued": False,
            "turn_id": str(receipt.turn_id or ""),
            "events": [receipt.to_dict()],
        }


async def _deliver_as_next_user_turn(
    *,
    context: CoreLiveContext,
    thread_id: str,
    params: dict[str, Any],
    input_items: list[dict[str, Any]],
    client_message_id: str,
) -> dict[str, Any]:
    """Turn guidance the run can no longer take into a real user message.

    user:“引导遇上结束阶段：当前回合正常结束，引导转为一条新的用户消息，自动开启
    新回合”+(被结束边界拒掉的引导不是排队项、也不是伪造的内部引导事件：它走普通
    发送同一条链路（turn/start），落库的是一条真实用户消息、事件流与生命周期和
    手打一条消息完全一致。只有会话仍被别的回合占着（旧回合正在收尾、或回合被暂停）
    时，才落到队列，由占有会话的那个回合结束时自动发出)。

    Idempotent by ``client_message_id``: a retried request reads the receipt left
    by the first attempt instead of opening a second turn.
    """
    from .background import _logger
    from .turn_start import handle_turn_start_operation

    receipt = await _submitted_receipt(
        context=context, thread_id=thread_id, client_message_id=client_message_id,
    )
    if receipt is not None:
        return {**receipt, "notify": []}
    start_params: dict[str, Any] = {
        "thread_id": thread_id,
        "client_message_id": client_message_id,
        "input": [dict(item) for item in input_items if isinstance(item, dict)],
        **_forwarded_turn_params(params),
    }
    started: dict[str, Any] | None = None
    notify: list[Any] = []
    try:
        outcome = await handle_turn_start_operation(
            request_id=None, params=start_params, context=context,
        )
        response = getattr(outcome, "response", None)
        result = response.get("result") if isinstance(response, dict) else None
        if isinstance(result, dict):
            started = result
            # 和一次普通发送一样，事件既进响应也推给这条连接。
            notify = list(getattr(outcome, "notify_events", None) or [])
    except BaseException:
        _logger.exception(
            "[live:steer] failed to start the next turn thread_id=%s", thread_id
        )
    if started is not None:
        return {
            "submitted": True,
            "queued": False,
            "turn_id": _accepted_turn_id(started),
            "events": list(started.get("events") or []),
            "notify": notify,
        }
    # The session is still owned by another turn (or the input could not become
    # a turn). Either way the text must not be dropped: it waits in the queue as
    # a normal next-turn user message.
    queued = await _queue_refused_guidance(
        context=context,
        thread_id=thread_id,
        params=params,
        input_items=input_items,
        client_message_id=client_message_id,
    )
    return {"submitted": False, "queued": queued, "turn_id": "", "events": [], "notify": []}


async def _queue_refused_guidance(
    *,
    context: CoreLiveContext,
    thread_id: str,
    params: dict[str, Any],
    input_items: list[dict[str, Any]],
    client_message_id: str,
) -> bool:
    """File guidance the live run can no longer take as the next user turn.

    Only used when the session is still owned by another turn (the ending one
    or a paused one), so a normal start is refused: the item is a normal user
    message, and the turn that owns the session dispatches it when it ends.
    """
    from .background import _logger
    from .queue import handle_queue_create_operation
    from .queue_dispatch import _dispatch_next_queue_item
    queue_params: dict[str, Any] = {
        "thread_id": thread_id,
        "client_message_id": client_message_id,
        "input": input_items,
        "mode": "next_turn",
        **_forwarded_turn_params(params),
    }
    try:
        outcome = await handle_queue_create_operation(
            request_id=None, params=queue_params, context=context
        )
    except BaseException:
        _logger.exception(
            "[live:steer] failed to queue refused guidance thread_id=%s", thread_id
        )
        return False
    response = getattr(outcome, "response", None) or {}
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict) or not result.get("queue_item"):
        return False
    state = None
    try:
        if context.runtime_state_store is not None:
            state = await context.runtime_state_store.get(thread_id)
    except BaseException:
        state = None
    if state is not None and str(getattr(state, "status", "") or "") == "paused":
        return True
    idle = False
    try:
        async with context.session_factory() as db:
            snapshot = await context.persistence.load(db, thread_id)
        idle = latest_active_turn_id(snapshot) is None
    except BaseException:
        idle = False
    if idle and context.host.runtime_task_registry.active_run_id(thread_id) is None:
        await _dispatch_next_queue_item(
            context=context,
            thread_id=thread_id,
            work_root=str(params.get("work_root") or params.get("workRoot") or ""),
            completed_turn_id="",
        )
    return True


async def handle_turn_steer_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    from .events import _append_app_event
    from .params import _expected_revision, _include_snapshot_param, _is_active_turn, _load_snapshot_outside_write_lock, _thread_id_from_params
    thread_id = _thread_id_from_params(params)
    turn_id = str(params.get("turn_id") or params.get("turnId") or "").strip()
    client_message_id = str(params.get("client_message_id") or params.get("clientMessageId") or uuid.uuid4().hex)
    input_items = params.get("input") if isinstance(params.get("input"), list) else params.get("input_items")
    if not thread_id or not turn_id or not isinstance(input_items, list):
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id, turn_id and input are required")
        )
    try:
        _expected_revision(params)  # Validate the optional event cursor only.
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    async with context.session_factory() as db:
        try:
            runtime_items = await _reference_input(db, input_items)
        except ValueError as exc:
            return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    text = input_items_text(runtime_items)
    if not text:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="steer input must include text")
        )
    guidance_accepted = False
    include_snapshot = _include_snapshot_param(params)

    async def write(db):
        nonlocal guidance_accepted
        existing = await context.persistence.find_client_event(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            methods={"turn/steered"},
        )
        if existing is not None:
            return "existing", existing
        # Guidance is an idempotent append scoped to turn_id. Live progress
        # changes the session revision between the client's read and this
        # transaction, without invalidating the requested guidance. Check the
        # target run below instead; retain client-message deduplication above.
        registry_run_id = context.host.runtime_task_registry.active_run_id(thread_id)
        # run id 有两种写法（`<thread>:turn:<run>` 与 `<run>`）：这里必须归一后比较，
        # 否则写法不同就会被判成"轮次不匹配"而把一条合法引导挡在门外（2026-10-09）。
        turn_is_active = normalize_run_id(thread_id, registry_run_id) == normalize_run_id(thread_id, turn_id)
        if not turn_is_active:
            # 轮次状态只存于元数据行（turns/requests）；正在运行的回合在这里
            # 直接命中注册表，一次条目表扫描都不需要。
            metadata_state = await context.persistence.load_metadata(db, thread_id)
            if not _is_active_turn(metadata_state, turn_id):
                # user:“回合已经结束：引导直接作为用户消息创建新回合”+(被点名的
                # 回合已不在运行：整条会话没有别的活动回合就是"它已经结束"，还有
                # 别的回合在跑才是真正的轮次不匹配。两者都由调用方改走普通发送)。
                return ("turn_ended" if latest_active_turn_id(metadata_state) is None else "mismatch"), None
        guidance_status = context.host.runtime_task_registry.accept_guidance(
            thread_id,
            text,
            run_id=turn_id,
            guidance_id=client_message_id,
            ready=False,
        )
        if guidance_status not in {"accepted", "duplicate"}:
            # "closed" means the kernel already sealed guidance for its final
            # reply: injecting now would never be consumed. The caller turns
            # this text into the next user turn instead.
            return ("guidance_closed" if guidance_status == "closed" else "run_not_active"), None
        if guidance_status == "accepted":
            guidance_accepted = True
        try:
            event = await _append_app_event(
                db,
                context=context,
                event=AppEventInput(
                    thread_id=thread_id,
                    method="turn/steered",
                    turn_id=turn_id,
                    client_message_id=client_message_id,
                    payload={"type": "turn", "input": input_items, "runtime_input": runtime_items, "runtime_text": text, "guidance_id": client_message_id},
                ),
            )
        except BaseException:
            context.host.runtime_task_registry.retract_guidance(
                thread_id, run_id=turn_id, guidance_id=client_message_id
            )
            guidance_accepted = False
            raise
        return "applied", event

    try:
        write_result = await context.persistence.write(write)
    except BaseException:
        if guidance_accepted:
            context.host.runtime_task_registry.retract_guidance(
                thread_id, run_id=turn_id, guidance_id=client_message_id
            )
        raise
    outcome_kind, payload = write_result
    if outcome_kind in {"existing", "applied"}:
        _activate_stored_guidance(context, payload)
    elif outcome_kind in {"guidance_closed", "run_not_active", "turn_ended", "mismatch"}:
        # The live run cannot take this text as guidance any more: the turn is
        # past its end boundary (guidance already sealed), it has already ended,
        # or the id the client steered is no longer the active turn.
        #
        # user:“引导遇上结束阶段：当前回合正常结束，引导转为一条新的用户消息，自动
        # 开启新回合”+(绝不丢文本、也绝不伪造一条落库的引导事件：这段文字改走普通
        # 发送链路开新回合；会话仍被旧回合占着时排队，由旧回合收尾自动发出)。
        delivered = await _deliver_as_next_user_turn(
            context=context,
            thread_id=thread_id,
            params=params,
            input_items=input_items,
            client_message_id=client_message_id,
        )
        response_payload: dict[str, Any] = {
            "applied": False,
            "submitted": bool(delivered.get("submitted")),
            "queued": bool(delivered.get("queued")),
            "turn_id": str(delivered.get("turn_id") or ""),
            "reason": (
                "turn_ending"
                if outcome_kind == "guidance_closed"
                else "active_turn_mismatch"
                if outcome_kind == "mismatch"
                else "run_not_active"
            ),
            "events": list(delivered.get("events") or []),
        }
        if include_snapshot:
            response_payload["snapshot"] = await _load_snapshot_outside_write_lock(
                context, thread_id
            )
        return CoreLiveOperationOutcome(
            response=rpc_result(request_id, response_payload),
            notify_events=list(delivered.get("notify") or []),
        )
    snapshot: dict[str, Any] | None = None
    if include_snapshot:
        snapshot = await _load_snapshot_outside_write_lock(context, thread_id)
    if outcome_kind == "existing":
        assert isinstance(payload, AppEventEnvelope)
        response_payload: dict[str, Any] = {
            "applied": True,
            "reason": "already_applied",
            "events": [payload.to_dict()],
        }
        if snapshot is not None:
            response_payload["snapshot"] = snapshot
        return CoreLiveOperationOutcome(response=rpc_result(request_id, response_payload))
    if outcome_kind == "mismatch":
        response_payload = {"applied": False, "reason": "active_turn_mismatch", "events": []}
        if snapshot is not None:
            response_payload["snapshot"] = snapshot
        return CoreLiveOperationOutcome(response=rpc_result(request_id, response_payload))
    if outcome_kind == "run_not_active":
        response_payload = {"applied": False, "reason": "run_not_active", "events": []}
        if snapshot is not None:
            response_payload["snapshot"] = snapshot
        return CoreLiveOperationOutcome(response=rpc_result(request_id, response_payload))
    event = payload
    await context.hub.publish(event)
    response_payload = {"applied": True, "reason": "", "events": [event.to_dict()]}
    if snapshot is not None:
        response_payload["snapshot"] = snapshot
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, response_payload),
        publish_events=[event],
    )
