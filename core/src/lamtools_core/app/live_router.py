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
    NOT_INITIALIZED,
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
from .thread_history import DEFAULT_THREAD_HISTORY_PAGE_BYTES, _character_page_snapshot


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
    "queue/itemDispatched",
    # queue/itemUpdated / queue/itemDeleted 不在此列：事件本身携带完整状态，
    # 客户端可确定性重放；每次删除/改状态再推一份整线程快照，正是在长会话里
    # 把发送通道堵住几十秒的原因（实测 64.5MB × 十余次）。
    # queue/itemReordered 同理：事件携带完整 order。
})
# Safety net: even for snapshot-trigger events, at most one snapshot per
# connection per interval — the next trigger (or thread/resume) delivers the
# latest state anyway.
SNAPSHOT_MIN_INTERVAL_SECONDS = 1.0

# user:“也不是完全发不出去 反正卡住了好久”+(长会话的整份快照有 64MB，推送一次就
# 把发送通道占住；通知里的快照超过这个条目数就按最近 10 个回合分页，历史往前翻
# 由客户端再按页取。)
SNAPSHOT_NOTIFICATION_MAX_ITEMS = 300
SNAPSHOT_NOTIFICATION_TURN_LIMIT = 10

# RPC replies and state notifications must not compete with the lossy stream
# of high-volume runItem deltas. Both lanes are bounded; producers of control
# messages apply backpressure while the sender drains them, whereas deltas may
# be dropped and recovered from snapshots/resume.
CONTROL_OUTBOUND_RUN_ITEM_KINDS = frozenset(
    {"approval_request", "approval_response", "interaction_update"}
)

# user:“22｜把「可丢的工具进度帧」从可靠控制通道迁到可丢通道”+(进行中的工具进度
# 帧没有 delta、不并入 20ms 合并窗口，却被旧规则当成可靠消息逐帧塞进 64 格控制
# 通道，于是通道打满 → 1013 重连风暴 → 订阅者队列溢出 → WAL 停止回收。分流必须按
# 「这帧丢了客户端会不会停在回不来的状态」判定，而不是按「有没有 delta」判定。)
RELIABLE = "reliable"
LOSSY = "lossy"
DROP = "drop"

# 进度类：后续帧总是重述同一 item 的全量状态（content / arguments / phase），所以
# 「最新一帧胜出」就能收敛，中间帧丢了只是少画几帧。
LOSSY_PROGRESS_RUN_ITEM_KINDS = frozenset(
    {"message", "thinking", "tool_call", "model_phase"}
)
# 结果与决策类：丢一帧客户端就永远看不到工具结束/审批卡，必须可靠。
RELIABLE_RUN_ITEM_KINDS = frozenset(
    {
        "tool_result",
        "status",
        "usage",
        "error",
        "artifact",
        "verification",
        "handoff",
    }
)

# user:“事件通道压力过高：可靠通道 0/64；已丢弃 400 帧可丢进度；正在自动恢复，无需操作”+(只在可靠消息实际积压时提示，进度去重留在诊断日志)
CONTROL_QUEUE_ALERT_RATIO = 0.5
CONTROL_QUEUE_ALERT_MIN_DEPTH = 8
BACKPRESSURE_NOTIFICATION_METHOD = "core/backpressure"
BACKPRESSURE_MIN_INTERVAL_SECONDS = 10.0

