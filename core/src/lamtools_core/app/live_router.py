from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from .event_store import CORE_RUN_ITEM_METHOD
from .live_hub import CoreAppEventGap
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
from .security import is_allowed_origin


logger = logging.getLogger(__name__)

# Events that change cross-client state outside the runItem stream and are
# rare enough to justify a full snapshot push (multi-window sync). Every other
# event is delivered as a plain event notification: clients apply core/runItem
# deltas incrementally, and turn boundaries / joins / reconnects sync through
# RPC responses and thread/resume. Sending a full snapshot per event turned a
# 56MB-thread stream into a flood (outbound queue overflow -> 1013 reconnect
# storm), which is the root cause of the mid-turn UI stutter on large threads.
SNAPSHOT_TRIGGER_EVENTS = frozenset({
    "turn/interrupted",
    "turn/steered",
    "queue/itemAccepted",
    "queue/itemUpdated",
    "queue/itemDeleted",
    "queue/itemDispatched",
})
# Safety net: even for snapshot-trigger events, at most one snapshot per
# connection per interval — the next trigger (or thread/resume) delivers the
# latest state anyway.
SNAPSHOT_MIN_INTERVAL_SECONDS = 1.0

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
        # Browsers always send an Origin header on WebSocket handshakes; reject
        # anything not on the local allow-list (a malicious page could
        # otherwise open a raw WS to 127.0.0.1 and drive the agent, since WS
        # is not subject to CORS).  Non-browser clients omit Origin and pass.
        origin = websocket.headers.get("origin")
        if origin is not None and not is_allowed_origin(origin):
            await websocket.close(code=1008, reason="origin not allowed")
            return
        context = context_factory()
        if inspect.isawaitable(context):
            context = await context
        connection = CoreLiveConnection(
            websocket,
            context=context,
            adapter=CoreLiveConnectionAdapter(),
            browser_origin=origin,
            # Bound the receive buffer so a hostile/leaky peer cannot balloon
            # memory with one oversized frame (audit 12). 4 MB comfortably
            # covers every legitimate RPC payload.
            max_message_bytes=4 * 1024 * 1024,
        )
        await connection.run()

    return router


