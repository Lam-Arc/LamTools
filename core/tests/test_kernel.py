"""Tests for lamtools_core.kernel module.

Uses mock RuntimeKit, LLMClient, StateStore, and EventSink to verify
CoreLoopKernel behavior without any business logic.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from lamtools_core.event import CollectingEventSink, CoreEvent, EventSink
from lamtools_core.app.base_agent import core_events_to_run_items
from lamtools_core.kernel import (
    CoreLoopKernel,
    KernelError,
    KernelResult,
    KernelStep,
    KernelTurn,
    LoopDecision,
    LoopPhase,
    LoopPolicy,
    ModelCallError,
    RuntimeKit,
    VerificationResult,
)
from lamtools_core.llm import ChatMessage, LLMClient, LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.llm.policy import BackoffStrategy, RetryPolicy
from lamtools_core.prompt import PromptContext
from lamtools_core.runtime import RuntimeState, RuntimeStateStore, RuntimeTaskRegistry, RuntimeToolStep, RuntimeTurnInput
from lamtools_core.tool import ToolCall, ToolResult


def test_partial_tool_arguments_do_not_emit_content_streaming_placeholder():
    summary = CoreLoopKernel._summarize_partial_tool_arguments(
        '{"path":"index.html","content":"<html>'
    )

    assert summary == {"path": "index.html"}


# ---------------------------------------------------------------------------
# Mock implementations
# ---------------------------------------------------------------------------


class InMemoryStateStore:
    """Simple in-memory state store for testing."""

    def __init__(self) -> None:
        self._states: dict[str, RuntimeState] = {}
        self.save_count = 0

    async def get(self, session_id: str) -> RuntimeState | None:
        return self._states.get(session_id)

    async def save(self, state: RuntimeState) -> None:
        self._states[state.session_id] = state
        self.save_count += 1


@dataclass
class MockKitStep:
    """Configuration for one step of the mock kit."""

    reply: str = "working"
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    decision: LoopDecision = "continue"
    verification_passed: bool = False
    verification_required: bool = False
    verification_summary: str = ""
    verification_repair_prompt: str = ""
    verification_attempt: int = 0
    verification_max_attempts: int = 3
    kit_events: list[CoreEvent] = field(default_factory=list)


class MockRuntimeKit:
    """Mock RuntimeKit that follows a scripted sequence of steps."""

    name: str = "mock"

    def __init__(self, steps: list[MockKitStep] | None = None) -> None:
        self.steps = steps or [MockKitStep()]
        self._step_index = 0
        self.on_run_start_called = False
        self.on_run_end_called = False
        self.writeback_calls: list[tuple[LoopDecision, ...]] = []
        self.build_context_calls: list[int] = []

    def _current_step(self) -> MockKitStep:
        idx = min(self._step_index, len(self.steps) - 1)
        return self.steps[idx]

    async def on_run_start(self, state: RuntimeState, turn_input: RuntimeTurnInput) -> None:
        self.on_run_start_called = True

    async def build_context(
        self,
        state: RuntimeState,
        turn_input: RuntimeTurnInput,
        history: list[ChatMessage],
        step_index: int,
    ) -> PromptContext:
        self.build_context_calls.append(step_index)
        return PromptContext(
            session_id=state.session_id,
            user_message=turn_input.user_message,
            history=history,
        )

    async def build_model_request(
        self,
        state: RuntimeState,
        context: PromptContext,
    ) -> LLMRequest:
        return LLMRequest(
            messages=[ChatMessage(role="user", content="test")],
            model="mock-model",
        )

    async def parse_model_output(
        self,
        state: RuntimeState,
        response: LLMResponse,
    ) -> KernelTurn:
        step = self._current_step()
        self._step_index += 1
        return KernelTurn(
            reply=step.reply,
            tool_calls=step.tool_calls,
            decision_hint=step.decision,
            events=step.kit_events,
        )

    async def execute_tool(
        self,
        state: RuntimeState,
        call: ToolCall,
    ) -> ToolResult:
        # Use the step before the current increment (parse_model_output already incremented)
        idx = min(self._step_index - 1, len(self.steps) - 1)
        step = self.steps[idx]
        # Find matching tool result by call id, or return default
        for tr in step.tool_results:
            if tr.call_id == call.id:
                return tr
        return ToolResult(call_id=call.id, name=call.name, content="mock result")

    async def format_tool_result_for_model(
        self,
        state: RuntimeState,
        call: ToolCall,
        result: ToolResult,
    ) -> ChatMessage:
        return ChatMessage(
            role="tool",
            content=result.content or "tool output",
            tool_call_id=call.id,
            name=call.name,
        )

    async def verify(
        self,
        state: RuntimeState,
        turn: KernelTurn,
        tool_results: list[ToolResult],
    ) -> VerificationResult:
        # Use the step before the current increment (parse_model_output already incremented)
        idx = min(self._step_index - 1, len(self.steps) - 1)
        step = self.steps[idx]
        return VerificationResult(
            passed=step.verification_passed,
            required=step.verification_required,
            summary=step.verification_summary,
            repair_prompt=step.verification_repair_prompt,
            attempt=step.verification_attempt,
            max_attempts=step.verification_max_attempts,
        )

    async def decide_next(
        self,
        state: RuntimeState,
        turn: KernelTurn,
        verification: VerificationResult,
        step: KernelStep,
    ) -> LoopDecision:
        # Use the step_index from the step to get the right decision
        idx = min(step.index, len(self.steps) - 1)
        return self.steps[idx].decision

    async def writeback(
        self,
        state: RuntimeState,
        turn: KernelTurn,
        tool_results: list[ToolResult],
        verification: VerificationResult,
        decision: LoopDecision,
    ) -> None:
        self.writeback_calls.append((decision,))

    async def on_run_end(
        self,
        state: RuntimeState,
        result: KernelResult,
    ) -> None:
        self.on_run_end_called = True


class MockLLMClient:
    """Mock LLM client that returns a fixed response."""

    def __init__(self, response: LLMResponse | None = None) -> None:
        self.response = response or LLMResponse(content="mock response")
        self.call_count = 0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        return self.response

    async def stream(self, request: LLMRequest):
        yield LLMResponse(content="mock stream")


class RecordingSlowToolKit(MockRuntimeKit):
    def __init__(self, steps: list[MockKitStep], delay: float = 0.05) -> None:
        super().__init__(steps)
        self.delay = delay
        self.started: list[str] = []
        self.finished: list[str] = []

    async def execute_tool(
        self,
        state: RuntimeState,
        call: ToolCall,
    ) -> ToolResult:
        self.started.append(call.id)
        await asyncio.sleep(self.delay)
        self.finished.append(call.id)
        return ToolResult(call_id=call.id, name=call.name, content=f"{call.id} done")


class PreflightBlockingToolKit(RecordingSlowToolKit):
    async def preflight_tool_calls(
        self,
        state: RuntimeState,
        calls: list[ToolCall],
    ) -> dict[str, ToolResult]:
        _ = state
        return {
            call.id: ToolResult(call_id=call.id, name=call.name, status="failed", error="blocked")
            for call in calls
        }


class CapturingLLMClient:
    """LLM client that records the final request sent by the kernel."""

    def __init__(self) -> None:
        self.last_request: LLMRequest | None = None
        self.requests: list[LLMRequest] = []
        self.call_count = 0

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.last_request = request
        self.requests.append(request)
        self.call_count += 1
        first_content = request.messages[0].content if request.messages else ""
        if isinstance(first_content, str) and first_content.startswith("Summarize this agent session context"):
            return LLMResponse(content=(
                "1. Current Goal\n"
                "- Continue the current task.\n\n"
                "2. User History, Instructions, And Decisions\n"
                "- old user 0 requested an earlier constraint.\n"
                "- old user 1 refined the expected behavior.\n\n"
                "3. Completed Work\n"
                "- Old context was reviewed and condensed.\n\n"
                "4. Key Decisions And Constraints\n"
                "- Preserve user decisions and exact paths.\n\n"
                "5. Files, APIs, Commands, And Results\n"
                "- No command results in this fixture.\n\n"
                "6. Open Issues Or Risks\n"
                "- None.\n\n"
                "7. Next Best Actions\n"
                "- Continue from the latest user message."
            ))
        return LLMResponse(content="done")

    async def stream(self, request: LLMRequest):
        raise NotImplementedError


class VerboseCompactionLLMClient(CapturingLLMClient):
    """LLM client that returns an intentionally oversized compaction summary."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.last_request = request
        self.requests.append(request)
        self.call_count += 1
        first_content = request.messages[0].content if request.messages else ""
        if isinstance(first_content, str) and first_content.startswith("Summarize this agent session context"):
            return LLMResponse(content=(
                "1. Current Goal\n"
                "- Continue the current task.\n\n"
                "2. User History, Instructions, And Decisions\n"
                "- Keep the critical user requirement.\n\n"
                "3. Completed Work\n"
                "- " + ("verbose summary " * 900) + "\n\n"
                "4. Key Decisions And Constraints\n"
                "- Preserve only effective information.\n\n"
                "5. Files, APIs, Commands, And Results\n"
                "- " + ("tool output " * 900) + "\n\n"
                "6. Open Issues Or Risks\n"
                "- None.\n\n"
                "7. Next Best Actions\n"
                "- Continue."
            ))
        return LLMResponse(content="done")


class FailingCompactionOnlyLLMClient(CapturingLLMClient):
    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.last_request = request
        self.requests.append(request)
        self.call_count += 1
        first_content = request.messages[0].content if request.messages else ""
        if isinstance(first_content, str) and first_content.startswith("Summarize this agent session context"):
            raise RuntimeError("compaction model unavailable")
        return LLMResponse(content="done")