# user:“查清 constant 安装版为什么退出 + 修掉事件风暴”+(同一 item 的同一
# 「进行中」帧只下发一次：模型流式生成工具参数时，每个 chunk 都重投影一次
# 同一个 tool_call runItem；这类事件没有 delta、不走 20ms 合并窗口，原来逐帧
# 直发，实测同一 item 1 秒下发 283 帧、19 分钟写满一个 16MB 的日志分片。
# 终态与结果类事件绝不参与去重——吞掉一个终态帧就等于客户端永远等不到工具结束。)
TERMINAL_RUN_ITEM_STATUSES = frozenset(
    {"completed", "complete", "failed", "cancelled", "canceled",
     "interrupted", "error", "denied", "done", "ok"}
)
NON_DEDUPED_RUN_ITEM_KINDS = frozenset(
    {"tool_result", "status", "usage", "approval_request", "approval_response",
     "interaction_update"}
)
# 指纹里必须剔除的簿记字段：它们每次重投影都不一样，却与界面状态无关。
RUN_ITEM_VOLATILE_FIELDS = frozenset(
    {"event_id", "_coalesced_event_ids", "seq", "event_seq", "revision",
     "created_at", "updated_at", "timestamp"}
)
MAX_TRACKED_RUN_ITEM_KEYS = 4096
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
    not_initialized_code: int = NOT_INITIALIZED
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
        # user:"Connection is not initialized"+(旧构建里未握手期间的轮询把同一个拒绝写成
        # 了 3 万多行日志，淹没真正的问题；这里只保留累计计数，日志按采样输出。)
        self._not_initialized_rejects = 0
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
        # 上一次真正下发的「进行中」runItem 状态指纹，按 (thread, item, kind)
        # 记录；命中即整帧丢弃：内容一模一样，客户端状态已经正确，重发只是把
        # 发送通道和日志一起淹掉。
        self._last_run_item_fingerprints: dict[tuple[str, str, str], str] = {}
        self._suppressed_run_item_count = 0
        self._suppressed_run_item_logged = 0
        self._suppressed_run_item_last_log_at: float | None = None
        # user:“22｜把「可丢的工具进度帧」从可靠控制通道迁到可丢通道”+(可丢通道的
        # 计数必须看得见：合并了多少、真丢了多少、可靠通道最深到过几格；这些就是
        # 用户可见告警的依据。)
        self._lossy_merged_count = 0
        self._lossy_dropped_count = 0
        self._lossy_stats_last_log_at: float | None = None
        self._control_peak_depth = 0
        self._control_frames_enqueued = 0
        # 已被同一 item 的终态帧取代、但还排在可丢通道里的旧进度帧（按对象身份记，
        # 出队时直接跳过，避免终态之后又来一条过期的 running 把工具行重新点亮）。
        self._superseded_frames: set[int] = set()
        self._backpressure_last_at: float | None = None

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
            if self._lossy_merged_count or self._lossy_dropped_count:
                _trace(
                    "core.lossy_lane_summary",
                    merged=self._lossy_merged_count,
                    dropped=self._lossy_dropped_count,
                    control_peak_depth=self._control_peak_depth,
                    thread_id=self.thread_id or "",
                )
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
        while True:
            message = self.outbound.get_nowait()
            if id(message) in self._superseded_frames:
                # 同一 item 的终态帧已经在可靠通道里等着了，这条过期进度再发出去只会
                # 把客户端状态点回 running（甚至盖掉结果）。
                self._superseded_frames.discard(id(message))
                self._lossy_dropped_count += 1
                continue
            key = self._run_item_replace_key(message)
            if key is not None:
                self._outbound_keys.pop(key, None)
            return message

    async def _send(self, message: dict[str, Any], *, force_control: bool = False) -> None:
        if self._closing:
            return
        # user:“22｜把「可丢的工具进度帧」从可靠控制通道迁到可丢通道”+(先分流再投递：
        # 进行中的工具进度帧与流式 delta 走可丢通道，终态/结果/审批/未知类型走可靠
        # 通道；force_control 只留给必须插队的控制信号（快照、gap、应答）。)
        lane = RELIABLE if force_control else classify_run_item_delivery(message)
        if lane == RELIABLE:
            if self._suppress_duplicate_run_item(message):
                return
            self._retire_pending_progress(message)
            self._control_peak_depth = max(
                self._control_peak_depth, self.control_outbound.qsize()
            )
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
            self._control_frames_enqueued += 1
            self._control_peak_depth = max(
                self._control_peak_depth, self.control_outbound.qsize()
            )
            self._maybe_report_backpressure(now=time.monotonic())
            self._outbound_ready.set()
            return
        if lane == DROP:
            self._record_lossy_drop()
            return
        if self._suppress_duplicate_run_item(message):
            self._record_lossy_drop()
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
                self._lossy_merged_count += 1
                self._log_lossy_lane_stats()
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
        """Return the merge key for a lossy runItem frame, else None.

        user:“22｜把「可丢的工具进度帧」从可靠控制通道迁到可丢通道”+(可丢通道里同一
        item 只占一个格：delta 帧拼接文本，进行中的进度帧用最新状态覆盖，队列深度
        因此不随帧数增长。)

        Only frames the classifier sends to the lossy lane get a key. Every state
        message (RPC reply, snapshot, approval, sync change, reliable runItem) is
        control-lane and must keep every frame, so it has no key. The key matches
        ``_enqueue_run_item`` so a frame flushed by the coalescer is recognised
        against the one already queued.
        """
        if not isinstance(message, Mapping):
            return None
        if classify_run_item_delivery(message) != LOSSY:
            return None
        params = message.get("params")
        if not isinstance(params, Mapping):
            return None
        value = params.get("payload") if isinstance(params.get("payload"), Mapping) else params
        item_id = str(value.get("item_id") or params.get("item_id") or "")
        if not item_id:
            return None
        return (
            str(value.get("thread_id") or params.get("thread_id") or self.thread_id or ""),
            item_id,
            str(value.get("kind") or ""),
        )

    def _retire_pending_progress(self, message: Mapping[str, Any]) -> None:
        """Mark queued lossy frames of the same item superseded by a reliable one.

        A terminal frame and the progress frames it ends can carry different
        kinds (``tool_result`` vs ``tool_call``), so the match is deliberately
        per item, not per (item, kind).
        """
        identity = _run_item_identity(message)
        if identity is None:
            return
        thread_id, item_id = identity
        for key, pending in list(self._outbound_keys.items()):
            if key[1] != item_id:
                continue
            if thread_id and key[0] and key[0] != thread_id:
                continue
            self._outbound_keys.pop(key, None)
            if len(self._superseded_frames) > 256:
                self._superseded_frames.clear()
            self._superseded_frames.add(id(pending))

    def _suppress_duplicate_run_item(self, message: Mapping[str, Any]) -> bool:
        """Drop a runItem frame that repeats the state already sent for this item.

        user:“查清 constant 安装版为什么退出 + 修掉事件风暴”+(工具参数流式生成时，
        每个 chunk 都重投影一次同一个 tool_call：没有 delta，不并入 20ms 合并
        窗口，而是逐帧进控制通道。同一 item 的同一「进行中」状态只发一次；
        内容变了、或到了终态（completed/failed/...），照常下发。)
        """
        if message.get("method") != CORE_RUN_ITEM_METHOD:
            return False
        params = message.get("params")
        if not isinstance(params, Mapping):
            return False
        value = params.get("payload") if isinstance(params.get("payload"), Mapping) else params
        if not isinstance(value, Mapping):
            return False
        item_id = str(value.get("item_id") or params.get("item_id") or "")
        if not item_id:
            return False
        kind = str(value.get("kind") or "")
        status = str(value.get("status") or "").lower()
        key = (
            str(value.get("thread_id") or params.get("thread_id") or self.thread_id or ""),
            item_id,
            kind,
        )
        if kind in NON_DEDUPED_RUN_ITEM_KINDS or status in TERMINAL_RUN_ITEM_STATUSES:
            # 终态/结果帧一律放行，并让该 item 的去重状态失效：之后若再有同内容
            # 的「进行中」帧（例如 resume 重跑），必须重新送达，不能被旧指纹吞掉。
            self._last_run_item_fingerprints.pop(key, None)
            return False
        inner = value.get("payload") if isinstance(value.get("payload"), Mapping) else {}
        if isinstance(inner.get("delta"), str):
            # user:“22｜把「可丢的工具进度帧」从可靠控制通道迁到可丢通道”+(delta 是
            # 增量文本：两帧内容相同也可能是要拼进客户端的两个字，按内容去重会吞字。)
            return False
        try:
            fingerprint = json.dumps(
                _stable_run_item_payload(inner),
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        except (TypeError, ValueError):
            return False
        if self._last_run_item_fingerprints.get(key) == fingerprint:
            self._suppressed_run_item_count += 1
            self._log_suppressed_run_items()
            return True
        if len(self._last_run_item_fingerprints) > MAX_TRACKED_RUN_ITEM_KEYS:
            self._last_run_item_fingerprints.clear()
        self._last_run_item_fingerprints[key] = fingerprint
        return False

    def _log_suppressed_run_items(self) -> None:
        """Rate-limited visibility: suppression itself must stay observable."""
        now = time.monotonic()
        last = self._suppressed_run_item_last_log_at
        if last is not None and now - last < OUTBOUND_DROP_LOG_INTERVAL_SECONDS:
            return
        self._suppressed_run_item_last_log_at = now
        logger.info(
            "core-app-server suppressed %d duplicate runItem frame(s) (total=%d, thread=%s)",
            self._suppressed_run_item_count - self._suppressed_run_item_logged,
            self._suppressed_run_item_count,
            self.thread_id or "-",
        )
        self._suppressed_run_item_logged = self._suppressed_run_item_count

    def _should_trace_not_initialized_reject(self) -> bool:
        """Sample repeated pre-handshake rejections instead of logging each one.

        user:"这次为什么又卡死到必须重启"+(60 次/分钟的轮询拒绝曾被逐条写进日志，
        19 分钟内写满 16MB 分片；前 3 次全记，之后每 100 次记一条并带累计数。)
        """
        count = self._not_initialized_rejects
        return count <= 3 or count % 100 == 0

    def _record_lossy_drop(self) -> None:
        """Count one frame the lossy lane did not need to deliver."""
        self._lossy_dropped_count += 1
        self._log_lossy_lane_stats()

    def _log_lossy_lane_stats(self, *, force: bool = False) -> None:
        """Report merged/dropped frames on a 10s throttle.

        user:“22｜把「可丢的工具进度帧」从可靠控制通道迁到可丢通道”+(被合并/丢弃的
        帧数按 10 秒节流打一条日志，别再让 283 帧/秒无声地滚过去。)
        """
        now = time.monotonic()
        last = self._lossy_stats_last_log_at
        if last is not None and now - last < OUTBOUND_DROP_LOG_INTERVAL_SECONDS:
            return
        merged = self._lossy_merged_count
        dropped = self._lossy_dropped_count
        if not merged and not dropped and not force:
            return
        self._lossy_stats_last_log_at = now
        logger.info(
            "core-app-server lossy lane merged=%d dropped=%d control_depth=%d "
            "control_peak=%d thread=%s",
            merged,
            dropped,
            self.control_outbound.qsize(),
            self._control_peak_depth,
            self.thread_id or "-",
        )

    def _maybe_report_backpressure(self, *, now: float) -> None:
        """Report a backed-up control queue without blocking reliable delivery."""
        if self._closing:
            return
        depth = self.control_outbound.qsize()
        limit = self.control_outbound.maxsize or 1
        threshold = max(
            CONTROL_QUEUE_ALERT_MIN_DEPTH, int(limit * CONTROL_QUEUE_ALERT_RATIO)
        )
        if depth < threshold:
            return
        last = self._backpressure_last_at
        if last is not None and now - last < BACKPRESSURE_MIN_INTERVAL_SECONDS:
            return
        self._backpressure_last_at = now
        logger.warning(
            "core-app-server reliable queue under pressure: control_depth=%d/%d thread=%s",
            depth,
            limit,
            self.thread_id or "-",
        )
        # Keep capacity for real control traffic. WAL has its own maintenance loop.
        if limit - depth <= 1:
            return
        self.control_outbound.put_nowait(
            {
                "method": BACKPRESSURE_NOTIFICATION_METHOD,
                "params": {
                    "thread_id": self.thread_id or "",
                    "reason": "control_queue_pressure",
                    "control_queue_depth": depth,
                    "control_queue_limit": limit,
                },
            }
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
                    # user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(避免每条事件都从数据库读取并重复发送完整工具输出)。
                    lookup = getattr(journal, "get_change_header", journal.get_change)
                    change = await lookup(str(event_id))
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
                if _run_item_kind(event) in {"approval_request", "approval_response"}:
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
        message = {"method": CORE_RUN_ITEM_METHOD, "params": params}
        # user:“22｜把「可丢的工具进度帧」从可靠控制通道迁到可丢通道”+(非 delta 的
        # 进行中进度帧也进 20ms 合并窗口，并按同 item 覆盖：一次工具参数流式生成
        # 不再逐帧直发，每个窗口最多出一帧；终态/结果帧先把缓冲冲出去再走可靠通道，
        # 客户端看到的顺序不会倒。)
        lane = classify_run_item_delivery(message)
        if lane == RELIABLE:
            # Reliable state frames go out immediately, ordered after any
            # buffered lossy frames for the same item.
            await self._flush_run_item_buffer(control=True)
            await self._send(message, force_control=True)
            return
        if lane == DROP:
            self._record_lossy_drop()
            return
        value = params.get("payload") if isinstance(params.get("payload"), dict) else params
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
            # 同一 item 的下一帧：delta 拼接，进行中的进度帧用最新状态覆盖。
            # 合并发生在这里（20ms 窗口内），队列层的覆盖是第二道保险。
            _merge_run_item_message(
                buffered, {"method": CORE_RUN_ITEM_METHOD, "params": _copy_run_item_params(params)}
            )
            self._lossy_merged_count += 1
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
        payload = _snapshot_for_notification(snapshot)
        if payload is not snapshot:
            logger.info(
                "[live] paged snapshot notification thread=%s items=%d",
                thread_id,
                _snapshot_item_count(snapshot),
            )
        await self._send(snapshot_notification(payload))

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
            # user:"界面出现 Connection is not initialized"+(先回包再记日志：回包是客户端
            # 自愈的唯一依据，任何路径都不能让它落空；重复拒绝按采样记录。)
            self._not_initialized_rejects += 1
            await self._send_not_initialized(request)
            if self._should_trace_not_initialized_reject():
                _trace(
                    "core.rpc.rejected",
                    request_id=request_id,
                    method=request.method,
                    reason="not_initialized",
                    count=self._not_initialized_rejects,
                )
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
        # user:"界面出现 Connection is not initialized"+(每个未握手的业务帧都要立刻拿到
        # 一条可识别的回包：专用错误码 + reason/retriable。客户端据此重新握手并重试，
        # 既不会把帧丢进黑洞，也不会把这条当成致命参数错误弹给用户看。)
        await self._send(
            rpc_error(
                request.id,
                code=self.adapter.not_initialized_code,
                message=self.adapter.not_initialized_message,
                data={"reason": "not_initialized", "retriable": True},
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
        if self._not_initialized_rejects:
            # 让运维能直接看出「这条连接曾经在未握手状态被拒了多少帧」。
            _trace(
                "core.rpc.not_initialized_recovered",
                rejected_before_initialize=self._not_initialized_rejects,
            )
            self._not_initialized_rejects = 0
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
                    "capabilities": {
                        "same_turn_resume": True,
                        "sub_agent_control": True,
                        # The backend owns the question-expiry timer; a client
                        # that sees this must not run a second local timer.
                        "ask_auto_continue_backend": True,
                    },
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
        if method in {"turn.start", "turn.replace"} and self.browser_origin is not None:
            # A browser page must not self-grant auto-approval: strip any
            # client-declared policy so the server-side runtimeControls
            # settings decide.  Non-browser callers (CLI / local processes)
            # keep their explicit policy.
            if params.get("approval_policy") is not None or params.get("approvalPolicy") is not None:
                params = {**params}
                params.pop("approval_policy", None)
                params.pop("approvalPolicy", None)
        if method in {"approval.respond", "session.permissions.set", "session.composer.set"}:
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
        "thread/writeReceipts": "thread.writeReceipts",  # user:“全修”+(断线核对只读，不重放写请求)。
        "thread/history": "thread.history",
        "thread/outline": "thread.outline",
        "turn/start": "turn.start",
        "turn/replace": "turn.replace",  # user:“全做”+(编辑通过实时接口固定历史回合)。
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
        "session/composer/set": "session.composer.set",
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


def _snapshot_item_count(snapshot: dict[str, Any]) -> int:
    total = 0
    for container in (snapshot.get("items"), (snapshot.get("core") or {}).get("items")):
        if isinstance(container, dict):
            total += len(container)
    return total


def _snapshot_for_notification(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Bound an unsolicited snapshot push to one recent page.

    user:“也不是完全发不出去 反正卡住了好久”+(64.5MB 的整份线程快照会让发送通道
    排队几十秒；超过阈值时只推最近 10 个回合、2MB 以内的一页，并带上
    ``history_page`` 让客户端按页往前翻，其余字段保持不变。)
    """
    # user:“调查并检修 constant 内 sunday 出现过的所有报错，整理并给出方案，然后修复，不要出错”+(条目少也可能超过客户端单帧限制，分页同时按大小判断)。
    if (_snapshot_item_count(snapshot) <= SNAPSHOT_NOTIFICATION_MAX_ITEMS
            and len(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            <= DEFAULT_THREAD_HISTORY_PAGE_BYTES):
        return snapshot
    return _character_page_snapshot(
        snapshot,
        before_item_id=None,
        before_seq=None,
        char_limit=10_000_000,
        turn_limit=SNAPSHOT_NOTIFICATION_TURN_LIMIT,
        byte_limit=DEFAULT_THREAD_HISTORY_PAGE_BYTES,
    )


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


def _run_item_identity(message: Mapping[str, Any]) -> tuple[str, str] | None:
    """Return ``(thread_id, item_id)`` for a runItem notification, else None."""
    if not isinstance(message, Mapping):
        return None
    if message.get("method") != CORE_RUN_ITEM_METHOD:
        return None
    params = message.get("params")
    if not isinstance(params, Mapping):
        return None
    value = params.get("payload") if isinstance(params.get("payload"), Mapping) else params
    if not isinstance(value, Mapping):
        return None
    item_id = str(value.get("item_id") or params.get("item_id") or "")
    if not item_id:
        return None
    return (
        str(value.get("thread_id") or params.get("thread_id") or ""),
        item_id,
    )


def classify_run_item_delivery(
    message: Mapping[str, Any], *, already_delivered: bool = False
) -> str:
    """Decide how one outbound frame must travel: ``reliable`` | ``lossy`` | ``drop``.

    user:“22｜把「可丢的工具进度帧」从可靠控制通道迁到可丢通道”+(判定收成一个纯
    函数：给定一帧判定可靠/可丢/丢且无新信息；未知类型一律按可靠处理，不能猜丢。)

    Why these frames may be dropped (each rule is load-bearing):

    * a frame carrying a ``delta`` string is *incremental* text — the client
      concatenates deltas per item, so merging one into the next loses nothing;
    * an in-progress frame without ``delta`` (tool_call arguments, thinking,
      model_phase) restates the whole item every time, so the newest frame
      supersedes the older ones and the client still converges;
    * terminal frames and ``tool_result`` / ``status`` / ``usage`` /
      ``approval_*`` / ``error`` are state boundaries and decision points:
      losing one leaves the client with a tool row that never ends or an
      approval card that never appears — those must stay reliable;
    * an unknown kind, an unknown method or an RPC reply is reliable by
      default: a newly added event type may be slow, never silently lost.
    """
    if not isinstance(message, Mapping):
        return RELIABLE
    if "id" in message:
        return RELIABLE
    if message.get("method") != CORE_RUN_ITEM_METHOD:
        return RELIABLE
    params = message.get("params")
    if not isinstance(params, Mapping):
        return RELIABLE
    kind = _run_item_kind(params)
    value = params.get("payload") if isinstance(params.get("payload"), Mapping) else params
    if not isinstance(value, Mapping):
        return RELIABLE
    inner = value.get("payload") if isinstance(value.get("payload"), Mapping) else {}
    status = str(value.get("status") or "").strip().lower()
    if kind in RELIABLE_RUN_ITEM_KINDS or kind in CONTROL_OUTBOUND_RUN_ITEM_KINDS:
        return RELIABLE
    if status in TERMINAL_RUN_ITEM_STATUSES:
        return RELIABLE
    if isinstance(inner.get("delta"), str):
        # 增量文本：先于 kind 判定（旧实现也是这么分的）。客户端按 item 拼接 delta，
        # 所以它可以被合并，但不能按内容去重（两帧同样的 "ha" 就是两个 "ha"）。
        return LOSSY
    if kind not in LOSSY_PROGRESS_RUN_ITEM_KINDS:
        # 未知 kind 且没有 delta：宁可慢一点走可靠通道，也不能猜着丢。
        return RELIABLE
    if not str(value.get("item_id") or params.get("item_id") or ""):
        # 没有 item 身份的进度帧客户端放不进任何一行，留着也应用不了。
        return DROP
    if already_delivered:
        return DROP
    return LOSSY


def _stable_run_item_payload(value: Any, depth: int = 0) -> Any:
    """Strip volatile bookkeeping fields so two identical states fingerprint alike."""
    if depth > 3:
        return value
    if isinstance(value, Mapping):
        return {
            key: _stable_run_item_payload(item, depth + 1)
            for key, item in value.items()
            if key not in RUN_ITEM_VOLATILE_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_stable_run_item_payload(item, depth + 1) for item in value]
    return value


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
        # 增量文本：两段都要，拼起来下发。
        target_inner["delta"] = target_delta + source_delta
        for key, value in source_inner.items():
            if key != "delta":
                target_inner[key] = value
    elif source_inner:
        # user:“22｜把「可丢的工具进度帧」从可靠控制通道迁到可丢通道”+(进行中的进度帧
        # 每帧都是同一 item 的全量状态，最新一帧胜出：覆盖旧状态而不是拼接，客户端
        # 据此收敛到最新的工具参数/思考内容。)
        merged = {**target_inner, **source_inner}
        target_inner.clear()
        target_inner.update(merged)
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


__all__ = [
    "DROP",
    "LOSSY",
    "RELIABLE",
    "CoreLiveConnection",
    "CoreLiveConnectionAdapter",
    "classify_run_item_delivery",
    "create_core_live_router",
]
