from __future__ import annotations

import inspect
from copy import deepcopy
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from lamtools_core.config.retry_store import (
    load_model_retry_config,
    loop_policy_overrides,
    retry_policy_from_config,
)
from lamtools_core.context_compaction import (
    ContextCompactionController,
)
from lamtools_core.context_compaction_budget import (
    TokenBudget,
    resolve_compaction_budget,
)
from lamtools_core.llm import ChatMessage, LLMClient, LLMToolCall
from lamtools_core.llm.shallow_thinking import ShallowThinkingClient
from lamtools_core.mem import MemoryStoreProtocol
from lamtools_core.mem.dreaming import dream_session
from lamtools_core.runtime import RuntimeCheckpointStore, RuntimeState, RuntimeStateStore
from lamtools_core.tokens import estimate_message_tokens


CommandActionHandler = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]


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
    runtime_snapshot = metadata.get("runtime_snapshot")
    runtime_snapshot = runtime_snapshot if isinstance(runtime_snapshot, dict) else {}
    messages = await _load_effective_compaction_history(
        runtime_state_store,
        thread_id,
        metadata,
    )

    total_context_window_tokens = _first_positive_int(
        runtime_snapshot.get("context_window_tokens"),
        metadata.get("context_window_tokens"),
        metrics.get("total_context_window_tokens"),
        loop_policy.get("context_window_tokens"),
    )
    reserved_output_tokens = _first_positive_int(
        runtime_snapshot.get("max_tokens"),
        metadata.get("max_tokens"),
        metrics.get("reserved_output_tokens"),
    )
    available_window = _first_positive_int(metrics.get("context_window_tokens"))
    if total_context_window_tokens > 0:
        computed_window = total_context_window_tokens - reserved_output_tokens
        if computed_window <= 0:
            raise ValueError(
                "Model max output tokens must be smaller than its total context window: "
                f"{reserved_output_tokens} >= {total_context_window_tokens}"
            )
        available_window = computed_window
    history_tokens = estimate_message_tokens(
        [message.to_dict() for message in messages],
    )
    request_overhead_tokens = max(
        0,
        _first_positive_int(metrics.get("estimated_prompt_tokens")) - history_tokens,
    )
    window = max(1, available_window or history_tokens)

    retry_config = load_model_retry_config()
    retry_overrides = loop_policy_overrides(retry_config)
    model_retries = _first_positive_int(
        loop_policy.get("model_retries"),
        retry_overrides.get("model_retries"),
        1,
    )
    model_timeout_seconds = _first_positive_number(
        loop_policy.get("model_timeout_seconds"),
        retry_overrides.get("model_timeout_seconds"),
    )
    summary_output_tokens = _first_positive_int(
        loop_policy.get("compact_summary_output_tokens"),
    ) or None
    safety_margin_tokens = _first_nonnegative_int(
        loop_policy.get("compact_safety_margin_tokens"),
    )

    trigger_ratio = _first_positive_number(
        loop_policy.get("compact_trigger_ratio"),
        metadata.get("compact_trigger_ratio"),
    ) or 0.8
    limit_ratio = _first_positive_number(
        loop_policy.get("compact_limit_ratio"),
        metadata.get("compact_limit_ratio"),
    ) or 0.6
    trigger_tokens = _first_positive_int(
        loop_policy.get("compact_trigger_tokens"),
        metrics.get("context_compaction_trigger_tokens"),
        metadata.get("compact_trigger_tokens"),
    ) or int(window * trigger_ratio)
    target_tokens = _first_positive_int(
        loop_policy.get("compact_limit_tokens"),
        metadata.get("compact_limit_tokens"),
    ) or int(window * limit_ratio)
    budget = resolve_compaction_budget(
        context_window=window,
        trigger_ratio=trigger_ratio,
        target_ratio=limit_ratio,
        trigger_tokens=trigger_tokens,
        target_tokens=target_tokens,
    )

    active_model = str(
        runtime_snapshot.get("model_id")
        or metadata.get("model_id")
        or metrics.get("model_id")
        or model
    ).strip()
    previous_model = str(metrics.get("model_id") or "").strip()
    previous_window = _first_positive_int(metrics.get("context_window_tokens"))
    model_switched = bool(
        previous_model and active_model and previous_model != active_model
    )
    provider = _provider_for_runtime_options(
        llm_client,
        active_model=active_model,
        runtime_snapshot=runtime_snapshot,
        metadata=metadata,
    )

    async def emit_delta(delta: str) -> None:
        if on_event is None:
            return
        emitted = on_event(
            {
                "status": "running",
                "phase": "segment",
                "label": "正在压缩上下文",
                "delta": delta,
            }
        )
        if inspect.isawaitable(emitted):
            await emitted

    controller = ContextCompactionController(
        llm_client=provider,
        estimate_request_tokens=lambda current, fast: (
            estimate_message_tokens(
                [message.to_dict() for message in current],
                fast=fast,
            )
            + request_overhead_tokens
        ),
        on_delta=emit_delta,
        on_event=on_event,
        model_retries=model_retries,
        model_timeout_seconds=model_timeout_seconds,
        retry_policy=retry_policy_from_config(retry_config),
        summary_output_tokens=summary_output_tokens,
        safety_margin_tokens=safety_margin_tokens,
    )
    measurement = controller.measure(messages, trigger_tokens=budget.trigger_tokens)
    execution = await controller.compact(
        messages,
        budget=budget,
        timeout=None,
        current_model=active_model,
        previous_model=previous_model,
        previous_window=previous_window,
        model_switched=model_switched,
        trigger="manual",
        measurement=measurement,
        force=True,
    )
    result = execution.result
    if result is None:
        return {
            "status": "not_needed",
            "session_id": thread_id,
            "trigger": "manual",
            "summary": "",
        }

    if result.status != "compacted":
        return {
            **result.display_payload,
            "session_id": thread_id,
            "summary": result.summary,
        }
    await _persist_manual_compaction_metadata(
        runtime_state_store,
        state,
        result=result,
        execution=execution,
        budget=budget,
        before_messages=len(messages),
        total_context_window_tokens=total_context_window_tokens,
        reserved_output_tokens=reserved_output_tokens,
    )
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


