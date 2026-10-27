"""Execution summaries and safe event reports for the command line."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

# user:“审查后端大文件并拆分”+(按职责独立维护实现，原模块保留导入入口以兼容现有调用。)


def _build_summary(
    *,
    result: Any,
    events: list[Any],
    model_context: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    parts = [_part_summary(event) for event in events if getattr(event, "name", "") == "runtime.part"]
    reasoning = [part["content_len"] for part in parts if part["part_type"] == "reasoning"]
    text = [part["content_len"] for part in parts if part["part_type"] == "text"]
    tool_names = [
        str(part["tool_name"])
        for part in parts
        if part["part_type"] in {"tool_call", "tool_input_delta"} and part.get("tool_name")
    ]
    response_indexes = sorted({part["response_index"] for part in parts if part["response_index"] is not None})
    usage_by_round = [
        dict(event.payload.get("usage"))
        for event in events
        if getattr(event, "name", "") == "runtime.reply_delta"
        and isinstance(getattr(event, "payload", {}).get("usage"), dict)
    ]
    tool_started = [
        event
        for event in events
        if getattr(event, "name", "") == "runtime.tool.started"
    ]
    tool_finished = [
        event
        for event in events
        if getattr(event, "name", "") == "runtime.tool.finished"
    ]
    tool_calls_by_name: dict[str, int] = {}
    call_fingerprints: dict[str, int] = {}
    for event in tool_started:
        payload = event.payload if isinstance(event.payload, dict) else {}
        tool_name = str(payload.get("tool_name") or "unknown")
        tool_calls_by_name[tool_name] = tool_calls_by_name.get(tool_name, 0) + 1
        arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
        canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        fingerprint = hashlib.sha256(f"{tool_name}\0{canonical}".encode("utf-8")).hexdigest()
        call_fingerprints[fingerprint] = call_fingerprints.get(fingerprint, 0) + 1
    failed_tool_calls = sum(
        1
        for event in tool_finished
        if str((event.payload if isinstance(event.payload, dict) else {}).get("status") or "") != "ok"
    )
    repeated_exact_tool_calls = sum(count - 1 for count in call_fingerprints.values() if count > 1)
    event_counts: dict[str, int] = {}
    for event in events:
        name = str(getattr(event, "name", "") or "unknown")
        event_counts[name] = event_counts.get(name, 0) + 1
    state = result.state
    document_path = str(state.metadata.get("document_path") or "") if state is not None else ""
    document_line_count = int(state.metadata.get("document_line_count") or 0) if state is not None else 0
    summary = {
        "ok": False,
        "model": dict(model_context),
        "result": {
            "decision": result.decision,
            "steps_count": len(result.steps),
            "run_id": result.run_id,
            "session_id": result.session_id,
            "final_message": result.message,
        },
        "proof": {
            "has_reasoning_block": any(length > 0 for length in reasoning),
            "max_reasoning_chars": max(reasoning) if reasoning else 0,
            "has_text_block": any(length > 0 for length in text),
            "max_text_chars": max(text) if text else 0,
            "has_tool_call_block": bool(tool_names),
            "tool_names": sorted(set(tool_names)),
            "response_indexes": response_indexes,
            "model_rounds_from_steps": len(result.steps),
            "usage_by_round": usage_by_round,
            "document_path": document_path,
            "document_line_count": document_line_count,
        },
        "execution": {
            "llm_rounds": len(result.steps),
            "tool_calls": len(tool_started),
            "tool_calls_by_name": dict(sorted(tool_calls_by_name.items())),
            "failed_tool_calls": failed_tool_calls,
            "tool_failure_rate": (
                round(failed_tool_calls / len(tool_finished), 6) if tool_finished else 0.0
            ),
            "repeated_exact_tool_calls": repeated_exact_tool_calls,
            "exact_repeat_rate": (
                round(repeated_exact_tool_calls / len(tool_started), 6) if tool_started else 0.0
            ),
            "collected_events": len(events),
            "events_by_name": dict(sorted(event_counts.items())),
        },
        "artifacts": {"run_dir": str(run_dir)},
    }
    summary["ok"] = result.decision == "done"
    return summary


def _part_summary(event: Any) -> dict[str, Any]:
    payload = event.payload if isinstance(event.payload, dict) else {}
    return {
        "response_index": payload.get("response_index"),
        "part_type": str(payload.get("part_type") or ""),
        "status": payload.get("status"),
        "tool_name": payload.get("tool_name"),
        "content_len": len(str(payload.get("content") or "")),
    }


def _redact_event(event: Any) -> dict[str, Any]:
    data = event.to_dict()
    payload = copy.deepcopy(data.get("payload")) if isinstance(data.get("payload"), dict) else {}
    if payload.get("part_type") == "reasoning":
        content = str(payload.get("content") or "")
        payload["content_len"] = len(content)
        payload["content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest() if content else ""
        payload.pop("content", None)
    if payload.get("part_type") == "tool_input_delta":
        _replace_large_stream_field(payload, "arguments_text")
        _replace_large_stream_field(payload, "delta")
    if event.name == "runtime.tool.started" and isinstance(payload.get("arguments"), dict):
        payload["arguments"] = _compact_large_event_strings(payload["arguments"])
    payload.pop("raw", None)
    data["payload"] = _redact_embedded_data_urls(payload)
    if isinstance(data.get("metadata"), dict):
        data["metadata"] = _redact_embedded_data_urls(copy.deepcopy(data["metadata"]))
    return data


def _should_collect_cli_event(event: Any) -> bool:
    return getattr(event, "metadata", {}).get("delivery") != "transient"


def _replace_large_stream_field(payload: dict[str, Any], key: str) -> None:
    value = payload.pop(key, None)
    if not isinstance(value, str) or not value:
        return
    encoded = value.encode("utf-8")
    payload[f"{key}_chars"] = len(value)
    payload[f"{key}_bytes"] = len(encoded)
    payload[f"{key}_sha256"] = hashlib.sha256(encoded).hexdigest()


def _compact_large_event_strings(value: Any, *, threshold_bytes: int = 16_384) -> Any:
    if isinstance(value, dict):
        return {
            key: _compact_large_event_strings(item, threshold_bytes=threshold_bytes)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_compact_large_event_strings(item, threshold_bytes=threshold_bytes) for item in value]
    if not isinstance(value, str):
        return value
    encoded = value.encode("utf-8")
    if len(encoded) <= threshold_bytes:
        return value
    return {
        "redacted": "large_text",
        "chars": len(value),
        "bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "prefix": value[:256],
    }


def _redact_embedded_data_urls(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_embedded_data_urls(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_embedded_data_urls(item) for item in value]
    if not isinstance(value, str) or not value.startswith("data:"):
        return value
    header = value.partition(",")[0]
    encoded = value.encode("utf-8")
    return {
        "redacted": "embedded_data_url",
        "media_type": header[5:].split(";", 1)[0],
        "chars": len(value),
        "bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }
