from __future__ import annotations

import asyncio

import pytest

from lamtools_core.context_compaction import (
    MAX_FIT_ATTEMPTS,
    NON_TEXT_USER_MESSAGE_PLACEHOLDER,
    CompactionBudgetExceeded,
    CompactionFitInput,
    CompactionFitter,
    CompactionOptions,
    CompactionSummary,
    ContextCompactionController,
    ContextCompactor,
    ContextCompactionRequest,
    compact_context,
    parse_compaction_summary,
    recent_user_message_text,
    select_context_compaction_layout,
    summarize_context_messages,
    truncate_text_to_tokens,
)
from lamtools_core.context_compaction_budget import SummaryTokenBudget, TokenBudget
from lamtools_core.llm import ChatMessage, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.tokens import estimate_message_tokens, estimate_text_tokens


class _CompactionClient:
    summary = (
        "1. Current Goal\n"
        "- Continue.\n\n"
        "2. User History, Instructions, And Decisions\n"
        "- Preserve earlier user constraints.\n\n"
        "3. Completed Work\n"
        "- Old context was summarized.\n\n"
        "4. Key Decisions And Constraints\n"
        "- Use one compaction interface.\n\n"
        "5. Files, APIs, Commands, And Results\n"
        "- None.\n\n"
        "6. Open Issues Or Risks\n"
        "- None.\n\n"
        "7. Next Best Actions\n"
        "- Continue from the latest raw user message.\n\n"
        "8. Rejected Or Superseded Directions\n"
        "- None.\n\n"
        "9. Next Actions\n"
        "- Continue."
    )

    def __init__(self) -> None:
        self.last_request = None

    async def complete(self, request):
        self.last_request = request
        return LLMResponse(
            content=self.summary,
            finish_reason="stop",
        )

    async def stream(self, request):
        raise NotImplementedError


class _AttributeErrorStreamingCompactionClient(_CompactionClient):
    async def complete(self, request):
        raise AssertionError("an AttributeError from streaming must not fall back")

    async def stream(self, request):
        raise AttributeError("stream implementation bug")


class _SegmentingCompactionClient:
    summary = (
        "1. Current Goal\n- Continue.\n\n"
        "2. User History, Instructions, And Decisions\n- Preserve constraints.\n\n"
        "3. Completed Work\n- Segment summarized.\n\n"
        "4. Key Decisions And Constraints\n- Keep evidence.\n\n"
        "5. Files, APIs, Commands, And Results\n- Recorded.\n\n"
        "6. Open Issues Or Risks\n- None.\n\n"
        "7. Next Best Actions\n- Continue.\n\n"
        "8. Rejected Or Superseded Directions\n- None.\n\n"
        "9. Next Actions\n- Continue."
    )

    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return LLMResponse(
            content=self.summary,
            finish_reason="stop",
        )

    async def stream(self, request):
        raise NotImplementedError


class _FailingCompactionClient:
    async def complete(self, request):
        raise RuntimeError("provider unavailable")

    async def stream(self, request):
        raise NotImplementedError


class _CancelledCompactionClient:
    async def complete(self, request):
        raise asyncio.CancelledError("compaction cancelled")

    async def stream(self, request):
        raise NotImplementedError


class _CharacterStreamingCompactionClient:
    summary = (
        "1. Current Goal\n- Continue.\n\n"
        "1. Nested detail that must remain plain text.\n\n"
        "2. User History, Instructions, And Decisions\n- Preserve constraints.\n\n"
        "3. Completed Work\n- Work is recorded.\n\n"
        "4. Key Decisions And Constraints\n- Keep evidence.\n\n"
        "5. Files, APIs, Commands, And Results\n- None.\n\n"
        "6. Open Issues Or Risks\n- None.\n\n"
        "7. Next Best Actions\n- Continue.\n\n"
        "8. Rejected Or Superseded Directions\n- None.\n\n"
        "9. Next Actions\n- Continue."
    )

    async def complete(self, request):
        raise AssertionError("streaming should complete the summary")

    async def stream(self, request):
        for character in self.summary:
            yield LLMStreamEvent(kind="content_delta", content=character)
        yield LLMStreamEvent(kind="done")


class _IncompleteStreamingCompactionClient:
    async def complete(self, request):
        raise AssertionError("an incomplete non-empty stream must not fall back or commit")

    async def stream(self, request):
        yield LLMStreamEvent(
            kind="content_delta",
            content="[Compacted Context]\n\nPartial summary `",
        )


class _LengthLimitedStreamingCompactionClient:
    async def complete(self, request):
        raise AssertionError("a length-limited stream must not fall back or commit")

    async def stream(self, request):
        yield LLMStreamEvent(kind="content_delta", content="partial")
        yield LLMStreamEvent(kind="finish", finish_reason="length")


class _LosesPriorUserInstructionsClient:
    async def complete(self, request):
        return LLMResponse(
            content=(
                "1. Current Objective And Done Criteria\n- Continue.\n\n"
                "2. Active User Instructions\n"
                "- No explicit user instructions.\n\n"
                "3. External Action Authorization\n"
                "- None confirmed.\n\n"
                "4. Confirmed Facts And Decisions\n- None.\n\n"
                "5. Current Execution State\n- Prior work was summarized.\n\n"
                "6. Verification Evidence\n- None.\n\n"
                "7. Open Issues, Risks, And Hypotheses\n- None.\n\n"
                "8. Rejected Or Superseded Directions\n- None.\n\n"
                "9. Next Actions\n- Continue."
            ),
            finish_reason="stop",
        )

    async def stream(self, request):
        raise NotImplementedError


def _estimate(messages: list[ChatMessage]) -> int:
    return estimate_message_tokens([message.to_dict() for message in messages])