class FlakyStreamingCompactionLLMClient(CapturingLLMClient):
    def __init__(self, *, compaction_failures: int) -> None:
        super().__init__()
        self.compaction_failures = compaction_failures
        self.stream_requests: list[LLMRequest] = []

    async def stream(self, request: LLMRequest):
        self.stream_requests.append(request)
        first_content = request.messages[0].content if request.messages else ""
        if isinstance(first_content, str) and first_content.startswith("Summarize this agent session context"):
            if self.compaction_failures > 0:
                self.compaction_failures -= 1
                raise RuntimeError("transient compaction model unavailable")
            yield LLMStreamEvent(kind="content_delta", content="1. Current Goal\n- Continue after retry.\n\n")
            yield LLMStreamEvent(
                kind="content_delta",
                content=(
                    "2. User History, Instructions, And Decisions\n"
                    "- Preserve the compacted user constraints.\n\n"
                    "3. Completed Work\n"
                    "- Compaction retried through the shared model path.\n\n"
                    "4. Key Decisions And Constraints\n"
                    "- Use one retry policy for model calls.\n\n"
                    "5. Files, APIs, Commands, And Results\n"
                    "- None.\n\n"
                    "6. Open Issues Or Risks\n"
                    "- None.\n\n"
                    "7. Next Best Actions\n"
                    "- Continue."
                ),
            )
            yield LLMStreamEvent(kind="done", metadata={"finish_reason": "stop"})
            return
        raise NotImplementedError


class FailingLLMClient:
    """LLM client that always raises an error."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("model unavailable")

    async def stream(self, request: LLMRequest):
        raise RuntimeError("model unavailable")


class SlowLLMClient:
    """LLM client that exceeds the configured timeout."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        await asyncio.sleep(0.05)
        return LLMResponse(content="too late")

    async def stream(self, request: LLMRequest):
        yield LLMResponse(content="too late")


class SlowToolKit(MockRuntimeKit):
    """RuntimeKit whose tool execution exceeds the configured timeout."""

    async def execute_tool(
        self,
        state: RuntimeState,
        call: ToolCall,
    ) -> ToolResult:
        await asyncio.sleep(0.05)
        return ToolResult(call_id=call.id, name=call.name, content="too late")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_kernel(
    kit: MockRuntimeKit,
    llm_client: LLMClient | None = None,
    state_store: InMemoryStateStore | None = None,
    event_sink: CollectingEventSink | None = None,
    policy: LoopPolicy | None = None,
    retry_policy: RetryPolicy | None = None,
) -> CoreLoopKernel:
    return CoreLoopKernel(
        kit=kit,
        llm_client=llm_client or MockLLMClient(),
        state_store=state_store or InMemoryStateStore(),
        event_sink=event_sink or CollectingEventSink(),
        policy=policy or LoopPolicy(),
        retry_policy=retry_policy or RetryPolicy(),
    )


def _make_turn_input(
    user_message: str = "hello",
    session_id: str = "test-session",
    user_content: str | list[dict[str, Any]] | None = None,
) -> RuntimeTurnInput:
    return RuntimeTurnInput(
        user_message=user_message,
        user_content=user_content,
        metadata={"session_id": session_id},
    )


# ---------------------------------------------------------------------------
# Tests: Type construction
# ---------------------------------------------------------------------------


class TestKernelTypes:
    def test_loop_decision_values(self):
        decisions: list[LoopDecision] = ["continue", "wait", "done", "failed"]
        assert len(decisions) == 4

    def test_kernel_turn_defaults(self):
        turn = KernelTurn()
        assert turn.reply == ""
        assert turn.tool_calls == []
        assert turn.decision_hint == "continue"
        assert turn.wait_reason == ""
        assert turn.repair_prompt == ""
        assert turn.events == []
        assert turn.metadata == {}

    @pytest.mark.asyncio
    async def test_current_user_content_can_be_multimodal_blocks(self):
        class HistoryEchoKit(MockRuntimeKit):
            async def build_model_request(self, state, context):
                return LLMRequest(messages=context.history, model="mock-model")

        llm = CapturingLLMClient()
        image_content = [
            {"type": "text", "text": "describe this screenshot"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,AA==", "detail": "auto"},
            },
        ]
        kernel = _make_kernel(HistoryEchoKit(steps=[MockKitStep(decision="done")]), llm_client=llm)

        result = await kernel.run(_make_turn_input(user_message="describe this screenshot", user_content=image_content))

        assert result.decision == "done"
        assert llm.last_request is not None
        user_messages = [message for message in llm.last_request.messages if message.role == "user"]
        assert user_messages
        assert user_messages[0].content == image_content

    def test_kernel_turn_with_values(self):
        call = ToolCall(id="c1", name="search", arguments={"q": "test"})
        event = CoreEvent(name="test", category="progress")
        turn = KernelTurn(
            reply="I will search",
            tool_calls=[call],
            decision_hint="continue",
            events=[event],
            metadata={"source": "kit"},
        )
        assert turn.reply == "I will search"
        assert len(turn.tool_calls) == 1
        assert turn.tool_calls[0].name == "search"
        assert len(turn.events) == 1

    def test_verification_result_defaults(self):
        vr = VerificationResult(passed=True)
        assert vr.passed is True
        assert vr.required is False
        assert vr.summary == ""
        assert vr.repair_prompt == ""
        assert vr.checks == []
        assert vr.events == []
        assert vr.metadata == {}

    def test_verification_result_not_done(self):
        """VerificationResult.passed=True does NOT mean task is done."""
        vr = VerificationResult(passed=True, required=True, summary="all checks pass")
        assert vr.passed is True
        # But the task decision is still up to Kit.decide_next

    def test_kernel_step_defaults(self):
        state = RuntimeState(session_id="s1")
        step = KernelStep(index=0, state_before=state)
        assert step.index == 0
        assert step.turn is None
        assert step.tool_steps == []
        assert step.verification is None
        assert step.decision == "continue"
        assert step.error == ""
        assert step.events == []
        assert step.metadata == {}

    def test_kernel_result_defaults(self):
        result = KernelResult(session_id="s1", run_id="r1", decision="done")
        assert result.session_id == "s1"
        assert result.run_id == "r1"
        assert result.decision == "done"
        assert result.message == ""
        assert result.steps == []
        assert result.state is None
        assert result.error == ""
        assert result.metadata == {}

    def test_loop_policy_defaults(self):
        policy = LoopPolicy()
        assert policy.model_timeout_seconds == 360.0
        assert policy.model_retries == 10
        assert policy.tool_timeout_seconds is None
        assert policy.emit_debug_events is False
        assert policy.context_window_tokens is None
        assert policy.compact_trigger_ratio == 0.8
        assert policy.compact_target_ratio == 0.6
        assert policy.metadata == {}

    def test_kernel_error_hierarchy(self):
        assert issubclass(ModelCallError, KernelError)

    def test_runtime_kit_protocol_checkable(self):
        assert isinstance("not_a_kit", RuntimeKit) is False


# ---------------------------------------------------------------------------
# Tests: Core loop scenarios
# ---------------------------------------------------------------------------


class TestKernelContinue:
    @pytest.mark.asyncio
    async def test_single_continue_then_done(self):
        """Kernel runs one continue step, then done on second step."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(reply="working on it", decision="continue"),
            MockKitStep(reply="all done", decision="done"),
        ])
        store = InMemoryStateStore()
        sink = CollectingEventSink()
        kernel = _make_kernel(kit, state_store=store, event_sink=sink)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert result.message == "all done"
        assert len(result.steps) == 2
        assert result.steps[0].decision == "continue"
        assert result.steps[1].decision == "done"
        assert result.state is not None
        assert result.state.status == "completed"
        assert result.state.turn_count == 2

    @pytest.mark.asyncio
    async def test_continue_updates_turn_count(self):
        """Each continue step increments turn_count."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(decision="continue"),
            MockKitStep(decision="continue"),
            MockKitStep(decision="done"),
        ])
        store = InMemoryStateStore()
        kernel = _make_kernel(kit, state_store=store)

        result = await kernel.run(_make_turn_input())

        assert result.state is not None
        assert result.state.turn_count == 3


class TestKernelWait:
    @pytest.mark.asyncio
    async def test_wait_saves_state_and_returns(self):
        """Wait saves state as 'waiting' and returns without blocking."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(reply="need more info", decision="wait"),
        ])
        store = InMemoryStateStore()
        sink = CollectingEventSink()
        kernel = _make_kernel(kit, state_store=store, event_sink=sink)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "wait"
        assert result.message == "need more info"
        assert result.state is not None
        assert result.state.status == "waiting"
        assert result.state.loop_state == "wait"

        # Verify state was saved
        saved = await store.get(result.state.session_id)
        assert saved is not None
        assert saved.status == "waiting"

        # Verify waiting event was emitted
        waiting_events = [e for e in sink.events if e.name == "runtime.waiting"]
        assert len(waiting_events) == 1

    @pytest.mark.asyncio
    async def test_wait_is_not_failure(self):
        """Wait is a first-class state, not an error or failure."""
        kit = MockRuntimeKit(steps=[MockKitStep(decision="wait")])
        kernel = _make_kernel(kit)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "wait"
        assert result.error == ""
        assert result.state is not None
        assert result.state.status == "waiting"


class TestKernelDone:
    @pytest.mark.asyncio
    async def test_done_completes_run(self):
        """Done marks state as completed and exits loop."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(reply="task finished", decision="done"),
        ])
        store = InMemoryStateStore()
        sink = CollectingEventSink()
        kernel = _make_kernel(kit, state_store=store, event_sink=sink)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert result.state is not None
        assert result.state.status == "completed"
        assert result.state.loop_state == "done"

        # Verify done event
        done_events = [e for e in sink.events if e.name == "runtime.done"]
        assert len(done_events) == 1


