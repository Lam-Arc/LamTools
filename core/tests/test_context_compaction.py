from __future__ import annotations

import asyncio

import pytest

from lamtools_core.context_compaction import (
    COMPACTION_PREFIX,
    MAX_FIT_ATTEMPTS,
    CompactionBudgetExceeded,
    CompactionFitInput,
    CompactionFitter,
    CompactionSummary,
    ContextCompactionRequest,
    compact_context,
    compress_structured_compaction_summary,
    parse_compaction_summary,
    select_context_compaction_layout,
    summarize_context_messages,
    truncate_text_to_tokens,
)
from lamtools_core.context_compaction_budget import SummaryTokenBudget
from lamtools_core.llm import ChatMessage, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.tokens import estimate_message_tokens, estimate_text_tokens


class _CompactionClient:
    def __init__(self) -> None:
        self.last_request = None

    async def complete(self, request):
        self.last_request = request
        return LLMResponse(
            content=(
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
            ),
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
    def __init__(self) -> None:
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        return LLMResponse(
            content=(
                "1. Current Goal\n- Continue.\n\n"
                "2. User History, Instructions, And Decisions\n- Preserve constraints.\n\n"
                "3. Completed Work\n- Segment summarized.\n\n"
                "4. Key Decisions And Constraints\n- Keep evidence.\n\n"
                "5. Files, APIs, Commands, And Results\n- Recorded.\n\n"
                "6. Open Issues Or Risks\n- None.\n\n"
                "7. Next Best Actions\n- Continue.\n\n"
                "8. Rejected Or Superseded Directions\n- None.\n\n"
                "9. Next Actions\n- Continue."
            ),
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


@pytest.mark.asyncio
async def test_stream_not_implemented_falls_back_to_complete():
    result = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=[
                ChatMessage(role="user", content="old request " + ("x" * 2_000)),
                ChatMessage(role="assistant", content="old result " + ("y" * 2_000)),
                ChatMessage(role="user", content="latest request"),
            ],
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
                messages=[
                    ChatMessage(role="user", content="old request " + ("x" * 2_000)),
                    ChatMessage(role="assistant", content="old result " + ("y" * 2_000)),
                    ChatMessage(role="user", content="latest request"),
                ],
                llm_client=_AttributeErrorStreamingCompactionClient(),
                model="mock-model",
                limit_tokens=1_200,
                estimate_tokens=_estimate,
            )
        )


