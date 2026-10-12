"""Backend step timing: millisecond stamps, dispatch gap, and time-to-first-event.

The backend log is the only durable trace of a run in an installed build, and
the step lines are read by subtracting adjacent timestamps.  These tests pin
the three properties that make that possible: a millisecond stamp on every
line, a per-step "gap since the previous result", and a per-step
time-to-first-stream-event.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from lamtools_core.kernel.loop import CoreLoopKernel
from lamtools_core.llm import LLMRequest, LLMStreamEvent
from lamtools_core.logging_setup import (
    attach_backend_file_logger,
    backend_log_formatter,
)
from lamtools_core.tool import ToolCall

from test_kernel import (
    MockKitStep,
    MockRuntimeKit,
    _make_kernel,
    _make_turn_input,
)

_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \[INFO\]")


class _StreamingOnlyLLM:
    """Streams one content delta and a done event; never uses the fallback."""

    def __init__(self) -> None:
        self.stream_calls = 0

    async def complete(self, request: LLMRequest):
        raise AssertionError("timing test must exercise the streaming path")

    async def stream(self, request: LLMRequest):
        self.stream_calls += 1
        yield LLMStreamEvent(kind="content_delta", content="ok")
        yield LLMStreamEvent(kind="done", finish_reason="stop")


class _SlowToolKit(MockRuntimeKit):
    """One tool round that is slow on purpose, so the gap is measurable."""

    TOOL_SECONDS = 0.05

    async def execute_tool(self, state, call: ToolCall):
        await asyncio.sleep(self.TOOL_SECONDS)
        return await super().execute_tool(state, call)


class TestLogStamp:
    def test_formatter_carries_millisecond_timestamp(self):
        record = logging.LogRecord(
            name="lamtools_core.kernel.loop",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        line = backend_log_formatter().format(record)
        assert _STAMP.match(line), line
        assert line.endswith("hello")

    def test_attach_writes_stamped_lines_and_is_idempotent(self, tmp_path):
        path = attach_backend_file_logger(tmp_path)
        assert path is not None
        root = logging.getLogger()
        attached = [h for h in root.handlers if getattr(h, "baseFilename", "") == str(path)]
        try:
            assert len(attached) == 1
            # A second call for the same directory must not duplicate lines.
            assert attach_backend_file_logger(tmp_path) == path
            assert len([h for h in root.handlers if getattr(h, "baseFilename", "") == str(path)]) == 1

            logging.getLogger("lamtools_core.test.timing").setLevel(logging.INFO)
            logging.getLogger("lamtools_core.test.timing").info("timing probe")
            for handler in attached:
                handler.flush()
            body = path.read_text(encoding="utf-8")
            assert "timing probe" in body
            assert any(_STAMP.match(line) for line in body.splitlines()), body
        finally:
            for handler in attached:
                root.removeHandler(handler)
                handler.close()


class TestStepTimingLogs:
    @pytest.mark.asyncio
    async def test_two_steps_report_gap_and_ttft(self, caplog):
        """Step 1 runs a slow tool; step 2 must report that time as its gap.

        A gap line that is always zero, or missing on the first step, would
        make the log useless for telling provider wait from local work — so the
        test drives a deliberately slow tool round and checks the measured gap
        covers it.
        """
        llm = _StreamingOnlyLLM()
        kit = _SlowToolKit(
            steps=[
                MockKitStep(
                    reply="working",
                    tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "a"})],
                    decision="continue",
                ),
                MockKitStep(reply="done", decision="done"),
            ]
        )
        kernel: CoreLoopKernel = _make_kernel(kit, llm_client=llm)

        with caplog.at_level(logging.INFO, logger="lamtools_core.kernel.loop"):
            result = await kernel.run(_make_turn_input())

        text = "\n".join(record.getMessage() for record in caplog.records)
        assert result.decision == "done"
        assert llm.stream_calls == 2
        assert text.count("dispatching model request") == 2
        assert text.count("first stream event") == 2

        gaps = [float(value) for value in re.findall(r"gap_since_last_result=([\d.]+)s", text)]
        assert len(gaps) == 2
        assert gaps[0] == 0.0, "the run's first request has no predecessor"
        assert gaps[1] >= _SlowToolKit.TOOL_SECONDS, gaps

        ttfts = [float(value) for value in re.findall(r"ttft=([\d.]+)s", text)]
        assert len(ttfts) == 2 and all(value >= 0.0 for value in ttfts)
