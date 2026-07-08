from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

from lamtools_core.kernel.display import CoreDisplayEvent, CoreDisplayFormatter

import aiohttp

from writer_cli.app_server_client import AppServerClient

DEFAULT_BASE_URL = "http://127.0.0.1:6173"
DEFAULT_MODE = "EXECUTE"


@dataclass(frozen=True)
class DisplayGroup:
    """Where a runtime signal should land in UI/CLI presentation."""

    name: str
    tags: tuple[str, ...]
    default_visible: bool = True
    collapses_after_reply: bool = False
    verbose_detail: bool = False


DISPLAY_GROUPS: tuple[DisplayGroup, ...] = (
    DisplayGroup("writer_reply", ("reply", "message:reply")),
    DisplayGroup("user_message", ("message:user",)),
    DisplayGroup("decision_card", ("decision", "plan_ready", "waiting_for_user")),
    DisplayGroup("sub_line", ("agent", "delegation", "design_agent")),
    DisplayGroup(
        "processed_flow",
        ("llm", "think", "model", "plan", "progress", "tool", "file", "step", "verify", "workflow", "mode", "phase", "state"),
        collapses_after_reply=True,
    ),
    DisplayGroup("git_panel", ("git", "checkpoint", "branch", "diff", "changes")),
    DisplayGroup("error_card", ("failed", "error", "cancelled")),
    DisplayGroup("status_bar", ("done", "resumed", "wait", "running", "idle")),
    DisplayGroup("debug_log", ("raw_log", "full_text", "runtime_event", "debug"), default_visible=False, verbose_detail=True),
)
TAG_TO_DISPLAY_GROUP = {
    tag: group.name
    for group in DISPLAY_GROUPS
    for tag in group.tags
}
CLI_DISPLAY_TAGS = set(TAG_TO_DISPLAY_GROUP)


class CliError(RuntimeError):
    """A user-facing CLI failure."""


def _elapsed_label(started_at: float) -> str:
    elapsed = max(0, int(time.monotonic() - started_at))
    minutes, seconds = divmod(elapsed, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _shorten(text: str, max_chars: int = 180) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 3].rstrip() + "..."


def _tool_output_id(data: dict[str, Any]) -> str:
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        return ""
    session_memory = metadata.get("session_memory", {})
    if not isinstance(session_memory, dict):
        return ""
    return str(session_memory.get("output_id") or "")


def _action_path(params: dict[str, Any]) -> str:
    for key in ("path", "file_path", "url", "command"):
        value = params.get(key)
        if value:
            return _shorten(str(value), 120)
    return ""


def _tool_tag(tool_name: str) -> str:
    normalized = str(tool_name or "").lower()
    if any(marker in normalized for marker in ("file", "dir", "path", "write", "edit", "read")):
        return "file"
    return "tool"


