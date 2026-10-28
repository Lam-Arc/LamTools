"""QQ bot runtime: gateway lifecycle, inbound pipeline, commands and RPC state.

One instance owns one QQ bot.  The host starts it when the plugin is enabled
and stops it on disable/update.  The QQ gateway, token refresher and cleanup
tasks are reported through ``lifecycle_tasks`` so the host can revoke
availability if the gateway dies unexpectedly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from .agent_bridge import AgentBridge, TurnTimeout
from .binding import BindingService, BindingState, QQBindClient
from .channels import (
    ApprovalChannel,
    InteractionRouter,
    QuestionChannel,
    answer_text,
    build_approval_keyboard,
    build_question_keyboard,
    decode_button_data,
    format_question,
    parse_answer,
)
from .commands import CommandContext, CommandRegistry, build_commands
from .config import (
    agent_name,
    build_late_context,
    load_config,
    redacted,
    save_config,
    scope_prompt,
    session_key,
)
from .constants import (
    DEFAULT_API_BASE_URL,
    DEFAULT_REPLY_LIMIT,
    DEFAULT_TOKEN_BASE_URL,
)
from .media import MediaStore, path_is_allowed, send_media_file
from .session_target import SessionTargetClient
from .state import reset_current_runtime, set_current_runtime
from .middleware import (
    MemoryHistoryStore,
    MemoryRefIndexStore,
    MiddlewareContext,
    access_policy,
    attachment_processor,
    build_agent_body,
    content_sanitizer,
    envelope_formatter,
    history_buffer,
    mention_gate,
    message_filter,
    quote_ref,
    rate_limiter,
    run_chain,
    typing_indicator,
)
from .outbound import OutboundRouter
from .protocol import (
    GatewaySessionStore,
    InboundMessage,
    MsgIdCache,
    QQApi,
    QQGateway,
    ReplyLimiter,
    ReplyTarget,
)
from .bubbles import BubbleOptions
from .util import format_relative_time, resolve_plugin_path, short_sender_id, split_bubbles


class MergeGuard:
    """Per-peer serialization with the upstream ``merge`` strategy.

    The active message runs immediately.  Messages arriving while it runs are
    buffered; when it finishes they are merged into one synthetic message and
    processed once.  This prevents concurrent stream_messages calls for the
    same peer while preserving every message's text and attachments.
    """

    def __init__(self, max_queue: int) -> None:
        self.max_queue = max(0, int(max_queue))
        self._states: dict[str, dict[str, Any]] = {}

    async def run(self, ctx: MiddlewareContext, downstream: Any) -> None:
        key = f"{ctx.message.scope}:{ctx.message.peer_id}"
        state = self._states.get(key)
        if state is not None and state["busy"]:
            if len(state["buffer"]) >= self.max_queue:
                if getattr(self, "logger", None) is not None:
                    self.logger.warning(
                        "QQ inbound dropped reason=merge-queue-full messageId=%s peer=%s:%s",
                        ctx.message.message_id,
                        ctx.message.scope,
                        ctx.message.peer_id,
                    )
                return
            state["buffer"].append(ctx)
            return
        state = {"busy": True, "buffer": []}
        self._states[key] = state
        try:
            await downstream(ctx)
            while state["buffer"]:
                batch = state["buffer"]
                state["buffer"] = []
                await downstream(merge_contexts(batch))
        finally:
            state["busy"] = False
            self._states.pop(key, None)


def merge_contexts(batch: list[MiddlewareContext]) -> MiddlewareContext:
    base = batch[-1]
    parts: list[str] = []
    attachments: list[dict[str, Any]] = []
    mentions: list[dict[str, Any]] = []
    for item in batch:
        message = item.message
        text = (message.content or "").strip()
        if not text and not message.attachments:
            continue
        if message.kind == "group":
            name = message.sender_name or short_sender_id(message.sender_id)
            parts.append(f"[{name} ({message.sender_id})] {text}")
        else:
            parts.append(text)
        attachments.extend(message.attachments or [])
        mentions.extend(message.mentions or [])
    merged_message = replace(
        base.message,
        content="\n\n".join(part for part in parts if part),
        attachments=attachments,
        mentions=mentions,
    )
    return MiddlewareContext(
        message=merged_message,
        bot=base.bot,
        state=dict(base.state),
        received_at=min(item.received_at for item in batch),
    )


class QQBotRuntime:
    def __init__(
        self,
        context: Any,
        *,
        bot_id: str = "default",
        data_dir: str | Path | None = None,
    ) -> None:
        self.bot_id = str(bot_id or "default").strip() or "default"
        self.context = context
        self._explicit_data_dir = data_dir is not None
        self.data_dir = (
            Path(data_dir)
            if data_dir is not None
            else Path(getattr(context, "data_dir", None) or Path(__file__).resolve().parent.parent / "data")
        )
        self.work_root = Path(getattr(context, "work_root", None) or Path.cwd())
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "logs").mkdir(parents=True, exist_ok=True)
        self.logger = self._make_logger()
        self.config = load_config(self.data_dir)
        self.running = False
        self._gateway: QQGateway | None = None
        self._gateway_task: asyncio.Task | None = None
        self._api: QQApi | None = None
        self._binding: BindingService | None = None
        self._bridge: AgentBridge | None = None
        self._target: SessionTargetClient | None = None
        self._outbound: OutboundRouter | None = None
        self._commands: CommandRegistry | None = None
        self._evictor_task: asyncio.Task | None = None
        self._media_task: asyncio.Task | None = None
        self._watcher_task: asyncio.Task | None = None
        self._history = MemoryHistoryStore()
        self._quote_store = MemoryRefIndexStore()
        self._cache = MsgIdCache()
        self._limiter = ReplyLimiter(limit=int(self.config.get("replyLimit") or DEFAULT_REPLY_LIMIT))
        self._media = MediaStore(self.data_dir, self.logger)
        self._approvals = ApprovalChannel(logger=self.logger)
        self._questions = QuestionChannel(logger=self.logger)
        self._target_pending: dict[str, asyncio.Future] = {}
        self._target_questions: dict[str, dict[str, Any]] = {}
        self._target_event_task: asyncio.Task | None = None
        self._target_peers: dict[str, dict[str, ReplyTarget]] = {}
        self._target_peers_path = self.data_dir / "target-peers.json"
        self._load_target_peers()
        self._target_sent_items: dict[str, set[str]] = {}
        self._target_sent_texts: dict[str, set[str]] = {}
        self._interactions: InteractionRouter | None = None
        self._guard = MergeGuard(int(self.config.get("maxQueue") or 20))
        self._last_config_mtime = self._config_mtime()
        self._started_at = time.time()
        self._last_error = ""

    # ── Logging ────────────────────────────────────────────────────────────
    def _make_logger(self) -> logging.Logger:
        logger = logging.getLogger(f"qqbot.{self.bot_id}")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.FileHandler(self.data_dir / "logs" / "qqbot.log", encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
            console = logging.StreamHandler()
            console.setFormatter(logging.Formatter(f"[qq-bot:{self.bot_id}] %(levelname)s %(message)s"))
            logger.addHandler(console)
        logger.propagate = False
        return logger

    def _config_mtime(self) -> float:
        try:
            return (self.data_dir / "config.jsonc").stat().st_mtime
        except OSError:
            return 0.0

    # ── Lifecycle ──────────────────────────────────────────────────────────
    async def start(self, context: Any | None = None) -> None:
        if self.running:
            return
        if context is not None:
            self.context = context
            if not self._explicit_data_dir and getattr(context, "data_dir", None):
                self.data_dir = Path(context.data_dir)
            if getattr(context, "work_root", None):
                self.work_root = Path(context.work_root)
        self.config = load_config(self.data_dir)
        # user:“该补齐就去补齐”+(宿主提供按插件隔离的密钥存储；QQ 的
        # AppSecret 优先放宿主密钥库，旧配置里的明文在启动时迁移并清掉)。
        self._migrate_secret()
        # Environment credentials are an in-memory fallback, matching the
        # upstream QQBOT_APPID / QQBOT_SECRET behaviour without writing them
        # into the config file.
        if not self.config.get("appId") and os.environ.get("QQBOT_APPID"):
            self.config["appId"] = os.environ["QQBOT_APPID"]
        if not self.config.get("appSecret") and os.environ.get("QQBOT_SECRET"):
            self.config["appSecret"] = os.environ["QQBOT_SECRET"]
        self._last_config_mtime = self._config_mtime()
        self.logger.setLevel(logging.DEBUG if self.config.get("debug") else logging.INFO)
        self._bridge = AgentBridge(
            context=self.context,
            config=self.config,
            data_dir=self.data_dir,
            work_root=self.work_root,
            logger=self.logger,
            approvals=self._approvals,
            questions=self._questions,
            on_event=self._on_agent_event,
        )
        self._target = SessionTargetClient(
            self.context,
            timeout_ms=int(self.config.get("processingTimeoutMs") or 30 * 60 * 1000),
        )
        self._interactions = InteractionRouter(
            approvals=self._approvals,
            questions=self._questions,
            manager=self._bridge,
        )
        self._commands = CommandRegistry(build_commands(self._bridge, self, self.config))
        self._evictor_task = asyncio.create_task(self._idle_evictor(), name="qqbot:idle-evictor")
        self._media_task = asyncio.create_task(self._media_cleaner(), name="qqbot:media-cleaner")
        self._watcher_task = asyncio.create_task(self._config_watcher(), name="qqbot:config-watcher")
        self.running = True
        self._start_target_event_watcher()
        app_id = self._app_id()
        app_secret = self._app_secret()
        if app_id and app_secret:
            await self._start_gateway()
        else:
            self._start_binding()
        self.logger.info("QQ bot runtime started (bound=%s)", bool(app_id and app_secret))

    async def stop(self) -> None:
        self.running = False
        for future in list(self._target_pending.values()):
            if not future.done():
                future.cancel()
        self._target_pending.clear()
        self._target_questions.clear()
        self._stop_target_event_watcher()
        for task in (self._evictor_task, self._media_task, self._watcher_task):
            if task is not None:
                task.cancel()
        tasks = [task for task in (self._evictor_task, self._media_task, self._watcher_task) if task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._evictor_task = None
        self._media_task = None
        self._watcher_task = None
        await self._stop_gateway()
        await self._stop_binding()
        if self._bridge is not None:
            await self._bridge.dispose_all()
            self._bridge = None
        self.logger.info("QQ bot runtime stopped")
        for handler in list(self.logger.handlers):
            try:
                handler.close()
            except Exception:
                pass
            self.logger.removeHandler(handler)

    def health_check(self) -> dict[str, Any]:
        app_id = self._app_id()
        app_secret = self._app_secret()
        bound = bool(app_id and app_secret)
        gateway_state = "unbound"
        if self._gateway is not None:
            if self._gateway.connected:
                gateway_state = "connected"
            elif self._gateway_task is not None and not self._gateway_task.done():
                gateway_state = "connecting"
            else:
                gateway_state = "stopped"
        binding_state = self._binding.state.phase if self._binding is not None else "idle"
        ready = bool(self.running)
        error = ""
        if bound and self._gateway_task is not None and self._gateway_task.done() and not self._gateway.connected:
            ready = False
            error = "QQ gateway task stopped unexpectedly"
        return {
            "ready": ready,
            "bound": bound,
            "gateway": gateway_state,
            "binding": binding_state,
            "sessions": len(self._bridge.all_sessions()) if self._bridge is not None else 0,
            **({"error": error} if error else {}),
        }

    @property
    def lifecycle_tasks(self) -> tuple[asyncio.Task, ...]:
        tasks = [self._gateway_task, self._evictor_task, self._media_task, self._watcher_task]
        return tuple(task for task in tasks if task is not None)

    @property
    def app_id(self) -> str:
        return self._app_id()

    # ── Credentials / gateway ──────────────────────────────────────────────
    def _app_id(self) -> str:
        return str(self.config.get("appId") or os.environ.get("QQBOT_APPID") or "").strip()

    def _secret_view(self) -> Any | None:
        try:
            return self.context.service("secrets")
        except Exception:
            return None

    def _secret_key(self) -> str:
        # The first/migrated bot keeps the historical key so existing installs
        # and tests continue to work; additional bots get their own key.
        return "appSecret" if self.bot_id in {"", "default"} else f"appSecret:{self.bot_id}"

    def _stored_secret(self) -> str:
        view = self._secret_view()
        if view is None:
            return ""
        try:
            return str(view.get(self._secret_key()) or "").strip()
        except Exception as exc:  # noqa: BLE001 - a corrupt secret must be visible
            self.logger.warning("QQ secret store read failed: %s", exc)
            return ""

    def _save_credentials(self, app_id: str, app_secret: str) -> dict[str, Any]:
        view = self._secret_view()
        if view is not None and app_secret:
            view.set(self._secret_key(), app_secret)
            return save_config(self.data_dir, {"appId": app_id, "appSecret": ""})
        return save_config(self.data_dir, {"appId": app_id, "appSecret": app_secret})

    def _migrate_secret(self) -> None:
        stored = self._stored_secret()
        if stored:
            self.config["appSecret"] = stored
            return
        view = self._secret_view()
        if view is not None and self.config.get("appSecret"):
            view.set(self._secret_key(), self.config["appSecret"])
            self.config = save_config(self.data_dir, {"appSecret": ""})

    def _app_secret(self) -> str:
        return str(
            self._stored_secret()
            or self.config.get("appSecret")
            or os.environ.get("QQBOT_SECRET")
            or ""
        ).strip()

    async def _start_gateway(self) -> None:
        app_id = self._app_id()
        app_secret = self._app_secret()
        if not app_id or not app_secret:
            return
        await self._stop_gateway()
        base_url = os.environ.get("QQBOT_BASE_URL") or DEFAULT_API_BASE_URL
        token_url = os.environ.get("QQBOT_TOKEN_BASE_URL") or DEFAULT_TOKEN_BASE_URL
        user_agent = f"lamtools-qqbot/{self._plugin_version()} (Python/{os.sys.version_info.major}.{os.sys.version_info.minor})"
        self._api = QQApi(
            app_id=app_id,
            app_secret=app_secret,
            base_url=base_url,
            token_base_url=token_url,
            user_agent=user_agent,
            logger=self.logger,
        )
        self._limiter = ReplyLimiter(limit=int(self.config.get("replyLimit") or DEFAULT_REPLY_LIMIT))
        self._outbound = OutboundRouter(
            api=self._api,
            config=self.config,
            logger=self.logger,
            find_by_agent=self._bridge.by_agent if self._bridge is not None else (lambda _name: None),
            cache=self._cache,
            limiter=self._limiter,
            data_dir=self.data_dir,
            work_root=self.work_root,
        )
        self._gateway = QQGateway(
            api=self._api,
            user_agent=user_agent,
            logger=self.logger,
            session_store=GatewaySessionStore(self.data_dir),
            on_message=self._on_message,
            on_interaction=self._on_interaction,
            on_ready=self._on_ready,
            on_resumed=self._on_resumed,
            on_disconnected=self._on_disconnected,
            on_error=self._on_gateway_error,
            on_raw=self._on_raw,
        )
        self._api.tokens.start_background_refresh()
        self._gateway_task = self._gateway.start()
        self.logger.info("QQ gateway starting appId=%s", app_id)

    async def _stop_gateway(self) -> None:
        gateway = self._gateway
        self._gateway = None
        self._gateway_task = None
        if gateway is not None:
            await gateway.stop()
        api = self._api
        self._api = None
        self._outbound = None
        if api is not None:
            await api.close()

    def _start_binding(self) -> None:
        if self._binding is not None:
            return
        self._binding = BindingService(
            client=QQBindClient(),
            logger=self.logger,
            on_state=self._on_bind_state,
            on_success=self._on_bind_success,
            on_failure=self._on_bind_failure,
        )
        self._binding.start()

    async def _stop_binding(self) -> None:
        binding = self._binding
        self._binding = None
        if binding is not None:
            await binding.dispose()

    def _on_bind_state(self, state: BindingState) -> None:
        self.logger.info("QQ binding state=%s", state.phase)

    async def _on_bind_success(self, credentials: dict[str, str]) -> None:
        self.config = self._save_credentials(
            credentials.get("appId") or "",
            credentials.get("appSecret") or "",
        )
        self._last_config_mtime = self._config_mtime()
        self.logger.info("QQ binding saved appId=%s", credentials.get("appId"))
        # The binding service is running this callback inside its own task;
        # disposing it here would await/cancel the current task.  Let the
        # callback return first, then reload in a separate task.
        asyncio.create_task(self._after_binding_saved(), name="qqbot:after-bind")

    async def _after_binding_saved(self) -> None:
        await asyncio.sleep(0)
        if not self.running:
            return
        await self._stop_binding()
        await self._start_gateway()

    async def _on_bind_failure(self, reason: str) -> None:
        self._last_error = reason
        self.logger.warning("QQ binding failed: %s", reason)

    async def _on_ready(self, data: dict[str, Any]) -> None:
        self.logger.info("QQ gateway ready")
        self._last_error = ""

    async def _on_resumed(self, data: dict[str, Any]) -> None:
        self.logger.info("QQ gateway resumed")

    async def _on_disconnected(self, code: int, reason: str, will_reconnect: bool) -> None:
        self.logger.warning("QQ gateway disconnected code=%s reason=%s reconnect=%s", code, reason, will_reconnect)

    async def _on_gateway_error(self, exc: Exception) -> None:
        self._last_error = str(exc)
        self.logger.warning("QQ gateway error: %s", exc)

    async def _on_raw(self, event_type: str, data: dict[str, Any]) -> None:
        if self.config.get("debug"):
            self.logger.debug("QQ raw event %s", event_type)

    # ── Inbound ────────────────────────────────────────────────────────────
    async def _on_message(self, message: InboundMessage) -> None:
        self.logger.info(
            "QQ inbound accepted botId=%s kind=%s messageId=%s sender=%s attachments=%d content=%r",
            self.bot_id,
            message.kind,
            message.message_id,
            message.sender_id,
            len(message.attachments or []),
            (message.content or "")[:160],
        )
        asyncio.create_task(self._process_message(message), name=f"qqbot:message:{message.message_id[:8]}")

    async def _process_message(self, message: InboundMessage) -> None:
        ctx = MiddlewareContext(message=message, bot=self)
        self._cache.cache_msg(message.scope, message.peer_id, message.message_id)
        pre = [
            message_filter(
                skip_self_echo=False,
                dedup_window_ms=5000,
                max_size=1000,
                logger=self.logger,
            ),
            access_policy(self.config.get("access") or {}, logger=self.logger),
            history_buffer(
                self._history,
                limit=int(self.config.get("historyLimit") or 10),
                group_key=self._history_group_key,
                record_on_skip=True,
                logger=self.logger,
            ),
            mention_gate(
                require_mention=bool(self.config.get("requireMention", True)),
                logger=self.logger,
            ),
            content_sanitizer(parse_face_tags=True),
            rate_limiter(logger=self.logger),
            self._command_middleware,
        ]
        post = [
            typing_indicator(api=self._api, logger=self.logger) if self._api is not None else _passthrough,
            quote_ref(self._quote_store, content_limit=200, prefer_msg_elements=True, logger=self.logger),
            attachment_processor(
                downloader=self._download_attachments,
                media_config=self.config.get("media") or {},
                logger=self.logger,
            ),
            envelope_formatter(
                history_limit=int(self.config.get("historyLimit") or 5),
                include_quote=True,
                include_sender=True,
            ),
            self._agent_middleware,
        ]
        token = set_current_runtime(self)
        try:
            await run_chain(pre, ctx)
            if ctx.stopped:
                self.logger.warning(
                    "QQ inbound stopped botId=%s reason=%s messageId=%s content=%r",
                    self.bot_id,
                    ctx.stop_reason,
                    message.message_id,
                    (message.content or "")[:160],
                )
                return
            # user:“现在怎么无论回合是否开启，都作为引导信息发出去了？”+(目标
            # 会话模式不能被合并缓冲拖到回合结束后；每条消息都要立刻进入
            # “运行中引导/空闲新回合”的判断)。
            if self._target_mode():
                await run_chain(post, ctx)
            else:
                await self._guard.run(ctx, lambda current: run_chain(post, current))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.exception("QQ message processing failed: %s", exc)
            try:
                await self._send_markdown(ctx.reply_target, "⚠️ 处理消息时出现异常，请稍后重试。")
            except Exception:
                pass
        finally:
            reset_current_runtime(token)

    def _target_mode(self) -> bool:
        return bool(str(self.config.get("targetSessionId") or "").strip())

    async def _command_middleware(self, ctx: MiddlewareContext, next_fn: Any) -> None:
        target_session = str(self.config.get("targetSessionId") or "").strip()
        if target_session:
            # In target-session mode every command must stay away from the
            # plugin's own bridge session.  Pending approvals/questions are
            # answered here; only /stop touches the target turn.
            if self._handle_target_interaction(ctx):
                ctx.stop("target-interaction")
                return
            registry = self._commands
            if registry is not None:
                parsed = registry.parse(ctx.message.content, ctx.message)
                if parsed is not None:
                    command, args, raw = parsed
                    await self._run_target_command(ctx, command, args, raw)
                    ctx.stop(f"command:{command.name}")
                    return
            await next_fn()
            return
        # Pending question answers must not be queued behind the agent turn.
        if self._handle_pending_question(ctx):
            ctx.stop("question-answer")
            return
        if self._handle_pending_approval_text(ctx):
            ctx.stop("approval-answer")
            return
        registry = self._commands
        if registry is not None:
            parsed = registry.parse(ctx.message.content, ctx.message)
            if parsed is not None:
                command, args, raw = parsed
                await self._run_command(ctx, command, args, raw)
                ctx.stop(f"command:{command.name}")
                return
        await next_fn()

    async def _agent_middleware(self, ctx: MiddlewareContext, next_fn: Any) -> None:
        del next_fn
        target_session = str(self.config.get("targetSessionId") or "").strip()
        # The target session already owns the conversation history.  Re-injecting
        # the QQ group buffer would duplicate every earlier message there.
        body = build_agent_body(
            ctx,
            history_limit=0 if target_session else int(self.config.get("historyLimit") or 10),
        )
        if not body:
            return
        message = ctx.message
        if target_session and self._target is not None:
            # Both private and group messages enter the selected Sunday session.
            # Idle -> normal user turn; running -> immediate guidance. Never a
            # queued message, which would wait for the next turn.
            text = body
            if message.scope == "group":
                sender = message.sender_name or short_sender_id(message.sender_id)
                text = f"[QQ群 {message.group_openid or message.peer_id}] {sender}: {body}"
            self._remember_target_peer(target_session, message.scope, message.peer_id)
            forward_replies = (
                self._target_event_task is not None
                and not self._target_event_task.done()
            )
            result = await self._target.send(
                session_id=target_session,
                text=text,
                client_message_id=f"qqbot:{message.message_id or message.timestamp_ms}",
                on_wait=lambda request: self._ask_target(ctx, request),
                on_reply=None if forward_replies else lambda reply: self._send_markdown(ctx.reply_target, reply),
                forward_replies=forward_replies,
            )
            if result.get("ok"):
                reply = str(result.get("reply") or "").strip()
                if reply:
                    await self._send_markdown(ctx.reply_target, reply)
            else:
                await self._send_markdown(
                    ctx.reply_target,
                    f"⚠️ 目标会话处理失败：{result.get('error') or '未知错误'}",
                )
            if message.scope == "group":
                key = self._history_group_key(ctx)
                if key:
                    self._history.clear(key)
            return
        if self._bridge is None:
            return
        session = self._bridge.get_or_create(
            scope=message.scope,
            peer_id=message.peer_id,
            sender_id=message.sender_id,
            sender_name=message.sender_name,
            reply_target=ctx.reply_target,
            sender=self._send_markdown,
        )
        try:
            # Attachments are delivered as @path text in the body; passing them
            # as attachment IDs here made the runner look up files that were
            # never registered as host attachments.
            await self._bridge.run(session, body)
        except TurnTimeout:
            await self._send_markdown(ctx.reply_target, "⚠️ 本轮处理超时，已中止。")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.exception("QQ agent turn failed: %s", exc)
            await self._send_markdown(ctx.reply_target, "⚠️ 本轮处理失败，请稍后重试。")
        finally:
            if message.scope == "group":
                key = self._history_group_key(ctx)
                if key:
                    self._history.clear(key)

    async def _download_attachments(self, attachments: list[dict[str, Any]], media_config: dict[str, Any]) -> list[dict[str, Any]]:
        return await self._media.download_attachments(attachments, media_config)

    # ── Target-session replies to QQ ───────────────────────────────────────
    def _load_target_peers(self) -> None:
        try:
            raw = json.loads(self._target_peers_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        for session_id, peers in raw.items():
            if not isinstance(peers, dict):
                continue
            for key, item in peers.items():
                if not isinstance(item, dict):
                    continue
                scope = "group" if str(item.get("scope") or "") == "group" else "c2c"
                target_id = str(item.get("targetId") or item.get("target_id") or "").strip()
                if not target_id:
                    continue
                self._target_peers.setdefault(str(session_id), {})[str(key)] = ReplyTarget(scope, target_id)

    def _save_target_peers(self) -> None:
        data = {
            session_id: {
                key: {"scope": target.scope, "targetId": target.target_id}
                for key, target in peers.items()
            }
            for session_id, peers in self._target_peers.items()
        }
        try:
            self._target_peers_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("QQ target peer persistence failed: %s", exc)

    def _start_target_event_watcher(self) -> None:
        self._stop_target_event_watcher()
        session_id = str(self.config.get("targetSessionId") or "").strip()
        bus = getattr(self.context, "event_bus", None)
        if not self.running or not session_id or bus is None:
            return
        if not callable(getattr(bus, "subscribe", None)):
            return
        self._target_event_task = asyncio.create_task(
            self._watch_target_events(session_id, bus),
            name=f"qqbot:target-events:{session_id[:8]}",
        )

    def _stop_target_event_watcher(self) -> None:
        task = self._target_event_task
        self._target_event_task = None
        if task is not None and not task.done():
            task.cancel()

    def _remember_target_peer(self, session_id: str, scope: str, peer_id: str) -> None:
        peer_id = str(peer_id or "").strip()
        if not session_id or not peer_id:
            return
        peers = self._target_peers.setdefault(session_id, {})
        peers[f"{scope}:{peer_id}"] = ReplyTarget(scope, peer_id)
        while len(peers) > 8:
            peers.pop(next(iter(peers)))
        self._save_target_peers()

    async def _watch_target_events(self, session_id: str, bus: Any) -> None:
        queue = bus.subscribe(session_id)
        try:
            while self.running and str(self.config.get("targetSessionId") or "").strip() == session_id:
                event = await queue.get()
                try:
                    await self._forward_target_event(session_id, event)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.logger.exception("QQ target event forwarding failed")
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe = getattr(bus, "unsubscribe", None)
            if callable(unsubscribe):
                try:
                    unsubscribe(session_id, queue)
                except Exception:
                    pass

    async def _forward_target_event(self, session_id: str, event: Any) -> None:
        if event is None:
            return
        if str(getattr(event, "reason", "") or "") == "subscriber_overflow":
            self.logger.warning("QQ target event stream overflow for %s", session_id)
            return
        data = getattr(event, "payload", None)
        if not isinstance(data, dict):
            return
        kind = str(data.get("kind") or "")
        body = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        turn_id = str(data.get("turn_id") or getattr(event, "turn_id", "") or "")
        if kind == "message":
            if str(body.get("type") or "") != "agentMessage":
                return
            if str(data.get("status") or "") != "completed":
                return
            content = str(body.get("content") or "").strip()
            if not content:
                return
            item_id = str(data.get("item_id") or body.get("item_id") or "")
            key = f"{turn_id}:{item_id}"
            sent_items = self._target_sent_items.setdefault(session_id, set())
            if key in sent_items:
                return
            sent_items.add(key)
            self._target_sent_texts.setdefault(session_id, set()).add(content)
            await self._send_target_text(session_id, content)
            self._prune_target_sent(session_id)
            return
        if kind != "status":
            return
        if str(body.get("status") or "") != "completed":
            return
        message = str(body.get("message") or "").strip()
        if not message:
            return
        sent_texts = self._target_sent_texts.setdefault(session_id, set())
        if message in sent_texts:
            return
        sent_texts.add(message)
        await self._send_target_text(session_id, message)
        self._prune_target_sent(session_id)

    async def _send_target_text(self, session_id: str, text: str) -> None:
        if self._api is None:
            return
        peers = list((self._target_peers.get(session_id) or {}).values())
        if not peers:
            return
        limit = int(self.config.get("textChunkLimit") or 4500)
        options = BubbleOptions.from_config(self.config)
        for peer in peers:
            for chunk in split_bubbles(text, limit, options=options):
                try:
                    await self._api.send_proactive_markdown(peer, chunk)
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning("QQ target reply send failed: %s", exc)

    def _prune_target_sent(self, session_id: str) -> None:
        items = self._target_sent_items.get(session_id)
        if items is not None and len(items) > 500:
            self._target_sent_items[session_id] = set(list(items)[-200:])
        texts = self._target_sent_texts.get(session_id)
        if texts is not None and len(texts) > 200:
            self._target_sent_texts[session_id] = set(list(texts)[-100:])

    # ── Target-session approvals and questions ─────────────────────────────
    @staticmethod
    def _target_key(scope: str, peer_id: str) -> str:
        return f"{scope}:{peer_id}"

    @staticmethod
    def _target_options(raw: Any) -> list[dict[str, str]]:
        options: list[dict[str, str]] = []
        for index, item in enumerate(raw or []):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or f"选项 {index + 1}")
            options.append(
                {
                    "label": label,
                    "description": str(item.get("description") or ""),
                    "response": str(item.get("response") or label),
                }
            )
        return options

    def _target_questions_from_request(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        arguments = request.get("arguments") if isinstance(request.get("arguments"), dict) else {}
        raw = arguments.get("questions") if isinstance(arguments, dict) else None
        base_id = str(request.get("request_id") or request.get("tool_call_id") or "question")
        questions: list[dict[str, Any]] = []
        if isinstance(raw, list) and raw:
            for index, item in enumerate(raw):
                if not isinstance(item, dict):
                    continue
                questions.append(
                    {
                        "id": str(item.get("id") or f"{base_id}:{index}"),
                        "header": str(item.get("header") or ""),
                        "question": str(item.get("question") or item.get("message") or f"问题 {index + 1}"),
                        "options": self._target_options(item.get("options")),
                        "multiSelect": bool(item.get("multiSelect")),
                    }
                )
        if questions:
            return questions
        return [
            {
                "id": base_id,
                "question": str(request.get("message") or "请选择"),
                "options": self._target_options(request.get("options")),
                "multiSelect": bool(request.get("multiSelect")),
            }
        ]

    @staticmethod
    def _target_approval_text(request: dict[str, Any]) -> str:
        tool_name = str(request.get("tool_name") or "tool")
        arguments = request.get("arguments") if isinstance(request.get("arguments"), dict) else {}
        command = str(arguments.get("command") or "")[:500] if isinstance(arguments, dict) else ""
        reason = str(request.get("reason") or request.get("message") or "").strip()
        lines = ["🔐 **执行审批**", "", f"🔧 工具: {tool_name}"]
        if command:
            lines.extend(["", "```", command, "```"])
        if reason:
            lines.extend(["", f"📝 {reason}"])
        lines.extend(["", "> 👇 点击下方按钮，或回复 允许/拒绝；也可以直接输入你的处理意见"])
        return "\n".join(lines)

    async def _ask_target(self, ctx: MiddlewareContext, request: dict[str, Any]) -> dict[str, Any] | None:
        key = self._target_key(ctx.message.scope, ctx.message.peer_id)
        is_question = str(request.get("request_kind") or "") == "question" or str(
            request.get("tool_name") or ""
        ) == "question"
        try:
            if is_question:
                questions = self._target_questions_from_request(request)
                answers: list[dict[str, Any]] = []
                for index, question in enumerate(questions):
                    keyboard = build_question_keyboard(question)
                    text = format_question(
                        question,
                        require_mention_hint=bool(self.config.get("requireMention", True)),
                        with_buttons=keyboard is not None,
                        index=index,
                        total=len(questions),
                    )
                    answer = await self._await_target_answer(
                        ctx,
                        key,
                        text,
                        keyboard,
                        question=question,
                    )
                    if answer is None:
                        return None
                    answers.append(answer)
                if len(answers) == 1:
                    guidance = answer_text(answers[0])
                else:
                    guidance = "\n".join(
                        f"问题 {index + 1}: {answer_text(answer)}"
                        for index, answer in enumerate(answers)
                    )
                return {"decision": "guide", "guidance": guidance}
            return await self._await_target_answer(
                ctx,
                key,
                self._target_approval_text(request),
                build_approval_keyboard(),
            )
        finally:
            self._target_pending.pop(key, None)
            self._target_questions.pop(key, None)

    async def _await_target_answer(
        self,
        ctx: MiddlewareContext,
        key: str,
        text: str,
        keyboard: dict[str, Any] | None,
        *,
        question: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._target_pending[key] = future
        if question is None:
            self._target_questions.pop(key, None)
        else:
            self._target_questions[key] = question
        try:
            try:
                await self._send_markdown(ctx.reply_target, text, keyboard=keyboard)
            except Exception:
                await self._send_markdown(ctx.reply_target, text)
            timeout = max(10_000, int(self.config.get("askTimeoutMs") or 5 * 60 * 1000)) / 1000.0
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        except asyncio.CancelledError:
            raise
        finally:
            if self._target_pending.get(key) is future:
                self._target_pending.pop(key, None)
            self._target_questions.pop(key, None)

    def _handle_target_interaction(self, ctx: MiddlewareContext) -> bool:
        key = self._target_key(ctx.message.scope, ctx.message.peer_id)
        future = self._target_pending.get(key)
        if future is None or future.done():
            return False
        text = str(ctx.message.content or "").strip()
        if not text:
            return False
        question = self._target_questions.get(key)
        if question is not None:
            future.set_result(
                {"decision": "guide", "guidance": answer_text(parse_answer(question, text))}
            )
            return True
        lowered = text.lower()
        allow = {"允许", "同意", "批准", "可以", "yes", "y", "allow", "ok"}
        deny = {"拒绝", "不允许", "不行", "no", "n", "deny", "cancel", "取消"}
        if lowered in allow:
            future.set_result({"decision": "approve", "guidance": ""})
        elif lowered in deny:
            future.set_result({"decision": "deny", "guidance": ""})
        else:
            future.set_result({"decision": "guide", "guidance": text})
        return True

    def _handle_target_button(self, event: dict[str, Any]) -> bool:
        raw = ((event.get("data") or {}).get("resolved") or {}).get("button_data")
        button = decode_button_data(raw)
        if not button:
            return False
        group_openid = str(event.get("group_openid") or "")
        user_openid = str(event.get("user_openid") or "")
        scope = "group" if group_openid else "c2c"
        peer_id = group_openid or user_openid
        key = self._target_key(scope, peer_id)
        future = self._target_pending.get(key)
        if future is None or future.done():
            return False
        if button.get("t") == "approval":
            decision = "approve" if button.get("d") == "allow" else "deny"
            future.set_result({"decision": decision, "guidance": ""})
            return True
        if button.get("t") == "question":
            question = self._target_questions.get(key)
            options = (question or {}).get("options") or []
            index = button.get("i")
            if not isinstance(index, int) or index < 0 or index >= len(options):
                return False
            future.set_result(
                {"decision": "guide", "guidance": str(options[index].get("label") or "")}
            )
            return True
        return False

    async def _run_target_command(
        self,
        ctx: MiddlewareContext,
        command: Any,
        args: list[str],
        raw: str,
    ) -> None:
        del args, raw
        target_session = str(self.config.get("targetSessionId") or "").strip()
        if command.name != "stop":
            await self._send_markdown(
                ctx.reply_target,
                "目标会话模式下请在 Sunday 中操作；发送 /stop 可中止目标会话当前回合。",
            )
            return
        registry = getattr(self.context, "runtime_task_registry", None)
        if registry is None:
            getter = getattr(self.context, "service", None)
            registry = getter("runtime_task_registry") if callable(getter) else None
        active = ""
        getter = getattr(registry, "active_run_id", None)
        if callable(getter):
            try:
                active = str(getter(target_session) or "")
            except Exception:
                active = ""
        if not active:
            await self._send_markdown(ctx.reply_target, "目标会话当前没有运行中的回合。")
            return
        cancel = getattr(registry, "request_cancel", None)
        if not callable(cancel):
            await self._send_markdown(ctx.reply_target, "宿主没有提供中止接口。")
            return
        try:
            cancel(target_session, run_id=active, force=True)
        except Exception as exc:
            await self._send_markdown(ctx.reply_target, f"⚠️ 中止失败：{exc}")
            return
        await self._send_markdown(ctx.reply_target, "⛔ 已请求中止目标会话当前回合。")

    def _history_group_key(self, ctx: MiddlewareContext) -> str | None:
        if ctx.message.kind != "group" or not ctx.message.group_openid:
            return None
        return f"{self._app_id()}:{ctx.message.group_openid}"

    def _handle_pending_question(self, ctx: MiddlewareContext) -> bool:
        if self._bridge is None:
            return False
        text = (ctx.message.content or "").strip()
        if not text:
            return False
        return self._questions.handle_text(ctx.message.scope, ctx.message.peer_id, text, self._bridge)

    def _handle_pending_approval_text(self, ctx: MiddlewareContext) -> bool:
        if self._bridge is None:
            return False
        text = (ctx.message.content or "").strip()
        if not text:
            return False
        return self._approvals.handle_text(ctx.message.scope, ctx.message.peer_id, text, self._bridge)

    async def _run_command(self, ctx: MiddlewareContext, command: Any, args: list[str], raw: str) -> None:
        if self._bridge is None:
            return
        message = ctx.message
        session = self._bridge.get_or_create(
            scope=message.scope,
            peer_id=message.peer_id,
            sender_id=message.sender_id,
            sender_name=message.sender_name,
            reply_target=ctx.reply_target,
            sender=self._send_markdown,
        )
        command_ctx = CommandContext(
            session=session,
            message=message,
            args=args,
            raw=raw,
            bridge=self._bridge,
            runtime=self,
        )
        try:
            result = command.handler(command_ctx)
            if hasattr(result, "__await__"):
                result = await result
            from .commands import CommandResult, _command_text

            normalized = result if isinstance(result, CommandResult) else _command_text(result)
            if normalized.text:
                await self._send_text(session, normalized.text)
        except Exception as exc:
            self.logger.exception("QQ command %s failed: %s", command.name, exc)
            await self._send_markdown(ctx.reply_target, f"⚠️ 指令执行失败: {exc}")

    async def _send_text(self, session: Any, text: str) -> None:
        limit = int(self.config.get("textChunkLimit") or 4500)
        options = BubbleOptions.from_config(self.config)
        for chunk in split_bubbles(text, limit, options=options):
            await session.send_markdown(chunk)

    async def _send_markdown(
        self,
        target: ReplyTarget,
        content: str,
        keyboard: dict[str, Any] | None = None,
    ) -> Any:
        if self._outbound is None:
            raise RuntimeError("QQ gateway is not running")
        if keyboard is not None:
            return await self._outbound.send_markdown(target, content, keyboard=keyboard)
        result = None
        limit = int(self.config.get("textChunkLimit") or 4500)
        options = BubbleOptions.from_config(self.config)
        for chunk in split_bubbles(content, limit, options=options):
            result = await self._outbound.send_markdown(target, chunk)
        return result

    async def _on_agent_event(self, event: Any) -> None:
        if self._outbound is not None:
            await self._outbound.handle_event(event)

    # ── Interactions ───────────────────────────────────────────────────────
    async def _on_interaction(self, event: dict[str, Any]) -> None:
        matched = self._handle_target_button(event)
        if not matched and self._interactions is not None:
            matched = self._interactions.handle(event)
        interaction_id = str(event.get("id") or "")
        group_openid = str(event.get("group_openid") or "")
        user_openid = str(event.get("user_openid") or "")
        scope = "group" if group_openid else "c2c"
        target_id = group_openid or user_openid
        if interaction_id and target_id:
            self._cache.cache_event(scope, target_id, interaction_id)
        if self._api is not None and interaction_id:
            try:
                await self._api.acknowledge_interaction(interaction_id, 0 if matched else 3)
            except Exception as exc:
                self.logger.debug("interaction ack failed: %s", exc)

    # ── Background tasks ───────────────────────────────────────────────────
    async def _idle_evictor(self) -> None:
        while self.running:
            await asyncio.sleep(30)
            if self._bridge is None:
                continue
            timeout = int(self.config.get("sessionIdleTimeout") or 1_800_000) / 1000.0
            now = time.time()
            for session in list(self._bridge.all_sessions()):
                if session.task is not None and not session.task.done():
                    continue
                if now - session.last_activity <= timeout:
                    continue
                self.logger.info("evicting idle QQ session key=%s", session.key)
                self._bridge.remove(session)

    async def _media_cleaner(self) -> None:
        while self.running:
            ttl = int((self.config.get("media") or {}).get("ttlHours") or 0)
            try:
                removed = await self._media.cleanup_expired(ttl)
                if removed:
                    self.logger.info("cleaned %s expired QQ media files", removed)
            except Exception as exc:
                self.logger.warning("QQ media cleanup failed: %s", exc)
            await asyncio.sleep(3600)

    async def _config_watcher(self) -> None:
        while self.running:
            await asyncio.sleep(2)
            mtime = self._config_mtime()
            if mtime == self._last_config_mtime:
                continue
            self._last_config_mtime = mtime
            old_app_id = self._app_id()
            old_secret = self._app_secret()
            try:
                new_config = load_config(self.data_dir)
            except Exception as exc:
                self.logger.warning("QQ config reload failed: %s", exc)
                continue
            self.config = new_config
            self.logger.setLevel(logging.DEBUG if new_config.get("debug") else logging.INFO)
            if self._outbound is not None:
                self._outbound.config = new_config
            if self._bridge is not None:
                self._bridge.config = new_config
                self._commands = CommandRegistry(build_commands(self._bridge, self, new_config))
            self._guard.max_queue = max(0, int(new_config.get("maxQueue") or 20))
            self._start_target_event_watcher()
            credentials_changed = old_app_id != self._app_id() or old_secret != self._app_secret()
            self.logger.info("QQ config reloaded (credentialsChanged=%s)", credentials_changed)
            if credentials_changed:
                if self._app_id() and self._app_secret():
                    await self._stop_binding()
                    await self._start_gateway()
                else:
                    await self._stop_gateway()
                    self._start_binding()

    # ── RPC surface ────────────────────────────────────────────────────────
    def status(self) -> dict[str, Any]:
        health = self.health_check()
        return {
            "ok": True,
            "running": self.running,
            "startedAt": int(self._started_at * 1000),
            "appId": self._app_id(),
            "bound": health["bound"],
            "gateway": health["gateway"],
            "binding": health["binding"],
            "sessions": self.session_list()["sessions"],
            "config": redacted(self.config),
            "lastError": self._last_error,
            "version": self._plugin_version(),
            "upstream": "dsh-qqbot 0.5.3",
        }

    def bind_state(self) -> dict[str, Any]:
        if self._app_id() and self._app_secret():
            return {"phase": "bound", "appId": self._app_id()}
        if self._binding is not None:
            return self._binding.state.wire()
        return {"phase": "starting"}

    def bind_refresh(self) -> dict[str, Any]:
        if self._binding is not None:
            self._binding.refresh()
        return {"ok": True, "phase": "starting"}

    async def bind_manual(self, app_id: str, app_secret: str) -> dict[str, Any]:
        app_id = str(app_id or "").strip()
        app_secret = str(app_secret or "").strip()
        if not app_id or not app_secret:
            return {"ok": False, "error": "appId 与 appSecret 不能为空"}
        if len(app_id) > 128 or len(app_secret) > 256:
            return {"ok": False, "error": "appId 或 appSecret 过长"}
        self.config = self._save_credentials(app_id, app_secret)
        self._last_config_mtime = self._config_mtime()
        await self._stop_binding()
        await self._start_gateway()
        return {"ok": True, "message": "凭据已保存，QQ 网关已重启"}

    async def bind_unbind(self) -> dict[str, Any]:
        if not self._app_id() and not self._app_secret():
            return {"ok": False, "error": "当前未绑定"}
        view = self._secret_view()
        if view is not None:
            try:
                view.delete(self._secret_key())
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("QQ secret delete failed: %s", exc)
        self.config = save_config(self.data_dir, {"appId": "", "appSecret": ""})
        self._last_config_mtime = self._config_mtime()
        await self._stop_gateway()
        self._start_binding()
        return {"ok": True, "message": "已解绑，插件将重新进入扫码绑定流程"}

    def config_get(self) -> dict[str, Any]:
        return {"ok": True, "config": redacted(self.config)}

    async def config_update(self, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "appId", "appSecret", "provider", "model", "preset", "cwd",
            "targetProjectId", "targetSessionId",
            "requireMention", "groupPrompt", "directPrompt", "textChunkLimit",
            "streaming", "sessionIdleTimeout", "maxQueue", "processingTimeoutMs",
            "askTimeoutMs", "historyLimit", "access", "showToolResults", "debug",
            "media", "vision", "sendFile", "agentMode", "replyLimit",
        }
        if not isinstance(patch, dict):
            return {"ok": False, "error": "patch 必须是对象"}
        unknown = [key for key in patch if key not in allowed]
        if unknown:
            return {"ok": False, "error": f"不支持的字段: {', '.join(unknown)}"}
        if "appId" in patch or "appSecret" in patch:
            return {"ok": False, "error": "凭据请使用绑定/更换/解绑操作"}
        old_app_id = self._app_id()
        old_secret = self._app_secret()
        self.config = save_config(self.data_dir, patch)
        self._last_config_mtime = self._config_mtime()
        if self._outbound is not None:
            self._outbound.config = self.config
        if self._bridge is not None:
            self._bridge.config = self.config
            self._commands = CommandRegistry(build_commands(self._bridge, self, self.config))
        self._guard.max_queue = max(0, int(self.config.get("maxQueue") or 20))
        self._start_target_event_watcher()
        if old_app_id != self._app_id() or old_secret != self._app_secret():
            await self._start_gateway()
        return {"ok": True, "message": "配置已保存", "config": redacted(self.config)}

    def session_list(self) -> dict[str, Any]:
        sessions = []
        if self._bridge is not None:
            for session in self._bridge.all_sessions():
                sessions.append(self._bridge.status(session))
        return {"ok": True, "sessions": sessions}

    async def targets(self) -> dict[str, Any]:
        """Projects and sessions available as QQ message targets."""
        builder = getattr(self.context, "operation_executor", None)
        executor = builder() if callable(builder) else None
        if executor is None:
            return {"ok": False, "error": "宿主没有提供操作目录"}
        try:
            projects_result = await executor("project.list", {})
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"读取项目失败：{exc}"}
        projects_payload = getattr(projects_result, "payload", {}) or {}
        projects = []
        for project in projects_payload.get("projects") or []:
            if not isinstance(project, dict):
                continue
            project_id = str(project.get("id") or "")
            sessions = []
            if project_id:
                try:
                    sessions_result = await executor("project.sessions.list", {"project_id": project_id})
                    sessions_payload = getattr(sessions_result, "payload", {}) or {}
                    sessions = [
                        {
                            "id": str(item.get("id") or ""),
                            "title": str(item.get("title") or item.get("id") or ""),
                            "status": str(item.get("status") or ""),
                        }
                        for item in (sessions_payload.get("sessions") or [])
                        if isinstance(item, dict)
                    ]
                except Exception:
                    sessions = []
            projects.append(
                {
                    "id": project_id,
                    "name": str(project.get("name") or project_id),
                    "workRoot": str(project.get("work_root") or project.get("workRoot") or ""),
                    "sessions": sessions,
                }
            )
        return {"ok": True, "projects": projects}

    async def session_send_file(self, scope: str, peer_id: str, file_path: str) -> dict[str, Any]:
        if self._bridge is None or self._api is None:
            return {"ok": False, "error": "QQ 网关未运行"}
        session = self._bridge.get(scope, peer_id)
        target = session.reply_target if session is not None else ReplyTarget(scope, peer_id, "")
        path = resolve_plugin_path(file_path, self.work_root)
        if not path_is_allowed(path, data_dir=self.data_dir, work_root=self.work_root, config=self.config):
            return {"ok": False, "error": f"文件不在允许范围: {path}"}
        if not path.is_file():
            return {"ok": False, "error": f"文件不存在: {path}"}
        result = await send_media_file(self._api, target, path, logger=self.logger)
        if result.get("outcome") != "sent":
            return {"ok": False, "error": str(result.get("error") or "发送失败")}
        return {"ok": True, "path": str(path), "result": result}

    def session_reset(self, scope: str, peer_id: str) -> dict[str, Any]:
        if self._bridge is None:
            return {"ok": False, "error": "运行时未启动"}
        session = self._bridge.get(scope, peer_id)
        if session is None:
            return {"ok": False, "error": "会话不存在"}
        self._bridge.new_session(session)
        return {"ok": True, "agent": session.agent_name}

    async def session_stop(self, scope: str, peer_id: str) -> dict[str, Any]:
        if self._bridge is None:
            return {"ok": False, "error": "运行时未启动"}
        session = self._bridge.get(scope, peer_id)
        if session is None:
            return {"ok": False, "error": "会话不存在"}
        stopped = await self._bridge.cancel(session)
        return {"ok": True, "stopped": stopped}

    def models_list(self) -> dict[str, Any]:
        if self._bridge is None:
            return {"ok": False, "error": "运行时未启动"}
        return {"ok": True, "models": self._bridge.list_models()}

    async def test_send(self, scope: str, target_id: str, text: str, dry_run: bool = False) -> dict[str, Any]:
        if self._api is None:
            return {"ok": False, "error": "QQ 网关未运行"}
        scope = "group" if scope == "group" else "c2c"
        target_id = str(target_id or "").strip()
        text = str(text or "").strip()
        if not target_id or not text:
            return {"ok": False, "error": "target 和 text 不能为空"}
        limit = int(self.config.get("textChunkLimit") or 4500)
        options = BubbleOptions.from_config(self.config)
        chunks = split_bubbles(text, limit, options=options)
        if dry_run:
            return {"ok": True, "dryRun": True, "chunks": chunks}
        results: list[dict[str, Any]] = []
        try:
            for chunk in chunks:
                results.append(
                    await self._api.send_proactive_markdown(
                        ReplyTarget(scope, target_id),
                        chunk,
                    )
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "result": results[-1] if results else {}, "results": results}

    async def gateway_restart(self) -> dict[str, Any]:
        if not self._app_id() or not self._app_secret():
            return {"ok": False, "error": "尚未绑定凭据"}
        await self._stop_gateway()
        await self._start_gateway()
        return {"ok": True, "message": "QQ 网关已重启"}

    def logs_tail(self, tail: int = 80) -> dict[str, Any]:
        path = self.data_dir / "logs" / "qqbot.log"
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        return {"ok": True, "path": str(path), "lines": lines[-max(1, int(tail or 80)):]}

    def diagnose(self) -> dict[str, Any]:
        return {
            "ok": True,
            "status": self.status(),
            "logs": self.logs_tail(120),
        }

    @staticmethod
    def _plugin_version() -> str:
        try:
            manifest = json.loads((Path(__file__).resolve().parent.parent / "plugin.json").read_text(encoding="utf-8"))
            return str(manifest.get("version") or "0.1.0")
        except Exception:
            return "0.1.0"


async def _passthrough(ctx: MiddlewareContext, next_fn: Any) -> None:
    await next_fn()


__all__ = ["QQBotRuntime", "MergeGuard", "merge_contexts"]