def _with_compactable_steps(
    messages: list[ChatMessage],
    *,
    assistant_steps: int = 6,
    user_fillers: int = 0,
    append_steps: bool = False,
) -> list[ChatMessage]:
    """Add deterministic synthetic history for compaction pipeline tests."""
    source = list(messages)
    prefix_end = 0
    for index, message in enumerate(source):
        if message.role != "system" or message.metadata.get("key") == "context_compaction_summary":
            break
        prefix_end = index + 1
    body = source[prefix_end:]
    if user_fillers:
        latest_user = next(
            (index for index in range(len(body) - 1, -1, -1) if body[index].role == "user"),
            None,
        )
        if latest_user is not None:
            fillers = [
                ChatMessage(role="user", content=f"retention filler {index}")
                for index in range(user_fillers)
            ]
            body = [*body[:latest_user], *fillers, *body[latest_user:]]
    steps = [
        ChatMessage(role="assistant", content=f"retention step {index}")
        for index in range(max(0, assistant_steps))
    ]
    if append_steps:
        latest_user = next(
            (index for index in range(len(body) - 1, -1, -1) if body[index].role == "user"),
            None,
        )
        if latest_user is None:
            body = [*body, *steps]
        else:
            body = [*body[:latest_user], *steps, *body[latest_user:]]
        steps = []
    return [*source[:prefix_end], *steps, *body]


def _canonical_summary_text() -> str:
    return CompactionSummary(
        goals="- Finish the export task.",
        active_user_instructions="- Keep the public interface unchanged.",
        external_action_authorization="- Do not deploy without confirmation.",
        confirmed_facts_and_decisions="- The route is implemented.",
        current_execution_state="- Tests are running.",
        verification_evidence="- The unit suite is green.",
        open_issues_risks_and_hypotheses="- Recheck the integration test.",
        rejected_or_superseded_directions="- None.",
        next_actions="- Run the integration test.",
    ).render()


def test_summary_parser_accepts_expected_sections():
    parsed = parse_compaction_summary(_canonical_summary_text())

    assert parsed is not None
    assert parsed.goals == "- Finish the export task."
    assert parsed.next_actions == "- Run the integration test."


def test_summary_parser_rejects_wrong_title():
    text = _canonical_summary_text().replace(
        "2. Active User Instructions",
        "2. Wrong Title",
    )

    assert parse_compaction_summary(text) is None


def test_summary_parser_rejects_missing_section():
    text = _canonical_summary_text().replace(
        "6. Verification Evidence\n- The unit suite is green.\n\n",
        "",
    )

    assert parse_compaction_summary(text) is None


def test_summary_parser_rejects_reordered_sections():
    sections = _canonical_summary_text().split("\n\n")
    sections[1], sections[2] = sections[2], sections[1]

    assert parse_compaction_summary("\n\n".join(sections)) is None


def test_summary_render_round_trip():
    summary = CompactionSummary(
        goals="- Goal.",
        active_user_instructions="- Constraint.",
        external_action_authorization="- Permission.",
        confirmed_facts_and_decisions="- Fact.",
        current_execution_state="- State.",
        verification_evidence="- Evidence.",
        open_issues_risks_and_hypotheses="- Risk.",
        rejected_or_superseded_directions="- Rejected.",
        next_actions="- Next.",
    )

    assert parse_compaction_summary(summary.render()) == summary


def test_summary_parser_ignores_program_owned_recent_user_suffix():
    summary = _canonical_summary_text()
    with_recent_users = (
        f"{summary}\n\n## Recent user messages\n"
        "1. first instruction\n\n2. second instruction"
    )

    assert parse_compaction_summary(with_recent_users) == parse_compaction_summary(summary)


def test_compaction_options_reject_non_positive_target():
    with pytest.raises(ValueError, match="target_tokens"):
        CompactionOptions(target_tokens=0)


@pytest.mark.asyncio
async def test_context_compactor_auto_and_manual_share_the_same_pipeline():
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="old request " + ("x" * 6_000)),
            ChatMessage(role="assistant", content="old result " + ("y" * 6_000)),
            ChatMessage(role="user", content="latest request"),
        ]
    )
    budget = TokenBudget(context_window=12_000, trigger_tokens=1_200, target_tokens=1_200)

    auto_client = _CompactionClient()
    auto_result = await ContextCompactor(
        llm_client=auto_client,
        model="mock-model",
        estimate_tokens=_estimate,
    ).compact(
        messages,
        budget=budget,
        options=CompactionOptions(force=False),
    )
    manual_client = _CompactionClient()
    manual_result = await ContextCompactor(
        llm_client=manual_client,
        model="mock-model",
        estimate_tokens=_estimate,
    ).compact(
        messages,
        budget=budget,
        options=CompactionOptions(force=True, target_tokens=1_200),
    )

    assert auto_result is not None
    assert manual_result is not None
    assert auto_result.status == manual_result.status == "compacted"
    assert auto_result.compacted_count == manual_result.compacted_count
    assert auto_result.retained_count == manual_result.retained_count
    assert auto_result.after_tokens == manual_result.after_tokens
    assert auto_result.trigger == "auto"
    assert manual_result.trigger == "manual"
    assert auto_client.last_request is not None
    assert manual_client.last_request is not None
    assert auto_client.last_request.messages[-1].content == manual_client.last_request.messages[-1].content


@pytest.mark.asyncio
async def test_context_compactor_auto_waits_for_trigger_but_force_bypasses_it():
    messages = [
        ChatMessage(role="user", content="old request"),
        ChatMessage(role="assistant", content="old result"),
        ChatMessage(role="user", content="latest request"),
    ]
    budget = TokenBudget(context_window=8_000, trigger_tokens=8_000, target_tokens=1_200)
    client = _CompactionClient()
    compactor = ContextCompactor(
        llm_client=client,
        model="mock-model",
        estimate_tokens=_estimate,
    )

    assert await compactor.compact(
        messages,
        budget=budget,
        options=CompactionOptions(force=False),
    ) is None
    forced = await compactor.compact(
        messages,
        budget=budget,
        options=CompactionOptions(force=True),
    )

    assert forced is not None
    assert forced.trigger == "manual"


