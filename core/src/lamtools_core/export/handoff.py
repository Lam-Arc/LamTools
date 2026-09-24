"""Provider-neutral Handoff context construction.

Handoff is deliberately a very small interchange format.  It is built from
the messages that are about to cross the model boundary, then removes the
transport/runtime details that only make sense to the current Agent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any

from lamtools_core.llm import ChatMessage

HANDOFF_SCHEMA = "lamtools.handoff.v1"
_MESSAGE_ROLES = {"system", "developer", "user", "assistant", "tool"}

# These keys are protocol/runtime metadata, not task knowledge.  Keep this
# list intentionally case-insensitive because provider payloads use several
# spellings (for example ``inputSchema`` and ``tool_call_id``).
_DROP_KEYS = {
    "model",
    "model_id",
    "model_name",
    "model_record_id",
    "provider",
    "provider_id",
    "provider_name",
    "temperature",
    "max_tokens",
    "top_p",
    "reasoning",
    "reasoning_effort",
    "thinking_budget",
    "tool_choice",
    "parallel_tool_calls",
    "tools",
    "tool",
    "input_schema",
    "output_schema",
    "inputschema",
    "outputschema",
    "function",
    "functions",
    "request_id",
    "response_id",
    "trace_id",
    "span_id",
    "run_id",
    "turn_id",
    "session_id",
    "thread_id",
    "checkpoint_id",
    "event_id",
    "event_seq",
    "seq",
    "row_id",
    "database_id",
    "db_id",
    "tool_call_id",
    "call_id",
    "token_usage",
    "usage",
    "latency",
    "telemetry",
    "metadata",
    "raw",
}


def build_handoff_context(messages: Iterable[ChatMessage | Mapping[str, Any]] | Any) -> dict[str, Any]:
    """Return the fixed ``lamtools.handoff.v1`` payload for *messages*.

    The input is expected to be the final request message list, after Kernel
    compaction and internal-message cleanup.  No model/provider/tool call is
    performed here.  Message content is copied rather than rewritten into a
    summary; only transport and runtime fields are removed.
    """

    # Accept an LLMRequest as a convenience, while deliberately reading only
    # its messages.  Model/config/tool fields never enter the DTO.
    if hasattr(messages, "messages"):
        messages = getattr(messages, "messages", [])
    if isinstance(messages, Mapping) and "context" in messages:
        return sanitize_handoff_context(messages)
    if not isinstance(messages, Iterable) or isinstance(messages, (str, bytes)):
        messages = []
    context: list[dict[str, Any]] = []
    for message in messages:
        item = _sanitize_message(message)
        if item is not None:
            context.append(item)
    return {"schema": HANDOFF_SCHEMA, "context": context}


def sanitize_handoff_context(value: Mapping[str, Any]) -> dict[str, Any]:
    """Sanitize a previously captured handoff payload.

    This second pass makes persisted/fixture data safe even when it was
    captured by an older caller.  It also guarantees the public DTO has no
    accidental envelope fields such as ``thread_id`` or ``exported_at``.
    """

    raw_context = value.get("context") if isinstance(value, Mapping) else []
    messages = raw_context if isinstance(raw_context, list) else []
    return build_handoff_context(messages)


def _sanitize_message(message: ChatMessage | Mapping[str, Any]) -> dict[str, Any] | None:
    if isinstance(message, ChatMessage):
        role = str(message.role or "").strip().lower()
        content: Any = message.content
        # ``ChatMessage.tool_calls`` is deliberately ignored.  The assistant's
        # natural-language content remains useful; an empty tool-call-only
        # message is just execution protocol and is omitted below.
    elif isinstance(message, Mapping):
        role = str(message.get("role") or "").strip().lower()
        content = message.get("content", "")
    else:
        return None

    if role not in _MESSAGE_ROLES:
        return None
    clean_content = _sanitize_content(content)
    if role in {"system", "developer"} and isinstance(clean_content, str):
        clean_content = _sanitize_semantic_text(clean_content)
    if role == "tool":
        clean_content = _sanitize_tool_result_text(clean_content)
    if _content_is_empty(clean_content):
        return None
    return {"role": role, "content": clean_content}


def _sanitize_content(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        result: list[Any] = []
        for item in value:
            clean = _sanitize_content_block(item)
            if clean is not None and not _content_is_empty(clean):
                result.append(clean)
        return result
    if isinstance(value, Mapping):
        return _sanitize_mapping(value, content_block=True)
    if value is None:
        return ""
    # Provider adapters occasionally hand a scalar content value through.
    # Preserve its meaning without exposing an object representation.
    return str(value)


def _sanitize_semantic_text(value: str) -> str:
    """Remove known transport/runtime prompt lines without summarizing text."""
    lines: list[str] = []
    for line in value.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if (
            ("当前项目:" in stripped and "当前会话:" in stripped)
            or ("Current project:" in stripped and "current session:" in stripped)
            or stripped.startswith("Current session:")
            or stripped.startswith("Available MCP servers")
            or stripped.startswith("已知成功证据调用 ID")
            or stripped.startswith("证据调用 ID")
            or stripped.startswith("Known successful evidence call IDs")
            or stripped == "[命令 Shell]"
            or stripped == "[Command Shell]"
            or stripped.startswith("当前平台：")
            or stripped.startswith("Current platform:")
            or stripped.startswith("当前 shell：")
            or stripped.startswith("Current shell:")
            or stripped.startswith("Instructions from:")
        ):
            continue
        if stripped in {
            "在有助于完成用户请求时使用可用工具。",
            "创建或修改文件时使用 write_file 或 edit_file。",
            "当可用技能与任务匹配时使用 load_skill。",
        }:
            continue
        # A target Agent cannot use the current model/provider selection or
        # token/reasoning budget.  Drop standalone configuration lines while
        # leaving ordinary prose that happens to discuss a model intact.
        if re.match(
            r"^(model|model_id|provider|provider_id|temperature|max_tokens|top_p|"
            r"reasoning_effort|thinking_budget|token_usage|trace_id|request_id)\s*[:=]",
            lowered,
        ):
            continue
        # Capability guidance is useful, but a named delegate model is not.
        line = re.sub(r"（指定\s*model\s*为\s*\"[^\"]*\"）", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\s*\(set\s+model\s+to\s+\"[^\"]*\"\)", "", line, flags=re.IGNORECASE)
        line = re.sub(r",\s*model\s*=\s*\"[^\"]*\"", "", line, flags=re.IGNORECASE)
        # Deferred attachment ids are private DB identifiers.  Keep the
        # sentence's attachment meaning without carrying the id or tool call.
        line = re.sub(r"\s*\(id:\s*[^\)]*\)", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\s*（id:\s*[^）]*）", "", line, flags=re.IGNORECASE)
        if "sub_agent(" in line or "tool_call_id" in line.lower():
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _sanitize_tool_result_text(value: Any) -> Any:
    """Remove obvious call/telemetry tokens from tool-result text only."""
    if isinstance(value, str):
        cleaned = re.sub(
            r"\b(?:tool[_ -]?call|call|request|response|trace|span|run|turn|checkpoint)[_-][A-Za-z0-9.-]+\b",
            "[internal id]",
            value,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\b(?:api[_ -]?key|auth(?:entication)?[_ -]?token)\s*[:=]\s*[^\s,;]+",
            "[redacted]",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned
    if isinstance(value, list):
        return [_sanitize_tool_result_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_tool_result_text(item) for key, item in value.items()}
    return value


def _sanitize_content_block(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return str(value) if value is not None else None

    block_type = str(value.get("type") or "").strip().lower()
    if block_type in {"tool_call", "tool_calls", "function", "function_call"}:
        return None

    # Normalize provider-specific image/file wrappers to the generic
    # attachment vocabulary accepted by a different Agent.  Inline data is
    # kept when present; a local path/blob/token is never copied as a private
    # reference.
    if block_type in {"image_url", "image", "file", "attachment", "document"}:
        block: dict[str, Any] = {"type": "attachment"}
        for key in ("name", "filename", "media_type", "mime_type", "reference", "text", "content", "data"):
            if key in value:
                clean = _sanitize_value(value[key], key=key)
                if clean is not None and not _content_is_empty(clean):
                    output_key = "name" if key == "filename" else "media_type" if key == "mime_type" else key
                    block[output_key] = clean
        nested_url = value.get("image_url")
        if isinstance(nested_url, Mapping):
            url = nested_url.get("url")
            if isinstance(url, str) and url.startswith("data:"):
                block["data"] = url
        elif isinstance(nested_url, str) and nested_url.startswith("data:"):
            block["data"] = nested_url
        return block

    return _sanitize_mapping(value, content_block=True)


def _sanitize_mapping(value: Mapping[str, Any], *, content_block: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key)
        normalized = key.replace("-", "_").lower()
        if normalized in _DROP_KEYS:
            continue
        # A generic ``id`` is only an internal identifier when it appears in
        # a provider/tool envelope.  Attachment blocks may use ``id`` in old
        # payloads, but a handoff must never expose it as a DB/blob reference.
        if content_block and normalized in {"id", "path", "storage_path", "blob_id", "signed_url", "download_token", "auth_token"}:
            continue
        clean = _sanitize_value(raw_value, key=key, content_block=content_block)
        if clean is not None:
            result[key] = clean
    return result


def _sanitize_value(value: Any, *, key: str = "", content_block: bool = False) -> Any:
    if isinstance(value, Mapping):
        return _sanitize_mapping(value, content_block=content_block)
    if isinstance(value, list):
        return [_sanitize_value(item, key=key, content_block=content_block) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _content_is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return not value
    return False


__all__ = ["HANDOFF_SCHEMA", "build_handoff_context", "sanitize_handoff_context"]
