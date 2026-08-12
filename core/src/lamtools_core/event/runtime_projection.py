"""Map runtime facts into canonical run item events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any

from lamtools_core.event.run_item import RunItemEvent
from lamtools_core.llm.helpers import (
    _cache_creation_tokens_from_usage,
    _cached_tokens_from_usage,
)

TERMINAL_STATUSES = {"completed", "done", "ok", "failed", "error", "cancelled"}
DEFAULT_RUNTIME_PREVIEW_CHARS = 25565
APPROVAL_OPTIONS = [
    {
        "id": "approve",
        "label": "批准执行",
        "description": "允许后端继续执行这个工具调用。",
        "response": "approve",
    },
    {
        "id": "deny",
        "label": "拒绝执行",
        "description": "不执行这个工具调用，本轮停在等待点。",
        "response": "deny",
    },
]


@dataclass
class RuntimeProjectionInput:
    id: str
    thread_id: str
    group: str
    source: str
    phase: str | None
    status: str | None
    sequence: int | None
    summary: str = ""
    preview: str = ""
    full_text: str = ""
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None


class RuntimeProjectionBuffer:
    def __init__(self) -> None:
        self._pending_parts: dict[str, RuntimeProjectionInput] = {}

    def merge_part_growth(self, fact: RuntimeProjectionInput) -> RuntimeProjectionInput:
        payload = (fact.metadata or {}).get("payload")
        part_id = ""
        if fact.phase == "runtime.part" and isinstance(payload, dict):
            part_id = str(payload.get("part_id") or "")
        if not part_id:
            return fact

        existing = self._pending_parts.get(part_id)
        if existing is None:
            self._pending_parts[part_id] = fact
            return fact

        existing.status = fact.status
        existing.summary = fact.summary
        existing.preview = fact.preview
        existing.full_text = fact.full_text
        existing.metadata = fact.metadata
        existing.created_at = fact.created_at
        return existing


def runtime_group_from_event_name(event_name: str) -> str:
    if event_name.startswith("runtime.tool"):
        return "tool"
    if event_name.startswith("runtime.verification"):
        return "verification"
    if event_name.startswith("runtime.repair"):
        return "verification"
    if event_name in {"runtime.done", "runtime.failed", "runtime.cancelled", "runtime.waiting", "runtime.started"}:
        return "system"
    return "plan"


def runtime_summary_from_event_name(event_name: str, payload: dict[str, Any]) -> str:
    if event_name == "runtime.started":
        return "开始理解任务。"
    if event_name == "runtime.tool.started":
        return f"开始执行工具：{payload.get('tool_name') or 'tool'}"
    if event_name == "runtime.tool.finished":
        return f"工具完成：{payload.get('tool_name') or 'tool'}"
    if event_name == "runtime.verification":
        return str(payload.get("summary") or "正在验证结果。")
    if event_name == "runtime.repair":
        return "根据验证结果调整。"
    if event_name == "runtime.done":
        return str(payload.get("message") or "任务已完成。")
    if event_name == "runtime.failed":
        return str(payload.get("error") or payload.get("message") or "任务失败。")
    if event_name == "runtime.cancelled":
        return str(payload.get("message") or "任务已取消。")
    if event_name == "runtime.reply":
        return "生成最终回复。"
    if event_name == "runtime.reply_delta":
        return str(payload.get("summary") or payload.get("message") or "")
    return str(payload.get("summary") or payload.get("message") or event_name)


def runtime_payload_preview(value: Any, *, max_text_chars: int = DEFAULT_RUNTIME_PREVIEW_CHARS) -> Any:
    if isinstance(value, dict):
        return {
            str(k): runtime_payload_preview(v, max_text_chars=max_text_chars)
            for k, v in list(value.items())[:40]
        }
    if isinstance(value, list):
        return [runtime_payload_preview(v, max_text_chars=max_text_chars) for v in value[:20]]
    if isinstance(value, str):
        return value[:max_text_chars]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:max_text_chars]


def event_run_id(metadata: dict[str, Any] | None, *, fallback_run_id: str) -> str:
    payload = (metadata or {}).get("payload")
    if isinstance(payload, dict) and payload.get("run_id"):
        return str(payload.get("run_id"))
    if (metadata or {}).get("run_id"):
        return str((metadata or {}).get("run_id"))
    return fallback_run_id


def event_response_index(payload: dict[str, Any]) -> str:
    raw = payload.get("response_index")
    if raw is None or raw == "":
        return ""
    return str(raw)


def event_model_call_id(metadata: dict[str, Any] | None, *, fallback_run_id: str) -> str:
    payload = (metadata or {}).get("payload")
    payload = payload if isinstance(payload, dict) else {}
    run_id = event_run_id(metadata, fallback_run_id=fallback_run_id)
    response_index = event_response_index(payload)
    return f"{run_id}:response-{response_index}" if response_index else run_id


def tool_call_id_from_payload(payload: dict[str, Any], *, fallback_call_id: str, sequence: int, turn_id: str) -> str:
    direct = payload.get("tool_call_id") or payload.get("call_id")
    if direct:
        raw = str(direct)
        return raw if raw.startswith(f"{fallback_call_id}:") else f"{fallback_call_id}:{raw}"
    part_id = str(payload.get("part_id") or "")
    if part_id.startswith("part-") and len(part_id) > 5:
        raw = part_id[5:]
        return raw if raw.startswith(f"{fallback_call_id}:") else f"{fallback_call_id}:{raw}"
    return f"{turn_id}:{fallback_call_id}:tool:{sequence}"


def raw_tool_call_id_from_payload(payload: dict[str, Any], storage_tool_call_id: str) -> str:
    direct = payload.get("tool_call_id") or payload.get("call_id")
    if direct:
        return str(direct)
    part_id = str(payload.get("part_id") or "")
    if part_id.startswith("part-") and len(part_id) > 5:
        return part_id[5:]
    return storage_tool_call_id


def tool_args_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw = payload.get("tool_args") or payload.get("arguments") or payload.get("args")
    return raw if isinstance(raw, dict) else None


def usage_tokens(usage: dict[str, Any], *names: str) -> int | None:
    for name in names:
        value = usage.get(name)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def visible_runtime_part_content(
    payload: dict[str, Any],
    *,
    full_text: str,
    preview: str,
    summary: str,
) -> str:
    for value in (
        payload.get("content"),
        payload.get("detail"),
        payload.get("summary"),
        full_text,
        preview,
        summary,
    ):
        text = str(value or "").strip()
        if text and text != "runtime.part":
            return text
    return ""


def runtime_projection_to_run_item_events(fact: RuntimeProjectionInput) -> list[RunItemEvent]:
    return runtime_fact_to_run_item_events(
        thread_id=fact.thread_id,
        event_id=fact.id,
        group=fact.group,
        source=fact.source,
        phase=fact.phase,
        status=fact.status,
        sequence=fact.sequence,
        summary=fact.summary,
        preview=fact.preview,
        full_text=fact.full_text,
        metadata=fact.metadata,
        created_at=fact.created_at,
    ) or []


def runtime_fact_to_run_item_events(
    *,
    thread_id: str,
    event_id: str,
    group: str,
    source: str,
    phase: str | None,
    status: str | None,
    sequence: int | None,
    summary: str = "",
    preview: str = "",
    full_text: str = "",
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> list[RunItemEvent] | None:
    fact = RuntimeProjectionInput(
        id=event_id,
        thread_id=thread_id,
        group=group,
        source=source,
        phase=phase,
        status=status,
        sequence=sequence,
        summary=summary,
        preview=preview,
        full_text=full_text,
        metadata=metadata,
        created_at=created_at or datetime.now(timezone.utc),
    )
    payload = _payload(fact)
    sub_agent = payload.get("sub_agent") if isinstance(payload.get("sub_agent"), dict) else None
    phase = str(fact.phase or "")
    status = str(fact.status or "")
    run_id = event_run_id(fact.metadata, fallback_run_id="")
    turn_id = _turn_id(fact, payload)
    base = {
        "thread_id": fact.thread_id,
        "event_id": fact.id,
        "run_id": run_id,
        "turn_id": turn_id,
        "seq": int(fact.sequence or 0),
        "source": fact.source,
        "created_at_ms": _created_at_ms(fact),
        "parent_item_id": _sub_agent_parent_item_id(fact, sub_agent),
        "metadata": {
            "runtime_phase": phase,
            "runtime_group": fact.group,
            "run_id": run_id,
            "turn_id": turn_id,
            **({"sub_agent": sub_agent} if sub_agent is not None else {}),
        },
    }

    if phase == "runtime.reply_delta":
        text = _text_from_event(fact, payload)
        metrics = _usage_metrics(payload)
        events: list[RunItemEvent] = []
        if text:
            content_base = {**base, "event_id": _content_event_id(fact, "reply-delta", text)}
            events.append(RunItemEvent(
                kind="message",
                item_id=_agent_item_id(fact, payload),
                status="running",
                payload={"type": "agentMessage", "delta": text},
                **content_base,
            ))
        if metrics:
            events.append(RunItemEvent(
                kind="usage",
                status="running",
                payload={"type": "turn", "runtime_metrics": metrics},
                usage=metrics,
                **base,
            ))
        return events

    if phase == "runtime.tool.started":
        arguments = payload.get("arguments") or payload.get("tool_args") or {}
        item_payload = {
            "type": "dynamicToolCall",
            "tool_name": _tool_name(payload),
            "arguments": arguments,
            "summary": fact.summary or fact.preview or "",
        }
        input_preview = extract_tool_input_preview_from_arguments(_tool_name(payload), arguments)
        if input_preview:
            item_payload["input_preview"] = input_preview
        return [
            RunItemEvent(
                kind="tool_call",
                item_id=_tool_item_id(fact, payload),
                status="running",
                payload=item_payload,
                **base,
            )
        ]

    if phase == "runtime.tool.finished":
        payload_metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        completed_status = (
            "waiting"
            if payload_metadata.get("decision") == "wait"
            else "completed"
            if status in {"ok", "completed", "done"}
            else "failed"
        )
        item_id = _tool_item_id(fact, payload)
        result_text = str(payload.get("content") or payload.get("tool_result") or fact.preview or fact.summary or "")
        return [
            RunItemEvent(
                kind="tool_result",
                item_id=item_id,
                status=completed_status,
                payload={
                    "type": "dynamicToolCall",
                    "tool_name": _tool_name(payload),
                    "delta": fact.preview or fact.summary or str(payload.get("result") or payload.get("error") or ""),
                    "tool_result": result_text,
                    "replace": True,
                    "metadata": payload_metadata,
                    "status": completed_status,
                    "error": str(payload.get("error") or "") or None,
                },
                artifacts=[
                    _artifact_payload(fact.thread_id, turn_id, item_id, artifact)
                    for artifact in _artifact_sources(payload)
                ],
                **base,
            )
        ]

    if phase == "runtime.approval_request":
        tool_item_id = _tool_item_id(fact, payload)
        kind = str(payload.get("request_kind") or "approval")
        message = str(payload.get("message") or payload.get("question") or fact.summary or "Waiting for user decision")
        return [
            RunItemEvent(
                kind="approval_request",
                item_id=tool_item_id,
                status="waiting",
                payload={
                    "type": "serverRequest",
                    "request_id": str(payload.get("request_id") or payload.get("decision_id") or f"{fact.id}:request"),
                    "kind": kind,
                    "message": message,
                    "tool_name": _tool_name(payload),
                    "options": _request_options(payload),
                    "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
                },
                **base,
            )
        ]

    if phase == "runtime.approval_response":
        request_id = str(payload.get("request_id") or payload.get("tool_call_id") or fact.id)
        response_payload = {
            "type": "serverRequest",
            "request_id": request_id,
            "status": "resolved",
            "decision": str(payload.get("decision") or ""),
            "action": str(payload.get("action") or payload.get("decision") or ""),
            "guidance": str(payload.get("guidance") or ""),
        }
        failure_reason = str(payload.get("failure_reason") or "")
        if failure_reason:
            response_payload["failure_reason"] = failure_reason
        return [
            RunItemEvent(
                kind="approval_response",
                item_id=request_id,
                status="completed",
                payload=response_payload,
                **base,
            )
        ]

    if phase == "runtime.usage":
        metrics = _usage_metrics(payload)
        if not metrics:
            return []
        return [
            RunItemEvent(
                kind="usage",
                status="running",
                payload={"type": "turn", "runtime_metrics": metrics},
                usage=metrics,
                **base,
            )
        ]

    if phase == "runtime.metrics":
        metrics = payload.get("runtime_metrics")
        if not isinstance(metrics, dict):
            return []
        return [
            RunItemEvent(
                kind="usage",
                status="running",
                payload={"type": "turn", "runtime_metrics": metrics, "replace": True},
                usage=metrics,
                **base,
            )
        ]

    if phase == "runtime.waiting":
        kind = str(payload.get("request_kind") or "ask")
        if kind == "permission":
            return []
        tool_item_id = _tool_item_id(fact, payload)
        message = str(payload.get("message") or payload.get("question") or fact.summary or "Waiting for user decision")
        if kind == "no_progress":
            return [
                RunItemEvent(
                    kind="status",
                    item_id=tool_item_id,
                    status="running",
                    payload={
                        "type": "status",
                        "content": message,
                        "status": "running",
                    },
                    **base,
                )
            ]
        return [
            RunItemEvent(
                kind="approval_request",
                item_id=tool_item_id,
                status="waiting",
                payload={
                    "type": "serverRequest",
                    "request_id": str(payload.get("request_id") or payload.get("decision_id") or f"{fact.id}:request"),
                    "kind": kind,
                    "message": message,
                    "tool_name": _tool_name(payload),
                    "options": payload.get("options") if isinstance(payload.get("options"), list) else [],
                    "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
                },
                **base,
            )
        ]

    if phase == "runtime.part":
        part_type = str(payload.get("part_type") or "text")
        if part_type == "tool_call":
            if status in TERMINAL_STATUSES:
                return []
            arguments = payload.get("tool_args") or payload.get("arguments") or {}
            item_payload = {
                "type": "dynamicToolCall",
                "tool_name": _tool_name(payload),
                "arguments": arguments,
                "summary": str(payload.get("content") or payload.get("label") or fact.summary or ""),
                "message": str(payload.get("detail") or fact.preview or ""),
            }
            input_preview = extract_tool_input_preview_from_arguments(_tool_name(payload), arguments)
            if input_preview:
                item_payload["input_preview"] = input_preview
            return [
                RunItemEvent(
                    kind="tool_call",
                    item_id=_tool_item_id(fact, payload),
                    status=_canonical_status(status or "running"),
                    payload=item_payload,
                    **base,
                )
            ]
        if part_type == "tool_input_delta":
            arguments_text = str(payload.get("arguments_text") or "")
            input_preview = extract_tool_input_preview(
                _tool_name(payload),
                arguments_text,
            )
            if input_preview is None:
                return []
            input_base = {
                **base,
                "event_id": _content_event_id(fact, "runtime-part-tool-input", arguments_text),
            }
            item_payload: dict[str, Any] = {
                "type": "dynamicToolCall",
                "tool_name": _tool_name(payload),
                "summary": str(payload.get("content") or payload.get("label") or fact.summary or ""),
                "message": str(payload.get("detail") or fact.preview or ""),
                "input_preview": input_preview,
            }
            arguments = payload.get("tool_args") or payload.get("arguments")
            if isinstance(arguments, dict) and arguments:
                item_payload["arguments"] = arguments
            return [
                RunItemEvent(
                    kind="tool_call",
                    item_id=_tool_item_id(fact, payload),
                    status=_canonical_status(status or "running"),
                    payload=item_payload,
                    **input_base,
                )
            ]
        if part_type == "tool_result":
            result_text = _complete_text_from_event(fact, payload) if status in TERMINAL_STATUSES else _text_from_event(fact, payload)
            if not result_text or result_text == "runtime.part":
                return []
            payload_metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            return [
                RunItemEvent(
                    kind="tool_result",
                    item_id=_tool_item_id(fact, payload),
                    status="completed" if status in {"done", "ok"} else _canonical_status(status),
                    payload={
                        "type": "dynamicToolCall",
                        "tool_name": _tool_name(payload),
                        "delta": result_text,
                        "tool_result": result_text,
                        "replace": status in TERMINAL_STATUSES,
                        "metadata": payload_metadata,
                        "status": "completed" if status in {"done", "ok"} else _canonical_status(status),
                        "error": str(payload.get("error") or payload.get("tool_error") or "") or None,
                    },
                    **base,
                )
            ]
        item_type = "agentMessage" if part_type in {"text", "model_text"} else part_type
        item_id = str(payload.get("part_id") or f"{fact.thread_id}:part:{fact.sequence or fact.id}")
        content = _complete_text_from_event(fact, payload) if status in TERMINAL_STATUSES else _text_from_event(fact, payload)
        delta = payload.get("delta")
        if isinstance(delta, str) and delta and status not in TERMINAL_STATUSES:
            content = delta
        if (not content and part_type != "compaction") or content == "runtime.part":
            return []
        item_payload: dict[str, Any] = {"type": item_type}
        if isinstance(delta, str) and delta and status not in TERMINAL_STATUSES:
            item_payload["delta"] = delta
        else:
            item_payload["content"] = content
        if part_type == "compaction":
            for key in (
                "label",
                "detail",
                "before_tokens",
                "after_tokens",
                "trigger_tokens",
                "limit_tokens",
                "window_tokens",
                "removed_messages",
                "trigger",
                "phase",
                "segment",
                "segments",
                "reason",
                "message",
            ):
                if key in payload:
                    item_payload[key] = payload[key]
            item_payload["compaction_status"] = str(payload.get("status") or status or "running")
            if "limit_tokens" not in item_payload and "target_tokens" in payload:
                item_payload["limit_tokens"] = payload["target_tokens"]
        content_base = {**base, "event_id": _content_event_id(fact, f"runtime-part-{part_type}", content)}
        return [
            RunItemEvent(
                kind="thinking" if part_type in {"reasoning", "thinking"} else "message",
                item_id=item_id,
                status="completed" if status in {"done", "ok"} else _canonical_status(status),
                payload=item_payload,
                **content_base,
            )
        ]

    if sub_agent is not None and phase in {"runtime.done", "runtime.failed", "runtime.cancelled"}:
        # The parent sub_agent tool result owns the delegated run's visible
        # terminal state. A forwarded child lifecycle must never terminate the
        # parent turn that carries it.
        return []

    if phase in {"runtime.done", "runtime.failed", "runtime.cancelled"}:
        completed_status = {
            "runtime.done": "completed",
            "runtime.failed": "failed",
            "runtime.cancelled": "cancelled",
        }[phase]
        message = max(
            [text for text in [str(fact.summary or ""), str(fact.preview or ""), str(fact.full_text or "")] if text],
            key=len,
            default="",
        )
        completed_payload: dict[str, Any] = {
            "type": "turn",
            "status": completed_status,
            "raw_end_reason": payload.get("decision") or payload.get("error") or completed_status,
            "message": message,
        }
        runtime_metrics = payload.get("runtime_metrics") if isinstance(payload.get("runtime_metrics"), dict) else None
        if runtime_metrics is not None:
            completed_payload["runtime_metrics"] = runtime_metrics
        return [
            RunItemEvent(
                kind="status",
                item_id=f"{run_id}:terminal" if run_id else f"{turn_id}:terminal",
                status=completed_status,
                payload=completed_payload,
                usage=runtime_metrics or {},
                **base,
            )
        ]

    return None


def _payload(fact: RuntimeProjectionInput) -> dict[str, Any]:
    metadata = fact.metadata if isinstance(fact.metadata, dict) else {}
    payload = metadata.get("payload")
    return payload if isinstance(payload, dict) else {}


def _metadata(fact: RuntimeProjectionInput) -> dict[str, Any]:
    return fact.metadata if isinstance(fact.metadata, dict) else {}


def _turn_id(fact: RuntimeProjectionInput, payload: dict[str, Any]) -> str:
    metadata = _metadata(fact)
    run_id = event_run_id(metadata, fallback_run_id="")
    return str(
        payload.get("turn_id")
        or metadata.get("turn_id")
        or metadata.get("turnId")
        or run_id
        or f"{fact.thread_id}:turn:unknown"
    )


def _tool_call_id(fact: RuntimeProjectionInput, payload: dict[str, Any]) -> str:
    raw = payload.get("tool_call_id") or payload.get("call_id")
    if not raw:
        part_id = str(payload.get("part_id") or "")
        raw = part_id[5:] if part_id.startswith("part-") and len(part_id) > 5 else part_id
    if not raw and payload.get("response_index") not in {None, ""}:
        raw = f"invalid-tool-call:{payload.get('response_index')}"
    if not raw:
        raw = f"tool:{fact.sequence or fact.id}"
    return str(raw)


def _tool_name(payload: dict[str, Any]) -> str:
    name = str(payload.get("tool_name") or "").strip()
    return name or "invalid_tool_call"


def extract_tool_input_preview(tool_name: str, arguments_text: str) -> dict[str, Any] | None:
    name = tool_name.strip().lower()
    fields = _tool_input_preview_fields(name)
    if not fields or not arguments_text:
        return None
    field = ""
    value = None
    for candidate in fields:
        value = _partial_json_string_field(arguments_text, candidate)
        if value is not None:
            field = candidate
            break
    if value is None:
        return None
    truncated = len(value) > DEFAULT_RUNTIME_PREVIEW_CHARS
    content = value[:DEFAULT_RUNTIME_PREVIEW_CHARS]
    return {
        "field": field,
        "content": content,
        "chars": len(value),
        "truncated": truncated,
    }


def extract_tool_input_preview_from_arguments(tool_name: str, arguments: Any) -> dict[str, Any] | None:
    if not isinstance(arguments, dict):
        return None
    for field in _tool_input_preview_fields(tool_name.strip().lower()):
        value = arguments.get(field)
        if not isinstance(value, str):
            continue
        truncated = len(value) > DEFAULT_RUNTIME_PREVIEW_CHARS
        return {
            "field": field,
            "content": value[:DEFAULT_RUNTIME_PREVIEW_CHARS],
            "chars": len(value),
            "truncated": truncated,
        }
    return None


def _tool_input_preview_fields(name: str) -> list[str]:
    if name == "write_file":
        return ["content"]
    if name == "edit_file":
        return ["new_text", "new_string"]
    return []


def _partial_json_string_field(text: str, field: str) -> str | None:
    marker = f'"{field}"'
    start = text.find(marker)
    if start < 0:
        return None
    colon = text.find(":", start + len(marker))
    if colon < 0:
        return None
    quote = text.find('"', colon + 1)
    if quote < 0:
        return None

    chars: list[str] = []
    escaped = False
    for char in text[quote + 1:]:
        if escaped:
            chars.append({
                "n": "\n",
                "r": "\r",
                "t": "\t",
                '"': '"',
                "\\": "\\",
            }.get(char, char))
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            break
        chars.append(char)
    if escaped:
        chars.append("\\")
    return "".join(chars)


def _tool_item_id(fact: RuntimeProjectionInput, payload: dict[str, Any]) -> str:
    metadata = _metadata(fact)
    run_id = str(payload.get("run_id") or metadata.get("run_id") or "").strip()
    scope_id = run_id or _turn_id(fact, payload)
    return f"{fact.thread_id}:{scope_id}:{_tool_call_id(fact, payload)}:tool"


def _sub_agent_parent_item_id(
    fact: RuntimeProjectionInput,
    sub_agent: dict[str, Any] | None,
) -> str:
    if not sub_agent:
        return ""
    parent_call_id = str(sub_agent.get("parent_call_id") or "").strip()
    if not parent_call_id:
        return ""
    metadata = _metadata(fact)
    parent_run_id = str(
        sub_agent.get("parent_run_id")
        or metadata.get("run_id")
        or ""
    ).strip()
    scope_id = parent_run_id or _turn_id(fact, _payload(fact))
    return f"{fact.thread_id}:{scope_id}:{parent_call_id}:tool"


def _agent_item_id(fact: RuntimeProjectionInput, payload: dict[str, Any]) -> str:
    direct = payload.get("part_id")
    if direct:
        return str(direct)
    metadata = _metadata(fact)
    run_id = str(payload.get("run_id") or metadata.get("run_id") or "").strip()
    response_index = payload.get("response_index")
    response_suffix = f":response-{response_index}" if response_index not in {None, ""} else ""
    if run_id:
        return f"{run_id}{response_suffix}:model_text"
    return f"{_turn_id(fact, payload)}:model_text"


def _content_event_id(fact: RuntimeProjectionInput, suffix: str, content: str) -> str:
    return _content_delta_event_id(fact.id, suffix, content)


def _content_delta_event_id(event_id: str, suffix: str, content: str) -> str:
    digest = sha1(content.encode("utf-8")).hexdigest()[:12]
    return f"{event_id}:{suffix}:{digest}"


def _artifact_sources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("artifacts")
    metadata = payload.get("metadata")
    if not raw and isinstance(metadata, dict):
        raw = metadata.get("artifacts")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _artifact_id(thread_id: str, turn_id: str, item_id: str, artifact: dict[str, Any]) -> str:
    existing = artifact.get("artifact_id") or artifact.get("id")
    if existing:
        return str(existing)
    seed = "|".join(
        [
            thread_id,
            turn_id,
            item_id,
            str(artifact.get("artifact_type") or artifact.get("kind") or "file"),
            str(artifact.get("path") or artifact.get("file_path") or artifact.get("name") or ""),
        ]
    )
    return f"artifact-{sha1(seed.encode('utf-8', errors='ignore')).hexdigest()[:16]}"


def _artifact_payload(thread_id: str, turn_id: str, item_id: str, artifact: dict[str, Any]) -> dict[str, Any]:
    metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
    uri = str(artifact.get("uri") or "")
    path = str(artifact.get("path") or artifact.get("file_path") or metadata.get("path") or uri)
    name = str(artifact.get("name") or (Path(path).name if path else artifact.get("description") or "artifact"))
    kind = str(artifact.get("kind") or artifact.get("artifact_type") or "file")
    return {
        "artifact_id": _artifact_id(thread_id, turn_id, item_id, artifact),
        "thread_id": thread_id,
        "turn_id": turn_id,
        "item_id": item_id,
        "kind": kind,
        "name": name,
        "path": path,
        "uri": uri or path,
        "content": artifact.get("content"),
        "mime_type": artifact.get("mime_type") or artifact.get("mimeType"),
        "size_bytes": artifact.get("size_bytes") or artifact.get("sizeBytes"),
        "content_hash": artifact.get("content_hash") or artifact.get("contentHash"),
        "metadata": {
            **metadata,
            "description": artifact.get("description") or metadata.get("description") or "",
            "diff": artifact.get("diff") or metadata.get("diff"),
            "has_content_after": bool(artifact.get("content_after")),
            "has_content_before": bool(artifact.get("content_before")),
        },
    }


def _text_from_event(fact: RuntimeProjectionInput, payload: dict[str, Any]) -> str:
    for key in ("content", "tool_result", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return str(fact.full_text or fact.preview or "")


def _complete_text_from_event(fact: RuntimeProjectionInput, payload: dict[str, Any]) -> str:
    candidates: list[str] = []
    for key in ("content", "tool_result", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value and value != "runtime.part":
            candidates.append(value)
    for value in (fact.full_text, fact.preview, fact.summary):
        if isinstance(value, str) and value and value != "runtime.part":
            candidates.append(value)
    if not candidates:
        return ""
    return max(candidates, key=len)


def _request_options(payload: dict[str, Any]) -> list[dict[str, Any]]:
    options = payload.get("options")
    if isinstance(options, list) and options:
        return [item for item in options if isinstance(item, dict)]
    return [dict(item) for item in APPROVAL_OPTIONS]


def _usage_metrics(payload: dict[str, Any]) -> dict[str, int | float]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return {}
    input_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or input_tokens + output_tokens or 0)
    cached_tokens = _cached_tokens_from_usage(usage)
    cache_creation_tokens = _cache_creation_tokens_from_usage(usage)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cache_hit_rate": round(cached_tokens / input_tokens, 4) if input_tokens > 0 else 0,
        "llm_calls": 1,
    }


def _created_at_ms(fact: RuntimeProjectionInput) -> int:
    created_at = fact.created_at or datetime.now(timezone.utc)
    return int(created_at.timestamp() * 1000)


def _canonical_status(status: str) -> str:
    if status in {"ok", "done", "completed", "compacted", "not_needed"}:
        return "completed"
    if status in {"error", "failed"}:
        return "failed"
    if status in {"cancelled", "skipped", "queued", "waiting", "running"}:
        return status
    return "running"


__all__ = [
    "DEFAULT_RUNTIME_PREVIEW_CHARS",
    "RuntimeProjectionBuffer",
    "RuntimeProjectionInput",
    "extract_tool_input_preview",
    "event_model_call_id",
    "event_response_index",
    "event_run_id",
    "raw_tool_call_id_from_payload",
    "runtime_group_from_event_name",
    "runtime_fact_to_run_item_events",
    "runtime_payload_preview",
    "runtime_projection_to_run_item_events",
    "runtime_summary_from_event_name",
    "tool_args_from_payload",
    "tool_call_id_from_payload",
    "usage_tokens",
    "visible_runtime_part_content",
]
