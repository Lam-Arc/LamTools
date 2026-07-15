from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from .event_store import CORE_RUN_ITEM_METHOD
from .live_hub import CoreAppEventGap
from .live_approval import normalize_approval_request
from .live_operations import (
    CoreLiveContext,
    CoreLiveOperationOutcome,
)
from .live_protocol import (
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    SERVER_ERROR,
    InitializeParams,
    JsonRpcRequest,
    event_notification,
    rpc_error,
    rpc_result,
    snapshot_notification,
)
from .operation_catalog import OperationCatalog


logger = logging.getLogger(__name__)

CoreLiveContextFactory = Callable[[], CoreLiveContext | Awaitable[CoreLiveContext]]
CoreLiveClientResponseHandler = Callable[["CoreLiveConnection", dict[str, Any]], bool | Awaitable[bool]]
CoreLiveOperationRequestHandler = Callable[["CoreLiveConnection", JsonRpcRequest], bool | Awaitable[bool]]
CoreLiveInitializedHandler = Callable[["CoreLiveConnection", InitializeParams], None | Awaitable[None]]
CoreLiveOperationCatalogFactory = Callable[["CoreLiveConnection"], OperationCatalog]
CoreLiveOperationNameNormalizer = Callable[[str], str]
CoreLiveRuntimeStartHandler = Callable[["CoreLiveConnection", dict[str, Any]], None | Awaitable[None]]
CoreLiveApprovalContinuationHandler = Callable[["CoreLiveConnection", dict[str, Any]], None | Awaitable[None]]


@dataclass(frozen=True)
class CoreLiveConnectionAdapter:
    protocol_version: str = PROTOCOL_VERSION
    server_name: str = "core_app_server"
    server_title: str = "Core App Server"
    accept_initialized_ack: bool = True
    invalid_request_message: str = "Invalid JSON-RPC request"
    not_initialized_code: int = INVALID_REQUEST
    not_initialized_message: str = "Connection is not initialized"
    already_initialized_message: str = "Already initialized"
    handle_client_response: CoreLiveClientResponseHandler | None = None
    handle_operation_request: CoreLiveOperationRequestHandler | None = None
    after_initialize: CoreLiveInitializedHandler | None = None
    operation_catalog_factory: CoreLiveOperationCatalogFactory | None = None
    normalize_operation_name: CoreLiveOperationNameNormalizer | None = None
    handle_unknown_operations: bool = False
    operation_error_code: int = SERVER_ERROR
    method_not_found_code: int = METHOD_NOT_FOUND
    start_runtime: CoreLiveRuntimeStartHandler | None = None
    continue_approval: CoreLiveApprovalContinuationHandler | None = None


def create_core_live_router(context_factory: CoreLiveContextFactory) -> APIRouter:
    router = APIRouter()

    @router.websocket("/app-server")
    async def app_server(websocket: WebSocket) -> None:
        context = context_factory()
        if inspect.isawaitable(context):
            context = await context
        connection = CoreLiveConnection(
            websocket,
            context=context,
            adapter=CoreLiveConnectionAdapter(handle_client_response=_handle_core_client_response),
        )
        await connection.run()

    return router


async def _handle_core_client_response(connection: "CoreLiveConnection", raw: dict[str, Any]) -> bool:
    if "method" in raw or "id" not in raw or not isinstance(raw.get("result"), dict):
        return False
    result_payload = raw["result"]
    params = dict(result_payload)
    params.setdefault("request_id", str(raw.get("id") or ""))
    host = getattr(connection.context, "host", None)
    if host is not None:
        outcome = await host.execute(
            "approval.respond",
            request_id=raw.get("id"),
            params=params,
            context=connection.context,
        )
        await connection.send_operation_outcome(outcome, send_response=False, publish_events=False, send_snapshot=True)
        return True
    try:
        normalized = await normalize_approval_request(params)
    except ValueError:
        return False
    result = await connection.context.operations.execute(
        "approval.respond",
        normalized.to_dict(),
        metadata={"source": "core_live_client_response"},
    )
    payload = dict(result.payload or {})
    if result.status != "ok":
        await connection.send(
            rpc_error(
                raw.get("id"),
                code=connection.adapter.operation_error_code,
                message=str(payload.get("error") or result.status),
                data=payload,
            )
        )
        return True
    snapshot = payload.get("snapshot")
    if isinstance(snapshot, dict):
        await connection.send(snapshot_notification(snapshot))
    return True


