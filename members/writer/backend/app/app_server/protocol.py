from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from lamtools_core.app.event_store import CORE_RUN_ITEM_METHOD
from lamtools_core.app.live_protocol import (
    ClientInfo,
    InitializeParams,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    event_notification,
    rpc_error,
    rpc_result,
)
from pydantic import BaseModel, Field


PROTOCOL_VERSION = "writer.app_server.v1"


class WriterAppEventPayload(BaseModel):
    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class WriterAppEventEnvelope(BaseModel):
    event_id: str
    protocol_version: Literal["writer.app_server.v1"] = PROTOCOL_VERSION
    seq: int
    thread_id: str
    method: str
    payload: dict[str, Any]
    created_at: datetime
    turn_id: str | None = None
    item_id: str | None = None
    parent_item_id: str | None = None
    client_message_id: str | None = None


class AppendEventInput(BaseModel):
    thread_id: str
    method: str
    payload: dict[str, Any] = Field(default_factory=dict)
    event_id: str | None = None
    turn_id: str | None = None
    item_id: str | None = None
    parent_item_id: str | None = None
    client_message_id: str | None = None
