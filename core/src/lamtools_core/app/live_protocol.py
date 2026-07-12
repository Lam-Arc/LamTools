from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


PROTOCOL_VERSION = "core.app_server.v1"
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
SERVER_ERROR = -32000


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: dict[str, Any] | None = None


class JsonRpcRequest(BaseModel):
    id: int | str | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class JsonRpcResponse(BaseModel):
    id: int | str | None
    result: dict[str, Any] | None = None
    error: JsonRpcError | None = None


class ClientInfo(BaseModel):
    name: str
    title: str | None = None
    version: str | None = None


class InitializeParams(BaseModel):
    clientInfo: ClientInfo
    threadId: str | None = None
    lastSeenSeq: int | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)


def rpc_result(message_id: int | str | None, result: dict[str, Any] | None = None) -> dict[str, Any]:
    return JsonRpcResponse(id=message_id, result=result or {}).model_dump(mode="json", exclude_none=True)


def rpc_error(
    message_id: int | str | None,
    *,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return JsonRpcResponse(
        id=message_id,
        error=JsonRpcError(code=code, message=message, data=data),
    ).model_dump(mode="json", exclude_none=True)


def event_notification(event: Any) -> dict[str, Any]:
    if hasattr(event, "to_dict"):
        params = event.to_dict()
    elif hasattr(event, "model_dump"):
        params = event.model_dump(mode="json")
    else:
        params = dict(event)
    return {"method": str(params.get("method") or "core/event"), "params": params}


def snapshot_notification(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {"method": "thread/snapshot", "params": snapshot}


def iso_now() -> str:
    return datetime.now().isoformat()


__all__ = [
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "PROTOCOL_VERSION",
    "SERVER_ERROR",
    "ClientInfo",
    "InitializeParams",
    "JsonRpcError",
    "JsonRpcRequest",
    "JsonRpcResponse",
    "event_notification",
    "iso_now",
    "rpc_error",
    "rpc_result",
    "snapshot_notification",
]