class CoreLiveConnection:
    def __init__(
        self,
        websocket: WebSocket,
        *,
        context: Any,
        outbound_limit: int = 256,
        adapter: CoreLiveConnectionAdapter | None = None,
    ) -> None:
        self.websocket = websocket
        self.context = context
        self.adapter = adapter or CoreLiveConnectionAdapter()
        self.initialized = False
        self.thread_id: str | None = None
        self.subscription: asyncio.Queue[Any | None] | None = None
        self.outbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=outbound_limit)

    async def run(self) -> None:
        await self.websocket.accept()
        sender = asyncio.create_task(self._sender())
        hub_reader = asyncio.create_task(self._hub_reader())
        try:
            while True:
                try:
                    raw = await self.websocket.receive_json()
                except WebSocketDisconnect:
                    break
                await self._handle_raw(raw)
        finally:
            sender.cancel()
            hub_reader.cancel()
            self._unsubscribe()

    async def _sender(self) -> None:
        while True:
            message = await self.outbound.get()
            await self.websocket.send_json(message)

    async def _send(self, message: dict[str, Any]) -> None:
        try:
            self.outbound.put_nowait(message)
        except asyncio.QueueFull:
            await self.websocket.close(code=1013, reason="Server overloaded; retry later.")

    async def send(self, message: dict[str, Any]) -> None:
        await self._send(message)

    async def _hub_reader(self) -> None:
        while True:
            if self.subscription is None:
                await asyncio.sleep(0.05)
                continue
            event = await self.subscription.get()
            if isinstance(event, CoreAppEventGap):
                await self.websocket.close(code=1013, reason="Event stream overflow; reconnect to resume.")
                return
            if event is None:
                continue
            await self._send(event_notification(event))
            event_method = event.get("method") if isinstance(event, dict) else getattr(event, "method", "")
            if event_method == CORE_RUN_ITEM_METHOD:
                continue
            await self._send_snapshot(_event_thread_id(event))

    async def _send_snapshot(self, thread_id: str) -> None:
        async with self.context.session_factory() as db:
            snapshot = await self.context.snapshot_store.load(db, thread_id)
        await self._send(snapshot_notification(snapshot))

    async def send_snapshot(self, thread_id: str) -> None:
        await self._send_snapshot(thread_id)

    async def send_operation_outcome(
        self,
        outcome: Any,
        *,
        send_response: bool = True,
        publish_events: bool = True,
        send_snapshot: bool = False,
        notify_events: bool = True,
    ) -> None:
        response = getattr(outcome, "response", None)
        if send_response and isinstance(response, dict):
            await self._send(response)
        if notify_events:
            for event in list(getattr(outcome, "notify_events", []) or []):
                await self._send(event_notification(event))
        if publish_events:
            for event in list(getattr(outcome, "publish_events", []) or []):
                await self.context.hub.publish(event)
        if send_snapshot and isinstance(response, dict):
            result = response.get("result")
            snapshot = result.get("snapshot") if isinstance(result, dict) else None
            if isinstance(snapshot, dict):
                await self._send(snapshot_notification(snapshot))
        runtime_start = getattr(outcome, "runtime_start", None)
        if isinstance(runtime_start, dict) and self.adapter.start_runtime is not None:
            started = self.adapter.start_runtime(self, runtime_start)
            if inspect.isawaitable(started):
                await started
        continuation = getattr(outcome, "continuation", None)
        if isinstance(continuation, dict) and self.adapter.continue_approval is not None:
            continued = self.adapter.continue_approval(self, continuation)
            if inspect.isawaitable(continued):
                asyncio.create_task(continued)

    def _subscribe(self, thread_id: str) -> None:
        if self.thread_id == thread_id and self.subscription is not None:
            return
        self._unsubscribe()
        self.thread_id = thread_id
        self.subscription = self.context.hub.subscribe(thread_id)

    def switch_thread_subscription(self, thread_id: str) -> None:
        self._subscribe(thread_id)

    def _unsubscribe(self) -> None:
        if self.thread_id and self.subscription is not None:
            self.context.hub.unsubscribe(self.thread_id, self.subscription)
        self.subscription = None

    async def _handle_raw(self, raw: dict[str, Any]) -> None:
        if await self._handle_client_response(raw):
            return
        try:
            request = JsonRpcRequest.model_validate(raw)
        except ValidationError as exc:
            await self._send(
                rpc_error(
                    raw.get("id") if isinstance(raw, dict) else None,
                    code=INVALID_REQUEST,
                    message=self._invalid_request_message(),
                    data={"errors": exc.errors()},
                )
            )
            return
        if await self._handle_control_request(request):
            return
        if not self.initialized:
            await self._send_not_initialized(request)
            return
        thread_id = _thread_id_from_params(request.params)
        if thread_id:
            self._subscribe(thread_id)
        if await self._handle_operation_request(request):
            return
        try:
            outcome = await self._dispatch(request)
        except Exception as exc:
            logger.exception("Core app-server operation failed: %s", request.method)
            await self._send(rpc_error(request.id, code=SERVER_ERROR, message=str(exc)))
            return
        await self._send(outcome.response)
        await self.send_operation_outcome(
            outcome,
            send_response=False,
            publish_events=False,
            send_snapshot=False,
            notify_events=False,
        )
        thread_id = _thread_id_from_params(request.params) or _thread_id_from_outcome(outcome)
        if thread_id:
            self._subscribe(thread_id)
            result = outcome.response.get("result")
            snapshot = result.get("snapshot") if isinstance(result, dict) else None
            if isinstance(snapshot, dict):
                await self._send(snapshot_notification(snapshot))

    async def handle_raw(self, raw: dict[str, Any]) -> None:
        await self._handle_raw(raw)

    async def _handle_client_response(self, raw: dict[str, Any]) -> bool:
        if self.adapter.handle_client_response is None:
            return False
        handled = self.adapter.handle_client_response(self, raw)
        if inspect.isawaitable(handled):
            handled = await handled
        return bool(handled)

    async def _handle_control_request(self, request: JsonRpcRequest) -> bool:
        if self.adapter.accept_initialized_ack and request.method == "initialized":
            await self._send(rpc_result(request.id, {"ok": True}))
            return True
        if request.method == "initialize":
            await self._initialize(request)
            return True
        return False

    async def _handle_operation_request(self, request: JsonRpcRequest) -> bool:
        if self.adapter.handle_operation_request is None:
            return await self._handle_adapter_operation_request(request)
        handled = self.adapter.handle_operation_request(self, request)
        if inspect.isawaitable(handled):
            handled = await handled
        return bool(handled)

    async def _handle_adapter_operation_request(self, request: JsonRpcRequest) -> bool:
        if self.adapter.operation_catalog_factory is None:
            return False
        catalog = self.adapter.operation_catalog_factory(self)
        normalizer = self.adapter.normalize_operation_name or _normalize_method
        operation_name = normalizer(request.method)
        if not catalog.has(operation_name):
            if not self.adapter.handle_unknown_operations:
                return False
            await self._send(
                rpc_error(
                    request.id,
                    code=self.adapter.method_not_found_code,
                    message=f"Unsupported method: {request.method}",
                )
            )
            return True
        try:
            result = await catalog.execute(
                operation_name,
                request.params,
                metadata={
                    "source": "core_live",
                    "rpc_method": request.method,
                    "rpc_request": request,
                    "connection": self,
                },
            )
        except Exception as exc:
            logger.exception("Core app-server operation failed: %s", operation_name)
            await self._send(rpc_error(request.id, code=self.adapter.operation_error_code, message=str(exc)))
            return True
        if result.metadata.get("live_response_sent") is True:
            return True
        payload = dict(result.payload or {})
        if result.status != "ok":
            await self._send(
                rpc_error(
                    request.id,
                    code=self.adapter.operation_error_code,
                    message=str(payload.get("error") or result.status),
                    data=payload,
                )
            )
            return True
        await self._send(rpc_result(request.id, payload))
        return True

    def _invalid_request_message(self) -> str:
        return self.adapter.invalid_request_message

    async def _send_not_initialized(self, request: JsonRpcRequest) -> None:
        await self._send(
            rpc_error(
                request.id,
                code=self.adapter.not_initialized_code,
                message=self.adapter.not_initialized_message,
            )
        )

    async def _initialize(self, request: JsonRpcRequest) -> None:
        if self.initialized:
            await self._send(rpc_error(request.id, code=INVALID_REQUEST, message=self.adapter.already_initialized_message))
            return
        try:
            params = InitializeParams.model_validate(request.params)
        except ValidationError as exc:
            await self._send(rpc_error(request.id, code=INVALID_REQUEST, message="Invalid initialize params", data={"errors": exc.errors()}))
            return
        self.initialized = True
        if params.threadId:
            self._subscribe(params.threadId)
        if self.adapter.after_initialize is not None:
            initialized = self.adapter.after_initialize(self, params)
            if inspect.isawaitable(initialized):
                await initialized
        await self._send(
            rpc_result(
                request.id,
                {
                    "protocolVersion": self.adapter.protocol_version,
                    "serverInfo": {"name": self.adapter.server_name, "title": self.adapter.server_title},
                },
            )
        )

    async def _dispatch(self, request: JsonRpcRequest) -> CoreLiveOperationOutcome:
        method = _normalize_method(request.method)
        if method == "thread.resume":
            thread_id = _thread_id_from_params(request.params)
            if thread_id:
                self.switch_thread_subscription(thread_id)
        if method in self.context.host.operation_handlers() or self.context.operations.has(method):
            return await self.context.host.execute(
                method,
                request_id=request.id,
                params=request.params,
                context=self.context,
            )
        return CoreLiveOperationOutcome(
            response=rpc_error(request.id, code=METHOD_NOT_FOUND, message=f"Unsupported method: {request.method}")
        )


