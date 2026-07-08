from __future__ import annotations

import json
from typing import Any

from lamtools_core.llm import ChatMessage
from lamtools_core.tool import ToolCall, ToolResult

_TOOL_ERROR_HINTS: dict[str, str] = {
    "run_command": (
        "\nHINT: The command could not execute. Check: 1) Is the executable "
        "installed and on PATH? 2) Are you using the correct command name for "
        "this OS (e.g. 'python' vs 'python3', 'dir' vs 'ls')? "
        "3) Try the command manually in a terminal to verify it works. "
        "If the command is unavailable, switch strategy - use an alternative "
        "tool or explain the limitation to the user."
    ),
    "write_file": (
        "\nHINT: File write failed. Check: 1) Does the parent directory exist? "
        "2) Is the path valid for this OS? 3) Is the disk full or write-protected?"
    ),
    "read_file": (
        "\nHINT: File read failed. Check: 1) Does the file exist at that path? "
        "2) Is the path spelled correctly (case-sensitive on Linux)? "
        "3) Try list_dir first to see what files are actually there."
    ),
    "web_search": (
        "\nHINT: Web search failed - the network may be unreachable or the "
        "search API returned no results. Switch to internal knowledge: produce "
        "your best answer from training data, clearly mark confidence levels "
        "(confirmed/likely/speculative), and note that real-time data was unavailable."
    ),
    "web_fetch": (
        "\nHINT: Web fetch failed - the URL may be blocked, unreachable, or "
        "returned an error. Try a different URL, use web_search to find "
        "alternative sources, or fall back to internal knowledge."
    ),
}


def tool_error_hint(tool_name: str, error: str) -> str:
    _ = error
    hint = _TOOL_ERROR_HINTS.get(tool_name, "")
    if not hint:
        hint = (
            "\nHINT: This tool call failed. Do NOT retry the same call with the "
            "same arguments - it will fail again. Switch to a different approach, "
            "use a different tool, or report the limitation to the user."
        )
    return hint


def tool_structured_error_summary(metadata: dict[str, Any] | None) -> str:
    if not isinstance(metadata, dict):
        return ""
    fields = {
        key: metadata.get(key)
        for key in (
            "error_type",
            "error_kind",
            "retryable",
            "recommended_action",
            "server_port",
            "server_probe_url",
            "readiness_url",
        )
        if metadata.get(key) not in (None, "")
    }
    if not fields:
        return ""
    return "\nStructured error: " + json.dumps(fields, ensure_ascii=False)


def agent_failure_reason(runtime_agent: str, metadata: dict[str, Any], content: str) -> str:
    if runtime_agent != "sub":
        return ""
    status = str(metadata.get("status") or "").lower()
    if status in {"blocked", "failed", "error"}:
        return str(metadata.get("error") or content or status).strip()
    if metadata.get("error"):
        return str(metadata["error"]).strip()
    if metadata.get("fallback_reason"):
        return str(metadata["fallback_reason"]).strip()
    diagnostics = metadata.get("diagnostics")
    if isinstance(diagnostics, dict):
        delivery = diagnostics.get("workspace_delivery")
        if isinstance(delivery, dict) and delivery.get("ok") is False:
            return str(delivery.get("error") or diagnostics.get("error") or "SubAgent workspace delivery failed").strip()
        for key in ("error", "fallback_reason", "exception"):
            if diagnostics.get(key):
                return str(diagnostics[key]).strip()
    delivery = metadata.get("workspace_delivery")
    if isinstance(delivery, dict) and delivery.get("ok") is False:
        return str(delivery.get("error") or "SubAgent workspace delivery failed").strip()
    return ""


def agent_tool_facts_for_model(runtime_agent: str, metadata: dict[str, Any]) -> dict[str, Any]:
    if runtime_agent != "sub":
        return {}
    delivery = metadata.get("workspace_delivery")
    if not isinstance(delivery, dict):
        diagnostics = metadata.get("diagnostics")
        if isinstance(diagnostics, dict) and isinstance(diagnostics.get("workspace_delivery"), dict):
            delivery = diagnostics["workspace_delivery"]
        else:
            delivery = {}
    changed_files = (
        metadata.get("changed_files")
        or delivery.get("changed_files")
        or delivery.get("paths")
        or []
    )
    if not isinstance(changed_files, list):
        changed_files = []
    changed_files = [str(item) for item in changed_files if str(item)]
    facts: dict[str, Any] = {
        "type": "sub_agent_result_facts",
        "agent": str(metadata.get("agent_name") or metadata.get("agent") or "sub"),
        "agent_index": str(metadata.get("agent_index") or ""),
        "sub_session_id": str(metadata.get("sub_session_id") or ""),
        "status": "失败" if delivery.get("ok") is False else "完成",
        "changed_files_count": len(changed_files),
        "changed_files": changed_files,
    }
    branch = str(delivery.get("branch") or metadata.get("branch") or "")
    worktree = str(delivery.get("worktree") or metadata.get("worktree") or "")
    if branch:
        facts["branch"] = branch
    if worktree:
        facts["worktree"] = worktree
    if delivery.get("commit"):
        facts["commit"] = str(delivery["commit"])
    if "needs_acceptance" in delivery or "needs_writer_acceptance" in delivery:
        facts["needs_acceptance"] = bool(
            delivery.get("needs_acceptance", delivery.get("needs_writer_acceptance"))
        )
    if "merged" in delivery:
        facts["merged"] = bool(delivery.get("merged"))
    if delivery.get("error"):
        facts["error"] = str(delivery["error"])
    return facts


def format_tool_result_for_model(call: ToolCall, result: ToolResult) -> ChatMessage:
    content = result.content
    if result.error:
        args_summary = ""
        if call.arguments:
            args_str = str(call.arguments)
            if len(args_str) > 300:
                args_str = args_str[:300] + "..."
            args_summary = f"\nTool called: {call.name}({args_str})"
        hint = tool_error_hint(call.name, result.error)
        structured_error = tool_structured_error_summary(result.metadata)
        content = f"[ERROR] {result.error}{args_summary}{structured_error}{hint}"
    elif not content:
        content = "[tool completed with no output]"

    facts = result.metadata.get("tool_facts") if isinstance(result.metadata, dict) else None
    if isinstance(facts, dict) and facts:
        content = (
            f"{content}\n\n"
            "[系统事实]\n"
            f"{json.dumps(facts, ensure_ascii=False, indent=2)}"
        )

    return ChatMessage(
        role="tool",
        content=content,
        tool_call_id=call.id,
        name=call.name,
    )
