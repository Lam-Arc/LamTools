from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from lamtools_core.context_compaction import ContextCompactionRequest, compact_context
from lamtools_core.llm import ChatMessage, LLMClient, LLMToolCall
from lamtools_core.runtime import RuntimeCheckpointStore, RuntimeState, RuntimeStateStore


CommandActionHandler = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]
MAX_RETAIN_MESSAGE_COUNT = 6
MANUAL_COMPACTION_TARGET_TOKENS = 6_000


async def execute_command_action(
    *,
    command: str,
    thread_id: str,
    handlers: Mapping[str, CommandActionHandler],
    work_root: str = "",
    on_delta: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    handler = handlers.get(command)
    if handler is None:
        raise ValueError(f"Command is not executable as an action: {command}")
    kwargs = {
        "thread_id": thread_id,
        "work_root": work_root,
        "on_delta": on_delta,
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
    on_delta: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(runtime_state_store, RuntimeCheckpointStore):
        raise RuntimeError("Runtime history storage does not support manual compaction")
    raw_history = await runtime_state_store.get_history(thread_id)
    messages = [message for item in raw_history if (message := _chat_message_from_dict(item)) is not None]
    result = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=messages,
            llm_client=llm_client,
            model=model,
            target_tokens=MANUAL_COMPACTION_TARGET_TOKENS,
            retain_tail_count=MAX_RETAIN_MESSAGE_COUNT,
            on_delta=on_delta,
        )
    )
    if result.status != "compacted":
        raise ValueError("Context compaction did not produce a summary")
    state = await runtime_state_store.get(thread_id) or RuntimeState(session_id=thread_id)
    await runtime_state_store.save_checkpoint(
        state,
        [message.to_dict() for message in result.replacement_messages],
    )
    return {
        "status": "compacted",
        "session_id": thread_id,
        "compacted_messages": result.compacted_count,
        "retained_messages": result.retained_count,
        "before_tokens": result.before_tokens,
        "after_tokens": result.after_tokens,
        "target_tokens": result.target_tokens,
        "trigger": "manual",
        "summary": result.summary,
    }


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
    "MANUAL_COMPACTION_TARGET_TOKENS",
    "MAX_RETAIN_MESSAGE_COUNT",
    "compact_runtime_history",
    "execute_command_action",
]
