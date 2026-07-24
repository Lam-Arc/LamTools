from __future__ import annotations

import datetime
import difflib
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from lamtools_core.tool import ToolArtifact, ToolCall, ToolResult
from lamtools_core.tool.document_normalize import (
    DocumentNormalizationError,
    normalize_document,
)
from lamtools_core.tool.workspace import (
    format_file_size,
    is_within_path,
    line_count,
    relative_workspace_uri,
    validate_workspace_path,
)

DEFAULT_MAX_LIST_ITEMS = 100
DEFAULT_MAX_TEXT_LENGTH = 50_000
DEFAULT_MAX_SEARCH_RESULTS = 50

SKIP_SEARCH_DIRS = frozenset({
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    ".cache",
})


def resolve_read_resource_path(
    path: str | Path,
    work_root: str | Path,
    resource_roots: tuple[Path, ...] = (),
) -> tuple[Path, Path]:
    root = Path(work_root).resolve()
    raw = Path(path)
    roots = tuple(item.resolve() for item in resource_roots)

    if raw.is_absolute():
        resolved = raw.resolve()
        for candidate_root in (root, *roots):
            if is_within_path(resolved, candidate_root):
                return resolved, candidate_root
        raise ValueError(f"Path '{path}' is outside work_root '{work_root}'")

    primary = (root / raw).resolve()
    if not is_within_path(primary, root):
        raise ValueError(f"Path '{path}' is outside work_root '{work_root}'")
    if primary.exists() or not roots:
        return primary, root

    for resource_root in roots:
        candidate = (resource_root / raw).resolve()
        if is_within_path(candidate, resource_root) and candidate.exists():
            return candidate, resource_root
    return primary, root


def unified_diff(old_content: str, new_content: str, rel_path: str) -> str:
    return "".join(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            lineterm="\n",
        )
    )


