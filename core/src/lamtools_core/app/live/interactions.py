"""Interaction lifecycle, supersession, reconciliation and responses."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

from typing import Any
from lamtools_core.event import RunItemEvent
from sqlalchemy.ext.asyncio import AsyncSession
from ..event_store import AppEventEnvelope
from ..live_protocol import INVALID_REQUEST, rpc_error, rpc_result
from .context import CoreLiveContext, CoreLiveOperationOutcome


async def _interaction_for_request(
    context: CoreLiveContext, thread_id: str, request_id: str
) -> Any | None:
    """Resolve an interaction by its own id, composite id, or tool-call id."""
    if not request_id:
        return None
    store = context.turn_store
    try:
        interaction = await store.get_interaction(request_id)
        if interaction is None and thread_id:
            for candidate in await store.list_interactions(thread_id, limit=200):
                if request_id in {
                    candidate.interaction_id,
                    candidate.legacy_request_id,
                    candidate.tool_call_id,
                }:
                    return candidate
    except BaseException:
        # The interaction table is a read model; a focused host or a pre-migration
        # database may not have it. Fall back to the runtime pending record.
        return None
    return interaction


async def _resolved_interaction_for_request(
    context: CoreLiveContext, thread_id: str, request_id: str
) -> Any | None:
    """Find an already-resolved interaction behind a repeated approval click.

    The UI can keep a submitted card on screen until the next snapshot lands.
    A second click then names a request whose runtime pending record is already
    cleared. That is an idempotent no-op, not a user error.
    """
    interaction = await _interaction_for_request(context, thread_id, request_id)
    if interaction is not None and interaction.terminal:
        return interaction
    return None


async def _append_interaction_lifecycle_event(
    context: CoreLiveContext,
    interaction: Any,
    *,
    state: str = "ending",
    decision: str = "",
    reason: str = "",
) -> None:
    """Publish one decision-pool lifecycle transition.

    ``appearing`` / ``processing`` / ``ending`` is the only card vocabulary.
    The empty envelope turn_id keeps the snapshot reducer's turn-status branch
    out of this write: a card transition must never revive or close a turn.
    """
    from .events import _append_run_item
    import hashlib

    event_id = "interaction:" + hashlib.sha1(
        f"{interaction.interaction_id}:{state}:{decision}:{reason}".encode("utf-8")
    ).hexdigest()
    run_status = {
        "appearing": "pending",
        "processing": "processing",
        "ending": "completed",
    }.get(state, "completed")
    request_status = {
        "appearing": "open",
        "processing": "processing",
        "ending": "resolved",
    }.get(state, "resolved")
    event = RunItemEvent(
        kind=("interaction_update" if state in {"appearing", "processing"} else "approval_response"),
        thread_id=interaction.thread_id,
        event_id=event_id,
        run_id=interaction.run_id or "",
        turn_id="",
        item_id=interaction.interaction_id,
        status=run_status,
        payload={
            "type": "serverRequest",
            "request_id": interaction.interaction_id,
            "interaction_id": interaction.interaction_id,
            "decision_id": interaction.decision_id,
            "sequence": int(interaction.created_seq),
            "tool_call_id": interaction.tool_call_id,
            "legacy_request_id": interaction.tool_call_id,
            "turn_id": interaction.turn_id,
            "kind": interaction.kind,
            "scope": interaction.scope,
            "agent_name": interaction.agent_name,
            "agent_session_id": interaction.agent_session_id,
            "delivered_by": interaction.delivered_by,
            "project_id": interaction.project_id,
            "title": interaction.title,
            "options": [option.to_dict() for option in interaction.options],
            "state": state,
            "lifecycle": state,
            "status": request_status,
            "decision": decision,
            "action": decision,
            "guidance": "",
            "reason": reason,
        },
    )

    async def write(db: AsyncSession) -> AppEventEnvelope:
        return await _append_run_item(db, context=context, event=event)

    envelope = await context.persistence.write(write)
    if context.hub is not None:
        await context.hub.publish(envelope)


async def _close_open_interactions(
    *,
    context: CoreLiveContext,
    thread_id: str,
    reason: str,
    include_member_cards: bool = False,
    turn_id: str | None = None,
) -> int:
    """Cancel this thread's open cards and close them in every window.

    A paused/terminated turn must not leave its cards in the interaction
    index: they would reappear as "queued backups" behind the next question
    and answering one would mismatch the new pending request.

    Member-scoped cards are the member's to answer, not the parent turn's, so
    a pause or a resume closes only the parent's own cards. A terminate passes
    ``include_member_cards=True`` because it promises to discard them.
    """
    from .background import _logger
    if not thread_id:
        return 0
    from lamtools_core.turn.model import MAIN_SCOPE

    try:
        cancelled = await context.turn_store.cancel_interactions(
            thread_id=thread_id,
            turn_id=turn_id,
            reason=reason,
            **({} if include_member_cards else {"scopes": (MAIN_SCOPE,)}),
        )
    except BaseException:
        _logger.exception(
            "[live] failed to cancel open interactions thread_id=%s", thread_id
        )
        return 0
    for interaction in cancelled:
        try:
            await _append_interaction_lifecycle_event(
                context,
                interaction,
                decision="cancelled",
                reason=reason,
            )
        except BaseException:
            _logger.exception(
                "[live] failed to publish closed interaction thread_id=%s id=%s",
                thread_id,
                getattr(interaction, "interaction_id", ""),
            )
    return len(cancelled)


async def _cancel_superseded_interactions(
    context: CoreLiveContext,
    thread_id: str,
    *,
    keep_request_id: str,
    keep_tool_call_id: str,
    reason: str,
) -> int:
    """Close every open card except the runtime's current pending request.

    Restart recovery keeps the answerable card and drops cards left by older
    runs; otherwise the old question reappeared as a queued backup behind the
    current one.
    """
    from .background import _logger
    if not thread_id:
        return 0
    try:
        open_interactions = await context.turn_store.list_open_interactions(
            thread_id=thread_id
        )
    except BaseException:
        _logger.exception(
            "[live] failed to list interactions for reconciliation thread_id=%s",
            thread_id,
        )
        return 0
    cancelled = 0
    for interaction in open_interactions:
        if interaction.interaction_id == keep_request_id:
            continue
        if keep_tool_call_id and interaction.tool_call_id == keep_tool_call_id:
            continue
        resolved = await context.turn_store.resolve_interaction(
            interaction.interaction_id, status="cancelled"
        )
        if resolved is None:
            continue
        try:
            await _append_interaction_lifecycle_event(
                context,
                resolved,
                decision="superseded",
                reason=reason,
            )
        except BaseException:
            _logger.exception(
                "[live] failed to publish superseded interaction thread_id=%s id=%s",
                thread_id,
                interaction.interaction_id,
            )
        cancelled += 1
    return cancelled


async def _execute_inline_approval_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Delegate to the operation catalog when the host owns no turn state.

    Focused embedders and pre-migration databases may not carry the runtime
    state or continuation-job tables. They keep the direct catalog contract;
    the app host always supplies both and uses the durable worker.
    """
    result = await context.operations.execute(
        "approval.respond", dict(params), metadata={"source": "core_live"}
    )
    payload = dict(result.payload or {})
    if result.status != "ok":
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=str(payload.get("error") or result.status),
                data=payload,
            )
        )
    return CoreLiveOperationOutcome(response=rpc_result(request_id, payload))


