from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
import uuid
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
ConnectedCallback = Callable[[Any], Awaitable[Any]]

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
        self._streamed_message_text: dict[str, str] = {}
        self._streamed_tool_content: str = ""
        self._streamed_tool_label: str = ""
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
        data = event_data(event)
        method, run_item = app_server_method_payload(data)
        if method == "core/runItem" and str(run_item.get("kind") or "") == "message":
            payload = run_item_payload(run_item)
            if payload.get("type") != "compaction":
                item_id = str(run_item.get("item_id") or "")
                delta = str(payload.get("delta") or "")
                if item_id and delta:
                    self._streamed_message_text[item_id] = self._streamed_message_text.get(item_id, "") + delta
                    self._inline_delta_active = True
                    return [OutputChunk(delta, end="")]
                content = str(payload.get("content") or "")
                streamed = self._streamed_message_text.get(item_id) if item_id else None
                if streamed is not None and content.startswith(streamed):
                    suffix = content[len(streamed):]
                    self._streamed_message_text[item_id] = content
                    if suffix:
                        self._inline_delta_active = True
                        return [OutputChunk(suffix, end="")]
                    return []
        compaction = compaction_event_details(event)
        if compaction is not None:
            run_item, payload, status = compaction
            item_id = str(run_item.get("item_id") or run_item.get("event_id") or "")
            delta = str(payload.get("delta") or "")
            if status == "running" and delta and item_id in self._seen_running_compactions:
                self._inline_delta_active = True
                return [OutputChunk(delta, end="")]
        if str(event.get("event") or "") == "display":
            display_event = CoreDisplayEvent.from_dict(event_data(event))
            if display_event.metadata.get("delta") and display_event.content:
                self._inline_delta_active = True
                return [OutputChunk(display_event.content, end="")]
            return self._close_inline_delta([OutputChunk(line) for line in self._format_display_event(display_event)])
        event_kind = str(run_item.get("kind") or "") if run_item and isinstance(run_item, dict) else ""
        if event_kind == "tool_call":
            payload = run_item_payload(run_item)
            preview = payload.get("input_preview")
            content = str(preview.get("content", "")) if isinstance(preview, dict) else ""
            if content:
                tool_name = str(payload.get("tool_name") or payload.get("kind") or "?")
                args = payload.get("arguments") or payload.get("tool_args")
                path = action_path(args) if isinstance(args, dict) else ""
                if not self._streamed_tool_label:
                    if not path:
                        self._streamed_tool_content = content
                        return []
                    label_parts = [self.label(tool_tag(tool_name), path, time.monotonic())]
                    self._streamed_tool_label = " ".join(label_parts) + " "
                    self._streamed_tool_content = ""
                prev = self._streamed_tool_content
                if content.startswith(prev) and len(content) > len(prev):
                    delta = content[len(prev):]
                    self._streamed_tool_content = content
                    self._inline_delta_active = True
                    suffix = OutputChunk(delta, end="")
                    if not prev:
                        suffix = OutputChunk(self._streamed_tool_label + delta, end="")
                    return [suffix]
                elif not prev:
                    self._streamed_tool_content = content
                    self._inline_delta_active = True
                    return [OutputChunk(self._streamed_tool_label + content, end="")]
            return []
        else:
            self._streamed_tool_label = ""
            self._streamed_tool_content = ""
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
            if isinstance(payload.get("input_preview"), dict) and payload["input_preview"].get("content"):
                return []
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
            # `runtime.metrics` items (`replace: true`) are session-cumulative
            # context snapshots, not per-call usage — never count them as calls.
            if payload.get("replace") is True:
                return [self.line("debug", json.dumps(run_item.get("usage") or payload, ensure_ascii=False))] if self.verbose else []
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
                reason = str(
                    payload.get("error")
                    or payload.get("message")
                    or payload.get("raw_end_reason")
                    or payload.get("reason")
                    or status
                )
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
        status = compaction_business_status(run_item, payload)
        if status == "running":
            item_id = str(run_item.get("item_id") or run_item.get("event_id") or "")
            if item_id and item_id in self._seen_running_compactions:
                delta = str(payload.get("delta") or "")
                return [delta] if delta else []
            if item_id:
                self._seen_running_compactions.add(item_id)
            self.last_status = "compacting"
            return [self.line("phase", str(payload.get("label") or "\u6b63\u5728\u538b\u7f29\u4e0a\u4e0b\u6587"))]
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
    target_turn_id = ""

    while True:
        client = client_factory()
        try:
            await client.connect(thread_id=thread_id, last_seen_seq=last_seen_seq)
            if not started and on_connected is not None:
                start_result = await on_connected(client)
                target_turn_id = started_turn_id(start_result)
            started = True
            events = client.events().__aiter__()
            while True:
                try:
                    event = await anext(events) if event_timeout is None else await asyncio.wait_for(anext(events), timeout=event_timeout)
                except StopAsyncIteration as exc:
                    raise ConnectionError("app-server connection closed") from exc
                last_seen_seq = max(last_seen_seq, event_sequence(event))
                if target_turn_id and event_turn_id(event) != target_turn_id:
                    continue
                failed = failed or is_failed_event(event)
                if raw:
                    if raw_watch_event_visible(event):
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