class WorkspaceReadOnlyTools:
    def __init__(
        self,
        work_root: str | Path,
        *,
        max_list_items: int = DEFAULT_MAX_LIST_ITEMS,
        max_text_length: int = DEFAULT_MAX_TEXT_LENGTH,
        max_search_results: int = DEFAULT_MAX_SEARCH_RESULTS,
    ) -> None:
        self._work_root = Path(work_root).resolve()
        self._max_list_items = max_list_items
        self._max_text_length = max_text_length
        self._max_search_results = max_search_results
        self._resource_roots: set[Path] = set()

    def add_resource_root(self, path: str | Path) -> None:
        self._resource_roots.add(Path(path).resolve())

    def resource_roots(self) -> tuple[Path, ...]:
        return tuple(sorted(self._resource_roots, key=lambda item: item.as_posix()))

    def as_dict(self) -> dict[str, Callable[[ToolCall], Awaitable[ToolResult]]]:
        return {
            "read_file": self.read_file,
            "list_dir": self.list_dir,
            "search_files": self.search_files,
            "search_content": self.search_content,
        }

    async def read_file(self, call: ToolCall) -> ToolResult:
        path_str = call.arguments.get("path", "") if isinstance(call.arguments, dict) else ""
        if not path_str:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error="Missing 'path' argument")

        try:
            resolved, access_root = resolve_read_resource_path(path_str, self._work_root, self.resource_roots())
        except ValueError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=str(exc))

        if not resolved.is_file():
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"File not found: {path_str}")

        document_metadata: dict[str, Any] = {}
        try:
            normalized = normalize_document(
                resolved,
                workspace_root=self._work_root,
                max_text_length=self._max_text_length,
            )
        except DocumentNormalizationError as exc:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error=f"Document normalize error for {path_str}: {exc}",
            )
        if normalized is not None:
            content = normalized.markdown
            document_metadata = {
                "document_format": normalized.document_format,
                "content_trust": "untrusted",
                "warnings": list(normalized.warnings),
                "assets": list(normalized.asset_paths),
            }
        else:
            try:
                content = resolved.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Read error: {exc}")

        try:
            stat = resolved.stat()
            file_size = stat.st_size
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            file_size = len(content.encode("utf-8", errors="replace"))
            mtime = "unknown"
        total_lines = line_count(content)

        truncated = False
        if len(content) > self._max_text_length:
            content = content[: self._max_text_length]
            truncated = True

        meta_suffix = f"\n[file: {total_lines} lines, {format_file_size(file_size)}, modified {mtime}]"
        suffix = ("\n[... truncated]" if truncated else "") + meta_suffix
        rel = relative_workspace_uri(resolved, access_root)
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="ok",
            content=content + suffix,
            artifacts=[
                ToolArtifact(
                    kind="file_read",
                    uri=rel,
                    content=content,
                    metadata={
                        "path": rel,
                        "line_count": total_lines,
                        "size_bytes": file_size,
                        "modified": mtime,
                        "truncated": truncated,
                        **document_metadata,
                    },
                )
            ],
            metadata={
                "path": rel,
                "line_count": total_lines,
                "size_bytes": file_size,
                "modified": mtime,
                "truncated": truncated,
                **document_metadata,
            },
        )

    async def list_dir(self, call: ToolCall) -> ToolResult:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        raw_path = args.get("path")
        path_str = raw_path if isinstance(raw_path, str) and raw_path.strip() else "."
        try:
            resolved, _access_root = resolve_read_resource_path(path_str, self._work_root, self.resource_roots())
        except ValueError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=str(exc))

        if not resolved.is_dir():
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Not a directory: {path_str}")

        try:
            entries = sorted(resolved.iterdir())
        except OSError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"List error: {exc}")

        total = len(entries)
        limited = entries[: self._max_list_items]
        lines: list[str] = []
        for entry in limited:
            if entry.is_dir():
                lines.append(f"{entry.name}/")
            else:
                try:
                    stat = entry.stat()
                    size = format_file_size(stat.st_size)
                    mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                    lines.append(f"{entry.name}\t{size}\t{mtime}")
                except OSError:
                    lines.append(f"{entry.name}")

        if total > self._max_list_items:
            lines.append(f"[... {total - self._max_list_items} more entries]")

        return ToolResult(call_id=call.id, name=call.name, status="ok", content="\n".join(lines))

    async def search_files(self, call: ToolCall) -> ToolResult:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        raw_pattern = args.get("pattern")
        pattern = raw_pattern if isinstance(raw_pattern, str) and raw_pattern.strip() else "*"
        raw_path = args.get("path")
        path_str = raw_path if isinstance(raw_path, str) and raw_path.strip() else "."
        try:
            search_root, access_root = resolve_read_resource_path(path_str, self._work_root, self.resource_roots())
        except ValueError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=str(exc))
        if not search_root.is_dir():
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Not a directory: {path_str}")

        try:
            matches = []
            total_seen = 0
            for root, dirs, files in os.walk(search_root):
                dirs[:] = [d for d in dirs if d not in SKIP_SEARCH_DIRS]
                for fname in files:
                    fpath = Path(root) / fname
                    try:
                        rel_to_search = fpath.relative_to(search_root).as_posix()
                    except ValueError:
                        continue
                    if Path(rel_to_search).match(pattern) or Path(fname).match(pattern):
                        total_seen += 1
                        if len(matches) < self._max_search_results:
                            try:
                                matches.append(fpath.relative_to(access_root).as_posix())
                            except ValueError:
                                continue
                if len(matches) >= self._max_search_results and total_seen > self._max_search_results:
                    break
        except OSError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Search error: {exc}")

        lines = sorted(matches)
        if total_seen > self._max_search_results:
            lines.append(f"[... at least {total_seen - self._max_search_results} more matches]")

        if not lines:
            return ToolResult(call_id=call.id, name=call.name, status="ok", content="No files found")

        return ToolResult(call_id=call.id, name=call.name, status="ok", content="\n".join(lines))

    async def search_content(self, call: ToolCall) -> ToolResult:
        pattern = call.arguments.get("pattern", "") if isinstance(call.arguments, dict) else ""
        if not pattern:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error="Missing 'pattern' argument")
        raw_path = call.arguments.get("path") if isinstance(call.arguments, dict) else None
        path_str = raw_path if isinstance(raw_path, str) and raw_path.strip() else "."
        try:
            search_root, access_root = resolve_read_resource_path(path_str, self._work_root, self.resource_roots())
        except ValueError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=str(exc))
        if not search_root.is_file() and not search_root.is_dir():
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Not a directory: {path_str}")

        def iter_search_files() -> Any:
            if search_root.is_file():
                yield search_root
                return
            for root, dirs, files in os.walk(search_root):
                dirs[:] = [d for d in dirs if d not in SKIP_SEARCH_DIRS]
                for fname in files:
                    yield Path(root) / fname

        results: list[str] = []
        count = 0
        try:
            for fpath in iter_search_files():
                if count >= self._max_search_results:
                    break
                try:
                    resolved = fpath.resolve()
                    if not is_within_path(resolved, access_root):
                        continue
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                    for line_no, line in enumerate(text.splitlines(), 1):
                        if pattern in line:
                            try:
                                rel = fpath.relative_to(access_root)
                            except ValueError:
                                continue
                            results.append(f"{rel.as_posix()}:{line_no}: {line.strip()}")
                            count += 1
                            if count >= self._max_search_results:
                                break
                except (OSError, UnicodeDecodeError):
                    continue
                if count >= self._max_search_results:
                    break
        except OSError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Search error: {exc}")

        if not results:
            return ToolResult(call_id=call.id, name=call.name, status="ok", content="No matches found")

        content = "\n".join(results)
        if len(content) > self._max_text_length:
            content = content[: self._max_text_length] + "\n[... truncated]"

        return ToolResult(call_id=call.id, name=call.name, status="ok", content=content)


