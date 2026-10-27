"""Attachment operations using the live session context."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

from typing import Any
from lamtools_core.attachment import AttachmentService
from ..live_protocol import INVALID_REQUEST, rpc_error, rpc_result
from .context import CoreLiveContext, CoreLiveOperationOutcome


async def handle_attachment_operation(
    *, request_id: int | str | None, params: dict[str, Any], context: "CoreLiveContext", operation: str
) -> "CoreLiveOperationOutcome":
    from .params import _thread_id_from_params
    session_id = _thread_id_from_params(params)
    attachment_id = str(params.get("attachment_id") or params.get("attachmentId") or params.get("id") or "").strip()
    if operation == "list" and not session_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="session_id is required")
        )
    if operation != "list" and not attachment_id:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message="attachment_id is required")
        )
    try:
        async with context.session_factory() as db:
            repository = context.host.member_hooks.attachment_repository(db)
            if repository is None:
                raise RuntimeError("Attachment storage is not configured")
            service = AttachmentService(repository)
            if operation == "list":
                result = {"attachments": await service.list(session_id)}
            elif operation == "get":
                result = {"attachment": await service.get_response(attachment_id)}
            elif operation == "preview":
                result = {"preview": await service.preview(attachment_id)}
            else:
                result = await service.open(attachment_id)
    except (FileNotFoundError, LookupError, RuntimeError, ValueError) as exc:
        return CoreLiveOperationOutcome(
            response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
        )
    return CoreLiveOperationOutcome(response=rpc_result(request_id, result))


async def handle_attachment_list_operation(**kwargs):
    return await handle_attachment_operation(**kwargs, operation="list")


async def handle_attachment_get_operation(**kwargs):
    return await handle_attachment_operation(**kwargs, operation="get")


async def handle_attachment_preview_operation(**kwargs):
    return await handle_attachment_operation(**kwargs, operation="preview")


async def handle_attachment_open_operation(**kwargs):
    return await handle_attachment_operation(**kwargs, operation="open")
