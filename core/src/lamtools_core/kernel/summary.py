"""Core runtime summary helpers."""

from __future__ import annotations

from typing import Any

from lamtools_core.event import CoreEvent

from .state import KernelResult


def compact_core_events_for_summary(events: list[CoreEvent]) -> list[dict[str, Any]]:
    """Return stable history events for UI reconstruction."""
    compacted: list[dict[str, Any]] = []
    part_positions: dict[str, int] = {}

    for event in events:
        if event.name == "runtime.reply_delta":
            continue

        payload = event.payload or {}
        if event.name == "runtime.part":
            part_id = str(payload.get("part_id") or "")
            item = core_event_to_progress_dict(event)
            response_index = str(payload.get("response_index") or "")
            key = part_id or f"runtime.part:{response_index}:{len(part_positions)}"
            existing = part_positions.get(key)
            if existing is None:
                part_positions[key] = len(compacted)
                compacted.append(item)
            else:
                compacted[existing] = item
            continue

        compacted.append(core_event_to_progress_dict(event))

    return compacted


def build_response_blocks_for_summary(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group model-output items by LLM response."""
    blocks: dict[int, dict[str, Any]] = {}
    fallback_index = 0

    def block_for(raw_index: Any) -> dict[str, Any]:
        nonlocal fallback_index
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            index = fallback_index
            fallback_index += 1
        block = blocks.get(index)
        if block is None:
            block = {"response_index": index, "items": []}
            blocks[index] = block
        return block

    for event in events:
        if event.get("event_name") != "runtime.part":
            continue
        part_type = str(event.get("part_type") or "")
        if part_type not in {"reasoning", "text"}:
            continue
        content = str(event.get("content") or "")
        if not content.strip():
            continue
        block = block_for(event.get("response_index"))
        item_id = str(event.get("part_id") or f"response-{block['response_index']}:{part_type}")
        items = block["items"]
        existing = next((item for item in items if item.get("type") == part_type), None)
        item = {
            "id": item_id,
            "type": part_type,
            "status": event.get("status") or "completed",
            "label": event.get("label") or ("思考" if part_type == "reasoning" else "输出"),
            "content": content[:25_565],
        }
        if existing is not None:
            existing.update(item)
        else:
            items.append(item)

    return [blocks[index] for index in sorted(blocks)]


def core_event_to_progress_dict(event: CoreEvent) -> dict[str, Any]:
    """Convert a CoreEvent into a lightweight progress dict for rendering."""
    d: dict[str, Any] = {
        "run_id": event.run_id or "",
        "turn_id": event.turn_id or "",
        "event_name": event.name,
        "category": event.category,
    }

    if event.sequence is not None:
        d["step_index"] = event.sequence

    payload = event.payload or {}

    if "tool_name" in payload:
        d["tool_name"] = payload["tool_name"]
    if "call_id" in payload:
        d["call_id"] = payload["call_id"]
    if "response_index" in payload:
        d["response_index"] = payload["response_index"]
    if "status" in payload:
        d["status"] = payload["status"]
    if "attempt" in payload:
        d["attempt"] = payload["attempt"]

    if event.name == "runtime.part":
        part_type = str(payload.get("part_type") or "")
        for key in (
            "part_id",
            "part_type",
            "status",
            "label",
            "detail",
            "tool_name",
            "tool_args",
            "tool_result",
            "tool_error",
            "delta",
            "arguments_text",
            "before_tokens",
            "after_tokens",
            "trigger_tokens",
            "target_tokens",
            "window_tokens",
            "removed_messages",
            "attempt",
            "max_retries",
            "delay_seconds",
            "error_kind",
            "response_index",
        ):
            if key in payload:
                d[key] = payload[key]
        if part_type in {"compaction", "reasoning", "text", "plan", "status"} and "content" in payload:
            d["content"] = str(payload["content"])[:25_565]
        payload_metadata = payload.get("metadata")
        metadata = dict(payload_metadata) if isinstance(payload_metadata, dict) else {}
        metadata.update({
            key: payload[key]
            for key in (
                "before_tokens",
                "after_tokens",
                "trigger_tokens",
                "target_tokens",
                "window_tokens",
                "removed_messages",
                "attempt",
                "max_retries",
                "delay_seconds",
                "error_kind",
            )
            if key in payload
        })
        d["metadata"] = metadata

    if event.name == "runtime.started":
        d["summary"] = "Run started"
    elif event.name == "runtime.done":
        d["summary"] = "Run completed"
    elif event.name == "runtime.failed":
        err = payload.get("error", "")
        d["summary"] = f"Run failed: {err[:100]}" if err else "Run failed"
    elif event.name == "runtime.waiting":
        d["summary"] = "Run waiting for user input"
    elif event.name == "runtime.ended":
        d["summary"] = f"Run ended ({payload.get('decision', 'unknown')})"
    elif event.name == "runtime.reply":
        content = payload.get("content", "")
        d["summary"] = content[:80] if content else "Reply"
    elif event.name == "runtime.tool.started":
        d["summary"] = f"Tool {payload.get('tool_name', '?')} started"
    elif event.name == "runtime.tool.finished":
        d["summary"] = f"Tool {payload.get('tool_name', '?')} finished ({payload.get('status', '?')})"
    elif event.name == "runtime.verification":
        passed = payload.get("passed", False)
        d["summary"] = f"Verification {'passed' if passed else 'failed'}"
    elif event.name == "runtime.repair":
        d["summary"] = "Repair prompt injected"
    elif event.name == "runtime.context_compacted":
        d["summary"] = "Context compacted"
        for key in ("before_tokens", "after_tokens", "trigger_tokens", "target_tokens", "window_tokens", "removed"):
            if key in payload:
                d[key] = payload[key]
    elif event.name == "runtime.part":
        d["summary"] = str(payload.get("label") or payload.get("part_type") or "Part")
    else:
        d["summary"] = event.name

    return d


def summarize_kernel_result(result: KernelResult) -> dict[str, Any]:
    """Produce a lightweight summary of a KernelResult for rendering."""
    md = result.metadata
    core_events = []
    for event in md.get("core_events", []):
        if isinstance(event, dict):
            sanitized = dict(event)
            sanitized.pop("content", None)
            sanitized.pop("prompt", None)
            core_events.append(sanitized)
        else:
            core_events.append(event)
    return {
        "session_id": result.session_id,
        "run_id": result.run_id,
        "decision": result.decision,
        "message": result.message,
        "steps_count": md.get("steps_count", len(result.steps)),
        "core_events": core_events,
        "response_blocks": md.get("response_blocks", []),
        "tool_results_summary": md.get("tool_results_summary", []),
        "verification_summaries": md.get("verification_summaries", []),
        "runtime_metrics": md.get("runtime_metrics", {}),
        "error": result.error,
    }


__all__ = [
    "build_response_blocks_for_summary",
    "compact_core_events_for_summary",
    "core_event_to_progress_dict",
    "summarize_kernel_result",
]
