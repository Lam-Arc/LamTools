from __future__ import annotations

import asyncio
import base64
import datetime
import difflib
import hashlib
import os
import tempfile
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable

from lamtools_core.tool import ToolArtifact, ToolCall, ToolResult
from lamtools_core.tool.document_normalize import (
    DocumentNormalizationError,
    normalize_document,
)
from lamtools_core.tool.optional_arguments import optional_string
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
# Search scans used to run inline on the backend event loop, so one unbounded
# walk of a multi-GB workspace froze every RPC — Stop included — and no timeout
# could fire because the loop itself was blocked.  Scans now run in a worker
# thread under a hard entry + wall-clock budget, and content matching reads each
# file with a byte cap instead of loading it whole.
DEFAULT_MAX_SEARCH_SCAN_ENTRIES = 100_000
DEFAULT_SEARCH_TIME_BUDGET_SECONDS = 20.0
DEFAULT_MAX_SEARCH_FILE_BYTES = 2_000_000
# Slack above the in-thread budget before the awaiting side gives up on a worker
# stuck inside an uninterruptible filesystem call (dead network share, slow
# device).  The worker thread is abandoned; it cannot be preempted.
SEARCH_TIMEOUT_SLACK_SECONDS = 5.0

SCAN_BUDGET_NOTE = (
    "[... scan stopped early after visiting {visited} entries within the {budget:g}s budget; "
    "results are incomplete — narrow 'path' or 'pattern' and retry]"
)
SCANNED_NOTHING_FOUND = (
    "No matches found within the scan budget after visiting {visited} entries; "
    "the workspace was not fully searched — narrow 'path' or 'pattern' and retry"
)
SKIPPED_FILES_NOTE = "[... {count} files skipped (binary or larger than {limit} bytes)]"

AccessOutsideWorkdir = bool | Callable[[], bool]


def _access_outside_enabled(value: AccessOutsideWorkdir) -> bool:
    return bool(value() if callable(value) else value)

# read_file 对图片文件以 base64 data URL 返回（不设体积上限），
# 多模态模型可直接查看；文本模型由 base_agent 丢弃图片块、仅保留说明文字。
IMAGE_MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".bmp": "image/bmp",
}
IMAGE_DATA_URL_METADATA_KEY = "image_data_url"

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


_FILE_LOCKS: dict[str, asyncio.Lock] = {}
_FILE_LOCKS_GUARD = threading.Lock()
#: Upper bound on the lock table so a long-lived process touching many distinct
#: paths cannot grow it without limit (2026-09-25 审计 P3).
_MAX_FILE_LOCKS = 512


class ScanBudget:
    """Bound a filesystem walk by visited entries and wall-clock time.

    A workspace is not a trusted size.  Without a budget, a pattern that matches
    nothing (or a tree far larger than the result cap) walks every entry there
    is; the caller cannot tell a slow scan from a hung one.  Workers consult the
    budget between entries so an exhausted scan returns what it has instead of
    running to completion.
    """

    def __init__(self, max_entries: int, time_budget_seconds: float) -> None:
        self._max_entries = max(1, int(max_entries))
        self._deadline = time.monotonic() + max(0.1, float(time_budget_seconds))
        self.visited = 0
        self.exhausted = False

    def visit(self) -> bool:
        """Count one visited entry; ``False`` once the budget is spent."""
        self.visited += 1
        if self.visited > self._max_entries or time.monotonic() > self._deadline:
            self.exhausted = True
            return False
        return True


def read_file_bytes(path: str | Path) -> bytes:
    """Read a file without applying platform newline or encoding transforms."""
    return Path(path).read_bytes()


def decode_utf8(data: bytes) -> str:
    """Decode file bytes strictly as UTF-8."""
    return data.decode("utf-8")


