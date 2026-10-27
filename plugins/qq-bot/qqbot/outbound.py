"""Outbound routing: host runtime events -> QQ messages.

The host forwards child events with a ``sub_agent`` block.  The router maps
them onto the upstream plugin's semantics:

* ``runtime.reply_delta``      -> streaming buffer / static accumulation
* ``runtime.reply``            -> final text (flush the stream, else send)
* ``runtime.tool.started``     -> remember the call for result formatting
* ``runtime.tool.finished``    -> error always shown; success by config
* ``runtime.usage``            -> per-session token counters
* ``runtime.done/failed/cancelled`` -> flush, report failure, deliver files
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import load_config
from .media import path_is_allowed, send_media_file
from .protocol import MsgIdCache, QQApi, ReplyLimiter, ReplyTarget, resolve_reply_target
from .util import chunk_markdown_text, format_file_size

RESULT_PREVIEW_LIMIT = 1500
SILENT_TURN_ERROR_CODES = {"STREAM_CLOSED"}


@dataclass
class _Buffer:
    text: str = ""
    stream: Any | None = None
    stream_failed: bool = False
    final_sent: bool = False


class OutboundRouter:
    def __init__(
        self,
        *,
        api: QQApi,
        config: dict[str, Any],
        logger: logging.Logger,
        find_by_agent: Callable[[str], Any],
        cache: MsgIdCache,
        limiter: ReplyLimiter,
        data_dir: Path,
        work_root: str | Path | None,
    ) -> None:
        self.api = api
        self.config = config
        self.logger = logger
        self.find_by_agent = find_by_agent
        self.cache = cache
        self.limiter = limiter
        self.data_dir = Path(data_dir)
        self.work_root = work_root
        self._buffers: dict[str, _Buffer] = {}
        self._tool_calls: dict[tuple[str, str], dict[str, str]] = {}
        self._artifacts: dict[str, list[str]] = {}

    # ── Public sender used by approvals/questions ──────────────────────────
    async def send_markdown(
        self,
        target: ReplyTarget,
        content: str,
        keyboard: dict[str, Any] | None = None,
    ) -> Any:
        resolved = resolve_reply_target(target, self.limiter, self.cache, allow_event=True)
        return await self.api.send_markdown(resolved, content, keyboard=keyboard)

    # ── Event entry ────────────────────────────────────────────────────────
    async def handle_event(self, event: Any) -> None:
        name = str(getattr(event, "name", "") or "")
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            return
        sub = payload.get("sub_agent")
        sub = sub if isinstance(sub, dict) else {}
        agent_name = str(sub.get("agent") or "")
        if not agent_name:
            return
        session = self.find_by_agent(agent_name)
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
        elif name in {"runtime.done", "runtime.failed", "runtime.cancelled"}:
            await self._on_turn_end(session, name, payload)

    # ── Streaming / final text ─────────────────────────────────────────────
    async def _on_delta(self, session: Any, content: str) -> None:
        if not content:
            return
        buffer = self._buffer(session)
        buffer.text += content
        if self._should_stream(session):
            if buffer.stream is None:
                buffer.stream = self.api.open_stream(session.reply_target)
            try:
                await buffer.stream.update(buffer.text)
            except Exception as exc:
                buffer.stream_failed = True
                self.logger.warning("QQ stream update failed, will fall back to static: %s", exc)

    async def _on_reply(self, session: Any, content: str) -> None:
        buffer = self._buffer(session)
        if buffer.text.strip():
            await self._flush(session, buffer)
            return
        if content.strip():
            await self._send(session, content, "reply")
        buffer.final_sent = True

    def _buffer(self, session: Any) -> _Buffer:
        return self._buffers.setdefault(session.agent_name, _Buffer())

    def _should_stream(self, session: Any) -> bool:
        return (
            bool(self.config.get("streaming", True))
            and session.reply_target.scope == "c2c"
            and bool(session.reply_target.msg_id)
        )

    async def _flush(self, session: Any, buffer: _Buffer) -> None:
        if not buffer.text.strip():
            return
        if buffer.stream is not None:
            try:
                await buffer.stream.complete()
            except Exception as exc:
                buffer.stream_failed = True
                self.logger.warning("QQ stream complete failed: %s", exc)
            if not buffer.stream_failed and not buffer.stream.should_fallback:
                buffer.text = ""
                buffer.final_sent = True
                return
        await self._send(session, buffer.text, "flush")
        buffer.text = ""
        buffer.final_sent = True

    # ── Tool results ───────────────────────────────────────────────────────
    def _on_tool_started(self, session: Any, payload: dict[str, Any]) -> None:
        call_id = str(payload.get("call_id") or "")
        if not call_id:
            return
        self._tool_calls[(session.agent_name, call_id)] = {
            "name": str(payload.get("tool_name") or ""),
            "arguments": payload.get("arguments") or {},
        }

    async def _on_tool_finished(self, session: Any, payload: dict[str, Any]) -> None:
        call_id = str(payload.get("call_id") or "")
        call = self._tool_calls.pop((session.agent_name, call_id), None)
        tool_name = str(payload.get("tool_name") or (call or {}).get("name") or "tool")
        error = str(payload.get("error") or "")
        if error or bool(self.config.get("showToolResults", False)):
            text = self._format_tool_result(tool_name, payload)
            if text:
                await self._send(session, text, "tool")
        artifacts = payload.get("artifacts")
        if isinstance(artifacts, list):
            for artifact in artifacts:
                path = _artifact_path(artifact)
                if path:
                    bucket = self._artifacts.setdefault(session.agent_name, [])
                    if path not in bucket:
                        bucket.append(path)

    @staticmethod
    def _format_tool_result(tool_name: str, payload: dict[str, Any]) -> str:
        error = str(payload.get("error") or "")
        error_code = str(payload.get("error_code") or "")
        if error:
            detail = f"\n`{error_code}`" if error_code else ""
            return f"❌ 工具 `{tool_name}` 执行失败{detail}\n{_truncate(error)}"
        content = str(payload.get("content") or "").strip()
        if not content:
            return ""
        return f"🔧 `{tool_name}` 完成\n{_truncate(content)}"

    def _on_usage(self, session: Any, payload: dict[str, Any]) -> None:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return
        session.usage["input"] += int(usage.get("prompt_tokens") or usage.get("input") or 0)
        session.usage["output"] += int(usage.get("completion_tokens") or usage.get("output") or 0)
        session.usage["cacheRead"] += int(usage.get("cached_tokens") or usage.get("cacheRead") or 0)
        session.usage["cacheWrite"] += int(usage.get("cache_creation_tokens") or usage.get("cacheWrite") or 0)

    # ── Turn end ───────────────────────────────────────────────────────────
    async def _on_turn_end(self, session: Any, name: str, payload: dict[str, Any]) -> None:
        buffer = self._buffers.pop(session.agent_name, None)
        if buffer is not None:
            await self._flush(session, buffer)
        if name == "runtime.failed":
            code = str(payload.get("error_code") or payload.get("code") or "ERROR")
            message = str(payload.get("error") or payload.get("message") or "unknown error")
            if code not in SILENT_TURN_ERROR_CODES:
                await self._send(session, f"⚠️ 本轮异常结束\n`{code}`: {message}", "turn-error")
        elif name == "runtime.cancelled":
            await self._send(session, "⛔ 本轮已中止", "turn-cancelled")
        files = self._artifacts.pop(session.agent_name, [])
        if files and bool((self.config.get("sendFile") or {}).get("sendPresentedFiles", True)):
            await self._deliver_files(session, files)
        for key in [key for key in self._tool_calls if key[0] == session.agent_name]:
            self._tool_calls.pop(key, None)

    async def _deliver_files(self, session: Any, files: list[str]) -> None:
        limit = max(1, int((self.config.get("sendFile") or {}).get("maxFiles") or 4))
        missed: list[str] = []
        for index, file_path in enumerate(files):
            name = Path(file_path).name
            if index >= limit:
                missed.append(f"{name}（超出单轮投递上限，未发送）")
                continue
            if not path_is_allowed(
                file_path,
                data_dir=self.data_dir,
                work_root=self.work_root,
                config=self.config,
            ):
                missed.append(f"{name}（路径不在允许范围）")
                continue
            target = resolve_reply_target(session.reply_target, self.limiter, self.cache, allow_event=False)
            result = await send_media_file(self.api, target, file_path, logger=self.logger)
            if result.get("outcome") == "sent":
                self.logger.info(
                    "QQ deliverable sent %s (%s) -> %s:%s",
                    name,
                    format_file_size(result.get("size") or 0),
                    session.reply_target.scope,
                    session.reply_target.target_id,
                )
            else:
                missed.append(name)
        if missed:
            text = "📎 已生成文件（未能直接发送）：\n" + "\n".join(f"- {item}" for item in missed)
            await self._send(session, text, "deliverables-notice")

    # ── Low-level send ─────────────────────────────────────────────────────
    async def _send(self, session: Any, text: str, tag: str) -> None:
        limit = int(self.config.get("textChunkLimit") or 4500)
        for chunk in chunk_markdown_text(text, limit):
            try:
                target = resolve_reply_target(session.reply_target, self.limiter, self.cache, allow_event=True)
                await self.api.send_markdown(target, chunk)
            except Exception as exc:
                self.logger.error("QQ %s send failed: %s", tag, exc)


def _artifact_path(artifact: Any) -> str:
    if not isinstance(artifact, dict):
        return ""
    metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
    for key in ("path", "localPath", "local_path", "file"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    uri = str(artifact.get("uri") or "")
    if uri.startswith("file://"):
        from urllib.parse import unquote, urlparse

        parsed = urlparse(uri)
        path = unquote(parsed.path)
        # Windows file URLs look like file:///C:/x; urlparse keeps the leading
        # slash.  Strip it only when the remainder is a drive-qualified path.
        if len(path) > 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return path
    if uri and (uri.startswith("/") or (len(uri) > 2 and uri[1] == ":")):
        return uri
    return ""


def _truncate(text: str) -> str:
    if len(text) <= RESULT_PREVIEW_LIMIT:
        return text
    return text[:RESULT_PREVIEW_LIMIT] + "\n…（已截断）"


__all__ = ["OutboundRouter", "SILENT_TURN_ERROR_CODES"]
