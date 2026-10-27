"""Session-scoped composer input parameter group updates."""
from __future__ import annotations

from typing import Any

from lamtools_core.llm.reasoning import coerce_reasoning_level

from ..composer_state import (
    COMPOSER_ACTIVE_MODES,
    composer_state_patch,
    live_composer_patch,
    with_composer_state,
)
from ..live_protocol import INVALID_REQUEST, rpc_error, rpc_result
from .context import CoreLiveContext, CoreLiveOperationOutcome

# user:“架构调整，输入框的信息作为‘输入参数组’按会话持久化保存包括模式权限模型思考以及输入信息”
# +(一个写入入口同时完成三件事：落库到会话、必要时放行待审批卡片、通知运行中的回合下一步应用。)


def _first_present(*values: object) -> object | None:
    for value in values:
        if value is not None:
            return value
    return None


async def handle_session_composer_set_operation(
    *,
    request_id: int | str | None,
    params: dict[str, Any],
    context: CoreLiveContext,
) -> CoreLiveOperationOutcome:
    """Persist the composer parameter group and notify the active run."""
    from ..runtime_permissions import normalize_permission_preset
    from .params import _expected_revision, _thread_id_from_params
    from .permissions import release_pending_approval_for_preset

    thread_id = _thread_id_from_params(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )

    raw_mode = _first_present(params.get("active_mode"), params.get("activeMode"))
    if raw_mode is not None and str(raw_mode).strip() not in COMPOSER_ACTIVE_MODES:
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=f"active_mode must be one of {', '.join(COMPOSER_ACTIVE_MODES)}",
            )
        )

    raw_level = _first_present(params.get("reasoning_level"), params.get("reasoningLevel"))
    if raw_level is not None and coerce_reasoning_level(raw_level) is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="reasoning_level is not a supported level",
            )
        )

    raw_shallow = _first_present(
        params.get("shallow_thinking_enabled"),
        params.get("shallowThinkingEnabled"),
    )
    if raw_shallow is not None and not isinstance(raw_shallow, bool):
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="shallow_thinking_enabled must be a boolean",
            )
        )

    raw_preset = _first_present(
        params.get("permission_preset"),
        params.get("permissionPreset"),
    )
    if raw_preset is not None:
        try:
            normalize_permission_preset(raw_preset)
        except ValueError as exc:
            return CoreLiveOperationOutcome(
                response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
            )

    try:
        expected_revision = _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )

    session_store = context.host.session_store
    if session_store is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id, code=INVALID_REQUEST, message="session store is unavailable"
            )
        )
    record = await session_store.get(thread_id)
    if record is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="session not found")
        )

    composer = composer_state_patch(
        record.metadata,
        active_mode=raw_mode,
        model_id=_first_present(params.get("model_id"), params.get("modelId")),
        reasoning_level=raw_level,
        shallow_thinking_enabled=raw_shallow,
        permission_preset=raw_preset,
    )
    metadata = with_composer_state(record.metadata, composer)

    patch = getattr(session_store, "patch", None)
    if not callable(patch):
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id, code=INVALID_REQUEST, message="session update is unavailable"
            )
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

    await context.hub.publish(
        {
            "method": "session/updated",
            "thread_id": thread_id,
            "payload": {
                "session": {
                    "id": updated.id,
                    "metadata": updated.metadata,
                }
            },
        }
    )

    approval_status = await release_pending_approval_for_preset(
        context=context,
        thread_id=thread_id,
        preset=composer["permission_preset"],
    )

    raw_apply = _first_present(
        params.get("apply_to_running"),
        params.get("applyToRunning"),
    )
    apply_to_running = raw_apply is not False
    applied_to_run = False
    if apply_to_running:
        registry = getattr(context.host, "runtime_task_registry", None)
        active_run_id = registry.active_run_id(thread_id) if registry is not None else None
        if active_run_id:
            applied_to_run = bool(
                registry.update_settings(
                    thread_id,
                    live_composer_patch(composer),
                    run_id=active_run_id,
                )
            )

    return CoreLiveOperationOutcome(
        response=rpc_result(
            request_id,
            {
                "thread_id": thread_id,
                "composer_state": composer,
                "approval_status": approval_status,
                "applied_to_run": applied_to_run,
                "session": updated.to_dict(),
            },
        )
    )


__all__ = ["handle_session_composer_set_operation"]
