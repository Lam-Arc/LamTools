from __future__ import annotations

from typing import Any

from lamtools_core.event import CoreEvent
from lamtools_core.kernel import KernelResult


def project_sub_agent_result(
    result: KernelResult,
    nested_events: list[CoreEvent],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    tool_records = _project_tool_records(result)
    reasoning_blocks = _project_reasoning_blocks(nested_events)
    final_text = _final_text(result)
    diagnostics = {
        "runner": "core_kernel",
        "decision": result.decision,
        "parse_status": "unstructured_text" if final_text else "failed",
        "tool_call_count": len(tool_records),
        "event_count": len(nested_events),
    }
    if result.error:
        diagnostics["error"] = result.error
    if result.decision == "wait":
        diagnostics["fallback_reason"] = "approval_pending"
        return {}, tool_records, reasoning_blocks, diagnostics
    if not final_text:
        diagnostics["fallback_reason"] = result.error or "empty_final_output"
        return {}, tool_records, reasoning_blocks, diagnostics
    return {"content": final_text}, tool_records, reasoning_blocks, diagnostics


def _project_reasoning_blocks(nested_events: list[CoreEvent]) -> list[dict[str, Any]]:
    reasoning_by_id: dict[str, dict[str, Any]] = {}
    for event in nested_events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if event.name != "runtime.part" or payload.get("part_type") != "reasoning":
            continue
        content = str(payload.get("content") or "").strip()
        if not content:
            continue
        response_index = str(payload.get("response_index") or "")
        block_id = str(payload.get("part_id") or "")
        if not block_id:
            block_id = f"response:{response_index}:reasoning" if response_index else "reasoning"
        reasoning_by_id[block_id] = {
            "id": block_id,
            "content": content,
            "status": str(payload.get("status") or "completed"),
        }
    return list(reasoning_by_id.values())


def _project_tool_records(result: KernelResult) -> list[dict[str, Any]]:
    tool_records: list[dict[str, Any]] = []
    for step in result.steps:
        for item in step.tool_steps:
            if item.result is None:
                continue
            content_preview = str(item.result.content or item.result.error or "")
            record = {
                "id": item.call.id,
                "call_id": item.call.id,
                "name": item.call.name,
                "tool_name": item.call.name,
                "arguments": item.call.arguments if isinstance(item.call.arguments, dict) else {},
                "args": item.call.arguments if isinstance(item.call.arguments, dict) else {},
                "status": "completed" if item.result.status == "ok" else item.result.status,
                "output": content_preview[:1200],
                "content_preview": content_preview[:1200],
            }
            if item.result.error:
                record["error"] = str(item.result.error)
            if item.result.artifacts:
                record["artifacts"] = [artifact.to_dict() for artifact in item.result.artifacts]
            if item.result.metadata:
                record["metadata"] = dict(item.result.metadata)
            tool_records.append(record)
    return tool_records


def _final_text(result: KernelResult) -> str:
    final_text = str(result.message or "").strip()
    if final_text:
        return final_text
    for step in reversed(result.steps):
        if step.turn is not None and str(step.turn.reply or "").strip():
            return str(step.turn.reply or "").strip()
    return ""