def make_write_file_handler(
    work_root: Path,
) -> Callable[[ToolCall], Awaitable[ToolResult]]:
    async def write_file(call: ToolCall) -> ToolResult:
        return await write_file_tool(call, work_root=work_root)

    return write_file


def make_document_normalize_handler(
    work_root: Path,
    *,
    max_text_length: int,
) -> Callable[[ToolCall], Awaitable[ToolResult]]:
    async def document_normalize(call: ToolCall) -> ToolResult:
        return await document_normalize_tool(
            call,
            work_root=work_root,
            max_text_length=max_text_length,
        )

    return document_normalize


async def document_normalize_tool(
    call: ToolCall,
    *,
    work_root: Path,
    max_text_length: int,
) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    path_str = args.get("path", "")
    if not isinstance(path_str, str) or not path_str.strip():
        return ToolResult(call_id=call.id, name=call.name, status="failed", error="Missing 'path' argument")

    try:
        resolved, access_root = resolve_read_resource_path(path_str, work_root)
    except ValueError as exc:
        return ToolResult(call_id=call.id, name=call.name, status="failed", error=str(exc))
    if not resolved.is_file():
        return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"File not found: {path_str}")

    try:
        normalized = normalize_document(
            resolved,
            workspace_root=work_root,
            extract_assets=True,
            max_text_length=max_text_length,
        )
    except DocumentNormalizationError as exc:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="failed",
            error=f"Document normalize error for {path_str}: {exc}",
        )
    if normalized is None:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="failed",
            error="document_normalize supports DOCX and PDF files only",
        )

    content = normalized.markdown
    truncated = len(content) > max_text_length
    if truncated:
        content = content[:max_text_length]
    rel = relative_workspace_uri(resolved, access_root)
    metadata = {
        "path": rel,
        "document_format": normalized.document_format,
        "content_trust": "untrusted",
        "warnings": list(normalized.warnings),
        "assets": list(normalized.asset_paths),
        "truncated": truncated,
    }
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="ok",
        content=content + ("\n[... truncated]" if truncated else ""),
        artifacts=[
            ToolArtifact(
                kind="document_normalized",
                uri=rel,
                content=content,
                metadata=metadata,
            )
        ],
        metadata=metadata,
    )


def make_edit_file_handler(
    work_root: Path,
) -> Callable[[ToolCall], Awaitable[ToolResult]]:
    async def edit_file(call: ToolCall) -> ToolResult:
        return await edit_file_tool(call, work_root=work_root)

    return edit_file


async def write_file_tool(
    call: ToolCall,
    *,
    work_root: Path,
) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    path_str = args.get("path", "")
    content = args.get("content", "")

    if not path_str:
        return ToolResult(call_id=call.id, name=call.name, status="failed", error="Missing 'path' argument")
    if not isinstance(path_str, str):
        return ToolResult(call_id=call.id, name=call.name, status="failed", error="'path' must be a string")
    if not isinstance(content, str):
        return ToolResult(call_id=call.id, name=call.name, status="failed", error="'content' must be a string")

    try:
        resolved = validate_workspace_path(path_str, work_root)
    except ValueError as exc:
        return ToolResult(call_id=call.id, name=call.name, status="failed", error=str(exc))

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Cannot create parent directory: {exc}")

    existed_before = resolved.is_file()
    old_content = ""
    if existed_before:
        try:
            old_content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Read error before overwrite: {exc}")

    try:
        resolved.write_text(content, encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Write error: {exc}")

    rel = relative_workspace_uri(resolved, work_root)
    lines = content.split("\n")
    total_lines = line_count(content)
    action = "Overwrote" if existed_before else "Created"
    preview_lines: list[str] = []
    if total_lines <= 6:
        for i, line in enumerate(lines):
            preview_lines.append(f"  {i + 1:4d} | {line}")
    else:
        for i in range(3):
            preview_lines.append(f"  {i + 1:4d} | {lines[i]}")
        preview_lines.append(f"       | ... ({total_lines - 6} lines omitted) ...")
        for i in range(total_lines - 3, total_lines):
            preview_lines.append(f"  {i + 1:4d} | {lines[i]}")
    preview = "\n".join(preview_lines)

    content_summary = (
        f"{action} {rel}: {len(content)} chars, {total_lines} lines.\n"
        f"--- preview ---\n{preview}\n--- end preview ---"
    )
    diff = unified_diff(old_content, content, rel)

    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="ok",
        content=content_summary,
        artifacts=[
            ToolArtifact(
                kind="file_change",
                uri=rel,
                content=diff,
                metadata={
                    "path": rel,
                    "action": "overwrite" if existed_before else "create",
                    "old_line_count": line_count(old_content),
                    "new_line_count": total_lines,
                    "old_size": len(old_content),
                    "new_size": len(content),
                },
            )
        ],
        metadata={
            "path": rel,
            "action": "overwrite" if existed_before else "create",
            "old_line_count": line_count(old_content),
            "new_line_count": total_lines,
            "old_size": len(old_content),
            "new_size": len(content),
        },
    )


