"""Composer command execution, including controlled context compaction."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from lamtools_core.composer_commands import (
    build_composer_command_catalog,
    default_core_resource_roots,
    normalize_command_name,
)
from lamtools_core.event import RunItemEvent
from sqlalchemy.ext.asyncio import AsyncSession
from ..command_execution import execute_command_action
from ..event_store import AppEventEnvelope, CORE_RUN_ITEM_METHOD
from ..live_member import DefaultCoreLiveMemberHooks
from ..live_protocol import INVALID_REQUEST, rpc_error, rpc_result
from ..persistence_host import RevisionConflictError
from .context import CoreLiveContext, CoreLiveOperationOutcome


async def handle_command_catalog_operation(
    *, request_id: int | str | None, params: dict[str, Any], context: "CoreLiveContext"
) -> "CoreLiveOperationOutcome":
    commands = await _live_command_catalog(context=context, params=params)
    return CoreLiveOperationOutcome(response=rpc_result(request_id, {"commands": commands}))


async def handle_command_execute_operation(
    *, request_id: int | str | None, params: dict[str, Any], context: "CoreLiveContext"
) -> "CoreLiveOperationOutcome":
    from .context import SessionBusyError
    from .params import _command_arguments, _command_kind, _expected_revision, _thread_id_from_params
    thread_id = _thread_id_from_params(params)
    command = normalize_command_name(params.get("command"))
    if not thread_id or not command:
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="thread_id and command are required",
            )
        )
    actions = context.host.member_hooks.command_action_handlers()
    catalog = {
        normalize_command_name(item.get("name")): item
        for item in await _live_command_catalog(context=context, params=params)
        if isinstance(item, dict) and normalize_command_name(item.get("name"))
    }
    definition = catalog.get(command)
    # Allow commands registered as actions even if the catalog (which may
    # go through operations) doesn't list them — e.g. "compact" registered
    # via member_hooks.command_action_handlers() or command.execute operation.
    if definition is None and command not in actions and not context.operations.has("command.execute"):
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=f"Command not available: {command}")
        )
    if definition is not None and _command_kind(definition) != "action":
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=f"Command is not executable as an action: {command}",
            )
        )
    arguments = _command_arguments(params)
    if definition is not None and arguments and not bool(definition.get("accepts_args")):
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=f"Command does not accept arguments: {command}",
            )
        )
    try:
        expected_revision = _expected_revision(params)
    except ValueError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    work_root = str(params.get("work_root") or params.get("workRoot") or "")
    try:
        # The CAS check is deliberately made immediately before dispatching
        # the action.  The live host serializes ordinary commands for this
        # session, while compact uses the runtime registry because it must
        # remain cancellable by turn.cancel.
        await context.persistence.write(
            lambda db: context.persistence.assert_revision(db, thread_id, expected_revision)
        )
        if command == "compact":
            result, snapshot = await _execute_compact_live_command(
                context=context,
                thread_id=thread_id,
                work_root=work_root,
                actions=actions,
                params={**params, "arguments": arguments},
            )
        else:
            result = await _execute_live_command_action(
                context=context,
                command=command,
                thread_id=thread_id,
                work_root=work_root,
                actions=actions,
                params=params,
                arguments=arguments,
            )
            async with context.session_factory() as db:
                snapshot = await context.persistence.load(db, thread_id)
    except RevisionConflictError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message="Revision conflict; refresh the session and retry explicitly",
                data=exc.data,
            )
        )
    except SessionBusyError as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=str(exc),
                data=exc.data,
            )
        )
    except (LookupError, RuntimeError, TypeError, ValueError) as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    response_payload: dict[str, Any] = {"result": result}
    if params.get("include_snapshot") is not False:
        response_payload["snapshot"] = snapshot
    return CoreLiveOperationOutcome(response=rpc_result(request_id, response_payload))


async def _live_command_catalog(
    *, context: CoreLiveContext, params: dict[str, Any]
) -> list[dict[str, Any]]:
    if isinstance(context.host.member_hooks, DefaultCoreLiveMemberHooks) and context.operations.has("command.catalog"):
        result = await context.operations.execute("command.catalog", params, metadata={"source": "core_live"})
        if result.status != "ok":
            raise ValueError(str(result.payload.get("error") or result.status))
        commands = result.payload.get("commands")
        return [dict(item) for item in commands if isinstance(item, dict)] if isinstance(commands, list) else []
    hooks = context.host.member_hooks
    work_root = params.get("work_root") or params.get("workRoot")
    commands = build_composer_command_catalog(
        core_roots=default_core_resource_roots(),
        member_roots=[Path(item) for item in hooks.command_member_roots()],
        work_root=work_root if isinstance(work_root, (str, Path)) else None,
        skill_registry=hooks.command_skill_registry(),
        skill_state_store=(
            hooks.command_skill_state_store()
            if callable(getattr(hooks, "command_skill_state_store", None))
            else None
        ),
    )
    return [command.to_dict() for command in commands]


async def _execute_live_command_action(
    *,
    context: CoreLiveContext,
    command: str,
    thread_id: str,
    work_root: str,
    actions: dict[str, Any],
    params: dict[str, Any],
    arguments: str = "",
    on_event: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    if command in actions:
        return await execute_command_action(
            command=command,
            thread_id=thread_id,
            work_root=work_root,
            arguments=arguments,
            handlers=actions,
            on_event=on_event,
        )
    if not context.operations.has("command.execute"):
        raise ValueError(f"Command is not executable as an action: {command}")
    result = await context.operations.execute(
        "command.execute",
        {
            **params,
            "thread_id": thread_id,
            "command": command,
            "arguments": arguments,
            "_on_event": on_event,
        },
        metadata={"source": "core_live"},
    )
    if result.status != "ok":
        raise ValueError(str(result.payload.get("error") or result.status))
    nested = result.payload.get("result")
    return dict(nested) if isinstance(nested, dict) else dict(result.payload)


async def _execute_compact_live_command(
    *,
    context: CoreLiveContext,
    thread_id: str,
    work_root: str,
    actions: dict[str, Any],
    params: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
    from .context import SessionBusyError
    ids = _compact_command_ids(
        thread_id,
        client_command_id=str(params.get("client_command_id") or params.get("clientCommandId") or ""),
    )
    registry = context.host.runtime_task_registry
    if not registry.accept_run(thread_id, ids["run_id"], turn_id=ids.get("turn_id") or ""):
        raise SessionBusyError(
            reason="active_turn_exists",
            message="A context compaction is already running",
            active_run_id=registry.active_run_id(thread_id) or "",
        )
    operation_task = asyncio.create_task(_execute_claimed_compact_live_command(
        context=context,
        thread_id=thread_id,
        work_root=work_root,
        actions=actions,
        params=params,
        ids=ids,
    ))
    if not registry.register(
        thread_id, operation_task, run_id=ids["run_id"], turn_id=ids.get("turn_id") or ""
    ):
        operation_task.cancel()
        try:
            await operation_task
        except asyncio.CancelledError:
            pass
        registry.release_run(thread_id, run_id=ids["run_id"])
        raise SessionBusyError(
            reason="active_turn_exists",
            message="A context compaction is already running",
            active_run_id=registry.active_run_id(thread_id) or "",
        )
    try:
        return await operation_task
    finally:
        registry.release_run(thread_id, run_id=ids["run_id"])


async def _execute_claimed_compact_live_command(
    *,
    context: CoreLiveContext,
    thread_id: str,
    work_root: str,
    actions: dict[str, Any],
    params: dict[str, Any],
    ids: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    from .params import _command_arguments
    _, snapshot = await _persist_command_run_item(
        context=context,
        event=_compact_command_event(thread_id, {}, ids=ids, status="running"),
    )

    terminal_emitted = False
    latest_snapshot = snapshot
    persisted_content_length = 0

    async def on_event(payload: dict[str, Any]) -> None:
        nonlocal terminal_emitted, latest_snapshot, persisted_content_length
        business_status = str(payload.get("status") or "running")
        cancelled = business_status == "cancelled" or str(payload.get("reason") or "") == "cancelled"
        event_status = (
            "cancelled"
            if cancelled
            else "failed"
            if business_status in {"failed", "error"}
            else "completed"
            if business_status in {"compacted", "not_needed"}
            else "running"
        )
        delta = str(payload.get("delta") or "")
        content = str(payload.get("content") or "")
        if event_status == "running" and delta:
            await _publish_transient_compaction_delta(
                context=context,
                thread_id=thread_id,
                ids=ids,
                payload=payload,
            )
            if len(content) - persisted_content_length < 64:
                return
            payload = {key: value for key, value in payload.items() if key != "delta"}
            persisted_content_length = len(content)
        _, latest_snapshot = await _persist_command_run_item(
            context=context,
            event=_compact_command_event(
                thread_id,
                payload,
                ids=ids,
                status=event_status,
            ),
        )
        if event_status in {"completed", "failed", "cancelled"} and not terminal_emitted:
            _, latest_snapshot = await _persist_command_run_item(
                context=context,
                event=_compact_command_terminal_event(
                    thread_id,
                    ids=ids,
                    status=event_status,
                    error=str(payload.get("error") or payload.get("message") or ""),
                ),
            )
            terminal_emitted = True

    try:
        result = await _execute_live_command_action(
            context=context,
            command="compact",
            thread_id=thread_id,
            work_root=work_root,
            actions=actions,
            params=params,
            arguments=_command_arguments(params),
            on_event=on_event,
        )
    except asyncio.CancelledError:
        cancelled_result = {
            "status": "cancelled",
            "reason": "cancelled",
            "message": "上下文压缩已取消",
        }
        if not terminal_emitted:
            await on_event(cancelled_result)
        return cancelled_result, latest_snapshot
    except BaseException as exc:
        await _persist_command_run_item(
            context=context,
            event=_compact_command_event(
                thread_id,
                {"error": str(exc)},
                ids=ids,
                status="failed",
            ),
        )
        await _persist_command_run_item(
            context=context,
            event=_compact_command_terminal_event(
                thread_id, ids=ids, status="failed", error=str(exc)
            ),
        )
        raise
    if terminal_emitted:
        return result, latest_snapshot
    _, snapshot = await _persist_command_run_item(
        context=context,
        event=_compact_command_event(thread_id, result, ids=ids, status="completed"),
    )
    _, snapshot = await _persist_command_run_item(
        context=context,
        event=_compact_command_terminal_event(thread_id, ids=ids, status="completed"),
    )
    return result, snapshot


async def _publish_transient_compaction_delta(
    *,
    context: CoreLiveContext,
    thread_id: str,
    ids: dict[str, str],
    payload: dict[str, Any],
) -> None:
    event = _compact_command_event(thread_id, payload, ids=ids, status="running")
    await context.hub.publish(AppEventEnvelope(
        event_id=event.event_id,
        protocol_version="core.app_server.v1",
        seq=0,
        thread_id=thread_id,
        method=CORE_RUN_ITEM_METHOD,
        payload=event.to_dict(),
        created_at=datetime.now(timezone.utc),
        turn_id=event.turn_id or None,
        item_id=event.item_id or None,
        parent_item_id=event.parent_item_id or None,
        client_message_id=None,
    ))


async def _persist_command_run_item(
    *, context: CoreLiveContext, event: RunItemEvent
) -> tuple[AppEventEnvelope, dict[str, Any]]:
    from .events import _append_run_item
    async def write(db: AsyncSession):
        envelope = await _append_run_item(db, context=context, event=event)
        return envelope, await context.persistence.load(db, event.thread_id)

    envelope, snapshot = await context.persistence.write(write)
    await context.hub.publish(envelope)
    return envelope, snapshot


def _compact_command_ids(thread_id: str, *, client_command_id: str = "") -> dict[str, str]:
    suffix = client_command_id.strip()
    if not suffix or len(suffix) > 64 or not suffix.isalnum():
        suffix = uuid.uuid4().hex[:12]
    run_id = f"{thread_id}:command:compact:{suffix}"
    return {"run_id": run_id, "turn_id": run_id, "item_id": f"{run_id}:summary"}


def _compact_command_event(
    thread_id: str,
    result: dict[str, Any],
    *,
    ids: dict[str, str],
    status: str,
) -> RunItemEvent:
    content = str(result.get("content") or result.get("summary") or result.get("error") or "")
    cancelled = status == "cancelled" or str(result.get("reason") or "") == "cancelled"
    business_status = "cancelled" if cancelled else str(result.get("status") or status)
    default_label = (
        "正在压缩上下文"
        if status == "running"
        else "压缩已取消"
        if cancelled
        else "压缩未完成"
        if status == "failed"
        else "上下文已压缩"
    )
    payload: dict[str, Any] = {
        "type": "compaction",
        "label": "压缩已取消" if cancelled else str(result.get("label") or default_label),
        "trigger": "manual",
        "compaction_status": business_status,
    }
    if content:
        payload["content"] = content
    if result.get("delta"):
        payload["delta"] = str(result["delta"])
    if result.get("error"):
        payload["error"] = str(result["error"])
    for key in (
        "compacted_messages",
        "retained_messages",
        "before_tokens",
        "after_tokens",
        "limit_tokens",
        "phase",
        "segment",
        "segments",
        "reason",
        "message",
    ):
        if result.get(key) is not None:
            payload[key] = result[key]
    return RunItemEvent(
        kind="message",
        thread_id=thread_id,
        event_id=f"compact:{status}:{uuid.uuid4().hex[:16]}",
        run_id=ids["run_id"],
        turn_id=ids["turn_id"],
        item_id=ids["item_id"],
        status=status,
        payload=payload,
        source="command.execute",
        metadata={"command": "compact"},
    )


def _compact_command_terminal_event(
    thread_id: str,
    *,
    ids: dict[str, str],
    status: str,
    error: str = "",
) -> RunItemEvent:
    return RunItemEvent(
        kind="status",
        thread_id=thread_id,
        event_id=f"compact:{status}-status:{uuid.uuid4().hex[:16]}",
        run_id=ids["run_id"],
        turn_id=ids["turn_id"],
        status=status,
        payload={
            "type": "turn",
            "status": status,
            "raw_end_reason": "command_failed" if status == "failed" else status,
            "message": error,
        },
        source="command.execute",
        metadata={"command": "compact"},
    )