@pytest.mark.asyncio
async def test_context_controller_owns_trigger_and_reports_execution_metadata():
    def estimate_request(messages: list[ChatMessage], fast: bool) -> int:
        return estimate_message_tokens(
            [message.to_dict() for message in messages],
            fast=fast,
        )

    controller = ContextCompactionController(
        llm_client=_CompactionClient(),
        estimate_request_tokens=estimate_request,
    )
    budget = TokenBudget(context_window=12_000, trigger_tokens=1_200, target_tokens=1_200)

    execution = await controller.compact(
        _with_compactable_steps(
            [
                ChatMessage(role="user", content="old request " + ("x" * 6_000)),
                ChatMessage(role="assistant", content="old result " + ("y" * 6_000)),
                ChatMessage(role="user", content="latest request"),
            ]
        ),
        budget=budget,
        timeout=None,
        current_model="mock-model",
    )

    assert execution.result is not None
    assert execution.result.status == "compacted"
    assert execution.execution_model == "mock-model"
    assert execution.strategy == "current_model"
    assert execution.measurement.exact is True


@pytest.mark.asyncio
async def test_context_controller_skips_small_request_without_calling_pipeline():
    client = _CompactionClient()
    controller = ContextCompactionController(
        llm_client=client,
        estimate_request_tokens=lambda messages, fast: estimate_message_tokens(
            [message.to_dict() for message in messages],
            fast=fast,
        ),
    )

    execution = await controller.compact(
        [ChatMessage(role="user", content="small request")],
        budget=TokenBudget(context_window=8_000, trigger_tokens=8_000, target_tokens=1_200),
        timeout=None,
        current_model="mock-model",
    )

    assert execution.result is None
    assert execution.measurement.exact is False
    assert client.last_request is None


@pytest.mark.asyncio
async def test_context_controller_force_only_bypasses_trigger_threshold():
    client = _CompactionClient()
    controller = ContextCompactionController(
        llm_client=client,
        estimate_request_tokens=lambda messages, fast: estimate_message_tokens(
            [message.to_dict() for message in messages], fast=fast
        ),
    )
    budget = TokenBudget(context_window=8_000, trigger_tokens=7_000, target_tokens=1_200)
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="old request " + ("x" * 3_000)),
            ChatMessage(role="assistant", content="old result " + ("y" * 3_000)),
            ChatMessage(role="user", content="latest request"),
        ]
    )

    execution = await controller.compact(
        messages,
        budget=budget,
        timeout=None,
        current_model="mock-model",
        trigger="manual",
        force=True,
    )

    assert execution.result is not None
    assert execution.result.status == "compacted"
    assert execution.result.limit_tokens == budget.target_tokens
    assert execution.result.trigger == "manual"
    assert execution.strategy == "current_model"
    assert client.last_request is not None
    assert client.last_request.max_tokens == 400


@pytest.mark.asyncio
async def test_stream_not_implemented_falls_back_to_complete():
    result = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=_with_compactable_steps(
                [
                    ChatMessage(role="user", content="old request " + ("x" * 2_000)),
                    ChatMessage(role="assistant", content="old result " + ("y" * 2_000)),
                    ChatMessage(role="user", content="latest request"),
                ]
            ),
            llm_client=_CompactionClient(),
            model="mock-model",
            limit_tokens=1_200,
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "compacted"


@pytest.mark.asyncio
async def test_attribute_error_from_stream_is_not_swallowed():
    with pytest.raises(AttributeError, match="stream implementation bug"):
        await compact_context(
            ContextCompactionRequest(
                trigger="manual",
                messages=_with_compactable_steps(
                    [
                        ChatMessage(role="user", content="old request " + ("x" * 2_000)),
                        ChatMessage(role="assistant", content="old result " + ("y" * 2_000)),
                        ChatMessage(role="user", content="latest request"),
                    ]
                ),
                llm_client=_AttributeErrorStreamingCompactionClient(),
                model="mock-model",
                limit_tokens=1_200,
                estimate_tokens=_estimate,
            )
        )