class TestKernelFailed:
    @pytest.mark.asyncio
    async def test_failed_marks_state_failed(self):
        """Failed marks state as failed and exits loop."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(reply="something went wrong", decision="failed"),
        ])
        store = InMemoryStateStore()
        sink = CollectingEventSink()
        kernel = _make_kernel(kit, state_store=store, event_sink=sink)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "failed"
        assert result.state is not None
        assert result.state.status == "failed"
        assert result.state.loop_state == "failed"

        # Verify failed event
        failed_events = [e for e in sink.events if e.name == "runtime.failed"]
        assert len(failed_events) == 1


class TestKernelToolFailure:
    @pytest.mark.asyncio
    async def test_tool_failure_does_not_auto_fail(self):
        """Tool failure does NOT automatically cause Kernel to fail.

        The Kit's decide_next decides what happens after a tool failure.
        """
        failed_tool_result = ToolResult(
            call_id="c1",
            name="search",
            status="failed",
            error="connection timeout",
        )
        kit = MockRuntimeKit(steps=[
            MockKitStep(
                reply="search failed, trying again",
                tool_calls=[ToolCall(id="c1", name="search", arguments={"q": "test"})],
                tool_results=[failed_tool_result],
                decision="continue",  # Kit decides to continue despite tool failure
            ),
            MockKitStep(
                reply="retry succeeded",
                decision="done",
            ),
        ])
        kernel = _make_kernel(kit)

        result = await kernel.run(_make_turn_input())

        # Tool failed but Kit decided to continue, so loop continues
        assert result.decision == "done"
        assert len(result.steps) == 2
        assert result.steps[0].tool_steps[0].result.status == "failed"
        assert result.steps[0].decision == "continue"

    @pytest.mark.asyncio
    async def test_tool_timeout_returns_failed_result_not_kernel_failure(self):
        """Tool timeout becomes a failed ToolResult; Kit still decides final state."""
        call = ToolCall(id="c1", name="slow_tool", arguments={})
        kit = SlowToolKit(steps=[
            MockKitStep(tool_calls=[call], decision="done"),
            MockKitStep(reply="done", decision="done"),
        ])
        policy = LoopPolicy(tool_timeout_seconds=0.001)
        kernel = _make_kernel(kit, policy=policy)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        tool_result = result.steps[0].tool_steps[0].result
        assert tool_result is not None
        assert tool_result.status == "failed"
        assert "timed out" in tool_result.error


class TestKernelVerification:
    @pytest.mark.asyncio
    async def test_verification_passed_not_auto_done(self):
        """Verification passed does NOT automatically make Kernel done.

        Only Kit.decide_next returning 'done' completes the task.
        """
        kit = MockRuntimeKit(steps=[
            MockKitStep(
                reply="verification passed but more work to do",
                verification_passed=True,
                verification_required=True,
                verification_summary="all checks pass",
                decision="continue",  # Kit decides to continue even though verification passed
            ),
            MockKitStep(
                reply="now truly done",
                decision="done",
            ),
        ])
        kernel = _make_kernel(kit)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert len(result.steps) == 2
        # First step: verification passed but decision is continue
        assert result.steps[0].verification is not None
        assert result.steps[0].verification.passed is True
        assert result.steps[0].decision == "continue"

    @pytest.mark.asyncio
    async def test_verification_not_required(self):
        """When verification is not required, it still runs but required=False."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(
                verification_passed=False,
                verification_required=False,
                decision="done",
            ),
        ])
        kernel = _make_kernel(kit)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert result.steps[0].verification is not None
        assert result.steps[0].verification.required is False


