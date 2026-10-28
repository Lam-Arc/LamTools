"""Turn acceptance and explicit continuation of paused turns."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
import time as time_module
import uuid
from typing import Any
from ..event_store import AppEventInput
from ..live_protocol import INVALID_REQUEST, rpc_error, rpc_result
from ..queue_state import latest_active_turn_id
from ..runtime_permissions import overlay_runtime_permissions
from ..turn_acceptance import TURN_ACCEPTED_METHODS, build_turn_acceptance_plan
from .context import CoreLiveContext, CoreLiveOperationOutcome


def _resume_target_turn(snapshot: dict[str, Any], requested: str) -> tuple[dict[str, Any], str]:
    """Pick the paused turn a resume request names, not the highest seq."""
    turns = snapshot.get("turns") if isinstance(snapshot.get("turns"), dict) else {}
    core = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
    core_turns = core.get("turns") if isinstance(core.get("turns"), dict) else {}
    all_turns = {**core_turns, **turns}
    requested_record = all_turns.get(requested) if requested else None
    if isinstance(requested_record, dict) and str(requested_record.get("status") or "") == "paused":
        latest = requested_record
    else:
        paused_turns = [
            turn for turn in all_turns.values()
            if isinstance(turn, dict) and str(turn.get("status") or "") == "paused"
        ]
        latest = max(
            paused_turns,
            key=lambda turn: int(turn.get("seq") or turn.get("last_seq") or 0),
            default={},
        )
    return latest, str(latest.get("turn_id") or requested or "")


async def handle_turn_resume_operation(
    *, request_id: int | str | None, params: dict[str, Any], context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Explicit continuation of the latest interrupted turn, using committed history."""
    from .background import _LIVE_BACKGROUND_TASKS, _spawn_live_background
    from .interactions import _close_open_interactions
    from .params import _expected_revision, _thread_id_from_params
    from .runtime_tasks import _mirror_turn_started, _start_runtime_task
    from .turn_options import _resolve_imagegen_config, _resolve_turn_approval_policy
    from .turn_pause import _resume_session_members
    thread_id = _thread_id_from_params(params)
    requested = str(params.get("turn_id") or params.get("turnId") or "")
    registry = context.host.runtime_task_registry
    if not thread_id:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required"))
    try:
        _expected_revision(params)  # append operation, same validation as turn.start
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
    # Stop acknowledges before settlement. Do not race its detached writers or
    # claim release, particularly when the logical Turn ID is reused. A settling
    # task can spawn another terminal writer, so drain the thread's set fully.
    while True:
        pending = [task for task in tuple(_LIVE_BACKGROUND_TASKS)
                   if not task.done() and task.get_name().endswith(f":{thread_id}")]
        if not pending:
            break
        await asyncio.gather(*(asyncio.shield(task) for task in pending), return_exceptions=True)
    client_id = str(params.get("client_message_id") or params.get("clientMessageId") or uuid.uuid4().hex)
    resolved = await _resolve_turn_approval_policy(context=context, params={"thread_id": thread_id})
    imagegen_config = await _resolve_imagegen_config(context=context)
    # The text typed while the turn was paused. It rides the same turn as a
    # supplementary user input, which is the whole point of sending instead of
    # pressing Continue: one action, and the model sees both.
    raw_input = params.get("input")
    extra_input = [dict(item) for item in raw_input if isinstance(item, dict)] if isinstance(raw_input, list) else []
    claimed = ""

    async def write(db):
        nonlocal claimed
        existing = await context.persistence.find_client_event(
            db, thread_id=thread_id, client_message_id=client_id, methods={"turn/started"},
        )
        if existing is not None:
            return existing, None
        snapshot = await context.persistence.load_metadata(db, thread_id)
        latest, turn_id = _resume_target_turn(snapshot, requested)
        if (not turn_id or (requested and requested != turn_id)
                or latest.get("status") != "paused"):
            # Only a paused turn continues. A terminated one is final on
            # purpose: the user asked for it, and re-running it silently would
            # undo that decision.
            raise ValueError("latest turn is not resumable")
        if latest_active_turn_id(snapshot) or registry.active_run_id(thread_id):
            raise ValueError("session has an active turn")
        state = await context.runtime_state_store.get(thread_id) if context.runtime_state_store else None
        from lamtools_core.runtime_owner import LIVE_RUN_STATES, owner_is_live, read_owner
        if state is not None and state.status in LIVE_RUN_STATES and owner_is_live(read_owner(state.metadata)):
            raise ValueError("previous execution is still settling")
        runtime_snapshot = overlay_runtime_permissions(
            latest.get("runtime_snapshot") or {}, resolved["runtime_snapshot"]
        )
        # user:“模式、权限、思考强度在下一步生效（即时生效）”+(暂停期间改的模式/
        # 思考/浅层在恢复后的下一步生效；模型保持暂停那一回合的值)。
        from ..composer_state import overlay_composer_controls

        runtime_snapshot = overlay_composer_controls(
            runtime_snapshot,
            resolved.get("session_metadata") or {},
        )
        if not registry.accept_run(thread_id, turn_id, turn_id=turn_id):
            raise ValueError("session has an active turn")
        claimed = turn_id
        execution_id = uuid.uuid4().hex
        get_history = getattr(context.runtime_state_store, "get_history", None)
        history = await get_history(thread_id) if callable(get_history) else []
        original_committed = any(
            row.get("role") in {"user", "system"}
            and row.get("metadata", {}).get("turn_id") == turn_id
            and row.get("metadata", {}).get("origin") != "turn_resume"
            for row in history
        )
        from ..queue_state import input_item_attachment_ids
        # Stop can win before the initial kernel input checkpoint. The accepted
        # input is already committed; use it as system continuation context then.
        original_input = (latest.get("input") or []) if not original_committed else []
        # user:“把它作为一个引导信息发进去”+(恢复只携带尚未入历史的原任务；
        # 补充消息持久化为普通引导，由现有消费、去重和显示流程处理)。
        carry_input = original_input
        carry_text = ""
        if carry_input:
            prepared_carry = await context.host.member_hooks.prepare_turn_input(
                thread_id=thread_id, params={**runtime_snapshot, "work_root": latest.get("work_root") or ""},
                input_items=carry_input,
            )
            carry_text = prepared_carry.runtime_text
        event = await context.persistence.append(db, AppEventInput(
            thread_id=thread_id, turn_id=turn_id, method="turn/started", client_message_id=client_id,
            payload={"status": "running", "resumed": True, "run_id": execution_id},
        ))
        if extra_input:
            prepared_guidance = await context.host.member_hooks.prepare_turn_input(
                thread_id=thread_id,
                params={**runtime_snapshot, "work_root": latest.get("work_root") or ""},
                input_items=extra_input,
            )
            guidance_id = f"resume-guide:{client_id}"
            await context.persistence.append(db, AppEventInput(
                thread_id=thread_id, turn_id=turn_id, method="turn/steered",
                client_message_id=guidance_id,
                payload={"type": "turn", "input": prepared_guidance.visible_input,
                         "runtime_input": prepared_guidance.runtime_input,
                         "guidance_id": guidance_id},
            ))
        runtime_start = {
            **runtime_snapshot, "runtime_snapshot": runtime_snapshot,
            "thread_id": thread_id, "turn_id": turn_id, "run_id": execution_id,
            # Pure continuation: the committed history already carries the task
            # and every finished step, so the resumed run adds no synthetic
            # instruction. Only the original task rides along when the pause
            # won the race against its first checkpoint; supplements are steering.
            "text": carry_text,
            "input": carry_input,
            "user_item_id": f"{turn_id}:input:{client_id}" if carry_input else "",
            "attachment_ids": input_item_attachment_ids(carry_input),
            "goal_id": runtime_snapshot.get("goal_id") or (
                state.metadata.get("goal_id", "") if state is not None
                and str(state.metadata.get("turn_id") or state.run_id) == turn_id else ""
            ),
            "origin": "turn_resume", "imagegen_config": imagegen_config, "work_root": latest.get("work_root") or resolved.get("work_root") or "",
        }
        return event, runtime_start

    try:
        event, runtime_start = await context.persistence.write(write)
    except BaseException as exc:
        if claimed:
            registry.release_run(thread_id, run_id=claimed)
        if isinstance(exc, ValueError):
            return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))
        raise
    if runtime_start is not None:
        # Cards from the paused run are superseded by this resume. Closing them
        # must run outside the write coordinator: cancel_interactions and the
        # closure event are writes themselves, and nesting them under this
        # transaction deadlocked the resume.
        await _close_open_interactions(
            context=context, thread_id=thread_id, reason="turn_resumed"
        )
    # The parked turn is about to run again: clear the pause request so the
    # resumed kernel does not immediately park on the same signal.
    reset_pause = getattr(context.host.runtime_task_registry, "reset_pause_event", None)
    if callable(reset_pause):
        reset_pause(thread_id)
    await context.hub.publish(event)
    if runtime_start is None:
        return CoreLiveOperationOutcome(response=rpc_result(request_id, {
            "turn_id": event.turn_id, "events": [event.to_dict()],
        }))
    failure = await _start_runtime_task(context=context, runtime_start=runtime_start)
    if failure is None:
        await _mirror_turn_started(
            context=context,
            thread_id=thread_id,
            turn_id=str(runtime_start.get("turn_id") or ""),
            run_id=str(runtime_start.get("run_id") or ""),
            input_payload={"text": str(runtime_start.get("text") or "")},
            resumed=True,
        )
    # One press continues the whole session: the members a pause parked start
    # again from their own committed history. Members waiting on a question are
    # untouched, that card is still the user's to answer. Detached so the
    # response never waits on member bookkeeping.
    _spawn_live_background(
        _resume_session_members(context=context, thread_id=thread_id),
        label="resume-session-members",
        thread_id=thread_id,
    )
    events = [event] + ([failure[0]] if failure else [])
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, {"turn_id": runtime_start["turn_id"], "events": [item.to_dict() for item in events]}),
        notify_events=events, runtime_start=runtime_start,
    )