@pytest.mark.asyncio
async def test_compact_context_auto_preserves_prefix_and_latest_user_message():
    llm = _CompactionClient()
    messages = _with_compactable_steps(
        [
            ChatMessage(role="system", content="stable system prefix"),
            ChatMessage(role="user", content="old user instruction"),
            ChatMessage(role="assistant", content="old assistant output"),
            ChatMessage(role="user", content="latest user request"),
        ],
        user_fillers=21,
        append_steps=True,
    )

    result = await compact_context(
        ContextCompactionRequest(
            trigger="auto",
            messages=messages,
            llm_client=llm,
            model="mock-model",
                limit_tokens=8_000,
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "compacted"
    assert result.trigger == "auto"
    assert result.compacted_count == len(messages) - 1
    assert result.retained_count == 0
    assert result.summary.startswith(llm.summary)
    assert "## Recent user messages" in result.summary
    assert result.replacement_messages[0].content == "stable system prefix"
    assert result.replacement_messages[1].metadata["key"] == "context_compaction_summary"
    assert result.replacement_messages[-1].content.endswith("20. latest user request")
    assert llm.last_request.messages[0] == messages[0]
    assert llm.last_request.messages[-1].role == "user"
    assert llm.last_request.messages[-1].metadata["key"] == "context_compaction_instruction"
    assert "old user instruction" in "\n".join(
        str(message.content) for message in llm.last_request.messages[:-1]
    )
    raw_replacement = "\n".join(
        str(message.content)
        for message in result.replacement_messages
        if message.metadata.get("key") != "context_compaction_summary"
    )
    assert "old user instruction" not in raw_replacement
    assert result.display_payload["type"] == "compaction"
    assert result.display_payload["trigger"] == "auto"
    assert result.display_payload["label"] == "上下文已压缩"


@pytest.mark.asyncio
async def test_compact_context_fails_without_model_summary_instead_of_using_local_fallback():
    messages = _with_compactable_steps(
        [
            ChatMessage(
                role="user",
                content=(
                    "Do not push, create a pull request, or deploy without my confirmation. "
                    "The export must keep the current filters. "
                    + ("important context " * 180)
                ),
            ),
            ChatMessage(
                role="assistant",
                content=(
                    "Implemented the export route. Typecheck passed, but the timezone test still fails. "
                    + ("verified work " * 180)
                ),
            ),
            ChatMessage(role="user", content="Fix the timezone test next."),
        ],
        user_fillers=21,
        append_steps=True,
    )

    result = await compact_context(
        ContextCompactionRequest(
            trigger="auto",
            messages=messages,
            limit_tokens=1200,
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "failed"
    assert result.replacement_messages == messages
    assert "model returned an empty summary" in result.display_payload["message"]


@pytest.mark.asyncio
async def test_model_compaction_requests_the_continuation_contract_from_the_adapter():
    llm = _CompactionClient()
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="Do not deploy. " + ("requirement " * 220)),
            ChatMessage(role="assistant", content="Implementation in progress. " + ("result " * 220)),
            ChatMessage(role="user", content="Continue with the failing test."),
        ]
    )

    await compact_context(
        ContextCompactionRequest(
            trigger="auto",
            messages=messages,
            llm_client=llm,
            model="mock-model",
            limit_tokens=1200,
            estimate_tokens=_estimate,
        )
    )

    assert llm.last_request.messages[-1].role == "user"
    assert llm.last_request.messages[-1].metadata["key"] == "context_compaction_instruction"
    prompt = str(llm.last_request.messages[-1].content)
    assert "Compact for continuation" in prompt
    assert "2. Active User Instructions" in prompt
    assert "3. External Action Authorization" in prompt
    assert "5. Current Execution State" in prompt
    assert "6. Verification Evidence" in prompt
    assert "8. Rejected Or Superseded Directions" in prompt
    assert "Never invent" in prompt
    assert "latest explicit user instruction" in prompt
    assert "hypoth" in prompt.lower()


@pytest.mark.asyncio
async def test_compact_context_manual_reuses_same_entry_and_retains_tail_messages():
    llm = _CompactionClient()
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="old user 0"),
            ChatMessage(role="assistant", content="old assistant 1"),
            ChatMessage(role="user", content="recent user 2"),
            ChatMessage(role="assistant", content="recent assistant 3"),
        ]
    )

    result = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=messages,
            llm_client=llm,
            model="mock-model",
            limit_tokens=4096,
            existing_summary=(
                "previous compacted summary\n\n"
                "## Recent user messages\n1. stale instruction"
            ),
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "compacted"
    assert result.trigger == "manual"
    assert result.compacted_count == len(messages)
    assert result.retained_count == 0
    assert len(result.replacement_messages) == 1
    # Recent-user originals roll forward from the metadata-backed prior
    # summary; a new compaction appends current entries and keeps one bounded
    # suffix instead of replacing the previous suffix wholesale.
    assert result.summary.endswith(
        "1. stale instruction\n\n2. old user 0\n\n3. recent user 2"
    )
    instruction = str(llm.last_request.messages[-1].content)
    assert "Existing compacted summary to preserve" in instruction
    assert "previous compacted summary" in instruction
    assert "stale instruction" not in instruction
    assert result.display_payload["type"] == "compaction"
    assert result.display_payload["trigger"] == "manual"
    assert result.display_payload["compacted_messages"] == len(messages)
    assert result.display_payload["retained_messages"] == 0


@pytest.mark.asyncio
async def test_repeated_compaction_rolls_recent_users_forward_with_a_bounded_twenty_entry_suffix():
    old_users = [f"old user {index}" for index in range(20)]
    old_messages: list[ChatMessage] = []
    for index, user in enumerate(old_users):
        old_messages.extend(
            [
                ChatMessage(role="user", content=user),
                ChatMessage(
                    role="assistant",
                    content=f"old assistant {index} " + ("y" * 500),
                ),
            ]
        )

    first = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=old_messages,
            llm_client=_CompactionClient(),
            model="mock-model",
            limit_tokens=4096,
            estimate_tokens=_estimate,
        )
    )

    assert first.status == "compacted"
    assert first.recent_user_messages == old_users
    assert first.summary_message is not None

    new_users = [f"new user {index}" for index in range(5)]
    new_messages: list[ChatMessage] = []
    for index, user in enumerate(new_users):
        new_messages.extend(
            [
                ChatMessage(role="user", content=user),
                ChatMessage(
                    role="assistant",
                    content=f"new assistant {index} " + ("z" * 500),
                ),
            ]
        )
    second = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=[first.summary_message, *new_messages],
            llm_client=_CompactionClient(),
            model="mock-model",
            limit_tokens=4096,
            estimate_tokens=_estimate,
        )
    )

    expected = [*old_users[5:], *new_users]
    assert second.status == "compacted"
    assert second.recent_user_messages == expected
    assert second.summary.endswith(
        "1. old user 5\n\n2. old user 6\n\n3. old user 7\n\n"
        "4. old user 8\n\n5. old user 9\n\n6. old user 10\n\n"
        "7. old user 11\n\n8. old user 12\n\n9. old user 13\n\n"
        "10. old user 14\n\n11. old user 15\n\n12. old user 16\n\n"
        "13. old user 17\n\n14. old user 18\n\n15. old user 19\n\n"
        "16. new user 0\n\n17. new user 1\n\n18. new user 2\n\n"
        "19. new user 3\n\n20. new user 4"
    )