async def _load_effective_compaction_history(
    runtime_state_store: RuntimeCheckpointStore,
    thread_id: str,
    metadata: Mapping[str, Any],
) -> list[ChatMessage]:
    """Load the same summary + retained history view used by the kernel."""
    compaction = metadata.get("context_compaction")
    compaction = compaction if isinstance(compaction, dict) else {}
    summary = str(compaction.get("summary") or "")
    try:
        boundary = max(0, int(compaction.get("summary_seq") or 0))
    except (TypeError, ValueError):
        boundary = 0
    raw_history = await runtime_state_store.get_history(thread_id, after_seq=boundary)
    if boundary > 0 and not raw_history:
        raw_history = await runtime_state_store.get_history(thread_id)
        boundary = 0
    elif boundary > 0:
        # Legacy stores may accept ``after_seq`` but return their complete
        # history blob. Detect that shape without issuing another history read.
        history_max_seq = getattr(runtime_state_store, "history_max_seq", None)
        if callable(history_max_seq):
            max_seq = history_max_seq(thread_id)
            if inspect.isawaitable(max_seq):
                max_seq = await max_seq
            if isinstance(max_seq, int) and max_seq > 0 and len(raw_history) == max_seq:
                raw_history = raw_history[boundary:]

    messages: list[ChatMessage] = []
    for index, item in enumerate(raw_history):
        message = _chat_message_from_dict(item)
        if message is None:
            continue
        if "history_seq" not in message.metadata:
            message.metadata["history_seq"] = boundary + index + 1
        if (
            message.role == "system"
            and message.metadata.get("key") == "context_compaction_summary"
        ):
            continue
        messages.append(message)
    if summary.strip():
        messages.insert(
            0,
            ChatMessage(
                role="system",
                content=summary,
                metadata={"key": "context_compaction_summary"},
            ),
        )
    return messages


