"""Durable, content-addressed original context for Markdown memories."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from urllib.parse import quote
from typing import Any

from lamtools_core.mem import library
from lamtools_core.llm import ChatMessage
from lamtools_core.runtime import RuntimeState
from lamtools_core.tool import ToolCall

# user:“上下文应当能够被精确召回，记忆也应当保存记忆时的精确位置”+(宿主记录来源与原文快照，不依赖模型重述)。
CONTEXT_KEY = "_memory_source_context"
MAX_CONTEXT_CHARS = 200_000
_LINK = re.compile(r"\[原始上下文\]\(memory-context:([a-f0-9]{64})\)")


class SourceError(library.MemoryError):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def attach_context(call: ToolCall, state: RuntimeState, history: list[ChatMessage]) -> None:
    """Stamp only memory mutations, using host-owned history before execution."""
    if call.name != "memory" or str(call.arguments.get("action", "")).strip().lower() not in {"write", "append", "edit"}:
        return
    start = call.arguments.get("source_start_seq")
    end = call.arguments.get("source_end_seq")
    messages = list(history)
    if start is not None or end is not None:
        valid = all(value is None or (type(value) is int and value > 0) for value in (start, end))
        seqs = {m.metadata.get("history_seq") for m in messages}
        if not valid or (start is not None and start not in seqs) or (end is not None and end not in seqs) or (start is not None and end is not None and start > end):
            call.metadata[CONTEXT_KEY] = {"error": "invalid_source_range"}
            return
        messages = [m for m in messages if type(m.metadata.get("history_seq")) is int and (start is None or m.metadata["history_seq"] >= start) and (end is None or m.metadata["history_seq"] <= end)]
    else:
        # The latest user message and subsequent evidence form the default
        # exchange. Never silently snapshot an arbitrary tail of older turns.
        latest_user = next((i for i in range(len(messages) - 1, -1, -1) if messages[i].role == "user"), None)
        messages = messages[latest_user:] if latest_user is not None else []
    records = []
    for message in messages:
        if message.role == "system" or any(tc.id == call.id for tc in message.tool_calls):
            continue
        # Keep original text and stable locators; exclude provider signatures,
        # credentials in internal metadata, and image/base64 payloads.
        content = message.content
        omitted_media = False
        if isinstance(content, list):
            omitted_media = any(block.get("type") not in {"text", "input_text", "output_text"} for block in content)
            content = [block for block in content if block.get("type") in {"text", "input_text", "output_text"}]
        record = {"role": message.role, "content": content}
        for key in ("history_seq", "turn_id", "message_id", "item_id"):
            if key in message.metadata:
                record[key] = message.metadata[key]
        if message.tool_call_id:
            record["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            record["tool_calls"] = [{"id": tc.id, "name": tc.name, "arguments": deepcopy(tc.arguments)} for tc in message.tool_calls]
        if omitted_media:
            record["media_omitted"] = True
        records.append(deepcopy(record))
    session_id = state.session_id
    turn_id = str(state.metadata.get("turn_id") or state.run_id)
    source = {
        "session_id": session_id, "turn_id": turn_id, "run_id": state.run_id,
        "tool_call_id": call.id, "work_root": str(state.metadata.get("work_root") or ""),
        "uri": f"lamtools-context://sessions/{quote(session_id, safe='')}/turns/{quote(turn_id, safe='')}?call={quote(call.id, safe='')}",
    }
    seqs = [record["history_seq"] for record in records if type(record.get("history_seq")) is int]
    if seqs:
        source["start_history_seq"] = seqs[0]
        source["end_history_seq"] = seqs[-1]
        source["uri"] += f"&start_history_seq={seqs[0]}&end_history_seq={seqs[-1]}"
    call.metadata[CONTEXT_KEY] = {
        "version": 1, "source": source, "messages": records,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "untrusted_context": True,
    } if records else {"error": "source_not_found"}


def source_ids(content: str) -> list[str]:
    return list(dict.fromkeys(_LINK.findall(content)))


def _snapshot_path(scope, root, source_id):
    if not re.fullmatch(r"[a-f0-9]{64}", source_id):
        raise SourceError("Invalid context source ID", "source_not_found")
    return library.resolve_memory_path(scope, root, f".contexts/{source_id}.json")


def save_context(scope, root, context: dict) -> str:
    if context.get("error"):
        raise SourceError("Original context unavailable; select an existing history_seq range.", str(context["error"]))
    text = json.dumps(context, ensure_ascii=False, sort_keys=True)
    if len(text) > MAX_CONTEXT_CHARS:
        raise SourceError("Original context exceeds the limit; select a smaller source history_seq range. Nothing was saved.", "source_too_large")
    source_id = hashlib.sha256(text.encode("utf-8")).hexdigest()
    library._atomic_write(_snapshot_path(scope, root, source_id), text)
    return source_id


def links(ids: list[str]) -> str:
    return "\n\n" + "\n".join(f"[原始上下文](memory-context:{source_id})" for source_id in ids) + "\n" if ids else ""


def merge_links(content: str, ids: list[str]) -> str:
    # user:“记忆也应当保存记忆时的精确位置”+(整篇回写时去重来源链接，避免来源随编辑次数重复膨胀)。
    combined = list(dict.fromkeys([*source_ids(content), *ids]))
    return _LINK.sub("", content).rstrip() + links(combined)


def reload_context(scope, root, path: str, source_id: str = "") -> dict[str, Any]:
    # Read the complete file: links can follow a memory larger than read's cap.
    target = library.resolve_memory_path(scope, root, path)
    if not target.is_file():
        raise library.MemoryNotFoundError(f"memory file not found: {path}")
    ids = source_ids(target.read_text(encoding="utf-8"))
    selected = source_id or (ids[-1] if ids else "")
    if selected not in ids:
        raise SourceError("This memory has no matching original context. Older memories have no automatic source.", "source_not_found")
    snapshot = _snapshot_path(scope, root, selected)
    if not snapshot.is_file():
        raise SourceError("The original context snapshot is missing.", "source_not_found")
    try:
        text = snapshot.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SourceError("Invalid original context encoding", "source_corrupt") from exc
    if len(text) > MAX_CONTEXT_CHARS or hashlib.sha256(text.encode("utf-8")).hexdigest() != selected:
        raise SourceError("The original context snapshot failed its integrity check.", "source_corrupt")
    try:
        result = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise SourceError("Invalid original context snapshot", "source_corrupt") from exc
    if not isinstance(result, dict) or result.get("version") != 1 or not isinstance(result.get("messages"), list):
        raise SourceError("Unsupported original context snapshot", "source_corrupt")
    return {**result, "source_id": selected, "available_sources": ids, "untrusted_context": True}