@pytest.mark.asyncio
async def test_internal_late_context_is_not_promoted_to_recent_user_suffix():
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="earlier user"),
            ChatMessage(
                role="user",
                content="request-local late context must stay internal",
                metadata={"key": "request_local_late_context"},
            ),
            ChatMessage(role="assistant", content="assistant result " + ("x" * 2000)),
            ChatMessage(role="user", content="latest real request"),
        ]
    )

    result = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=messages,
            llm_client=_CompactionClient(),
            model="mock-model",
            limit_tokens=4096,
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "compacted"
    assert "request-local late context must stay internal" not in result.recent_user_messages
    assert result.recent_user_messages[-1] == "latest real request"
    assert result.summary.endswith("1. earlier user\n\n2. latest real request")


def test_typed_media_user_content_uses_a_safe_placeholder_without_leaking_payload_fields():
    media_content = [
        {
            "type": "input_image",
            "image_url": {
                "url": "data:image/png;base64,secret-pixels",
                "detail": "high",
            },
        },
        {
            "type": "image_url",
            "image_url": {"url": "https://example.invalid/image.png"},
        },
    ]

    assert recent_user_message_text(media_content) == NON_TEXT_USER_MESSAGE_PLACEHOLDER


@pytest.mark.asyncio
async def test_recursive_compaction_uses_model_output_without_post_processing():
    prior_summary = (
        "[Compacted Context]\n\n"
        "1. Current Objective And Done Criteria\n- Finish acceptance.\n\n"
        "2. Active User Instructions\n"
        "- Use Kimi-K2.6 without thinking.\n"
        "- Preserve user messages in the visible transcript.\n\n"
        "3. External Action Authorization\n"
        "- Do not commit, publish, or deploy without user confirmation.\n\n"
        "4. Confirmed Facts And Decisions\n- Keep one compaction interface.\n\n"
        "5. Current Execution State\n- " + ("verified work " * 200) + "\n\n"
        "6. Verification Evidence\n- core.db\n\n"
        "7. Open Issues, Risks, And Hypotheses\n- Recheck the GUI.\n\n"
        "8. Rejected Or Superseded Directions\n- None.\n\n"
        "9. Next Actions\n- Continue."
    )
    messages = [
        ChatMessage(
            role="system",
            content=prior_summary,
            metadata={"key": "context_compaction_summary", "kind": "history"},
        ),
        ChatMessage(role="user", content="Continue the acceptance run."),
    ]

    result = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=messages,
            llm_client=_LosesPriorUserInstructionsClient(),
            model="mock-model",
            limit_tokens=1200,
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "compacted"
    assert "Use Kimi-K2.6 without thinking." not in result.summary
    assert "Preserve user messages in the visible transcript." not in result.summary
    assert "Do not commit, publish, or deploy without user confirmation." not in result.summary
    assert "2. Active User Instructions" in result.summary
    assert "3. External Action Authorization" in result.summary
    assert "No explicit user instructions" in result.summary
    assert "None confirmed" in result.summary


def test_summary_budget_truncates_plain_text_without_parsing():
    summary = "Keep the public interface unchanged. " + ("detail " * 800)

    compressed = truncate_text_to_tokens(summary, 100)

    assert estimate_text_tokens(compressed) <= 100
    assert compressed.startswith("Keep the public interface unchanged.")


@pytest.mark.asyncio
async def test_compact_context_reports_not_needed_for_zero_or_one_message():
    llm = _CompactionClient()

    one_message = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=[ChatMessage(role="user", content="only message")],
            llm_client=llm,
            model="mock-model",
            limit_tokens=4096,
            estimate_tokens=_estimate,
        )
    )

    assert one_message.status == "not_needed"
    assert one_message.compacted_count == 0
    assert one_message.retained_count == 0
    assert len(one_message.replacement_messages) == 1
    assert one_message.replacement_messages[0].content == "only message"

    empty = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=[],
            llm_client=llm,
            model="mock-model",
            limit_tokens=4096,
            estimate_tokens=_estimate,
        )
    )

    assert empty.status == "not_needed"
    assert empty.compacted_count == 0
    assert empty.retained_count == 0
    assert empty.replacement_messages == []


@pytest.mark.asyncio
async def test_compact_context_keeps_original_history_when_summary_has_no_token_gain():
    messages = [
        ChatMessage(role="user", content="old short history"),
        ChatMessage(role="user", content="latest request"),
    ]

    result = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=messages,
            llm_client=_CompactionClient(),
            model="mock-model",
            limit_tokens=4096,
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "compacted"
    assert result.retained_messages == []
    assert result.summary.endswith("1. old short history\n\n2. latest request")


@pytest.mark.asyncio
async def test_compact_context_segments_oversized_history_within_model_input_limit():
    llm = _SegmentingCompactionClient()
    progress = []
    messages = [
        ChatMessage(role="user", content=f"constraint {index} " + ("x" * 1000))
        for index in range(32)
    ]

    result = await compact_context(
        ContextCompactionRequest(
            trigger="model_switch",
            messages=messages,
            llm_client=llm,
            model="smaller-model",
            limit_tokens=1200,
            input_limit_tokens=1200,
            preserve_latest_user=False,
            estimate_tokens=_estimate,
            on_event=progress.append,
        )
    )

    assert result.status == "compacted"
    assert result.segment_count > 1
    assert len(llm.requests) > 1
    assert all(_estimate(request.messages) <= 1200 for request in llm.requests)
    assert result.after_tokens < result.before_tokens
    assert result.after_tokens <= 1200
    assert any(event["phase"] == "segment" for event in progress)
    assert progress[-1]["status"] == "compacted"


