from __future__ import annotations

from dataclasses import dataclass

import pytest

from lamtools_core.event import CollectingEventSink
from lamtools_core.kernel.loop import CoreLoopKernel
from lamtools_core.kernel.policy import LoopPolicy
from lamtools_core.plugins import HookDecision, HookEvent
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState, RuntimeTurnInput
from lamtools_core.tool import ToolCall, ToolResult

from core.tests.test_kernel import MockKitStep, MockLLMClient, MockRuntimeKit


@dataclass
class BlockingHookEngine:
    async def run(self, event: HookEvent) -> HookDecision:
        assert event.event_name == "PreToolUse"
        assert event.tool_name == "run_command"
        return HookDecision(decision="block", reason="blocked by hook")


@dataclass
class RewritingHookEngine:
    async def run(self, event: HookEvent) -> HookDecision:
        return HookDecision(updated_input={"command": "py -3.14 -m pytest"})


@pytest.mark.asyncio
async def test_pre_tool_use_hook_blocks_tool_execution():
    executor_calls = []

    class ToolKit(MockRuntimeKit):
        async def execute_tool(self, state: RuntimeState, call: ToolCall) -> ToolResult:
            executor_calls.append(call.name)
            return ToolResult(call_id=call.id, name=call.name, status="ok", content="ran")

    kit = ToolKit(steps=[
        MockKitStep(
            tool_calls=[ToolCall(id="call-1", name="run_command", arguments={"command": "pytest"})],
            decision="continue",
        ),
        MockKitStep(reply="done", decision="done"),
    ])
    kernel = CoreLoopKernel(
        kit=kit,
        llm_client=MockLLMClient(),
        state_store=InMemoryRuntimeStateStore(),
        event_sink=CollectingEventSink(),
        policy=LoopPolicy(),
        hook_engine=BlockingHookEngine(),
    )

    result = await kernel.run(RuntimeTurnInput(user_message="run tests", metadata={"session_id": "s1"}))

    assert executor_calls == []
    assert result.steps[0].tool_steps[0].result.status == "blocked"
    assert result.steps[0].tool_steps[0].result.error == "blocked by hook"


@pytest.mark.asyncio
async def test_pre_tool_use_hook_rewrites_tool_input_before_execution():
    seen_arguments = []

    class ToolKit(MockRuntimeKit):
        async def execute_tool(self, state: RuntimeState, call: ToolCall) -> ToolResult:
            seen_arguments.append(dict(call.arguments))
            return ToolResult(call_id=call.id, name=call.name, status="ok", content="ran")

    kit = ToolKit(steps=[
        MockKitStep(
            tool_calls=[ToolCall(id="call-1", name="run_command", arguments={"command": "pytest"})],
            decision="continue",
        ),
        MockKitStep(reply="done", decision="done"),
    ])
    kernel = CoreLoopKernel(
        kit=kit,
        llm_client=MockLLMClient(),
        state_store=InMemoryRuntimeStateStore(),
        event_sink=CollectingEventSink(),
        policy=LoopPolicy(),
        hook_engine=RewritingHookEngine(),
    )

    await kernel.run(RuntimeTurnInput(user_message="run tests", metadata={"session_id": "s1"}))

    assert seen_arguments == [{"command": "py -3.14 -m pytest"}]