async def edit_file_tool(
    call: ToolCall,
    *,
    work_root: Path,
) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    path_str = args.get("path", "")
    old_string = args.get("old_string") or args.get("old_text", "")
    new_string = args.get("new_string") or args.get("new_text", "")

    if not path_str:
        return ToolResult(call_id=call.id, name=call.name, status="failed", error="Missing 'path' argument")
    if not old_string:
        return ToolResult(call_id=call.id, name=call.name, status="failed", error="Missing 'old_string' argument")
    if not isinstance(path_str, str):
        return ToolResult(call_id=call.id, name=call.name, status="failed", error="'path' must be a string")
    if not isinstance(old_string, str):
        return ToolResult(call_id=call.id, name=call.name, status="failed", error="'old_string' must be a string")
    if not isinstance(new_string, str):
        return ToolResult(call_id=call.id, name=call.name, status="failed", error="'new_string' must be a string")

    try:
        resolved = validate_workspace_path(path_str, work_root)
    except ValueError as exc:
        return ToolResult(call_id=call.id, name=call.name, status="failed", error=str(exc))

    if not resolved.is_file():
        return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"File not found: {path_str}")

    try:
        content = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Read error: {exc}")

    count = content.count(old_string)
    if count == 0:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="failed",
            error=f"old_string not found in {path_str}",
        )
    if count > 1:
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="failed",
            error=f"old_string found {count} times in {path_str} - provide more context to make it unique",
        )

    match_offset = content.find(old_string)
    match_line_no = content.count("\n", 0, match_offset) + 1
    new_content = content.replace(old_string, new_string, 1)

    try:
        resolved.write_text(new_content, encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Write error: {exc}")

    rel = relative_workspace_uri(resolved, work_root)
    new_lines = new_content.split("\n")
    replaced_line_count = new_string.count("\n") + 1
    start_idx = max(0, match_line_no - 1 - 3)
    end_idx = min(len(new_lines), match_line_no - 1 + replaced_line_count + 3)
    snippet_lines = []
    for i in range(start_idx, end_idx):
        marker = ">>" if (match_line_no - 1) <= i < (match_line_no - 1 + replaced_line_count) else "  "
        snippet_lines.append(f"{marker} {i + 1:4d} | {new_lines[i]}")
    snippet = "\n".join(snippet_lines)

    total_lines = line_count(new_content)
    content_summary = (
        f"Edited {rel} (line {match_line_no}): "
        f"replaced {len(old_string)} chars with {len(new_string)} chars. "
        f"File now {total_lines} lines, {len(new_content)} chars.\n"
        f"--- context around edit ---\n{snippet}\n--- end context ---"
    )
    diff = unified_diff(content, new_content, rel)

    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="ok",
        content=content_summary,
        artifacts=[
            ToolArtifact(
                kind="file_change",
                uri=rel,
                content=diff,
                metadata={
                    "path": rel,
                    "action": "edit",
                    "start_line": match_line_no,
                    "old_line_count": line_count(content),
                    "new_line_count": total_lines,
                    "old_size": len(content),
                    "new_size": len(new_content),
                },
            )
        ],
        metadata={
            "path": rel,
            "action": "edit",
            "start_line": match_line_no,
            "old_line_count": line_count(content),
            "new_line_count": total_lines,
            "old_size": len(content),
            "new_size": len(new_content),
        },
    )


__all__ = [
    "DEFAULT_MAX_LIST_ITEMS",
    "DEFAULT_MAX_SEARCH_RESULTS",
    "DEFAULT_MAX_TEXT_LENGTH",
    "SKIP_SEARCH_DIRS",
    "WorkspaceReadOnlyTools",
    "document_normalize_tool",
    "edit_file_tool",
    "make_document_normalize_handler",
    "make_edit_file_handler",
    "make_write_file_handler",
    "resolve_read_resource_path",
    "unified_diff",
    "write_file_tool",
]
