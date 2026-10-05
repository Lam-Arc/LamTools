"""The ``memory`` tool — file management over the two-tier memory library.

One tool, dispatched by ``action``, over the ``project`` or ``global`` tier.
Memory is a directory of plain Markdown files whose tree *is* the index; the
generated ``INDEX.md`` in each tier is injected every session and is read-only
here.  All paths are relative to the tier root and cannot escape it.
"""

from __future__ import annotations

from pathlib import Path

from lamtools_core.mem import library as memory_library
from lamtools_core.mem.library import MemoryError
from lamtools_core.tool import ToolCall, ToolResult

MEMORY_TOOL_NAME = "memory"

MEMORY_TOOL_DESCRIPTION = (
    "Read and edit long-term memory. Memory is a directory of Markdown files, "
    "and the folder structure is the index; each tier's generated INDEX.md is "
    "injected into your context every turn. Two tiers: 'project' "
    "(<workspace>/.lam/memory/) for this project only, 'global' "
    "(user config memory/) shared across all projects. Paths are relative to "
    "the tier root. Actions: list (browse; set recursive/max_depth), read, "
    "write (replace whole file; creates it), append, edit (replace old_string "
    "with new_string; add occurrence when the text appears more than once), "
    "delete (file or directory), rename (move to new_path), mkdir. "
    "INDEX.md is generated and cannot be written, renamed or deleted."
)

MEMORY_TOOL_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "read", "write", "append", "edit", "delete", "rename", "mkdir"],
            "description": "Operation to perform on the memory library.",
        },
        "scope": {
            "type": "string",
            "enum": ["project", "global"],
            "description": "Which tier to act on. Defaults to 'project'.",
        },
        "path": {
            "type": "string",
            "description": "Path relative to the tier root (e.g. 'decisions/api.md').",
        },
        "new_path": {
            "type": "string",
            "description": "Destination path for 'rename'.",
        },
        "content": {
            "type": "string",
            "description": "File content for 'write' / text to add for 'append'.",
        },
        "old_string": {
            "type": "string",
            "description": "Exact text to replace for 'edit'.",
        },
        "new_string": {
            "type": "string",
            "description": "Replacement text for 'edit'.",
        },
        "occurrence": {
            "type": "integer",
            "minimum": 1,
            "description": "1-based occurrence to replace when old_string appears multiple times.",
        },
        "recursive": {
            "type": "boolean",
            "description": "For 'list': descend into subdirectories (default true).",
        },
        "max_depth": {
            "type": "integer",
            "minimum": 0,
            "description": "For 'list': maximum depth to descend (0 = unlimited).",
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


def _format_entries(entries: list[memory_library.MemoryEntry]) -> str:
    if not entries:
        return "(empty)"
    lines: list[str] = []
    for entry in entries:
        name = entry.path + ("/" if entry.is_dir else "")
        if entry.is_dir:
            lines.append(f"- {name}")
        elif entry.summary:
            lines.append(f"- {name} — {entry.summary}")
        else:
            lines.append(f"- {name}")
    return "\n".join(lines)


def make_memory_handler(work_root: str | Path | None):
    """Build the ``memory`` tool handler bound to *work_root*."""

    async def memory(call: ToolCall) -> ToolResult:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        action = str(args.get("action") or "").strip().lower()
        if not action:
            return _failed(call, "Missing 'action' argument", "missing_argument")
        scope = str(args.get("scope") or memory_library.SCOPE_PROJECT)
        root = work_root
        path = str(args.get("path") or "")
        try:
            if action == "list":
                entries = memory_library.list_entries(
                    scope,
                    root,
                    path=path,
                    recursive=bool(args.get("recursive", True)),
                    max_depth=int(args.get("max_depth") or 0),
                )
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=_format_entries(entries),
                    metadata={"scope": memory_library.normalize_scope(scope), "count": len(entries)},
                )
            if action == "read":
                if not path:
                    return _failed(call, "'read' requires a path", "missing_argument")
                content = memory_library.read_memory(scope, root, path)
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=content,
                    metadata={"scope": memory_library.normalize_scope(scope), "path": path},
                )
            if action == "write":
                if not path:
                    return _failed(call, "'write' requires a path", "missing_argument")
                entry = memory_library.write_memory(
                    scope, root, path, str(args.get("content") or "")
                )
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=f"Wrote {entry.path} ({entry.size} bytes)",
                    metadata={"scope": memory_library.normalize_scope(scope), "path": entry.path},
                )
            if action == "append":
                if not path:
                    return _failed(call, "'append' requires a path", "missing_argument")
                entry = memory_library.append_memory(
                    scope, root, path, str(args.get("content") or "")
                )
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=f"Appended to {entry.path} ({entry.size} bytes)",
                    metadata={"scope": memory_library.normalize_scope(scope), "path": entry.path},
                )
            if action == "edit":
                if not path:
                    return _failed(call, "'edit' requires a path", "missing_argument")
                raw_occurrence = args.get("occurrence")
                occurrence = int(raw_occurrence) if raw_occurrence else None
                entry = memory_library.edit_memory(
                    scope,
                    root,
                    path,
                    str(args.get("old_string") or ""),
                    str(args.get("new_string") or ""),
                    occurrence=occurrence,
                )
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=f"Edited {entry.path}",
                    metadata={"scope": memory_library.normalize_scope(scope), "path": entry.path},
                )
            if action == "delete":
                if not path:
                    return _failed(call, "'delete' requires a path", "missing_argument")
                deleted = memory_library.delete_memory(scope, root, path)
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=f"Deleted {deleted}",
                    metadata={"scope": memory_library.normalize_scope(scope), "path": deleted},
                )
            if action == "rename":
                new_path = str(args.get("new_path") or "")
                if not path or not new_path:
                    return _failed(call, "'rename' requires path and new_path", "missing_argument")
                renamed = memory_library.rename_memory(scope, root, path, new_path)
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=f"Renamed {path} -> {renamed}",
                    metadata={"scope": memory_library.normalize_scope(scope), "path": renamed},
                )
            if action == "mkdir":
                if not path:
                    return _failed(call, "'mkdir' requires a path", "missing_argument")
                made = memory_library.make_directory(scope, root, path)
                return ToolResult(
                    call_id=call.id,
                    name=call.name,
                    status="ok",
                    content=f"Created directory {made}",
                    metadata={"scope": memory_library.normalize_scope(scope), "path": made},
                )
        except MemoryError as exc:
            return _failed(call, str(exc), getattr(exc, "code", "memory_error"))
        except OSError as exc:
            return _failed(call, str(exc), "memory_io_error")
        return _failed(call, f"Unknown memory action '{action}'", "invalid_action")

    return memory


__all__ = [
    "MEMORY_TOOL_DESCRIPTION",
    "MEMORY_TOOL_NAME",
    "MEMORY_TOOL_SCHEMA",
    "make_memory_handler",
]