def _provider_for_runtime_options(
    llm_client: LLMClient | None,
    *,
    active_model: str,
    runtime_snapshot: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> LLMClient | None:
    """Apply the persisted per-session model/thinking settings."""
    if llm_client is None:
        return None
    provider: Any = llm_client
    reasoning_level = str(
        runtime_snapshot.get("reasoning_level")
        or metadata.get("reasoning_level")
        or ""
    ).strip()
    thinking_enabled = _first_bool(
        runtime_snapshot.get("thinking_enabled"), metadata.get("thinking_enabled")
    )
    thinking_budget = _first_positive_int(
        runtime_snapshot.get("thinking_budget"), metadata.get("thinking_budget")
    ) or None
    configure = getattr(provider, "with_runtime_options", None)
    if callable(configure):
        try:
            configured = configure(
                model_id=active_model,
                reasoning_level=reasoning_level,
                thinking_enabled=thinking_enabled,
                thinking_budget=thinking_budget,
            )
        except TypeError:
            configured = configure(
                model_id=active_model,
                thinking_enabled=thinking_enabled,
                thinking_budget=thinking_budget,
            )
        if configured is not None:
            provider = configured
    shallow_thinking_enabled = _first_bool(
        runtime_snapshot.get("shallow_thinking_enabled"),
        metadata.get("shallow_thinking_enabled"),
    )
    if shallow_thinking_enabled:
        provider = ShallowThinkingClient(provider)
    return provider


async def _persist_manual_compaction_metadata(
    runtime_state_store: RuntimeStateStore,
    state: RuntimeState,
    *,
    result: Any,
    execution: Any,
    budget: TokenBudget,
    before_messages: int,
    total_context_window_tokens: int,
    reserved_output_tokens: int,
) -> None:
    """Persist the automatic-compaction metadata without rewriting history."""
    boundary = 0
    if result.retained_messages:
        first_retained = result.retained_messages[0]
        first_seq = (
            first_retained.metadata.get("history_seq")
            if isinstance(first_retained.metadata, dict)
            else None
        )
        if isinstance(first_seq, int) and first_seq > 0:
            boundary = first_seq - 1
    if not isinstance(state.metadata, dict):
        state.metadata = {}
    state.metadata["context_compaction"] = {
        "summary": result.summary,
        "summary_seq": boundary,
        "compacted_count": result.compacted_count,
        "retained_count": result.retained_count,
        "before_tokens": result.before_tokens,
        "after_tokens": result.after_tokens,
    }
    previous_metrics = state.metadata.get("runtime_context_metrics")
    metrics = dict(previous_metrics) if isinstance(previous_metrics, dict) else {}
    state.metadata["runtime_context_metrics"] = {
        **metrics,
        "estimated_prompt_tokens": result.after_tokens,
        "context_window_tokens": budget.context_window,
        "total_context_window_tokens": total_context_window_tokens,
        "reserved_output_tokens": reserved_output_tokens,
        "context_compaction_trigger_tokens": budget.trigger_tokens,
        "context_compacted": True,
        "context_compaction_mode": "structured_summary",
        "context_tokens_before_compaction": result.before_tokens,
        "context_tokens_after_compaction": result.after_tokens,
        "context_messages_before_compaction": before_messages,
        "context_messages_after_compaction": len(result.replacement_messages),
        "context_compaction_strategy": execution.strategy,
        "context_compaction_execution_model": execution.execution_model,
    }
    await runtime_state_store.save(state)


def _first_positive_number(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, bool):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def _first_nonnegative_int(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, bool) or value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed >= 0:
            return parsed
    return None


def _first_bool(*values: Any) -> bool | None:
    for value in values:
        if isinstance(value, bool):
            return value
    return None


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
        provider_state=deepcopy(value.get("provider_state"))
        if "provider_state" in value
        else None,
    )


__all__ = [
    "CommandActionHandler",
    "compact_runtime_history",
    "dream_session_memory",
    "execute_command_action",
]
