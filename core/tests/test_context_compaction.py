from __future__ import annotations

import asyncio

import pytest

from lamtools_core.context_compaction import (
    COMPACTION_PREFIX,
    ContextCompactionRequest,
    compact_context,
)
from lamtools_core.llm import ChatMessage, LLMResponse, LLMStreamEvent
from lamtools_core.tokens import estimate_message_tokens


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
                "- Continue from the latest raw user message."
            ),
            finish_reason="stop",
        )

    async def stream(self, request):
        raise NotImplementedError


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
                "7. Next Best Actions\n- Continue."
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
        "7. Next Best Actions\n- Continue."
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
                "1. Current Goal\n- Continue.\n\n"
                "2. User History, Instructions, And Decisions\n"
                "- No explicit user instructions.\n\n"
                "3. Completed Work\n- Prior work was summarized.\n\n"
                "4. Key Decisions And Constraints\n- None.\n\n"
                "5. Files, APIs, Commands, And Results\n- None.\n\n"
                "6. Open Issues Or Risks\n- None.\n\n"
                "7. Next Best Actions\n- Continue."
            ),
            finish_reason="stop",
        )

    async def stream(self, request):
        raise NotImplementedError


def _estimate(messages: list[ChatMessage]) -> int:
    return estimate_message_tokens([message.to_dict() for message in messages])


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
        "1. Current Goal\n- Finish acceptance.\n\n"
        "2. User History, Instructions, And Decisions\n"
        "- Do not commit or publish.\n"
        "- Use Kimi-K2.6 without thinking.\n"
        "- Preserve user messages in the visible transcript.\n\n"
        "3. Completed Work\n- " + ("verified work " * 200) + "\n\n"
        "4. Key Decisions And Constraints\n- Keep one compaction interface.\n\n"
        "5. Files, APIs, Commands, And Results\n- core.db\n\n"
        "6. Open Issues Or Risks\n- Recheck the GUI.\n\n"
        "7. Next Best Actions\n- Continue."
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
    assert "Do not commit or publish." in result.summary
    assert "Use Kimi-K2.6 without thinking." in result.summary
    assert "Preserve user messages in the visible transcript." in result.summary
    assert "No explicit user instructions" not in result.summary


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
            input_limit_tokens=1000,
            preserve_latest_user=False,
            estimate_tokens=_estimate,
            on_event=progress.append,
        )
    )

    assert result.status == "compacted"
    assert result.segment_count > 1
    assert len(llm.requests) > 1
    assert all(_estimate(request.messages) <= 1000 for request in llm.requests)
    assert result.after_tokens < result.before_tokens
    assert result.after_tokens <= 1200
    assert any(event["phase"] == "segment" for event in progress)
    assert progress[-1]["status"] == "compacted"


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
