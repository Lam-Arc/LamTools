"""The ``library`` tool — catalog bookkeeping over the project library (资料库).

One tool, dispatched by ``action``: list, register, favorite, folder, remove,
restore.  Nothing lands in the catalog automatically any more: agent-produced
files enter the library only when the agent registers them here (user uploads
are catalogued by the upload itself).  The catalog is bookkeeping over
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

from lamtools_core.tool import ToolCall, ToolResult

LIBRARY_TOOL_NAME = "library"

LIBRARY_TOOL_DESCRIPTION = (
    "Curate the project library (资料库): the catalog of files that matter for "
    "this project — user uploads and the deliverables you deliberately file into "
    "it. Nothing you produce enters the catalog automatically: registering is "
    "your call. The catalog is bookkeeping only — entries point at workspace "
    "files and no action here reads, moves or deletes the file itself. Folders "
    "are catalog layers (the library's archive tabs), not disk directories; "
    "layer names are free-form and may nest with '/', empty string = "
    "unarchived. Actions: list (entry ids, names, roles, layers, favorites), "
    "register (file a workspace file into the catalog; optionally assign its "
    "layer in the same call), favorite (set favorite true/false), folder "
    "(re-layer one or more entries), remove (soft-remove; restorable, file "
    "untouched), restore. "
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
            "enum": ["list", "register", "favorite", "folder", "remove", "restore"],
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


def _format_records(records: list[Any]) -> str:
    if not records:
        return "(empty)"
    lines: list[str] = []
    for record in records:
        flags: list[str] = []
        if getattr(record, "deleted", False):
            flags.append("removed")
        if str(getattr(record, "availability", "") or "") == "missing":
            flags.append("missing")
        parts = [
            str(getattr(record, "artifact_id", "") or ""),
            str(getattr(record, "name", "") or ""),
            f"role={getattr(record, 'role', '') or '-'}",
            f"folder={getattr(record, 'folder', '') or '-'}",
            "favorite" if getattr(record, "favorite", False) else "",
            *(flags),
        ]
        lines.append("- " + "  ".join(part for part in parts if part))
    return "\n".join(lines)


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
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=_format_records(records),
                    metadata={"count": len(records), "project_id": project_id},
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
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=f"Filed {relative} into the library as {record.artifact_id}"
                    + (f" under {folder}" if folder else ""),
                    metadata={"artifact_id": record.artifact_id, "path": relative, "folder": folder},
                )

            raw_ids = args.get("artifact_ids")
            ids = [str(item).strip() for item in raw_ids if str(item).strip()] if isinstance(raw_ids, list) else []
            if not ids:
                return _failed(call, f"'{action}' requires artifact_ids", "missing_argument")

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
