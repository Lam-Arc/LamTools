from __future__ import annotations

import pytest

from lamtools_core.event import CollectingEventSink, CoreEvent
from lamtools_core.sub_agent import SubAgentEventForwardingSink


def _sink(
    collected: CollectingEventSink,
    provider=None,
) -> SubAgentEventForwardingSink:
    return SubAgentEventForwardingSink(
        parent_sink=collected,
        parent_session_id="parent",
        agent="worker",
        task="initial work",
        parent_call_id="call-start",
        parent_run_id="run-1",
        parent_turn_id="turn-1",
        type="execute",
        model_id="test-model",
        reasoning_level="max",
        parent_source_provider=provider,
    )


def _done() -> CoreEvent:
    return CoreEvent(
        name="runtime.done",
        category="message",
        payload={"content": "done"},
        session_id="parent:sub:worker",
        run_id="child-run",
    )


@pytest.mark.asyncio
async def test_child_events_follow_the_call_that_delivered_the_guidance():
    """Child rows must nest under the supplement that actually caused them.

    user:“修”+(补充消息被消化后，子代理后续事件的归属切到这条补充的调用行，
    面板才能做到“指令在前、紧接着是它触发的过程”)。
    """
    collected = CollectingEventSink()
    source = {"call_id": "call-start", "run_id": "run-1", "turn_id": "turn-1"}
    sink = _sink(
        collected,
        provider=lambda: (source["call_id"], source["run_id"], source["turn_id"]),
    )

    await sink.emit(_done())
    assert collected.events[-1].payload["sub_agent"]["parent_call_id"] == "call-start"
    assert collected.events[-1].payload["sub_agent"]["parent_turn_id"] == "turn-1"
    assert collected.events[-1].turn_id == "turn-1"

    # The kernel drained a supplement at the next step boundary.
    source.update({"call_id": "call-steer", "run_id": "run-1", "turn_id": "turn-2"})

    await sink.emit(_done())
    assert collected.events[-1].payload["sub_agent"]["parent_call_id"] == "call-steer"
    assert collected.events[-1].payload["sub_agent"]["parent_turn_id"] == "turn-2"
    assert collected.events[-1].turn_id == "turn-2"


@pytest.mark.asyncio
async def test_child_events_keep_the_starting_call_without_a_provider():
    """One-shot delegations have no supervisor binding and must not lose theirs."""
    collected = CollectingEventSink()
    sink = _sink(collected)

    await sink.emit(_done())

    assert collected.events[-1].payload["sub_agent"]["parent_call_id"] == "call-start"
    assert collected.events[-1].turn_id == "turn-1"


@pytest.mark.asyncio
async def test_a_failing_provider_never_drops_the_child_event():
    """Attribution is bookkeeping; it must never swallow the child's event."""
    collected = CollectingEventSink()

    def provider():
        raise RuntimeError("registry unavailable")

    sink = _sink(collected, provider=provider)

    await sink.emit(_done())

    assert [event.name for event in collected.events] == ["runtime.done"]
    assert collected.events[-1].payload["sub_agent"]["parent_call_id"] == "call-start"