async def reconcile_open_interactions(
    *, context: CoreLiveContext, thread_id: str | None = None
) -> int:
    """Close decision-pool cards whose runtime pending no longer exists.

    A card is alive only while its request is the runtime's current pending
    request. A completed/cancelled turn, a restarted process, or an old run
    must not leave an answerable-looking card behind. Child-scope cards stay
    while the child session itself is active.
    """
    from .background import _logger
    from .continuations import _pending_approval_record
    store = context.turn_store
    state_store = context.host.runtime_state_store
    try:
        open_interactions = await store.list_open_interactions(thread_id=thread_id)
    except BaseException:
        _logger.exception("[live:reconcile] interaction pool read failed")
        return 0
    closed = 0
    for interaction in open_interactions:
        owner_thread = interaction.thread_id
        state = None
        try:
            if state_store is not None and owner_thread:
                state = await state_store.get(owner_thread)
        except BaseException:
            state = None
        if interaction.scope != "main":
            child_id = interaction.scope.split(":", 1)[-1]
            child_state = None
            try:
                if state_store is not None and child_id:
                    child_state = await state_store.get(child_id)
            except BaseException:
                child_state = None
            if child_state is not None and str(
                getattr(child_state, "status", "") or ""
            ) in {"waiting", "running", "interrupting"}:
                continue
        else:
            pending = _pending_approval_record(state)
            pending_call = (
                pending.get("tool_call")
                if isinstance(pending, dict)
                and isinstance(pending.get("tool_call"), dict)
                else {}
            )
            if (
                state is not None
                and str(getattr(state, "status", "") or "")
                in {"waiting", "running", "interrupting"}
                and pending is not None
                and (
                    interaction.interaction_id
                    == str(pending.get("request_id") or "")
                    or interaction.tool_call_id
                    == str(pending_call.get("id") or "")
                )
            ):
                continue
        resolved = await store.resolve_interaction(
            interaction.interaction_id, status="cancelled"
        )
        if resolved is None:
            continue
        try:
            await _append_interaction_lifecycle_event(
                context,
                resolved,
                state="ending",
                decision="superseded",
                reason="no_live_pending",
            )
        except BaseException:
            _logger.exception(
                "[live:reconcile] failed to publish closed interaction thread_id=%s id=%s",
                owner_thread,
                interaction.interaction_id,
            )
        closed += 1
    return closed


