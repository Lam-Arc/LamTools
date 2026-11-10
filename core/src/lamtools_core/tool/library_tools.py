"""The ``library`` tool — catalog bookkeeping over the project library (资料库).

One tool, dispatched by ``action``: list, register, favorite, folder, remove,
restore. Final-answer file references, web links and changed memory are indexed
automatically; this tool also files other intentional deliverables and organizes
existing entries. The catalog is bookkeeping over
workspace files — no action reads, moves or deletes the file itself, exactly
like the UI's library panel.  Folders are catalog layers, not disk
directories.  The handler is bound to the current project via the toolbox's
work root; the description carries the behavioral rules that make the agent
curate the library deliberately.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from lamtools_core.tool import ToolCall, ToolResult, ToolArtifact

LIBRARY_TOOL_NAME = "library"

LIBRARY_TOOL_DESCRIPTION = (
    "Curate the project library (资料库): the catalog of files that matter for "
    "this project — user uploads and the deliverables you deliberately file into "
    "it. Existing files named in your final answer, web links and changed memory "
    "are indexed automatically; use register to file other intentional outputs. "
    "The catalog is bookkeeping only — entries point at files and no "
    "action here reads, moves or deletes those files. Folders are catalog "
    "layers (the library's archive tabs), not disk directories; layer names are "
    "free-form and may nest with '/', empty string = unarchived. Every entry "
    "lists the file it points at (file=…): workspace uploads live under the "
    "project's 资料/ folder, chat uploads live in the app's attachment store, "
    "and either way the listed path is a real file you can read_file. "
    "Tags are the retrieval key, layers are the archive: tag entries by what they "
    "are (button, card, css, motion) so they can be found again by kind, and put "
    "them in a layer by which part of the project they belong to. Ratings are 0 "
    "to 5, 0 = unrated. "
    "Tag the way a person speaks, in three questions: what it is (material, "
    "control, layout, motion, surface), how it looks (glass, low-trans, ring, "
    "rounded, glow), and where it is used (button, dialog, ping-ring, card, "
    "composer). Never tag with tokens sliced out of class names — 'head', 'row' "
    "and 'label' are not retrieval words. "
    "Every reusable material should carry 'usage': entry (the class name or the "
    "import path it is reached by), requires (design tokens, parent requirements) "
    "and example (a minimal snippet). An entry without usage only points at a "
    "file, which forces the next reader to re-derive the material from source. "
    "After you land a material in real code, call 'use' with the file you put it "
    "in — that is the only trace of what has actually been reused. "
    "Actions: list (entry ids, names, roles, layers, tags, ratings, use counts, "
    "usage entry, file locations; 'tag' takes one tag or a list where every tag "
    "must match; 'sort' is rating (default, best first, ties by recent use), used, "
    "recent or name), register (file a workspace file into the catalog; optionally "
    "assign its layer and its 'usage' in the same call), favorite (set favorite "
    "true/false), folder (re-layer one or more entries), tag (add, remove or set "
    "tags on existing entries), rate (0 to 5), use (record one use: artifact_ids "
    "plus used_in), remove (soft-remove; restorable, file untouched), restore. "
    "File deliberately: after a turn produces a deliverable worth keeping, "
    "'register' it and give it a fitting layer in the same call — follow the "
    "layers this project already uses (check with 'list' first), otherwise pick "
    "a short fitting layer name. Leave scratch files, intermediate debris and "
    "things the user never asked to keep out of the library. Favorite only when "
    "the user marks something as important; remove or restore only when the "
    "user explicitly asks. Resolve entries by id from 'list'."
)

LIBRARY_TOOL_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "register", "favorite", "folder", "tag", "rate", "use", "remove", "restore"],
            "description": "Operation to perform on the project library catalog.",
        },
        "path": {
            "type": "string",
            "description": "For 'register': the workspace file to file in (relative to the workspace, or workspace://…).",
        },
        "role": {
            "type": "string",
            "enum": ["deliverable", "intermediate"],
            "description": "For 'register': the entry's role. Default deliverable.",
        },
        "artifact_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "Entry ids from 'list'; required by favorite/folder/remove/restore.",
        },
        "favorite": {
            "type": "boolean",
            "description": "For 'favorite': true to mark as favorite, false to unmark.",
        },
        "folder": {
            "type": "string",
            "description": "Catalog layer name; '' removes entries from any layer. With 'register': optional layer assigned in the same call.",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "For 'tag': the tags to add or remove. Lowercase, short, by what the thing is.",
        },
        "mode": {
            "type": "string",
            "enum": ["add", "remove", "set"],
            "description": "For 'tag': add merges, remove drops, set replaces the whole list. Default add.",
        },
        "rating": {
            "type": "integer",
            "minimum": 0,
            "maximum": 5,
            "description": "For 'rate': 0 to 5, 0 clears the rating.",
        },
        "tag": {
            "anyOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}, "minItems": 1},
            ],
            "description": "For 'list': one tag, or a list of tags where every tag must match (material + shape).",
        },
        "sort": {
            "type": "string",
            "enum": ["rating", "used", "recent", "name"],
            "description": "For 'list': rating (default: highest rating first, ties by recent use), used (most reused), recent (last used/changed), name.",
        },
        "usage": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "entry": {"type": "string"},
                "requires": {"type": "string"},
                "example": {"type": "string"},
            },
            "description": "How to use it: entry (class name or import path), requires (tokens/parent), example (minimal snippet).",
        },
        "used_in": {
            "type": "string",
            "description": "For 'use': where the material landed — task/session plus file path.",
        },
    },
    "required": ["action"],
}


def _failed(call: ToolCall, message: str, code: str) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="failed",
        error=message,
        error_code=code,
        metadata={"error_type": code},
    )


async def _format_records(records: list[Any], artifact_store: Any) -> str:
    """一条一行；每条带上它在磁盘上的当前位置，助手据此可以直接读文件。

    「用户」上传有两种落点：资料库上传在项目「资料/」里，聊天附件在应用
    的附件库里——都由 store 解析成真实文件的绝对路径，读起来一视同仁。
    """
    if not records:
        return "(empty)"
    lines: list[str] = []
    for record in records:
        flags: list[str] = []
        if getattr(record, "deleted", False):
            flags.append("removed")
        try:
            resolved = await artifact_store.current_content_path(record)
        except OSError:
            resolved = None
        if resolved is not None:
            location = f"file={resolved}"
        else:
            flags.append("missing")
            location = "file=(missing)"
        tags = ",".join(getattr(record, "tags", []) or [])
        rating = int(getattr(record, "rating", 0) or 0)
        used = int(getattr(record, "usage_count", 0) or 0)
        usage = getattr(record, "usage", {}) or {}
        entry = str(usage.get("entry") or "").strip() if isinstance(usage, dict) else ""
        parts = [
            str(getattr(record, "artifact_id", "") or ""),
            str(getattr(record, "name", "") or ""),
            f"role={getattr(record, 'role', '') or '-'}",
            f"folder={getattr(record, 'folder', '') or '-'}",
            f"tags={tags}" if tags else "",
            f"rating={rating}" if rating else "",
            f"used={used}",
            "favorite" if getattr(record, "favorite", False) else "",
            f"entry={entry}" if entry else "",
            location,
            *(flags),
        ]
        lines.append("- " + "  ".join(part for part in parts if part))
    return "\n".join(lines)


LIBRARY_SORT_KEYS = {"rating", "used", "recent", "name"}


def _recency(record: Any) -> str:
    """最近一次被用到/被改动的时间；三种都没有就排最后。"""
    return str(
        getattr(record, "last_used_at", "")
        or getattr(record, "updated_at", "")
        or getattr(record, "created_at", "")
        or ""
    )


def _sorted_records(records: list[Any], sort: str) -> list[Any]:
    """排序是取用的一部分：先按最近时间排，再按主键稳定排序。

    - rating（默认）：星级从高到低，同分按最近使用/改动；
    - used：取用次数从多到少；
    - recent：最近使用/改动；
    - name：名字。
    """
    if sort == "name":
        return sorted(records, key=lambda item: (
            str(getattr(item, "name", "") or "").lower(),
            str(getattr(item, "artifact_id", "") or ""),
        ))
    ordered = sorted(records, key=_recency, reverse=True)
    if sort == "used":
        return sorted(ordered, key=lambda item: int(getattr(item, "usage_count", 0) or 0), reverse=True)
    if sort == "recent":
        return ordered
    return sorted(ordered, key=lambda item: int(getattr(item, "rating", 0) or 0), reverse=True)


class _OutsideWorkspace(ValueError):
    """登记路径越出了项目工作区（对应 path_outside_root 错误码）。"""


def _workspace_reference(work_root: Path, raw_path: str) -> Path:
    """把调用方给的路径落回工作区内的一个真实文件；越界或缺文件都直接抛错。"""
    value = raw_path.strip()
    if value.startswith("workspace://"):
        value = value[len("workspace://"):]
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = work_root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(work_root)
    except ValueError as exc:
        raise _OutsideWorkspace(f"Path escapes the workspace: {raw_path}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(raw_path)
    return candidate


def make_library_handler(artifact_store: Any, work_root: str | Path | None):
    """Build the ``library`` tool handler bound to the current project's catalog."""

    async def library(call: ToolCall) -> ToolResult:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        action = str(args.get("action") or "").strip().lower()
        if not action:
            return _failed(call, "Missing 'action' argument", "missing_argument")
        if artifact_store is None:
            return _failed(call, "The library catalog is unavailable in this runtime", "library_unavailable")
        root = Path(work_root).resolve() if work_root else None
        if root is None:
            return _failed(call, "No workspace is bound to this session", "project_not_found")
        project_id = await artifact_store.resolve_project_id(root)
        if not project_id:
            return _failed(call, "No project is bound to the current workspace", "project_not_found")
        try:
            if action == "list":
                records = await artifact_store.list(project_id)
                raw_tags = args.get("tag")
                if isinstance(raw_tags, str):
                    wanted = [raw_tags]
                elif isinstance(raw_tags, list):
                    wanted = [str(item) for item in raw_tags]
                else:
                    wanted = []
                wanted = [" ".join(item.split()).strip().lower() for item in wanted]
                wanted = [item for item in wanted if item]
                if wanted:
                    matched: list[Any] = []
                    for item in records:
                        own = {str(tag).lower() for tag in (getattr(item, "tags", []) or [])}
                        if all(tag in own for tag in wanted):
                            matched.append(item)
                    records = matched
                sort_key = str(args.get("sort") or "rating").strip().lower()
                if sort_key not in LIBRARY_SORT_KEYS:
                    return _failed(call, f"Unknown sort '{sort_key}'", "invalid_argument")
                records = _sorted_records(records, sort_key)
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=await _format_records(records, artifact_store),
                    metadata={"count": len(records), "project_id": project_id, "tag": wanted, "sort": sort_key},
                )

            if action == "register":
                raw_path = str(args.get("path") or "").strip()
                if not raw_path:
                    return _failed(call, "'register' requires a path", "missing_argument")
                candidate = _workspace_reference(root, raw_path)
                relative = candidate.relative_to(root).as_posix()
                role = str(args.get("role") or "deliverable")
                if role not in {"deliverable", "intermediate"}:
                    return _failed(call, f"Unknown role '{role}'", "invalid_argument")
                # 用法先校验：不合格就不登记，避免留下一条半成品。
                usage = args.get("usage")
                if usage is not None and not isinstance(usage, dict):
                    return _failed(call, "'usage' must be an object with entry/requires/example", "invalid_argument")
                record = await artifact_store.register(
                    project_id=project_id,
                    work_root=root,
                    path=f"workspace://{relative}",
                    kind="file_change",
                    mime_type=mimetypes.guess_type(candidate.name)[0] or "",
                    name=candidate.name,
                    source="agent_generated",
                    role=role,
                    provenance={"registered_by": "library_tool"},
                )
                folder = str(args.get("folder") or "")
                if folder:
                    record = await artifact_store.set_folder(record.artifact_id, folder)
                if isinstance(usage, dict) and usage:
                    record = await artifact_store.set_usage(record.artifact_id, usage)
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=f"Filed {relative} into the library as {record.artifact_id}"
                    + (f" under {folder}" if folder else ""),
                    # user:“这一轮被操作进libary的文件”+(显式登记也形成可汇总的本轮成果)。
                    artifacts=[ToolArtifact(kind="file_change", uri=record.path, artifact_id=record.artifact_id, metadata={"path": record.path, "role": record.role, "mime_type": record.mime_type})],
                    metadata={"artifact_id": record.artifact_id, "path": relative, "folder": folder},
                )

            raw_ids = args.get("artifact_ids")
            ids = [str(item).strip() for item in raw_ids if str(item).strip()] if isinstance(raw_ids, list) else []
            if not ids:
                return _failed(call, f"'{action}' requires artifact_ids", "missing_argument")

            if action == "tag":
                raw_tags = args.get("tags")
                tags = [str(item) for item in raw_tags] if isinstance(raw_tags, list) else []
                mode = str(args.get("mode") or "add").strip().lower()
                if mode not in {"add", "remove", "set"}:
                    return _failed(call, f"Unknown mode '{mode}'", "invalid_argument")
                for artifact_id in ids:
                    record = await artifact_store.get(artifact_id)
                    if record is None:
                        return _failed(call, f"Artifact not found: {artifact_id}", "artifact_not_found")
                    current = [str(item) for item in getattr(record, "tags", []) or []]
                    if mode == "set":
                        merged = tags
                    elif mode == "remove":
                        drop = {item.strip().lower() for item in tags}
                        merged = [item for item in current if item.lower() not in drop]
                    else:
                        merged = current + tags
                    await artifact_store.set_tags(artifact_id, merged)
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=f"Tagged {len(ids)} entr{'y' if len(ids) == 1 else 'ies'} ({mode}: {', '.join(tags) or '-'})",
                    metadata={"mode": mode, "tags": tags, "artifact_ids": ids},
                )
            if action == "rate":
                try:
                    rating = int(args.get("rating") or 0)
                except (TypeError, ValueError):
                    return _failed(call, "rating must be an integer 0-5", "invalid_argument")
                rating = max(0, min(5, rating))
                for artifact_id in ids:
                    await artifact_store.set_rating(artifact_id, rating)
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=f"Rated {len(ids)} entr{'y' if len(ids) == 1 else 'ies'} {rating}/5",
                    metadata={"rating": rating, "artifact_ids": ids},
                )
            if action == "favorite":
                favorite = bool(args.get("favorite", True))
                for artifact_id in ids:
                    await artifact_store.set_favorite(artifact_id, favorite)
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=f"{'Marked' if favorite else 'Unmarked'} {len(ids)} entr{'y' if len(ids) == 1 else 'ies'}",
                    metadata={"favorite": favorite, "artifact_ids": ids},
                )
            if action == "folder":
                folder = str(args.get("folder") or "")
                for artifact_id in ids:
                    await artifact_store.set_folder(artifact_id, folder)
                label = folder if folder else "(unarchived)"
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=f"Moved {len(ids)} entr{'y' if len(ids) == 1 else 'ies'} to layer {label}",
                    metadata={"folder": folder, "artifact_ids": ids},
                )
            if action == "use":
                where = " ".join(str(args.get("used_in") or "").split()).strip()
                if not where:
                    return _failed(call, "'use' requires used_in — where the material landed", "missing_argument")
                used = await artifact_store.record_use(ids, used_in=where)
                lines = [
                    f"- {item.artifact_id}  used={item.usage_count}  last_used={item.last_used_at}"
                    for item in used
                ]
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=(
                        f"Recorded one use of {len(used)} entr{'y' if len(used) == 1 else 'ies'} in {where}\n"
                        + "\n".join(lines)
                    ),
                    metadata={"used_in": where, "artifact_ids": [item.artifact_id for item in used]},
                )
            if action == "remove":
                removed = await artifact_store.soft_remove(ids, project_id=project_id)
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=f"Removed {removed} entr{'y' if removed == 1 else 'ies'} from the library (file untouched, restorable)",
                    metadata={"removed": removed},
                )
            if action == "restore":
                restored = await artifact_store.soft_remove(ids, deleted=False, project_id=project_id)
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=f"Restored {restored} entr{'y' if restored == 1 else 'ies'}",
                    metadata={"restored": restored},
                )
        except LookupError as exc:
            return _failed(call, str(exc), "entry_not_found")
        except FileNotFoundError as exc:
            return _failed(call, str(exc), "file_not_found")
        except _OutsideWorkspace as exc:
            return _failed(call, str(exc), "path_outside_root")
        except ValueError as exc:
            return _failed(call, str(exc), "invalid_argument")
        except OSError as exc:
            return _failed(call, str(exc), "library_io_error")
        return _failed(call, f"Unknown library action '{action}'", "invalid_action")

    return library


__all__ = [
    "LIBRARY_TOOL_DESCRIPTION",
    "LIBRARY_TOOL_NAME",
    "LIBRARY_TOOL_SCHEMA",
    "make_library_handler",
]
