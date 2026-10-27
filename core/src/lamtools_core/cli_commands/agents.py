"""Arrange, sub-agent lifecycle, roles and strategy commands."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from lamtools_core.app.live_client import CoreAppServerClient


async def cmd_arrange_create(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    trigger: dict[str, Any] = {}
    if args.trigger_once:
        trigger = {"type": "once", "local_at": args.trigger_once, "timezone": args.timezone}
    elif args.trigger_daily:
        trigger = {"type": "calendar", "frequency": "daily", "time": args.trigger_daily, "timezone": args.timezone}
    elif args.trigger_monthly:
        parts = args.trigger_monthly.split(":", 1)
        day = int(parts[0])
        time_val = parts[1] if len(parts) > 1 else "09:00"
        trigger = {"type": "calendar", "frequency": "monthly", "day": day, "time": time_val, "timezone": args.timezone}
    elif args.trigger_event:
        trigger = {"type": "event", "event_type": args.trigger_event}
    else:
        trigger = {"type": "once", "local_at": "", "timezone": args.timezone}
    thread_id = str(args.thread_id or "").strip()
    if not thread_id:
        thread_id = args.work_root  # fallback: use work_root as source_thread_id
    payload = {
        "work_root": args.work_root,
        "thread_id": thread_id,
        "kind": args.kind,
        "operation": "turn.start",
        "payload": {"message": " ".join(args.message)},
        "trigger": trigger,
        "title": str(args.title or "").strip(),
        "session_strategy": args.session_strategy,
        "model_id": str(args.model_id or "").strip(),
    }
    if args.max_runs is not None:
        payload["max_runs"] = args.max_runs
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("arrange.create", payload)
    result = await _invoke_live(args, op)
    job = result.get("job", {}) if isinstance(result, dict) else {}
    jid = str(job.get("id") or job.get("job_id") or "")
    print(f"[arrange] {jid}")
    if not args.raw:
        instruction = " ".join(args.message)
        print(f"  instruction: {instruction}")
        print(f"  trigger: {json.dumps(trigger, ensure_ascii=False)}")
    return 0


async def cmd_arrange_list(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    params: dict[str, Any] = {}
    work_root = str(args.work_root or "").strip()
    if work_root:
        params["work_root"] = work_root
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("arrange.list", params)
    result = await _invoke_live(args, op)
    jobs = result.get("jobs", []) if isinstance(result, dict) else []
    if isinstance(jobs, list):
        for j in jobs:
            if isinstance(j, dict):
                sid = str(j.get("id") or j.get("job_id") or "")[:16]
                msg = str((j.get("payload") or {}).get("message") or "?")[:80]
                st = str(j.get("status") or "?")
                print(f"{sid}  {st:12s} {msg}")
    return 0


async def cmd_arrange_show(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("arrange.get", {"job_id": args.job_id})
    result = await _invoke_live(args, op)
    job = result.get("job", {}) if isinstance(result, dict) else {}
    if isinstance(job, dict):
        for k in ("id", "thread_id", "kind", "status", "run_count", "last_error", "next_run_at", "created_at", "updated_at"):
            v = job.get(k)
            if v is not None:
                print(f"  {k}: {v}")
        trigger = job.get("trigger", {})
        if isinstance(trigger, dict) and trigger:
            print(f"  trigger: {json.dumps(trigger, ensure_ascii=False)}")
        payload = job.get("payload", {})
        if isinstance(payload, dict):
            msg = payload.get("message", "")
            if msg:
                print(f"  message: {msg}")
    return 0


async def cmd_arrange_update(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    if not args.status:
        print("error: --status is required (scheduled/paused/cancelled)", file=sys.stderr)
        return 1
    operation = {"scheduled": "arrange.resume", "paused": "arrange.pause", "cancelled": "arrange.cancel"}.get(args.status, "")
    if not operation:
        print(f"error: unsupported status '{args.status}' (use scheduled/paused/cancelled)", file=sys.stderr)
        return 1
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request(operation, {"job_id": args.job_id})
    result = await _invoke_live(args, op)
    job = result.get("job", {}) if isinstance(result, dict) else {}
    print(f"[arrange] {str(job.get('id') or args.job_id)} status={args.status}")
    return 0


async def cmd_arrange_edit(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    payload: dict[str, Any] = {"job_id": args.job_id}
    if args.title:
        payload["title"] = args.title
    if args.instruction:
        payload["instruction"] = args.instruction
    if args.session_strategy:
        payload["session_strategy"] = args.session_strategy
    if args.model_id:
        payload["model_id"] = args.model_id
    if args.trigger_once:
        payload["trigger"] = {"type": "once", "local_at": args.trigger_once, "timezone": args.timezone}
    elif args.trigger_daily:
        payload["trigger"] = {"type": "calendar", "frequency": "daily", "time": args.trigger_daily, "timezone": args.timezone}
    elif args.trigger_monthly:
        parts = args.trigger_monthly.split(":", 1)
        day = int(parts[0])
        time_val = parts[1] if len(parts) > 1 else "09:00"
        payload["trigger"] = {"type": "calendar", "frequency": "monthly", "day": day, "time": time_val, "timezone": args.timezone}
    elif args.trigger_event:
        payload["trigger"] = {"type": "event", "event_type": args.trigger_event}
    if len(payload) <= 1:
        print("error: no fields to update", file=sys.stderr)
        return 1
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("arrange.update", payload)
    result = await _invoke_live(args, op)
    job = result.get("job", {}) if isinstance(result, dict) else {}
    jid = str(job.get("id") or args.job_id)
    print(f"[arrange] {jid} updated")
    return 0


async def cmd_subagent_lifecycle(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    command = str(args.subagent_command)
    payload: dict[str, Any] = {"thread_id": args.thread_id}
    if command not in {"list", "interrupt", "pause", "resume"}:
        payload.update({"type": args.type, "name": args.name})
    if command in {"create", "close"}:
        payload.update({"model": args.model, "reasoning_level": args.reasoning_level})
    if command == "message":
        payload["prompt"] = args.prompt
    result = await _invoke_live(
        args, lambda client: client.request(f"sub_agent.{command}", payload)
    )
    if args.raw:
        print(json.dumps(result, ensure_ascii=False), flush=True)
    elif command == "list":
        for item in result.get("items", []):
            print(
                f"{item.get('name')} {item.get('type')} {item.get('status')} "
                f"{item.get('model_id')} {item.get('reasoning_level')}", flush=True
            )
    else:
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


async def cmd_subagent_guide_show(args: argparse.Namespace) -> int:
    from lamtools_core.config.subagent_prompt import (
        DEFAULT_SUBAGENT_GUIDE,
        load_subagent_guide,
        resolve_subagent_guide_path,
    )

    work_root = str(args.work_root or "").strip() or None
    if args.scope == "project" and not work_root:
        print("error: --work-root is required for --scope project", file=sys.stderr)
        return 1
    if args.scope:
        from lamtools_core.config.subagent_prompt import subagent_guide_dirs

        dirs = subagent_guide_dirs(work_root)
        path = dirs[0] / "guide.md" if args.scope == "project" and dirs else (dirs[-1] / "guide.md" if dirs else None)
        if path is None or not path.is_file():
            print(f"[subagent] no {args.scope} guide configured; builtin shown below:")
            print(DEFAULT_SUBAGENT_GUIDE)
            return 0
        print(path.read_text(encoding="utf-8"))
        return 0
    resolved = resolve_subagent_guide_path(work_root)
    content = load_subagent_guide(work_root)
    if resolved is None:
        print("[subagent] no project/global guide configured; builtin shown below:")
    else:
        print(f"[subagent] guide from {resolved}")
    print(content)
    return 0


async def cmd_subagent_guide_set(args: argparse.Namespace) -> int:
    from lamtools_core.config.subagent_prompt import write_subagent_guide

    work_root = str(args.work_root or "").strip() or None
    if args.scope == "project" and not work_root:
        print("error: --work-root is required for --scope project", file=sys.stderr)
        return 1
    if args.source_file == "-":
        content = sys.stdin.read()
    else:
        content = Path(args.source_file).read_text(encoding="utf-8")
    path = write_subagent_guide(content, scope=args.scope, work_root=work_root)
    print(f"[subagent] guide written to {path} (scope={args.scope})")
    return 0


async def cmd_subagent_guide_edit(args: argparse.Namespace) -> int:
    from lamtools_core.config.subagent_prompt import guide_path_for_scope

    work_root = str(args.work_root or "").strip() or None
    if args.scope == "project" and not work_root:
        print("error: --work-root is required for --scope project", file=sys.stderr)
        return 1
    path = guide_path_for_scope(args.scope, work_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        from lamtools_core.config.subagent_prompt import DEFAULT_SUBAGENT_GUIDE

        path.write_text(DEFAULT_SUBAGENT_GUIDE, encoding="utf-8")
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        print("error: $EDITOR (or $VISUAL) is not set", file=sys.stderr)
        return 1
    import shutil
    import subprocess

    exe = shutil.which(editor) or editor
    subprocess.run([exe, str(path)], check=False)
    print(f"[subagent] edited {path} (scope={args.scope})")
    return 0


def _subagent_roles_require_project_root(args: argparse.Namespace) -> bool:
    args.work_root = str(args.work_root or "").strip()
    if args.scope == "project" and not args.work_root:
        print("error: --work-root is required for --scope project", file=sys.stderr)
        return False
    return True


async def cmd_subagent_roles_show(args: argparse.Namespace) -> int:
    from lamtools_core.config.subagent_prompt import (
        ROLE_ASSIGNMENTS_KEY,
        load_effective_role_assignments,
        load_local_subagent_settings,
        normalize_role_assignments,
    )

    if not _subagent_roles_require_project_root(args):
        return 1
    work_root = str(args.work_root or "").strip() or None
    try:
        if args.scope == "effective":
            roles = load_effective_role_assignments(work_root)
        else:
            settings = load_local_subagent_settings(args.scope, work_root)
            roles = normalize_role_assignments(settings.get(ROLE_ASSIGNMENTS_KEY, []))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"scope": args.scope, "role_assignments": roles},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


async def cmd_subagent_roles_set(args: argparse.Namespace) -> int:
    from lamtools_core.config.subagent_prompt import (
        ROLE_ASSIGNMENTS_KEY,
        load_local_subagent_settings,
        normalize_role_assignment,
        normalize_role_assignments,
        write_subagent_settings,
    )

    if not _subagent_roles_require_project_root(args):
        return 1
    work_root = str(args.work_root or "").strip() or None
    try:
        rule = normalize_role_assignment(
            {
                "task_type": args.task_type,
                "type": args.type,
                "model": args.model,
                "reasoning_min": args.reasoning_min,
                "reasoning_max": args.reasoning_max,
            }
        )
        local = load_local_subagent_settings(args.scope, work_root)
        roles = normalize_role_assignments(local.get(ROLE_ASSIGNMENTS_KEY, []))
        key = rule["task_type"].strip().casefold()
        for index, current in enumerate(roles):
            if current["task_type"].strip().casefold() == key:
                roles[index] = rule
                break
        else:
            roles.append(rule)
        path = write_subagent_settings(
            {ROLE_ASSIGNMENTS_KEY: roles},
            scope=args.scope,
            work_root=work_root,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"scope": args.scope, "path": str(path), "role_assignment": rule},
            ensure_ascii=False,
        )
    )
    return 0


async def cmd_subagent_roles_delete(args: argparse.Namespace) -> int:
    from lamtools_core.config.subagent_prompt import (
        ROLE_ASSIGNMENTS_KEY,
        load_local_subagent_settings,
        normalize_role_assignments,
        write_subagent_settings,
    )

    if not _subagent_roles_require_project_root(args):
        return 1
    work_root = args.work_root or None
    key = str(args.task_type or "").strip().casefold()
    if not key:
        print("error: task_type must not be empty", file=sys.stderr)
        return 1
    try:
        local = load_local_subagent_settings(args.scope, work_root)
        roles = normalize_role_assignments(local.get(ROLE_ASSIGNMENTS_KEY, []))
        remaining = [
            rule
            for rule in roles
            if rule["task_type"].strip().casefold() != key
        ]
        deleted = len(remaining) != len(roles)
        path = write_subagent_settings(
            {ROLE_ASSIGNMENTS_KEY: remaining},
            scope=args.scope,
            work_root=work_root,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"scope": args.scope, "path": str(path), "deleted": deleted},
            ensure_ascii=False,
        )
    )
    return 0


async def cmd_subagent_strategy_show(args: argparse.Namespace) -> int:
    from lamtools_core.config.subagent_prompt import (
        DELEGATION_STRATEGY_KEY,
        load_effective_delegation_strategy,
        load_global_delegation_strategy,
        load_local_subagent_settings,
        normalize_delegation_strategy,
    )

    if not _subagent_roles_require_project_root(args):
        return 1
    work_root = args.work_root or None
    effective = load_effective_delegation_strategy(work_root)
    global_strategy = load_global_delegation_strategy()
    local_strategy: str | None = None
    inherited = False
    if args.scope in {"global", "project"}:
        local = load_local_subagent_settings(args.scope, work_root)
        inherited = DELEGATION_STRATEGY_KEY not in local
        if not inherited:
            try:
                local_strategy = normalize_delegation_strategy(
                    local[DELEGATION_STRATEGY_KEY]
                )
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
    print(
        json.dumps(
            {
                "scope": args.scope,
                "delegation_strategy": local_strategy if args.scope != "effective" else effective,
                "effective_delegation_strategy": effective,
                "global_delegation_strategy": global_strategy,
                "delegation_strategy_inherited": inherited,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


async def cmd_subagent_strategy_set(args: argparse.Namespace) -> int:
    from lamtools_core.config.subagent_prompt import (
        DELEGATION_STRATEGY_KEY,
        normalize_delegation_strategy,
        write_subagent_settings,
    )

    if not _subagent_roles_require_project_root(args):
        return 1
    try:
        strategy = normalize_delegation_strategy(args.strategy)
        path = write_subagent_settings(
            {DELEGATION_STRATEGY_KEY: strategy},
            scope=args.scope,
            work_root=args.work_root or None,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"scope": args.scope, "path": str(path), "delegation_strategy": strategy},
            ensure_ascii=False,
        )
    )
    return 0


async def cmd_subagent_strategy_unset(args: argparse.Namespace) -> int:
    from lamtools_core.config.subagent_prompt import (
        DELEGATION_STRATEGY_KEY,
        write_subagent_settings,
    )

    if not _subagent_roles_require_project_root(args):
        return 1
    try:
        path = write_subagent_settings(
            {DELEGATION_STRATEGY_KEY: None},
            scope=args.scope,
            work_root=args.work_root or None,
        )
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"scope": args.scope, "path": str(path), "delegation_strategy": None},
            ensure_ascii=False,
        )
    )
    return 0