class CliRunFormatter:
    """Stateful human formatter for long Writer runs."""

    def __init__(self, *, verbose: bool = False, heartbeat_interval: int = 30) -> None:
        self.verbose = verbose
        self.heartbeat_interval = heartbeat_interval
        self.started_at = time.monotonic()
        self.last_heartbeat_at = self.started_at
        self.last_status = "started"
        self.llm_call_count = 0
        self._counted_usage_event_ids: set[str] = set()
        self._seen_running_compactions: set[str] = set()

    def _line(self, label: str, text: str = "") -> str:
        suffix = f" {text}" if text else ""
        return f"[{_elapsed_label(self.started_at)}] {label}{suffix}"

    def _tagged_line(self, tag: str, text: str = "") -> str:
        # The display group is intentionally resolved here so future show/hide
        # rules can be driven by group without changing event-specific branches.
        _ = TAG_TO_DISPLAY_GROUP.get(tag, "processed_flow")
        return self._line(tag, text)

    def format(self, event: dict[str, Any]) -> list[str]:
        event_type = str(event.get("event", "message"))
        data = _event_data(event)

        if event_type == "ping":
            now = time.monotonic()
            if now - self.last_heartbeat_at >= self.heartbeat_interval:
                self.last_heartbeat_at = now
                return [self._tagged_line("wait", f"still running; last={self.last_status}")]
            return []

        if event_type == "app_server_event":
            return self._format_app_server_event(data)

        if event_type == "writer_error":
            self.last_status = "error"
            return [self._tagged_line("error", _shorten(str(data.get("error") or data.get("message") or event), 300))]

        if event_type == "display":
            return self._format_display(data)

        return []

    def _format_app_server_event(self, data: dict[str, Any]) -> list[str]:
        method, payload = _app_server_method_payload(data)
        if method == "core/runItem":
            return self._format_core_run_item(payload)

        item_type = str(payload.get("type") or "item")

        if method in {"turn/accepted", "turn/started", "turn/steered", "turn/interrupted"}:
            return []
        if method == "item/started":
            if item_type == "userMessage":
                text = _shorten(_input_text(payload.get("content")), 160)
                return [self._tagged_line("message:user", text)] if text else [self._tagged_line("message:user")]
        if method == "serverRequest/resolved":
            self.last_status = "resumed"
            return [self._tagged_line("resumed")]
        if method == "queue/itemAccepted":
            self.last_status = "queued"
            return [self._tagged_line("phase", "queued")]
        if method == "queue/itemDispatched":
            self.last_status = "queue_dispatched"
            return [self._tagged_line("phase", "queue_dispatched")]
        if method == "queue/itemUpdated":
            phase = str(payload.get("status") or "queue_updated")
            self.last_status = phase
            return [self._tagged_line("phase", phase)]
        if self.verbose:
            return [self._tagged_line("runtime_event", f"{method} {json.dumps(payload, ensure_ascii=False)}")]
        return []

    def _format_core_run_item(self, run_item: dict[str, Any]) -> list[str]:
        kind = str(run_item.get("kind") or "")
        payload = _run_item_payload(run_item)

        if payload.get("type") == "compaction":
            return self._format_compaction_run_item(run_item, payload)
        if kind == "message":
            text = _run_item_text(payload)
            return [self._tagged_line("reply", _shorten(text, 300 if self.verbose else 180))] if text else []
        if kind == "thinking":
            text = _run_item_text(payload)
            return [self._tagged_line("think", _shorten(text, 220))] if self.verbose and text else []
        if kind == "tool_call":
            tool_name = _app_server_tool_name(payload)
            detail = _app_server_tool_detail(payload)
            self.last_status = f"tool:{tool_name}:running"
            return [self._tagged_line(_tool_tag(tool_name), detail or tool_name)]
        if kind == "tool_result":
            tool_name = _app_server_tool_name(payload)
            detail = _app_server_tool_detail(payload, _run_item_text(payload))
            self.last_status = f"tool:{tool_name}:completed"
            return [self._tagged_line(_tool_tag(tool_name), detail or tool_name)]
        if kind == "approval_request":
            self.last_status = "waiting_for_user"
            text = str(payload.get("message") or payload.get("summary") or "waiting")
            return [self._tagged_line("waiting_for_user", _shorten(text, 220))]
        if kind == "artifact":
            artifact = _run_item_artifact(run_item, payload)
            detail = _shorten(str(artifact.get("title") or artifact.get("path") or artifact.get("artifact_id") or "artifact"), 180)
            return [self._tagged_line("file", detail)]
        if kind == "usage":
            usage_event_id = str(run_item.get("event_id") or run_item.get("item_id") or id(run_item))
            if usage_event_id not in self._counted_usage_event_ids:
                self.llm_call_count += 1
                self._counted_usage_event_ids.add(usage_event_id)
            return [self._tagged_line("debug", json.dumps(run_item.get("usage") or payload, ensure_ascii=False))] if self.verbose else []
        if kind == "status":
            status = _run_item_status(run_item, payload)
            if status == "completed":
                self.last_status = "done"
                return [self._tagged_line("done", f"模型调用 {self.llm_call_count} 次")]
            if status in {"failed", "cancelled", "error"}:
                reason = str(payload.get("raw_end_reason") or payload.get("reason") or status)
                self.last_status = f"failed:{reason}"
                return [self._tagged_line("failed", reason)]
            if status:
                self.last_status = status
                return [self._tagged_line("phase", status)]
        if kind == "error":
            self.last_status = "error"
            text = str(payload.get("message") or payload.get("error") or payload or "error")
            return [self._tagged_line("error", _shorten(text, 300))]

        if self.verbose:
            return [self._tagged_line("runtime_event", f"core/runItem {json.dumps(run_item, ensure_ascii=False)}")]
        return []

    def _format_compaction_run_item(self, run_item: dict[str, Any], payload: dict[str, Any]) -> list[str]:
        status = _run_item_status(run_item, payload)
        if status == "running":
            item_id = str(run_item.get("item_id") or run_item.get("event_id") or "")
            if item_id and item_id in self._seen_running_compactions:
                return [self._tagged_line("debug", _shorten(str(payload.get("delta") or ""), 220))] if self.verbose and payload.get("delta") else []
            if item_id:
                self._seen_running_compactions.add(item_id)
            self.last_status = "compacting"
            return [self._tagged_line("phase", "正在压缩上下文...")]
        if status in {"failed", "error", "cancelled"}:
            self.last_status = "compaction_failed"
            return [self._tagged_line("failed", _format_compaction_failure(payload))]
        self.last_status = "compacted"
        lines = [self._tagged_line("done", _format_compaction_result(payload))]
        if self.verbose and payload.get("content"):
            lines.append(str(payload.get("content")))
        return lines

    def _format_display(self, data: dict[str, Any]) -> list[str]:
        """Format a ``display`` event through CoreDisplayFormatter."""
        de = CoreDisplayEvent.from_dict(data)
        # Stream deltas inline — no line prefix, just the text
        if de.metadata.get("delta") and de.content:
            print(de.content, end="", flush=True)
            return []
        # Full reply: prefix a newline before starting (close the inline stream)
        if de.kind == "reply" and de.content:
            print(flush=True)  # flush any pending inline text
        fmt = CoreDisplayFormatter(verbose=self.verbose)
        fmt.started_at = self.started_at
        return fmt.format(de)


