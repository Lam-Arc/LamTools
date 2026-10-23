from __future__ import annotations

import inspect
import logging
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
from lamtools_core.context_compaction.state import (
    load_compaction_history as _load_effective_compaction_history,
    persist_compaction,
)
from lamtools_core.context_compaction_budget import (
    TokenBudget,
    context_measurement,
    load_retained_steps,
    resolve_compaction_budget,
    resolve_retained_steps,
)
from lamtools_core.dialogue_records import COMPACTION_RECORD, build_compaction_record
from lamtools_core.llm import ChatMessage, LLMClient
from lamtools_core.llm.shallow_thinking import ShallowThinkingClient
from lamtools_core.runtime import RuntimeCheckpointStore, RuntimeState, RuntimeStateStore
from lamtools_core.tokens import estimate_message_tokens


CommandActionHandler = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]

_logger = logging.getLogger(__name__)


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
    """Manually compact a session's runtime history.

    Compaction is not a one-time state: a session may compact any number of
    times; there is no permanent "already compacted" status.
    """
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
    # The compaction summarizes exactly what a normal request would carry at
    # this point: same assembly, same image handling.  If the agent can still
    # run, this input is provably within what the gateway accepts.
    from lamtools_core.llm.image_payload import degrade_stale_message_images

    messages = degrade_stale_message_images(
        messages, current_step=int(getattr(state, "turn_count", 0) or 0)
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
    # user:“去重构吧”+(容量测量与协议开销分开，禁止用真实用量减本地历史估算)。
    request_overhead_tokens = max(0, _first_positive_int(metrics.get("context_request_overhead_tokens")))
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
    retained_override = loop_policy.get("compact_retained_steps")
    retained_steps = (
        resolve_retained_steps(retained_override)
        if retained_override is not None
        else load_retained_steps()
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
        # Summary output follows the output limit this session's model already
        # runs with (the reserved output tokens above).  The fixed 4096 default
        # truncated long summaries, and a truncated summary is rejected whole.
        model_output_tokens=reserved_output_tokens,
        safety_margin_tokens=safety_margin_tokens,
        request_metadata={"_runtime_session_id": state.session_id},
    )
    measurement = context_measurement(
        metrics, model_id=active_model,
        estimate=lambda: estimate_message_tokens([m.to_dict() for m in messages]) + request_overhead_tokens,
    )
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
        retained_steps=retained_steps,
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
        source_messages=messages,
        budget=budget,
        retained_steps=retained_steps,
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
    runtime_state_store, state, **kwargs,
) -> None:
    # user:“去重构吧”+(手动仅产生压缩信号，保存与自动路径完全一致)。
    await persist_compaction(runtime_state_store, state, **kwargs)
    await _persist_manual_compaction_record(
        runtime_state_store, state, result=kwargs["result"], execution=kwargs["execution"],
        retained_steps=kwargs["retained_steps"], before_messages=kwargs["before_messages"],
    )


async def _persist_manual_compaction_record(
    runtime_state_store: RuntimeStateStore,
    state: RuntimeState,
    *,
    result: Any,
    execution: Any,
    retained_steps: int,
    before_messages: int,
) -> None:
    """Append one complete compaction control record (best effort).

    Mirrors the automatic path: the record carries the full summary, folded and
    retained identity, parameters and watermark.  It is a pure addition to the
    append-only dialogue log and never changes the existing rewrite/load
    behaviour.
    """
    append = getattr(runtime_state_store, "append_dialogue_record", None)
    if not callable(append) or result.summary_message is None:
        return
    try:
        summary_message = result.summary_message
        retained = list(result.retained_messages)
        record = build_compaction_record(
            trigger="manual",
            summary_message=summary_message,
            retained=retained,
            folded=list(result.compacted_messages),
            sent_messages=[summary_message, *retained],
            prefix_count=len(result.prefix_messages),
            limit_tokens=int(result.limit_tokens or 0),
            trigger_tokens=int(result.limit_tokens or 0),
            retained_steps=int(retained_steps or 0),
            before_tokens=int(result.before_tokens or 0),
            after_tokens=int(result.after_tokens or 0),
            before_messages=int(before_messages or 0),
            after_messages=len([summary_message, *retained]),
            segments=int(result.segment_count or 0),
            strategy=str(getattr(execution, "strategy", "") or ""),
            execution_model=str(getattr(execution, "execution_model", "") or ""),
            recent_user_messages=list(result.recent_user_messages),
        )
        await append(
            state.session_id,
            kind=COMPACTION_RECORD,
            record=record,
            watermark=int(record.get("watermark") or 0),
        )
    except Exception:  # noqa: BLE001 — bookkeeping must never break a command
        _logger.warning(
            "[command_execution:_persist_manual_compaction_record] failed sid=%s",
            state.session_id,
            exc_info=True,
        )


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




__all__ = [
    "CommandActionHandler",
    "compact_runtime_history",
    "execute_command_action",
]
