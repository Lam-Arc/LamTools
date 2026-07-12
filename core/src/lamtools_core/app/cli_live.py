from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from lamtools_core.kernel.display import CoreDisplayEvent, CoreDisplayFormatter


LabelCallback = Callable[[str, str, float], str]
InputCallback = Callable[[Any], str]
OutputCallback = Callable[["OutputChunk"], Any]
ApprovalCallback = Callable[[], str | Awaitable[str]]
ApprovalDecisionCallback = Callable[[str], str]
ClientFactory = Callable[[], Any]
ConnectedCallback = Callable[[Any], Awaitable[None]]

logger = logging.getLogger(__name__)


class OutputChunk(str):
    """A string-compatible CLI write with explicit newline behavior."""

    def __new__(cls, text: str, *, end: str = "\n", flush: bool = True) -> "OutputChunk":
        value = super().__new__(cls, text)
        value.end = end
        value.flush = flush
        return value


def default_input_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(str(item.get("text") or "") for item in value if isinstance(item, dict))
    return ""


def default_label(tag: str, text: str, started_at: float) -> str:
    elapsed = max(0, int(time.monotonic() - started_at))
    minutes, seconds = divmod(elapsed, 60)
    hours, minutes = divmod(minutes, 60)
    elapsed_label = f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
    return f"[{elapsed_label}] {tag}" + (f" {text}" if text else "")


