"""Session permission changes and live runtime control updates."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

from typing import Any
from ..live_protocol import INVALID_REQUEST, rpc_error, rpc_result
from ..runtime_permissions import normalize_permission_preset, with_session_runtime_preferences
from .context import CoreLiveContext, CoreLiveOperationOutcome


async def release_pending_approval_for_preset(
    *,
    context: CoreLiveContext,
    thread_id: str,
    preset: str,
) -> str:
    """Auto-release a parked tool approval when the new preset covers it.

    user:“模式、权限、思考强度在下一步生效（即时生效）”+(权限变化除了刷新审批门，
    还要放行已经停在卡片上的工具；这条规则由权限设置与输入参数组共用)。
    """
    from lamtools_core.tool.operation_levels import pending_auto_approvable

    from .approvals import handle_approval_respond_operation

    if preset not in {"auto", "full_access"} or context.host.runtime_state_store is None:
        return "not_pending"

    approval_status = "not_pending"
    state = await context.host.runtime_state_store.get(thread_id)
    pending = (
        state.metadata.get("pending_approval")
        if state is not None and isinstance(state.metadata, dict)
        else None
    )
    pending_call = pending.get("tool_call") if isinstance(pending, dict) else None
    pending_status = str(pending.get("status") or "waiting") if isinstance(pending, dict) else ""
    approval_request_id = str(
        (
            pending.get("request_id")
            or (pending_call.get("id") if isinstance(pending_call, dict) else "")
        )
        if isinstance(pending, dict)
        else ""
    ).strip()
    if isinstance(pending_call, dict) and str(pending_call.get("name") or "") == "question":
        approval_status = "user_input_required"
    if (
        isinstance(pending_call, dict)
        and str(pending_call.get("name") or "") != "question"
        and pending_status == "waiting"
        and approval_request_id
        and pending_auto_approvable(pending_call, preset)
    ):
        approval_outcome = await handle_approval_respond_operation(
            request_id=None,
            params={
                "thread_id": thread_id,
                "request_id": approval_request_id,
                "decision": "approve_once",
                "guidance": "",
            },
            context=context,
        )
        approval_status = (
            "accepted"
            if isinstance(approval_outcome.response, dict)
            and "result" in approval_outcome.response
            else "failed"
        )
    return approval_status


async def handle_session_permissions_set_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Persist a live session preset and release an existing approval."""
    from .params import _expected_revision, _thread_id_from_params
    thread_id = _thread_id_from_params(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    try:
        preset = normalize_permission_preset(
            params.get("permission_preset", params.get("permissionPreset"))
        )
        expected_revision = _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )

    session_store = context.host.session_store
    if session_store is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="session store is unavailable")
        )
    record = await session_store.get(thread_id)
    if record is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="session not found")
        )
    metadata = with_session_runtime_preferences(
        record.metadata,
        permission_preset=preset,
    )
    patch = getattr(session_store, "patch", None)
    if not callable(patch):
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="session update is unavailable")
        )
    updated = await patch(
        thread_id,
        metadata=metadata,
        expected_revision=expected_revision,
    )
    if updated is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="session not found")
        )

    session_event = {
        "method": "session/updated",
        "thread_id": thread_id,
        "payload": {
            "session": {
                "id": updated.id,
                "metadata": updated.metadata,
            }
        },
    }
    await context.hub.publish(session_event)

    # A permission change can add or remove tools.  Tell the active run so its
    # next step drops the frozen tool array; without this the model keeps
    # seeing the previous set until the next turn.
    registry = getattr(context.host, "runtime_task_registry", None)
    active_run_id = registry.active_run_id(thread_id) if registry is not None else None
    if active_run_id:
        registry.update_settings(
            thread_id,
            {"permission_preset": preset},
            run_id=active_run_id,
        )

    approval_status = await release_pending_approval_for_preset(
        context=context,
        thread_id=thread_id,
        preset=preset,
    )

    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "thread_id": thread_id,
                "permission_preset": preset,
                "approval_status": approval_status,
                "session": updated.to_dict(),
            },
        )
    )
