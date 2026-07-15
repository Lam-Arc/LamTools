from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from dataclasses import dataclass
from typing import Any

import aiohttp

from lamtools_core.app.cli_live import (
    CliLiveFormatter as CoreCliLiveFormatter,
    OutputChunk,
    approval_decision_from_reply as _approval_decision_from_reply,
    default_input_text as _input_text,
    default_label,
    event_request_id as _event_request_id,
    execute_compaction_command_live,
    format_compaction_result as _format_compaction_result,
    format_event as _format_event,
    is_done_event as _is_done_event,
    is_failed_event as _is_failed_event,
    is_resumed_event as _is_resumed_event,
    is_waiting_event as _is_waiting_event,
    shorten as _shorten,
    watch_live_events,
)
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


def _writer_label(tag: str, text: str, started_at: float) -> str:
    _ = TAG_TO_DISPLAY_GROUP.get(tag, "processed_flow")
    return default_label(tag, text, started_at)


class CliRunFormatter(CoreCliLiveFormatter):
    """Writer's display-group callback around the shared live formatter."""

    def __init__(self, *, verbose: bool = False, heartbeat_interval: int = 30) -> None:
        super().__init__(verbose=verbose, heartbeat_interval=heartbeat_interval, label=_writer_label)

    def _line(self, label: str, text: str = "") -> str:
        return self.line(label, text)

    def format(self, event: dict[str, Any]) -> list[str]:
        if str(event.get("event") or "") == "writer_error":
            return super().format({"event": "live_error", "data": event.get("data") or {}})
        return super().format(event)

    def format_chunks(self, event: dict[str, Any]) -> list[OutputChunk]:
        if str(event.get("event") or "") == "writer_error":
            return super().format_chunks({"event": "live_error", "data": event.get("data") or {}})
        return super().format_chunks(event)


def _write_live_chunk(chunk: OutputChunk) -> None:
    print(str(chunk), end=chunk.end, flush=chunk.flush)


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