class CliLiveFormatter:
    """Format app-server events without product-specific command semantics."""

    def __init__(
        self,
        *,
        verbose: bool = False,
        heartbeat_interval: int = 30,
        label: LabelCallback = default_label,
        input_text: InputCallback = default_input_text,
    ) -> None:
        self.verbose = verbose
        self.heartbeat_interval = heartbeat_interval
        self.label = label
        self.input_text = input_text
        self.started_at = time.monotonic()
        self.last_heartbeat_at = self.started_at
        self.last_status = "started"
        self.llm_call_count = 0
        self._counted_usage_event_ids: set[str] = set()
        self._seen_running_compactions: set[str] = set()
        self._inline_delta_active = False

    def line(self, tag: str, text: str = "") -> str:
        return self.label(tag, text, self.started_at)

    def format(self, event: dict[str, Any]) -> list[str]:
        event_type = str(event.get("event", "message"))
        data = event_data(event)

        if event_type == "ping":
            now = time.monotonic()
            if now - self.last_heartbeat_at >= self.heartbeat_interval:
                self.last_heartbeat_at = now
                return [self.line("wait", f"still running; last={self.last_status}")]
            return []
        if event_type == "app_server_event":
            return self._format_app_server_event(data)
        if event_type == "live_error":
            self.last_status = "error"
            return [self.line("error", shorten(str(data.get("error") or data.get("message") or event), 300))]
        if event_type == "display":
            return self._format_display(data)
        return []

    def format_chunks(self, event: dict[str, Any]) -> list[OutputChunk]:
        if str(event.get("event") or "") == "display":
            display_event = CoreDisplayEvent.from_dict(event_data(event))
            if display_event.metadata.get("delta") and display_event.content:
                self._inline_delta_active = True
                return [OutputChunk(display_event.content, end="")]
            return self._close_inline_delta([OutputChunk(line) for line in self._format_display_event(display_event)])
        return self._close_inline_delta([OutputChunk(line) for line in self.format(event)])

    def _close_inline_delta(self, chunks: list[OutputChunk]) -> list[OutputChunk]:
        if not chunks or not self._inline_delta_active:
            return chunks
        self._inline_delta_active = False
        return [OutputChunk("\n", end=""), *chunks]

    def _format_app_server_event(self, data: dict[str, Any]) -> list[str]:
        method, payload = app_server_method_payload(data)
        if method == "core/runItem":
            return self._format_core_run_item(payload)
        item_type = str(payload.get("type") or "item")
        if method in {"turn/accepted", "turn/started", "turn/steered", "turn/interrupted"}:
            return []
        if method == "item/started" and item_type == "userMessage":
            text = shorten(self.input_text(payload.get("content")), 160)
            return [self.line("message:user", text)] if text else [self.line("message:user")]
        if method == "serverRequest/resolved":
            self.last_status = "resumed"
            return [self.line("resumed")]
        if method == "queue/itemAccepted":
            self.last_status = "queued"
            return [self.line("phase", "queued")]
        if method == "queue/itemDispatched":
            self.last_status = "queue_dispatched"
            return [self.line("phase", "queue_dispatched")]
        if method == "queue/itemUpdated":
            phase = str(payload.get("status") or "queue_updated")
            self.last_status = phase
            return [self.line("phase", phase)]
        if self.verbose:
            return [self.line("runtime_event", f"{method} {json.dumps(payload, ensure_ascii=False)}")]
        return []

    def _format_core_run_item(self, run_item: dict[str, Any]) -> list[str]:
        kind = str(run_item.get("kind") or "")
        payload = run_item_payload(run_item)
        if payload.get("type") == "compaction":
            return self._format_compaction_run_item(run_item, payload)
        if kind == "message":
            text = run_item_text(payload, input_text=self.input_text)
            return [self.line("reply", shorten(text, 300 if self.verbose else 180))] if text else []
        if kind in {"thinking", "reasoning"}:
            text = run_item_text(payload, input_text=self.input_text)
            return [self.line("think", shorten(text, 220))] if self.verbose and text else []
        if kind == "tool_call":
            tool_name = app_server_tool_name(payload)
            self.last_status = f"tool:{tool_name}:running"
            return [self.line(tool_tag(tool_name), app_server_tool_detail(payload) or tool_name)]
        if kind == "tool_result":
            tool_name = app_server_tool_name(payload)
            self.last_status = f"tool:{tool_name}:completed"
            detail = app_server_tool_detail(payload, run_item_text(payload, input_text=self.input_text))
            return [self.line(tool_tag(tool_name), detail or tool_name)]
        if kind == "approval_request":
            self.last_status = "waiting_for_user"
            text = str(payload.get("message") or payload.get("summary") or "waiting")
            return [self.line("waiting_for_user", shorten(text, 220))]
        if kind == "artifact":
            artifact = run_item_artifact(run_item, payload)
            detail = shorten(str(artifact.get("title") or artifact.get("path") or artifact.get("artifact_id") or "artifact"), 180)
            return [self.line("file", detail)]
        if kind == "usage":
            usage_event_id = str(run_item.get("event_id") or run_item.get("item_id") or id(run_item))
            if usage_event_id not in self._counted_usage_event_ids:
                self.llm_call_count += 1
                self._counted_usage_event_ids.add(usage_event_id)
            return [self.line("debug", json.dumps(run_item.get("usage") or payload, ensure_ascii=False))] if self.verbose else []
        if kind == "status":
            status = run_item_status(run_item, payload)
            if status == "completed":
                self.last_status = "done"
                detail = f"\u6a21\u578b\u8c03\u7528 {self.llm_call_count} \u6b21" if self.llm_call_count else ""
                return [self.line("done", detail)]
            if status in {"failed", "cancelled", "error"}:
                reason = str(payload.get("raw_end_reason") or payload.get("reason") or status)
                self.last_status = f"failed:{reason}"
                return [self.line("failed", reason)]
            if status:
                self.last_status = status
                return [self.line("phase", status)]
        if kind == "error":
            self.last_status = "error"
            text = str(payload.get("message") or payload.get("error") or payload or "error")
            return [self.line("error", shorten(text, 300))]
        if self.verbose:
            return [self.line("runtime_event", f"core/runItem {json.dumps(run_item, ensure_ascii=False)}")]
        return []

    def _format_compaction_run_item(self, run_item: dict[str, Any], payload: dict[str, Any]) -> list[str]:
        status = run_item_status(run_item, payload)
        if status == "running":
            item_id = str(run_item.get("item_id") or run_item.get("event_id") or "")
            if item_id and item_id in self._seen_running_compactions:
                delta = str(payload.get("delta") or "")
                return [self.line("debug", shorten(delta, 220))] if self.verbose and delta else []
            if item_id:
                self._seen_running_compactions.add(item_id)
            self.last_status = "compacting"
            return [self.line("phase", "\u6b63\u5728\u538b\u7f29\u4e0a\u4e0b\u6587...")]
        if status in {"failed", "error", "cancelled"}:
            self.last_status = "compaction_failed"
            return [self.line("failed", format_compaction_failure(payload))]
        self.last_status = "compacted"
        lines = [self.line("done", format_compaction_result(payload))]
        if self.verbose and payload.get("content"):
            lines.append(str(payload.get("content")))
        return lines

    def _format_display(self, data: dict[str, Any]) -> list[str]:
        return self._format_display_event(CoreDisplayEvent.from_dict(data))

    def _format_display_event(self, display_event: CoreDisplayEvent) -> list[str]:
        if display_event.metadata.get("delta") and display_event.content:
            return [display_event.content]
        formatter = CoreDisplayFormatter(verbose=self.verbose)
        formatter.started_at = self.started_at
        return formatter.format(display_event)