async def execute_compaction_command_live(
    *,
    client_factory: ClientFactory,
    thread_id: str,
    work_root: str,
    formatter: CliLiveFormatter,
    output: OutputCallback,
    raw: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Execute /compact while consuming only its new compaction events."""
    client = client_factory()
    event_task: asyncio.Task[dict[str, Any]] | None = None
    operation_task: asyncio.Task[dict[str, Any]] | None = None
    saw_terminal = False
    client_command_id = uuid.uuid4().hex
    target_turn_id = f"{thread_id}:command:compact:{client_command_id}"
    try:
        # command.execute subscribes the connection before starting compaction.
        # Avoid replaying an arbitrarily large historical event stream first.
        await client.connect()
        operation_task = asyncio.create_task(
            client.execute_command(
                thread_id=thread_id,
                command="compact",
                work_root=work_root,
                client_command_id=client_command_id,
            )
        )
        events = client.events().__aiter__()
        event_task = asyncio.create_task(anext(events))

        while True:
            waiters: set[asyncio.Task[Any]] = {operation_task}
            if event_task is not None:
                waiters.add(event_task)
            done, _pending = await asyncio.wait(
                waiters,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if event_task in done:
                try:
                    event = event_task.result()
                except StopAsyncIteration:
                    event_task = None
                else:
                    details = compaction_event_details(event)
                    if details is not None and event_turn_id(event) == target_turn_id:
                        if raw:
                            await emit_output(output, OutputChunk(json.dumps(event, ensure_ascii=False)))
                        else:
                            for chunk in formatter.format_chunks(event):
                                await emit_output(output, chunk)
                        saw_terminal = details[2] in {
                            "compacted", "completed", "not_needed", "skipped", "failed", "error", "cancelled",
                        }
                    event_task = asyncio.create_task(anext(events))

            if operation_task.done():
                if operation_task.cancelled() or operation_task.exception() is not None or saw_terminal:
                    break
                if event_task is None:
                    break

        return await operation_task, saw_terminal
    finally:
        if event_task is not None and not event_task.done():
            event_task.cancel()
        if operation_task is not None and not operation_task.done():
            operation_task.cancel()
        await client.close()


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
    message = str(payload.get("error") or payload.get("message") or payload.get("reason") or "").strip()
    return f"\u538b\u7f29\u672a\u5b8c\u6210{f'\uff1a{message}' if message else ''} \u00b7 \u539f\u4e0a\u4e0b\u6587\u5df2\u4fdd\u7559"


def format_compaction_result(payload: dict[str, Any]) -> str:
    status = str(payload.get("compaction_status") or payload.get("compactionStatus") or payload.get("status") or "")
    if status in {"skipped", "not_needed"}:
        reason = str(payload.get("reason") or "")
        gain = " \u00b7 \u672a\u83b7\u5f97\u6536\u76ca" if reason == "no_gain" else ""
        return f"\u65e0\u9700\u538b\u7f29{gain} \u00b7 \u539f\u4e0a\u4e0b\u6587\u5df2\u4fdd\u7559"
    if status in {"failed", "error", "cancelled"}:
        return format_compaction_failure(payload)
    label = str(payload.get("label") or "\u4e0a\u4e0b\u6587\u5df2\u538b\u7f29").strip() or "\u4e0a\u4e0b\u6587\u5df2\u538b\u7f29"
    before, after = payload.get("before_tokens"), payload.get("after_tokens")
    segments = payload.get("segments")
    pieces: list[str] = []
    if isinstance(before, int) and isinstance(after, int):
        pieces.append(f"{before} \u2192 {after} tokens")
    if isinstance(segments, int) and segments > 1:
        pieces.append(f"{segments} \u6bb5")
    return " \u00b7 ".join([label, *pieces]) if pieces else label


def compaction_business_status(run_item: dict[str, Any], payload: dict[str, Any]) -> str:
    return str(
        payload.get("compaction_status")
        or payload.get("compactionStatus")
        or payload.get("status")
        or run_item.get("status")
        or ""
    )


def compaction_event_details(
    event: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str] | None:
    if str(event.get("event") or "") != "app_server_event":
        return None
    method, run_item = app_server_method_payload(event_data(event))
    if method != "core/runItem":
        return None
    payload = run_item_payload(run_item)
    if payload.get("type") != "compaction":
        return None
    return run_item, payload, compaction_business_status(run_item, payload)


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
    raw = payload.get("message") or payload.get("summary") or payload.get("error") or fallback or ""
    preview = payload.get("input_preview")
    if isinstance(preview, dict) and preview.get("content"):
        p = str(preview["content"]).replace("\n", " ").strip()
        raw = f"{preview.get('chars', '?')} chars: {p}"
    text = str(raw).strip()
    return " ".join(bit for bit in (app_server_tool_name(payload), action_path(args) if isinstance(args, dict) else "", shorten(text, 200)) if bit)


def tool_tag(tool_name: str) -> str:
    """Map a tool name to a concise Chinese action label for the live CLI.

    Mirrors the simplified UI wording: no category tag, just the action verb.
    """
    normalized = str(tool_name or "").lower()
    if "checklist" in normalized:
        return "清单"
    if "write" in normalized or "create" in normalized:
        return "创建"
    if "edit" in normalized or "patch" in normalized:
        return "编辑"
    if any(marker in normalized for marker in ("command", "run", "exec", "bash", "shell")):
        return "运行命令"
    if any(marker in normalized for marker in ("search", "grep", "glob", "find")):
        return "搜索"
    if any(marker in normalized for marker in ("fetch", "browser", "http")):
        return "获取网页"
    if any(marker in normalized for marker in ("read", "cat", "get-content")):
        return "读取"
    if any(marker in normalized for marker in ("list", "ls", "dir")):
        return "列出"
    if "git" in normalized:
        return "git 差异" if "diff" in normalized else "git 状态"
    if "question" in normalized or "ask" in normalized:
        return "提问"
    if "sub_agent" in normalized or "subagent" in normalized:
        return "子代理"
    if "skill" in normalized:
        return "技能"
    if "workflow" in normalized:
        return "工作流"
    if "goal" in normalized:
        return "目标"
    if "arrange" in normalized:
        return "定时任务"
    if "mcp" in normalized:
        return "MCP"
    return "工具"


def is_failed_event(event: dict[str, Any]) -> bool:
    if str(event.get("event") or "") != "app_server_event":
        return False
    method, run_item = app_server_method_payload(event_data(event))
    if method != "core/runItem":
        return False
    kind = str(run_item.get("kind") or "")
    status = run_item_status(run_item, run_item_payload(run_item))
    return kind == "error" or (kind == "status" and status in {"failed", "cancelled", "error"})


def event_turn_id(event: dict[str, Any]) -> str:
    method, payload = app_server_method_payload(event_data(event))
    if method == "core/runItem":
        return str(payload.get("turn_id") or payload.get("turnId") or "")
    return str(payload.get("turn_id") or payload.get("turnId") or "")


def started_turn_id(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    runtime_start = result.get("runtime_start")
    if isinstance(runtime_start, dict):
        return str(runtime_start.get("turn_id") or runtime_start.get("turnId") or "")
    return str(result.get("turn_id") or result.get("turnId") or "")


def raw_watch_event_visible(event: dict[str, Any]) -> bool:
    if str(event.get("event") or "") != "app_server_event":
        return False
    method, run_item = app_server_method_payload(event_data(event))
    if method != "core/runItem":
        return False
    kind = str(run_item.get("kind") or "")
    payload = run_item_payload(run_item)
    if kind == "message":
        return bool(payload.get("delta"))
    return kind == "status" and run_item_status(run_item, payload) in {
        "completed", "failed", "cancelled", "error",
    }


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
        status = compaction_business_status(run_item, payload)
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
    "execute_compaction_command_live",
    "format_compaction_result",
    "format_event",
    "format_run_item_event",
    "is_done_event",
    "is_failed_event",
    "is_resumed_event",
    "is_waiting_event",
    "watch_live_events",
]