@pytest.mark.asyncio
async def test_summary_budget_limits_segment_and_merge_requests():
    llm = _SegmentingCompactionClient()
    budget = SummaryTokenBudget(
        context_window=2_000,
        output_tokens=200,
        protocol_tokens=100,
        safety_margin_tokens=0,
    )
    messages = [
        ChatMessage(role="user", content=f"segment {index} " + ("x" * 300))
        for index in range(20)
    ]

    summary, segment_count = await summarize_context_messages(
        messages,
        llm_client=llm,
        model="mock-model",
        limit_tokens=1_200,
        input_limit_tokens=99_999,
        summary_budget=budget,
    )

    assert summary == llm.summary
    assert segment_count > 1
    assert len(llm.requests) > segment_count
    assert all(
        estimate_message_tokens([message.to_dict() for message in request.messages])
        <= budget.max_input_tokens
        for request in llm.requests
    )
    assert all(request.max_tokens == budget.output_tokens for request in llm.requests)


@pytest.mark.asyncio
async def test_compact_context_forwards_native_character_stream_events_without_losing_content():
    llm = _CharacterStreamingCompactionClient()
    progress = []
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="old request " + ("x" * 3000)),
            ChatMessage(role="assistant", content="old result " + ("y" * 3000)),
            ChatMessage(role="user", content="continue"),
        ],
        user_fillers=21,
        append_steps=True,
    )

    result = await compact_context(
        ContextCompactionRequest(
            trigger="auto",
            messages=messages,
            llm_client=llm,
            model="mock-model",
            limit_tokens=6_000,
            estimate_tokens=_estimate,
            on_event=progress.append,
            retained_steps=6,
        )
    )

    deltas = [event["delta"] for event in progress if event.get("delta")]
    assert result.status == "compacted"
    assert result.summary.startswith(llm.summary)
    assert "## Recent user messages" in result.summary
    assert "".join(deltas) == llm.summary
    assert deltas == list(llm.summary)


@pytest.mark.asyncio
async def test_compact_context_retains_recent_complete_turns_by_token_budget():
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="old request " + ("x" * 3000)),
            ChatMessage(role="assistant", content="old answer " + ("y" * 3000)),
            ChatMessage(role="user", content="recent request"),
            ChatMessage(role="assistant", content="recent answer"),
            ChatMessage(role="user", content="latest request"),
        ]
    )

    result = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=messages,
            llm_client=_CompactionClient(),
            model="mock-model",
            limit_tokens=1000,
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "compacted"
    assert result.retained_messages == []
    assert result.summary.endswith("1. recent request\n\n2. latest request")
    assert "old request " not in result.summary
    assert result.after_tokens <= 1000


@pytest.mark.asyncio
async def test_compact_context_returns_failed_without_replacing_history():
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="important constraint " + ("x" * 2000)),
            ChatMessage(role="assistant", content="work result " + ("y" * 2000)),
            ChatMessage(role="user", content="continue"),
        ]
    )
    progress = []

    result = await compact_context(
        ContextCompactionRequest(
            trigger="auto",
            messages=messages,
            llm_client=_FailingCompactionClient(),
            model="unavailable-model",
            limit_tokens=1000,
            estimate_tokens=_estimate,
            on_event=progress.append,
        )
    )

    assert result.status == "failed"
    assert result.replacement_messages == messages
    assert result.before_tokens == result.after_tokens
    assert result.display_payload["status"] == "failed"
    assert result.display_payload["label"] == "压缩未完成"
    assert progress[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_compact_context_returns_failed_when_replacement_cannot_fit_limit():
    messages = _with_compactable_steps(
        [
            ChatMessage(role="system", content="stable prefix"),
            ChatMessage(role="user", content="old context"),
            ChatMessage(role="assistant", content="old result"),
            ChatMessage(role="user", content="latest request"),
        ],
        assistant_steps=1,
    )
    progress = []

    result = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=messages,
            llm_client=_CompactionClient(),
            model="mock-model",
            limit_tokens=250,
            estimate_tokens=lambda values: len(values) * 100,
            estimate_exact_tokens=lambda values: len(values) * 100,
            on_event=progress.append,
            retained_steps=1,
        )
    )

    assert result.status == "compacted"
    assert result.after_tokens <= 250
    assert progress[-1]["status"] == "compacted"


@pytest.mark.asyncio
async def test_compact_context_emits_failed_then_propagates_cancellation_without_mutating_history():
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="important constraint " + ("x" * 2000)),
            ChatMessage(role="assistant", content="work result " + ("y" * 2000)),
            ChatMessage(role="user", content="continue"),
        ]
    )
    original = [message.to_dict() for message in messages]
    progress = []

    with pytest.raises(asyncio.CancelledError, match="compaction cancelled"):
        await compact_context(
            ContextCompactionRequest(
                trigger="auto",
                messages=messages,
                llm_client=_CancelledCompactionClient(),
                model="mock-model",
                limit_tokens=1000,
                estimate_tokens=_estimate,
                on_event=progress.append,
            )
        )

    assert [message.to_dict() for message in messages] == original
    assert progress[-1]["status"] == "failed"
    assert progress[-1]["reason"] == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "client",
    [_IncompleteStreamingCompactionClient(), _LengthLimitedStreamingCompactionClient()],
)
async def test_incomplete_stream_never_replaces_original_history(client):
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="important constraint " + ("x" * 6000)),
            ChatMessage(role="assistant", content="completed work " + ("y" * 6000)),
            ChatMessage(role="user", content="continue"),
        ]
    )
    original = [message.to_dict() for message in messages]
    progress = []

    result = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=messages,
            llm_client=client,
            model="mock-model",
            limit_tokens=3600,
            estimate_tokens=_estimate,
            on_event=progress.append,
        )
    )

    assert result.status == "failed"
    assert [message.to_dict() for message in result.replacement_messages] == original
    assert result.before_tokens == result.after_tokens
    assert progress[-1]["status"] == "failed"
    assert "Context compaction failed" in progress[-1]["message"]