@dataclass(frozen=True)
class CliLiveWatchResult:
    completed: bool
    failed: bool
    last_seen_seq: int
    error: str = ""

    @property
    def exit_code(self) -> int:
        return 2 if self.failed else 0


async def watch_live_events(
    *,
    client_factory: ClientFactory,
    thread_id: str,
    formatter: CliLiveFormatter,
    output: OutputCallback,
    raw: bool = False,
    approval: ApprovalCallback | None = None,
    approval_decision: ApprovalDecisionCallback | None = None,
    on_connected: ConnectedCallback | None = None,
    initial_last_seen_seq: int = 0,
    event_timeout: float | None = None,
    reconnect_delay: float = 1.0,
    max_reconnects: int = 3,
) -> CliLiveWatchResult:
    last_seen_seq = initial_last_seen_seq
    reconnects = 0
    failed = False
    started = False
    approval_prompted = False

    while True:
        client = client_factory()
        try:
            await client.connect(thread_id=thread_id, last_seen_seq=last_seen_seq)
            if not started and on_connected is not None:
                await on_connected(client)
            started = True
            events = client.events().__aiter__()
            while True:
                try:
                    event = await anext(events) if event_timeout is None else await asyncio.wait_for(anext(events), timeout=event_timeout)
                except StopAsyncIteration as exc:
                    raise ConnectionError("app-server connection closed") from exc
                last_seen_seq = max(last_seen_seq, event_sequence(event))
                failed = failed or is_failed_event(event)
                if raw:
                    await emit_output(output, OutputChunk(json.dumps(event, ensure_ascii=False)))
                else:
                    for chunk in formatter.format_chunks(event):
                        await emit_output(output, chunk)
                if is_done_event(event):
                    return CliLiveWatchResult(
                        completed=not failed,
                        failed=failed,
                        last_seen_seq=last_seen_seq,
                    )
                if approval is not None and is_waiting_event(event) and not approval_prompted:
                    request_id = event_request_id(event)
                    if request_id:
                        reply = await resolve_approval(approval)
                        decision = approval_decision(reply) if approval_decision else approval_decision_from_reply(reply)
                        await client.respond_approval(request_id=request_id, decision=decision, guidance=reply)
                        approval_prompted = True
                elif raw and is_waiting_event(event):
                    message = "approval decision is required for raw watch"
                    envelope = {
                        "event": "live_error",
                        "data": {"error": message, "thread_id": thread_id, "last_seen_seq": last_seen_seq, "reconnect": reconnects},
                    }
                    await emit_output(output, OutputChunk(json.dumps(envelope, ensure_ascii=False)))
                    return CliLiveWatchResult(completed=False, failed=True, last_seen_seq=last_seen_seq, error=message)
                elif is_resumed_event(event):
                    approval_prompted = False
        except (asyncio.TimeoutError, ConnectionError, OSError, RuntimeError) as exc:
            message = str(exc) or type(exc).__name__
            envelope = {
                "event": "live_error",
                "data": {"error": message, "thread_id": thread_id, "last_seen_seq": last_seen_seq, "reconnect": reconnects},
            }
            if raw:
                await emit_output(output, OutputChunk(json.dumps(envelope, ensure_ascii=False)))
            else:
                for chunk in formatter.format_chunks(envelope):
                    await emit_output(output, chunk)
            if reconnects >= max_reconnects:
                return CliLiveWatchResult(completed=False, failed=True, last_seen_seq=last_seen_seq, error=message)
            reconnects += 1
            if reconnect_delay:
                await asyncio.sleep(reconnect_delay)
        finally:
            try:
                await client.close()
            except Exception:
                logger.warning("Failed to close live client", exc_info=True)


async def emit_output(output: OutputCallback, value: OutputChunk) -> None:
    result = output(value)
    if inspect.isawaitable(result):
        await result


async def resolve_approval(approval: ApprovalCallback) -> str:
    reply = approval()
    if inspect.isawaitable(reply):
        reply = await reply
    return str(reply).strip()


def shorten(text: str, max_chars: int = 180) -> str:
    clean = " ".join(str(text or "").split())
    return clean if len(clean) <= max_chars else clean[: max_chars - 3].rstrip() + "..."


