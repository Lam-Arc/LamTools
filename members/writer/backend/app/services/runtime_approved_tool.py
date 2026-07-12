from __future__ import annotations

import asyncio
from typing import Any

from app.core.writer.core_kernel_adapter import ReadWriteToolExecutor
from lamtools_core.tool import ToolCall
from lamtools_core.tool.approval_continuation import ApprovedToolExecution


APPROVABLE_TOOL_NAMES = {"run_command", "run_tests"}


async def execute_approved_tool(
    tool_call: dict[str, Any],
    *,
    work_root: str,
    handler: Any | None = None,
) -> ApprovedToolExecution:
    tool_name = str(tool_call.get("name") or "")
    tool_args = tool_call.get("arguments") if isinstance(tool_call.get("arguments"), dict) else {}
    tool_call_id = str(tool_call.get("id") or "approved-tool")
    if tool_name not in APPROVABLE_TOOL_NAMES:
        raise ValueError(f"Tool is not executable through approval continuation: {tool_name}")
    handler = handler or ReadWriteToolExecutor(work_root).as_dict().get(tool_name)
    if handler is None:
        raise ValueError(f"Tool is not executable: {tool_name}")
    result = handler(ToolCall(
        id=tool_call_id,
        name=tool_name,
        arguments=tool_args,
        metadata={"approval_policy": "approved_by_user"},
    ))
    if asyncio.iscoroutine(result):
        result = await result
    content = str(getattr(result, "content", "") or getattr(result, "error", "") or "")
    return ApprovedToolExecution(
        tool_name=tool_name,
        tool_args=tool_args,
        tool_content=content,
        tool_status="completed" if getattr(result, "status", "") == "ok" else "failed",
    )


__all__ = [
    "APPROVABLE_TOOL_NAMES",
    "execute_approved_tool",
]
