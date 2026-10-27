"""Background process inspection, termination and log reads."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from lamtools_core.runtime.background_processes import default_background_process_registry, status_to_dict
from ..event_store import AppEventEnvelope
from ..live_protocol import INVALID_REQUEST, rpc_error, rpc_result
from .context import CoreLiveContext, CoreLiveOperationOutcome


def _background_process_registry_of(context: CoreLiveContext):
    registry = getattr(context.host.runtime_task_registry, "background_process_registry", None)
    return registry if registry is not None else default_background_process_registry()


def _process_scope_thread_id(params: dict[str, Any]) -> str:
    from .params import _thread_id_from_params
    return _thread_id_from_params(params)


async def _publish_process_changed(
    context: CoreLiveContext,
    thread_id: str,
    pid: int,
    action: str,
) -> None:
    envelope = AppEventEnvelope(
        event_id=f"{thread_id}:process-changed:{action}:{pid}:{uuid.uuid4().hex[:8]}",
        protocol_version="core.app_server.v1",
        seq=0,
        thread_id=thread_id,
        method="process/changed",
        payload={"pid": pid, "action": action},
        created_at=datetime.now(timezone.utc),
    )
    await context.hub.publish(envelope)


def _invalid_pid_response(request_id: int | str | None, raw: Any):
    return CoreLiveOperationOutcome(
        response=rpc_error(request_id, code=INVALID_REQUEST, message=f"pid must be an integer, got {raw!r}")
    )


async def handle_process_list_operation(
    *, request_id: int | str | None = None, params: dict[str, Any] | None = None, context: CoreLiveContext
) -> CoreLiveOperationOutcome:
    params = params or {}
    thread_id = _process_scope_thread_id(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    registry = _background_process_registry_of(context)
    statuses = registry.list_status(session_id=thread_id)
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, {"processes": [status_to_dict(status) for status in statuses]})
    )


async def handle_process_kill_operation(
    *, request_id: int | str | None = None, params: dict[str, Any] | None = None, context: CoreLiveContext
) -> CoreLiveOperationOutcome:
    params = params or {}
    thread_id = _process_scope_thread_id(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    try:
        pid = int(params.get("pid"))
    except (TypeError, ValueError):
        return _invalid_pid_response(request_id, params.get("pid"))
    if pid <= 0:
        return _invalid_pid_response(request_id, params.get("pid"))
    registry = _background_process_registry_of(context)
    outcome = registry.kill(thread_id, pid)
    if outcome == "not_owned":
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=(
                    f"Process {pid} was registered before the last backend restart; "
                    "it cannot be terminated safely."
                ),
                data={"code": "PROCESS_NOT_OWNED", "pid": pid},
            )
        )
    if outcome != "terminated":
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=f"No registered background process with pid {pid} in this session.",
                data={"code": "PROCESS_NOT_FOUND", "pid": pid},
            )
        )
    await _publish_process_changed(context, thread_id, pid, "killed")
    return CoreLiveOperationOutcome(response=rpc_result(request_id, {"pid": pid, "terminated": True}))


async def handle_process_forget_operation(
    *, request_id: int | str | None = None, params: dict[str, Any] | None = None, context: CoreLiveContext
) -> CoreLiveOperationOutcome:
    params = params or {}
    thread_id = _process_scope_thread_id(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    try:
        pid = int(params.get("pid"))
    except (TypeError, ValueError):
        return _invalid_pid_response(request_id, params.get("pid"))
    if pid <= 0:
        return _invalid_pid_response(request_id, params.get("pid"))
    registry = _background_process_registry_of(context)
    removed = registry.forget(thread_id, pid)
    if removed:
        await _publish_process_changed(context, thread_id, pid, "forgotten")
    return CoreLiveOperationOutcome(response=rpc_result(request_id, {"pid": pid, "removed": removed}))


async def handle_process_log_operation(
    *, request_id: int | str | None = None, params: dict[str, Any] | None = None, context: CoreLiveContext
) -> CoreLiveOperationOutcome:
    params = params or {}
    thread_id = _process_scope_thread_id(params)
    if not thread_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="thread_id is required")
        )
    try:
        pid = int(params.get("pid"))
    except (TypeError, ValueError):
        return _invalid_pid_response(request_id, params.get("pid"))
    if pid <= 0:
        return _invalid_pid_response(request_id, params.get("pid"))
    stream = str(params.get("stream") or "stdout").strip().lower()
    if stream in {"out", "stdout", ""}:
        stream = "stdout"
    elif stream in {"err", "stderr"}:
        stream = "stderr"
    else:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="stream must be 'stdout' or 'stderr'")
        )
    try:
        max_bytes = int(params.get("max_bytes") or 8192)
    except (TypeError, ValueError):
        max_bytes = 8192
    max_bytes = max(256, min(max_bytes, 262144))
    registry = _background_process_registry_of(context)
    status = next(
        (item for item in registry.list_status(session_id=thread_id) if item.record.pid == pid),
        None,
    )
    if status is None:
        return CoreLiveOperationOutcome(
            response=rpc_error(
                request_id,
                code=INVALID_REQUEST,
                message=f"No registered background process with pid {pid} in this session.",
                data={"code": "PROCESS_NOT_FOUND", "pid": pid},
            )
        )
    path_text = status.record.stdout_log if stream == "stdout" else status.record.stderr_log
    path = Path(path_text) if path_text else None
    if path is None or not path.is_file():
        return CoreLiveOperationOutcome(
            response=rpc_result(request_id, {
                "pid": pid,
                "stream": stream,
                "path": path_text,
                "content": "",
                "truncated": False,
                "missing": True,
            })
        )
    size = path.stat().st_size
    truncated = size > max_bytes
    with path.open("rb") as handle:
        if truncated:
            handle.seek(-max_bytes, os.SEEK_END)
        content = handle.read(max_bytes).decode("utf-8", errors="replace")
    if truncated:
        newline = content.find("\n")
        if 0 <= newline < len(content) - 1:
            content = content[newline + 1:]
    return CoreLiveOperationOutcome(
        response=rpc_result(request_id, {
            "pid": pid,
            "stream": stream,
            "path": str(path),
            "content": content,
            "truncated": truncated,
            "missing": False,
        })
    )
