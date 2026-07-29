from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from lamtools_core.event import CollectingEventSink
from lamtools_core.kernel.loop import CoreLoopKernel
from lamtools_core.kernel.policy import LoopPolicy
from lamtools_core.plugins import HookDecision, HookEvent
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState, RuntimeTurnInput
from lamtools_core.tool import ToolCall, ToolResult

from core.tests.test_kernel import MockKitStep, MockLLMClient, MockRuntimeKit


# ── Fake hook engines for kernel-level tests ──────────────────


@dataclass
class BlockingHookEngine:
    """PreToolUse: block run_command. Neutral for all other events."""
    async def run(self, event: HookEvent) -> HookDecision:
        if event.event_name != "PreToolUse":
            return HookDecision()
        assert event.tool_name == "run_command"
        return HookDecision(decision="block", reason="blocked by hook")


@dataclass
class RewritingHookEngine:
    """PreToolUse: rewrite command argument."""
    async def run(self, event: HookEvent) -> HookDecision:
        return HookDecision(updated_input={"command": "py -3.14 -m pytest"})


@dataclass
class PostToolUseHookEngine:
    """PostToolUse: modify tool result content."""
    async def run(self, event: HookEvent) -> HookDecision:
        if event.event_name == "PostToolUse" and event.tool_name == "run_command":
            return HookDecision(updated_output={"content": "sanitized: " + event.tool_result.get("content", "")})
        return HookDecision()


@dataclass
class PostToolUseFailureHookEngine:
    """PostToolUseFailure: replace error message."""
    async def run(self, event: HookEvent) -> HookDecision:
        if event.event_name == "PostToolUseFailure" and event.tool_name == "run_command":
            return HookDecision(updated_output={"error": "intercepted: " + event.error,
                                                "content": "recovered content"})
        return HookDecision()


@dataclass
class SessionLifecycleHookEngine:
    """Tracks SessionStart / Stop events."""
    def __init__(self):
        self.events: list[str] = []

    async def run(self, event: HookEvent) -> HookDecision:
        self.events.append(event.event_name)
        return HookDecision()


@dataclass
class PermissionAutoApproveHookEngine:
    """PermissionRequest: auto‑approve the tool."""
    async def run(self, event: HookEvent) -> HookDecision:
        if event.event_name == "PermissionRequest":
            return HookDecision(permission_decision="allow")
        return HookDecision()


@dataclass
class PermissionDenyHookEngine:
    """PermissionRequest: deny the tool."""
    async def run(self, event: HookEvent) -> HookDecision:
        if event.event_name == "PermissionRequest":
            return HookDecision(decision="block", reason="denied by policy")
        return HookDecision()


@dataclass
class UserPromptSubmitHookEngine:
    """UserPromptSubmit: record user message, optionally block."""
    def __init__(self, block_keyword: str = ""):
        self.received_messages: list[str] = []
        self.block_keyword = block_keyword

    async def run(self, event: HookEvent) -> HookDecision:
        if event.event_name == "UserPromptSubmit":
            self.received_messages.append(event.user_message)
            if self.block_keyword and self.block_keyword in event.user_message:
                return HookDecision(decision="block", reason="blocked prompt keyword")
        return HookDecision()


@dataclass
class StatusMessageHookEngine:
    """Emit status messages."""
    async def run(self, event: HookEvent) -> HookDecision:
        return HookDecision(status_message="checking tool safety...")


# ── Tests ─────────────────────────────────────────────────────


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


@pytest.mark.asyncio
async def test_post_tool_use_hook_modifies_result():
    """PostToolUse hook sanitizes the tool result content."""
    seen_results = []

    class ToolKit(MockRuntimeKit):
        async def execute_tool(self, state: RuntimeState, call: ToolCall) -> ToolResult:
            return ToolResult(call_id=call.id, name=call.name, status="ok", content="raw output")

        async def format_tool_result_for_model(self, state: RuntimeState, call: ToolCall, result: ToolResult):
            seen_results.append(result.content)
            return await super().format_tool_result_for_model(state, call, result)

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
        hook_engine=PostToolUseHookEngine(),
    )

    await kernel.run(RuntimeTurnInput(user_message="run tests", metadata={"session_id": "s1"}))

    assert seen_results == ["sanitized: raw output"]


@pytest.mark.asyncio
async def test_post_tool_use_failure_hook_intercepts_error():
    """PostToolUseFailure hook overrides the error and content."""
    seen_results = []

    class ToolKit(MockRuntimeKit):
        async def execute_tool(self, state: RuntimeState, call: ToolCall) -> ToolResult:
            return ToolResult(
                call_id=call.id, name=call.name, status="failed",
                error="original error",
                metadata={"error_type": "ValueError"},
            )

        async def format_tool_result_for_model(self, state: RuntimeState, call: ToolCall, result: ToolResult):
            seen_results.append((result.status, result.error, result.content))
            return await super().format_tool_result_for_model(state, call, result)

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
        hook_engine=PostToolUseFailureHookEngine(),
    )

    await kernel.run(RuntimeTurnInput(user_message="run tests", metadata={"session_id": "s1"}))

    assert seen_results[0] == ("failed", "intercepted: original error", "recovered content")


