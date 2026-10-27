"""Host-produced deliverables events and their forwarding to channels/UI."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lamtools_core.event import CoreEvent
from lamtools_core.kernel.loop import CoreLoopKernel
from lamtools_core.runtime import RuntimeState
from lamtools_core.sub_agent import SubAgentEventForwardingSink
from lamtools_core.tool import ToolArtifact, ToolCall, ToolResult
from lamtools_core.tool.sub_agent_runner import deliverables_payload


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[CoreEvent] = []

    async def emit(self, event: CoreEvent) -> None:
        self.events.append(event)


def test_deliverables_payload_normalizes_artifacts() -> None:
    payload = deliverables_payload(
        [ToolArtifact(kind="file", uri="C:/tmp/report.txt", metadata={"path": "C:/tmp/report.txt"})],
        tool_name="make_report",
        call_id="c1",
    )

    assert payload["tool_name"] == "make_report"
    assert payload["call_id"] == "c1"
    assert payload["files"][0]["uri"] == "C:/tmp/report.txt"


async def test_sub_agent_sink_forwards_deliverables() -> None:
    parent = RecordingSink()
    sink = SubAgentEventForwardingSink(
        parent_sink=parent,
        parent_session_id="parent",
        agent="child",
        task="make a report",
    )

    await sink.emit(
        CoreEvent(
            name="deliverables/presented",
            category="artifact",
            payload={"files": [{"kind": "file", "uri": "C:/tmp/report.txt"}]},
            session_id="child-session",
            run_id="run-1",
        )
    )

    assert len(parent.events) == 1
    event = parent.events[0]
    assert event.name == "deliverables/presented"
    assert event.payload["sub_agent"]["agent"] == "child"
    assert event.payload["files"][0]["uri"] == "C:/tmp/report.txt"


async def test_kernel_emits_deliverables_after_a_tool_with_artifacts() -> None:
    sink = RecordingSink()
    state = RuntimeState(session_id="session-1", run_id="run-1")
    result = ToolResult(
        call_id="call-1",
        name="make_report",
        status="ok",
        content="report ready",
        artifacts=[ToolArtifact(kind="file", uri="C:/tmp/report.txt")],
    )

    await CoreLoopKernel._emit_tool_finished(
        SimpleNamespace(event_sink=sink),
        state,
        ToolCall(id="call-1", name="make_report"),
        result,
    )

    names = [event.name for event in sink.events]
    assert "runtime.tool.finished" in names
    assert "deliverables/presented" in names
    delivered = next(event for event in sink.events if event.name == "deliverables/presented")
    assert delivered.payload["tool_name"] == "make_report"
    assert delivered.payload["files"][0]["uri"] == "C:/tmp/report.txt"