def _normalize_method(method: str) -> str:
    aliases = {
        "thread/resume": "thread.resume",
        "thread/read": "thread.read",
        "turn/start": "turn.start",
        "turn/cancel": "turn.cancel",
        "turn/interrupt": "turn.cancel",
        "turn.interrupt": "turn.cancel",
        "turn/steer": "turn.steer",
        "approval/respond": "approval.respond",
        "queue/create": "queue.create",
        "queue/update": "queue.update",
        "queue/delete": "queue.delete",
        "queue/guide": "queue.guide",
    }
    return aliases.get(method, method.replace("/", "."))


def _thread_id_from_params(params: dict[str, Any]) -> str:
    return str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or params.get("sessionId") or "")


def _thread_id_from_outcome(outcome: CoreLiveOperationOutcome) -> str:
    result = outcome.response.get("result")
    if not isinstance(result, dict):
        return ""
    snapshot = result.get("snapshot")
    if isinstance(snapshot, dict):
        return str(snapshot.get("thread_id") or "")
    thread = result.get("thread")
    if isinstance(thread, dict):
        return str(thread.get("id") or "")
    return ""


def _event_thread_id(event: Any) -> str:
    if hasattr(event, "thread_id"):
        return str(event.thread_id)
    if isinstance(event, dict):
        return str(event.get("thread_id") or "")
    return ""


__all__ = ["CoreLiveConnection", "CoreLiveConnectionAdapter", "create_core_live_router"]
