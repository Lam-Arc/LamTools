"""Attachment, artifact, memory and tool-set command handlers."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import argparse
import httpx
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote
from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.config.network import httpx_client_kwargs


async def cmd_attachment_upload(args: argparse.Namespace) -> int:
    from .connection import _print_live_result
    path = Path(args.file).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Attachment file not found: {path}")
    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    upload_url = f"{args.base_url.rstrip('/')}/api/core/sessions/{quote(args.thread_id, safe='')}/attachments"
    async with httpx.AsyncClient(
        timeout=60.0,
        headers=headers,
        **httpx_client_kwargs(upload_url),
    ) as client:
        with path.open("rb") as stream:
            response = await client.post(
                upload_url,
                files={"file": (path.name, stream)},
            )
        response.raise_for_status()
        result = response.json()
    _print_live_result(args, result, f"uploaded {path.name} ({result.get('id', '-')})")
    return 0


def _artifact_work_root(args: argparse.Namespace) -> str:
    return str(getattr(args, "work_root", "") or "")


async def _artifact_store_for_cli(args: argparse.Namespace) -> tuple[Any, Any, Path]:
    from .config import _resolve_core_db
    root = Path(_artifact_work_root(args) or Path.cwd()).resolve()
    db = await open_core_app_db(_resolve_core_db(getattr(args, "core_db", "") or None))
    project = next((item for item in await db.project_store.list() if Path(item.work_root).resolve() == root), None)
    if project is None:
        await db.close()
        raise LookupError(f"Project not found for work_root: {root}")
    await db.artifact_store.migrate_legacy(project_id=project.id, work_root=root)
    return db, project, root


def _format_artifact(record: Any, *, with_prompt: bool = False) -> str:
    marker = "🗑" if record.deleted else ("🧊" if record.source == "user_upload" else "✨")
    line = (
        f"{marker} {record.artifact_id[:8]}  {record.kind:<8} {record.name}  "
        f"[{record.source}] {record.created_at or '-'}"
    )
    if record.parent_ids:
        line += f"  parents={','.join(p[:8] for p in record.parent_ids)}"
    if with_prompt and record.prompt:
        line += f"\n    prompt: {record.prompt[:200]}"
    return line


async def cmd_artifact_list(args: argparse.Namespace) -> int:
    try:
        db, project, root = await _artifact_store_for_cli(args)
    except LookupError as exc:
        print(f"[artifact] {exc}", file=sys.stderr)
        return 1
    try:
        records = await db.artifact_store.list(project.id, include_deleted=bool(args.include_deleted))
        print(f"[artifact] {len(records)} 个（{root}）")
        for record in records:
            print(_format_artifact(record, with_prompt=True))
        return 0
    finally:
        await db.close()


async def cmd_artifact_show(args: argparse.Namespace) -> int:
    try:
        db, project, _root = await _artifact_store_for_cli(args)
    except LookupError as exc:
        print(f"[artifact] {exc}", file=sys.stderr)
        return 1
    try:
        record = await db.artifact_store.get(args.artifact_id)
        if record is None or record.project_id != project.id:
            print(f"[artifact] not found: {args.artifact_id}", file=sys.stderr)
            return 1
        for key in ("artifact_id", "kind", "mime_type", "name", "path", "source", "role", "availability", "created_at", "deleted"):
            print(f"{key}: {getattr(record, key)}")
        return 0
    finally:
        await db.close()


async def cmd_artifact_open(args: argparse.Namespace) -> int:
    from lamtools_core.attachment import open_with_default_app

    try:
        db, project, root = await _artifact_store_for_cli(args)
    except LookupError as exc:
        print(f"[artifact] {exc}", file=sys.stderr)
        return 1
    try:
        record = await db.artifact_store.get(args.artifact_id)
        if record is None or record.project_id != project.id:
            raise FileNotFoundError(args.artifact_id)
        if record.path.startswith("attachment://"):
            raise ValueError("attachment-backed artifacts must use attachment open")
        candidate = (root / record.path.removeprefix("workspace://")).resolve()
        candidate.relative_to(root)
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        open_with_default_app(candidate)
        print(f"[artifact] opened: {record.name}")
        return 0
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"[artifact] open failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await db.close()


async def cmd_artifact_preview(args: argparse.Namespace) -> int:
    """Read an artifact through the same workspace boundary as GUI text preview."""

    try:
        db, project, root = await _artifact_store_for_cli(args)
    except LookupError as exc:
        print(f"[artifact] {exc}", file=sys.stderr)
        return 1
    try:
        record = await db.artifact_store.get(args.artifact_id)
        if record is None or record.project_id != project.id:
            raise FileNotFoundError(args.artifact_id)
        if record.path.startswith("attachment://"):
            raise ValueError("attachment-backed artifacts must use attachment preview")
        candidate = (root / record.path.removeprefix("workspace://")).resolve()
        candidate.relative_to(root)
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        if b"\0" in candidate.read_bytes()[:8192]:
            raise ValueError(f"not a plain-text artifact: {record.name}")
        limit = max(1, int(getattr(args, "max_chars", 200000) or 200000))
        text = candidate.read_text(encoding="utf-8", errors="replace")
        print(text[:limit], end="" if text[:limit].endswith("\n") else "\n")
        if len(text) > limit:
            print(f"[artifact] preview truncated at {limit} characters", file=sys.stderr)
        return 0
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"[artifact] preview failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await db.close()


async def cmd_artifact_delete(args: argparse.Namespace) -> int:
    db, project, _root = await _artifact_store_for_cli(args)
    try:
        deleted = await db.artifact_store.soft_remove(args.artifact_ids, project_id=project.id)
        print(f"[artifact] 已移出资料库 {deleted} 个（只改成果库状态，不动磁盘文件）")
        return 0
    finally:
        await db.close()


async def cmd_artifact_restore(args: argparse.Namespace) -> int:
    db, project, _root = await _artifact_store_for_cli(args)
    try:
        restored = await db.artifact_store.soft_remove(
            args.artifact_ids,
            deleted=False,
            project_id=project.id,
        )
        print(f"[artifact] 已恢复 {restored} 个")
        return 0
    finally:
        await db.close()


async def cmd_loadtools_show(args: argparse.Namespace) -> int:
    from .settings import _loadtools_for_cli
    modes, path, from_config = _loadtools_for_cli()
    source = "config" if from_config else "builtin"
    print(f"[loadtools] source={source}  file={path}")
    for name, mode in modes.items():
        tool_text = ", ".join(mode.tools) if mode.tools else "(all tools — no limit)"
        print(f"  {name}: {mode.description or '(no description)'}")
        print(f"    tools: {tool_text}")
    return 0


async def cmd_loadtools_edit_mode(args: argparse.Namespace) -> int:
    from .settings import _loadtools_for_cli
    from lamtools_core.tool.loadtools import LoadToolMode, serialize_loadtools

    modes, path, _ = _loadtools_for_cli()
    name = args.mode.strip()
    if not name:
        print("error: --mode is required", file=sys.stderr)
        return 1
    if args.no_limit:
        tools: list[str] = []
    elif args.tools.strip():
        tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    else:
        existing = modes.get(name)
        tools = list(existing.tools) if existing is not None else []
    description = args.description.strip() or (modes.get(name).description if modes.get(name) else "")
    modes[name] = LoadToolMode(description=description, tools=tools)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize_loadtools(modes), encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"[loadtools] mode '{name}' saved to {path}")
    return 0


async def cmd_loadtools_delete_mode(args: argparse.Namespace) -> int:
    from .settings import _loadtools_for_cli
    from lamtools_core.tool.loadtools import serialize_loadtools

    modes, path, from_config = _loadtools_for_cli()
    name = args.mode.strip()
    if name not in modes:
        print(f"error: mode '{name}' not found", file=sys.stderr)
        return 1
    del modes[name]
    if not modes:
        print("error: cannot delete the last mode", file=sys.stderr)
        return 1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize_loadtools(modes), encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"[loadtools] mode '{name}' deleted; file={path}")
    return 0


async def cmd_memory(args: argparse.Namespace) -> int:
    """Browse and edit the two-tier memory library (see ``mem.library``)."""
    from pathlib import Path as _Path

    from lamtools_core import mem as memory

    scope = memory.SCOPE_GLOBAL if getattr(args, "memory_global", False) else memory.SCOPE_PROJECT
    work_root = str(getattr(args, "work_root", "") or "") or str(_Path.cwd())
    command = args.memory_command

    def _content() -> str:
        source = str(getattr(args, "from_file", "") or "")
        if source:
            if source == "-":
                return sys.stdin.read()
            return _Path(source).read_text(encoding="utf-8")
        inline = getattr(args, "content", None)
        if inline:
            return str(inline)
        return sys.stdin.read()

    try:
        if command == "tree":
            entries = memory.list_entries(
                scope,
                work_root,
                path=str(getattr(args, "path", "") or ""),
                recursive=not getattr(args, "flat", False),
                max_depth=int(getattr(args, "max_depth", 0) or 0),
            )
            root = memory.memory_root(scope, work_root)
            print(f"[memory] {memory.normalize_scope(scope)} tier: {root}")
            if not entries:
                print("(empty)")
                return 0
            for entry in entries:
                suffix = "/" if entry.is_dir else ""
                summary = f"  — {entry.summary}" if entry.summary else ""
                print(f"{entry.path}{suffix}{summary}")
            return 0
        if command == "read":
            print(memory.read_memory(scope, work_root, args.path), end="")
            return 0
        if command == "write":
            entry = memory.write_memory(scope, work_root, args.path, _content())
            print(f"[memory] wrote {entry.path} ({entry.size} bytes)")
            return 0
        if command == "append":
            entry = memory.append_memory(scope, work_root, args.path, _content())
            print(f"[memory] appended to {entry.path} ({entry.size} bytes)")
            return 0
        if command == "edit":
            raw_occurrence = int(getattr(args, "occurrence", 0) or 0)
            entry = memory.edit_memory(
                scope,
                work_root,
                args.path,
                str(args.old),
                str(args.new),
                occurrence=raw_occurrence or None,
            )
            print(f"[memory] edited {entry.path}")
            return 0
        if command == "delete":
            print(f"[memory] deleted {memory.delete_memory(scope, work_root, args.path)}")
            return 0
        if command == "rename":
            renamed = memory.rename_memory(scope, work_root, args.path, args.new_path)
            print(f"[memory] renamed {args.path} -> {renamed}")
            return 0
        if command == "mkdir":
            print(f"[memory] created directory {memory.make_directory(scope, work_root, args.path)}")
            return 0
        if command == "reveal":
            opened = memory.reveal_memory(scope, work_root)
            print(f"[memory] {memory.normalize_scope(scope)} tier: {opened}")
            return 0
        if command == "projects":
            kept = [
                str(root)
                for root in args.roots
                if memory.has_content(memory.SCOPE_PROJECT, str(root))
            ]
            if not kept:
                print("(none)")
                return 0
            for root in kept:
                print(root)
            return 0
    except memory.MemoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"error: unknown memory command '{command}'", file=sys.stderr)
    return 1