class _UnstructuredCompactionClient:
    async def complete(self, request):
        return LLMResponse(
            content="Just some notes without the required nine-section structure at all.",
            finish_reason="stop",
        )

    async def stream(self, request):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_model_output_is_used_verbatim_without_parsing_or_fallback():
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="keep this requirement visible " + ("x" * 6000)),
            ChatMessage(role="assistant", content="implemented export route " + ("y" * 6000)),
            ChatMessage(role="user", content="continue"),
        ],
        user_fillers=21,
        append_steps=True,
    )

    result = await compact_context(
        ContextCompactionRequest(
            trigger="auto",
            messages=messages,
            llm_client=_UnstructuredCompactionClient(),
            model="mock-model",
            limit_tokens=6_000,
            estimate_tokens=_estimate,
            retained_steps=6,
        )
    )

    assert result.status == "compacted"
    assert result.summary.startswith(
        "Just some notes without the required nine-section structure at all."
    )
    assert "## Recent user messages" in result.summary
    assert result.summary_message is not None
    assert result.summary_message.content == result.summary


@pytest.mark.asyncio
async def test_auto_compaction_transcript_includes_prior_summary_and_excludes_retained_span():
    llm = _CompactionClient()
    prior_summary = (
        "[Compacted Context]\n\n"
        "1. Current Objective And Done Criteria\n- Finish acceptance.\n\n"
        "2. Active User Instructions\n- Use Kimi-K2.6 without thinking.\n\n"
        "3. External Action Authorization\n- Do not commit, publish, or deploy without user confirmation.\n\n"
        "4. Confirmed Facts And Decisions\n- Keep one compaction interface.\n\n"
        "5. Current Execution State\n- Prior work summarized.\n\n"
        "6. Verification Evidence\n- core.db\n\n"
        "7. Open Issues, Risks, And Hypotheses\n- Recheck the GUI.\n\n"
        "8. Rejected Or Superseded Directions\n- None.\n\n"
        "9. Next Actions\n- Continue."
    )
    messages = _with_compactable_steps(
        [
            ChatMessage(role="system", content="stable system prefix"),
            ChatMessage(
                role="system",
                content=prior_summary,
                metadata={"key": "context_compaction_summary", "kind": "history"},
            ),
            ChatMessage(role="user", content="old instruction to compress " + ("x" * 2000)),
            ChatMessage(role="assistant", content="old result to compress " + ("y" * 2000)),
            ChatMessage(role="user", content="recent user 2"),
            ChatMessage(role="assistant", content="recent assistant 3"),
            ChatMessage(role="user", content="latest request"),
        ],
        user_fillers=21,
    )

    result = await compact_context(
        ContextCompactionRequest(
            trigger="auto",
            messages=messages,
            llm_client=llm,
            model="mock-model",
            limit_tokens=8_000,
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "compacted"
    assert result.summary.startswith(llm.summary)
    assert "## Recent user messages" in result.summary
    source_context = "\n".join(
        str(message.content) for message in llm.last_request.messages[:-1]
    )
    # The prior summary and complete non-prefix history are fed to the model.
    assert llm.last_request.messages[0] == messages[0]
    assert llm.last_request.messages[-1].metadata["key"] == "context_compaction_instruction"
    assert "[Compacted Context]" in source_context
    assert "Use Kimi-K2.6 without thinking." in source_context
    assert "old instruction to compress" in source_context
    assert "retention filler 20" in source_context
    assert "recent assistant 3" in source_context
    assert "latest request" in source_context


def test_preserves_leading_system_prefix():
    prefix = [
        ChatMessage(role="system", content="stable policy"),
        ChatMessage(role="system", content="workspace policy"),
    ]
    messages = _with_compactable_steps(
        [
            *prefix,
            ChatMessage(role="user", content="old context " + ("x " * 1600)),
            ChatMessage(role="assistant", content="old result " + ("y " * 1600)),
            ChatMessage(role="user", content="latest request"),
        ]
    )

    layout = select_context_compaction_layout(
        messages,
        limit_tokens=1200,
        estimate_tokens=_estimate,
    )

    assert layout is not None
    assert layout.prefix_messages == prefix


def test_default_zero_steps_summarizes_latest_user_turn():
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="old context " + ("x " * 1600)),
            ChatMessage(role="assistant", content="old result " + ("y " * 1600)),
            ChatMessage(role="user", content="latest explicit request"),
        ]
    )

    layout = select_context_compaction_layout(
        messages,
        limit_tokens=1200,
        estimate_tokens=_estimate,
    )

    assert layout is not None
    assert layout.retained_messages == []
    assert layout.compacted_messages == messages


def test_positive_override_retains_only_recent_model_steps():
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="old context " + ("x " * 1600)),
            ChatMessage(role="assistant", content="old result " + ("y " * 1600)),
            ChatMessage(role="user", content="recent request"),
            ChatMessage(role="assistant", content="recent answer"),
            ChatMessage(role="user", content="latest request"),
        ]
    )

    layout = select_context_compaction_layout(
        messages,
        limit_tokens=100_000,
        retained_steps=2,
        estimate_tokens=_estimate,
    )

    assert layout is not None
    assert [message.content for message in layout.retained_messages] == [
        "old result " + ("y " * 1600),
        "recent answer",
    ]
    assert all(message.role != "user" for message in layout.retained_messages)


def test_tool_call_and_result_stay_together():
    tool_call = LLMToolCall(
        id="call-1",
        name="read_file",
        arguments={"path": "notes.txt"},
    )
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="old context " + ("x " * 1600)),
            ChatMessage(role="assistant", content="old result " + ("y " * 1600)),
            ChatMessage(role="user", content="read the notes"),
            ChatMessage(role="assistant", tool_calls=[tool_call]),
            ChatMessage(
                role="tool",
                tool_call_id="call-1",
                content="notes content",
            ),
        ],
        assistant_steps=1,
    )

    layout = select_context_compaction_layout(
        messages,
        limit_tokens=1200,
        retained_steps=1,
        estimate_tokens=_estimate,
    )

    assert layout is not None
    assert layout.retained_messages[-2].tool_calls == [tool_call]
    assert layout.retained_messages[-1].tool_call_id == "call-1"


