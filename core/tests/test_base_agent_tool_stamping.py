"""The parent-side delegation tools must stamp tool calls with the current run.

Without the stamp, a `sub_agent_message` sent from a later turn reuses the
record's stale source run id, and the child timeline is filed under a parent
item id that no transcript row owns (the "delegated message has no process
rows" bug).
"""

from __future__ import annotations

import pytest

from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
from lamtools_core.runtime import RuntimeState
from lamtools_core.tool import ToolCall, ToolResult


class RecordingToolbox:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    def model_tools(self, active_mode=None):  # noqa: ANN001, ANN202
        return []

    async def execute(self, call: ToolCall, context) -> ToolResult:  # noqa: ANN001
        self.calls.append(call)
        return ToolResult(call_id=call.id, name=call.name, status="ok", content="ok")


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["sub_agent", "sub_agent_message"])
async def test_delegation_tools_stamp_current_run(tmp_path, tool_name: str) -> None:
    toolbox = RecordingToolbox()
    kit = CoreBaseAgentKit(
        work_root=tmp_path,
        config=CoreBaseAgentConfig(model_id="fake-model", approval_policy="auto_approve"),
        toolbox=toolbox,  # type: ignore[arg-type]
    )
    state = RuntimeState(
        session_id="thread-1",
        run_id="thread-1:turn:current",
        metadata={"turn_id": "thread-1:turn:current"},
    )
    call = ToolCall(id="call-1", name=tool_name, arguments={})

    await kit.execute_tool(state, call)

    stamped = toolbox.calls[0]
    assert stamped.metadata["parent_run_id"] == "thread-1:turn:current"
    assert stamped.metadata["parent_turn_id"] == "thread-1:turn:current"