async def handle_turn_start_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    from .background import _logger
    from .events import _app_event_input, _get_running_loop
    from .params import _expected_revision, _include_snapshot_param, _load_snapshot_outside_write_lock
    from .runtime_tasks import _auto_title_session, _fail_runtime_start, _mirror_turn_started, _start_runtime_task
    from .terminal_state import _paused_turn_id
    from .turn_options import _resolve_imagegen_config, _resolve_turn_approval_policy, _runtime_snapshot_with_turn_options
    thread_id = str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()
    client_message_id = str(params.get("client_message_id") or params.get("clientMessageId") or uuid.uuid4().hex)
    # Provenance of an automatic (non-user) turn, e.g. "member_wake". It rides the
    # acceptance and runtime payloads so the projection can mark the turn and its
    # input item, and the kernel can preserve the wake as a marked system-history
    # entry at the model boundary.
    turn_origin = str(params.get("origin") or params.get("turn_origin") or "").strip()
    input_items = params.get("input")
    if not thread_id or not isinstance(input_items, list):
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id and input are required")
        )
    # user:“手动终止后才能继续”+(失败收尾遇到暂时性数据库故障时，下次发送先补写终态，无需手动终止)。
    for (pending_thread, pending_turn), failure_message in list(context.host.pending_terminal_failures.items()):
        if pending_thread == thread_id and not context.host.runtime_task_registry.active_run_id(thread_id):
            await _fail_runtime_start(context=context, thread_id=thread_id,
                                      turn_id=pending_turn, message=failure_message)
    try:
        _expected_revision(params)  # 形状校验；回合创建是幂等追加，见 write 说明
    except ValueError as exc:
        return CoreLiveOperationOutcome(response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc)))

    turn_id = str(params.get("turn_id") or params.get("turnId") or f"{thread_id}:turn:{uuid.uuid4().hex[:12]}")
    user_item_id = str(params.get("user_item_id") or params.get("userItemId") or f"{turn_id}:user")
    run_claimed = False

    # Capture the session's initial permission state in the acceptance event.
    # Running toolboxes refresh these fields from the session before each tool
    # boundary, while the remaining runtime options stay turn-scoped.
    try:
        resolved = await _resolve_turn_approval_policy(context=context, params={**params, "thread_id": thread_id})
    except ValueError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    # user:“架构调整，输入框的信息作为‘输入参数组’按会话持久化保存”+(显式参数
    # 优先；CLI/自动回合没带模式、模型、档位时，从该会话自己的参数组补齐)。
    from ..composer_state import inherit_composer_params

    params = inherit_composer_params(params, resolved.get("session_metadata") or {})
    # Clients and automatic continuations need not repeat the project path on
    # every message. Resolve it before composer preparation and persist the
    # same root that the tools/runtime will receive.
    if not (params.get("work_root") or params.get("workRoot")) and resolved.get("work_root"):
        params = {**params, "work_root": resolved["work_root"]}
    try:
        prepared = await context.host.member_hooks.prepare_turn_input(
            thread_id=thread_id, params=params, input_items=input_items,
        )
    except ValueError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    turn_runtime_snapshot = _runtime_snapshot_with_turn_options(
        resolved["runtime_snapshot"],
        params=params,
        active_mode=resolved.get("active_mode"),
    )


    async def write(db):
        nonlocal run_claimed
        _w0 = time_module.perf_counter()
        existing = await context.persistence.find_client_event(
            db,
            thread_id=thread_id,
            client_message_id=client_message_id,
            methods=TURN_ACCEPTED_METHODS,
        )
        _w1 = time_module.perf_counter()
        _logger.info("[PERF:turn_start:write] find_client_event=%.3fs", _w1 - _w0)
        if existing is not None:
            return ("existing", existing, None, None, None, False)

        _w2 = time_module.perf_counter()
        # 回合创建是幂等追加（client_message_id 去重）：它只追加 turn/accepted、
        # user item 与 running 状态，不读改写任何共享字段，真正的并发保护是下面的
        # 活跃回合判定（注册表 + 元数据行）。因此这里不做修订号 CAS：活跃回合持续
        # 追加事件会把会话修订号一路推高，而本写又要排队数秒才执行，客户端在发起
        # RPC 前读到的修订号几乎必然落后，CAS 会把一条合法的新回合打成
        # REVISION_CONFLICT，还盖住了本该返回的 SESSION_BUSY（2026-10-12）。
        # 只需要轮次状态与顶层用户条目顺序（活跃轮判定 + 首条消息判定），
        # 全部存放在元数据行——这里曾装配整个会话的条目表，大会话上阻塞写锁秒级。
        snapshot = await context.persistence.load_metadata(db, thread_id)
        _w3 = time_module.perf_counter()
        _logger.info("[PERF:turn_start:write] load_metadata=%.3fs", _w3 - _w2)
        active_run_id = latest_active_turn_id(snapshot) or context.host.runtime_task_registry.active_run_id(thread_id)
        if active_run_id:
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message="session has an active turn",
                    data={
                        "code": "SESSION_BUSY",
                        "reason": "active_turn_exists",
                        "active_run_id": active_run_id,
                    },
                )
            )
        # A continuation of the paused turn runs through this same executor, so
        # the gate below must let its own resume pass and only refuse a *new*
        # turn started behind the paused one.
        is_continuation = str(
            params.get("origin") or params.get("turn_origin") or ""
        ).strip() == "turn_resume"
        paused_turn_id = "" if is_continuation else _paused_turn_id(snapshot)
        if paused_turn_id:
            # One session, one turn: a paused turn owns the session until the
            # user continues or terminates it. Clients turn a send into a
            # continue, so reaching here means a caller tried to start a second
            # turn behind the paused one.
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message="session has a paused turn",
                    data={
                        "code": "SESSION_PAUSED",
                        "reason": "paused_turn_exists",
                        "paused_turn_id": paused_turn_id,
                    },
                )
            )
        # Detect a first message: the snapshot has no items yet. Captured before
        # the user item is appended so it reflects the pre-turn state.
        prior_item_order = snapshot.get("item_order") if isinstance(snapshot, dict) else None
        is_first_message = not prior_item_order
        if not context.host.runtime_task_registry.accept_run(thread_id, turn_id, turn_id=turn_id):
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message="session has an active turn",
                    data={
                        "code": "SESSION_BUSY",
                        "reason": "active_turn_exists",
                        "active_run_id": context.host.runtime_task_registry.active_run_id(thread_id),
                    },
                )
            )

        run_claimed = True
        try:
            materialized = await context.host.member_hooks.materialize_turn(
                db=db,
                thread_id=thread_id,
                turn_id=turn_id,
                user_item_id=user_item_id,
                client_message_id=client_message_id,
                prepared=prepared,
                params=params,
            )
            if materialized.turn_id != turn_id or materialized.user_item_id != user_item_id:
                raise ValueError("member turn materialization must preserve Core acceptance ids")
            plan = build_turn_acceptance_plan(
                thread_id=thread_id,
                turn_id=turn_id,
                user_item_id=user_item_id,
                client_message_id=client_message_id,
                input_items=prepared.visible_input,
                work_root=prepared.work_root,
                turn_payload_extra={
                    **materialized.turn_payload_extra,
                    "runtime_snapshot": turn_runtime_snapshot,
                    **({"origin": turn_origin} if turn_origin else {}),
                },
                user_payload_extra={
                    **materialized.user_payload_extra,
                    **(
                        # An automatic turn's input is a SYSTEM message, not the
                        # user's: the interface must not render it as their text.
                        {"origin": turn_origin, "type": "systemMessage", "role": "system"}
                        if turn_origin
                        else {}
                    ),
                },
                include_turn_status=materialized.include_turn_status,
            )
            _w4 = time_module.perf_counter()
            envelopes = await context.persistence.append_batch(
                db,
                app_events=[_app_event_input(plan.turn_accepted), _app_event_input(plan.user_item)],
                run_item_events=[plan.running_status],
            )
            _w5 = time_module.perf_counter()
            _logger.info("[PERF:turn_start:write] append_batch=%.3fs", _w5 - _w4)
            accepted, user, running = envelopes[0], envelopes[1], envelopes[2]
            # 响应快照不再在写锁内装配（曾有一次全量 load + 一次 return_state 全量
            # load）；需要快照的调用方在事务提交后于锁外装配。
            return ("applied", accepted, user, running, materialized, is_first_message)
        except BaseException:
            context.host.runtime_task_registry.release_run(thread_id, run_id=turn_id)
            run_claimed = False
            raise

    _t0 = time_module.perf_counter()
    try:
        write_result = await context.persistence.write(write)
    except BaseException:
        if run_claimed:
            context.host.runtime_task_registry.release_run(thread_id, run_id=turn_id)
        raise
    _t1 = time_module.perf_counter()
    _logger.info("[PERF:turn_start] persistence.write=%.3fs thread_id=%s", _t1 - _t0, thread_id)
    if isinstance(write_result, CoreLiveOperationOutcome):
        return write_result
    include_snapshot = _include_snapshot_param(params)
    response_snapshot: dict[str, Any] | None = None
    outcome_kind, accepted, user, running, materialized, is_first_message = write_result
    if include_snapshot:
        response_snapshot = await _load_snapshot_outside_write_lock(context, thread_id)
    if outcome_kind == "existing":
        response_payload: dict[str, Any] = {"events": [accepted.to_dict()]}
        if response_snapshot is not None:
            response_payload["snapshot"] = response_snapshot
        return CoreLiveOperationOutcome(
            response=rpc_result(request_id, response_payload),
            notify_events=[accepted],
        )

    # Best-effort: generate a short title from the first user message.
    if is_first_message and context.host.llm_client and prepared.runtime_text:
        loop = _get_running_loop()
        loop.create_task(_auto_title_session(
            context=context,
            thread_id=thread_id,
            first_message=prepared.runtime_text,
            model_id=str(params.get("model_id") or params.get("modelId") or "").strip(),
        ))

    imagegen_config = await _resolve_imagegen_config(context=context)
    runtime_start = {
        "thread_id": thread_id,
        "turn_id": turn_id,
        "user_message_id": user_item_id,
        "text": prepared.runtime_text,
        "input": prepared.runtime_input,
        "work_root": prepared.work_root,
        "approval_policy": turn_runtime_snapshot["approval_policy"],
        "active_tier": turn_runtime_snapshot["active_tier"],
        "tier_tools": resolved["tier_tools"],
        "active_mode": resolved["active_mode"],
        "instructions": str(params.get("instructions") or ""),
        "request_local_late_context": str(params.get("request_local_late_context") or ""),
        "allow_access_outside_workdir": turn_runtime_snapshot["allow_access_outside_workdir"],
        "permission_preset": turn_runtime_snapshot["permission_preset"],
        "runtime_snapshot": turn_runtime_snapshot,
        "imagegen_config": imagegen_config,
        "model_id": str(params.get("model_id") or params.get("modelId") or ""),
        "reasoning_level": str(params.get("reasoning_level") or params.get("reasoningLevel") or ""),
        "thinking_enabled": params.get("thinking_enabled") if isinstance(params.get("thinking_enabled"), bool) else None,
        "thinking_budget": params.get("thinking_budget") if isinstance(params.get("thinking_budget"), int) else None,
        "reasoning_effort": str(params.get("reasoning_effort") or params.get("reasoningEffort") or ""),
        "shallow_thinking_enabled": (
            params.get("shallow_thinking_enabled")
            if isinstance(params.get("shallow_thinking_enabled"), bool)
            else None
        ),
        "context_window_tokens": (
            params.get("context_window_tokens")
            if isinstance(params.get("context_window_tokens"), int)
            and not isinstance(params.get("context_window_tokens"), bool)
            and params.get("context_window_tokens") > 0
            else None
        ),
        "goal_id": str(params.get("goal_id") or params.get("goalId") or "").strip(),
        "max_tokens": (
            params.get("max_tokens")
            if isinstance(params.get("max_tokens"), int)
            and not isinstance(params.get("max_tokens"), bool)
            and params.get("max_tokens") > 0
            else None
        ),
        "temperature": (
            float(params.get("temperature"))
            if isinstance(params.get("temperature"), (int, float))
            and not isinstance(params.get("temperature"), bool)
            else None
        ),
        "compact_trigger_tokens": (
            params.get("compact_trigger_tokens")
            if isinstance(params.get("compact_trigger_tokens"), int)
            and not isinstance(params.get("compact_trigger_tokens"), bool)
            and params.get("compact_trigger_tokens") > 0
            else None
        ),
        "compact_limit_tokens": (
            params.get("compact_limit_tokens")
            if isinstance(params.get("compact_limit_tokens"), int)
            and not isinstance(params.get("compact_limit_tokens"), bool)
            and params.get("compact_limit_tokens") > 0
            else None
        ),
        **prepared.runtime_extras,
        **materialized.runtime_extras,
        **({"origin": turn_origin} if turn_origin else {}),
    }
    events = [accepted, user, running]
    _t2 = time_module.perf_counter()
    for event in events:
        await context.hub.publish(event)
    _t3 = time_module.perf_counter()
    _logger.info("[PERF:turn_start] hub.publish(3)=%.3fs", _t3 - _t2)
    await _mirror_turn_started(
        context=context,
        thread_id=thread_id,
        turn_id=turn_id,
        run_id=turn_id,
        input_payload={"text": str(runtime_start.get("text") or "")},
        resumed=False,
    )
    start_failure = await _start_runtime_task(context=context, runtime_start=runtime_start)
    _t4 = time_module.perf_counter()
    _logger.info("[PERF:turn_start] _start_runtime_task=%.3fs", _t4 - _t3)
    if start_failure is not None:
        failure_event, failure_snapshot = start_failure
        events.append(failure_event)
        # 失败终态快照比提交后的常规快照更新（含 failed 终态），必须覆盖。
        if include_snapshot:
            response_snapshot = failure_snapshot
    _logger.info("[PERF:turn_start] total=%.3fs thread_id=%s", _t4 - _t0, thread_id)
    _logger.info("[live:handle_turn_start] dispatched background task thread_id=%s turn_id=%s model=%s",
                  thread_id, turn_id, runtime_start.get("model_id") or "default")
    response_payload = {
        "events": [event.to_dict() for event in events],
        "runtime_start": runtime_start,
    }
    if response_snapshot is not None:
        response_payload["snapshot"] = response_snapshot
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, response_payload),
        notify_events=events,
        runtime_start=runtime_start,
    )
