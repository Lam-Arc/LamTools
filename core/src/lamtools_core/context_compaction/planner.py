"""Deterministic context planning and summary-request chunking."""

from __future__ import annotations

from lamtools_core.context_compaction_budget import TokenBudget
from lamtools_core.llm import ChatMessage
from lamtools_core.tokens import estimate_message_tokens

from .formatting import truncate_text_to_tokens
from .models import (
    COMPACTION_PROMPT,
    CompactionPlan,
    CompactionTokenEstimator,
    ContextCompactionError,
)


MAX_COMPACTION_SEGMENT_INPUT_TOKENS = 64_000


def compaction_segment_input_limit(context_window_tokens: int) -> int:
    """Return the per-request input ceiling used by every compaction entrypoint."""
    window = max(0, int(context_window_tokens or 0))
    if window <= 0:
        return MAX_COMPACTION_SEGMENT_INPUT_TOKENS
    return window


class CompactionPlanner:
    """Plan which messages are summarized and which recent tail is retained."""

    def __init__(self, estimate_tokens: CompactionTokenEstimator | None = None) -> None:
        self._estimate_tokens = estimate_tokens

    def plan(
        self,
        messages: list[ChatMessage],
        *,
        budget: TokenBudget,
        preserve_latest_user: bool = True,
        estimate_tokens: CompactionTokenEstimator | None = None,
    ) -> CompactionPlan | None:
        return _select_layout(
            messages,
            preserve_latest_user=preserve_latest_user,
            limit_tokens=budget.target_tokens,
            estimate_tokens=estimate_tokens or self._estimate_tokens,
        )


def select_context_compaction_layout(
    messages: list[ChatMessage],
    *,
    preserve_latest_user: bool = True,
    limit_tokens: int = 0,
    estimate_tokens: CompactionTokenEstimator | None = None,
) -> CompactionPlan | None:
    """Compatibility wrapper for the pre-planner API."""
    return _select_layout(
        messages,
        preserve_latest_user=preserve_latest_user,
        limit_tokens=limit_tokens,
        estimate_tokens=estimate_tokens,
    )


def _select_layout(
    messages: list[ChatMessage],
    *,
    preserve_latest_user: bool,
    limit_tokens: int,
    estimate_tokens: CompactionTokenEstimator | None,
) -> CompactionPlan | None:
    prefix_end = 0
    for index, message in enumerate(messages):
        if message.role != "system":
            break
        if message.metadata.get("key") == "context_compaction_summary":
            break
        prefix_end = index + 1

    body = list(messages[prefix_end:])
    if not body:
        return None

    estimator = estimate_tokens or (
        lambda values: estimate_message_tokens([message.to_dict() for message in values])
    )
    prefix_messages = list(messages[:prefix_end])
    fixed_tokens = estimator(prefix_messages)
    retained_budget = max(0, limit_tokens - fixed_tokens - _summary_output_limit(limit_tokens))
    groups = _semantic_message_groups(body)
    retained_ids: set[int] = set()

    def retained_values(extra: list[ChatMessage] | None = None) -> list[ChatMessage]:
        selected = set(retained_ids)
        selected.update(id(message) for message in (extra or []))
        return [message for message in body if id(message) in selected]

    def retained_token_count(extra: list[ChatMessage] | None = None) -> int:
        return max(0, estimator([*prefix_messages, *retained_values(extra)]) - fixed_tokens)

    latest_group_index = len(groups) - 1
    if preserve_latest_user:
        latest_user = next((message for message in reversed(body) if message.role == "user"), None)
        if latest_user is not None:
            latest_group_index = next(
                index for index, group in enumerate(groups) if any(message is latest_user for message in group)
            )
            latest_group = groups[latest_group_index]
            required = (
                latest_group
                if retained_token_count(latest_group) <= retained_budget
                else [latest_user]
            )
            retained_ids.update(id(message) for message in required)

    start_index = latest_group_index if preserve_latest_user else len(groups)
    for group in reversed(groups[:start_index]):
        if len(retained_ids) + len(group) >= len(body):
            continue
        if retained_token_count(group) > retained_budget:
            break
        retained_ids.update(id(message) for message in group)

    retained_messages = retained_values()
    compacted_messages = [message for message in body if id(message) not in retained_ids]
    if not compacted_messages:
        return None
    return CompactionPlan(
        system_prefix=prefix_messages,
        messages_to_summarize=compacted_messages,
        recent_messages=retained_messages,
    )