@pytest.mark.asyncio
async def test_compact_context_auto_preserves_prefix_and_latest_user_message():
    llm = _CompactionClient()
    messages = [
        ChatMessage(role="system", content="stable system prefix"),
        ChatMessage(role="user", content="old user instruction"),
        ChatMessage(role="assistant", content="old assistant output"),
        ChatMessage(role="user", content="latest user request"),
    ]

    result = await compact_context(
        ContextCompactionRequest(
            trigger="auto",
            messages=messages,
            llm_client=llm,
            model="mock-model",
            limit_tokens=4096,
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "compacted"
    assert result.trigger == "auto"
    assert result.compacted_count == 2
    assert result.retained_count == 1
    assert result.summary.startswith(COMPACTION_PREFIX)
    assert result.replacement_messages[0].content == "stable system prefix"
    assert result.replacement_messages[1].metadata["key"] == "context_compaction_summary"
    assert result.replacement_messages[-1].content == "latest user request"
    assert "old user instruction" in str(llm.last_request.messages[-1].content)
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
async def test_compact_context_fallback_produces_minimum_sufficient_continuation_state():
    messages = [
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
    ]

    result = await compact_context(
        ContextCompactionRequest(
            trigger="auto",
            messages=messages,
            limit_tokens=1200,
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "compacted"
    assert "1. Current Objective And Done Criteria" in result.summary
    assert "2. Active User Instructions" in result.summary
    assert "3. External Action Authorization" in result.summary
    assert "4. Confirmed Facts And Decisions" in result.summary
    assert "5. Current Execution State" in result.summary
    assert "6. Verification Evidence" in result.summary
    assert "7. Open Issues, Risks, And Hypotheses" in result.summary
    assert "8. Rejected Or Superseded Directions" in result.summary
    assert "9. Next Actions" in result.summary
    assert "Do not push, create a pull request, or deploy without my confirmation." in result.summary


@pytest.mark.asyncio
async def test_model_compaction_requests_the_continuation_contract_from_the_adapter():
    llm = _CompactionClient()
    messages = [
        ChatMessage(role="user", content="Do not deploy. " + ("requirement " * 220)),
        ChatMessage(role="assistant", content="Implementation in progress. " + ("result " * 220)),
        ChatMessage(role="user", content="Continue with the failing test."),
    ]

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

    prompt = str(llm.last_request.messages[0].content)
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
    messages = [
        ChatMessage(role="user", content="old user 0"),
        ChatMessage(role="assistant", content="old assistant 1"),
        ChatMessage(role="user", content="recent user 2"),
        ChatMessage(role="assistant", content="recent assistant 3"),
    ]

    result = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=messages,
            llm_client=llm,
            model="mock-model",
            limit_tokens=4096,
            existing_summary="previous compacted summary",
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "compacted"
    assert result.trigger == "manual"
    assert result.compacted_count == 2
    assert result.retained_count == 2
    assert [message.content for message in result.replacement_messages[-2:]] == [
        "recent user 2",
        "recent assistant 3",
    ]
    transcript = str(llm.last_request.messages[-1].content)
    assert "## Existing Compacted Summary" in transcript
    assert "previous compacted summary" in transcript
    assert result.display_payload["type"] == "compaction"
    assert result.display_payload["trigger"] == "manual"
    assert result.display_payload["compacted_messages"] == 2
    assert result.display_payload["retained_messages"] == 2


@pytest.mark.asyncio
async def test_recursive_compaction_does_not_erase_prior_user_instructions():
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
    assert "Use Kimi-K2.6 without thinking." in result.summary
    assert "Preserve user messages in the visible transcript." in result.summary
    assert "Do not commit, publish, or deploy without user confirmation." in result.summary
    assert "2. Active User Instructions" in result.summary
    assert "3. External Action Authorization" in result.summary
    assert "No explicit user instructions" not in result.summary
    assert "None confirmed" not in result.summary


def test_summary_budget_preserves_user_instructions_and_external_authorization_first():
    summary = (
        "[Compacted Context]\n\n"
        "1. Current Objective And Done Criteria\n- Finish the task.\n\n"
        "2. Active User Instructions\n- Keep the public interface unchanged.\n\n"
        "3. External Action Authorization\n- Do not commit, push, deploy, or create a PR.\n\n"
        "4. Confirmed Facts And Decisions\n- " + ("confirmed detail " * 80) + "\n\n"
        "5. Current Execution State\n- " + ("execution detail " * 80) + "\n\n"
        "6. Verification Evidence\n- " + ("verification detail " * 80) + "\n\n"
        "7. Open Issues, Risks, And Hypotheses\n- " + ("open issue " * 80) + "\n\n"
        "8. Rejected Or Superseded Directions\n- " + ("rejected detail " * 80) + "\n\n"
        "9. Next Actions\n- Continue."
    )

    compressed = compress_structured_compaction_summary(summary, 100)

    assert "Keep the public interface unchanged." in compressed
    assert "Do not commit, push, deploy, or create a PR." in compressed


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

    assert result.status == "not_needed"
    assert result.before_tokens == result.after_tokens
    assert result.replacement_messages == messages
    assert result.display_payload["status"] == "not_needed"
    assert result.display_payload["reason"] == "no_gain"
    assert result.display_payload["label"] == "无需压缩"


@pytest.mark.asyncio
async def test_compact_context_segments_oversized_history_within_model_input_limit():
    llm = _SegmentingCompactionClient()
    progress = []
    messages = [
        ChatMessage(role="user", content=f"constraint {index} " + ("x" * 1000))
        for index in range(12)
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

    assert summary.startswith(COMPACTION_PREFIX)
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
    messages = [
        ChatMessage(role="user", content="old request " + ("x" * 3000)),
        ChatMessage(role="assistant", content="old result " + ("y" * 3000)),
        ChatMessage(role="user", content="continue"),
    ]

    result = await compact_context(
        ContextCompactionRequest(
            trigger="auto",
            messages=messages,
            llm_client=llm,
            model="mock-model",
            limit_tokens=1200,
            estimate_tokens=_estimate,
            on_event=progress.append,
        )
    )

    deltas = [event["delta"] for event in progress if event.get("delta")]
    assert result.status == "compacted"
    assert "".join(deltas) == llm.summary
    assert deltas == list(llm.summary)


@pytest.mark.asyncio
async def test_compact_context_retains_recent_complete_turns_by_token_budget():
    messages = [
        ChatMessage(role="user", content="old request " + ("x" * 3000)),
        ChatMessage(role="assistant", content="old answer " + ("y" * 3000)),
        ChatMessage(role="user", content="recent request"),
        ChatMessage(role="assistant", content="recent answer"),
        ChatMessage(role="user", content="latest request"),
    ]

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
    assert [message.content for message in result.retained_messages] == [
        "recent request",
        "recent answer",
        "latest request",
    ]
    assert result.after_tokens <= 1000


@pytest.mark.asyncio
async def test_compact_context_returns_failed_without_replacing_history():
    messages = [
        ChatMessage(role="user", content="important constraint " + ("x" * 2000)),
        ChatMessage(role="assistant", content="work result " + ("y" * 2000)),
        ChatMessage(role="user", content="continue"),
    ]
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
    messages = [
        ChatMessage(role="system", content="stable prefix"),
        ChatMessage(role="user", content="old context"),
        ChatMessage(role="assistant", content="old result"),
        ChatMessage(role="user", content="latest request"),
    ]
    progress = []

    result = await compact_context(
        ContextCompactionRequest(
            trigger="manual",
            messages=messages,
            llm_client=_CompactionClient(),
            model="mock-model",
            limit_tokens=150,
            estimate_tokens=lambda values: len(values) * 100,
            on_event=progress.append,
        )
    )

    assert result.status == "failed"
    assert result.replacement_messages == messages
    assert result.before_tokens == result.after_tokens == 400
    assert result.display_payload["reason"] == "over_limit"
    assert progress[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_compact_context_emits_failed_then_propagates_cancellation_without_mutating_history():
    messages = [
        ChatMessage(role="user", content="important constraint " + ("x" * 2000)),
        ChatMessage(role="assistant", content="work result " + ("y" * 2000)),
        ChatMessage(role="user", content="continue"),
    ]
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


class _UnstructuredCompactionClient:
    async def complete(self, request):
        return LLMResponse(
            content="Just some notes without the required nine-section structure at all.",
            finish_reason="stop",
        )

    async def stream(self, request):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_model_output_without_nine_sections_falls_back_to_structured_summary():
    messages = [
        ChatMessage(role="user", content="keep this requirement visible " + ("x" * 6000)),
        ChatMessage(role="assistant", content="implemented export route " + ("y" * 6000)),
        ChatMessage(role="user", content="continue"),
    ]

    result = await compact_context(
        ContextCompactionRequest(
            trigger="auto",
            messages=messages,
            llm_client=_UnstructuredCompactionClient(),
            model="mock-model",
            limit_tokens=3600,
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "compacted"
    assert result.summary.startswith(COMPACTION_PREFIX)
    assert "Just some notes" not in result.summary
    for section in (
        "1. Current Objective And Done Criteria",
        "2. Active User Instructions",
        "3. External Action Authorization",
        "4. Confirmed Facts And Decisions",
        "5. Current Execution State",
        "6. Verification Evidence",
        "7. Open Issues, Risks, And Hypotheses",
        "8. Rejected Or Superseded Directions",
        "9. Next Actions",
    ):
        assert section in result.summary
    assert "keep this requirement visible" in result.summary


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
    messages = [
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
    ]

    result = await compact_context(
        ContextCompactionRequest(
            trigger="auto",
            messages=messages,
            llm_client=llm,
            model="mock-model",
            limit_tokens=2000,
            estimate_tokens=_estimate,
        )
    )

    assert result.status == "compacted"
    assert "Use Kimi-K2.6 without thinking." in result.summary
    transcript = str(llm.last_request.messages[-1].content)
    # The prior summary is part of the compacted span (a) and is fed to the
    # compaction model as a regular message; the retained span (c) is excluded.
    assert "[Compacted Context]" in transcript
    assert "Use Kimi-K2.6 without thinking." in transcript
    assert "old instruction to compress" in transcript
    assert "recent user 2" not in transcript
    assert "recent assistant 3" not in transcript
    assert "latest request" not in transcript


def test_preserves_leading_system_prefix():
    prefix = [
        ChatMessage(role="system", content="stable policy"),
        ChatMessage(role="system", content="workspace policy"),
    ]
    messages = [
        *prefix,
        ChatMessage(role="user", content="old context " + ("x " * 1600)),
        ChatMessage(role="assistant", content="old result " + ("y " * 1600)),
        ChatMessage(role="user", content="latest request"),
    ]

    layout = select_context_compaction_layout(
        messages,
        limit_tokens=1200,
        estimate_tokens=_estimate,
    )

    assert layout is not None
    assert layout.prefix_messages == prefix


def test_preserves_latest_user_turn():
    messages = [
        ChatMessage(role="user", content="old context " + ("x " * 1600)),
        ChatMessage(role="assistant", content="old result " + ("y " * 1600)),
        ChatMessage(role="user", content="latest explicit request"),
    ]

    layout = select_context_compaction_layout(
        messages,
        limit_tokens=1200,
        estimate_tokens=_estimate,
    )

    assert layout is not None
    assert layout.retained_messages[-1].content == "latest explicit request"


def test_preserves_recent_complete_turns():
    messages = [
        ChatMessage(role="user", content="old context " + ("x " * 1600)),
        ChatMessage(role="assistant", content="old result " + ("y " * 1600)),
        ChatMessage(role="user", content="recent request"),
        ChatMessage(role="assistant", content="recent answer"),
        ChatMessage(role="user", content="latest request"),
    ]

    layout = select_context_compaction_layout(
        messages,
        limit_tokens=1200,
        estimate_tokens=_estimate,
    )

    assert layout is not None
    assert [message.content for message in layout.retained_messages] == [
        "recent request",
        "recent answer",
        "latest request",
    ]


def test_tool_call_and_result_stay_together():
    tool_call = LLMToolCall(
        id="call-1",
        name="read_file",
        arguments={"path": "notes.txt"},
    )
    messages = [
        ChatMessage(role="user", content="old context " + ("x " * 1600)),
        ChatMessage(role="assistant", content="old result " + ("y " * 1600)),
        ChatMessage(role="user", content="read the notes"),
        ChatMessage(role="assistant", tool_calls=[tool_call]),
        ChatMessage(
            role="tool",
            tool_call_id="call-1",
            content="notes content",
        ),
    ]

    layout = select_context_compaction_layout(
        messages,
        limit_tokens=1200,
        estimate_tokens=_estimate,
    )

    assert layout is not None
    assert layout.retained_messages[-2].tool_calls == [tool_call]
    assert layout.retained_messages[-1].tool_call_id == "call-1"


@pytest.mark.asyncio
async def test_compaction_summary_does_not_enter_raw_history():
    messages = [
        ChatMessage(role="user", content="old requirement " + ("x " * 1600)),
        ChatMessage(role="assistant", content="old result " + ("y " * 1600)),
        ChatMessage(role="user", content="latest request"),
    ]
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
    messages = [
        ChatMessage(role="user", content="old request " + ("x " * 1600)),
        ChatMessage(role="assistant", content="old answer " + ("y " * 1600)),
        ChatMessage(role="user", content="recent request"),
        ChatMessage(role="assistant", content="recent answer"),
        ChatMessage(role="user", content="latest request"),
    ]

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
    assert [message.content for message in result.retained_messages] == [
        "recent request",
        "recent answer",
        "latest request",
    ]
    assert [message.content for message in result.replacement_messages[-3:]] == [
        "recent request",
        "recent answer",
        "latest request",
    ]


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
