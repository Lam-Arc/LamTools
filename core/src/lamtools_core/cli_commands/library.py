"""Project, goal and plan-library command handlers."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.app.live_client import CoreAppServerClient


def _print_project_result(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


async def cmd_project_list(args: argparse.Namespace) -> int:
    from .config import _resolve_core_db
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        _print_project_result({"projects": [project.to_dict() for project in await db.project_store.list()]})
    finally:
        await db.close()
    return 0


async def cmd_project_create(args: argparse.Namespace) -> int:
    from .config import _resolve_core_db
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        project, session, created = await db.project_store.create_with_initial_session(
            args.work_root,
            name=args.name,
            icon_key=args.icon_key,
            color_key=args.color_key,
        )
        _print_project_result({"created": created, "project": project.to_dict(), "session": session.to_dict()})
    finally:
        await db.close()
    return 0


async def cmd_project_show(args: argparse.Namespace) -> int:
    from .config import _resolve_core_db
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        project = await db.project_store.get(args.project_id)
        if project is None:
            raise RuntimeError("Project not found")
        _print_project_result({"project": project.to_dict()})
    finally:
        await db.close()
    return 0


async def cmd_project_rename(args: argparse.Namespace) -> int:
    from .config import _resolve_core_db
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        project = await db.project_store.rename(args.project_id, args.name)
        if project is None:
            raise RuntimeError("Project not found")
        _print_project_result({"project": project.to_dict()})
    finally:
        await db.close()
    return 0


async def cmd_project_update(args: argparse.Namespace) -> int:
    from .config import _resolve_core_db
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        project = await db.project_store.update(
            args.project_id,
            name=args.name,
            icon_key=args.icon_key,
            color_key=args.color_key,
        )
        if project is None:
            raise RuntimeError("Project not found")
        _print_project_result({"project": project.to_dict()})
    finally:
        await db.close()
    return 0


async def cmd_project_delete(args: argparse.Namespace) -> int:
    from .config import _resolve_core_db
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        if not await db.project_store.delete_with_sessions(args.project_id):
            raise RuntimeError("Project not found")
        _print_project_result({"deleted": True, "project_id": args.project_id})
    finally:
        await db.close()
    return 0


async def cmd_project_agents_get(args: argparse.Namespace) -> int:
    from .config import _resolve_core_db
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        agents_md = await db.project_store.read_agents_md(args.project_id)
        if agents_md is None:
            raise RuntimeError("Project not found")
        _print_project_result({"agents_md": agents_md})
    finally:
        await db.close()
    return 0


async def cmd_project_agents_set(args: argparse.Namespace) -> int:
    from .config import _resolve_core_db
    content = Path(args.source_file).read_text(encoding="utf-8")
    db = await open_core_app_db(_resolve_core_db(args.core_db or None))
    try:
        agents_md = await db.project_store.write_agents_md(args.project_id, content)
        if agents_md is None:
            raise RuntimeError("Project not found")
        _print_project_result({"agents_md": agents_md})
    finally:
        await db.close()
    return 0


async def cmd_goal_create(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("goal.create", {"thread_id": args.thread_id, "objective": " ".join(args.objective)})
    result = await _invoke_live(args, op)
    goal = result.get("goal", {}) if isinstance(result, dict) else {}
    gid = str(goal.get("id") or goal.get("goal_id") or "")
    print(f"[goal] {gid}")
    if not args.raw:
        obj = str(goal.get("objective") or " ".join(args.objective))
        print(f"  objective: {obj}")
    return 0


async def cmd_goal_list(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("goal.list", {})
    result = await _invoke_live(args, op)
    goals = result.get("goals", []) if isinstance(result, dict) else []
    if isinstance(goals, list):
        for g in goals:
            if isinstance(g, dict):
                sid = str(g.get("id") or g.get("goal_id") or "")[:16]
                obj = str(g.get("objective") or "")[:80]
                st = str(g.get("status") or "?")
                print(f"{sid}  {st:12s} {obj}")
    return 0


async def cmd_goal_show(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("goal.get", {"goal_id": args.goal_id})
    result = await _invoke_live(args, op)
    goal = result.get("goal", {}) if isinstance(result, dict) else {}
    if isinstance(goal, dict):
        for k in ("id", "objective", "status", "created_at"):
            v = goal.get(k)
            if v is not None:
                print(f"  {k}: {v}")
    return 0


async def cmd_goal_update(args: argparse.Namespace) -> int:
    from .connection import _invoke_live
    if not args.status:
        print("error: --status is required (active/blocked/archived)", file=sys.stderr)
        return 1
    async def op(client: CoreAppServerClient) -> dict[str, Any]:
        return await client.request("goal.update", {"goal_id": args.goal_id, "status": args.status})
    result = await _invoke_live(args, op)
    goal = result.get("goal", {}) if isinstance(result, dict) else {}
    print(f"[goal] {str(goal.get('id') or args.goal_id)} status={args.status}")
    return 0


def _plan_library_path(work_root: str, name: str) -> Path | None:
    """A plan file inside 方案/, refusing anything that climbs out of it.

    Accepts the bare name (``导出显示进度.md``), a path relative to the library
    (``归档/导出显示进度.md``) and the full library path the scan reports
    (``方案/归档/导出显示进度.md``) — the same spellings ``rename`` / ``move``
    already take.
    """
    from lamtools_core.app.plan_library import PLAN_LIBRARY_DIRNAME, plan_library_root

    root = plan_library_root(work_root).resolve()
    cleaned = (name or "").strip().replace("\\", "/").strip("/")
    prefix = f"{PLAN_LIBRARY_DIRNAME}/"
    if cleaned.startswith(prefix):
        cleaned = cleaned[len(prefix):]
    if not cleaned:
        return None
    target = (root / cleaned).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


async def cmd_plan_library_list(args: argparse.Namespace) -> int:
    from lamtools_core.app.plan_library import scan_plan_library

    entries = scan_plan_library(args.work_root)
    if not entries:
        print(f"[plan-library] no plans in {args.work_root}/方案")
        return 0
    for entry in entries:
        print(f"[plan-library] {entry['status']:9} {entry['path']}  {entry['title']}")
    return 0


async def cmd_plan_library_show(args: argparse.Namespace) -> int:
    path = _plan_library_path(args.work_root, args.name)
    if path is None:
        print("error: name escapes the plan library", file=sys.stderr)
        return 1
    if not path.is_file():
        print(f"error: plan not found: {args.name}", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"), end="")
    return 0


async def cmd_plan_library_delete(args: argparse.Namespace) -> int:
    path = _plan_library_path(args.work_root, args.name)
    if path is None:
        print("error: name escapes the plan library", file=sys.stderr)
        return 1
    if not path.is_file():
        print(f"error: plan not found: {args.name}", file=sys.stderr)
        return 1
    path.unlink()
    print(f"[plan-library] deleted {args.name}")
    return 0


def _plan_library_command_error(cause: Exception) -> int:
    print(f"error: {cause}", file=sys.stderr)
    return 1


async def cmd_plan_library_create(args: argparse.Namespace) -> int:
    from lamtools_core.app.plan_library import PlanLibraryError, create_plan

    try:
        entry = create_plan(args.work_root, args.name, folder=args.folder)
    except PlanLibraryError as cause:
        return _plan_library_command_error(cause)
    print(f"[plan-library] created {entry['path']}")
    return 0


async def cmd_plan_library_folder(args: argparse.Namespace) -> int:
    from lamtools_core.app.plan_library import PlanLibraryError, create_folder

    try:
        folder = create_folder(args.work_root, args.path)
    except PlanLibraryError as cause:
        return _plan_library_command_error(cause)
    print(f"[plan-library] created folder {folder['path']}")
    return 0


async def cmd_plan_library_rename(args: argparse.Namespace) -> int:
    from lamtools_core.app.plan_library import PlanLibraryError, rename_plan

    try:
        entry = rename_plan(args.work_root, args.path, args.new_name)
    except PlanLibraryError as cause:
        return _plan_library_command_error(cause)
    print(f"[plan-library] renamed to {entry['path']}")
    return 0


async def cmd_plan_library_move(args: argparse.Namespace) -> int:
    from lamtools_core.app.plan_library import PlanLibraryError, move_plan

    try:
        entry = move_plan(args.work_root, args.path, folder=args.folder)
    except PlanLibraryError as cause:
        return _plan_library_command_error(cause)
    print(f"[plan-library] moved to {entry['path']}")
    return 0


async def cmd_plan_library_favorite(args: argparse.Namespace) -> int:
    from lamtools_core.app.plan_library import PlanLibraryError, set_plan_favorite

    try:
        entry = set_plan_favorite(args.work_root, args.path, favorite=not args.off)
    except PlanLibraryError as cause:
        return _plan_library_command_error(cause)
    print(f"[plan-library] favorite={'on' if entry['favorite'] else 'off'} {entry['path']}")
    return 0