class CoreLiveConnection:
    def __init__(
        self,
        websocket: WebSocket,
        *,
        context: Any,
        outbound_limit: int = 256,
        adapter: CoreLiveConnectionAdapter | None = None,
        browser_origin: str | None = None,
        max_message_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        self.websocket = websocket
        self.context = context
        self.adapter = adapter or CoreLiveConnectionAdapter()
        self.max_message_bytes = max_message_bytes
        # Set when the handshake carried an Origin header (i.e. the peer is a
        # browser page, not a local CLI process).  Browser connections cannot
        # self-grant auto-approval (see _dispatch).
        self.browser_origin = browser_origin
        self.initialized = False
        self.thread_id: str | None = None
        self.subscription: asyncio.Queue[Any | None] | None = None
        # Signalled when a subscription is active so _hub_reader can block
        # without busy-polling while idle. Cleared on unsubscribe.
        self._subscription_ready = asyncio.Event()
        self.outbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=outbound_limit)
        self.request_tasks: set[asyncio.Task[None]] = set()
        self._last_snapshot_sent_at = 0.0
        # Per-item runItem delta coalescing window. Model streams can deliver
        # thousands of tiny per-token deltas per second; sending each as its
        # own WS message floods the renderer's task queue (measured ~2500
        # msgs/s in bursts), starving requestAnimationFrame so the UI freezes
        # and jumps instead of streaming smoothly. Batching per (thread, item,
        # kind) over a ~20ms window cuts the message count ~30x with no
        # protocol change — the client already merges in-frame deltas and
        # understands `_coalesced_event_ids` for dedup.
        self._run_item_buffer: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._run_item_flush_task: asyncio.Task[None] | None = None
        self._run_item_flush_interval: float = 0.02

    async def run(self) -> None:
        await self.websocket.accept()
        sender = asyncio.create_task(self._sender())
        hub_reader = asyncio.create_task(self._hub_reader())
        try:
            while True:
                try:
                    raw_text = await self.websocket.receive_text()
                except WebSocketDisconnect as exc:
                    logger.info("core-app-server ws disconnected: code=%s reason=%r", exc.code, exc.reason)
                    break
                except Exception as exc:
                    logger.warning("core-app-server ws receive failed: %s", exc)
                    break
                if len(raw_text) > self.max_message_bytes:
                    # A hostile/leaky peer must not balloon memory with one
                    # oversized frame (audit 12); close with the standard
                    # "message too big" code.
                    logger.warning("core-app-server ws frame too large (%d bytes)", len(raw_text))
                    await self.websocket.close(code=1009, reason="message too big")
                    break
                try:
                    raw = json.loads(raw_text)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("core-app-server ws invalid JSON frame")
                    continue
                if not self.initialized:
                    await self._handle_raw(raw)
                    continue
                task = asyncio.create_task(self._handle_raw(raw))
                self.request_tasks.add(task)
                task.add_done_callback(self._request_task_done)
        finally:
            sender.cancel()
            hub_reader.cancel()
            if self._run_item_flush_task is not None:
                self._run_item_flush_task.cancel()
                self._run_item_flush_task = None
            pending = list(self.request_tasks)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self._unsubscribe()

    def _request_task_done(self, task: asyncio.Task[None]) -> None:
        self.request_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Core app-server request task failed",
                exc_info=(type(error), error, error.__traceback__),
            )

    async def _sender(self) -> None:
        while True:
            message = await self.outbound.get()
            await self.websocket.send_json(message)

    async def _send(self, message: dict[str, Any]) -> None:
        try:
            self.outbound.put_nowait(message)
        except asyncio.QueueFull:
            # Never kill a live connection over outbound pressure: dropping the
            # message is safe because clients re-sync via boundary snapshots and
            # thread/resume. Closing with 1013 here turned transient overload
            # into a reconnect storm (56MB snapshots x many events).
            logger.warning(
                "Core app-server outbound queue full; dropping message for thread %s",
                self.thread_id or "(unsubscribed)",
            )

    async def send(self, message: dict[str, Any]) -> None:
        await self._send(message)

    async def _hub_reader(self) -> None:
        while True:
            # Block until a subscription exists, instead of busy-polling at
            # 20 Hz. Event.wait() yields the loop with no wakeups while idle.
            if self.subscription is None:
                await self._subscription_ready.wait()
                continue
            event = await self.subscription.get()
            if isinstance(event, CoreAppEventGap):
                logger.warning("core-app-server event stream overflow; closing ws 1013 (thread=%s)", self.thread_id or "-")
                await self.websocket.close(code=1013, reason="Event stream overflow; reconnect to resume.")
                return
            if event is None:
                continue
            event_method = event.get("method") if isinstance(event, dict) else getattr(event, "method", "")
            if event_method == CORE_RUN_ITEM_METHOD:
                await self._enqueue_run_item(event)
                continue
            # Non-runItem events must land after any buffered deltas so the
            # client never observes state out of order.
            await self._flush_run_item_buffer()
            await self._send(event_notification(event))
            if event_method in (CORE_RUN_ITEM_METHOD, "session/created", "session/updated", "workflow/changed"):
                continue
            if event_method not in SNAPSHOT_TRIGGER_EVENTS:
                continue
            # Throttled boundary snapshot (latest state wins on the next
            # trigger). The client applies everything else incrementally.
            now = asyncio.get_running_loop().time()
            if now - self._last_snapshot_sent_at < SNAPSHOT_MIN_INTERVAL_SECONDS:
                logger.debug(
                    "Core app-server skipping throttled snapshot for %s (%.2fs since last)",
                    _event_thread_id(event),
                    now - self._last_snapshot_sent_at,
                )
                continue
            self._last_snapshot_sent_at = now
            await self._send_snapshot(_event_thread_id(event))

    async def _enqueue_run_item(self, event: Any) -> None:
        """Coalesce runItem text deltas for the same item into one message.

        Deltas are merged in-place over a ~20ms window (see __init__ for why);
        the merged message keeps the first event's identity and lists every
        absorbed event id under ``_coalesced_event_ids`` so the client marks
        them all seen and a later snapshot never replays them.
        """
        params = event_notification(event)["params"]
        value = params.get("payload") if isinstance(params.get("payload"), dict) else params
        inner = value.get("payload") if isinstance(value.get("payload"), dict) else {}
        if not isinstance(inner.get("delta"), str):
            # Non-delta runItem events (tool_result, status, usage, full
            # content) carry completion/state — send immediately, ordered
            # after any buffered deltas for the same item.
            await self._flush_run_item_buffer()
            await self._send({"method": CORE_RUN_ITEM_METHOD, "params": params})
            return
        key = (
            str(value.get("thread_id") or params.get("thread_id") or self.thread_id or ""),
            str(value.get("item_id") or params.get("item_id") or ""),
            str(value.get("kind") or ""),
        )
        buffered = self._run_item_buffer.get(key)
        if buffered is None:
            buffered = self._run_item_buffer[key] = {
                "method": CORE_RUN_ITEM_METHOD,
                "params": _copy_run_item_params(params),
            }
            buffered["params"]["payload"]["_coalesced_event_ids"] = [
                str(value.get("event_id") or params.get("event_id") or ""),
            ]
        else:
            b_inner = buffered["params"]["payload"]["payload"]
            if isinstance(b_inner, dict):
                b_inner["delta"] = f"{b_inner.get('delta') or ''}{inner['delta']}"
            event_id = str(value.get("event_id") or params.get("event_id") or "")
            if event_id:
                buffered["params"]["payload"]["_coalesced_event_ids"].append(event_id)
        if self._run_item_flush_task is None:
            self._run_item_flush_task = asyncio.create_task(self._flush_run_items_soon())

    async def _flush_run_items_soon(self) -> None:
        try:
            await asyncio.sleep(self._run_item_flush_interval)
        finally:
            self._run_item_flush_task = None
        await self._flush_run_item_buffer()

    async def _flush_run_item_buffer(self) -> None:
        if self._run_item_flush_task is not None:
            self._run_item_flush_task.cancel()
            self._run_item_flush_task = None
        if not self._run_item_buffer:
            return
        buffer, self._run_item_buffer = self._run_item_buffer, {}
        for message in buffer.values():
            await self._send(message)

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
        self._subscription_ready.set()

    def switch_thread_subscription(self, thread_id: str) -> None:
        self._subscribe(thread_id)

    def _unsubscribe(self) -> None:
        if self.thread_id and self.subscription is not None:
            self.context.hub.unsubscribe(self.thread_id, self.subscription)
        self.subscription = None
        self._subscription_ready.clear()

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
            # Note: no separate thread/snapshot notification here — the RPC
            # response already carries result.snapshot (when included), and
            # re-sending it as a notification doubled snapshot traffic
            # (56MB x 2 per operation on large threads).

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
        client_name = ""
        if params.clientInfo is not None:
            client_name = str(getattr(params.clientInfo, "name", "") or "")
        logger.info(
            "core-app-server initialize client=%s thread=%s last_seen_seq=%s",
            client_name,
            params.threadId or "-",
            params.lastSeenSeq,
        )
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
        params = request.params
        if method == "turn.start" and self.browser_origin is not None:
            # A browser page must not self-grant auto-approval: strip any
            # client-declared policy so the server-side runtimeControls
            # settings decide.  Non-browser callers (CLI / local processes)
            # keep their explicit policy.
            if params.get("approval_policy") is not None or params.get("approvalPolicy") is not None:
                params = {**params}
                params.pop("approval_policy", None)
                params.pop("approvalPolicy", None)
        if method == "approval.respond":
            # Bind the response to the subscribed thread: a connection may
            # only answer an approval request for the thread it is watching.
            thread_id = _thread_id_from_params(params)
            if not thread_id or self.thread_id != thread_id:
                return CoreLiveOperationOutcome(
                    response=rpc_error(
                        request.id,
                        code=INVALID_REQUEST,
                        message="approval.respond must target the subscribed thread",
                    )
                )
        if method in self.context.host.operation_handlers() or self.context.operations.has(method):
            return await self.context.host.execute(
                method,
                request_id=request.id,
                params=params,
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
        "turn/force_reset": "turn.force_reset",
        "turn/force-reset": "turn.force_reset",
        "turn.force_reset": "turn.force_reset",
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


def _copy_run_item_params(params: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy the two payload levels of a runItem event.

    ``event_notification`` shallow-copies the envelope, so the runItem's inner
    ``payload`` dict is still shared with the stored event. Coalescing mutates
    that dict (appending deltas) — copy it first so the event store and other
    subscribers never see rewritten history.
    """
    value = params.get("payload")
    if isinstance(value, dict):
        inner = value.get("payload")
        return {
            **params,
            "payload": {
                **value,
                "payload": dict(inner) if isinstance(inner, dict) else inner,
            },
        }
    return dict(params)


__all__ = ["CoreLiveConnection", "CoreLiveConnectionAdapter", "create_core_live_router"]
