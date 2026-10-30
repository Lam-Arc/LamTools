"""One durable context view for automatic and manual compaction.

user:“压缩信号有两条路径来触发：一条是自动压缩，另一条是手动/compact”
+两条入口共用加载和保存，摘要只覆盖视图，不删除原始消息。
"""
from __future__ import annotations

import inspect
from copy import deepcopy
from collections.abc import Mapping
from typing import Any, TYPE_CHECKING

from lamtools_core.llm import ChatMessage, LLMToolCall
from lamtools_core.runtime import RuntimeCheckpointStore, RuntimeState, RuntimeStateStore
from lamtools_core.context_compaction_budget import TokenBudget
from .formatting import RECENT_USER_MESSAGES_METADATA_KEY, extract_recent_user_messages
from .models import ContextCompactionResult

if TYPE_CHECKING:
    from .controller import CompactionExecution

async def load_compaction_history(
    runtime_state_store: RuntimeCheckpointStore,
    thread_id: str,
    metadata: Mapping[str, Any],
) -> list[ChatMessage]:
    """Load the same summary + retained history view used by the kernel."""
    compaction = metadata.get("context_compaction")
    compaction = compaction if isinstance(compaction, dict) else {}
    summary = str(compaction.get("summary") or "")
    max_seq: int | None = None
    history_max_seq = getattr(runtime_state_store, "history_max_seq", None)
    if callable(history_max_seq):
        try:
            max_value = history_max_seq(thread_id)
            if inspect.isawaitable(max_value):
                max_value = await max_value
            if not isinstance(max_value, bool):
                max_seq = max(0, int(max_value))
        except (TypeError, ValueError, OSError):
            max_seq = None

    boundary, compacted_seqs = _validated_compaction_filter(compaction, max_seq)

    if compacted_seqs:
        # Manual compaction intentionally leaves durable rows untouched. Read
        # the full set and remove only rows folded into the summary; this keeps
        # retained model Steps even when user rows are interspersed between
        # them.  A zero-tail compaction is a safe fast path: when every known
        # row through the durable high-water mark was compacted, ask for the
        # empty incremental tail at that boundary instead of falling back to
        # the full history blob.
        compacted_through_max = (
            max_seq is not None
            and max_seq > 0
            and boundary == max_seq
            and compacted_seqs == set(range(1, max_seq + 1))
        )
        if compacted_through_max:
            raw_history = await runtime_state_store.get_history(
                thread_id,
                after_seq=boundary,
            )
            # Legacy blob stores may ignore ``after_seq`` and return the full
            # blob.  Slice that shape locally without issuing a second full
            # read; an actual empty incremental tail remains empty.
            if len(raw_history) == max_seq:
                raw_history = raw_history[boundary:]
        else:
            raw_history = await runtime_state_store.get_history(thread_id)
            boundary = 0
    else:
        raw_history = await runtime_state_store.get_history(thread_id, after_seq=boundary)
        if boundary > 0 and max_seq == 0:
            # Legacy blob stores ignore ``after_seq`` and report no row max.
            full_history = await runtime_state_store.get_history(thread_id)
            raw_history = full_history[boundary:]
        elif boundary > 0 and max_seq is not None and len(raw_history) == max_seq:
            # Legacy-compatible stores may return all rows despite accepting
            # the keyword; detect that shape without a second read.
            raw_history = raw_history[boundary:]
        elif boundary > 0 and not raw_history and (
            max_seq is None or max_seq != boundary
        ):
            # A stale anchor is recoverable only when rows are known to exist
            # beyond it. An empty result at the current max is legitimate.
            raw_history = await runtime_state_store.get_history(thread_id)
            boundary = 0

    messages: list[ChatMessage] = []
    for index, item in enumerate(raw_history):
        message = _chat_message_from_dict(item)
        if message is None:
            continue
        if "history_seq" not in message.metadata:
            message.metadata["history_seq"] = boundary + index + 1
        if _message_history_seq(message) in compacted_seqs:
            continue
        if (
            message.role == "system"
            and message.metadata.get("key") == "context_compaction_summary"
        ):
            continue
        messages.append(message)
    if summary.strip():
        raw_recent = compaction.get(RECENT_USER_MESSAGES_METADATA_KEY)
        recent_users = (
            list(raw_recent)
            if isinstance(raw_recent, list) and all(isinstance(item, str) for item in raw_recent)
            else extract_recent_user_messages(summary)
        )
        messages.insert(
            0,
            ChatMessage(
                role="system",
                content=summary,
                metadata={
                    "key": "context_compaction_summary",
                    RECENT_USER_MESSAGES_METADATA_KEY: recent_users,
                },
            ),
        )
    return messages


