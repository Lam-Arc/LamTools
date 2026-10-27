"""Turns responsibilities."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import json
from typing import Any
from lamtools_core.app.cli_live import (
    CliLiveFormatter,
    OutputChunk,
    execute_compaction_command_live,
    format_compaction_result,
)
from lamtools_core.app.live_client import CoreAppServerClient


async def cmd_start(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    from .task import _watch_live_cli
    permission_preset = getattr(args, "permission_preset", None)
    legacy_approval_policy = getattr(args, "approval_policy", None)
    if permission_preset is None and legacy_approval_policy is None and bool(getattr(args, "auto_approve", False)):
        legacy_approval_policy = "auto_approve"

    async def start(client: CoreAppServerClient) -> dict[str, Any]:
        reasoning_level = getattr(args, "reasoning_level", None)
        if reasoning_level is None:
            reasoning_level = "high" if args.thinking == "enabled" else "off"
        params: dict[str, Any] = {
            "thread_id": args.thread_id,
            "input_items": [{"type": "text", "text": " ".join(args.message)}],
            "work_root": args.work_root,
            "model_id": args.model_id or None,
            "goal_id": args.goal_id or None,
            "reasoning_level": reasoning_level,
            "thinking_budget": args.thinking_budget,
            "shallow_thinking_enabled": bool(args.shallow),
            # Keep this legacy key in the Python call shape for compatibility;
            # CoreAppServerClient omits it from the wire when it is None.
            "approval_policy": legacy_approval_policy,
            "client_message_id": args.client_message_id or None,
        }
        if permission_preset is not None:
            params["permission_preset"] = permission_preset
        allow_outside = getattr(args, "allow_outside_workdir", None)
        if allow_outside is not None:
            params["allow_access_outside_workdir"] = bool(allow_outside)
        return await client.start_turn(**params)

    if args.watch:
        return await _watch_live_cli(args, thread_id=args.thread_id, on_connected=start)
    result = await _invoke_live(args, start)
    _print_live_result(args, result, f"started {args.thread_id}")
    return 0


async def cmd_resume_turn(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(args, lambda client: client.resume_turn(thread_id=args.thread_id, turn_id=args.turn_id))
    _print_live_result(args, result, f"resume requested {args.thread_id}")
    return 0


async def cmd_pause_turn(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(args, lambda client: client.pause_turn(thread_id=args.thread_id, turn_id=args.turn_id))
    _print_live_result(args, result, f"pause requested {args.thread_id}")
    return 0


async def cmd_terminate_turn(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(args, lambda client: client.terminate_turn(thread_id=args.thread_id, turn_id=args.turn_id))
    _print_live_result(args, result, f"terminate requested {args.thread_id}")
    return 0


async def cmd_cancel(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(args, lambda client: client.cancel_turn(thread_id=args.thread_id, turn_id=args.turn_id))
    _print_live_result(args, result, f"cancel requested {args.thread_id}")
    return 0


async def cmd_steer(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(
        args,
        lambda client: client.steer_turn(
            thread_id=args.thread_id,
            turn_id=args.turn_id,
            input_items=[{"type": "text", "text": " ".join(args.message)}],
        ),
    )
    _print_live_result(args, result, f"steered {args.thread_id}")
    return 0


def _format_process_row(item: dict[str, Any]) -> str:
    state = "running" if item.get("alive") else "exited"
    kind = "persistent" if item.get("persistent") else "turn-scoped"
    ownership = "" if item.get("owned") else " | not-owned (predates last restart)"
    return (
        f"pid {item.get('pid')} | {state} | {kind}{ownership} | "
        f"{item.get('command') or '<unknown command>'}"
    )


async def cmd_process_list(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    result = await _invoke_live(args, lambda client: client.request("process.list", {"thread_id": args.session_id}))
    if args.raw:
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    processes = result.get("processes") if isinstance(result, dict) else []
    if not processes:
        print("no registered background processes", flush=True)
        return 0
    for item in processes:
        if isinstance(item, dict):
            print(_format_process_row(item), flush=True)
    return 0


async def cmd_process_kill(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(
        args,
        lambda client: client.request("process.kill", {"thread_id": args.session_id, "pid": args.pid}),
    )
    _print_live_result(args, result, f"terminated pid {args.pid}")
    return 0


async def cmd_process_forget(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(
        args,
        lambda client: client.request("process.forget", {"thread_id": args.session_id, "pid": args.pid}),
    )
    removed = bool(result.get("removed")) if isinstance(result, dict) else False
    message = f"removed record for pid {args.pid}" if removed else f"no removable record for pid {args.pid}"
    _print_live_result(args, result, message)
    return 0


async def cmd_process_logs(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    result = await _invoke_live(
        args,
        lambda client: client.request(
            "process.log",
            {
                "thread_id": args.session_id,
                "pid": args.pid,
                "stream": args.stream,
                "max_bytes": args.max_bytes,
            },
        ),
    )
    if args.raw:
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    if not isinstance(result, dict) or result.get("missing"):
        print(f"(no log captured for pid {args.pid} {args.stream})", flush=True)
        return 0
    content = str(result.get("content") or "")
    if result.get("truncated"):
        print(f"[... truncated to the last {args.max_bytes} bytes ...]", flush=True)
    if content:
        print(content, flush=True)
    else:
        print("(log is empty)", flush=True)
    return 0


async def cmd_queue_create(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    permission_preset = getattr(args, "permission_preset", None)
    legacy_approval_policy = getattr(args, "approval_policy", None)
    if permission_preset is None and legacy_approval_policy is None and bool(getattr(args, "auto_approve", False)):
        legacy_approval_policy = "auto_approve"
    params: dict[str, Any] = {
        "thread_id": args.thread_id,
        "input_items": [{"type": "text", "text": " ".join(args.message)}],
    }
    if permission_preset is not None:
        params["permission_preset"] = permission_preset
    if legacy_approval_policy is not None:
        params["approval_policy"] = legacy_approval_policy
    allow_outside = getattr(args, "allow_outside_workdir", None)
    if allow_outside is not None:
        params["allow_access_outside_workdir"] = bool(allow_outside)
    result = await _invoke_live(
        args,
        lambda client: client.create_queue_input(**params),
    )
    _print_live_result(args, result, f"queued {args.thread_id}")
    return 0


async def cmd_queue_update(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(
        args,
        lambda client: client.update_queue_input(
            thread_id=args.thread_id,
            queue_item_id=args.queue_item_id,
            text=" ".join(args.message),
        ),
    )
    _print_live_result(args, result, f"updated queue item {args.queue_item_id}")
    return 0


async def cmd_queue_delete(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(
        args,
        lambda client: client.delete_queue_input(thread_id=args.thread_id, queue_item_id=args.queue_item_id),
    )
    _print_live_result(args, result, f"deleted queue item {args.queue_item_id}")
    return 0


async def cmd_queue_guide(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(
        args,
        lambda client: client.guide_queue_input(
            thread_id=args.thread_id,
            turn_id=args.turn_id,
            queue_item_id=args.queue_item_id,
            text=" ".join(args.message) or None,
        ),
    )
    _print_live_result(args, result, f"guided {args.thread_id}")
    return 0


async def cmd_approval_respond(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(
        args,
        lambda client: client.request(
            "approval.respond",
            {"thread_id": args.thread_id, "action": args.action, "response": " ".join(args.response)},
        ),
    )
    _print_live_result(args, result, f"approval {args.action} sent")
    return 0


async def cmd_command_catalog(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(
        args,
        lambda client: client.request("command.catalog", {"work_root": args.work_root}),
    )
    message = "\n".join(
        f"/{item['name']}\t{item.get('description', '')}"
        for item in result.get("commands", [])
        if isinstance(item, dict) and item.get("name")
    )
    _print_live_result(args, result, message)
    return 0


async def cmd_command_execute(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    if args.name == "compact":
        formatter = CliLiveFormatter()

        def output(chunk: OutputChunk) -> None:
            print(str(chunk), end=chunk.end, flush=chunk.flush)

        result, saw_terminal = await execute_compaction_command_live(
            client_factory=lambda: CoreAppServerClient(args.base_url, path=args.ws_path, token=args.token),
            thread_id=args.thread_id,
            work_root=args.work_root,
            formatter=formatter,
            output=output,
            raw=bool(args.raw),
        )
        if args.raw:
            print(json.dumps(result, ensure_ascii=False), flush=True)
        elif not saw_terminal:
            print(format_compaction_result(result), flush=True)
        return 0
    result = await _invoke_live(
        args,
        lambda client: client.request(
            "command.execute",
            {
                "thread_id": args.thread_id,
                "command": args.name,
                "arguments": " ".join(args.arguments).strip(),
                "work_root": args.work_root,
            },
        ),
    )
    _print_live_result(args, result, f"/{args.name} completed for {args.thread_id}")
    return 0