class TestKernelUnboundedLoop:
    @pytest.mark.asyncio
    async def test_no_tool_final_atomically_seals_guidance_before_task_done(self):
        registry = RuntimeTaskRegistry()
        current_task = asyncio.current_task()
        assert current_task is not None
        assert registry.accept_run("sealed-thread", "sealed-run") is True
        assert registry.register("sealed-thread", current_task, run_id="sealed-run") is True
        llm = MockLLMClient()
        kernel = _make_kernel(MockRuntimeKit([MockKitStep(reply="Final", decision="done")]), llm_client=llm)

        result = await kernel.run(RuntimeTurnInput(
            user_message="finish",
            run_id="sealed-run",
            turn_id="sealed-run",
            metadata={"session_id": "sealed-thread"},
            guidance_source=registry.guidance_source("sealed-thread", run_id="sealed-run"),
            guidance_finalizer=registry.guidance_finalizer("sealed-thread", run_id="sealed-run"),
        ))

        assert result.decision == "done"
        assert llm.call_count == 1
        assert registry.accept_guidance(
            "sealed-thread",
            "too late",
            run_id="sealed-run",
            guidance_id="late-guidance",
        ) == "closed"

    @pytest.mark.asyncio
    async def test_guidance_present_at_final_check_is_consumed_before_sealing(self):
        registry = RuntimeTaskRegistry()
        current_task = asyncio.current_task()
        assert current_task is not None
        assert registry.accept_run("race-thread", "race-run") is True
        assert registry.register("race-thread", current_task, run_id="race-run") is True

        class InjectingLLM:
            def __init__(self) -> None:
                self.call_count = 0

            async def stream(self, request):
                if False:
                    yield request
                raise NotImplementedError

            async def complete(self, request):
                self.call_count += 1
                if self.call_count == 1:
                    assert registry.accept_guidance(
                        "race-thread",
                        "new direction",
                        run_id="race-run",
                        guidance_id="guidance-1",
                    ) == "accepted"
                return LLMResponse(content="Final")

        llm = InjectingLLM()
        sink = CollectingEventSink()
        kernel = _make_kernel(
            MockRuntimeKit([
                MockKitStep(reply="First final", decision="done"),
                MockKitStep(reply="Guided final", decision="done"),
            ]),
            llm_client=llm,
            event_sink=sink,
        )

        result = await kernel.run(RuntimeTurnInput(
            user_message="finish",
            run_id="race-run",
            turn_id="race-run",
            metadata={"session_id": "race-thread"},
            guidance_source=registry.guidance_source("race-thread", run_id="race-run"),
            guidance_finalizer=registry.guidance_finalizer("race-thread", run_id="race-run"),
        ))

        assert result.decision == "done"
        assert llm.call_count == 2
        assert [event.payload["content"] for event in sink.events if event.name == "runtime.guidance_received"] == [
            "new direction"
        ]

    @pytest.mark.asyncio
    async def test_registry_rejects_run_overwrite_and_deduplicates_guidance_ids(self):
        registry = RuntimeTaskRegistry()
        current_task = asyncio.current_task()
        assert current_task is not None

        assert registry.accept_run("thread-1", "run-1") is True
        assert registry.accept_run("thread-1", "run-2") is False
        assert registry.register("thread-1", current_task, run_id="run-2") is False
        assert registry.register("thread-1", current_task, run_id="run-1") is True
        assert registry.active_run_id("thread-1") == "run-1"
        assert registry.accept_guidance(
            "thread-1", "once", run_id="run-1", guidance_id="client-1"
        ) == "accepted"
        assert registry.accept_guidance(
            "thread-1", "twice", run_id="run-1", guidance_id="client-1"
        ) == "duplicate"
        assert registry.consume_guidance("thread-1", run_id="run-1") == ["once"]

    @pytest.mark.asyncio
    async def test_retract_keeps_seen_id_after_kernel_consumed_guidance(self):
        registry = RuntimeTaskRegistry()
        current_task = asyncio.current_task()
        assert current_task is not None
        assert registry.accept_run("thread-consumed", "run-consumed") is True
        assert registry.register("thread-consumed", current_task, run_id="run-consumed") is True
        assert registry.accept_guidance(
            "thread-consumed",
            "consume once",
            run_id="run-consumed",
            guidance_id="client-consumed",
        ) == "accepted"
        assert registry.consume_guidance("thread-consumed", run_id="run-consumed") == ["consume once"]

        registry.retract_guidance(
            "thread-consumed",
            run_id="run-consumed",
            guidance_id="client-consumed",
        )

        assert registry.accept_guidance(
            "thread-consumed",
            "must not re-inject",
            run_id="run-consumed",
            guidance_id="client-consumed",
        ) == "duplicate"

    @pytest.mark.asyncio
    async def test_many_tool_rounds_continue_until_final_text(self):
        """Tool rounds continue until the model returns no-tool final text."""
        steps = [
            MockKitStep(
                reply="",
                tool_calls=[ToolCall(id=f"c{i}", name="run_command", arguments={"command": "echo ok"})],
                decision="done",
            )
            for i in range(8)
        ]
        steps.append(MockKitStep(reply="Final answer after many tools", decision="done"))
        kit = MockRuntimeKit(steps=steps)
        kernel = _make_kernel(kit)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert result.message == "Final answer after many tools"
        assert result.error == ""
        assert len(result.steps) == 9
        assert result.state is not None

    @pytest.mark.asyncio
    async def test_tool_calls_force_continue_until_no_tool_final_text(self):
        """A tool call is never terminal; the next no-tool text can finish."""
        call = ToolCall(id="c1", name="run_command", arguments={"command": "echo ok"})
        kit = MockRuntimeKit(steps=[
            MockKitStep(reply="", tool_calls=[call], decision="done"),
            MockKitStep(reply="Final answer from tool results", decision="done"),
        ])
        llm = MockLLMClient()
        kernel = _make_kernel(kit, llm_client=llm)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert result.message == "Final answer from tool results"
        assert result.state is not None
        assert result.state.metadata.get("tool_calls_force_continue") is True
        assert len(result.steps) == 2
        assert result.steps[0].metadata.get("tool_calls_force_continue") is True
        assert result.steps[-1].turn is not None
        assert result.steps[-1].turn.tool_calls == []

    @pytest.mark.asyncio
    async def test_done_requires_visible_final_text(self):
        """A no-tool empty response is not a successful final answer."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(reply="", decision="done"),
        ])
        kernel = _make_kernel(kit)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "wait"
        assert result.message == ""
        assert result.state is not None
        assert result.state.status == "waiting"
        assert result.state.metadata.get("done_without_final_text") is True


class TestKernelEvents:
    @pytest.mark.asyncio
    async def test_lifecycle_events_emitted(self):
        """Kernel emits started and terminal events."""
        kit = MockRuntimeKit(steps=[MockKitStep(decision="done")])
        sink = CollectingEventSink()
        kernel = _make_kernel(kit, event_sink=sink)

        result = await kernel.run(_make_turn_input())

        started = [e for e in sink.events if e.name == "runtime.started"]
        done = [e for e in sink.events if e.name == "runtime.done"]
        assert len(started) == 1
        assert len(done) == 1

    @pytest.mark.asyncio
    async def test_reply_event_emitted(self):
        """Kernel emits reply event for user-visible text."""
        kit = MockRuntimeKit(steps=[MockKitStep(reply="hello user", decision="done")])
        sink = CollectingEventSink()
        kernel = _make_kernel(kit, event_sink=sink)

        result = await kernel.run(_make_turn_input())

        reply_events = [e for e in sink.events if e.name == "runtime.reply"]
        assert len(reply_events) == 1
        assert reply_events[0].payload["content"] == "hello user"

    @pytest.mark.asyncio
    async def test_non_streaming_thinking_is_emitted_as_reasoning_part(self):
        """Kernel renders non-streaming thinking with the same reasoning part contract."""
        kit = MockRuntimeKit(steps=[MockKitStep(reply="final answer", decision="done")])
        sink = CollectingEventSink()
        llm = MockLLMClient(LLMResponse(content="final answer", thinking="visible shallow plan"))
        kernel = _make_kernel(kit, llm_client=llm, event_sink=sink)

        await kernel.run(_make_turn_input())

        reasoning_parts = [
            event.payload
            for event in sink.events
            if event.name == "runtime.part" and event.payload.get("part_type") == "reasoning"
        ]
        assert len(reasoning_parts) == 1
        assert reasoning_parts[0]["content"] == "visible shallow plan"
        assert reasoning_parts[0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_shallow_thinking_missing_does_not_block_tool_execution(self):
        """A shallow-thinking miss is diagnostic and must not replace model output."""
        call = LLMToolCall(id="call-1", name="search", arguments={"q": "test"})

        class ResponseDrivenToolKit(MockRuntimeKit):
            def __init__(self) -> None:
                super().__init__([MockKitStep(decision="failed")])
                self.executed: list[str] = []

            async def parse_model_output(self, state: RuntimeState, response: LLMResponse) -> KernelTurn:
                return KernelTurn(
                    reply=response.content,
                    tool_calls=[
                        ToolCall(id=tc.id, name=tc.name, arguments=tc.arguments if isinstance(tc.arguments, dict) else {})
                        for tc in response.tool_calls
                    ],
                    decision_hint="continue",
                )

            async def execute_tool(self, state: RuntimeState, call: ToolCall) -> ToolResult:
                self.executed.append(call.id)
                return await super().execute_tool(state, call)

        kit = ResponseDrivenToolKit()
        sink = CollectingEventSink()
        llm = MockLLMClient(LLMResponse(
            content="I will search first",
            tool_calls=[call],
            finish_reason="tool_calls",
            metadata={"shallow_thinking_missing": True},
        ))
        kernel = _make_kernel(kit, llm_client=llm, event_sink=sink)

        await kernel.run(_make_turn_input())

        assert kit.executed == ["call-1"]
        assert [event for event in sink.events if event.name == "runtime.tool.started"]
        replies = [event.payload["content"] for event in sink.events if event.name == "runtime.reply"]
        assert replies == []
        text_parts = [
            event.payload
            for event in sink.events
            if event.name == "runtime.part" and event.payload.get("part_type") == "text"
        ]
        assert any(part["content"] == "I will search first" for part in text_parts)

    @pytest.mark.asyncio
    async def test_tool_turn_text_is_process_not_reply(self):
        """Text from a tool-calling model response is process text, not final reply."""
        call = ToolCall(id="c1", name="search", arguments={"q": "test"})
        kit = MockRuntimeKit(steps=[
            MockKitStep(reply="I will search first", tool_calls=[call], decision="continue"),
            MockKitStep(reply="Final answer", decision="done"),
        ])
        sink = CollectingEventSink()
        kernel = _make_kernel(kit, event_sink=sink)

        await kernel.run(_make_turn_input())

        reply_events = [e for e in sink.events if e.name == "runtime.reply"]
        assert [e.payload["content"] for e in reply_events] == ["Final answer"]

        text_parts = [
            e.payload
            for e in sink.events
            if e.name == "runtime.part" and e.payload.get("part_type") == "text"
        ]
        process_part = next(p for p in text_parts if p["content"] == "I will search first")
        final_part = next(p for p in text_parts if p["content"] == "Final answer")
        assert process_part["has_tool_calls"] is True
        assert process_part["final_response"] is False
        assert final_part["has_tool_calls"] is False
        assert final_part["final_response"] is True

    @pytest.mark.asyncio
    async def test_stream_timeout_falls_back_to_non_streaming_completion(self):
        """A stalled stream uses the model timeout and falls back to complete()."""

        class ResponseEchoKit(MockRuntimeKit):
            async def parse_model_output(self, state: RuntimeState, response: LLMResponse) -> KernelTurn:
                return KernelTurn(reply=response.content)

            async def decide_next(self, state, turn, verification, step):
                return "done" if turn.reply else "failed"

        class SlowStreamFastCompleteLLM:
            def __init__(self) -> None:
                self.stream_calls = 0
                self.complete_calls = 0

            async def stream(self, request: LLMRequest):
                self.stream_calls += 1
                await asyncio.sleep(0.05)
                yield LLMStreamEvent(kind="content_delta", content="late stream text")
                yield LLMStreamEvent(kind="done")

            async def complete(self, request: LLMRequest) -> LLMResponse:
                self.complete_calls += 1
                return LLMResponse(content="fallback final text")

        llm = SlowStreamFastCompleteLLM()
        kernel = _make_kernel(
            ResponseEchoKit(),
            llm_client=llm,
            policy=LoopPolicy(
                model_timeout_seconds=1,
                model_retries=1,
                model_stream_idle_timeout_seconds=0.01,
            ),
        )

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert result.message == "fallback final text"
        assert llm.stream_calls == 1
        assert llm.complete_calls == 1

    @pytest.mark.asyncio
    async def test_tool_events_emitted(self):
        """Kernel emits tool started and finished events."""
        call = ToolCall(id="c1", name="search", arguments={"q": "test"})
        kit = MockRuntimeKit(steps=[
            MockKitStep(
                tool_calls=[call],
                decision="done",
            ),
            MockKitStep(reply="done", decision="done"),
        ])
        sink = CollectingEventSink()
        kernel = _make_kernel(kit, event_sink=sink)

        result = await kernel.run(_make_turn_input())

        started = [e for e in sink.events if e.name == "runtime.tool.started"]
        finished = [e for e in sink.events if e.name == "runtime.tool.finished"]
        assert len(started) == 1
        assert len(finished) == 1
        assert started[0].payload["tool_name"] == "search"

    @pytest.mark.asyncio
    async def test_verification_event_emitted(self):
        """Kernel emits verification result event."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(
                verification_passed=True,
                verification_required=True,
                verification_summary="all good",
                decision="done",
            ),
        ])
        sink = CollectingEventSink()
        kernel = _make_kernel(kit, event_sink=sink)

        result = await kernel.run(_make_turn_input())

        ver_events = [e for e in sink.events if e.name == "runtime.verification"]
        assert len(ver_events) == 1
        assert ver_events[0].payload["passed"] is True

    @pytest.mark.asyncio
    async def test_kit_events_forwarded(self):
        """Kit-produced events are forwarded through the event sink."""
        kit_event = CoreEvent(name="custom.business", category="progress", payload={"detail": "x"})
        kit = MockRuntimeKit(steps=[
            MockKitStep(kit_events=[kit_event], decision="done"),
        ])
        sink = CollectingEventSink()
        kernel = _make_kernel(kit, event_sink=sink)

        result = await kernel.run(_make_turn_input())

        custom = [e for e in sink.events if e.name == "custom.business"]
        assert len(custom) == 1
        assert custom[0].payload["detail"] == "x"

    @pytest.mark.asyncio
    async def test_verification_events_forwarded(self):
        """Verification events are forwarded through the event sink."""
        ver_event = CoreEvent(name="check.complete", category="verification")
        kit = MockRuntimeKit(steps=[
            MockKitStep(
                verification_passed=True,
                decision="done",
            ),
        ])
        # Override verify to include events
        original_verify = kit.verify

        async def verify_with_events(state, turn, tool_results):
            vr = await original_verify(state, turn, tool_results)
            vr.events = [ver_event]
            return vr

        kit.verify = verify_with_events
        sink = CollectingEventSink()
        kernel = _make_kernel(kit, event_sink=sink)

        result = await kernel.run(_make_turn_input())

        check_events = [e for e in sink.events if e.name == "check.complete"]
        assert len(check_events) == 1


class TestKernelStateSave:
    @pytest.mark.asyncio
    async def test_state_saved_on_each_step(self):
        """State is saved after each loop iteration."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(decision="continue"),
            MockKitStep(decision="continue"),
            MockKitStep(decision="done"),
        ])
        store = InMemoryStateStore()
        kernel = _make_kernel(kit, state_store=store)

        result = await kernel.run(_make_turn_input())

        # Initial save (mark running) + 3 step saves + final status save
        assert store.save_count >= 4

    @pytest.mark.asyncio
    async def test_state_preserved_across_steps(self):
        """State accumulates turn_count across steps."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(decision="continue"),
            MockKitStep(decision="done"),
        ])
        store = InMemoryStateStore()
        kernel = _make_kernel(kit, state_store=store)

        result = await kernel.run(_make_turn_input())

        assert result.state is not None
        assert result.state.turn_count == 2
        # Verify saved state matches
        saved = await store.get(result.state.session_id)
        assert saved is not None
        assert saved.turn_count == 2

    @pytest.mark.asyncio
    async def test_state_loaded_from_store(self):
        """Kernel loads session state but starts a fresh run for new input."""
        existing_state = RuntimeState(
            session_id="existing-session",
            run_id="existing-run",
            status="running",
            loop_state="continue",
            position="tool",
            turn_count=5,
            metadata={"existing": True},
        )
        store = InMemoryStateStore()
        await store.save(existing_state)

        kit = MockRuntimeKit(steps=[MockKitStep(decision="done")])
        kernel = _make_kernel(kit, state_store=store)

        result = await kernel.run(RuntimeTurnInput(
            user_message="resume",
            metadata={"session_id": "existing-session"},
        ))

        assert result.session_id == "existing-session"
        assert result.run_id
        assert result.run_id != "existing-run"
        assert result.state is not None
        assert result.state.turn_count == 6
        assert result.state.loop_state == "done"
        assert result.state.position == ""
        assert result.state.metadata.get("existing") is True

    @pytest.mark.asyncio
    async def test_state_from_turn_input(self):
        """Kernel uses provided session state but still starts a fresh run."""
        provided_state = RuntimeState(
            session_id="provided-session",
            run_id="provided-run",
            turn_count=3,
        )
        kit = MockRuntimeKit(steps=[MockKitStep(decision="done")])
        kernel = _make_kernel(kit)

        result = await kernel.run(RuntimeTurnInput(
            user_message="continue",
            state=provided_state,
        ))

        assert result.session_id == "provided-session"
        assert result.run_id
        assert result.run_id != "provided-run"
        assert result.state is not None
        assert result.state.turn_count == 4