def event_data(event: dict[str, Any]) -> dict[str, Any]:
    top_level = {key: value for key, value in event.items() if key not in {"event", "data"} and value is not None}
    data = event.get("data", {})
    if isinstance(data, dict):
        return {**top_level, **data}
    if top_level:
        top_level["value"] = data
        return top_level
    return {"value": data}


def app_server_method_payload(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    payload = data.get("payload")
    return str(data.get("method") or ""), payload if isinstance(payload, dict) else {}


def run_item_payload(run_item: dict[str, Any]) -> dict[str, Any]:
    payload = run_item.get("payload")
    return payload if isinstance(payload, dict) else {}


def run_item_text(payload: dict[str, Any], *, input_text: InputCallback = default_input_text) -> str:
    for key in ("delta", "content", "message", "summary"):
        value = payload.get(key)
        text = input_text(value) if key == "content" else str(value or "")
        text = text.strip()
        if text:
            return text
    return ""


def run_item_status(run_item: dict[str, Any], payload: dict[str, Any]) -> str:
    return str(run_item.get("status") or payload.get("status") or "")


def run_item_artifact(run_item: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    artifacts = run_item.get("artifacts")
    if isinstance(artifacts, list):
        first = next((item for item in artifacts if isinstance(item, dict)), None)
        if first is not None:
            return first
    artifact = payload.get("artifact")
    return artifact if isinstance(artifact, dict) else payload


def format_compaction_failure(payload: dict[str, Any]) -> str:
    message = str(payload.get("error") or payload.get("message") or payload.get("reason") or "\u538b\u7f29\u5931\u8d25").strip()
    return f"\u538b\u7f29\u5931\u8d25\uff1a{message}" if not message.startswith("\u538b\u7f29\u5931\u8d25") else message


def format_compaction_result(payload: dict[str, Any]) -> str:
    status = str(payload.get("compaction_status") or payload.get("compactionStatus") or payload.get("status") or "")
    if status == "skipped":
        return str(payload.get("message") or payload.get("reason") or "\u6682\u65e0\u53ef\u538b\u7f29\u4e0a\u4e0b\u6587")
    label = str(payload.get("label") or "\u4e0a\u4e0b\u6587\u5df2\u538b\u7f29").strip() or "\u4e0a\u4e0b\u6587\u5df2\u538b\u7f29"
    before, after = payload.get("before_tokens"), payload.get("after_tokens")
    count = payload.get("compacted_messages", payload.get("removed_messages"))
    pieces: list[str] = []
    if isinstance(before, int) and isinstance(after, int):
        pieces.append(f"{before} -> {after} tokens")
    if isinstance(count, int):
        pieces.append(f"\u538b\u7f29 {count} \u6761\u6d88\u606f")
    return f"{label}\uff1a" + "\uff0c".join(pieces) + "\u3002" if pieces else label


def action_path(params: dict[str, Any]) -> str:
    for key in ("path", "file_path", "url", "command"):
        if value := params.get(key):
            return shorten(str(value), 120)
    return ""


def app_server_tool_name(payload: dict[str, Any]) -> str:
    return str(payload.get("tool_name") or payload.get("kind") or payload.get("type") or "tool")


def app_server_tool_detail(payload: dict[str, Any], fallback: str = "") -> str:
    args = payload.get("arguments")
    if not isinstance(args, dict):
        args = payload.get("tool_args")
    text = str(payload.get("message") or payload.get("summary") or payload.get("error") or fallback or "").strip()
    return " ".join(bit for bit in (app_server_tool_name(payload), action_path(args) if isinstance(args, dict) else "", shorten(text, 180)) if bit)


def tool_tag(tool_name: str) -> str:
    normalized = str(tool_name or "").lower()
    return "file" if any(marker in normalized for marker in ("file", "dir", "path", "write", "edit", "read")) else "tool"


def is_failed_event(event: dict[str, Any]) -> bool:
    if str(event.get("event") or "") != "app_server_event":
        return False
    method, run_item = app_server_method_payload(event_data(event))
    if method != "core/runItem":
        return False
    status = run_item_status(run_item, run_item_payload(run_item))
    return str(run_item.get("kind") or "") == "error" or status in {"failed", "cancelled", "error"}


def is_done_event(event: dict[str, Any]) -> bool:
    if str(event.get("event") or "") != "app_server_event":
        return False
    method, run_item = app_server_method_payload(event_data(event))
    if method != "core/runItem":
        return False
    kind = str(run_item.get("kind") or "")
    status = run_item_status(run_item, run_item_payload(run_item))
    return kind == "error" or (kind == "status" and status in {"completed", "failed", "cancelled", "error"})


def is_waiting_event(event: dict[str, Any]) -> bool:
    method, run_item = app_server_method_payload(event_data(event))
    return str(event.get("event") or "") == "app_server_event" and method == "core/runItem" and str(run_item.get("kind") or "") == "approval_request"


def is_resumed_event(event: dict[str, Any]) -> bool:
    method, _payload = app_server_method_payload(event_data(event))
    return str(event.get("event") or "") == "app_server_event" and method == "serverRequest/resolved"


def event_request_id(event: dict[str, Any]) -> str:
    method, payload = app_server_method_payload(event_data(event))
    if str(event.get("event") or "") != "app_server_event":
        return ""
    if method == "core/runItem":
        run_payload = run_item_payload(payload)
        return str(run_payload.get("request_id") or payload.get("item_id") or "")
    return str(payload.get("request_id") or "")


def approval_decision_from_reply(reply: str) -> str:
    normalized = reply.strip().lower()
    if normalized in {"y", "yes", "ok", "approve", "approved", "\u540c\u610f", "\u6279\u51c6"}:
        return "approve_once"
    if normalized in {"n", "no", "deny", "decline", "reject", "\u62d2\u7edd"}:
        return "deny"
    return "other_guidance"


def event_sequence(event: dict[str, Any]) -> int:
    value = event_data(event).get("seq")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def format_event(event: dict[str, Any]) -> str | None:
    if str(event.get("event") or "") == "ping":
        return None
    if str(event.get("event") or "") != "app_server_event":
        return None
    method, run_item = app_server_method_payload(event_data(event))
    if method == "core/runItem":
        return format_run_item_event(run_item)
    payload = run_item
    item_type = str(payload.get("type") or "item")
    if method in {"turn/accepted", "turn/started", "turn/steered", "turn/interrupted"}:
        return None
    if method == "item/started" and item_type == "userMessage":
        text = default_input_text(payload.get("content"))
        return f"[user] {text}" if text else "[user]"
    if method == "serverRequest/resolved":
        return "[resumed]"
    if method == "queue/itemAccepted":
        return "[phase] queued"
    if method == "queue/itemDispatched":
        return "[phase] queue_dispatched"
    if method == "queue/itemUpdated":
        return f"[phase] {payload.get('status') or 'queue_updated'}"
    return f"[{method}] {json.dumps(payload, ensure_ascii=False)}" if method else None


def format_run_item_event(run_item: dict[str, Any]) -> str | None:
    kind = str(run_item.get("kind") or "")
    payload = run_item_payload(run_item)
    if payload.get("type") == "compaction":
        status = run_item_status(run_item, payload)
        if status == "running":
            return "\u6b63\u5728\u538b\u7f29\u4e0a\u4e0b\u6587..."
        return format_compaction_failure(payload) if status in {"failed", "error", "cancelled"} else format_compaction_result(payload)
    if kind == "message":
        return run_item_text(payload) or None
    if kind in {"thinking", "reasoning"}:
        text = run_item_text(payload)
        return f"[thinking] {text}" if text else None
    if kind in {"tool_call", "tool_result"}:
        fallback = run_item_text(payload) if kind == "tool_result" else ""
        return f"[tool] {app_server_tool_detail(payload, fallback)}".rstrip()
    if kind == "approval_request":
        text = str(payload.get("message") or payload.get("summary") or "")
        return f"[waiting] {text}" if text else "[waiting for user]"
    if kind == "approval_response":
        return "[resumed]"
    if kind == "artifact":
        artifact = run_item_artifact(run_item, payload)
        text = str(artifact.get("title") or artifact.get("path") or artifact.get("artifact_id") or "")
        return f"[artifact] {text}" if text else "[artifact]"
    if kind == "status":
        status = run_item_status(run_item, payload)
        if status == "completed":
            return "[done]"
        if status in {"failed", "cancelled", "error"}:
            return f"[failed] {payload.get('raw_end_reason') or payload.get('reason') or status}"
        return f"[phase] {status}" if status else None
    if kind == "error":
        return f"[error] {payload.get('message') or payload.get('error') or payload}"
    return None


__all__ = [
    "CliLiveFormatter",
    "CliLiveWatchResult",
    "OutputChunk",
    "approval_decision_from_reply",
    "default_input_text",
    "default_label",
    "event_request_id",
    "format_event",
    "format_run_item_event",
    "is_done_event",
    "is_failed_event",
    "is_resumed_event",
    "is_waiting_event",
    "watch_live_events",
]
