"""Deterministic context planning and summary-request chunking."""

from __future__ import annotations

from lamtools_core.context_compaction_budget import (
    DEFAULT_RETAINED_STEPS,
    TokenBudget,
    load_retained_steps,
    resolve_retained_steps,
)
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
    """Plan a Step tail and the history that must be summarized.

    By default no Step is retained, so the complete non-prefix history enters
    summarization. A positive setting retains that many latest model Steps;
    recent user instructions are appended to the summary later by the
    controller instead of remaining as raw messages.
    """

    def __init__(self, estimate_tokens: CompactionTokenEstimator | None = None) -> None:
        self._estimate_tokens = estimate_tokens

    def plan(
        self,
        messages: list[ChatMessage],
        *,
        budget: TokenBudget,
        preserve_latest_user: bool = True,
        retained_steps: int | None = None,
        estimate_tokens: CompactionTokenEstimator | None = None,
    ) -> CompactionPlan | None:
        return _select_layout(
            messages,
            preserve_latest_user=preserve_latest_user,
            compact_all=False,
            limit_tokens=budget.target_tokens,
            retained_steps=retained_steps,
            estimate_tokens=estimate_tokens or self._estimate_tokens,
        )


def select_context_compaction_layout(
    messages: list[ChatMessage],
    *,
    preserve_latest_user: bool = True,
    compact_all: bool = False,
    limit_tokens: int = 0,
    retained_steps: int | None = None,
    estimate_tokens: CompactionTokenEstimator | None = None,
) -> CompactionPlan | None:
    """Compatibility wrapper for the pre-planner API."""
    return _select_layout(
        messages,
        preserve_latest_user=preserve_latest_user,
        compact_all=compact_all,
        limit_tokens=limit_tokens,
        retained_steps=retained_steps,
        estimate_tokens=estimate_tokens,
    )


def _select_layout(
    messages: list[ChatMessage],
    *,
    preserve_latest_user: bool,
    compact_all: bool,
    limit_tokens: int,
    retained_steps: int | None,
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

    prefix_messages = list(messages[:prefix_end])
    # ``compact_all`` and ``preserve_latest_user`` remain accepted for callers
    # of the old API. Automatic and manual compaction now share one preferred
    # retention policy; the fitter may still discard its oldest selected units
    # when the token budget requires it.
    _ = compact_all, preserve_latest_user
    resolved_steps = (
        load_retained_steps()
        if retained_steps is None
        else resolve_retained_steps(retained_steps)
    )
    protected_indexes = _protected_message_indexes(
        body,
        retained_steps=resolved_steps,
    )
    estimator = estimate_tokens or (
        lambda values: estimate_message_tokens(
            [message.to_dict() for message in values]
        )
    )
    fixed_tokens = estimator(prefix_messages)
    retained_budget = max(
        0,
        limit_tokens - fixed_tokens - _summary_output_limit(limit_tokens),
    )
    latest_user_index = next(
        (
            index
            for index in range(len(body) - 1, -1, -1)
            if body[index].role == "user" and not body[index].metadata.get("internal")
        ),
        None,
    )

    # Step/user counts define the preferred tail, while the token target is
    # authoritative. Move its oldest units into the summary input until the
    # retained span leaves the normal summary allowance. The newest user is
    # the only non-droppable boundary and is checked against the hard target
    # by the controller before any model call.
    for unit in _retention_index_units(body):
        retained_values = [
            message for index, message in enumerate(body) if index in protected_indexes
        ]
        retained_tokens = max(
            0,
            estimator([*prefix_messages, *retained_values]) - fixed_tokens,
        )
        if limit_tokens <= 0 or retained_tokens <= retained_budget:
            break
        if latest_user_index is not None and latest_user_index in unit:
            continue
        protected_indexes.difference_update(unit)

    retained_messages = [
        message for index, message in enumerate(body) if index in protected_indexes
    ]
    compacted_messages = [
        message for index, message in enumerate(body) if index not in protected_indexes
    ]
    if not compacted_messages:
        if limit_tokens <= 0 or estimator([*prefix_messages, *retained_messages]) <= limit_tokens:
            return None
    return CompactionPlan(
        system_prefix=prefix_messages,
        messages_to_summarize=compacted_messages,
        recent_messages=retained_messages,
    )


def _protected_message_indexes(
    messages: list[ChatMessage],
    *,
    retained_steps: int = DEFAULT_RETAINED_STEPS,
) -> set[int]:
    """Return the configured latest model Steps.

    A Step starts at an assistant model message and owns every immediately
    following ``tool`` result.  The returned indexes are always in source
    order when projected back onto ``messages``; no token budget is consulted.
    """
    step_groups = _model_step_groups(messages)
    selected: set[int] = set()
    step_count = max(0, int(retained_steps))
    if step_count:
        for group in step_groups[-step_count:]:
            selected.update(group)
    return selected


def _model_step_groups(messages: list[ChatMessage]) -> list[list[int]]:
    """Group assistant messages with their following contiguous tool results."""
    groups: list[list[int]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role != "assistant":
            index += 1
            continue
        group = [index]
        index += 1
        while index < len(messages) and messages[index].role == "tool":
            group.append(index)
            index += 1
        groups.append(group)
    return groups


def _retention_index_units(messages: list[ChatMessage]) -> list[list[int]]:
    """Return source-ordered units suitable for summary/drop boundaries."""
    units: list[list[int]] = []
    index = 0
    while index < len(messages):
        unit = [index]
        message = messages[index]
        index += 1
        if message.role == "assistant":
            while index < len(messages) and messages[index].role == "tool":
                unit.append(index)
                index += 1
        units.append(unit)
    return units


def _summary_output_limit(limit_tokens: int) -> int:
    return max(256, min(4096, limit_tokens // 3 if limit_tokens > 0 else 4096))


def _semantic_message_groups(messages: list[ChatMessage]) -> list[list[ChatMessage]]:
    groups: list[list[ChatMessage]] = []
    current: list[ChatMessage] = []
    for message in messages:
        starts_group = (
            (message.role == "user" and not message.metadata.get("internal"))
            or message.metadata.get("key") == "compaction_segment_summary"
        )
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
