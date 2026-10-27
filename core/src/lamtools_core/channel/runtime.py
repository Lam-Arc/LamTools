"""Host-owned chat-channel runtime.

The runtime is the reusable half of an IM bridge:

* one peer (private chat / group) maps to one stable child-agent session;
* an inbound message is prepared by the plugin's policy, routed through chat
  commands, serialized with a per-peer merge queue, and run as a child turn;
* pending approvals/questions are handed to the adapter, then the same child
  session is resumed;
* host runtime events (streaming text, tool results, usage, turn end,
  deliverables) are routed back through the adapter;
* session status, usage, transcript, reset, stop, compact, fork and model/preset
  overrides are exposed as methods.

A channel plugin supplies the adapter (network protocol, send, approval UI) and
keeps only its own middleware/policy.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from .commands import ChannelCommand, ChannelCommandContext, CommandRegistry
from .outbound import chunk_text
from .types import ChannelAdapter, ChannelMessage, ChannelPolicy, ChannelSession, ChannelTarget

_current_session: contextvars.ContextVar[ChannelSession | None] = contextvars.ContextVar(
    "channel_current_session", default=None
)


def current_channel_session() -> ChannelSession | None:
    return _current_session.get()


@dataclass
class _Buffer:
    text: str = ""
    stream: Any | None = None
    stream_failed: bool = False
    final_sent: bool = False


SILENT_TURN_ERROR_CODES = {"STREAM_CLOSED"}
RESULT_PREVIEW_LIMIT = 1500


class ChannelRuntime:
    def __init__(
        self,
        *,
        adapter: ChannelAdapter,
        context: Any,
        config: dict[str, Any] | None = None,
        data_dir: str | Path,
        work_root: str | Path,
        logger: logging.Logger | None = None,
        policy: ChannelPolicy | None = None,
        commands: list[ChannelCommand] | None = None,
        runner: Any | None = None,
        runner_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.adapter = adapter
        self.context = context
        self.config = dict(config or {})
        self.data_dir = Path(data_dir)
        self.work_root = Path(work_root)
        self.logger = logger or logging.getLogger("channel")
        self.policy = policy or ChannelPolicy()
        self.commands = CommandRegistry(commands or [])
        self.runner = runner or self._create_runner(runner_factory)
        self.presets = self._service("agent_presets")
        self.model_catalog = self._service("model_catalog")
        self._sessions: dict[str, ChannelSession] = {}
        self._by_agent: dict[str, ChannelSession] = {}
        self._buffers: dict[str, _Buffer] = {}
        self._tool_calls: dict[tuple[str, str], dict[str, Any]] = {}
        self._artifacts: dict[str, list[str]] = {}
        self._seen: dict[str, float] = {}
        self._merge: dict[str, dict[str, Any]] = {}
        self._generation = 0
        self._closed = False
        try:
            self.runner.parent_event_sink = self._on_event
        except Exception:
            pass

    # ── Services ───────────────────────────────────────────────────────────
    def _service(self, name: str) -> Any | None:
        getter = getattr(self.context, "service", None)
        return getter(name) if callable(getter) else None

    def _create_runner(self, factory: Callable[..., Any] | None) -> Any:
        factory = factory or self._service("sub_agent_runner_factory")
        if not callable(factory):
            raise RuntimeError("host did not provide sub_agent_runner_factory")
        cwd = str(self.config.get("cwd") or "").strip()
        try:
            return factory(work_root=cwd) if cwd else factory()
        except TypeError:
            return factory()

    # ── Commands ───────────────────────────────────────────────────────────
    def register_command(self, command: ChannelCommand) -> None:
        self.commands.register(command)

    # ── Sessions ───────────────────────────────────────────────────────────
    def session_key(self, message: ChannelMessage) -> str:
        account = str(self.config.get("accountId") or self.config.get("appId") or "default")
        return f"{self.adapter.name}:{account}:{message.scope}:{message.peer_id}"

    def _agent_name(self, key: str, generation: int) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        name = f"ch_{digest}"
        return f"{name}_g{generation}" if generation else name

    def get(self, scope: str, peer_id: str) -> ChannelSession | None:
        account = str(self.config.get("accountId") or self.config.get("appId") or "default")
        return self._sessions.get(f"{self.adapter.name}:{account}:{scope}:{peer_id}")

    def by_agent(self, agent_name: str) -> ChannelSession | None:
        return self._by_agent.get(agent_name)

    def all_sessions(self) -> list[ChannelSession]:
        return list(self._sessions.values())

    def get_or_create(self, message: ChannelMessage) -> ChannelSession:
        key = self.session_key(message)
        existing = self._sessions.get(key)
        if existing is not None:
            existing.target = message.reply_target
            existing.sender_id = message.sender_id or existing.sender_id
            existing.last_activity = time.time()
            return existing
        generation = self._generation
        agent = self._agent_name(key, generation)
        session = ChannelSession(
            key=key,
            scope=message.scope,
            peer_id=message.peer_id,
            sender_id=message.sender_id,
            agent_name=agent,
            target=message.reply_target,
            model=str(self.config.get("model") or ""),
            preset=str(self.config.get("preset") or ""),
            generation=generation,
        )
        self._sessions[key] = session
        self._by_agent[agent] = session
        self.logger.info("channel session created key=%s agent=%s", key, agent)
        return session

    def remove(self, session: ChannelSession) -> None:
        try:
            self.adapter.cancel_pending(session)
        except Exception:
            pass
        self._sessions.pop(session.key, None)
        self._by_agent.pop(session.agent_name, None)

    # ── Inbound ────────────────────────────────────────────────────────────
    async def handle_message(self, message: ChannelMessage) -> None:
        if self._closed:
            return
        if not self._dedup(message.message_id):
            return
        if self.policy.allow is not None and not self.policy.allow(message):
            return
        if self.policy.should_answer is not None and not self.policy.should_answer(message):
            return
        text = str(message.text or "")
        if self.adapter.handle_text(message.scope, message.peer_id, text):
            return
        parsed = self.commands.parse(text)
        if parsed is not None:
            command, args, raw = parsed
            await self._run_command(message, command, args, raw)
            return
        key = message.reply_target.key
        state = self._merge.get(key)
        if state is not None and state["busy"]:
            if len(state["buffer"]) >= int(self.config.get("maxQueue") or 20):
                return
            state["buffer"].append(message)
            return
        state = {"busy": True, "buffer": []}
        self._merge[key] = state
        try:
            await self._run_one(message)
            while state["buffer"]:
                batch = state["buffer"]
                state["buffer"] = []
                merged, prepared = await self._merge_messages(batch)
                await self._run_one(merged, prepared_text=prepared)
        finally:
            state["busy"] = False
            self._merge.pop(key, None)

    def _dedup(self, message_id: str) -> bool:
        message_id = str(message_id or "")
        if not message_id:
            return True
        now = time.time()
        previous = self._seen.get(message_id)
        if previous is not None and now - previous < 5.0:
            return False
        self._seen[message_id] = now
        if len(self._seen) > 1000:
            cutoff = now - 5.0
            for key in [key for key, value in self._seen.items() if value < cutoff]:
                self._seen.pop(key, None)
        return True

    async def _prepare(self, message: ChannelMessage) -> str:
        if self.policy.prepare is not None:
            prepared = await self.policy.prepare(message)
            return str(prepared or "")
        return str(message.text or "")

    async def _merge_messages(self, batch: list[ChannelMessage]) -> tuple[ChannelMessage, str]:
        base = batch[-1]
        texts: list[str] = []
        attachments: list[dict[str, Any]] = []
        for message in batch:
            text = (await self._prepare(message)).strip()
            if text:
                texts.append(text)
            attachments.extend(message.attachments or [])
        merged = ChannelMessage(
            channel=base.channel,
            scope=base.scope,
            peer_id=base.peer_id,
            sender_id=base.sender_id,
            sender_name=base.sender_name,
            group_id=base.group_id,
            text="\n\n".join(texts),
            message_id=base.message_id,
            timestamp_ms=base.timestamp_ms,
            attachments=attachments,
            raw=base.raw,
            target=base.reply_target,
        )
        return merged, merged.text

    async def _run_one(self, message: ChannelMessage, *, prepared_text: str | None = None) -> None:
        text = prepared_text if prepared_text is not None else await self._prepare(message)
        if not text.strip() and not message.attachments:
            return
        session = self.get_or_create(message)
        try:
            await self._run_turn(session, text, message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.exception("channel turn failed: %s", exc)
            session.last_error = str(exc)
            try:
                await self.adapter.send_text(message.reply_target, "⚠️ 本轮处理失败，请稍后重试。")
            except Exception:
                pass
        finally:
            if self.policy.after_turn is not None:
                try:
                    result = self.policy.after_turn(session, message)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass

    async def _run_turn(self, session: ChannelSession, text: str, message: ChannelMessage) -> Any:
        async with session.lock:
            session.task = asyncio.current_task()
            token = _current_session.set(session)
            try:
                result = await self._run_with_pending(session, text, message)
                session.last_result = result
                session.last_activity = time.time()
                session.message_count += 2
                session.transcript.append({"role": "user", "text": text})
                reply = str(getattr(result, "message", "") or "").strip()
                if reply:
                    session.transcript.append({"role": "assistant", "text": reply})
                if getattr(result, "session_id", ""):
                    session.session_id = str(result.session_id)
                return result
            finally:
                _current_session.reset(token)
                if session.task is asyncio.current_task():
                    session.task = None

    async def _run_with_pending(self, session: ChannelSession, text: str, message: ChannelMessage) -> Any:
        timeout = max(10_000, int(self.config.get("processingTimeoutMs") or 1_800_000)) / 1000.0
        ask_timeout = max(1_000, int(self.config.get("askTimeoutMs") or 300_000))
        model = session.model or str(self.config.get("model") or "")
        preset = session.preset or str(self.config.get("preset") or "")
        mode = str(self.config.get("agentMode") or "")
        run_kwargs: dict[str, Any] = {
            "task": text,
            "agent": session.agent_name,
            "model": model,
            "mode": mode,
            "preset": preset,
            "late_context": str(self.config.get("lateContext") or ""),
            "attachments": [
                str(item.get("localPath") or item.get("path") or "")
                for item in (message.attachments or [])
                if item.get("localPath") or item.get("path")
            ] or None,
            "parent_call_id": session.agent_name,
        }
        try:
            result = await asyncio.wait_for(self.runner.run(**run_kwargs), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("本轮处理超时") from exc
        while True:
            pending = dict(getattr(result, "pending_approval", {}) or {})
            if not pending:
                break
            tool_call = pending.get("tool_call") or {}
            if not tool_call:
                break
            request_payload = pending.get("request_payload") or {}
            request_kind = str(
                pending.get("request_kind")
                or request_payload.get("request_kind")
                or ("question" if tool_call.get("name") == "question" else "permission")
            )
            if request_kind == "question":
                answer = await self.adapter.ask_questions(session, pending, ask_timeout)
                if answer is None:
                    await self._clear_pending(session, result, tool_call, text, model, mode, question=True)
                    break
                answer_text = self._format_answer(answer)
                question_text = self._question_text(pending, request_payload, tool_call)
                result = await asyncio.wait_for(
                    self.runner.resume_question(
                        session_id=str(result.session_id),
                        pending_call=tool_call,
                        task=text,
                        agent=session.agent_name,
                        parent_call_id=session.agent_name,
                        answer=answer_text,
                        question=question_text,
                        model=model,
                        mode=mode,
                    ),
                    timeout=timeout,
                )
            else:
                decision = await self.adapter.ask_approval(session, pending, ask_timeout)
                if decision == "allow":
                    result = await asyncio.wait_for(
                        self.runner.resume_approved(
                            session_id=str(result.session_id),
                            pending_call=tool_call,
                            task=text,
                            agent=session.agent_name,
                            parent_call_id=session.agent_name,
                            model=model,
                            mode=mode,
                        ),
                        timeout=timeout,
                    )
                else:
                    # Denial/timeout/cancel is delivered as a tool result so the
                    # child can adapt; this also clears the host's pending record.
                    answer = (
                        "用户拒绝了这次工具调用。不要执行它；根据已有信息继续，或向用户说明。"
                        if decision == "deny"
                        else "审批等待超时或已取消；不要执行这次工具调用。"
                    )
                    result = await asyncio.wait_for(
                        self.runner.resume_question(
                            session_id=str(result.session_id),
                            pending_call=tool_call,
                            task=text,
                            agent=session.agent_name,
                            parent_call_id=session.agent_name,
                            answer=answer,
                            question=str(tool_call.get("name") or ""),
                            skipped=decision != "deny",
                            model=model,
                            mode=mode,
                        ),
                        timeout=timeout,
                    )
            session.last_result = result
            session.last_activity = time.time()
            if getattr(result, "session_id", ""):
                session.session_id = str(result.session_id)
        return result

    async def _clear_pending(
        self,
        session: ChannelSession,
        result: Any,
        tool_call: dict[str, Any],
        text: str,
        model: str,
        mode: str,
        *,
        question: bool,
    ) -> None:
        try:
            await self.runner.resume_question(
                session_id=str(result.session_id),
                pending_call=tool_call,
                task=text,
                agent=session.agent_name,
                parent_call_id=session.agent_name,
                answer="（用户没有回答这个问题，请按合理默认继续或结束。）",
                question=str(tool_call.get("name") or "") if not question else "",
                skipped=True,
                model=model,
                mode=mode,
            )
        except Exception as exc:
            self.logger.debug("clearing pending request failed: %s", exc)

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

    @staticmethod
    def _format_answer(answer: Any) -> str:
        if isinstance(answer, list):
            if len(answer) == 1:
                return ChannelRuntime._format_answer(answer[0])
            return "\n".join(
                f"问题 {index + 1}: {ChannelRuntime._format_answer(item)}"
                for index, item in enumerate(answer)
            )
        if isinstance(answer, dict):
            selected = [str(item) for item in (answer.get("selected") or []) if str(item)]
            custom = str(answer.get("custom") or "").strip()
            return "、".join(selected) or custom or "（用户没有回答这个问题。）"
        return str(answer or "（用户没有回答这个问题。）")

    async def _run_command(self, message: ChannelMessage, command: ChannelCommand, args: list[str], raw: str) -> None:
        session = self.get_or_create(message)
        context = ChannelCommandContext(
            session=session,
            message=message,
            args=args,
            raw=raw,
            runtime=self,
        )
        try:
            result = command.handler(context)
            if asyncio.iscoroutine(result):
                result = await result
            if result:
                for chunk in chunk_text(str(result), int(self.config.get("textChunkLimit") or 4500)):
                    await self.adapter.send_text(message.reply_target, chunk)
        except Exception as exc:
            self.logger.exception("channel command %s failed: %s", command.name, exc)
            try:
                await self.adapter.send_text(message.reply_target, f"⚠️ 指令执行失败: {exc}")
            except Exception:
                pass

    # ── Interactions ───────────────────────────────────────────────────────
    async def handle_interaction(self, event: Any) -> bool:
        matched = False
        try:
            matched = bool(self.adapter.handle_interaction(event))
        except Exception:
            self.logger.exception("channel interaction handling failed")
        try:
            self.adapter.acknowledge_interaction(event)
        except Exception:
            pass
        return matched

    # ── Outbound events ────────────────────────────────────────────────────
    async def _on_event(self, event: Any) -> None:
        name = str(getattr(event, "name", "") or "")
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            return
        sub = payload.get("sub_agent")
        sub = sub if isinstance(sub, dict) else {}
        agent_name = str(sub.get("agent") or "")
        session = self.by_agent(agent_name)
        if session is None:
            return
        if name == "runtime.reply_delta":
            await self._on_delta(session, str(payload.get("content") or ""))
        elif name == "runtime.reply":
            await self._on_reply(session, str(payload.get("content") or ""))
        elif name == "runtime.tool.started":
            self._on_tool_started(session, payload)
        elif name == "runtime.tool.finished":
            await self._on_tool_finished(session, payload)
        elif name == "runtime.usage":
            self._on_usage(session, payload)
        elif name == "deliverables/presented":
            self._collect_files(session, payload.get("files"))
        elif name in {"runtime.done", "runtime.failed", "runtime.cancelled"}:
            await self._on_turn_end(session, name, payload)

    async def _on_delta(self, session: ChannelSession, content: str) -> None:
        if not content:
            return
        buffer = self._buffer(session)
        buffer.text += content
        if not bool(self.config.get("streaming", True)):
            return
        if buffer.stream is None:
            try:
                buffer.stream = self.adapter.open_stream(session.target)
            except Exception as exc:
                self.logger.debug("channel open_stream failed: %s", exc)
                buffer.stream = None
        if buffer.stream is not None:
            try:
                await buffer.stream.update(buffer.text)
            except Exception as exc:
                buffer.stream_failed = True
                self.logger.warning("channel stream update failed: %s", exc)

    async def _on_reply(self, session: ChannelSession, content: str) -> None:
        buffer = self._buffer(session)
        if buffer.text.strip():
            await self._flush(session, buffer)
            return
        if content.strip():
            await self._send(session, content)
        buffer.final_sent = True

    def _buffer(self, session: ChannelSession) -> _Buffer:
        return self._buffers.setdefault(session.agent_name, _Buffer())

    async def _flush(self, session: ChannelSession, buffer: _Buffer) -> None:
        if not buffer.text.strip():
            return
        if buffer.stream is not None:
            try:
                await buffer.stream.complete()
            except Exception as exc:
                buffer.stream_failed = True
                self.logger.warning("channel stream complete failed: %s", exc)
            fallback = bool(getattr(buffer.stream, "should_fallback", False))
            if not buffer.stream_failed and not fallback:
                buffer.text = ""
                buffer.final_sent = True
                return
        await self._send(session, buffer.text)
        buffer.text = ""
        buffer.final_sent = True

    def _on_tool_started(self, session: ChannelSession, payload: dict[str, Any]) -> None:
        call_id = str(payload.get("call_id") or "")
        if call_id:
            self._tool_calls[(session.agent_name, call_id)] = {
                "name": str(payload.get("tool_name") or ""),
                "arguments": payload.get("arguments") or {},
            }

    async def _on_tool_finished(self, session: ChannelSession, payload: dict[str, Any]) -> None:
        call_id = str(payload.get("call_id") or "")
        call = self._tool_calls.pop((session.agent_name, call_id), None)
        tool_name = str(payload.get("tool_name") or (call or {}).get("name") or "tool")
        error = str(payload.get("error") or "")
        if error or bool(self.config.get("showToolResults", False)):
            if error:
                error_code = str(payload.get("error_code") or "")
                text = f"❌ 工具 `{tool_name}` 执行失败" + (f"\n`{error_code}`" if error_code else "") + f"\n{_truncate(error)}"
            else:
                content = str(payload.get("content") or "").strip()
                text = f"🔧 `{tool_name}` 完成\n{_truncate(content)}" if content else ""
            if text:
                await self._send(session, text)
        self._collect_files(session, payload.get("artifacts"))

    def _collect_files(self, session: ChannelSession, files: Any) -> None:
        if not isinstance(files, list):
            return
        bucket = self._artifacts.setdefault(session.agent_name, [])
        for item in files:
            path = ""
            if isinstance(item, dict):
                metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                path = str(
                    metadata.get("path")
                    or metadata.get("localPath")
                    or item.get("path")
                    or item.get("uri")
                    or ""
                )
            elif isinstance(item, str):
                path = item
            if path.startswith("file://"):
                from urllib.parse import unquote, urlparse

                parsed = urlparse(path)
                path = unquote(parsed.path)
                if len(path) > 3 and path[0] == "/" and path[2] == ":":
                    path = path[1:]
            if path and path not in bucket:
                bucket.append(path)

    def _on_usage(self, session: ChannelSession, payload: dict[str, Any]) -> None:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return
        session.usage["input"] += int(usage.get("prompt_tokens") or usage.get("input") or 0)
        session.usage["output"] += int(usage.get("completion_tokens") or usage.get("output") or 0)
        session.usage["cacheRead"] += int(usage.get("cached_tokens") or usage.get("cacheRead") or 0)
        session.usage["cacheWrite"] += int(usage.get("cache_creation_tokens") or usage.get("cacheWrite") or 0)

    async def _on_turn_end(self, session: ChannelSession, name: str, payload: dict[str, Any]) -> None:
        buffer = self._buffers.pop(session.agent_name, None)
        if buffer is not None:
            await self._flush(session, buffer)
        if name == "runtime.failed":
            code = str(payload.get("error_code") or payload.get("code") or "ERROR")
            message = str(payload.get("error") or payload.get("message") or "unknown error")
            if code not in SILENT_TURN_ERROR_CODES:
                await self._send(session, f"⚠️ 本轮异常结束\n`{code}`: {message}")
        elif name == "runtime.cancelled":
            await self._send(session, "⛔ 本轮已中止")
        files = self._artifacts.pop(session.agent_name, [])
        if files and bool((self.config.get("sendFile") or {}).get("sendPresentedFiles", True)):
            await self._deliver_files(session, files)
        for key in [key for key in self._tool_calls if key[0] == session.agent_name]:
            self._tool_calls.pop(key, None)

    async def _send(self, session: ChannelSession, text: str) -> None:
        for chunk in chunk_text(text, int(self.config.get("textChunkLimit") or 4500)):
            try:
                await self.adapter.send_text(session.target, chunk)
            except Exception as exc:
                self.logger.error("channel send failed: %s", exc)

    async def _deliver_files(self, session: ChannelSession, files: list[str]) -> None:
        limit = max(1, int((self.config.get("sendFile") or {}).get("maxFiles") or 4))
        missed: list[str] = []
        for index, path in enumerate(files):
            name = Path(path).name
            if index >= limit:
                missed.append(f"{name}（超出单轮投递上限，未发送）")
                continue
            try:
                result = await self.adapter.send_file(session.target, path, name)
            except Exception as exc:
                self.logger.warning("channel file delivery failed %s: %s", name, exc)
                missed.append(name)
                continue
            if result.get("outcome") not in {None, "sent"}:
                missed.append(name)
        if missed:
            await self._send(session, "📎 已生成文件（未能直接发送）：\n" + "\n".join(f"- {item}" for item in missed))

    # ── Session operations ─────────────────────────────────────────────────
    def set_model(self, session: ChannelSession, model: str) -> None:
        session.model = str(model or "")

    def set_preset(self, session: ChannelSession, preset_id: str) -> dict[str, Any]:
        preset_id = str(preset_id or "")
        if self.presets is not None and hasattr(self.presets, "has") and preset_id and not self.presets.has(preset_id):
            return {"ok": False, "error": f"unknown preset: {preset_id}"}
        session.preset = preset_id
        return {"ok": True, "preset": preset_id}

    def list_models(self) -> list[dict[str, Any]]:
        if self.model_catalog is not None and hasattr(self.model_catalog, "list"):
            return [model.to_dict() for model in self.model_catalog.list()]
        return []

    def list_presets(self) -> list[dict[str, Any]]:
        if self.presets is not None and hasattr(self.presets, "list"):
            return [
                {
                    "id": preset.id,
                    "title": preset.title or preset.id,
                    "description": preset.description,
                    "mode": preset.mode,
                    "tools": list(preset.tools),
                }
                for preset in self.presets.list()
            ]
        return []

    async def session_info(self, session: ChannelSession) -> dict[str, Any]:
        info: dict[str, Any] = {
            "key": session.key,
            "scope": session.scope,
            "peerId": session.peer_id,
            "agent": session.agent_name,
            "sessionId": session.session_id,
            "model": session.model,
            "preset": session.preset,
            "messageCount": session.message_count,
            "lastActivity": int(session.last_activity * 1000),
            "running": session.task is not None and not session.task.done(),
            "usage": dict(session.usage),
            "lastError": session.last_error,
            "transcript": list(session.transcript),
        }
        if session.session_id and hasattr(self.runner, "session_info"):
            try:
                host_info = await self.runner.session_info(session.session_id)
                info["host"] = host_info
                info["messageCount"] = host_info.get("message_count", info["messageCount"])
                info["usage"] = host_info.get("usage", info["usage"])
            except Exception:
                pass
        return info

    async def compact(self, session: ChannelSession) -> dict[str, Any]:
        if not session.session_id:
            return {"status": "no-session"}
        # Prefer the preset-scoped service so a plugin can replace compaction
        # without replacing the runner.
        service = None
        resolver = getattr(self.runner, "preset_service", None)
        if callable(resolver):
            try:
                service = resolver("compaction", session.preset)
            except Exception:
                service = None
        compact_now = getattr(service, "compact_now", None)
        if callable(compact_now):
            return await compact_now(session.session_id)
        compact = getattr(self.runner, "compact", None)
        if not callable(compact):
            return {"status": "unavailable"}
        return await compact(session.session_id)

    async def fork(self, session: ChannelSession, new_agent_name: str) -> dict[str, Any]:
        if not session.session_id:
            raise ValueError("session has no child session to fork")
        fork = getattr(self.runner, "fork", None)
        if not callable(fork):
            raise RuntimeError("host runner does not support fork")
        info = await fork(session.session_id, new_agent_name)
        old_agent = session.agent_name
        session.agent_name = str(info["agent"])
        session.session_id = str(info["session_id"])
        session.transcript.clear()
        session.message_count = 0
        self._by_agent.pop(old_agent, None)
        self._by_agent[session.agent_name] = session
        return info

    def reset(self, session: ChannelSession) -> None:
        try:
            self.adapter.cancel_pending(session)
        except Exception:
            pass
        self._generation += 1
        session.generation = self._generation
        old_agent = session.agent_name
        session.agent_name = self._agent_name(session.key, self._generation)
        session.session_id = ""
        session.transcript.clear()
        session.message_count = 0
        session.last_result = None
        session.last_error = ""
        self._by_agent.pop(old_agent, None)
        self._by_agent[session.agent_name] = session

    async def stop(self, session: ChannelSession) -> bool:
        task = session.task
        if task is None or task.done():
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        session.last_error = "cancelled"
        return True

    def export_markdown(self, session: ChannelSession) -> str:
        lines = ["# 会话导出", "", f"> session: {session.session_id or session.agent_name}", ""]
        for item in session.transcript:
            title = "用户" if item.get("role") == "user" else "助手"
            lines.extend([f"## {title}", "", str(item.get("text") or ""), ""])
        return "\n".join(lines)

    def evict_idle(self, timeout_ms: int | None = None) -> int:
        timeout = (int(timeout_ms) if timeout_ms is not None else int(self.config.get("sessionIdleTimeout") or 1_800_000)) / 1000.0
        now = time.time()
        removed = 0
        for session in list(self._sessions.values()):
            if session.task is not None and not session.task.done():
                continue
            if now - session.last_activity > timeout:
                self.remove(session)
                removed += 1
        return removed

    async def dispose(self) -> None:
        self._closed = True
        tasks = [session.task for session in self._sessions.values() if session.task is not None and not session.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._sessions.clear()
        self._by_agent.clear()


class ChannelHost:
    """Factory exposed to plugin backends as ``context.service('channel_host')``."""

    def create(
        self,
        adapter: ChannelAdapter,
        *,
        context: Any,
        config: dict[str, Any] | None = None,
        data_dir: str | Path,
        work_root: str | Path,
        logger: logging.Logger | None = None,
        policy: ChannelPolicy | None = None,
        commands: list[ChannelCommand] | None = None,
        runner: Any | None = None,
        runner_factory: Callable[..., Any] | None = None,
    ) -> ChannelRuntime:
        return ChannelRuntime(
            adapter=adapter,
            context=context,
            config=config,
            data_dir=data_dir,
            work_root=work_root,
            logger=logger,
            policy=policy,
            commands=commands,
            runner=runner,
            runner_factory=runner_factory,
        )


def _truncate(text: str) -> str:
    if len(text) <= RESULT_PREVIEW_LIMIT:
        return text
    return text[:RESULT_PREVIEW_LIMIT] + "\n…（已截断）"


__all__ = [
    "ChannelRuntime",
    "ChannelHost",
    "current_channel_session",
    "SILENT_TURN_ERROR_CODES",
]