def compute_sha256(data: bytes) -> str:
    """Return the externally visible hash format used by workspace tools."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """Replace *path* with *data* only after the complete payload is durable.

    The temporary file is created beside the target so ``os.replace`` stays on
    the same filesystem.  Any error before replacement leaves an existing
    target untouched.
    """
    target = Path(path)
    temporary_path: Path | None = None
    file_descriptor = -1
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=str(target.parent),
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(file_descriptor, "wb") as stream:
            file_descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if file_descriptor != -1:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                # The original write/replace exception is more useful to the
                # caller than a best-effort temporary-file cleanup failure.
                pass


def _file_lock_key(path: str | Path) -> str:
    resolved = Path(path).resolve()
    return os.path.normcase(os.path.normpath(str(resolved)))


def _get_file_lock(path: str | Path) -> asyncio.Lock:
    key = _file_lock_key(path)
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(key)
        if lock is None:
            if len(_FILE_LOCKS) >= _MAX_FILE_LOCKS:
                # 每个不同路径一个锁，进程内只增不减（2026-09-25 审计 P3）：
                # 超限时先丢掉当前没被持有的锁。
                for stale in [item for item, held in _FILE_LOCKS.items() if not held.locked()]:
                    del _FILE_LOCKS[stale]
                    if len(_FILE_LOCKS) < _MAX_FILE_LOCKS:
                        break
            lock = asyncio.Lock()
            _FILE_LOCKS[key] = lock
        return lock


@asynccontextmanager
async def file_lock(path: str | Path) -> AsyncIterator[None]:
    """Serialize workspace operations targeting the same resolved path."""
    lock = _get_file_lock(path)
    async with lock:
        yield


def _failed_result(
    call: ToolCall,
    error_code: str,
    message: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="failed",
        error=message,
        error_code=error_code,
        metadata=dict(metadata or {}),
    )


def _context_mismatch_result(
    call: ToolCall,
    path_str: str,
    matches: list[tuple[int, int]],
    before_context: str | None,
    after_context: str | None,
) -> ToolResult:
    suspected_null_string_fields = [
        field_name
        for field_name, value in (
            ("before_context", before_context),
            ("after_context", after_context),
        )
        if value == "null"
    ]
    metadata: dict[str, Any] = {"old_string_match_count": len(matches)}
    if suspected_null_string_fields:
        metadata["suspected_null_string_fields"] = suspected_null_string_fields
        fields = ", ".join(suspected_null_string_fields)
        message = (
            f"Context did not match any occurrence of old_string in {path_str}; "
            f"{fields} received the literal string \"null\". "
            "Pass JSON null (without quotes) or omit that field when no context constraint is intended."
        )
    else:
        message = f"Context did not match any occurrence of old_string in {path_str}"
    return _failed_result(call, "context_mismatch", message, metadata=metadata)


def _find_non_overlapping_occurrences(content: str, needle: str) -> list[tuple[int, int]]:
    positions: list[tuple[int, int]] = []
    offset = 0
    while True:
        start = content.find(needle, offset)
        if start < 0:
            return positions
        end = start + len(needle)
        positions.append((start, end))
        offset = end


def _context_matches(
    content: str,
    start: int,
    end: int,
    before_context: str | None,
    after_context: str | None,
) -> bool:
    if before_context is not None:
        before_start = start - len(before_context)
        if before_start < 0 or content[before_start:start] != before_context:
            return False
    if after_context is not None and content[end:end + len(after_context)] != after_context:
        return False
    return True


def _selected_content_hash(
    content: str,
    start: int,
    end: int,
    before_context: str | None,
    after_context: str | None,
) -> str:
    local_start = start - len(before_context or "") if before_context is not None else start
    local_end = end + len(after_context or "") if after_context is not None else end
    return compute_sha256(content[local_start:local_end].encode("utf-8"))


def resolve_read_resource_path(
    path: str | Path,
    work_root: str | Path,
    resource_roots: tuple[Path, ...] = (),
    *,
    allow_outside: bool = True,
) -> tuple[Path, Path]:
    """Resolve a read/search target, permissive by default.

    The workspace boundary is no longer enforced (2026-09-27); an explicit
    ``allow_outside=False`` restores the old restriction for callers that want
    it.
    """
    root = Path(work_root).resolve()
    raw = Path(path)
    roots = tuple(item.resolve() for item in resource_roots)

    if raw.is_absolute():
        resolved = raw.resolve()
        for candidate_root in (root, *roots):
            if is_within_path(resolved, candidate_root):
                return resolved, candidate_root
        if allow_outside:
            # Out-of-workspace absolute path: treat the target itself as the
            # access root so search/read relative URIs stay consistent.
            return resolved, resolved
        raise ValueError(f"Path '{path}' is outside work_root '{work_root}'")

    primary = (root / raw).resolve()
    if not is_within_path(primary, root):
        if allow_outside:
            return primary, primary
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
        max_search_scan_entries: int = DEFAULT_MAX_SEARCH_SCAN_ENTRIES,
        search_time_budget_seconds: float = DEFAULT_SEARCH_TIME_BUDGET_SECONDS,
        max_search_file_bytes: int = DEFAULT_MAX_SEARCH_FILE_BYTES,
        allow_access_outside_workdir: AccessOutsideWorkdir = False,
    ) -> None:
        self._work_root = Path(work_root).resolve()
        self._max_list_items = max_list_items
        self._max_text_length = max_text_length
        self._max_search_results = max_search_results
        self._max_search_scan_entries = max(1, int(max_search_scan_entries))
        self._search_time_budget_seconds = max(0.1, float(search_time_budget_seconds))
        self._max_search_file_bytes = max(1, int(max_search_file_bytes))
        self._allow_access_outside_workdir = allow_access_outside_workdir
        self._resource_roots: set[Path] = set()

    def _scan_budget(self) -> ScanBudget:
        return ScanBudget(self._max_search_scan_entries, self._search_time_budget_seconds)

    def _search_timeout_seconds(self) -> float:
        return self._search_time_budget_seconds + SEARCH_TIMEOUT_SLACK_SECONDS

    def _scan_budget_note(self, budget: ScanBudget) -> str:
        return SCAN_BUDGET_NOTE.format(visited=budget.visited, budget=self._search_time_budget_seconds)

    def _search_timeout_result(self, call: ToolCall, path_str: str) -> ToolResult:
        seconds = self._search_timeout_seconds()
        return _failed_result(
            call,
            "search_timeout",
            f"Search aborted after {seconds:g}s without finishing the scan of {path_str}. "
            "The workspace is too large for an unbounded scan; narrow 'path' or 'pattern' and retry.",
        )

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
        args = call.arguments if isinstance(call.arguments, dict) else {}
        if "path" not in args:
            return _failed_result(call, "missing_argument", "Missing 'path' argument")
        path_str = args["path"]
        if not isinstance(path_str, str):
            return _failed_result(call, "invalid_argument", "'path' must be a string")
        if not path_str.strip():
            return _failed_result(call, "missing_argument", "Missing 'path' argument")

        try:
            resolved, access_root = resolve_read_resource_path(
                path_str, self._work_root, self.resource_roots(),
                allow_outside=_access_outside_enabled(self._allow_access_outside_workdir)
            )
        except ValueError as exc:
            return _failed_result(call, "path_outside_root", str(exc))

        if not resolved.is_file():
            return _failed_result(call, "file_not_found", f"File not found: {path_str}")

        try:
            async with file_lock(resolved):
                # Disk reads of an arbitrarily large file belong off the event
                # loop; the read itself is unbounded by design (tools report the
                # full-file hash), so blocking here would freeze every RPC.
                raw_bytes = await asyncio.to_thread(read_file_bytes, resolved)
        except FileNotFoundError:
            return _failed_result(call, "file_not_found", f"File not found: {path_str}")
        except OSError as exc:
            return _failed_result(call, "read_failed", f"Read error: {exc}")
        file_hash = compute_sha256(raw_bytes)

        document_metadata: dict[str, Any] = {}
        image_data_url: str | None = None
        try:
            normalized = await asyncio.to_thread(
                normalize_document,
                resolved,
                workspace_root=self._work_root,
                max_text_length=self._max_text_length,
            )
        except DocumentNormalizationError as exc:
            return _failed_result(
                call,
                "read_failed",
                f"Document normalize error for {path_str}: {exc}",
                metadata={"file_hash": file_hash},
            )
        if normalized is not None:
            content = normalized.markdown
            document_metadata = {
                "document_format": normalized.document_format,
                "content_trust": "untrusted",
                "warnings": list(normalized.warnings),
                "assets": list(normalized.asset_paths),
            }
        elif resolved.suffix.lower() in IMAGE_MIME_TYPES:
            # 图片：二进制读取 + base64 data URL。像素内容不放进文本（会变乱码），
            # 而是以 image_url 块随工具结果返回，由 base_agent 按模型 capability 决定是否发送。
            mime = IMAGE_MIME_TYPES[resolved.suffix.lower()]
            image_data_url = f"data:{mime};base64,{base64.b64encode(raw_bytes).decode('ascii')}"
            rel_preview = relative_workspace_uri(resolved, access_root)
            content = (
                f"图片文件: {rel_preview}（{format_file_size(len(raw_bytes))}）。"
                "像素内容以图片形式随本工具结果返回，支持图片输入的模型可直接查看。"
            )
        else:
            try:
                content = decode_utf8(raw_bytes)
            except UnicodeDecodeError as exc:
                return _failed_result(
                    call,
                    "invalid_utf8",
                    f"File is not valid UTF-8: {exc}",
                    metadata={"file_hash": file_hash},
                )

        try:
            stat = resolved.stat()
            file_size = len(raw_bytes)
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            file_size = len(raw_bytes)
            mtime = "unknown"
        total_lines = line_count(content)

        truncated = False
        if len(content) > self._max_text_length:
            content = content[: self._max_text_length]
            truncated = True

        try:
            content_hash = compute_sha256(content.encode("utf-8"))
        except UnicodeError as exc:
            return _failed_result(
                call,
                "invalid_utf8",
                f"File content cannot be represented as UTF-8: {exc}",
                metadata={"file_hash": file_hash},
            )
        version_metadata = {
            "file_hash": file_hash,
            "start": 0,
            "end": len(content),
            "content_hash": content_hash,
        }

        meta_suffix = f"\n[file: {total_lines} lines, {format_file_size(file_size)}, modified {mtime}]"
        suffix = ("\n[... truncated]" if truncated else "") + meta_suffix
        rel = relative_workspace_uri(resolved, access_root)
        artifact_metadata = {
            "path": rel,
            "line_count": total_lines,
            "size_bytes": file_size,
            "modified": mtime,
            "truncated": truncated,
            **version_metadata,
            **document_metadata,
        }
        result_metadata = dict(artifact_metadata)
        if image_data_url:
            # 图片数据 URL 进 metadata：LLM 侧 base_agent 读取组装 image_url 块，
            # UI 侧 MessageView.imageSrc 直接渲染缩略图。
            artifact_metadata[IMAGE_DATA_URL_METADATA_KEY] = image_data_url
            result_metadata[IMAGE_DATA_URL_METADATA_KEY] = image_data_url
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
                    metadata=artifact_metadata,
                )
            ],
            metadata={**result_metadata, **version_metadata},
        )

    async def list_dir(self, call: ToolCall) -> ToolResult:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        raw_path = args.get("path")
        path_str = raw_path if isinstance(raw_path, str) and raw_path.strip() else "."
        try:
            resolved, _access_root = resolve_read_resource_path(
                path_str, self._work_root, self.resource_roots(),
                allow_outside=_access_outside_enabled(self._allow_access_outside_workdir)
            )
        except ValueError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=str(exc))

        if not resolved.is_dir():
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Not a directory: {path_str}")

        # Listing plus a stat per entry is synchronous disk work; a directory
        # with a very large number of entries must not occupy the event loop.
        def collect() -> list[str]:
            entries = sorted(resolved.iterdir())
            total = len(entries)
            limited = entries[: self._max_list_items]
            collected: list[str] = []
            for entry in limited:
                if entry.is_dir():
                    collected.append(f"{entry.name}/")
                else:
                    try:
                        stat = entry.stat()
                        size = format_file_size(stat.st_size)
                        mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                        collected.append(f"{entry.name}\t{size}\t{mtime}")
                    except OSError:
                        collected.append(f"{entry.name}")
            if total > self._max_list_items:
                collected.append(f"[... {total - self._max_list_items} more entries]")
            return collected

        try:
            lines = await asyncio.to_thread(collect)
        except OSError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"List error: {exc}")

        return ToolResult(call_id=call.id, name=call.name, status="ok", content="\n".join(lines))

    async def search_files(self, call: ToolCall) -> ToolResult:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        raw_pattern = args.get("pattern")
        pattern = raw_pattern if isinstance(raw_pattern, str) and raw_pattern.strip() else "*"
        raw_path = args.get("path")
        path_str = raw_path if isinstance(raw_path, str) and raw_path.strip() else "."
        try:
            search_root, access_root = resolve_read_resource_path(
                path_str, self._work_root, self.resource_roots(),
                allow_outside=_access_outside_enabled(self._allow_access_outside_workdir)
            )
        except ValueError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=str(exc))
        if not search_root.is_dir():
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Not a directory: {path_str}")

        budget = self._scan_budget()
        try:
            matches, total_seen = await asyncio.wait_for(
                asyncio.to_thread(
                    self._scan_files_sync, search_root, access_root, pattern, budget
                ),
                timeout=self._search_timeout_seconds(),
            )
        except TimeoutError:
            return self._search_timeout_result(call, path_str)
        except OSError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Search error: {exc}")

        lines = list(matches)
        if total_seen > self._max_search_results:
            lines.append(f"[... at least {total_seen - self._max_search_results} more matches]")
        if budget.exhausted:
            lines.append(self._scan_budget_note(budget))
        metadata = {
            "scanned_entries": budget.visited,
            "scan_exhausted": budget.exhausted,
            "match_count": len(matches),
        }

        if not lines:
            content = (
                SCANNED_NOTHING_FOUND.format(visited=budget.visited)
                if budget.exhausted
                else "No files found"
            )
            return ToolResult(
                call_id=call.id, name=call.name, status="ok", content=content, metadata=metadata
            )

        return ToolResult(
            call_id=call.id, name=call.name, status="ok", content="\n".join(lines), metadata=metadata
        )

    def _scan_files_sync(
        self,
        search_root: Path,
        access_root: Path,
        pattern: str,
        budget: ScanBudget,
    ) -> tuple[list[str], int]:
        """Walk ``search_root`` for matching names until the result or scan cap.

        Runs in a worker thread: the walk is synchronous and must never occupy
        the event loop.
        """
        matches: list[str] = []
        total_seen = 0
        for root, dirs, files in os.walk(search_root):
            dirs[:] = [d for d in dirs if d not in SKIP_SEARCH_DIRS]
            if not budget.visit():
                break
            for fname in files:
                if not budget.visit():
                    break
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
            if budget.exhausted:
                break
            if len(matches) >= self._max_search_results and total_seen > self._max_search_results:
                break
        return sorted(matches), total_seen

    async def search_content(self, call: ToolCall) -> ToolResult:
        pattern = call.arguments.get("pattern", "") if isinstance(call.arguments, dict) else ""
        if not pattern:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error="Missing 'pattern' argument")
        raw_path = call.arguments.get("path") if isinstance(call.arguments, dict) else None
        path_str = raw_path if isinstance(raw_path, str) and raw_path.strip() else "."
        try:
            search_root, access_root = resolve_read_resource_path(
                path_str, self._work_root, self.resource_roots(),
                allow_outside=_access_outside_enabled(self._allow_access_outside_workdir)
            )
        except ValueError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=str(exc))
        if not search_root.is_file() and not search_root.is_dir():
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Not a directory: {path_str}")

        budget = self._scan_budget()
        try:
            results, skipped_files = await asyncio.wait_for(
                asyncio.to_thread(
                    self._scan_content_sync, search_root, access_root, pattern, budget
                ),
                timeout=self._search_timeout_seconds(),
            )
        except TimeoutError:
            return self._search_timeout_result(call, path_str)
        except OSError as exc:
            return ToolResult(call_id=call.id, name=call.name, status="failed", error=f"Search error: {exc}")

        metadata = {
            "scanned_entries": budget.visited,
            "scan_exhausted": budget.exhausted,
            "match_count": len(results),
            "skipped_files": skipped_files,
        }
        if not results:
            content = (
                SCANNED_NOTHING_FOUND.format(visited=budget.visited)
                if budget.exhausted
                else "No matches found"
            )
            if skipped_files:
                content += "\n" + self._skipped_files_note(skipped_files)
            return ToolResult(
                call_id=call.id, name=call.name, status="ok", content=content, metadata=metadata
            )

        content = "\n".join(results)
        if len(content) > self._max_text_length:
            content = content[: self._max_text_length] + "\n[... truncated]"
        if budget.exhausted:
            content += "\n" + self._scan_budget_note(budget)
        if skipped_files:
            content += "\n" + self._skipped_files_note(skipped_files)

        return ToolResult(
            call_id=call.id, name=call.name, status="ok", content=content, metadata=metadata
        )

    def _iter_search_files(self, search_root: Path) -> Any:
        if search_root.is_file():
            yield search_root
            return
        for root, dirs, files in os.walk(search_root):
            dirs[:] = [d for d in dirs if d not in SKIP_SEARCH_DIRS]
            for fname in files:
                yield Path(root) / fname

    def _skipped_files_note(self, skipped_files: int) -> str:
        return SKIPPED_FILES_NOTE.format(count=skipped_files, limit=self._max_search_file_bytes)

    def _scan_content_sync(
        self,
        search_root: Path,
        access_root: Path,
        pattern: str,
        budget: ScanBudget,
    ) -> tuple[list[str], int]:
        """Match ``pattern`` line by line until the result or scan cap.

        Runs in a worker thread.  Each file is read with a byte cap so a single
        multi-GB file can neither exhaust memory nor stall the scan; binary
        files are skipped rather than decoded into garbage matches.
        """
        results: list[str] = []
        count = 0
        skipped_files = 0
        for fpath in self._iter_search_files(search_root):
            if not budget.visit():
                break
            try:
                resolved = fpath.resolve()
                if not is_within_path(resolved, access_root):
                    continue
                with fpath.open("rb") as stream:
                    data = stream.read(self._max_search_file_bytes + 1)
                if len(data) > self._max_search_file_bytes or b"\0" in data:
                    skipped_files += 1
                    continue
                text = data.decode("utf-8", errors="ignore")
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
        return results, skipped_files


def make_write_file_handler(
    work_root: Path,
    *,
    allow_access_outside_workdir: AccessOutsideWorkdir = False,
) -> Callable[[ToolCall], Awaitable[ToolResult]]:
    async def write_file(call: ToolCall) -> ToolResult:
        return await write_file_tool(
            call,
            work_root=work_root,
            allow_access_outside_workdir=allow_access_outside_workdir,
        )

    return write_file


def make_edit_file_handler(
    work_root: Path,
    *,
    allow_access_outside_workdir: AccessOutsideWorkdir = False,
) -> Callable[[ToolCall], Awaitable[ToolResult]]:
    async def edit_file(call: ToolCall) -> ToolResult:
        return await edit_file_tool(
            call,
            work_root=work_root,
            allow_access_outside_workdir=allow_access_outside_workdir,
        )

    return edit_file


async def write_file_tool(
    call: ToolCall,
    *,
    work_root: Path,
    allow_access_outside_workdir: AccessOutsideWorkdir = False,
) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    if "path" not in args:
        return _failed_result(call, "missing_argument", "Missing 'path' argument")
    path_str = args["path"]
    if not isinstance(path_str, str):
        return _failed_result(call, "invalid_argument", "'path' must be a string")
    if not path_str.strip():
        return _failed_result(call, "missing_argument", "Missing 'path' argument")
    if "content" not in args:
        return _failed_result(call, "missing_argument", "Missing 'content' argument")
    content = args["content"]
    if not isinstance(content, str):
        return _failed_result(call, "invalid_argument", "'content' must be a string")

    expected_file_hash = args.get("expected_file_hash")
    if expected_file_hash is not None and not isinstance(expected_file_hash, str):
        return _failed_result(call, "invalid_argument", "'expected_file_hash' must be a string or null")
    # Models fill the field with "null" when they mean no guard; keeping it as a
    # hash would turn a create into a version-checked overwrite.
    expected_file_hash = optional_string(expected_file_hash) or None
    must_not_exist = args.get("must_not_exist")
    if must_not_exist is not None and type(must_not_exist) is not bool:
        return _failed_result(call, "invalid_argument", "'must_not_exist' must be a boolean or null")

    try:
        new_bytes = content.encode("utf-8")
    except UnicodeError as exc:
        return _failed_result(call, "invalid_utf8", f"Content is not valid UTF-8: {exc}")

    try:
        resolved = validate_workspace_path(
            path_str,
            work_root,
            allow_outside=_access_outside_enabled(allow_access_outside_workdir),
        )
    except ValueError as exc:
        return _failed_result(call, "path_outside_root", str(exc))

    async with file_lock(resolved):
        exists_before = resolved.exists()
        if must_not_exist is True and exists_before:
            return _failed_result(call, "file_already_exists", f"File already exists: {path_str}")
        if exists_before and not resolved.is_file():
            return _failed_result(call, "write_failed", f"Target is not a file: {path_str}")

        old_bytes = b""
        old_file_hash: str | None = None
        if exists_before:
            try:
                old_bytes = read_file_bytes(resolved)
            except FileNotFoundError:
                exists_before = False
            except OSError as exc:
                return _failed_result(call, "write_failed", f"Read error before overwrite: {exc}")

        if exists_before:
            old_file_hash = compute_sha256(old_bytes)
            if expected_file_hash is not None and old_file_hash != expected_file_hash:
                return _failed_result(
                    call,
                    "file_version_changed",
                    "The file changed since it was read.",
                    metadata={
                        "expected_file_hash": expected_file_hash,
                        "current_file_hash": old_file_hash,
                    },
                )
            try:
                old_content = decode_utf8(old_bytes)
            except UnicodeDecodeError as exc:
                return _failed_result(
                    call,
                    "invalid_utf8",
                    f"Existing file is not valid UTF-8: {exc}",
                    metadata={"current_file_hash": old_file_hash},
                )
        else:
            old_content = ""
            if expected_file_hash is not None:
                return _failed_result(
                    call,
                    "file_not_found",
                    f"File not found: {path_str}",
                    metadata={"expected_file_hash": expected_file_hash},
                )

        # Recheck preconditions immediately before replacement.  This closes
        # the most important TOCTOU window for callers using a version guard.
        if expected_file_hash is not None or must_not_exist is True:
            current_exists = resolved.exists()
            if must_not_exist is True and current_exists:
                return _failed_result(call, "file_already_exists", f"File already exists: {path_str}")
            if expected_file_hash is not None:
                if not current_exists or not resolved.is_file():
                    return _failed_result(call, "file_not_found", f"File not found: {path_str}")
                try:
                    latest_hash = compute_sha256(read_file_bytes(resolved))
                except FileNotFoundError:
                    return _failed_result(call, "file_not_found", f"File not found: {path_str}")
                except OSError as exc:
                    return _failed_result(call, "write_failed", f"Read error before overwrite: {exc}")
                if latest_hash != expected_file_hash:
                    return _failed_result(
                        call,
                        "file_version_changed",
                        "The file changed since it was read.",
                        metadata={
                            "expected_file_hash": expected_file_hash,
                            "current_file_hash": latest_hash,
                        },
                    )

        rel = relative_workspace_uri(resolved, Path(work_root).resolve())
        lines = content.split("\n")
        total_lines = line_count(content)
        action = "Overwrote" if exists_before else "Created"
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

        try:
            atomic_write_bytes(resolved, new_bytes)
        except OSError as exc:
            return _failed_result(call, "write_failed", f"Write error: {exc}")

        new_file_hash = compute_sha256(new_bytes)
        metadata = {
            "path": rel,
            "action": "overwrite" if exists_before else "create",
            "old_line_count": line_count(old_content),
            "new_line_count": total_lines,
            "old_size": len(old_content),
            "new_size": len(content),
            "old_size_bytes": len(old_bytes),
            "new_size_bytes": len(new_bytes),
            "file_hash": new_file_hash,
            **({"old_file_hash": old_file_hash} if old_file_hash is not None else {}),
        }
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
                    metadata=dict(metadata),
                )
            ],
            metadata=metadata,
        )


async def edit_file_tool(
    call: ToolCall,
    *,
    work_root: Path,
    allow_access_outside_workdir: AccessOutsideWorkdir = False,
) -> ToolResult:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    if "path" not in args:
        return _failed_result(call, "missing_argument", "Missing 'path' argument")
    path_str = args["path"]
    if not isinstance(path_str, str):
        return _failed_result(call, "invalid_argument", "'path' must be a string")
    if not path_str.strip():
        return _failed_result(call, "missing_argument", "Missing 'path' argument")
    if "old_string" not in args:
        return _failed_result(call, "missing_argument", "Missing 'old_string' argument")
    old_string = args["old_string"]
    if not isinstance(old_string, str):
        return _failed_result(call, "invalid_argument", "'old_string' must be a string")
    if not old_string:
        return _failed_result(call, "old_string_empty", "'old_string' must not be empty")
    if "new_string" not in args:
        return _failed_result(call, "missing_argument", "Missing 'new_string' argument")
    new_string = args["new_string"]
    if not isinstance(new_string, str):
        return _failed_result(call, "invalid_argument", "'new_string' must be a string")

    expected_file_hash = args.get("expected_file_hash")
    if expected_file_hash is not None and not isinstance(expected_file_hash, str):
        return _failed_result(call, "invalid_argument", "'expected_file_hash' must be a string or null")
    # Models fill the field with "null" when they mean no guard; keeping it as a
    # hash would turn a create into a version-checked overwrite.
    expected_file_hash = optional_string(expected_file_hash) or None
    expected_content_hash = args.get("expected_content_hash")
    if expected_content_hash is not None and not isinstance(expected_content_hash, str):
        return _failed_result(call, "invalid_argument", "'expected_content_hash' must be a string or null")
    before_context = args.get("before_context")
    if before_context is not None and not isinstance(before_context, str):
        return _failed_result(call, "invalid_argument", "'before_context' must be a string or null")
    after_context = args.get("after_context")
    if after_context is not None and not isinstance(after_context, str):
        return _failed_result(call, "invalid_argument", "'after_context' must be a string or null")
    occurrence = args.get("occurrence")
    if occurrence is not None and (type(occurrence) is not int or occurrence < 1):
        return _failed_result(call, "invalid_argument", "'occurrence' must be a positive 1-based integer or null")

    try:
        resolved = validate_workspace_path(
            path_str,
            work_root,
            allow_outside=_access_outside_enabled(allow_access_outside_workdir),
        )
    except ValueError as exc:
        return _failed_result(call, "path_outside_root", str(exc))

    if not resolved.is_file():
        return _failed_result(call, "file_not_found", f"File not found: {path_str}")

    async with file_lock(resolved):
        try:
            current_bytes = read_file_bytes(resolved)
        except FileNotFoundError:
            return _failed_result(call, "file_not_found", f"File not found: {path_str}")
        except OSError as exc:
            return _failed_result(call, "read_failed", f"Read error: {exc}")
        current_file_hash = compute_sha256(current_bytes)
        if expected_file_hash is not None and current_file_hash != expected_file_hash:
            return _failed_result(
                call,
                "file_version_changed",
                "The file changed since it was read.",
                metadata={
                    "expected_file_hash": expected_file_hash,
                    "current_file_hash": current_file_hash,
                },
            )
        try:
            content = decode_utf8(current_bytes)
        except UnicodeDecodeError as exc:
            return _failed_result(
                call,
                "invalid_utf8",
                f"File is not valid UTF-8: {exc}",
                metadata={"current_file_hash": current_file_hash},
            )

        matches = _find_non_overlapping_occurrences(content, old_string)
        if not matches:
            return _failed_result(call, "old_string_not_found", f"old_string not found in {path_str}")

        has_context = before_context is not None or after_context is not None
        candidates = [
            (start, end)
            for start, end in matches
            if not has_context or _context_matches(content, start, end, before_context, after_context)
        ]
        if has_context and not candidates:
            return _context_mismatch_result(
                call,
                path_str,
                matches,
                before_context,
                after_context,
            )
        if occurrence is not None:
            if occurrence > len(candidates):
                return _failed_result(
                    call,
                    "context_mismatch" if has_context else "old_string_not_found",
                    f"Occurrence {occurrence} is not available for old_string in {path_str}",
                )
            match_offset, match_end = candidates[occurrence - 1]
        else:
            if len(candidates) > 1:
                return _failed_result(
                    call,
                    "ambiguous_match",
                    f"old_string found {len(candidates)} times in {path_str} - provide context or a 1-based occurrence",
                )
            match_offset, match_end = candidates[0]

        local_content_hash = _selected_content_hash(
            content,
            match_offset,
            match_end,
            before_context,
            after_context,
        )
        if expected_content_hash is not None and local_content_hash != expected_content_hash:
            return _failed_result(
                call,
                "content_version_changed",
                "The selected file content changed since it was read.",
                metadata={
                    "expected_content_hash": expected_content_hash,
                    "current_content_hash": local_content_hash,
                    "current_file_hash": current_file_hash,
                },
            )

        new_content = content[:match_offset] + new_string + content[match_end:]
        try:
            new_bytes = new_content.encode("utf-8")
        except UnicodeError as exc:
            return _failed_result(
                call,
                "invalid_utf8",
                f"Replacement content is not valid UTF-8: {exc}",
                metadata={"current_file_hash": current_file_hash},
            )

        # An edit is always based on the exact bytes read above.  Re-read just
        # before replacement so an external editor cannot silently be lost.
        try:
            latest_bytes = read_file_bytes(resolved)
        except FileNotFoundError:
            return _failed_result(call, "file_not_found", f"File not found: {path_str}")
        except OSError as exc:
            return _failed_result(call, "read_failed", f"Read error before edit: {exc}")
        latest_file_hash = compute_sha256(latest_bytes)
        if latest_file_hash != current_file_hash:
            return _failed_result(
                call,
                "file_version_changed",
                "The file changed while the edit was being prepared.",
                metadata={"current_file_hash": latest_file_hash},
            )

        match_line_no = content.count("\n", 0, match_offset) + 1
        try:
            atomic_write_bytes(resolved, new_bytes)
        except OSError as exc:
            return _failed_result(call, "write_failed", f"Write error: {exc}")

        rel = relative_workspace_uri(resolved, Path(work_root).resolve())
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
        new_file_hash = compute_sha256(new_bytes)
        raw_occurrence = matches.index((match_offset, match_end)) + 1
        metadata = {
            "path": rel,
            "action": "edit",
            "start_line": match_line_no,
            "start": match_offset,
            "end": match_end,
            "occurrence": raw_occurrence,
            "old_line_count": line_count(content),
            "new_line_count": total_lines,
            "old_size": len(content),
            "new_size": len(new_content),
            "old_size_bytes": len(current_bytes),
            "new_size_bytes": len(new_bytes),
            "old_file_hash": current_file_hash,
            "file_hash": new_file_hash,
            "content_hash": local_content_hash,
            "matched_content_hash": local_content_hash,
        }
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
                    metadata=dict(metadata),
                )
            ],
            metadata=metadata,
        )


__all__ = [
    "DEFAULT_MAX_LIST_ITEMS",
    "DEFAULT_MAX_SEARCH_FILE_BYTES",
    "DEFAULT_MAX_SEARCH_RESULTS",
    "DEFAULT_MAX_SEARCH_SCAN_ENTRIES",
    "DEFAULT_MAX_TEXT_LENGTH",
    "DEFAULT_SEARCH_TIME_BUDGET_SECONDS",
    "SCAN_BUDGET_NOTE",
    "SCANNED_NOTHING_FOUND",
    "SEARCH_TIMEOUT_SLACK_SECONDS",
    "SKIPPED_FILES_NOTE",
    "SKIP_SEARCH_DIRS",
    "ScanBudget",
    "WorkspaceReadOnlyTools",
    "atomic_write_bytes",
    "compute_sha256",
    "decode_utf8",
    "edit_file_tool",
    "file_lock",
    "make_edit_file_handler",
    "make_write_file_handler",
    "read_file_bytes",
    "resolve_read_resource_path",
    "unified_diff",
    "write_file_tool",
]