@pytest.mark.asyncio
async def test_compaction_summary_does_not_enter_raw_history():
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="old requirement " + ("x " * 1600)),
            ChatMessage(role="assistant", content="old result " + ("y " * 1600)),
            ChatMessage(role="user", content="latest request"),
        ]
    )
    original = [message.to_dict() for message in messages]

    result = await compact_context(
        ContextCompactionRequest(
            trigger="auto",
            messages=messages,
            llm_client=_CompactionClient(),
            model="mock-model",
            limit_tokens=1200,
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "compacted"
    assert [message.to_dict() for message in messages] == original
    assert all(
        message.metadata.get("key") != "context_compaction_summary"
        for message in messages
    )


@pytest.mark.asyncio
async def test_resume_boundary_restores_recent_tail():
    messages = _with_compactable_steps(
        [
            ChatMessage(role="user", content="old request " + ("x " * 1600)),
            ChatMessage(role="assistant", content="old answer " + ("y " * 1600)),
            ChatMessage(role="user", content="recent request"),
            ChatMessage(role="assistant", content="recent answer"),
            ChatMessage(role="user", content="latest request"),
        ]
    )

    result = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=messages,
            llm_client=_CompactionClient(),
            model="mock-model",
            limit_tokens=1200,
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "compacted"
    assert result.retained_messages == []
    assert result.summary.endswith("3. latest request")
    assert len(result.replacement_messages) == 1


def test_fitter_finishes_within_max_attempts():
    calls = 0

    def never_shrinks(messages: list[ChatMessage]) -> int:
        nonlocal calls
        calls += 1
        return 10_000 if messages else 0

    fitter = CompactionFitter(never_shrinks)
    with pytest.raises(CompactionBudgetExceeded):
        fitter.fit(
            CompactionFitInput(
                system_prefix=[],
                summary_message=ChatMessage(role="system", content="summary"),
                recent_messages=[],
                target_tokens=100,
            )
        )

    assert calls >= MAX_FIT_ATTEMPTS


def test_fitter_never_returns_over_target():
    result = CompactionFitter(_estimate).fit(
        CompactionFitInput(
            system_prefix=[ChatMessage(role="system", content="stable prefix")],
            summary_message=ChatMessage(role="system", content="summary " + ("中" * 1_000)),
            recent_messages=[ChatMessage(role="user", content="latest request")],
            target_tokens=1_200,
        )
    )

    assert result.estimated_tokens <= 1_200
    assert _estimate(result.messages) == result.estimated_tokens
    assert result.attempts <= MAX_FIT_ATTEMPTS


def test_fitter_drops_oldest_recent_turn_first():
    result = CompactionFitter(_estimate).fit(
        CompactionFitInput(
            system_prefix=[],
            summary_message=ChatMessage(role="system", content="summary"),
            recent_messages=[
                ChatMessage(role="user", content="old request"),
                ChatMessage(role="assistant", content="old answer"),
                ChatMessage(role="user", content="recent request"),
                ChatMessage(role="assistant", content="recent answer"),
                ChatMessage(role="user", content="latest request"),
            ],
            target_tokens=1_000,
        )
    )

    assert [message.content for message in result.messages[-3:]] == [
        "recent request",
        "recent answer",
        "latest request",
    ]


def test_fitter_preserves_latest_user_turn():
    result = CompactionFitter(_estimate).fit(
        CompactionFitInput(
            system_prefix=[],
            summary_message=ChatMessage(role="system", content="summary" + ("x" * 200)),
            recent_messages=[ChatMessage(role="user", content="latest user instruction")],
            target_tokens=600,
        )
    )

    assert result.messages[-1].role == "user"
    assert result.messages[-1].content == "latest user instruction"


def test_fitter_raises_when_required_messages_exceed_budget():
    with pytest.raises(CompactionBudgetExceeded, match="required latest turn"):
        CompactionFitter(_estimate).fit(
            CompactionFitInput(
                system_prefix=[ChatMessage(role="system", content="stable prefix")],
                summary_message=ChatMessage(role="system", content="summary"),
                recent_messages=[ChatMessage(role="user", content="中" * 2_000)],
                target_tokens=1_000,
            )
        )


@pytest.mark.parametrize("summary", ["中" * 1_000, "🙂" * 500], ids=["cjk", "emoji"])
def test_fitter_handles_unicode_summary(summary: str):
    result = CompactionFitter(_estimate).fit(
        CompactionFitInput(
            system_prefix=[],
            summary_message=ChatMessage(role="system", content=summary),
            recent_messages=[ChatMessage(role="user", content="latest request")],
            target_tokens=1_400,
        )
    )

    assert result.estimated_tokens <= 1_400
    assert estimate_message_tokens([message.to_dict() for message in result.messages]) <= 1_400


@pytest.mark.parametrize(
    "text",
    [
        "a" * 10_000,
        "中" * 10_000,
        "🙂" * 3_000,
        "abc中文🙂" * 1_000,
    ],
    ids=["ascii", "cjk", "emoji", "mixed"],
)
def test_truncate_never_exceeds_token_limit(text: str):
    result = truncate_text_to_tokens(text, 100)

    assert estimate_text_tokens(result) <= 100
    assert len(result) < len(text)


def test_truncate_returns_original_text_when_already_within_budget():
    assert truncate_text_to_tokens("abc", 100) == "abc"


def test_truncate_returns_empty_text_for_zero_budget():
    assert truncate_text_to_tokens("abc", 0) == ""


def test_truncate_budget_includes_marker_when_marker_fits():
    result = truncate_text_to_tokens("a" * 10_000, 20)

    assert estimate_text_tokens(result) <= 20
    assert "compaction summary truncated to fit budget" in result


def test_truncate_omits_marker_when_marker_cannot_fit():
    result = truncate_text_to_tokens("a" * 10_000, 1)

    assert estimate_text_tokens(result) <= 1
