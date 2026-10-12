"""The context metric must report the provider's own count, not only the estimate.

The anchored-prefix check that guards the compaction *trigger* is strict by
design: the system prompt shifts between steps, so on one live session only 9 of
115 measurements could reuse the anchor.  Gating the *reported* number on that
reuse left the panel showing the local estimate forever — and the estimate
undercounts the request badly (measured 75,969 estimated vs 119,365 reported for
one request).  Reporting and deciding are different jobs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from lamtools_core.kernel.loop import CoreLoopKernel
from lamtools_core.kernel.policy import LoopPolicy
from lamtools_core.llm import ChatMessage, LLMRequest, LLMStreamEvent, LLMUsage
from lamtools_core.tool import ToolCall

from test_kernel import MockKitStep, MockRuntimeKit, _make_kernel, _make_turn_input


class _UsageStreamingLLM:
    """Streams one answer that carries provider usage."""

    async def complete(self, request: LLMRequest):
        raise AssertionError("streaming path expected")

    async def stream(self, request: LLMRequest):
        yield LLMStreamEvent(kind="content_delta", content="ok")
        yield LLMStreamEvent(
            kind="done",
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=1234, completion_tokens=7, total_tokens=1241),
        )


class _ChangingPromptKit(MockRuntimeKit):
    """Rebuilds a different request each step, so a stored anchor never matches."""

    async def build_model_request(self, state, context):
        return LLMRequest(
            messages=[ChatMessage(role="user", content=f"step-{state.turn_count}")],
            model="mock-model",
        )


@pytest.mark.asyncio
async def test_provider_count_is_reported_even_when_the_anchor_is_stale():
    kit = _ChangingPromptKit(
        steps=[
            MockKitStep(
                reply="working",
                tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "a"})],
                decision="continue",
            ),
            MockKitStep(reply="done", decision="done"),
        ]
    )
    kernel: CoreLoopKernel = _make_kernel(
        kit,
        llm_client=_UsageStreamingLLM(),
        policy=LoopPolicy(context_window_tokens=100_000),
    )

    result = await kernel.run(_make_turn_input())

    metrics = (result.state.metadata or {}).get("runtime_context_metrics") or {}
    # The anchor is stale (the prompt changed), so the trigger fell back to the
    # estimate and used the provider count as its floor.  The panel gets the
    # provider's number either way.
    assert metrics.get("context_measurement_source") == "provider_count_floor"
    assert metrics.get("context_usage_prompt_tokens") == 1234


@pytest.mark.asyncio
async def test_provider_count_is_recorded_as_soon_as_a_response_reports_usage():
    """A single-step run has no anchor yet; the reported count must still land.

    The panel shows the provider number for the request it last measured, so the
    value has to be recorded when the response arrives, not only when a later
    step happens to reuse the anchor.
    """
    kit = MockRuntimeKit(steps=[MockKitStep(reply="done", decision="done")])
    kernel: CoreLoopKernel = _make_kernel(
        kit,
        llm_client=_UsageStreamingLLM(),
        policy=LoopPolicy(context_window_tokens=100_000),
    )

    result = await kernel.run(_make_turn_input())

    metrics = (result.state.metadata or {}).get("runtime_context_metrics") or {}
    assert metrics.get("context_usage_prompt_tokens") == 1234


_SUMMARY = (
    "[Compacted Context]\n\n"
    "## 1. Current Objective And Done Criteria\n- Continue.\n\n"
    "## 2. Active User Instructions\n- Preserve earlier user constraints.\n\n"
    "## 3. External Action Authorization\n- None.\n\n"
    "## 4. Confirmed Facts And Decisions\n- Old context was summarized.\n\n"
    "## 5. Current Execution State\n- Work so far is recorded here.\n\n"
    "## 6. Verification Evidence\n- None.\n\n"
    "## 7. Open Issues, Risks, And Hypotheses\n- None.\n\n"
    "## 8. Rejected Or Superseded Directions\n- None.\n\n"
    "## 9. Next Actions\n- Continue the task."
)


class _ProviderCountLLM:
    """Answers normal turns and compaction requests over streaming."""

    async def complete(self, request: LLMRequest):
        raise AssertionError("streaming path expected")

    async def stream(self, request: LLMRequest):
        text = "\n".join(str(message.content) for message in request.messages)
        if "Compact for continuation" in text:
            yield LLMStreamEvent(kind="content_delta", content=_SUMMARY)
            yield LLMStreamEvent(kind="done", finish_reason="stop",
                                 usage=LLMUsage(prompt_tokens=900, completion_tokens=50))
            return
        yield LLMStreamEvent(kind="content_delta", content="ok")
        yield LLMStreamEvent(kind="done", finish_reason="stop",
                             usage=LLMUsage(prompt_tokens=1234, completion_tokens=7))


@pytest.mark.asyncio
async def test_compaction_triggers_on_the_provider_count_when_the_estimate_is_low():
    """The estimate read ~50 tokens where the provider had reported 1234.

    With the trigger keyed on the estimate alone, compaction waited until the
    real context had already crossed the provider's limit (measured 503s on a
    live session).  The provider count must be able to fire it.
    """
    from lamtools_core.event import CollectingEventSink

    sink = CollectingEventSink()
    kit = _ChangingPromptKit(
        steps=[
            MockKitStep(
                reply="working",
                tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "a"})],
                decision="continue",
            ),
            MockKitStep(reply="done", decision="done"),
        ]
    )
    kernel: CoreLoopKernel = _make_kernel(
        kit,
        llm_client=_ProviderCountLLM(),
        event_sink=sink,
        policy=LoopPolicy(context_window_tokens=100_000, compact_trigger_tokens=500),
    )

    result = await kernel.run(_make_turn_input())

    metric_events = [
        event for event in sink.events
        if event.name == "runtime.metrics"
        and (event.payload.get("runtime_metrics") or {}).get("context_measurement_source")
        == "provider_count_floor"
    ]
    assert metric_events, "the provider count never drove the trigger"
    compaction_started = any(
        event.name == "runtime.part" and (event.payload or {}).get("part_type") == "compaction"
        for event in sink.events
    )
    assert compaction_started, [e.name for e in sink.events][:20]
    assert result.decision in {"done", "failed"}