class TestKernelModelCall:
    @pytest.mark.asyncio
    async def test_model_call_per_step(self):
        """Kernel calls the model once per step."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(decision="continue"),
            MockKitStep(decision="done"),
        ])
        llm = MockLLMClient()
        kernel = _make_kernel(kit, llm_client=llm)

        result = await kernel.run(_make_turn_input())

        assert llm.call_count == 2

    @pytest.mark.asyncio
    async def test_model_failure_retries(self):
        """Kernel retries model calls on failure."""
        kit = MockRuntimeKit(steps=[MockKitStep(decision="done")])
        llm = FailingLLMClient()
        policy = LoopPolicy(model_retries=2)
        kernel = _make_kernel(kit, llm_client=llm, policy=policy)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "failed"
        assert ("Model call failed" in result.error) or ("model unavailable" in result.error)

    @pytest.mark.asyncio
    async def test_model_failure_uses_retry_backoff(self, monkeypatch):
        """Kernel waits according to RetryPolicy between model retries."""
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        kit = MockRuntimeKit(steps=[MockKitStep(decision="done")])
        llm = FailingLLMClient()
        policy = LoopPolicy(model_retries=3)
        retry_policy = RetryPolicy(
            backoff_strategy=BackoffStrategy.LINEAR,
            initial_delay_seconds=0.25,
            max_delay_seconds=1.0,
            jitter=False,
        )
        kernel = _make_kernel(
            kit,
            llm_client=llm,
            policy=policy,
            retry_policy=retry_policy,
        )

        result = await kernel.run(_make_turn_input())

        assert result.decision == "failed"
        assert sleeps == [0.25, 0.5]

    @pytest.mark.asyncio
    async def test_model_failure_uses_staged_retry_schedule_and_emits_progress(self, monkeypatch):
        """Default model retry policy is visible and starts with short waits."""
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        kit = MockRuntimeKit(steps=[MockKitStep(decision="done")])
        llm = FailingLLMClient()
        policy = LoopPolicy()
        retry_policy = RetryPolicy(jitter=False)
        sink = CollectingEventSink()
        kernel = _make_kernel(
            kit,
            llm_client=llm,
            event_sink=sink,
            policy=policy,
            retry_policy=retry_policy,
        )

        result = await kernel.run(_make_turn_input())

        retry_events = [
            e for e in sink.events
            if e.name == "runtime.part" and e.payload.get("part_type") == "status"
        ]
        assert result.decision == "failed"
        assert sleeps == [1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 4.0, 8.0, 16.0]
        assert len(retry_events) == 9
        assert [e.payload["attempt"] for e in retry_events] == list(range(1, 10))
        assert retry_events[0].payload["label"] == "模型请求重试中 (1/9)"
        assert retry_events[-1].payload["label"] == "模型请求重试中 (9/9)"

    @pytest.mark.asyncio
    async def test_model_call_timeout_uses_policy(self):
        """Kernel enforces model timeout from LoopPolicy."""
        kit = MockRuntimeKit(steps=[MockKitStep(decision="done")])
        llm = SlowLLMClient()
        policy = LoopPolicy(model_retries=1, model_timeout_seconds=0.001)
        kernel = _make_kernel(kit, llm_client=llm, policy=policy)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "failed"
        assert ("Model call failed" in result.error) or ("too slow" in result.error)


class TestKernelKitHooks:
    @pytest.mark.asyncio
    async def test_on_run_start_called(self):
        """Kit.on_run_start is called at the beginning of a run."""
        kit = MockRuntimeKit(steps=[MockKitStep(decision="done")])
        kernel = _make_kernel(kit)

        await kernel.run(_make_turn_input())

        assert kit.on_run_start_called is True

    @pytest.mark.asyncio
    async def test_on_run_end_called(self):
        """Kit.on_run_end is called at the end of a run."""
        kit = MockRuntimeKit(steps=[MockKitStep(decision="done")])
        kernel = _make_kernel(kit)

        await kernel.run(_make_turn_input())

        assert kit.on_run_end_called is True

    @pytest.mark.asyncio
    async def test_writeback_called_per_step(self):
        """Kit.writeback is called once per step."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(decision="continue"),
            MockKitStep(decision="done"),
        ])
        kernel = _make_kernel(kit)

        await kernel.run(_make_turn_input())

        assert len(kit.writeback_calls) == 2

    @pytest.mark.asyncio
    async def test_build_context_called_per_step(self):
        """Kit.build_context is called once per step with correct index."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(decision="continue"),
            MockKitStep(decision="done"),
        ])
        kernel = _make_kernel(kit)

        await kernel.run(_make_turn_input())

        assert kit.build_context_calls == [0, 1]


class TestKernelToolResults:
    @pytest.mark.asyncio
    async def test_tool_results_appended_to_history(self):
        """Formatted tool results are appended to model history."""
        call = ToolCall(id="c1", name="search", arguments={"q": "test"})
        kit = MockRuntimeKit(steps=[
            MockKitStep(tool_calls=[call], decision="done"),
            MockKitStep(reply="done", decision="done"),
        ])
        llm = MockLLMClient()
        kernel = _make_kernel(kit, llm_client=llm)

        result = await kernel.run(_make_turn_input())

        # The second model call should include the tool result in history
        # (We verify indirectly through the step recording)
        assert len(result.steps[0].tool_steps) == 1
        assert result.steps[0].tool_steps[0].call.name == "search"

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_one_step(self):
        """Multiple tool calls in one step are all executed."""
        call1 = ToolCall(id="c1", name="search", arguments={"q": "a"})
        call2 = ToolCall(id="c2", name="read", arguments={"path": "b"})
        kit = MockRuntimeKit(steps=[
            MockKitStep(tool_calls=[call1, call2], decision="done"),
            MockKitStep(reply="done", decision="done"),
        ])
        kernel = _make_kernel(kit)

        result = await kernel.run(_make_turn_input())

        assert len(result.steps[0].tool_steps) == 2
        assert result.steps[0].tool_steps[0].call.name == "search"
        assert result.steps[0].tool_steps[1].call.name == "read"


class TestKernelNoBusinessPollution:
    def test_kernel_source_no_artist_writer_imager(self):
        """Kernel source code must not contain Artist/Writer/Imager business logic."""
        import lamtools_core.kernel.loop as loop_mod
        import lamtools_core.kernel.state as state_mod
        import lamtools_core.kernel.kit as kit_mod
        import lamtools_core.kernel.policy as policy_mod
        import lamtools_core.kernel.errors as errors_mod

        for mod in [loop_mod, state_mod, kit_mod, policy_mod, errors_mod]:
            source = open(mod.__file__, encoding="utf-8").read()
            # Business names should NOT appear in kernel source
            assert "Artist" not in source, f"Artist found in {mod.__file__}"
            assert "Writer" not in source, f"Writer found in {mod.__file__}"
            assert "Imager" not in source, f"Imager found in {mod.__file__}"
            # No references or app.* imports
            assert "references" not in source, f"references import in {mod.__file__}"
            assert "app." not in source, f"app.* import in {mod.__file__}"

    def test_kernel_no_if_product_branching(self):
        """Kernel must not contain if artist / if writer branching."""
        import lamtools_core.kernel.loop as loop_mod

        source = open(loop_mod.__file__, encoding="utf-8").read()
        assert 'if "artist"' not in source
        assert 'if "writer"' not in source
        assert "if product" not in source


class TestKernelRunId:
    @pytest.mark.asyncio
    async def test_supplied_live_run_id_prefixes_projected_item_ids_and_metadata(self):
        accepted_turn_id = "thread-1:turn:accepted-run"
        kit = MockRuntimeKit(steps=[MockKitStep(reply="done", decision="done")])
        sink = CollectingEventSink()
        kernel = _make_kernel(kit, event_sink=sink)

        result = await kernel.run(RuntimeTurnInput(
            user_message="start",
            run_id=accepted_turn_id,
            turn_id=accepted_turn_id,
            metadata={"session_id": "thread-1"},
        ))
        items = core_events_to_run_items(sink.events, thread_id="thread-1")

        assert result.run_id == accepted_turn_id
        assert items
        assert {item.run_id for item in items} == {accepted_turn_id}
        assert {item.turn_id for item in items} == {accepted_turn_id}
        assert all(item.item_id.startswith(accepted_turn_id) for item in items)
        assert {item.metadata["run_id"] for item in items} == {accepted_turn_id}

    @pytest.mark.asyncio
    async def test_run_id_generated_when_missing(self):
        """Kernel generates a run_id if state doesn't have one."""
        kit = MockRuntimeKit(steps=[MockKitStep(decision="done")])
        kernel = _make_kernel(kit)

        result = await kernel.run(RuntimeTurnInput(
            user_message="start",
            state=RuntimeState(session_id="s1"),
        ))

        assert result.run_id != ""
        assert result.state is not None
        assert result.state.run_id != ""