def _base_url(args: argparse.Namespace) -> str:
    return (args.base_url or os.environ.get("LAMWRITER_API_URL") or DEFAULT_BASE_URL).rstrip("/")


async def _request_json(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> Any:
    async with session.request(method, url, json=json_body) as response:
        text = await response.text()
        if response.status >= 400:
            raise CliError(f"HTTP {response.status}: {text[:500]}")
        if not text:
            return None
        return json.loads(text)


async def _create_visible_session(
    args: argparse.Namespace,
    *,
    title: str,
    work_root: str,
    mode: str,
) -> dict[str, Any]:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect()
        created = await client.create_session(title=title, work_root=work_root, mode=mode)
    if not isinstance(created, dict):
        raise CliError("Session creation returned an invalid response")
    return created


def _event_data(event: dict[str, Any]) -> dict[str, Any]:
    top_level = {
        key: value
        for key, value in event.items()
        if key not in {"event", "data"} and value is not None
    }
    data = event.get("data", {})
    if isinstance(data, dict):
        return {**top_level, **data}
    if top_level:
        top_level["value"] = data
        return top_level
    return {"value": data}


def _app_server_method_payload(data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    method = str(data.get("method") or "")
    payload = data.get("payload")
    return method, payload if isinstance(payload, dict) else {}


def _run_item_payload(run_item: dict[str, Any]) -> dict[str, Any]:
    payload = run_item.get("payload")
    return payload if isinstance(payload, dict) else {}


def _run_item_text(payload: dict[str, Any]) -> str:
    return _app_server_payload_text(payload)


def _run_item_status(run_item: dict[str, Any], payload: dict[str, Any]) -> str:
    return str(run_item.get("status") or payload.get("status") or "")


def _run_item_artifact(run_item: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    artifacts = run_item.get("artifacts")
    if isinstance(artifacts, list):
        first = next((item for item in artifacts if isinstance(item, dict)), None)
        if first is not None:
            return first
    artifact = payload.get("artifact")
    if isinstance(artifact, dict):
        return artifact
    return payload


def _input_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(str(item.get("text") or "") for item in value if isinstance(item, dict))
    return ""


def _app_server_payload_text(payload: dict[str, Any]) -> str:
    for key in ("delta", "content", "message", "summary"):
        value = payload.get(key)
        text = _input_text(value) if key == "content" else str(value or "")
        text = text.strip()
        if text:
            return text
    return ""


def _format_compaction_failure(payload: dict[str, Any]) -> str:
    message = str(payload.get("error") or payload.get("message") or payload.get("reason") or "压缩失败").strip()
    return f"压缩失败：{message}" if not message.startswith("压缩失败") else message


def _format_compaction_result(payload: dict[str, Any]) -> str:
    status = str(payload.get("compaction_status") or payload.get("compactionStatus") or payload.get("status") or "")
    if status == "skipped":
        return str(payload.get("message") or payload.get("reason") or "暂无可压缩上下文")
    label = str(payload.get("label") or "上下文已压缩").strip() or "上下文已压缩"
    before = payload.get("before_tokens")
    after = payload.get("after_tokens")
    count = payload.get("compacted_messages")
    if count is None:
        count = payload.get("removed_messages")
    pieces: list[str] = []
    if isinstance(before, int) and isinstance(after, int):
        pieces.append(f"{before} -> {after} tokens")
    if isinstance(count, int):
        pieces.append(f"压缩 {count} 条消息")
    if pieces:
        return f"{label}：" + "，".join(pieces) + "。"
    return label


def _app_server_tool_name(payload: dict[str, Any]) -> str:
    return str(payload.get("tool_name") or payload.get("kind") or payload.get("type") or "tool")


def _app_server_tool_detail(payload: dict[str, Any], fallback: str = "") -> str:
    tool_name = _app_server_tool_name(payload)
    args = payload.get("arguments")
    if not isinstance(args, dict):
        args = payload.get("tool_args")
    path = _action_path(args) if isinstance(args, dict) else ""
    text = str(
        payload.get("message")
        or payload.get("summary")
        or payload.get("error")
        or fallback
        or ""
    ).strip()
    bits = [tool_name, path, _shorten(text, 180)]
    return " ".join(bit for bit in bits if bit)


def _is_failed_event(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event", ""))
    data = _event_data(event)
    if event_type == "app_server_event":
        method, payload = _app_server_method_payload(data)
        if method == "core/runItem":
            kind = str(payload.get("kind") or "")
            run_payload = _run_item_payload(payload)
            status = _run_item_status(payload, run_payload)
            return kind == "error" or (kind == "status" and status in {"failed", "cancelled", "error"})
        return False
    return False


def _is_done_event(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event", ""))
    data = _event_data(event)
    if event_type == "app_server_event":
        method, payload = _app_server_method_payload(data)
        if method == "core/runItem":
            kind = str(payload.get("kind") or "")
            run_payload = _run_item_payload(payload)
            status = _run_item_status(payload, run_payload)
            return kind in {"error", "status"} and status in {"completed", "failed", "cancelled", "error"}
        return False
    return False


def _is_decision_event(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event", ""))
    if event_type != "app_server_event":
        return False
    method, payload = _app_server_method_payload(_event_data(event))
    return method == "core/runItem" and str(payload.get("kind") or "") == "approval_request"


def _is_waiting_event(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event", ""))
    if event_type == "app_server_event":
        method, payload = _app_server_method_payload(_event_data(event))
        return method == "core/runItem" and str(payload.get("kind") or "") == "approval_request"
    return False


def _is_resumed_event(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event", ""))
    if event_type == "app_server_event":
        method, _payload = _app_server_method_payload(_event_data(event))
        return method == "serverRequest/resolved"
    return False


def _event_request_id(event: dict[str, Any]) -> str:
    data = _event_data(event)
    if str(event.get("event") or "") == "app_server_event":
        method, payload = _app_server_method_payload(data)
        if method == "core/runItem":
            run_payload = _run_item_payload(payload)
            return str(run_payload.get("request_id") or payload.get("item_id") or "")
        return str(payload.get("request_id") or "")
    return ""


def _approval_decision_from_reply(reply: str) -> str:
    normalized = reply.strip().lower()
    if normalized in {"y", "yes", "ok", "approve", "approved", "同意", "批准"}:
        return "approve_once"
    if normalized in {"n", "no", "deny", "decline", "reject", "拒绝"}:
        return "deny"
    return "other_guidance"


def _format_event(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("event", "message"))
    data = _event_data(event)

    if event_type == "ping":
        return None
    if event_type == "app_server_event":
        return _format_app_server_event(data)
    return None


def _format_app_server_event(data: dict[str, Any]) -> str | None:
    method, payload = _app_server_method_payload(data)
    if method == "core/runItem":
        return _format_core_run_item_event(payload)

    item_type = str(payload.get("type") or "item")
    if method in {"turn/accepted", "turn/started", "turn/steered", "turn/interrupted"}:
        return None
    if method == "item/started":
        if item_type == "userMessage":
            text = _input_text(payload.get("content"))
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


def _format_core_run_item_event(run_item: dict[str, Any]) -> str | None:
    kind = str(run_item.get("kind") or "")
    payload = _run_item_payload(run_item)
    if payload.get("type") == "compaction":
        status = _run_item_status(run_item, payload)
        if status == "running":
            return "正在压缩上下文..."
        if status in {"failed", "error", "cancelled"}:
            return _format_compaction_failure(payload)
        return _format_compaction_result(payload)
    if kind == "message":
        return _run_item_text(payload) or None
    if kind == "thinking":
        text = _run_item_text(payload)
        return f"[thinking] {text}" if text else None
    if kind == "tool_call":
        return f"[tool] {_app_server_tool_detail(payload)}".rstrip()
    if kind == "tool_result":
        return f"[tool] {_app_server_tool_detail(payload, _run_item_text(payload))}".rstrip()
    if kind == "approval_request":
        text = str(payload.get("message") or payload.get("summary") or "")
        return f"[waiting] {text}" if text else "[waiting for user]"
    if kind == "approval_response":
        return "[resumed]"
    if kind == "artifact":
        artifact = _run_item_artifact(run_item, payload)
        text = str(artifact.get("title") or artifact.get("path") or artifact.get("artifact_id") or "")
        return f"[artifact] {text}" if text else "[artifact]"
    if kind == "status":
        status = _run_item_status(run_item, payload)
        if status == "completed":
            return "[done]"
        if status in {"failed", "cancelled", "error"}:
            return f"[failed] {payload.get('raw_end_reason') or payload.get('reason') or status}"
        return f"[phase] {status}" if status else None
    if kind == "error":
        return f"[error] {payload.get('message') or payload.get('error') or payload}"
    return None


async def cmd_health(args: argparse.Namespace) -> int:
    async with aiohttp.ClientSession() as session:
        data = await _request_json(session, "GET", f"{_base_url(args)}/api/health")
    print(f"{data.get('status')} {data.get('app')}")
    return 0


async def cmd_pick_directory(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect()
        path = await client.pick_project_directory()
    print(path)
    return 0


async def cmd_project_create(args: argparse.Namespace) -> int:
    work_root = str(args.work_root or "").strip()
    if not work_root:
        raise CliError("work-root is required")
    async with AppServerClient(_base_url(args)) as client:
        await client.connect()
        project = await client.create_project(work_root=work_root)
    if not project:
        raise CliError("Project creation returned an invalid response")
    print(f"{project.get('id')}  {project.get('work_root')}")
    return 0


async def cmd_list(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect()
        sessions = await client.list_sessions(limit=args.limit)
    for item in sessions:
        print(f"{item['id']}  {item['status']:<9}  {item['mode']:<9}  {item['title']}")
    return 0


async def cmd_new(args: argparse.Namespace) -> int:
    created = await _create_visible_session(
        args,
        title=args.title,
        work_root=args.work_root or "",
        mode=args.mode,
    )
    print(created["id"])
    return 0


async def cmd_show(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect(thread_id=args.session_id)
        session = await client.get_session(session_id=args.session_id)
    print(json.dumps(session, ensure_ascii=False, indent=2))
    return 0


async def cmd_rename(args: argparse.Namespace) -> int:
    title = " ".join(args.title).strip()
    if not title:
        raise CliError("title is required")
    async with AppServerClient(_base_url(args)) as client:
        await client.connect(thread_id=args.session_id)
        session = await client.update_session(session_id=args.session_id, title=title)
    print(f"[session_rename] session_id: {session.get('id', args.session_id)}")
    print(f"[session_rename] title: {session.get('title', title)}")
    return 0


async def cmd_delete(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect(thread_id=args.session_id)
        await client.delete_session(session_id=args.session_id)
    print(f"[session_delete] session_id: {args.session_id}")
    return 0


async def cmd_messages(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect(thread_id=args.session_id)
        thread = await client.read_thread(thread_id=args.session_id)
    snapshot = thread.get("snapshot") if isinstance(thread.get("snapshot"), dict) else {}
    messages = _snapshot_chat_messages(snapshot)
    visible_messages = messages[-args.limit :] if args.limit > 0 else messages
    for message in visible_messages:
        content = message.get("content") or ""
        print(f"{message['role']}: {content}")
    return 0


def _load_local_state_summary(session_id: str) -> dict[str, Any]:
    try:
        from app.config import settings
    except Exception:
        return {}
    path = os.path.join(settings.data_dir, "states", f"{session_id}.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    git_state = data.get("git_state", {}) if isinstance(data.get("git_state"), dict) else {}
    checkpoint = git_state.get("last_checkpoint", {}) if isinstance(git_state.get("last_checkpoint"), dict) else {}
    current = git_state.get("current", {}) if isinstance(git_state.get("current"), dict) else {}
    return {
        "loop_position": data.get("loop_position", ""),
        "task_complexity": data.get("task_complexity", ""),
        "planning_depth": data.get("planning_depth", ""),
        "git_branch": git_state.get("current_branch") or current.get("branch") or data.get("branch"),
        "git_head": git_state.get("current_head") or current.get("head"),
        "dirty_files": git_state.get("current_dirty_files") or current.get("dirty_files") or [],
        "owned_files": git_state.get("current_owned_files") or [],
        "checkpoint": checkpoint,
        "task_branch": git_state.get("task_branch", ""),
        "main_branch": git_state.get("main_branch", ""),
    }


def _snapshot_chat_messages(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    item_order = _merged_snapshot_item_order(snapshot)
    for item_id in item_order:
        item = _snapshot_item(snapshot, item_id)
        if not item:
            continue
        item_type = _snapshot_item_type(item)
        if item_type == "userMessage":
            messages.append({"role": "user", "content": _input_text(item.get("content"))})
            continue
        if item_type != "agentMessage":
            continue
        turn_id = str(item.get("turn_id") or "none")
        content = str(item.get("content") or "")
        if not messages or messages[-1].get("role") != "assistant" or messages[-1].get("turn_id") != turn_id:
            messages.append({"role": "assistant", "content": content, "turn_id": turn_id})
        else:
            messages[-1]["content"] = f"{messages[-1].get('content', '')}{content}"
    return [{"role": message["role"], "content": message.get("content", "")} for message in messages]


def _merged_snapshot_item_order(snapshot: dict[str, Any]) -> list[str]:
    order: list[str] = []
    seen: set[str] = set()
    core = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
    for item_id in [*(snapshot.get("item_order") or []), *(core.get("item_order") or [])]:
        item = str(item_id or "")
        if not item or item in seen:
            continue
        seen.add(item)
        order.append(item)
    return order


def _snapshot_item(snapshot: dict[str, Any], item_id: str) -> dict[str, Any]:
    core = snapshot.get("core") if isinstance(snapshot.get("core"), dict) else {}
    core_items = core.get("items") if isinstance(core.get("items"), dict) else {}
    top_items = snapshot.get("items") if isinstance(snapshot.get("items"), dict) else {}
    raw = core_items.get(item_id) or top_items.get(item_id)
    return raw if isinstance(raw, dict) else {}


def _snapshot_item_type(item: dict[str, Any]) -> str:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    item_type = item.get("type") or payload.get("type")
    if item_type:
        return str(item_type)
    kind = str(item.get("kind") or "")
    if kind == "message":
        return "agentMessage"
    return kind


async def cmd_status(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect(thread_id=args.session_id)
        thread = await client.read_thread(thread_id=args.session_id)

    info = thread.get("session") if isinstance(thread.get("session"), dict) else {"id": args.session_id}
    snapshot = thread.get("snapshot") if isinstance(thread.get("snapshot"), dict) else {}
    messages = _snapshot_chat_messages(snapshot)
    state = _load_local_state_summary(args.session_id)
    print(f"session {info.get('id')}")
    status = info.get("status") or snapshot.get("status")
    phase = info.get("phase") or "-"
    mode = info.get("mode") or "-"
    print(f"status  {status}  phase={phase}  mode={mode}")
    print(f"root    {info.get('work_root') or '(default)'}")
    if state:
        print(
            "loop    "
            f"{state.get('loop_position') or '-'}  "
            f"complexity={state.get('task_complexity') or '-'}  "
            f"planning={state.get('planning_depth') or '-'}"
        )
        head = str(state.get("git_head") or "")
        print(f"git     branch={state.get('git_branch') or '-'} head={head[:8] if head else '-'}")
        if state.get("task_branch") or state.get("main_branch"):
            print(f"refs    task={state.get('task_branch') or '-'} main={state.get('main_branch') or '-'}")
        dirty_files = state.get("dirty_files") or []
        owned_files = state.get("owned_files") or []
        print(f"dirty   total={len(dirty_files)} writer_owned={len(owned_files)}")
        checkpoint = state.get("checkpoint") or {}
        if checkpoint:
            commit = str(checkpoint.get("commit") or checkpoint.get("head") or "")
            paths = checkpoint.get("paths") or []
            print(f"checkpoint {commit[:8] if commit else '-'} files={len(paths)} reason={checkpoint.get('reason') or ''}".rstrip())
    if messages:
        print("recent")
        for message in messages[-3:]:
            role = message.get("role", "")
            content = _shorten(str(message.get("content") or ""), 120)
            print(f"  {role}: {content}")
    return 0


async def cmd_result(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect(thread_id=args.session_id)
        thread = await client.read_thread(thread_id=args.session_id)

    info = thread.get("session") if isinstance(thread.get("session"), dict) else {"id": args.session_id}
    snapshot = thread.get("snapshot") if isinstance(thread.get("snapshot"), dict) else {}
    messages = _snapshot_chat_messages(snapshot)
    state = _load_local_state_summary(args.session_id)
    print(f"session {info.get('id')}")
    status = info.get("status") or snapshot.get("status")
    phase = info.get("phase") or "-"
    print(f"status  {status}  phase={phase}")
    print(f"root    {info.get('work_root') or '(default)'}")
    if state:
        checkpoint = state.get("checkpoint") or {}
        if checkpoint:
            commit = str(checkpoint.get("commit") or checkpoint.get("head") or "")
            paths = checkpoint.get("paths") or []
            print(f"commit  {commit[:8] if commit else '-'}  files={len(paths)}")
            for path in paths[:12]:
                print(f"  changed {path}")
        head = str(state.get("git_head") or "")
        print(f"git     branch={state.get('git_branch') or '-'} head={head[:8] if head else '-'}")

    assistant_messages = [
        str(message.get("content") or "")
        for message in messages
        if message.get("role") == "assistant" and message.get("content")
    ]
    if assistant_messages:
        print("summary")
        print("  " + _shorten(assistant_messages[-1], 300))
    return 0


async def cmd_cancel(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect(thread_id=args.session_id)
        await client.cancel_turn(thread_id=args.session_id)
    print("cancelled")
    return 0


async def cmd_compact(args: argparse.Namespace) -> int:
    print("正在压缩上下文...")
    async with AppServerClient(_base_url(args)) as client:
        await client.connect(thread_id=args.session_id)
        result = await client.execute_command(
            thread_id=args.session_id,
            command="compact",
            work_root=args.work_root or "",
        )
    print(_format_compaction_result(result))
    if args.verbose and result.get("summary"):
        print()
        print(str(result.get("summary")))
    return 0


async def cmd_open_change_file(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect(thread_id=args.session_id)
        try:
            result = await client.request(
                "session.change_file.open",
                {"session_id": args.session_id, "path": args.path},
            )
        except RuntimeError as exc:
            raise CliError(str(exc)) from exc
    path = str(result.get("path") or args.path)
    opened_with = str(result.get("opened_with") or "unknown")
    print(f"[open_change_file] {path} via {opened_with}")
    return 0


async def _stream_chat(
    args: argparse.Namespace,
    session_id: str,
    message: str,
) -> int:
    failed = False
    interactive = (
        not args.raw
        and (
            getattr(args, "interactive_decisions", False)
            or (
                not getattr(args, "no_interactive_decisions", False)
                and sys.stdin.isatty()
            )
        )
    )
    decision_prompted = False
    formatter = CliRunFormatter(
        verbose=bool(getattr(args, "verbose", False)),
        heartbeat_interval=int(getattr(args, "heartbeat_interval", 30) or 30),
    )
    async with AppServerClient(_base_url(args)) as client:
        await client.connect(thread_id=session_id)
        await client.start_turn(
            thread_id=session_id,
            message=message,
            work_root=args.work_root or "",
            mode=args.mode,
            model_id=getattr(args, "model_id", None),
            shallow_thinking_enabled=bool(getattr(args, "shallow_thinking", False)),
        )
        async for event in client.events():
            if _is_failed_event(event):
                failed = True
            if args.raw:
                print(json.dumps(event, ensure_ascii=False), flush=True)
                if _is_done_event(event):
                    break
                continue
            for line in formatter.format(event):
                print(line, flush=True)
            if _is_done_event(event):
                break
            if interactive and (_is_decision_event(event) or _is_waiting_event(event)) and not decision_prompted:
                reply = await _prompt_reply(args)
                request_id = _event_request_id(event)
                if request_id:
                    await client.respond_approval(
                        request_id=request_id,
                        decision=_approval_decision_from_reply(reply),
                        guidance=reply,
                    )
                decision_prompted = True
            elif _is_resumed_event(event):
                decision_prompted = False
    return 2 if failed else 0


async def _prompt_reply(args: argparse.Namespace) -> str:
    """Prompt the user for a free-text reply."""
    _ = args
    return (await asyncio.to_thread(input, "reply> ")).strip()


async def cmd_run(args: argparse.Namespace) -> int:
    message = " ".join(args.message)
    title = args.title or message[:48] or "CLI Session"
    created = await _create_visible_session(
        args,
        title=title,
        work_root=args.work_root or "",
        mode=args.mode,
    )
    print(f"[session] {created['id']}")
    return await _stream_chat(args, created["id"], message)


async def cmd_resume(args: argparse.Namespace) -> int:
    return await _stream_chat(args, args.session_id, " ".join(args.message))


async def cmd_watch(args: argparse.Namespace) -> int:
    formatter = CliRunFormatter(
        verbose=bool(getattr(args, "verbose", False)),
        heartbeat_interval=int(getattr(args, "heartbeat_interval", 30) or 30),
    )
    failed = False
    async with AppServerClient(_base_url(args)) as client:
        await client.connect(thread_id=args.session_id)
        for line in [formatter._line("watch", args.session_id)]:
            print(line, flush=True)
        async for event in client.events():
            if _is_failed_event(event):
                failed = True
            if args.raw:
                print(json.dumps(event, ensure_ascii=False), flush=True)
            else:
                for line in formatter.format(event):
                    print(line, flush=True)
            if _is_done_event(event):
                break
    return 2 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="writer",
        description="LamWriter CLI - run, watch, and resume Writer tasks",
    )
    parser.add_argument("--base-url", default=None, help=f"Backend URL, default {DEFAULT_BASE_URL}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health", help="Check backend health").set_defaults(func=cmd_health)

    project_parser = sub.add_parser("project", help="Project utilities")
    project_sub = project_parser.add_subparsers(dest="project_command", required=True)
    project_create = project_sub.add_parser("create", help="Create a project")
    project_create.add_argument("--work-root", required=True)
    project_create.set_defaults(func=cmd_project_create)
    project_pick = project_sub.add_parser("pick-directory", help="Open the local directory picker")
    project_pick.set_defaults(func=cmd_pick_directory)

    list_parser = sub.add_parser("list", help="List sessions")
    list_parser.add_argument("-n", "--limit", type=int, default=20)
    list_parser.set_defaults(func=cmd_list)

    new_parser = sub.add_parser("new", help="Create a session")
    new_parser.add_argument("title", nargs="?", default="CLI Session")
    new_parser.add_argument("--work-root", default="")
    new_parser.add_argument("--mode", default=DEFAULT_MODE)
    new_parser.set_defaults(func=cmd_new)

    show_parser = sub.add_parser("show", help="Show session metadata")
    show_parser.add_argument("session_id")
    show_parser.set_defaults(func=cmd_show)

    rename_parser = sub.add_parser("rename", help="Rename a session")
    rename_parser.add_argument("session_id")
    rename_parser.add_argument("title", nargs="+")
    rename_parser.set_defaults(func=cmd_rename)

    delete_parser = sub.add_parser("delete", help="Delete a session")
    delete_parser.add_argument("session_id")
    delete_parser.set_defaults(func=cmd_delete)

    msg_parser = sub.add_parser("messages", help="Show session messages")
    msg_parser.add_argument("session_id")
    msg_parser.add_argument("-n", "--limit", type=int, default=50)
    msg_parser.set_defaults(func=cmd_messages)

    status_parser = sub.add_parser("status", help="Show session run status")
    status_parser.add_argument("session_id")
    status_parser.set_defaults(func=cmd_status)

    result_parser = sub.add_parser("result", help="Show final result summary")
    result_parser.add_argument("session_id")
    result_parser.set_defaults(func=cmd_result)

    run_parser = sub.add_parser("run", help="Start a task and stream progress")
    run_parser.add_argument("message", nargs="+")
    run_parser.add_argument("--title", default="")
    run_parser.add_argument("--work-root", "--project", dest="work_root", default="")
    run_parser.add_argument("--mode", default=DEFAULT_MODE)
    run_parser.add_argument("--model-id", dest="model_id", default=None, help="Override the resolved model (per-request switch)")
    run_parser.add_argument("--shallow-thinking", action="store_true", help="Enable prompt-based shallow thinking for this turn")
    run_parser.add_argument("--raw", action="store_true")
    run_parser.add_argument("--verbose", action="store_true", help="Show additional app-server details")
    run_parser.add_argument("--heartbeat-interval", type=int, default=30, help="Seconds between wait heartbeat lines")
    run_parser.add_argument("--interactive-decisions", action="store_true")
    run_parser.add_argument("--no-interactive-decisions", action="store_true")
    run_parser.set_defaults(func=cmd_run)

    resume_parser = sub.add_parser("resume", help="Send a follow-up to an existing task")
    resume_parser.add_argument("session_id")
    resume_parser.add_argument("message", nargs="+")
    resume_parser.add_argument("--work-root", "--project", dest="work_root", default="")
    resume_parser.add_argument("--mode", default=DEFAULT_MODE)
    resume_parser.add_argument("--shallow-thinking", action="store_true", help="Enable prompt-based shallow thinking for this turn")
    resume_parser.add_argument("--raw", action="store_true")
    resume_parser.add_argument("--verbose", action="store_true", help="Show additional app-server details")
    resume_parser.add_argument("--heartbeat-interval", type=int, default=30, help="Seconds between wait heartbeat lines")
    resume_parser.add_argument("--interactive-decisions", action="store_true")
    resume_parser.add_argument("--no-interactive-decisions", action="store_true")
    resume_parser.set_defaults(func=cmd_resume)

    watch_parser = sub.add_parser("watch", help="Watch a running task without sending a message")
    watch_parser.add_argument("session_id")
    watch_parser.add_argument("--raw", action="store_true")
    watch_parser.add_argument("--verbose", action="store_true", help="Show additional app-server details")
    watch_parser.add_argument("--heartbeat-interval", type=int, default=30, help="Seconds between wait heartbeat lines")
    watch_parser.set_defaults(func=cmd_watch)

    cancel_parser = sub.add_parser("cancel", help="Cancel a running session")
    cancel_parser.add_argument("session_id")
    cancel_parser.set_defaults(func=cmd_cancel)

    compact_parser = sub.add_parser("compact", help="Compact a session context")
    compact_parser.add_argument("session_id")
    compact_parser.add_argument("--work-root", "--project", dest="work_root", default="")
    compact_parser.add_argument("--verbose", action="store_true", help="Print the compacted summary")
    compact_parser.set_defaults(func=cmd_compact)

    open_change_file_parser = sub.add_parser("open-change-file", help="Open a changed file from a session")
    open_change_file_parser.add_argument("session_id")
    open_change_file_parser.add_argument("path")
    open_change_file_parser.set_defaults(func=cmd_open_change_file)

    return parser


async def _main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return await args.func(args)
    except aiohttp.ClientConnectorError as exc:
        raise CliError(f"Cannot connect to backend: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(_main(sys.argv[1:] if argv is None else argv))
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
