from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
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
    THREAD_GAP_METHOD,
    InitializeParams,
    JsonRpcRequest,
    event_notification,
    rpc_error,
    rpc_result,
    snapshot_notification,
)
from .operation_catalog import OperationCatalog
from .security import is_allowed_origin, is_same_server_origin


logger = logging.getLogger(__name__)


def _trace(event: str, **fields: Any) -> None:
    """Write correlation metadata without logging request or response bodies."""
    payload: dict[str, Any] = {"component": "core", "event": event}
    payload.update(fields)
    logger.info("[lamtools-remote] %s", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

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

# RPC replies and state notifications must not compete with the lossy stream
# of high-volume runItem deltas. Both lanes are bounded; producers of control
# messages apply backpressure while the sender drains them, whereas deltas may
# be dropped and recovered from snapshots/resume.
CONTROL_OUTBOUND_RUN_ITEM_KINDS = frozenset({"approval_request"})
CONTROL_OUTBOUND_ENQUEUE_TIMEOUT_SECONDS = 5.0
OUTBOUND_DROP_LOG_INTERVAL_SECONDS = 10.0
# After the lossy lane drops frames, tell the client to resynchronize from its
# own revision. Rate limited so a sustained overflow cannot flood the reliable
# control lane (and throttle the resync storm rather than the drops).
OUTBOUND_GAP_MIN_INTERVAL_SECONDS = 1.0

# A snapshot page is delimited by complete turns, so a page on a long thread can
# be tens of MB in one WebSocket message. Common client libraries cap a single
# message at 4 MiB — aiohttp's ``max_msg_size`` default, and Node/undici's
# permessage-deflate decompressed-message limit (which closes with 1009
# "Max decompressed message size exceeded"; that limit is not configurable).
# The local send still succeeds, so without a warning an oversized response
# looks like an unexplained disconnect on the client (2026-10-12: three probes
# died exactly this way right after ``core.rpc.response_sent``). Log anything at
# or above the cap with its size and thread/turn identity.
LARGE_OUTBOUND_MESSAGE_BYTES = 4 * 1024 * 1024

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
        if (
            origin is not None
            and not is_allowed_origin(origin)
            and not is_same_server_origin(
                origin,
                scheme=str(websocket.scope.get("scheme") or ""),
                server=websocket.scope.get("server"),
            )
        ):
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
        control_outbound_limit: int = 64,
        control_outbound_timeout_seconds: float = CONTROL_OUTBOUND_ENQUEUE_TIMEOUT_SECONDS,
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
        # Ordinary event traffic is deliberately lossy and remains isolated
        # from responses and recovery-critical notifications. In particular,
        # filling the runItem lane must never make an RPC acknowledgement vanish.
        self.outbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max(1, outbound_limit))
        self.control_outbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=max(1, control_outbound_limit),
        )
        self.control_outbound_timeout_seconds = max(0.001, control_outbound_timeout_seconds)
        self._outbound_ready = asyncio.Event()
        self._closing = False
        self._outbound_dropped_count = 0
        self._outbound_drops_since_log = 0
        self._outbound_drop_last_log_at: float | None = None
        self._outbound_gap_last_at: float | None = None
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
        # Index of replaceable runItem delta frames currently sitting in
        # ``outbound``, keyed by (thread, item, kind). A later frame for a key
        # that is still queued is merged into the pending frame in place rather
        # than enqueued, so filling the lane loses only intermediate frames and
        # the client still converges on the merged text (see _send). The key is
        # removed when the frame leaves the queue (_take_outbound), so a sent
        # frame is never mutated afterwards.
        self._outbound_keys: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._request_methods: dict[str, str] = {}

    async def run(self) -> None:
        await self.websocket.accept()
        _trace("core.connection_started")
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
            self._closing = True
            self._outbound_ready.set()
            sender.cancel()
            hub_reader.cancel()
            background = [sender, hub_reader]
            if self._run_item_flush_task is not None:
                self._run_item_flush_task.cancel()
                background.append(self._run_item_flush_task)
                self._run_item_flush_task = None
            pending = list(self.request_tasks)
            for task in pending:
                task.cancel()
            await asyncio.gather(*background, *pending, return_exceptions=True)
            self._unsubscribe()
            if self._outbound_dropped_count:
                _trace(
                    "core.outbound_notifications_dropped",
                    count=self._outbound_dropped_count,
                    since_last_report=self._outbound_drops_since_log,
                    thread_id=self.thread_id or "",
                )
            _trace("core.connection_closed", thread_id=self.thread_id or "")

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
            message = await self._next_outbound()
            # Serialize once here so the size is known exactly; starlette's
            # send_json produces this same text, so sending it ourselves is
            # byte-identical and avoids serializing a huge page a second time.
            payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
            size = len(payload.encode("utf-8"))
            if size >= LARGE_OUTBOUND_MESSAGE_BYTES:
                logger.warning(
                    "%s",
                    _describe_large_outbound(message, size, self._request_methods),
                )
            send_text = getattr(self.websocket, "send_text", None)
            if callable(send_text):
                await send_text(payload)
            else:
                await self.websocket.send_json(message)
            if "id" in message:
                request_id = message.get("id")
                method = self._request_methods.pop(str(request_id), "")
                error = message.get("error")
                _trace(
                    "core.rpc.response_sent",
                    request_id=request_id,
                    method=method,
                    ok=not isinstance(error, dict),
                )
            else:
                _trace_outbound_notification(message)

    async def _next_outbound(self) -> dict[str, Any]:
        """Take control messages first, otherwise preserve notification FIFO."""
        while True:
            try:
                return self.control_outbound.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                return self._take_outbound()
            except asyncio.QueueEmpty:
                pass

            # No await occurs between clearing and checking the queues, so a
            # producer cannot set the event in that interval and be missed.
            self._outbound_ready.clear()
            try:
                return self.control_outbound.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                return self._take_outbound()
            except asyncio.QueueEmpty:
                pass
            if self._closing:
                raise asyncio.CancelledError
            await self._outbound_ready.wait()

    def _take_outbound(self) -> dict[str, Any]:
        """Pop the next notification frame, retiring its replaceable key.

        Popping the key in the same step the frame leaves the queue is what makes
        the in-place merge in ``_send`` safe: once a frame is handed to the
        sender it is no longer reachable through ``_outbound_keys`` and cannot be
        mutated while it is being serialized.
        """
        message = self.outbound.get_nowait()
        key = self._run_item_replace_key(message)
        if key is not None:
            self._outbound_keys.pop(key, None)
        return message

    async def _send(self, message: dict[str, Any], *, force_control: bool = False) -> None:
        if self._closing:
            return
        if force_control or _is_control_outbound(message):
            # Backpressure is intentional for bounded control traffic. The
            # producer belongs to a request or reader task and is cancelled by
            # run() when the peer disconnects; a bounded timeout also forces a
            # reconnect if the socket stays open but its sender cannot drain.
            try:
                await asyncio.wait_for(
                    self.control_outbound.put(message),
                    timeout=self.control_outbound_timeout_seconds,
                )
            except asyncio.TimeoutError:
                # If even the reserved lane cannot drain, stop accepting work
                # and ask the client to reconnect/resume. This puts a hard
                # bound on blocked request tasks and lets the existing resume
                # path recover persisted state.
                self._closing = True
                self._outbound_ready.set()
                logger.error(
                    "Core app-server control queue saturated; closing ws 1013 (thread=%s)",
                    self.thread_id or "-",
                )
                try:
                    await self.websocket.close(
                        code=1013,
                        reason="Control message queue saturated; reconnect to resume.",
                    )
                except Exception as exc:
                    logger.debug("core-app-server saturated close failed: %s", exc)
                return
            self._outbound_ready.set()
            return
        key = self._run_item_replace_key(message)
        if key is not None:
            # A replaceable runItem delta. If a frame for the same item is still
            # queued, merge into it in place: the pending frame already owns the
            # slot, so the newer text never adds a second frame and nothing is
            # dropped. Only intermediate frames are lost, and because the delta
            # text is concatenated the client converges on the latest state.
            pending = self._outbound_keys.get(key)
            if pending is not None:
                _merge_run_item_message(pending, message)
                return
            try:
                self.outbound.put_nowait(message)
            except asyncio.QueueFull:
                self._record_outbound_drop()
                return
            self._outbound_keys[key] = message
            self._outbound_ready.set()
            return
        try:
            self.outbound.put_nowait(message)
        except asyncio.QueueFull:
            self._record_outbound_drop()
            return
        self._outbound_ready.set()

    def _run_item_replace_key(self, message: Mapping[str, Any]) -> tuple[str, str, str] | None:
        """Return the replaceable key for a lossy runItem delta frame, else None.

        Only non-control runItem frames carrying a live ``delta`` string are
        replaceable; every state message (RPC reply, snapshot, approval, sync
        change, non-delta runItem) is either control-lane or must keep every
        frame, so it has no key and keeps the drop-on-full behaviour. The key
        matches ``_enqueue_run_item`` so a frame flushed by the coalescer is
        recognised against the one already queued.
        """
        if "id" in message or message.get("method") != CORE_RUN_ITEM_METHOD:
            return None
        params = message.get("params")
        if not isinstance(params, Mapping):
            return None
        if _run_item_kind(params) in CONTROL_OUTBOUND_RUN_ITEM_KINDS:
            return None
        value = params.get("payload") if isinstance(params.get("payload"), Mapping) else params
        inner = value.get("payload") if isinstance(value.get("payload"), Mapping) else {}
        if not isinstance(inner.get("delta"), str):
            return None
        return (
            str(value.get("thread_id") or params.get("thread_id") or self.thread_id or ""),
            str(value.get("item_id") or params.get("item_id") or ""),
            str(value.get("kind") or ""),
        )

    def _record_outbound_drop(self) -> None:
        self._outbound_dropped_count += 1
        self._outbound_drops_since_log += 1
        now = time.monotonic()
        self._schedule_outbound_gap(now)
        last_log_at = self._outbound_drop_last_log_at
        if last_log_at is not None and now - last_log_at < OUTBOUND_DROP_LOG_INTERVAL_SECONDS:
            return
        logger.warning(
            "Core app-server outbound notification queue full; dropped=%d total_dropped=%d thread=%s",
            self._outbound_drops_since_log,
            self._outbound_dropped_count,
            self.thread_id or "(unsubscribed)",
        )
        self._outbound_drops_since_log = 0
        self._outbound_drop_last_log_at = now

    def _schedule_outbound_gap(self, now: float) -> None:
        """Tell the client it missed updates so it can resynchronize.

        Mirrors the hub's ``CoreAppEventGap``: when the lossy lane drops frames,
        the client must not wait for the next full snapshot to heal. A bounded,
        rate-limited ``thread/gap`` travels on the reliable control lane, so it
        cannot itself be dropped; the control lane's own saturation policy
        (close 1013 while the client is unrecoverably slow) still bounds the
        worst case. Scheduled rather than awaited because ``_send`` is on the
        producer's hot path.
        """
        last = self._outbound_gap_last_at
        if last is not None and now - last < OUTBOUND_GAP_MIN_INTERVAL_SECONDS:
            return
        self._outbound_gap_last_at = now
        if self._closing:
            return
        task = asyncio.create_task(self._publish_outbound_gap())
        self.request_tasks.add(task)
        task.add_done_callback(self._request_task_done)

    async def _publish_outbound_gap(self) -> None:
        await self._send(
            {
                "method": THREAD_GAP_METHOD,
                "params": {
                    "thread_id": self.thread_id or "",
                    "reason": "outbound_dropped",
                    "dropped": self._outbound_dropped_count,
                },
            },
            force_control=True,
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
            # Capture the queue we are actually waiting on. A connection can
            # switch threads while this await is blocked; _unsubscribe wakes
            # the old queue so the reader can move to the new subscription.
            subscription = self.subscription
            event = await subscription.get()
            if subscription is not self.subscription:
                continue
            if isinstance(event, CoreAppEventGap):
                logger.warning("core-app-server event stream overflow; closing ws 1013 (thread=%s)", self.thread_id or "-")
                await self.websocket.close(code=1013, reason="Event stream overflow; reconnect to resume.")
                return
            if event is None:
                continue
            # Project/session mutations can be committed outside a thread
            # subscription.  They are already protocol-shaped notifications
            # from the global sync broadcaster; do not wrap them a second time
            # through event_notification().
            if isinstance(event, dict) and event.get("method") == "sync/change":
                await self._send(event)
                continue
            event_method = event.get("method") if isinstance(event, dict) else getattr(event, "method", "")
            # Persisted app events are also mobile sync deltas. Forward the
            # journal row as a protocol-neutral notification; the normal live
            # event remains below for the existing desktop projector.
            event_id = event.get("event_id") if isinstance(event, dict) else getattr(event, "event_id", "")
            event_seq = event.get("seq", 0) if isinstance(event, dict) else getattr(event, "seq", 0)
            journal = getattr(getattr(self.context, "host", None), "sync_journal", None)
            # seq=0 is the explicit marker for transient stream progress. Such
            # events are never written to the sync journal, so querying SQLite
            # for every tiny model delta only blocks this reader and can fill
            # the 256-item subscriber queue, forcing a 1013 reconnect. Persisted
            # events have a positive sequence and keep the normal sync lookup.
            if event_id and event_seq and journal is not None:
                try:
                    change = await journal.get_change(str(event_id))
                except Exception:
                    change = None
                if change is not None:
                    await self._send({"method": "sync/change", "params": change})
            if event_method == CORE_RUN_ITEM_METHOD:
                await self._enqueue_run_item(event)
                # approval_request（审批请求）是重要边界：事件流可能因订阅者
                # 溢出被强制断连而丢失，而持久化 item 的 kind 回落 tool_call
                # （审批状态只存在于事件流/requests），前端断连恢复拿不到审批
                # 卡就无法回答（死锁）。到达即节流推一次快照，让所有连接都能
                # 从快照恢复审批状态（快照由 item 表组装 + requests，见
                # snapshot_store._assemble）。
                if _run_item_kind(event) == "approval_request":
                    await self._flush_run_item_buffer()
                    now = asyncio.get_running_loop().time()
                    if now - self._last_snapshot_sent_at >= SNAPSHOT_MIN_INTERVAL_SECONDS:
                        self._last_snapshot_sent_at = now
                        await self._send_snapshot(_event_thread_id(event))
                continue
            # Non-runItem events must land after any buffered deltas so the
            # client never observes state out of order.
            await self._flush_run_item_buffer(control=True)
            await self._send(event_notification(event))
            if event_method in (CORE_RUN_ITEM_METHOD, "session/created", "session/updated"):
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
            await self._flush_run_item_buffer(control=True)
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

    async def _flush_run_item_buffer(self, *, control: bool = False) -> None:
        if self._run_item_flush_task is not None:
            self._run_item_flush_task.cancel()
            self._run_item_flush_task = None
        if not self._run_item_buffer:
            return
        buffer, self._run_item_buffer = self._run_item_buffer, {}
        for message in buffer.values():
            await self._send(message, force_control=control)

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
        subscription = self.subscription
        if self.thread_id and subscription is not None:
            self.context.hub.unsubscribe(self.thread_id, subscription)
        self.subscription = None
        self._subscription_ready.clear()
        if subscription is not None:
            # _hub_reader may currently be blocked on the old queue. Remove
            # obsolete events and wake it; otherwise switching threads leaves
            # the reader parked forever until the old thread happens to emit.
            while not subscription.empty():
                subscription.get_nowait()
            subscription.put_nowait(None)

    async def _handle_raw(self, raw: dict[str, Any]) -> None:
        if await self._handle_client_response(raw):
            return
        try:
            request = JsonRpcRequest.model_validate(raw)
        except ValidationError as exc:
            _trace(
                "core.rpc.invalid",
                request_id=raw.get("id") if isinstance(raw, dict) else None,
            )
            await self._send(
                rpc_error(
                    raw.get("id") if isinstance(raw, dict) else None,
                    code=INVALID_REQUEST,
                    message=self._invalid_request_message(),
                    data={"errors": exc.errors()},
                )
            )
            return
        request_id = request.id
        thread_id = _thread_id_from_params(request.params)
        turn_id = _turn_id_from_params(request.params)
        if request_id is not None:
            self._request_methods[str(request_id)] = request.method
        _trace(
            "core.rpc.received",
            request_id=request_id,
            method=request.method,
            thread_id=thread_id,
            turn_id=turn_id,
        )
        started_at = time.monotonic()
        if await self._handle_control_request(request):
            _trace(
                "core.rpc.processed",
                request_id=request_id,
                method=request.method,
                path="control",
                elapsed_ms=round((time.monotonic() - started_at) * 1000, 1),
            )
            return
        if not self.initialized:
            _trace(
                "core.rpc.rejected",
                request_id=request_id,
                method=request.method,
                reason="not_initialized",
            )
            await self._send_not_initialized(request)
            return
        if thread_id:
            self._subscribe(thread_id)
        if await self._handle_operation_request(request):
            _trace(
                "core.rpc.processed",
                request_id=request_id,
                method=request.method,
                path="operation_handler",
                elapsed_ms=round((time.monotonic() - started_at) * 1000, 1),
            )
            return
        try:
            outcome = await self._dispatch(request)
        except Exception as exc:
            logger.exception("Core app-server operation failed: %s", request.method)
            _trace(
                "core.rpc.failed",
                request_id=request_id,
                method=request.method,
                error=type(exc).__name__,
                elapsed_ms=round((time.monotonic() - started_at) * 1000, 1),
            )
            await self._send(rpc_error(request.id, code=SERVER_ERROR, message=str(exc)))
            return
        response_error = outcome.response.get("error") if isinstance(outcome.response, dict) else None
        _trace(
            "core.rpc.processed",
            request_id=request_id,
            method=request.method,
            path="dispatch",
            ok=not isinstance(response_error, dict),
            elapsed_ms=round((time.monotonic() - started_at) * 1000, 1),
        )
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
                    # sub_agent_control: child-directed Stop/Resume
                    # (sub_agent.interrupt / sub_agent.resume) is a Core
                    # runtime operation; runtimes without it (embedded
                    # mobile standalone) must not offer the control.
                    "capabilities": {"same_turn_resume": True, "sub_agent_control": True},
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
        if method in {"approval.respond", "session.permissions.set"}:
            # Bind the response to the subscribed thread: a connection may
            # only answer an approval request for the thread it is watching.
            thread_id = _thread_id_from_params(params)
            if not thread_id or self.thread_id != thread_id:
                return CoreLiveOperationOutcome(
                    response=rpc_error(
                        request.id,
                        code=INVALID_REQUEST,
                        message=f"{method} must target the subscribed thread",
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
        "thread/history": "thread.history",
        "thread/outline": "thread.outline",
        "turn/start": "turn.start",
        "turn/resume": "turn.resume",
        "turn/pause": "turn.pause",
        "turn/paused": "turn.pause",
        "turn/cancel": "turn.cancel",
        # ``turn/interrupt`` keeps its terminal meaning for the clients that
        # still send it (mobile). The desktop's single click sends
        # ``turn/pause`` and its long-press confirm sends ``turn/terminate``.
        "turn/interrupt": "turn.cancel",
        "turn.interrupt": "turn.cancel",
        "turn/terminate": "turn.terminate",
        "turn/stop": "turn.terminate",
        "turn/force_reset": "turn.force_reset",
        "turn/force-reset": "turn.force_reset",
        "turn.force_reset": "turn.force_reset",
        "turn/steer": "turn.steer",
        "approval/respond": "approval.respond",
        "session/permissions/set": "session.permissions.set",
        "queue/create": "queue.create",
        "queue/update": "queue.update",
        "queue/delete": "queue.delete",
        "queue/guide": "queue.guide",
    }
    return aliases.get(method, method.replace("/", "."))


def _thread_id_from_params(params: dict[str, Any]) -> str:
    return str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or params.get("sessionId") or "")


def _turn_id_from_params(params: dict[str, Any]) -> str:
    return str(params.get("turn_id") or params.get("turnId") or "")


def _describe_large_outbound(
    message: dict[str, Any],
    size: int,
    request_methods: Mapping[str, str],
) -> str:
    """One diagnostic line for an outbound message at/over the client cap.

    Carries the size plus the best-effort method / thread / turn identity so an
    oversized response can be tied to the thread that produced it without
    logging any body content.
    """
    method = str(message.get("method") or "")
    if not method and "id" in message:
        method = str(request_methods.get(str(message.get("id"))) or "")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    thread_id = str(params.get("thread_id") or params.get("threadId") or "")
    turn_id = str(params.get("turn_id") or params.get("turnId") or "")
    page_turns: Any = None
    if not thread_id:
        # RPC responses carry the page under result.snapshot.
        result = message.get("result")
        snapshot = result.get("snapshot") if isinstance(result, dict) else None
        if isinstance(snapshot, dict):
            thread_id = str(snapshot.get("thread_id") or "")
            page = snapshot.get("history_page")
            if isinstance(page, dict):
                page_turns = page.get("turn_count")
    return (
        f"Core app-server outbound message is {size} bytes "
        f"(>= the {LARGE_OUTBOUND_MESSAGE_BYTES}-byte single-message cap most "
        f"clients enforce); the local send can still succeed while the peer "
        f"aborts with 1009. method={method or '-'} thread={thread_id or '-'} "
        f"turn={turn_id or '-'} page_turns={page_turns if page_turns is not None else '-'}"
    )


def _trace_outbound_notification(message: dict[str, Any]) -> None:
    method = str(message.get("method") or "")
    if not method:
        return
    params = message.get("params")
    fields: dict[str, Any] = {"method": method}
    if isinstance(params, dict):
        fields.update(
            thread_id=str(params.get("thread_id") or ""),
            turn_id=str(params.get("turn_id") or ""),
            item_id=str(params.get("item_id") or ""),
            kind=str(params.get("kind") or ""),
        )
        if _contains_stream_delta(params):
            return
    _trace("core.event_sent", **fields)


def _contains_stream_delta(value: Any) -> bool:
    current = value
    for _ in range(4):
        if not isinstance(current, dict):
            return False
        if isinstance(current.get("delta"), str):
            return True
        current = current.get("payload")
    return False


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


def _run_item_kind(event: Any) -> str:
    """Extract the runItem kind from an envelope (dict or object form).

    The hub delivers envelopes whose ``payload`` is the serialized RunItemEvent
    dict (``{kind, item_id, payload: {...}}``) — or a dict envelope with the
    same shape. Only ``approval_request`` is interesting to the boundary
    snapshot logic.
    """
    payload = event.get("payload") if isinstance(event, dict) else getattr(event, "payload", None)
    if not isinstance(payload, dict):
        return ""
    kind = payload.get("kind")
    if isinstance(kind, str):
        return kind
    inner = payload.get("payload")
    if isinstance(inner, dict) and isinstance(inner.get("kind"), str):
        return inner["kind"]
    return ""


def _is_control_outbound(message: Mapping[str, Any]) -> bool:
    """Return whether a message needs reliable, priority-lane delivery.

    High-volume runItem text deltas can be recovered from a later snapshot or
    resume. RPC responses and every state notification use the bounded control
    lane; non-delta runItem updates and approvals are also reliable.
    """
    if "id" in message:
        return True
    method = message.get("method")
    if method == CORE_RUN_ITEM_METHOD:
        params = message.get("params")
        if not isinstance(params, dict):
            return True
        if _run_item_kind(params) in CONTROL_OUTBOUND_RUN_ITEM_KINDS:
            return True
        value = params.get("payload") if isinstance(params.get("payload"), dict) else params
        inner = value.get("payload") if isinstance(value.get("payload"), dict) else {}
        return not isinstance(inner.get("delta"), str)
    # App-server state notifications are low-volume compared with runItem
    # token deltas and need reliable delivery. Unknown notification methods
    # stay on the control lane too so a newly added state event is safe by
    # default.
    return isinstance(method, str) and bool(method)


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


def _merge_run_item_message(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    """Fold a newer runItem delta frame into the pending queued frame in place.

    ``target`` is the frame already sitting in ``outbound`` (identity, item id and
    event id are kept); ``source`` is the newer frame that would otherwise have
    been dropped. The delta strings are concatenated so the client receives the
    union of the streamed text, and every absorbed event id is recorded under
    ``_coalesced_event_ids`` so the client marks them all seen and a later
    snapshot never replays them.
    """
    target_params = target.get("params") if isinstance(target.get("params"), Mapping) else {}
    source_params = source.get("params") if isinstance(source.get("params"), Mapping) else {}
    target_value = target_params.get("payload") if isinstance(target_params.get("payload"), dict) else {}
    source_value = source_params.get("payload") if isinstance(source_params.get("payload"), Mapping) else {}
    target_inner = target_value.get("payload") if isinstance(target_value.get("payload"), dict) else {}
    source_inner = source_value.get("payload") if isinstance(source_value.get("payload"), Mapping) else {}
    target_delta = target_inner.get("delta")
    source_delta = source_inner.get("delta")
    if isinstance(target_delta, str) and isinstance(source_delta, str):
        target_inner["delta"] = target_delta + source_delta
    absorbed = target_value.get("_coalesced_event_ids")
    if not isinstance(absorbed, list):
        absorbed = target_value["_coalesced_event_ids"] = []
    target_own = str(target_value.get("event_id") or target_params.get("event_id") or "")
    if target_own and target_own not in absorbed:
        absorbed.append(target_own)
    source_ids = source_value.get("_coalesced_event_ids")
    candidates: list[Any] = []
    if isinstance(source_ids, list):
        candidates.extend(source_ids)
    candidates.append(source_value.get("event_id") or source_params.get("event_id"))
    for candidate in candidates:
        event_id = str(candidate or "")
        if event_id and event_id not in absorbed:
            absorbed.append(event_id)


__all__ = ["CoreLiveConnection", "CoreLiveConnectionAdapter", "create_core_live_router"]
