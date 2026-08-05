from __future__ import annotations

from typing import Any

from lamtools_core.llm import LLMToolCall
from lamtools_core.tool import ToolResult

from app.core.writer.tool_failure import tool_failure_context, tool_failure_signature

_READ_TOOLS = frozenset({"read_file", "list_dir", "search_files", "search_content"})
_WRITE_TOOLS = frozenset({"write_file", "edit_file", "run_tests", "run_command"})
_GIT_TOOLS = frozenset({"git_status", "git_diff"})

_TOOL_CATEGORIES: dict[str, str] = {
    "web_search": "network_search",
    "web_fetch": "network_fetch",
    "browser_check": "network_fetch",
    "sub_agent": "agent",
}
for _tool in _READ_TOOLS:
    _TOOL_CATEGORIES[_tool] = "file_read"
for _tool in _WRITE_TOOLS:
    _TOOL_CATEGORIES[_tool] = "file_write"
for _tool in _GIT_TOOLS:
    _TOOL_CATEGORIES[_tool] = "git"


def record_tool_outcomes(
    metadata: dict[str, Any],
    tool_calls: list[LLMToolCall],
    tool_results: list[ToolResult],
) -> None:
    recent_tools: list[str] = list(metadata.get("recent_tools", []))
    recent_statuses: list[str] = list(metadata.get("recent_statuses", []))
    recent_failure_signatures: list[str] = list(metadata.get("recent_failure_signatures", []))
    recent_failures: list[str] = list(metadata.get("recent_failures", []))
    recent_category_empty: list[str] = list(metadata.get("recent_category_empty", []))
    written_files: list[str] = list(metadata.get("written_files", []))

    for index, result in enumerate(tool_results):
        recent_tools = _append_limited(recent_tools, result.name, 50)

        status = "ok" if result.status == "ok" else "failed"
        recent_statuses = _append_limited(recent_statuses, status, 50)

        call = tool_calls[index] if index < len(tool_calls) else None
        if result.status == "failed" and call is not None:
            recent_failure_signatures = _append_limited(
                recent_failure_signatures,
                tool_failure_signature(call, result),
                50,
            )
        else:
            recent_failure_signatures = _append_limited(recent_failure_signatures, "", 50)

        if result.status == "failed" and result.error:
            recent_failures = _append_limited(recent_failures, tool_failure_context(result)[:1200], 20)

        recent_category_empty.append(_empty_category_marker(result))

        if result.status == "ok" and result.name in {"write_file", "edit_file"}:
            metadata.pop("test_assertion_repair_required", None)
            path = result.metadata.get("path") if isinstance(result.metadata, dict) else None
            if path:
                written_files = _append_limited(written_files, str(path), 50)

    metadata["recent_tools"] = recent_tools
    metadata["recent_statuses"] = recent_statuses
    metadata["recent_failure_signatures"] = recent_failure_signatures
    metadata["recent_failures"] = recent_failures
    metadata["recent_category_empty"] = recent_category_empty[-40:]
    metadata["written_files"] = written_files

    if all(result.status == "ok" for result in tool_results):
        metadata["forced_continue_count"] = 0


def _append_limited(items: list[str], value: str, limit: int) -> list[str]:
    items.append(value)
    if len(items) > limit:
        return items[-limit:]
    return items


def _empty_category_marker(result: ToolResult) -> str:
    tool_name = result.name
    category = _TOOL_CATEGORIES.get(tool_name, "other")
    if category == "other" and tool_name.startswith("mcp__"):
        if any(marker in tool_name for marker in ("browser_", "playwright")):
            category = "network_fetch"
    content = (result.content or "").strip()
    is_empty = (
        result.status == "failed"
        or (result.status == "ok" and len(content) < 50)
        or content.startswith("[web_search] No results")
        or "not available in this execution environment" in content
        or ("HTTP 403" in content and "web_fetch" in content)
        or ("blocked" in content.lower() and len(content) < 200)
    )
    return category if is_empty else ""