def rebase_compaction_history(
    runtime_state: dict[str, Any], history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Renumber a restored transcript and its summary view together."""
    # user:“修”+(回退或恢复重新编号时，压缩标记必须按原消息身份一起映射，不能误伤后续消息)。
    result = deepcopy(runtime_state)
    metadata = result.get("metadata")
    compaction = metadata.get("context_compaction") if isinstance(metadata, dict) else None
    compacted: set[int] = set()
    old_seqs = []
    for index, message in enumerate(history, 1):
        old_metadata = message.get("metadata")
        old_seqs.append(max(_history_seq_set([
            old_metadata.get("history_seq") if isinstance(old_metadata, dict) else index,
        ]), default=index))
    if isinstance(compaction, dict):
        boundary, old_compacted = _validated_compaction_filter(compaction, max(old_seqs, default=0))
        # Older checkpoints only stored a prefix boundary, not an explicit set.
        explicit = isinstance(compaction.get("compacted_history_seqs"), list)
        for index, old_seq in enumerate(old_seqs, 1):
            if old_seq in old_compacted or (not explicit and old_seq <= boundary):
                compacted.add(index)
        compaction["compacted_history_seqs"] = sorted(compacted)
        compaction["summary_seq"] = next(
            (index - 1 for index in range(1, len(history) + 1) if index not in compacted),
            len(history),
        )
    for index, message in enumerate(history, 1):
        message_metadata = message.get("metadata")
        message["metadata"] = {
            **(message_metadata if isinstance(message_metadata, dict) else {}),
            "history_seq": index,
        }
    return result



async def persist_compaction(
    runtime_state_store: RuntimeStateStore,
    state: RuntimeState,
    *,
    result: ContextCompactionResult,
    execution: CompactionExecution,
    source_messages: list[ChatMessage],
    budget: TokenBudget,
    retained_steps: int,
    before_messages: int,
    total_context_window_tokens: int,
    reserved_output_tokens: int,
    trigger: str = "manual",
    extra_messages: list[ChatMessage] | None = None,
) -> None:
    """Persist the automatic-compaction metadata without rewriting history."""
    # user:“去重构吧”+(只提交摘要视图；原始历史始终保留，自动与手动共用事务边界)。
    original_state = state
    state = deepcopy(state)
    retained_ids = {id(message) for message in result.retained_messages}
    prefix_ids = {id(message) for message in result.prefix_messages}
    retained_seqs = {_message_history_seq(message) for message in result.retained_messages}
    current_compacted_history_seqs = {
        int(message.metadata.get("history_seq"))
        for message in result.compacted_messages
        if isinstance(message.metadata, dict)
        and isinstance(message.metadata.get("history_seq"), int)
        and message.metadata.get("history_seq") > 0
    }
    # The fitter may drop a preferred retained Step to satisfy the exact
    # target. It is absent from ``result.compacted_messages`` as well as the
    # final retained list, but it is still folded into the new summary and
    # must be recorded so future manual loads do not resurrect that raw row.
    current_compacted_history_seqs.update(
        int(message.metadata.get("history_seq"))
        for message in source_messages
        if id(message) not in retained_ids
        and id(message) not in prefix_ids
        and _message_history_seq(message) not in retained_seqs
        and isinstance(message.metadata, dict)
        and isinstance(message.metadata.get("history_seq"), int)
        and message.metadata.get("history_seq") > 0
    )
    previous_compaction = state.metadata.get("context_compaction") if isinstance(state.metadata, dict) else None
    previous_compacted_history_seqs = (
        _history_seq_set(previous_compaction.get("compacted_history_seqs"))
        if isinstance(previous_compaction, dict)
        else set()
    )
    compacted_history_seqs = sorted(
        previous_compacted_history_seqs | current_compacted_history_seqs
    )

    retained_history_seqs = [
        int(message.metadata.get("history_seq"))
        for message in result.retained_messages
        if isinstance(message.metadata, dict)
        and isinstance(message.metadata.get("history_seq"), int)
        and message.metadata.get("history_seq") > 0
    ]
    # A retained row is the durable resume point.  Use the first retained
    # sequence, even when the compacted set contains a later interspersed row;
    # using max(compacted) would hide the retained span on the next manual run.
    boundary = max(0, retained_history_seqs[0] - 1) if retained_history_seqs else 0
    if not retained_history_seqs:
        # Zero-tail compaction has no retained row to anchor against. Prefer a
        # verified durable high-water mark; a known compacted sequence is the
        # fallback for stores that do not expose one.
        history_max_seq = getattr(runtime_state_store, "history_max_seq", None)
        if callable(history_max_seq):
            try:
                max_value = history_max_seq(state.session_id)
                if inspect.isawaitable(max_value):
                    max_value = await max_value
                if not isinstance(max_value, bool):
                    boundary = max(0, int(max_value))
            except (TypeError, ValueError, OSError):
                boundary = max(compacted_history_seqs, default=0)
        else:
            boundary = max(compacted_history_seqs, default=0)
    if not isinstance(state.metadata, dict):
        state.metadata = {}
    state.metadata["context_compaction"] = {
        "trigger": trigger,
        "summary": result.summary,
        "summary_seq": boundary,
        "compacted_count": result.compacted_count,
        "retained_count": result.retained_count,
        "before_tokens": result.before_tokens,
        "after_tokens": result.after_tokens,
        "retained_steps": retained_steps,
        RECENT_USER_MESSAGES_METADATA_KEY: list(result.recent_user_messages),
        "compacted_history_seqs": compacted_history_seqs,
    }
    # The manual compaction replaced the message view, so the provider count
    # from the pre-compaction request no longer describes the live context.
    state.metadata.pop("context_usage_anchor", None)
    previous_metrics = state.metadata.get("runtime_context_metrics")
    metrics = dict(previous_metrics) if isinstance(previous_metrics, dict) else {}
    metrics.pop("context_usage_prompt_tokens", None)
    state.metadata.pop("_context_compaction_run_id", None)
    state.metadata["runtime_context_metrics"] = {
        **metrics,
        "estimated_prompt_tokens": result.after_tokens,
        "context_tokens": result.after_tokens,
        "context_measurement_source": "estimate",
        "context_window_tokens": budget.context_window,
        "total_context_window_tokens": total_context_window_tokens,
        "reserved_output_tokens": reserved_output_tokens,
        "context_compaction_trigger_tokens": budget.trigger_tokens,
        "context_compaction_retained_steps": retained_steps,
        "context_compacted": True,
        "context_compaction_mode": "structured_summary",
        "context_tokens_before_compaction": result.before_tokens,
        "context_tokens_after_compaction": result.after_tokens,
        "context_messages_before_compaction": before_messages,
        "context_messages_after_compaction": len(result.replacement_messages),
        "context_compaction_strategy": execution.strategy,
        "context_compaction_execution_model": execution.execution_model,
    }
    rows = [deepcopy(message.to_dict()) for message in (extra_messages or [])]
    commit = getattr(runtime_state_store, "save_compaction", None)
    if callable(commit):
        await commit(state, rows)
    else:
        # Legacy stores may only implement the original checkpoint protocol.
        # Append first: an interrupted save can leave a harmless extra row,
        # never a summary baseline whose source snapshot was not persisted.
        if rows:
            await runtime_state_store.append_history(state.session_id, rows)
        await runtime_state_store.save(state)
    for message, row in zip(extra_messages or [], rows):
        if isinstance(row.get("metadata", {}).get("history_seq"), int):
            message.metadata["history_seq"] = row["metadata"]["history_seq"]
    original_state.metadata = state.metadata
    if hasattr(state, "_runtime_store_revision"):
        setattr(original_state, "_runtime_store_revision", state._runtime_store_revision)


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


def _message_history_seq(message: ChatMessage) -> int:
    raw = message.metadata.get("history_seq")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def _history_seq_set(value: Any) -> set[int]:
    if not isinstance(value, list):
        return set()
    result: set[int] = set()
    for item in value:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            result.add(parsed)
    return result


def _validated_compaction_filter(
    compaction: dict[str, Any], max_seq: int | None,
) -> tuple[int, set[int]]:
    boundary = max(_history_seq_set([compaction.get("summary_seq")]), default=0)
    compacted_seqs = _history_seq_set(compaction.get("compacted_history_seqs"))
    # user:“修”+(加载已有异常会话和恢复旧快照时，都先清除不属于当前编号范围的压缩标记)。
    # Preserve the summary; recover raw rows instead of silently hiding them.
    # Zero may denote a legacy blob store, whose row watermark is unavailable.
    if max_seq is not None and max_seq > 0 and max(boundary, max(compacted_seqs, default=0)) > max_seq:
        boundary = 0
        compacted_seqs = set()
        compaction["summary_seq"] = 0
        compaction["compacted_history_seqs"] = []
    return boundary, compacted_seqs