async def handle_interaction_list_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    from .params import _thread_id_from_params
    thread_id = _thread_id_from_params(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    store = context.turn_store
    if bool(params.get("include_resolved")):
        interactions = await store.list_interactions(thread_id)
    else:
        interactions = await store.list_open_interactions(thread_id=thread_id)
    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {"thread_id": thread_id, "interactions": [item.to_dict() for item in interactions]},
        )
    )


async def handle_interaction_respond_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Answer an interaction through the unified broker surface.

    ``approval.respond`` remains the compatibility transport underneath; the
    difference is that the caller names a stable ``interaction_id`` and sends a
    typed answer instead of overloading the approval decision vocabulary.
    """
    from .approvals import handle_approval_respond_operation
    from .params import _thread_id_from_params
    interaction_id = str(
        params.get("interaction_id")
        or params.get("interactionId")
        or params.get("request_id")
        or ""
    ).strip()
    thread_id = _thread_id_from_params(params)
    if not interaction_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="interaction_id is required")
        )
    store = context.turn_store
    interaction = await store.get_interaction(interaction_id)
    answer = params.get("answer") if isinstance(params.get("answer"), dict) else {}
    kind = str(answer.get("kind") or ("option" if answer.get("option_id") else "text"))
    decision = "other_guidance"
    guidance = str(answer.get("text") or "")
    if interaction is not None:
        thread_id = interaction.thread_id
        if kind == "option":
            option = interaction.option(str(answer.get("option_id") or ""))
            if option is None:
                return CoreLiveOperationOutcome(
                    response=rpc_error(
                        request_id, code=INVALID_REQUEST, message="unknown interaction option"
                    )
                )
            decision = option.response if interaction.kind == "approval" and option.id in {"approve", "deny", "trust"} and option.response in {"approve", "deny", "trust"} else "approve_once"
            guidance = option.response or option.label
        elif kind == "skip":
            decision = "skip"
            guidance = "（用户跳过了这个问题，未提供回答。）"
        elif kind == "cancel":
            decision = "deny"
        elif not guidance:
            return CoreLiveOperationOutcome(
                response=rpc_error(request_id, code=INVALID_REQUEST, message="answer text is required")
            )
    params_for_approval: dict[str, Any] = {
        "thread_id": thread_id,
        "request_id": interaction_id,
        "decision": decision,
        "guidance": guidance,
        "include_snapshot": params.get("include_snapshot", False),
    }
    for key in ("expected_revision", "expectedRevision"):
        if key in params:
            params_for_approval[key] = params[key]
    return await handle_approval_respond_operation(
        request_id=request_id,
        params=params_for_approval,
        context=context,
    )