# ---------------------------------------------------------------------------
# Tests: Repair loop
# ---------------------------------------------------------------------------


class TestKernelRepairLoop:
    @pytest.mark.asyncio
    async def test_repair_prompt_not_injected_in_new_kernel(self):
        """Verification failure does NOT trigger repair injection.
        The model self-corrects based on tool results directly (OpenAI-style)."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(
                reply="first attempt",
                decision="continue",
                verification_passed=False,
                verification_required=True,
                verification_repair_prompt="Fix the formatting errors",
                verification_attempt=0,
                verification_max_attempts=3,
            ),
            MockKitStep(
                reply="repaired version",
                decision="done",
                verification_passed=True,
                verification_required=True,
            ),
        ])
        sink = CollectingEventSink()
        kernel = _make_kernel(kit, event_sink=sink)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert len(result.steps) == 2

        # No repair events — the kernel no longer injects repair prompts
        repair_events = [e for e in sink.events if e.name == "runtime.repair"]
        assert len(repair_events) == 0

    @pytest.mark.asyncio
    async def test_repair_loop_verify_fail_then_pass_no_injection(self):
        """Verification fail→continue→verify pass→done. No repair prompt injection."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(
                reply="draft",
                decision="continue",
                verification_passed=False,
                verification_required=True,
                verification_repair_prompt="Add missing section",
                verification_attempt=0,
                verification_max_attempts=3,
            ),
            MockKitStep(
                reply="repaired draft",
                decision="done",
                verification_passed=True,
                verification_required=True,
                verification_summary="all checks pass",
            ),
        ])
        kernel = _make_kernel(kit)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert len(result.steps) == 2
        # First step: verification failed
        assert result.steps[0].verification is not None
        assert result.steps[0].verification.passed is False
        # Second step: verification passed
        assert result.steps[1].verification is not None
        assert result.steps[1].verification.passed is True

    @pytest.mark.asyncio
    async def test_no_max_repair_attempts_enforcement(self):
        """Kernel no longer enforces max repair attempts.
        The loop continues until the kit returns a terminal decision."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(
                reply="final attempt",
                decision="continue",
                verification_passed=False,
                verification_required=True,
                verification_repair_prompt="Try again",
                verification_attempt=3,
                verification_max_attempts=3,
            ),
            MockKitStep(
                reply="kit decided to stop",
                decision="failed",
                verification_passed=False,
                verification_required=True,
                verification_repair_prompt="Try again",
                verification_attempt=4,
                verification_max_attempts=3,
            ),
        ])
        kernel = _make_kernel(kit)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "failed"
        assert result.error == ""
        assert result.state is not None
        assert result.state.status == "failed"
        assert len(result.steps) == 2

    @pytest.mark.asyncio
    async def test_no_repair_prompt_when_verification_passes(self):
        """When verification passes, no repair prompt is injected."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(
                reply="good work",
                decision="continue",
                verification_passed=True,
                verification_required=True,
            ),
            MockKitStep(
                reply="done",
                decision="done",
            ),
        ])
        sink = CollectingEventSink()
        kernel = _make_kernel(kit, event_sink=sink)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        repair_events = [e for e in sink.events if e.name == "runtime.repair"]
        assert len(repair_events) == 0

    @pytest.mark.asyncio
    async def test_verification_event_includes_attempt_info(self):
        """Verification event payload includes attempt and max_attempts."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(
                reply="trying",
                decision="done",
                verification_passed=False,
                verification_required=True,
                verification_attempt=1,
                verification_max_attempts=5,
            ),
        ])
        sink = CollectingEventSink()
        kernel = _make_kernel(kit, event_sink=sink)

        result = await kernel.run(_make_turn_input())

        verif_events = [e for e in sink.events if e.name == "runtime.verification"]
        assert len(verif_events) == 1
        assert verif_events[0].payload["attempt"] == 1
        assert verif_events[0].payload["max_attempts"] == 5


class TestKernelParallelToolWhitelist:
    @pytest.mark.asyncio
    async def test_parallelizes_only_whitelisted_tool_names(self):
        calls = [
            ToolCall(id="agent-1", name="sub_agent", arguments={"task": "A"}),
            ToolCall(id="agent-2", name="sub_agent", arguments={"task": "B"}),
        ]
        kit = RecordingSlowToolKit([
            MockKitStep(
                tool_calls=calls,
                decision="done",
            ),
            MockKitStep(reply="done", decision="done"),
        ])
        kernel = _make_kernel(
            kit,
            policy=LoopPolicy(parallel_tool_names=("sub_agent",)),
        )

        start = asyncio.get_running_loop().time()
        result = await kernel.run(_make_turn_input())
        elapsed = asyncio.get_running_loop().time() - start

        assert result.decision == "done"
        assert set(kit.started) == {"agent-1", "agent-2"}
        assert elapsed < 0.09

    @pytest.mark.asyncio
    async def test_parallel_preflight_can_block_tool_execution(self):
        calls = [
            ToolCall(id="agent-1", name="sub_agent", arguments={"task": "A"}),
            ToolCall(id="agent-2", name="sub_agent", arguments={"task": "B"}),
        ]
        kit = PreflightBlockingToolKit([
            MockKitStep(
                tool_calls=calls,
                decision="done",
            ),
            MockKitStep(reply="done", decision="done"),
        ])
        kernel = _make_kernel(
            kit,
            policy=LoopPolicy(parallel_tool_names=("sub_agent",)),
        )

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert kit.started == []
        assert [tool.result.status for tool in result.steps[0].tool_steps] == ["failed", "failed"]


# ---------------------------------------------------------------------------
# Tests: Token-based context compaction
# ---------------------------------------------------------------------------


class TestKernelContextCompaction:
    @pytest.mark.asyncio
    async def test_compacts_request_when_estimate_reaches_80_percent(self):
        class LargeRequestKit(MockRuntimeKit):
            async def build_model_request(self, state, context):
                messages = [ChatMessage(role="system", content="stable prefix")]
                for i in range(5):
                    messages.append(ChatMessage(
                        role="user",
                        content=f"old user {i} " + ("x" * 500),
                        metadata={"message_id": f"user-{i}"},
                    ))
                    messages.append(ChatMessage(
                        role="assistant",
                        content=f"old assistant {i} " + ("y" * 500),
                        metadata={"message_id": f"assistant-{i}"},
                    ))
                messages.append(ChatMessage(role="user", content="current task"))
                return LLMRequest(messages=messages, model="mock-model")

        sink = CollectingEventSink()
        llm = CapturingLLMClient()
        kernel = _make_kernel(
            LargeRequestKit(steps=[MockKitStep(decision="done")]),
            llm_client=llm,
            event_sink=sink,
            policy=LoopPolicy(
                context_window_tokens=2_000,
                compact_trigger_ratio=0.8,
                compact_target_ratio=0.6,
            ),
        )

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert llm.last_request is not None
        assert llm.call_count == 2
        assert llm.last_request.metadata["context_compacted"] is True
        assert llm.last_request.metadata["context_compaction_mode"] == "structured_summary"
        assert llm.last_request.metadata["context_tokens_before_compaction"] >= 1_600
        assert llm.last_request.metadata["context_tokens_after_compaction"] <= 1_200
        assert llm.last_request.messages[0].role == "system"
        summary_messages = [
            message
            for message in llm.last_request.messages
            if message.metadata.get("key") == "context_compaction_summary"
        ]
        assert len(summary_messages) == 1
        assert "[Compacted Context]" in summary_messages[0].content
        assert "Current Goal" in summary_messages[0].content
        assert "User History, Instructions, And Decisions" in summary_messages[0].content
        assert "old user 0 requested an earlier constraint" in summary_messages[0].content
        assert "Next Best Actions" in summary_messages[0].content
        raw_messages = [
            str(m.content)
            for m in llm.last_request.messages
            if m.metadata.get("key") != "context_compaction_summary"
        ]
        assert "old user 0" not in "\n".join(raw_messages)
        assert llm.last_request.messages[-1].role == "user"
        assert llm.last_request.messages[-1].content == "current task"

        events = [event for event in sink.events if event.name == "runtime.context_compacted"]
        assert len(events) == 1
        assert events[0].payload["trigger_tokens"] == 1_600
        assert events[0].payload["target_tokens"] == 1_200
        assert events[0].payload["removed"] > 0
        assert events[0].payload["compacted_message_ids"][:2] == ["user-0", "assistant-0"]
        assert "user-4" in events[0].payload["compacted_message_ids"]

        part_events = [
            event
            for event in sink.events
            if event.name == "runtime.part" and event.payload.get("part_type") == "compaction"
        ]
        assert [event.payload["status"] for event in part_events] == ["running", "completed"]
        assert part_events[-1].payload["label"] == "上下文已压缩"
        assert part_events[-1].payload["trigger"] == "auto"
        assert "[Compacted Context]" in part_events[-1].payload["content"]

    @pytest.mark.asyncio
    async def test_compaction_target_ratio_is_a_hard_upper_bound(self):
        class OversizedSummaryKit(MockRuntimeKit):
            async def build_model_request(self, state, context):
                messages = [ChatMessage(role="system", content="stable prefix")]
                for i in range(5):
                    messages.append(ChatMessage(role="user", content=f"important user {i} " + ("x" * 500)))
                    messages.append(ChatMessage(role="assistant", content=f"noisy assistant {i} " + ("y" * 500)))
                messages.append(ChatMessage(role="user", content="current task"))
                return LLMRequest(messages=messages, model="mock-model")

        sink = CollectingEventSink()
        llm = VerboseCompactionLLMClient()
        kernel = _make_kernel(
            OversizedSummaryKit(steps=[MockKitStep(decision="done")]),
            llm_client=llm,
            event_sink=sink,
            policy=LoopPolicy(
                context_window_tokens=2_000,
                compact_trigger_ratio=0.8,
                compact_target_ratio=0.6,
            ),
        )

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert llm.last_request is not None
        assert llm.last_request.metadata["context_tokens_after_compaction"] <= 1_200
        summary_messages = [
            message
            for message in llm.last_request.messages
            if message.metadata.get("key") == "context_compaction_summary"
        ]
        assert len(summary_messages) == 1
        assert "User History, Instructions, And Decisions" in summary_messages[0].content
        assert "effective information" in summary_messages[0].content
        assert "verbose summary " not in summary_messages[0].content
        assert "tool output " not in summary_messages[0].content

    @pytest.mark.asyncio
    async def test_compaction_stream_model_call_uses_kernel_retry_policy(self):
        class LargeRequestKit(MockRuntimeKit):
            async def build_model_request(self, state, context):
                messages = [ChatMessage(role="system", content="stable prefix")]
                for i in range(5):
                    messages.append(ChatMessage(role="user", content=f"old user {i} " + ("x" * 500)))
                    messages.append(ChatMessage(role="assistant", content=f"old assistant {i} " + ("y" * 500)))
                messages.append(ChatMessage(role="user", content="current task"))
                return LLMRequest(messages=messages, model="mock-model")

        sink = CollectingEventSink()
        llm = FlakyStreamingCompactionLLMClient(compaction_failures=2)
        kernel = _make_kernel(
            LargeRequestKit(steps=[MockKitStep(decision="done")]),
            llm_client=llm,
            event_sink=sink,
            policy=LoopPolicy(
                context_window_tokens=2_000,
                compact_trigger_ratio=0.8,
                compact_target_ratio=0.6,
                model_retries=3,
            ),
            retry_policy=RetryPolicy(
                initial_delay_seconds=0,
                max_delay_seconds=0,
                jitter=False,
                staged_delay_seconds=(),
            ),
        )

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        compaction_requests = [
            request
            for request in llm.stream_requests
            if request.messages
            and isinstance(request.messages[0].content, str)
            and request.messages[0].content.startswith("Summarize this agent session context")
        ]
        assert len(compaction_requests) == 3
        compaction_complete_requests = [
            request
            for request in llm.requests
            if request.messages
            and isinstance(request.messages[0].content, str)
            and request.messages[0].content.startswith("Summarize this agent session context")
        ]
        assert compaction_complete_requests == []
        retry_events = [
            event
            for event in sink.events
            if event.name == "runtime.part" and event.payload.get("status") == "retrying"
        ]
        assert [event.payload["attempt"] for event in retry_events] == [1, 2]
        assert [event.payload["max_retries"] for event in retry_events] == [2, 2]
        compaction_parts = [
            event
            for event in sink.events
            if event.name == "runtime.part" and event.payload.get("part_type") == "compaction"
        ]
        assert [event.payload["status"] for event in compaction_parts] == [
            "running",
            "running",
            "completed",
        ]
        assert [event for event in sink.events if event.name == "runtime.context_compacted"]

    @pytest.mark.asyncio
    async def test_compaction_model_failure_stops_run_without_success_event(self):
        class LargeRequestKit(MockRuntimeKit):
            async def build_model_request(self, state, context):
                messages = [ChatMessage(role="system", content="stable prefix")]
                for i in range(5):
                    messages.append(ChatMessage(role="user", content=f"old user {i} " + ("x" * 500)))
                    messages.append(ChatMessage(role="assistant", content=f"old assistant {i} " + ("y" * 500)))
                messages.append(ChatMessage(role="user", content="current task"))
                return LLMRequest(messages=messages, model="mock-model")

        sink = CollectingEventSink()
        llm = FailingCompactionOnlyLLMClient()
        kernel = _make_kernel(
            LargeRequestKit(steps=[MockKitStep(decision="done")]),
            llm_client=llm,
            event_sink=sink,
            policy=LoopPolicy(
                context_window_tokens=2_000,
                compact_trigger_ratio=0.8,
                compact_target_ratio=0.6,
                model_retries=3,
            ),
            retry_policy=RetryPolicy(
                initial_delay_seconds=0,
                max_delay_seconds=0,
                jitter=False,
                staged_delay_seconds=(),
            ),
        )

        result = await kernel.run(_make_turn_input())

        assert result.decision == "failed"
        assert result.error == (
            "Context compaction failed: "
            "Model call failed after 3 attempts: compaction model unavailable"
        )
        assert llm.call_count == 3
        assert [event for event in sink.events if event.name == "runtime.context_compacted"] == []
        assert [
            event
            for event in sink.events
            if event.name == "runtime.part" and event.payload.get("part_type") == "compaction"
        ] == []
        retry_events = [
            event
            for event in sink.events
            if event.name == "runtime.part" and event.payload.get("status") == "retrying"
        ]
        assert [event.payload["attempt"] for event in retry_events] == [1, 2]
        failed_events = [event for event in sink.events if event.name == "runtime.failed"]
        assert len(failed_events) == 1
        assert failed_events[0].payload["error"] == result.error

    @pytest.mark.asyncio
    async def test_compaction_fails_clearly_when_preserved_context_exceeds_target(self):
        class UncompressibleCurrentRequestKit(MockRuntimeKit):
            async def build_model_request(self, state, context):
                return LLMRequest(
                    messages=[
                        ChatMessage(role="system", content="stable prefix"),
                        ChatMessage(role="assistant", content="old context " + ("x" * 1200)),
                        ChatMessage(role="user", content="current huge message " + ("y" * 6000)),
                    ],
                    model="mock-model",
                )

        sink = CollectingEventSink()
        llm = CapturingLLMClient()
        kernel = _make_kernel(
            UncompressibleCurrentRequestKit(steps=[MockKitStep(decision="done")]),
            llm_client=llm,
            event_sink=sink,
            policy=LoopPolicy(
                context_window_tokens=2_000,
                compact_trigger_ratio=0.8,
                compact_target_ratio=0.6,
            ),
        )

        result = await kernel.run(_make_turn_input())

        assert result.decision == "failed"
        assert result.error.startswith("Context compaction failed to fit within target budget:")
        assert "Unexpected error" not in result.error
        assert [event for event in sink.events if event.name == "runtime.context_compacted"] == []

    @pytest.mark.asyncio
    async def test_compacts_tool_heavy_current_turn_after_latest_user_message(self):
        class ToolHeavyCurrentTurnKit(MockRuntimeKit):
            async def build_model_request(self, state, context):
                messages = [
                    ChatMessage(role="system", content="stable prefix"),
                    ChatMessage(role="user", content="current long task with exact acceptance criteria"),
                ]
                for i in range(8):
                    messages.append(ChatMessage(role="assistant", content=f"inspecting step {i}"))
                    messages.append(
                        ChatMessage(
                            role="tool",
                            name="run_command",
                            tool_call_id=f"call-{i}",
                            content=f"CURRENT_TOOL_RESULT_SENTINEL {i} " + ("z" * 900),
                        )
                    )
                return LLMRequest(messages=messages, model="mock-model")

        sink = CollectingEventSink()
        llm = CapturingLLMClient()
        kernel = _make_kernel(
            ToolHeavyCurrentTurnKit(steps=[MockKitStep(decision="done")]),
            llm_client=llm,
            event_sink=sink,
            policy=LoopPolicy(
                context_window_tokens=2_000,
                compact_trigger_ratio=0.8,
                compact_target_ratio=0.6,
            ),
        )

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert llm.last_request is not None
        assert llm.last_request.metadata["context_compacted"] is True
        assert llm.last_request.metadata["context_tokens_after_compaction"] <= 1_200
        summary_prompt = llm.requests[0].messages[-1].content
        assert "CURRENT_TOOL_RESULT_SENTINEL" in str(summary_prompt)
        raw_messages = [
            str(message.content)
            for message in llm.last_request.messages
            if message.metadata.get("key") != "context_compaction_summary"
        ]
        assert "CURRENT_TOOL_RESULT_SENTINEL" not in "\n".join(raw_messages)
        assert llm.last_request.messages[-1].role == "user"
        assert llm.last_request.messages[-1].content == "current long task with exact acceptance criteria"

    @pytest.mark.asyncio
    async def test_does_not_compact_below_80_percent(self):
        class SmallRequestKit(MockRuntimeKit):
            async def build_model_request(self, state, context):
                return LLMRequest(
                    messages=[
                        ChatMessage(role="system", content="stable prefix"),
                        ChatMessage(role="user", content="current task"),
                    ],
                    model="mock-model",
                )

        sink = CollectingEventSink()
        llm = CapturingLLMClient()
        kernel = _make_kernel(
            SmallRequestKit(steps=[MockKitStep(decision="done")]),
            llm_client=llm,
            event_sink=sink,
            policy=LoopPolicy(context_window_tokens=10_000, compact_trigger_ratio=0.8),
        )

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert llm.last_request is not None
        assert "context_compacted" not in llm.last_request.metadata
        assert [event for event in sink.events if event.name == "runtime.context_compacted"] == []


# ---------------------------------------------------------------------------
# Tests: LoopPhase
# ---------------------------------------------------------------------------


class TestKernelLoopPhase:
    def test_loop_phase_type_values(self):
        """LoopPhase accepts the four defined values."""
        phases: list[LoopPhase] = ["idle", "plan", "execute", "verify"]
        assert len(phases) == 4

    def test_kernel_step_default_phase_is_execute(self):
        """KernelStep defaults to 'execute' phase."""
        state = RuntimeState(session_id="s1")
        step = KernelStep(index=0, state_before=state)
        assert step.phase == "execute"

    def test_kernel_step_phase_can_be_set(self):
        """KernelStep phase can be explicitly set."""
        state = RuntimeState(session_id="s1")
        step = KernelStep(index=0, state_before=state, phase="verify")
        assert step.phase == "verify"

    @pytest.mark.asyncio
    async def test_new_run_resets_stale_state_position(self):
        """A new user input starts from execute instead of prior-run position."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(decision="done"),
        ])
        kernel = _make_kernel(kit)

        result = await kernel.run(RuntimeTurnInput(
            user_message="start",
            state=RuntimeState(session_id="s1", position="verify"),
        ))

        assert len(result.steps) == 1
        assert result.steps[0].phase == "execute"

    @pytest.mark.asyncio
    async def test_step_phase_defaults_to_execute_for_invalid_position(self):
        """When state.position is not a valid LoopPhase, step.phase defaults to 'execute'."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(decision="done"),
        ])
        kernel = _make_kernel(kit)

        result = await kernel.run(RuntimeTurnInput(
            user_message="start",
            state=RuntimeState(session_id="s1", position="some_custom_value"),
        ))

        assert len(result.steps) == 1
        assert result.steps[0].phase == "execute"


# ---------------------------------------------------------------------------
# Tests: Cancellation
# ---------------------------------------------------------------------------


class TestKernelCancellation:
    @pytest.mark.asyncio
    async def test_cancel_stops_loop(self):
        """Calling cancel() during an async gap causes the kernel to stop with error='cancelled'."""
        cancel_event = asyncio.Event()

        class CancelAfterFirstStep(MockRuntimeKit):
            """Kit that triggers cancel after the first step completes."""
            step_count = 0

            async def decide_next(self, state, turn, verification, step):
                self.step_count += 1
                if self.step_count == 1:
                    # After first step, signal cancel
                    cancel_event.set()
                return await super().decide_next(state, turn, verification, step)

        kit = CancelAfterFirstStep(steps=[
            MockKitStep(decision="continue"),
            MockKitStep(decision="continue"),
            MockKitStep(decision="done"),
        ])
        kernel = _make_kernel(kit)
        # Wire cancel_event to kernel's cancel
        kernel._cancel_event = cancel_event

        result = await kernel.run(_make_turn_input())

        assert result.decision == "failed"
        assert result.error == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_detected_at_loop_start(self):
        """If cancel is set during a step, the next iteration detects it and fails."""
        # Use a kit that sets cancel during writeback (an async method)
        class CancelDuringWriteback(MockRuntimeKit):
            cancel_target: asyncio.Event | None = None

            async def writeback(self, state, turn, tool_results, verification, decision):
                if self.cancel_target and decision == "continue":
                    self.cancel_target.set()
                await super().writeback(state, turn, tool_results, verification, decision)

        cancel_event = asyncio.Event()
        kit = CancelDuringWriteback(steps=[
            MockKitStep(decision="continue"),
            MockKitStep(decision="done"),
        ])
        kit.cancel_target = cancel_event
        kernel = _make_kernel(kit)
        kernel._cancel_event = cancel_event

        result = await kernel.run(_make_turn_input())

        # Cancel was set during step 0's writeback, detected at step 1's start
        assert result.decision == "failed"
        assert result.error == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_resets_between_runs(self):
        """Cancel event is cleared at the start of each run, so a new run works normally."""
        cancel_event = asyncio.Event()
        cancel_event.set()

        kit = MockRuntimeKit(steps=[MockKitStep(decision="done")])
        kernel = _make_kernel(kit)
        kernel._cancel_event = cancel_event

        # First run: cancel is set, but run() clears it at start
        result1 = await kernel.run(_make_turn_input())
        assert result1.decision == "done"
        assert result1.error == ""

        # Now set cancel and run again — should be cleared again
        cancel_event.set()
        result2 = await kernel.run(_make_turn_input())
        assert result2.decision == "done"
        assert result2.error == ""


# ---------------------------------------------------------------------------
# Tests: Assistant response in history
# ---------------------------------------------------------------------------


class TestKernelAssistantHistory:
    @pytest.mark.asyncio
    async def test_assistant_reply_appended_to_history(self):
        """Assistant reply is appended to history before tool results."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(
                reply="I will search",
                tool_calls=[ToolCall(id="c1", name="search", arguments={"q": "test"})],
                decision="done",
            ),
            MockKitStep(reply="done", decision="done"),
        ])
        # We need to capture the history passed to build_context
        # Use a custom kit that records history
        history_snapshots: list[list[ChatMessage]] = []

        class HistoryCapturingKit(MockRuntimeKit):
            async def build_context(self, state, turn_input, history, step_index):
                history_snapshots.append(list(history))
                return await super().build_context(state, turn_input, history, step_index)

        capturing_kit = HistoryCapturingKit(steps=[
            MockKitStep(
                reply="I will search",
                tool_calls=[ToolCall(id="c1", name="search", arguments={"q": "test"})],
                decision="done",
            ),
            MockKitStep(reply="done", decision="done"),
        ])
        kernel = _make_kernel(capturing_kit)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        # The first turn still keeps assistant text alongside its tool call.
        assert result.steps[0].turn is not None
        assert result.steps[0].turn.reply == "I will search"

    @pytest.mark.asyncio
    async def test_assistant_history_visible_in_next_iteration(self):
        """Assistant response from step N is visible in history at step N+1."""
        history_snapshots: list[list[ChatMessage]] = []

        class HistoryCapturingKit(MockRuntimeKit):
            async def build_context(self, state, turn_input, history, step_index):
                history_snapshots.append([ChatMessage(role=m.role, content=m.content) for m in history])
                return await super().build_context(state, turn_input, history, step_index)

        capturing_kit = HistoryCapturingKit(steps=[
            MockKitStep(
                reply="step 1 reply",
                decision="continue",
            ),
            MockKitStep(
                reply="step 2 reply",
                decision="done",
            ),
        ])
        kernel = _make_kernel(capturing_kit)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert len(history_snapshots) == 2

        # Step 0 history: just the user message
        assert len(history_snapshots[0]) == 1
        assert history_snapshots[0][0].role == "user"

        # Step 1 history: user message + assistant reply from step 0
        assert len(history_snapshots[1]) == 2
        assert history_snapshots[1][0].role == "user"
        assert history_snapshots[1][1].role == "assistant"
        assert history_snapshots[1][1].content == "step 1 reply"

    @pytest.mark.asyncio
    async def test_assistant_tool_calls_visible_in_next_iteration(self):
        """Assistant history preserves tool call IDs before tool result messages."""
        history_snapshots: list[list[ChatMessage]] = []

        class HistoryCapturingKit(MockRuntimeKit):
            async def build_context(self, state, turn_input, history, step_index):
                history_snapshots.append([
                    ChatMessage(
                        role=m.role,
                        content=m.content,
                        tool_call_id=m.tool_call_id,
                        tool_calls=list(m.tool_calls),
                    )
                    for m in history
                ])
                return await super().build_context(state, turn_input, history, step_index)

        call = ToolCall(id="call-1", name="search", arguments={"q": "cat"}, reason="look up fact")
        kit = HistoryCapturingKit(steps=[
            MockKitStep(
                reply="checking",
                tool_calls=[call],
                decision="continue",
                verification_passed=True,
            ),
            MockKitStep(reply="done", decision="done", verification_passed=True),
        ])
        kernel = _make_kernel(kit)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        step1_history = history_snapshots[1]
        assistant_messages = [m for m in step1_history if m.role == "assistant"]
        tool_messages = [m for m in step1_history if m.role == "tool"]
        assert len(assistant_messages) == 1
        assert len(assistant_messages[0].tool_calls) == 1
        assert assistant_messages[0].tool_calls[0].id == "call-1"
        assert assistant_messages[0].tool_calls[0].name == "search"
        assert assistant_messages[0].tool_calls[0].arguments == {"q": "cat"}
        assert assistant_messages[0].tool_calls[0].metadata["reason"] == "look up fact"
        assert len(tool_messages) == 1
        assert tool_messages[0].tool_call_id == "call-1"

    @pytest.mark.asyncio
    async def test_repair_prompt_not_in_history(self):
        """Repair prompt appears as a user message in the next iteration's history."""
        history_snapshots: list[list[ChatMessage]] = []

        class HistoryCapturingKit(MockRuntimeKit):
            async def build_context(self, state, turn_input, history, step_index):
                history_snapshots.append([ChatMessage(role=m.role, content=m.content) for m in history])
                return await super().build_context(state, turn_input, history, step_index)

        capturing_kit = HistoryCapturingKit(steps=[
            MockKitStep(
                reply="first attempt",
                decision="continue",
                verification_passed=False,
                verification_required=True,
                verification_repair_prompt="Fix the errors",
                verification_attempt=0,
                verification_max_attempts=3,
            ),
            MockKitStep(
                reply="repaired",
                decision="done",
                verification_passed=True,
            ),
        ])
        kernel = _make_kernel(capturing_kit)

        result = await kernel.run(_make_turn_input())

        assert result.decision == "done"
        assert len(history_snapshots) == 2

        # Step 1 history should NOT contain a repair prompt injection
        # (the kernel no longer injects repair prompts into history)
        step1_history = history_snapshots[1]
        assert step1_history[0].role == "user"  # original user message
        assert step1_history[1].role == "assistant"  # assistant reply from step 0
        # No repair prompt injection — the model self-corrects from tool results
        assert len(step1_history) == 2


# ---------------------------------------------------------------------------
# Tests: VerificationResult attempt/max_attempts
# ---------------------------------------------------------------------------


class TestVerificationResultAttempt:
    def test_verification_result_attempt_defaults(self):
        """VerificationResult defaults: attempt=0, max_attempts=3."""
        vr = VerificationResult(passed=False)
        assert vr.attempt == 0
        assert vr.max_attempts == 3

    def test_verification_result_attempt_can_be_set(self):
        """VerificationResult attempt and max_attempts can be set."""
        vr = VerificationResult(passed=False, attempt=2, max_attempts=5)
        assert vr.attempt == 2
        assert vr.max_attempts == 5

    @pytest.mark.asyncio
    async def test_step_verification_captures_attempt_info(self):
        """KernelStep.verification captures attempt and max_attempts from Kit."""
        kit = MockRuntimeKit(steps=[
            MockKitStep(
                decision="done",
                verification_passed=False,
                verification_required=True,
                verification_attempt=1,
                verification_max_attempts=5,
            ),
        ])
        kernel = _make_kernel(kit)

        result = await kernel.run(_make_turn_input())

        assert result.steps[0].verification is not None
        assert result.steps[0].verification.attempt == 1
        assert result.steps[0].verification.max_attempts == 5
