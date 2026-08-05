from __future__ import annotations

import json
from hashlib import sha1

from typing import Any

from lamtools_core.tool import ToolCall, ToolResult


def tool_failure_signature(call: ToolCall, result: ToolResult | None) -> str:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    canonical_args = json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
    status = str((result.status if result else "") or "").strip()
    error = str((result.error if result else "") or "").strip()
    content = str((result.content if result else "") or "")
    metadata = result.metadata if result is not None and isinstance(result.metadata, dict) else {}
    stable_metadata = {
        key: metadata.get(key)
        for key in ("exit_code", "timed_out", "error_type")
        if key in metadata
    }
    canonical_metadata = json.dumps(stable_metadata, ensure_ascii=False, sort_keys=True, default=str)
    digest = sha1(
        f"{call.name}\n{canonical_args}\n{status}\n{error}\n{content}\n{canonical_metadata}".encode("utf-8")
    ).hexdigest()[:12]
    return f"{call.name}:{digest}"


def tool_failure_context(result: ToolResult) -> str:
    error = str(result.error or "").strip()
    content = str(result.content or "").strip()
    if result.name not in {"run_tests", "run_command"} or not content:
        return error[:1200]

    markers = (
        "[test_result]",
        "[command]",
        "[exit_code]",
        "FAILED",
        "ERROR",
        "AssertionError",
        "Traceback",
        "assert ",
        "E       ",
        ".py:",
        "test_",
    )
    selected: list[str] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if any(marker in line for marker in markers):
            selected.append(line[:220])
        if len(selected) >= 14:
            break

    details = "\n".join(selected).strip()
    if not details:
        details = content[-1000:]

    if error:
        return f"{result.name}: {error}\n{details}"[:1200]
    return f"{result.name} failed\n{details}"[:1200]


def looks_like_test_assertion_failure(result: ToolResult) -> bool:
    if result.name not in {"run_tests", "run_command"}:
        return False
    text = f"{result.content or ''}\n{result.error or ''}".lower()
    if not any(marker in text for marker in ("pytest", "unittest", "test session starts", "collected ")):
        return False
    if any(marker in text for marker in ("failed", "assertionerror", "assert ", "e       assert")):
        return True
    return False
