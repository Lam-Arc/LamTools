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
from .channels import ApprovalChannel, InteractionRouter, QuestionChannel
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
from .util import chunk_markdown_text, format_relative_time, short_sender_id


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
    def __init__(self, context: Any) -> None:
        self.context = context
        self.data_dir = Path(getattr(context, "data_dir", None) or Path(__file__).resolve().parent.parent / "data")
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
        self._interactions: InteractionRouter | None = None
        self._guard = MergeGuard(int(self.config.get("maxQueue") or 20))
        self._last_config_mtime = self._config_mtime()
        self._started_at = time.time()
        self._last_error = ""

    # ── Logging ────────────────────────────────────────────────────────────
    def _make_logger(self) -> logging.Logger:
        logger = logging.getLogger("qqbot")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.FileHandler(self.data_dir / "logs" / "qqbot.log", encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
            console = logging.StreamHandler()
            console.setFormatter(logging.Formatter("[qq-bot] %(levelname)s %(message)s"))
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
            if getattr(context, "data_dir", None):
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
        app_id = self._app_id()
        app_secret = self._app_secret()
        if app_id and app_secret:
            await self._start_gateway()
        else:
            self._start_binding()
        self.logger.info("QQ bot runtime started (bound=%s)", bool(app_id and app_secret))

    async def stop(self) -> None:
        self.running = False
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

    def _stored_secret(self) -> str:
        view = self._secret_view()
        if view is None:
            return ""
        try:
            return str(view.get("appSecret") or "").strip()
        except Exception as exc:  # noqa: BLE001 - a corrupt secret must be visible
            self.logger.warning("QQ secret store read failed: %s", exc)
            return ""

    def _save_credentials(self, app_id: str, app_secret: str) -> dict[str, Any]:
        view = self._secret_view()
        if view is not None and app_secret:
            view.set("appSecret", app_secret)
            return save_config(self.data_dir, {"appId": app_id, "appSecret": ""})
        return save_config(self.data_dir, {"appId": app_id, "appSecret": app_secret})

    def _migrate_secret(self) -> None:
        stored = self._stored_secret()
        if stored:
            self.config["appSecret"] = stored
            return
        view = self._secret_view()
        if view is not None and self.config.get("appSecret"):
            view.set("appSecret", self.config["appSecret"])
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
            rate_limiter(),
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
        try:
            await run_chain(pre, ctx)
            if ctx.stopped:
                return
            await self._guard.run(ctx, lambda current: run_chain(post, current))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.exception("QQ message processing failed: %s", exc)
            try:
                await self._send_markdown(ctx.reply_target, "⚠️ 处理消息时出现异常，请稍后重试。")
            except Exception:
                pass

    async def _command_middleware(self, ctx: MiddlewareContext, next_fn: Any) -> None:
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
        if self._bridge is None:
            return
        body = build_agent_body(ctx, history_limit=int(self.config.get("historyLimit") or 10))
        if not body:
            return
        message = ctx.message
        session = self._bridge.get_or_create(
            scope=message.scope,
            peer_id=message.peer_id,
            sender_id=message.sender_id,
            reply_target=ctx.reply_target,
            sender=self._send_markdown,
        )
        image_paths = [
            str(item.get("localPath"))
            for item in (ctx.state.get("downloadedFiles") or [])
            if item.get("localPath") and item.get("contentType") == "image"
        ]
        try:
            await self._bridge.run(session, body, image_paths=image_paths)
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
        for chunk in chunk_markdown_text(text, int(self.config.get("textChunkLimit") or 4500)):
            await session.send_markdown(chunk)

    async def _send_markdown(
        self,
        target: ReplyTarget,
        content: str,
        keyboard: dict[str, Any] | None = None,
    ) -> Any:
        if self._outbound is None:
            raise RuntimeError("QQ gateway is not running")
        return await self._outbound.send_markdown(target, content, keyboard=keyboard)

    async def _on_agent_event(self, event: Any) -> None:
        if self._outbound is not None:
            await self._outbound.handle_event(event)

    # ── Interactions ───────────────────────────────────────────────────────
    async def _on_interaction(self, event: dict[str, Any]) -> None:
        matched = False
        if self._interactions is not None:
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
                view.delete("appSecret")
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
        if old_app_id != self._app_id() or old_secret != self._app_secret():
            await self._start_gateway()
        return {"ok": True, "message": "配置已保存", "config": redacted(self.config)}

    def session_list(self) -> dict[str, Any]:
        sessions = []
        if self._bridge is not None:
            for session in self._bridge.all_sessions():
                sessions.append(self._bridge.status(session))
        return {"ok": True, "sessions": sessions}

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

    async def test_send(self, scope: str, target_id: str, text: str) -> dict[str, Any]:
        if self._api is None:
            return {"ok": False, "error": "QQ 网关未运行"}
        scope = "group" if scope == "group" else "c2c"
        target_id = str(target_id or "").strip()
        text = str(text or "").strip()
        if not target_id or not text:
            return {"ok": False, "error": "target 和 text 不能为空"}
        try:
            result = await self._api.send_proactive_markdown(ReplyTarget(scope, target_id), text)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "result": result}

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