async def cmd_project_list(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect()
        projects = await client.list_projects()
    print(json.dumps({"projects": projects}, ensure_ascii=False, sort_keys=True))
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
    formatter = CliRunFormatter(verbose=bool(args.verbose))
    result, saw_terminal = await execute_compaction_command_live(
        client_factory=lambda: AppServerClient(_base_url(args)),
        thread_id=args.session_id,
        work_root=args.work_root or "",
        formatter=formatter,
        output=_write_live_chunk,
    )
    if not saw_terminal:
        print(_format_compaction_result(result))
    if args.verbose and not saw_terminal and result.get("summary"):
        print()
        print(str(result.get("summary")))
    return 0


async def cmd_plugin_list(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect()
        result = await client.request("plugin.list", {})
    for plugin in result.get("plugins", []):
        if isinstance(plugin, dict):
            print(f"{plugin.get('name')} enabled={plugin.get('enabled')}")
    return 0


async def cmd_plugin_enable(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect()
        result = await client.request("plugin.enable", {"name": args.name})
    print(f"{result.get('name')} enabled")
    return 0


async def cmd_plugin_disable(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect()
        result = await client.request("plugin.disable", {"name": args.name})
    print(f"{result.get('name')} disabled")
    return 0


async def cmd_hook_list(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect()
        result = await client.request("hook.list", {})
    for hook in result.get("hooks", []):
        if isinstance(hook, dict):
            print(f"{hook.get('id')} {hook.get('event')} {hook.get('matcher')} trusted={hook.get('trusted')}")
    return 0


async def cmd_hook_trust(args: argparse.Namespace) -> int:
    async with AppServerClient(_base_url(args)) as client:
        await client.connect()
        result = await client.request("hook.trust", {"hook_id": args.hook_id})
    print(f"{result.get('hook_id')} trusted")
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
    client_message_id = str(uuid.uuid4())
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
    formatter = CliRunFormatter(
        verbose=bool(getattr(args, "verbose", False)),
        heartbeat_interval=int(getattr(args, "heartbeat_interval", 30) or 30),
    )

    async def start_turn(client: AppServerClient) -> None:
        await client.start_turn(
            thread_id=session_id,
            message=message,
            work_root=args.work_root or "",
            mode=args.mode,
            model_id=getattr(args, "model_id", None),
            shallow_thinking_enabled=bool(getattr(args, "shallow_thinking", False)),
            client_message_id=client_message_id,
        )

    approval = None
    approval_decision = None
    if getattr(args, "approval_decision", None):
        approval = lambda: args.approval_decision
        approval_decision = lambda value: value
    elif interactive:
        approval = lambda: _prompt_reply(args)
        approval_decision = _approval_decision_from_reply

    result = await watch_live_events(
        client_factory=lambda: AppServerClient(_base_url(args)),
        thread_id=session_id,
        formatter=formatter,
        output=_write_live_chunk,
        raw=bool(args.raw),
        approval=approval,
        approval_decision=approval_decision,
        on_connected=start_turn,
    )
    return result.exit_code


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
    if not args.raw:
        print(f"[session] {created['id']}")
    return await _stream_chat(args, created["id"], message)


async def cmd_resume(args: argparse.Namespace) -> int:
    return await _stream_chat(args, args.session_id, " ".join(args.message))


async def cmd_watch(args: argparse.Namespace) -> int:
    formatter = CliRunFormatter(
        verbose=bool(getattr(args, "verbose", False)),
        heartbeat_interval=int(getattr(args, "heartbeat_interval", 30) or 30),
    )
    if not args.raw:
        _write_live_chunk(OutputChunk(formatter.line("watch", args.session_id)))
    approval = None
    approval_decision = None
    if getattr(args, "approval_decision", None):
        approval = lambda: args.approval_decision
        approval_decision = lambda value: value
    elif getattr(args, "interactive_decisions", False) or (not args.raw and sys.stdin.isatty()):
        approval = lambda: _prompt_reply(args)
        approval_decision = _approval_decision_from_reply
    result = await watch_live_events(
        client_factory=lambda: AppServerClient(_base_url(args)),
        thread_id=args.session_id,
        formatter=formatter,
        output=_write_live_chunk,
        raw=bool(args.raw),
        approval=approval,
        approval_decision=approval_decision,
    )
    return result.exit_code


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
    project_sub.add_parser("list", help="List projects").set_defaults(func=cmd_project_list)
    project_pick = project_sub.add_parser("pick-directory", help="Open the local directory picker")
    project_pick.set_defaults(func=cmd_pick_directory)

    plugin_parser = sub.add_parser("plugin", help="Plugin utilities")
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_command", required=True)
    plugin_sub.add_parser("list", help="List plugins").set_defaults(func=cmd_plugin_list)
    plugin_enable = plugin_sub.add_parser("enable", help="Enable plugin")
    plugin_enable.add_argument("name")
    plugin_enable.set_defaults(func=cmd_plugin_enable)
    plugin_disable = plugin_sub.add_parser("disable", help="Disable plugin")
    plugin_disable.add_argument("name")
    plugin_disable.set_defaults(func=cmd_plugin_disable)

    hook_parser = sub.add_parser("hook", help="Hook utilities")
    hook_sub = hook_parser.add_subparsers(dest="hook_command", required=True)
    hook_sub.add_parser("list", help="List hooks").set_defaults(func=cmd_hook_list)
    hook_trust = hook_sub.add_parser("trust", help="Trust hook by id")
    hook_trust.add_argument("hook_id")
    hook_trust.set_defaults(func=cmd_hook_trust)

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
    run_parser.add_argument("--approval-decision", choices=("approve_once", "deny", "other_guidance"))
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
    resume_parser.add_argument("--approval-decision", choices=("approve_once", "deny", "other_guidance"))
    resume_parser.set_defaults(func=cmd_resume)

    watch_parser = sub.add_parser("watch", help="Watch a running task without sending a message")
    watch_parser.add_argument("session_id")
    watch_parser.add_argument("--raw", action="store_true")
    watch_parser.add_argument("--verbose", action="store_true", help="Show additional app-server details")
    watch_parser.add_argument("--heartbeat-interval", type=int, default=30, help="Seconds between wait heartbeat lines")
    watch_parser.add_argument("--interactive-decisions", action="store_true")
    watch_parser.add_argument("--approval-decision", choices=("approve_once", "deny", "other_guidance"))
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
