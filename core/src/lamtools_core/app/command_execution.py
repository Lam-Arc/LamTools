from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from lamtools_core.context_compaction import (
    ContextCompactionRequest,
    compact_context,
    compaction_segment_input_limit,
)
from lamtools_core.llm import ChatMessage, LLMClient, LLMToolCall
from lamtools_core.mem import MemoryStoreProtocol
from lamtools_core.mem.dreaming import dream_session
from lamtools_core.runtime import RuntimeCheckpointStore, RuntimeState, RuntimeStateStore


CommandActionHandler = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]
MANUAL_COMPACTION_LIMIT_TOKENS = 6_000


async def execute_command_action(
    *,
    command: str,
    thread_id: str,
    handlers: Mapping[str, CommandActionHandler],
    work_root: str = "",
    arguments: str = "",
    on_event: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    handler = handlers.get(command)
    if handler is None:
        raise ValueError(f"Command is not executable as an action: {command}")
    kwargs = {
        "thread_id": thread_id,
        "work_root": work_root,
        "arguments": arguments,
        "on_event": on_event,
    }
    accepted = _accepted_kwargs(handler, kwargs)
    result = handler(**accepted)
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, dict):
        raise TypeError(f"Command action must return an object: {command}")
    return result


async def compact_runtime_history(
    *,
    runtime_state_store: RuntimeStateStore,
    thread_id: str,
    llm_client: LLMClient | None = None,
    model: str = "",
    on_event: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(runtime_state_store, RuntimeCheckpointStore):
        raise RuntimeError("Runtime history storage does not support manual compaction")
    state = await runtime_state_store.get(thread_id) or RuntimeState(session_id=thread_id)
    metadata = state.metadata if isinstance(state.metadata, dict) else {}
    metrics = metadata.get("runtime_context_metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    audit = metadata.get("runtime_audit")
    audit = audit if isinstance(audit, dict) else {}
    loop_policy = audit.get("loop_policy")
    loop_policy = loop_policy if isinstance(loop_policy, dict) else {}
    context_window_tokens = _first_positive_int(
        metadata.get("context_window_tokens"),
        metrics.get("context_window_tokens"),
        loop_policy.get("context_window_tokens"),
    )
    active_model = str(metadata.get("model_id") or metrics.get("model_id") or model).strip()
    raw_history = await runtime_state_store.get_history(thread_id)
    messages = [message for item in raw_history if (message := _chat_message_from_dict(item)) is not None]
    result = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=messages,
            llm_client=llm_client,
            model=active_model,
            limit_tokens=MANUAL_COMPACTION_LIMIT_TOKENS,
            input_limit_tokens=compaction_segment_input_limit(context_window_tokens),
            on_event=on_event,
        )
    )
    if result.status != "compacted":
        return {
            **result.display_payload,
            "session_id": thread_id,
            "summary": result.summary,
        }
    # Do NOT overwrite persisted history.  Store the compaction summary +
    # boundary seq in state.metadata so subsequent runs load only messages
    # after the boundary and prepend the summary.
    compaction_boundary = 0
    if isinstance(runtime_state_store, RuntimeCheckpointStore):
        compaction_boundary = await runtime_state_store.history_max_seq(thread_id)
    if not isinstance(state.metadata, dict):
        state.metadata = {}
    state.metadata["context_compaction"] = {
        "summary": result.summary,
        "summary_seq": compaction_boundary,
        "compacted_count": result.compacted_count,
        "retained_count": result.retained_count,
        "before_tokens": result.before_tokens,
        "after_tokens": result.after_tokens,
    }
    await runtime_state_store.save(state)
    return {
        "status": "compacted",
        "session_id": thread_id,
        "compacted_messages": result.compacted_count,
        "retained_messages": result.retained_count,
        "before_tokens": result.before_tokens,
        "after_tokens": result.after_tokens,
        "limit_tokens": result.limit_tokens,
        "trigger": "manual",
        "summary": result.summary,
    }


async def dream_session_memory(
    *,
    runtime_state_store: RuntimeStateStore,
    memory_store: MemoryStoreProtocol,
    thread_id: str,
    work_root: str = "",
    llm_client: LLMClient | None = None,
    model: str = "",
    on_event: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Manually trigger dreaming for a session (the ``/dream`` command).

    Mirrors :func:`compact_runtime_history`: loads state + history from the
    runtime store, extracts the compaction summary if present, and delegates
    to :func:`lamtools_core.mem.dreaming.dream_session`. The work root is
    taken from ``state.metadata["work_root"]`` (set by ``on_run_start``) and
    falls back to the ``work_root`` argument.
    """
    if not isinstance(runtime_state_store, RuntimeCheckpointStore):
        raise RuntimeError("Runtime history storage does not support manual dreaming")
    state = await runtime_state_store.get(thread_id) or RuntimeState(session_id=thread_id)
    metadata = state.metadata if isinstance(state.metadata, dict) else {}

    work_root_str = str(metadata.get("work_root") or work_root or "")
    active_model = str(metadata.get("model_id") or model).strip()

    # Pull the compaction summary if one exists for this session.
    compaction = metadata.get("context_compaction")
    compaction_summary: str | None = None
    if isinstance(compaction, dict):
        raw_summary = compaction.get("summary")
        if isinstance(raw_summary, str) and raw_summary.strip():
            compaction_summary = raw_summary

    # Load full history (after_seq=0 → everything in the incremental table).
    raw_history = await runtime_state_store.get_history(thread_id)
    history = [message for item in raw_history if (message := _chat_message_from_dict(item)) is not None]

    result = await dream_session(
        session_id=thread_id,
        work_root=Path(work_root_str) if work_root_str else "",
        history=history,
        compaction_summary=compaction_summary,
        memory_store=memory_store,
        llm_client=llm_client,
        model=active_model,
        on_event=on_event,
    )
    return {
        "status": result.status,
        "session_id": thread_id,
        "extracted": result.extracted,
        "added": result.added,
        "updated": result.updated,
        "memory_md_updated": result.memory_md_updated,
        "summary": result.summary,
        "error": result.error,
    }


def _first_positive_int(*values: Any) -> int:
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return 0


def _accepted_kwargs(handler: CommandActionHandler, kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        return kwargs
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        return kwargs
    return {name: value for name, value in kwargs.items() if name in signature.parameters}


def _chat_message_from_dict(value: Any) -> ChatMessage | None:
    if not isinstance(value, dict):
        return None
    role = str(value.get("role") or "")
    if role not in {"system", "user", "assistant", "tool"}:
        return None
    content = value.get("content")
    if not isinstance(content, (str, list)):
        content = ""
    tool_calls = []
    for raw in value.get("tool_calls") if isinstance(value.get("tool_calls"), list) else []:
        if not isinstance(raw, dict):
            continue
        tool_calls.append(
            LLMToolCall(
                id=str(raw.get("id") or ""),
                name=str(raw.get("name") or ""),
                arguments=raw.get("arguments") if isinstance(raw.get("arguments"), (dict, str)) else {},
                metadata=dict(raw.get("metadata") or {}),
            )
        )
    return ChatMessage(
        role=role,  # type: ignore[arg-type]
        content=content,
        name=str(value.get("name") or ""),
        tool_call_id=str(value.get("tool_call_id") or ""),
        tool_calls=tool_calls,
        metadata=dict(value.get("metadata") or {}),
    )


__all__ = [
    "CommandActionHandler",
    "MANUAL_COMPACTION_LIMIT_TOKENS",
    "compact_runtime_history",
    "dream_session_memory",
    "execute_command_action",
]
