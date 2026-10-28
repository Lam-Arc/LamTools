"""Bridge between QQ peers and the host's persistent sub-agent runner.

LamTools exposes ``sub_agent_runner_factory`` to plugins.  One runner instance
keeps per-agent-name state in the host's runtime state store, so a stable
``agent_name`` per QQ peer gives us persistent conversation history across
messages and restarts without a second database.

Approvals and questions arrive as ``pending_approval`` on the run result.  The
bridge parks them on the QQ channels and resumes the same child session with
``resume_approved`` / ``resume_question``.  A denied approval is delivered to
the model as a tool result (via ``resume_question``) so the turn can continue
instead of leaving an orphaned pending state; this is recorded as a porting
change in the difference table.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable

from .channels import ApprovalChannel, QuestionChannel, answer_text
from .config import build_late_context, find_preset
from .protocol import ReplyTarget
from .store import PrefsStore

_current_session: contextvars.ContextVar["PeerSession | None"] = contextvars.ContextVar(
    "qqbot_current_session", default=None
)


def current_session() -> "PeerSession | None":
    return _current_session.get()


def session_title(scope: str, peer_id: str, sender_name: str = "") -> str:
    """Stable display title used by the QQ page and session lists."""
    name = str(sender_name or "").strip()
    if not name:
        name = str(peer_id or "").strip()[-6:] or "未知"
    if len(name) > 32:
        name = name[:31] + "…"
    prefix = "QQ-群聊" if scope == "group" else "QQ-私聊"
    return f"{prefix}-{name}"


@dataclass
class PeerSession:
    key: str
    scope: str
    peer_id: str
    sender_id: str
    agent_name: str
    reply_target: ReplyTarget
    title: str = ""
    generation: int = 0
    model_provider: str = ""
    model: str = ""
    preset: str = ""
    session_id: str = ""
    last_activity: float = field(default_factory=time.time)
    message_count: int = 0
    usage: dict[str, int] = field(default_factory=lambda: {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0})
    transcript: list[dict[str, str]] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task | None = None
    last_result: Any = None
    last_error: str = ""
    sender: Callable[..., Awaitable[Any]] | None = None

    async def send_markdown(self, content: str, keyboard: dict[str, Any] | None = None) -> Any:
        if self.sender is None:
            raise RuntimeError("QQ session has no sender")
        return await self.sender(self.reply_target, content, keyboard)


class TurnTimeout(RuntimeError):
    pass


class AgentBridge:
    def __init__(
        self,
        *,
        context: Any,
        config: dict[str, Any],
        data_dir: Path,
        work_root: str | Path,
        logger: logging.Logger,
        approvals: ApprovalChannel,
        questions: QuestionChannel,
        on_event: Callable[[Any], Awaitable[None]],
    ) -> None:
        self.context = context
        self.config = config
        self.data_dir = Path(data_dir)
        self.work_root = Path(work_root)
        self.logger = logger
        self.approvals = approvals
        self.questions = questions
        self.on_event = on_event
        self.prefs = PrefsStore(self.data_dir)
        self.runner = self._create_runner()
        self._sessions: dict[str, PeerSession] = {}
        self._by_agent: dict[str, PeerSession] = {}
        # user:“agent preset（智能体预设）system-prompt waterfall（系统提示词
        # 流水线）都是宿主缺失，去补”+(插件直接消费宿主服务；旧宿主才回退
        # 到插件自己的 presets.jsonc / late_context)。服务可能晚于后端启动
        # 才注册（操作目录先启动后端），因此每次使用前再确认一次。
        self.agent_presets: Any | None = None
        self.prompt_waterfall: Any | None = None
        self._prompt_unregister: Callable[[], None] | None = None
        self._ensure_host_services()

    def _ensure_host_services(self) -> None:
        service = getattr(self.context, "service", None)
        if not callable(service):
            return
        if self.agent_presets is None:
            self.agent_presets = service("agent_presets")
        waterfall = service("system_prompt_waterfall")
        if waterfall is not None and waterfall is not self.prompt_waterfall:
            if self._prompt_unregister is not None:
                self._prompt_unregister()
            self.prompt_waterfall = waterfall
            self._prompt_unregister = waterfall.register(
                self._prompt_handler,
                plugin="qq-bot",
                order=100,
            )

    def _prompt_handler(self, context: Any, assembly: Any) -> Any:
        """Append the QQ scope prompt to the leading system prompt.

        The handler runs for every assembled prompt in this host process; it
        only touches agents that belong to a QQ peer.  This is the host
        waterfall equivalent of the upstream DSH ``system-prompt/assemble``
        listener.
        """
        agent_name = str(getattr(context, "agent_name", "") or "")
        session = self._by_agent.get(agent_name)
        if session is None:
            return assembly
        from .config import scope_prompt

        extra = scope_prompt(self.config, session.scope)
        if extra:
            assembly.append_section("qqbot:scope-prompt", extra, order=90)
        return assembly

    def _create_runner(self) -> Any:
        factory = self.context.service("sub_agent_runner_factory") if hasattr(self.context, "service") else None
        if callable(factory):
            cwd = str(self.config.get("cwd") or "").strip()
            try:
                runner = factory(work_root=cwd) if cwd else factory()
            except TypeError:
                # Older host factories do not accept a work_root override.
                runner = factory()
        else:
            runner = self.context.service("sub_agent_runner") if hasattr(self.context, "service") else None
        if runner is None:
            raise RuntimeError(
                "宿主未提供 sub_agent_runner_factory；QQ 机器人需要宿主子代理运行器"
            )
        # Route child events to the QQ outbound router.
        try:
            runner.parent_event_sink = self._event_sink
        except Exception:
            pass
        return runner

    async def _event_sink(self, event: Any) -> None:
        try:
            await self.on_event(event)
        except Exception:
            self.logger.exception("QQ outbound event handling failed")

    # ── Session registry ───────────────────────────────────────────────────
    def get(self, scope: str, peer_id: str) -> PeerSession | None:
        from .config import session_key

        return self._sessions.get(session_key(str(self.config.get("appId") or ""), scope, peer_id))

    def by_agent(self, agent_name: str) -> PeerSession | None:
        return self._by_agent.get(agent_name)

    def all_sessions(self) -> list[PeerSession]:
        return list(self._sessions.values())

    def get_or_create(
        self,
        *,
        scope: str,
        peer_id: str,
        sender_id: str,
        reply_target: ReplyTarget,
        sender: Callable[..., Awaitable[Any]],
        sender_name: str = "",
    ) -> PeerSession:
        from .config import agent_name, session_key

        app_id = str(self.config.get("appId") or "")
        key = session_key(app_id, scope, peer_id)
        existing = self._sessions.get(key)
        if existing is not None:
            existing.reply_target = reply_target
            existing.sender_id = sender_id or existing.sender_id
            existing.title = session_title(scope, peer_id, sender_name) or existing.title
            existing.last_activity = time.time()
            existing.sender = sender
            return existing

        generation = self.prefs.get_generation(key)
        agent = agent_name(key, generation)
        override = self.prefs.get_override(key)
        preset = self.prefs.get_preset(key) or str(self.config.get("preset") or "")
        session = PeerSession(
            key=key,
            scope=scope,
            peer_id=peer_id,
            sender_id=sender_id,
            agent_name=agent,
            reply_target=reply_target,
            title=session_title(scope, peer_id, sender_name),
            generation=generation,
            model_provider=(override or {}).get("provider", ""),
            model=(override or {}).get("model", ""),
            preset=preset,
            sender=sender,
        )
        self._sessions[key] = session
        self._by_agent[agent] = session
        self.logger.info("QQ session created key=%s agent=%s", key, agent)
        return session

    def remove(self, session: PeerSession) -> None:
        self._sessions.pop(session.key, None)
        self._by_agent.pop(session.agent_name, None)
        self.approvals.cancel_pending(session.key)
        self.questions.cancel_pending(session.key)

    # ── Model / preset ─────────────────────────────────────────────────────
    def list_models(self) -> list[dict[str, str]]:
        catalog = self.context.service("model_catalog") if hasattr(self.context, "service") else None
        if catalog is not None and hasattr(catalog, "list"):
            try:
                return [
                    {
                        "provider": model.provider,
                        "id": model.id,
                        "name": model.display_name or model.id,
                        "model_id": model.id,
                        "capability": model.capability,
                    }
                    for model in catalog.list()
                ]
            except Exception as exc:
                self.logger.debug("host model catalog failed: %s", exc)
        models: list[dict[str, str]] = []
        try:
            from lamtools_core.config.model_store import ModelStore

            for record in ModelStore().list_sync(work_root=str(self.work_root)):
                model_id = str(getattr(record, "model_id", "") or "").strip()
                if not model_id:
                    continue
                models.append(
                    {
                        "provider": str(getattr(record, "provider", "") or getattr(record, "provider_id", "") or ""),
                        "id": model_id,
                        "name": str(getattr(record, "display_name", "") or model_id),
                        "model_id": model_id,
                    }
                )
        except Exception as exc:
            self.logger.debug("host model catalog unavailable: %s", exc)
        configured = str(self.config.get("model") or "").strip()
        if configured and not any(item["model_id"] == configured for item in models):
            models.append(
                {
                    "provider": str(self.config.get("provider") or ""),
                    "id": configured,
                    "name": configured,
                    "model_id": configured,
                }
            )
        # Deduplicate by model id while keeping the first display name.
        seen: set[str] = set()
        unique: list[dict[str, str]] = []
        for item in models:
            if item["model_id"] in seen:
                continue
            seen.add(item["model_id"])
            unique.append(item)
        return unique

    def resolve_model_ref(self, ref: str) -> tuple[str, str]:
        ref = str(ref or "").strip()
        if not ref:
            return "", ""
        provider = ""
        model = ref
        if "/" in ref:
            provider, model = ref.split("/", 1)
        if not provider:
            provider = str(self.config.get("provider") or "")
        catalog = self.context.service("model_catalog") if hasattr(self.context, "service") else None
        if catalog is not None and hasattr(catalog, "resolve"):
            try:
                info = catalog.resolve(model)
                if info is not None:
                    model = info.id
                    provider = provider or info.provider
            except Exception:
                pass
        # Canonicalize display names through the host store when possible.
        try:
            from lamtools_core.config.model_store import ModelStore

            record = ModelStore().get_sync(model, work_root=str(self.work_root))
            if record is not None:
                model = str(getattr(record, "model_id", model) or model)
                provider = provider or str(getattr(record, "provider", "") or "")
        except Exception:
            pass
        return provider, model

    def set_model(self, session: PeerSession, ref: str) -> dict[str, str]:
        provider, model = self.resolve_model_ref(ref)
        if not model:
            raise ValueError("用法: /model provider/model")
        session.model_provider = provider
        session.model = model
        self.prefs.set_override(session.key, provider, model)
        return {"provider": provider, "model": model}

    def clear_model(self, session: PeerSession) -> None:
        session.model_provider = ""
        session.model = ""
        self.prefs.clear_override(session.key)

    def list_presets(self) -> list[dict[str, Any]]:
        self._ensure_host_services()
        if self.agent_presets is not None:
            try:
                return [
                    {
                        "id": preset.id,
                        "title": preset.title or preset.id,
                        "description": preset.description,
                        "mode": preset.mode,
                        "tools": list(preset.tools),
                    }
                    for preset in self.agent_presets.list()
                ]
            except Exception:
                pass
        from .config import load_presets

        return load_presets(self.data_dir)

    def set_preset(self, session: PeerSession, preset_id: str) -> dict[str, Any]:
        self._ensure_host_services()
        preset_id = str(preset_id or "").strip()
        if self.agent_presets is not None:
            if not self.agent_presets.has(preset_id):
                return {"ok": False, "reason": "unknown-preset", "message": f"未知 preset: {preset_id}"}
        else:
            preset = find_preset(self.data_dir, preset_id)
            if preset is None:
                return {"ok": False, "reason": "unknown-preset", "message": f"未知 preset: {preset_id}"}
        session.preset = preset_id
        self.prefs.set_preset(session.key, preset_id)
        return {"ok": True, "preset": preset_id}

    def clear_preset(self, session: PeerSession) -> dict[str, Any]:
        self._ensure_host_services()
        session.preset = str(self.config.get("preset") or "")
        self.prefs.set_preset(session.key, "")
        return {"ok": True}

    def new_session(self, session: PeerSession) -> None:
        from .config import agent_name

        generation = self.prefs.bump_generation(session.key)
        old_agent = session.agent_name
        session.generation = generation
        session.agent_name = agent_name(session.key, generation)
        session.session_id = ""
        session.last_result = None
        session.last_error = ""
        session.message_count = 0
        session.transcript.clear()
        self._by_agent.pop(old_agent, None)
        self._by_agent[session.agent_name] = session
        self.approvals.cancel_pending(session.key)
        self.questions.cancel_pending(session.key)
        self.logger.info("QQ session reset key=%s agent=%s", session.key, session.agent_name)

    async def fork_session(self, session: PeerSession) -> dict[str, Any]:
        """Branch the current conversation and make the branch live.

        user:“child-session manual compact/fork/history/usage”+(子会话分叉由
        宿主 runner 负责，QQ 侧只把当前 peer 切到分叉后的会话)。
        """
        if not session.session_id:
            raise RuntimeError("当前没有可分支的会话")
        fork = getattr(self.runner, "fork", None)
        if not callable(fork):
            raise RuntimeError("宿主未提供子会话分叉接口。")
        fork_name = f"{session.agent_name}_fork_{int(time.time() * 1000)}"
        result = await fork(session.session_id, fork_name)
        self._by_agent.pop(session.agent_name, None)
        session.agent_name = str(result.get("agent") or fork_name)
        session.session_id = str(result.get("session_id") or "")
        self._by_agent[session.agent_name] = session
        self.prefs.set_session_id(session.key, session.session_id)
        return result

    async def session_info(self, session: PeerSession) -> dict[str, Any]:
        if not session.session_id:
            raise RuntimeError("当前无活跃会话")
        info = getattr(self.runner, "session_info", None)
        if not callable(info):
            raise RuntimeError("宿主未提供子会话历史接口。")
        return await info(session.session_id)

    # ── Turn driver ────────────────────────────────────────────────────────
    async def run(self, session: PeerSession, text: str, *, image_paths: list[str] | None = None) -> Any:
        self._ensure_host_services()
        async with session.lock:
            session.task = asyncio.current_task()
            token = _current_session.set(session)
            try:
                return await self._run_loop(session, text, image_paths or [])
            finally:
                _current_session.reset(token)
                if session.task is asyncio.current_task():
                    session.task = None

    async def _run_loop(self, session: PeerSession, text: str, image_paths: list[str]) -> Any:
        host_preset = session.preset if (self.agent_presets is not None and session.preset) else ""
        preset = None if host_preset else find_preset(self.data_dir, session.preset)
        mode = "" if host_preset else ((preset or {}).get("mode") or str(self.config.get("agentMode") or ""))
        allowed_tools = None if host_preset else ((preset or {}).get("tools") or None)
        late_context = build_late_context(
            self.config,
            session.scope,
            include_scope_prompt=self.prompt_waterfall is None,
        )
        if preset and preset.get("prompt"):
            late_context = f"{late_context}\n\n{preset['prompt']}"

        model = session.model or str(self.config.get("model") or "")
        run_kwargs: dict[str, Any] = {
            "task": text,
            "agent": session.agent_name,
            "model": model,
            "mode": mode,
            "late_context": late_context,
            "attachments": image_paths or None,
            "allowed_tools": allowed_tools,
            "parent_call_id": session.agent_name,
        }
        if self.agent_presets is not None:
            run_kwargs["preset"] = host_preset
        result = await self._call(self.runner.run, **run_kwargs)
        session.transcript.append({"role": "user", "text": text})
        session.last_result = result
        session.last_activity = time.time()
        if getattr(result, "session_id", ""):
            session.session_id = str(result.session_id)
            self.prefs.set_session_id(session.key, session.session_id)

        while True:
            pending = dict(getattr(result, "pending_approval", {}) or {})
            if not pending:
                break
            request_payload = pending.get("request_payload") or {}
            request_kind = str(
                pending.get("request_kind")
                or request_payload.get("request_kind")
                or ("question" if (pending.get("tool_call") or {}).get("name") == "question" else "permission")
            )
            tool_call = pending.get("tool_call") or {}
            if not tool_call:
                # A no-progress pause has no tool call to answer; leave it to
                # the next user message rather than inventing a decision.
                break
            if request_kind == "question":
                answer = await self.questions.ask(
                    session,
                    pending,
                    timeout_ms=int(self.config.get("askTimeoutMs") or 300_000),
                    require_mention=bool(self.config.get("requireMention", True)),
                )
                if answer is None:
                    session.last_error = "question timeout/cancelled"
                    # Clear the host's pending record so the next message is not
                    # blocked by an unanswered question.
                    try:
                        result = await self._call(
                            self.runner.resume_question,
                            session_id=str(result.session_id),
                            pending_call=tool_call,
                            task=text,
                            agent=session.agent_name,
                            parent_call_id=session.agent_name,
                            answer="（用户没有回答这个问题，请按合理默认继续或结束。）",
                            question=self._question_text(pending, request_payload, tool_call),
                            skipped=True,
                            model=model,
                            mode=mode,
                        )
                        session.last_result = result
                    except Exception as exc:
                        self.logger.warning("clearing timed-out question failed: %s", exc)
                    break
                question_text = self._question_text(pending, request_payload, tool_call)
                result = await self._call(
                    self.runner.resume_question,
                    session_id=str(result.session_id),
                    pending_call=tool_call,
                    task=text,
                    agent=session.agent_name,
                    parent_call_id=session.agent_name,
                    answer=answer_text(answer),
                    question=question_text,
                    model=model,
                    mode=mode,
                )
            else:
                decision = await self.approvals.ask(
                    session,
                    pending,
                    timeout_ms=int(self.config.get("askTimeoutMs") or 300_000),
                )
                if decision == "allow":
                    result = await self._call(
                        self.runner.resume_approved,
                        session_id=str(result.session_id),
                        pending_call=tool_call,
                        task=text,
                        agent=session.agent_name,
                        parent_call_id=session.agent_name,
                        model=model,
                        mode=mode,
                    )
                elif decision == "deny":
                    # Denial is a tool result, not an approval: this clears the
                    # pending record and lets the model adapt in the same turn.
                    result = await self._call(
                        self.runner.resume_question,
                        session_id=str(result.session_id),
                        pending_call=tool_call,
                        task=text,
                        agent=session.agent_name,
                        parent_call_id=session.agent_name,
                        answer="用户拒绝了这次工具调用。不要执行它；根据已有信息继续，或向用户说明。",
                        question=str(tool_call.get("name") or ""),
                        model=model,
                        mode=mode,
                    )
                else:
                    session.last_error = f"approval {decision}"
                    # Clear the pending approval as a denied tool result so a
                    # later message can start cleanly.
                    try:
                        result = await self._call(
                            self.runner.resume_question,
                            session_id=str(result.session_id),
                            pending_call=tool_call,
                            task=text,
                            agent=session.agent_name,
                            parent_call_id=session.agent_name,
                            answer="审批等待超时或已取消；不要执行这次工具调用。",
                            question=str(tool_call.get("name") or ""),
                            skipped=True,
                            model=model,
                            mode=mode,
                        )
                        session.last_result = result
                    except Exception as exc:
                        self.logger.warning("clearing timed-out approval failed: %s", exc)
                    break
            session.last_result = result
            session.last_activity = time.time()
            if getattr(result, "session_id", ""):
                session.session_id = str(result.session_id)
                self.prefs.set_session_id(session.key, session.session_id)

        reply = str(getattr(result, "message", "") or "").strip()
        if reply:
            session.transcript.append({"role": "assistant", "text": reply})
        session.message_count += 2
        return result

    @staticmethod
    def _question_text(pending: dict[str, Any], request_payload: dict[str, Any], tool_call: dict[str, Any]) -> str:
        arguments = tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else {}
        raw = arguments.get("questions") or request_payload.get("questions") or []
        if isinstance(raw, list) and raw:
            lines = [
                str(item.get("question") or item.get("message") or "")
                for item in raw
                if isinstance(item, dict)
            ]
            return "\n".join(line for line in lines if line)
        return str(
            request_payload.get("message")
            or pending.get("message")
            or arguments.get("question")
            or ""
        )

    async def _call(self, function: Callable[..., Awaitable[Any]], **kwargs: Any) -> Any:
        timeout = max(10_000, int(self.config.get("processingTimeoutMs") or 1_800_000)) / 1000.0
        try:
            return await asyncio.wait_for(function(**kwargs), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise TurnTimeout("本轮处理超时") from exc

    async def cancel(self, session: PeerSession) -> bool:
        task = session.task
        if task is None or task.done():
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        session.last_error = "cancelled"
        # Best effort: settle a child left in the resumable "waiting" state so
        # the next message is not blocked by a stale pending approval.
        if session.session_id:
            async def settle() -> None:
                try:
                    await self.runner.resume_interrupted(
                        session_id=session.session_id,
                        agent=session.agent_name,
                        model=session.model or str(self.config.get("model") or ""),
                        prompt="用户中止了上一轮。不要重复已完成的工作；根据已有信息简短说明并结束。",
                    )
                except Exception as exc:
                    self.logger.debug("settle after cancel failed: %s", exc)

            asyncio.create_task(settle(), name="qqbot:settle-cancel")
        return True

    def status(self, session: PeerSession) -> dict[str, Any]:
        return {
            "active": True,
            "key": session.key,
            "title": session.title or session_title(session.scope, session.peer_id),
            "scope": session.scope,
            "peerId": session.peer_id,
            "agent": session.agent_name,
            "sessionId": session.session_id,
            "provider": session.model_provider,
            "model": session.model or str(self.config.get("model") or ""),
            "preset": session.preset or None,
            "messageCount": session.message_count,
            "lastActivity": int(session.last_activity * 1000),
            "running": session.task is not None and not session.task.done(),
            "usage": dict(session.usage),
            "lastError": session.last_error,
        }

    def record_usage(self, agent_name: str, usage: dict[str, Any]) -> None:
        session = self._by_agent.get(agent_name)
        if session is None:
            return
        session.usage["input"] += int(usage.get("prompt_tokens") or usage.get("input") or 0)
        session.usage["output"] += int(usage.get("completion_tokens") or usage.get("output") or 0)
        session.usage["cacheRead"] += int(usage.get("cached_tokens") or usage.get("cacheRead") or 0)
        session.usage["cacheWrite"] += int(usage.get("cache_creation_tokens") or usage.get("cacheWrite") or 0)

    def export_markdown(self, session: PeerSession) -> str:
        lines = [f"# QQ 会话导出\n", f"> session: {session.session_id or session.agent_name}\n"]
        for item in session.transcript:
            title = "用户" if item.get("role") == "user" else "助手"
            lines.append(f"## {title}\n\n{item.get('text') or ''}\n")
        return "\n".join(lines)

    async def dispose_all(self) -> None:
        if self._prompt_unregister is not None:
            self._prompt_unregister()
            self._prompt_unregister = None
        self.approvals.cancel_all()
        self.questions.cancel_all()
        tasks = [session.task for session in self._sessions.values() if session.task is not None and not session.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._sessions.clear()
        self._by_agent.clear()


__all__ = ["PeerSession", "AgentBridge", "TurnTimeout", "current_session"]
