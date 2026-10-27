"""Session browsing, checkpoints, rollback and export commands."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import json
from pathlib import Path
from typing import Any
from lamtools_core.app.core_db import list_core_sessions, open_core_app_db, show_core_session
from lamtools_core.app.live_client import CoreAppServerClient
from lamtools_core.export import ConversationExportService
from lamtools_core.export.serializers import (
    full_to_zip,
    to_json,
    transcript_to_jsonl,
    transcript_to_markdown,
    transcript_to_text,
)


async def cmd_session_list(args: argparse.Namespace) -> int:
    sessions = await list_core_cli_sessions(core_db=args.core_db or None)
    if args.raw:
        print(json.dumps({"sessions": sessions}, ensure_ascii=False, indent=2), flush=True)
    else:
        for session in sessions:
            print(
                f"{session['thread_id']} {session.get('status') or '-'} "
                f"seq={session.get('snapshot_seq') or 0} updated={session.get('updated_at') or '-'}",
                flush=True,
            )
    return 0


async def cmd_session_checkpoints(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(
        args,
        lambda client: client.request(
            "session.checkpoints.list",
            {"session_id": args.thread_id},
        ),
    )
    message = "\n".join(
        f"{item.get('id', '-')} {item.get('actor_kind', '-')} turn={item.get('turn_id', '-')}"
        for item in result.get("checkpoints", [])
        if isinstance(item, dict)
    )
    _print_live_result(args, result, message)
    return 0


async def cmd_session_rollback(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    payload = {"session_id": args.thread_id}
    if args.turn_id:
        payload["turn_id"] = args.turn_id
    elif args.checkpoint_id:
        payload["checkpoint_id"] = args.checkpoint_id
    else:
        raise ValueError("rollback requires a checkpoint_id or --turn-id")
    result = await _invoke_live(
        args,
        lambda client: client.request(
            "session.rollback",
            payload,
        ),
    )
    _print_live_result(args, result, f"rollback {result.get('status', '-')} ({result.get('operation_id', '-')})")
    return 0


async def cmd_session_fork(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    payload = {"session_id": args.thread_id}
    if args.turn_id:
        payload["turn_id"] = args.turn_id
    elif args.checkpoint_id:
        payload["checkpoint_id"] = args.checkpoint_id
    else:
        raise ValueError("fork requires a checkpoint_id or --turn-id")
    result = await _invoke_live(
        args,
        lambda client: client.request(
            "session.fork",
            payload,
        ),
    )
    _print_live_result(args, result, f"fork {result.get('status', '-')} ({result.get('session_id', '-')})")
    return 0


async def cmd_session_permissions(args: argparse.Namespace) -> int:
    from .connection import _print_live_result
    client = CoreAppServerClient(args.base_url, path=args.ws_path, token=args.token)
    try:
        await client.connect(thread_id=args.thread_id)
        result = await client.request(
            "session.permissions.set",
            {
                "thread_id": args.thread_id,
                "permission_preset": args.approval,
            },
        )
    finally:
        await client.close()
    _print_live_result(
        args,
        result,
        f"session {args.thread_id} approval={result.get('permission_preset', args.approval)}",
    )
    return 0


async def cmd_session_show(args: argparse.Namespace) -> int:
    detail = await show_core_cli_session(args.thread_id, core_db=args.core_db or None)
    if args.raw:
        print(json.dumps(detail, ensure_ascii=False, indent=2), flush=True)
    else:
        snapshot = detail.get("snapshot") if isinstance(detail.get("snapshot"), dict) else {}
        print(f"[session] {detail['thread_id']}", flush=True)
        print(f"[status] {snapshot.get('status') or '-'} seq={snapshot.get('snapshot_seq') or 0}", flush=True)
        print(f"[events] {len(detail.get('events') or [])}", flush=True)
    return 0


async def cmd_session_outline(args: argparse.Namespace) -> int:
    from .connection import _invoke_live, _print_live_result
    result = await _invoke_live(
        args,
        lambda client: client.request(
            "thread.outline",
            {"thread_id": args.thread_id},
        ),
    )
    items = result.get("items") if isinstance(result.get("items"), list) else []
    lines = [f"[session outline] {args.thread_id} ({len(items)} messages)"]
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        timestamp = str(item.get("timestamp") or "-")
        turn_id = str(item.get("turn_id") or "-")
        prompt = " ".join(str(item.get("prompt") or "").split()) or "-"
        response = " ".join(str(item.get("response_excerpt") or "").split()) or "-"
        lines.append(
            f"{index}. seq={item.get('seq', '-')} turn={turn_id} time={timestamp} "
            f"{prompt} -> {response}"
        )
    _print_live_result(args, result, "\n".join(lines))
    return 0


async def cmd_session_export(args: argparse.Namespace) -> int:
    from .config import _resolve_core_db
    mode = str(getattr(args, "mode", "") or "").strip().lower()
    output_format = str(getattr(args, "format", "") or "").strip().lower()
    if not mode:
        # Keep old scripts working while making --mode the explicit public
        # spelling for the three export tiers.
        mode = "full" if output_format == "zip" else "transcript"
    if mode == "transcript":
        if output_format in {"", "md"}:
            output_format = "markdown"
        elif output_format == "json":
            raise ValueError("Transcript JSON is no longer supported; use --format jsonl")
        elif output_format not in {"markdown", "txt", "jsonl"}:
            raise ValueError("Transcript export requires --format markdown, txt, or jsonl")
    elif mode == "handoff":
        if output_format not in {"", "json"}:
            raise ValueError("Handoff export only supports JSON")
        output_format = "json"
    elif mode == "full":
        if output_format not in {"", "zip"}:
            raise ValueError("Full Archive export only supports ZIP")
        output_format = "zip"
    else:
        raise ValueError(f"Unsupported session export mode: {mode}")
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        service = ConversationExportService(
            db.session_factory,
            handoff_context_store=db.handoff_context_store,
        )
        if mode == "transcript" and output_format == "markdown":
            payload: str | bytes = transcript_to_markdown(await service.transcript(args.thread_id))
        elif mode == "transcript" and output_format == "txt":
            payload = transcript_to_text(await service.transcript(args.thread_id))
        elif mode == "transcript" and output_format == "jsonl":
            payload = transcript_to_jsonl(await service.transcript(args.thread_id))
        elif mode == "handoff":
            payload = to_json(await service.handoff(args.thread_id)) + "\n"
        elif mode == "full" and output_format == "zip":
            payload = full_to_zip(await service.full(args.thread_id))
        else:
            raise ValueError(f"Unsupported session export mode/format: {mode}/{output_format}")

        destination = str(args.output or "").strip()
        if destination and destination != "-":
            path = Path(destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(payload, bytes):
                path.write_bytes(payload)
            else:
                path.write_text(payload, encoding="utf-8")
            print(f"[session export] {path}", flush=True)
            return 0

        if isinstance(payload, bytes):
            raise ValueError("Full Archive ZIP requires --output PATH")
        print(payload, end="" if payload.endswith("\n") else "\n", flush=True)
        return 0
    finally:
        await db.close()


async def list_core_cli_sessions(*, core_db: Path | str | None = None) -> list[dict[str, Any]]:
    from .config import _resolve_core_db
    db = await open_core_app_db(_resolve_core_db(core_db))
    try:
        return await list_core_sessions(db)
    finally:
        await db.close()


async def show_core_cli_session(thread_id: str, *, core_db: Path | str | None = None) -> dict[str, Any]:
    from .config import _resolve_core_db
    db = await open_core_app_db(_resolve_core_db(core_db))
    try:
        return await show_core_session(db, thread_id)
    finally:
        await db.close()