def _summary_output_limit(limit_tokens: int) -> int:
    return max(256, min(4096, limit_tokens // 3 if limit_tokens > 0 else 4096))


def _semantic_message_groups(messages: list[ChatMessage]) -> list[list[ChatMessage]]:
    groups: list[list[ChatMessage]] = []
    current: list[ChatMessage] = []
    for message in messages:
        starts_group = message.role == "user" or message.metadata.get("key") == "compaction_segment_summary"
        if starts_group and current:
            groups.append(current)
            current = []
        current.append(message)
    if current:
        groups.append(current)
    return groups


def _compaction_instruction(existing_summary: str = "") -> ChatMessage:
    content = COMPACTION_PROMPT
    if existing_summary.strip():
        content += f"\n\nExisting compacted summary to preserve:\n{existing_summary.strip()}"
    return ChatMessage(
        role="user",
        content=content,
        metadata={"key": "context_compaction_instruction"},
    )


def _compaction_request_tokens(
    messages: list[ChatMessage],
    existing_summary: str = "",
    prefix_messages: list[ChatMessage] | None = None,
) -> int:
    return estimate_message_tokens(
        [message.to_dict() for message in [*(prefix_messages or []), *messages, _compaction_instruction(existing_summary)]]
    )


def _split_compaction_messages(
    messages: list[ChatMessage],
    *,
    input_limit_tokens: int,
    existing_summary: str,
    prefix_messages: list[ChatMessage] | None = None,
) -> list[list[ChatMessage]]:
    if not messages:
        return [[]]
    if input_limit_tokens <= 0 or _compaction_request_tokens(
        messages,
        existing_summary,
        prefix_messages,
    ) <= input_limit_tokens:
        return [list(messages)]

    chunks: list[list[ChatMessage]] = []
    current: list[ChatMessage] = []
    semantic_groups: list[list[ChatMessage]] = []
    for group in _semantic_message_groups(messages):
        group_existing = existing_summary if not semantic_groups else ""
        if _compaction_request_tokens(group, group_existing, prefix_messages) > input_limit_tokens:
            semantic_groups.extend(_split_oversized_semantic_group(group))
        else:
            semantic_groups.append(group)

    for group in semantic_groups:
        candidate = [*current, *group]
        candidate_existing = existing_summary if not chunks else ""
        if current and _compaction_request_tokens(candidate, candidate_existing, prefix_messages) > input_limit_tokens:
            chunks.append(current)
            current = list(group)
        else:
            current = candidate
        current_existing = existing_summary if not chunks else ""
        if _compaction_request_tokens(current, current_existing, prefix_messages) > input_limit_tokens:
            raise ContextCompactionError(
                "Context compaction failed: one complete conversation turn exceeds the model input limit"
            )
    if current:
        chunks.append(current)
    return chunks or [list(messages)]


def _split_oversized_semantic_group(messages: list[ChatMessage]) -> list[list[ChatMessage]]:
    """Split one oversized turn while keeping assistant/tool-result units intact."""
    groups: list[list[ChatMessage]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role != "assistant":
            groups.append([message])
            index += 1
            continue
        unit = [message]
        index += 1
        while index < len(messages) and messages[index].role == "tool":
            unit.append(messages[index])
            index += 1
        groups.append(unit)
    return groups


def _pair_compaction_messages(
    messages: list[ChatMessage],
    input_limit_tokens: int,
) -> list[list[ChatMessage]]:
    pairs: list[list[ChatMessage]] = []
    for index in range(0, len(messages), 2):
        pair = messages[index : index + 2]
        if input_limit_tokens > 0 and _compaction_request_tokens(pair) > input_limit_tokens:
            source_pair = pair
            budget = max(16, (input_limit_tokens - _compaction_request_tokens([])) // max(1, len(pair)))
            while True:
                pair = [
                    ChatMessage(
                        role=message.role,
                        content=truncate_text_to_tokens(str(message.content or ""), budget),
                    )
                    for message in source_pair
                ]
                if _compaction_request_tokens(pair) <= input_limit_tokens or budget <= 16:
                    break
                budget = max(16, budget - max(8, budget // 8))
        if input_limit_tokens > 0 and _compaction_request_tokens(pair) > input_limit_tokens:
            raise ContextCompactionError(
                "Context compaction failed: intermediate summaries exceed the model input limit"
            )
        pairs.append(pair)
    return pairs


__all__ = [
    "CompactionPlanner",
    "MAX_COMPACTION_SEGMENT_INPUT_TOKENS",
    "_compaction_instruction",
    "compaction_segment_input_limit",
    "select_context_compaction_layout",
]