@pytest.mark.asyncio
async def test_session_lifecycle_hooks_fire():
    """SessionStart fires at the beginning; Stop fires at the end."""
    engine = SessionLifecycleHookEngine()

    kit = MockRuntimeKit(steps=[
        MockKitStep(reply="hello", decision="done"),
    ])
    kernel = CoreLoopKernel(
        kit=kit,
        llm_client=MockLLMClient(),
        state_store=InMemoryRuntimeStateStore(),
        event_sink=CollectingEventSink(),
        policy=LoopPolicy(),
        hook_engine=engine,
    )

    await kernel.run(RuntimeTurnInput(user_message="hi", metadata={"session_id": "s1"}))

    assert engine.events[0] == "SessionStart"
    assert engine.events[1] == "UserPromptSubmit"
    assert engine.events[-1] == "Stop"
    assert len(engine.events) >= 3  # at least Start, PromptSubmit, Stop


@pytest.mark.asyncio
async def test_permission_request_hook_auto_approves():
    """PermissionRequest hook sets permission_decision='allow' so the tool runs without waiting."""
    pre_hook_requires_approval = True

    class ToolKit(MockRuntimeKit):
        async def execute_tool(self, state: RuntimeState, call: ToolCall) -> ToolResult:
            nonlocal pre_hook_requires_approval
            pre_hook_requires_approval = call.requires_approval
            return ToolResult(call_id=call.id, name=call.name, status="ok", content="ran auto approved")

    kit = ToolKit(steps=[
        MockKitStep(
            tool_calls=[ToolCall(id="call-1", name="run_command", arguments={"command": "ls"},
                                 requires_approval=True)],
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
        hook_engine=PermissionAutoApproveHookEngine(),
    )

    result = await kernel.run(RuntimeTurnInput(user_message="auto approve test", metadata={"session_id": "s1"}))
    # Should not have waited for approval
    assert result.decision == "done"
    assert not pre_hook_requires_approval


@pytest.mark.asyncio
async def test_permission_request_hook_denies():
    """PermissionRequest hook denies the tool; it should be blocked."""
    kit = MockRuntimeKit(steps=[
        MockKitStep(
            tool_calls=[ToolCall(id="call-1", name="run_command", arguments={"command": "rm -rf /"},
                                 requires_approval=True)],
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
        hook_engine=PermissionDenyHookEngine(),
    )

    result = await kernel.run(RuntimeTurnInput(user_message="deny test", metadata={"session_id": "s1"}))
    # Tool should be blocked
    first_step = result.steps[0]
    assert first_step.tool_steps[0].result.status == "blocked"
    assert "denied" in first_step.tool_steps[0].result.error.lower()


@pytest.mark.asyncio
async def test_user_prompt_submit_hook_receives_message():
    """UserPromptSubmit hook receives the user's message."""
    engine = UserPromptSubmitHookEngine()
    kit = MockRuntimeKit(steps=[
        MockKitStep(reply="got it", decision="done"),
    ])
    kernel = CoreLoopKernel(
        kit=kit,
        llm_client=MockLLMClient(),
        state_store=InMemoryRuntimeStateStore(),
        event_sink=CollectingEventSink(),
        policy=LoopPolicy(),
        hook_engine=engine,
    )

    await kernel.run(RuntimeTurnInput(user_message="hello world", metadata={"session_id": "s1"}))

    assert engine.received_messages == ["hello world"]


@pytest.mark.asyncio
async def test_status_message_emitted():
    """Status messages from hooks are emitted as runtime.hook_status events."""
    sink = CollectingEventSink()
    kit = MockRuntimeKit(steps=[
        MockKitStep(
            tool_calls=[ToolCall(id="call-1", name="run_command", arguments={"command": "ls"})],
            decision="continue",
        ),
        MockKitStep(reply="done", decision="done"),
    ])
    kernel = CoreLoopKernel(
        kit=kit,
        llm_client=MockLLMClient(),
        state_store=InMemoryRuntimeStateStore(),
        event_sink=sink,
        policy=LoopPolicy(),
        hook_engine=StatusMessageHookEngine(),
    )

    await kernel.run(RuntimeTurnInput(user_message="status test", metadata={"session_id": "s1"}))

    status_events = [e for e in sink.events if e.name == "runtime.hook_status" and e.payload.get("tool_name")]
    assert len(status_events) >= 1
    assert status_events[0].payload["tool_name"] == "run_command"
    assert status_events[0].payload["message"] == "checking tool safety..."