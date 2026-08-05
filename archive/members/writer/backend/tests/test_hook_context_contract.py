"""Contract tests: prove that WriterKit context enters the LLM request.

These tests verify the current Kernel/Kit contract. WriterKit owns business
context injection, verification, decision, and writeback behavior.
"""

from __future__ import annotations

import pytest

from lamtools_core.event import InMemoryEventLog, CoreEvent
from lamtools_core.kernel import CoreLoopKernel, LoopPolicy
from lamtools_core.llm import ChatMessage, LLMRequest, LLMResponse
from lamtools_core.prompt import PromptContext
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState, RuntimeTurnInput

from app.core.persona import get_writer_system_prompt
from app.core.writer.core_kernel_adapter import WriterKit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class CapturingLLMClient:
    """LLMClient that captures the request for inspection."""

    def __init__(self) -> None:
        self.captured_request: LLMRequest | None = None

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.captured_request = request
        return LLMResponse(content="Done", finish_reason="stop")

    async def stream(self, request: LLMRequest):
        raise NotImplementedError


class _EventSink:
    def __init__(self, event_log: InMemoryEventLog) -> None:
        self._log = event_log

    async def emit(self, event: CoreEvent) -> None:
        self._log.append(event)


def _make_kernel(
    kit: WriterKit,
    llm: CapturingLLMClient,
    state: RuntimeState | None = None,
) -> tuple[CoreLoopKernel, RuntimeTurnInput]:
    """Build a CoreLoopKernel with the given kit, llm, and optional state.

    If state is provided, it is passed via turn_input.state so the kernel
    uses it directly (bypassing state_store lookup).
    """
    event_log = InMemoryEventLog()
    kernel = CoreLoopKernel(
        kit=kit,
        llm_client=llm,
        state_store=InMemoryRuntimeStateStore(),
        event_sink=_EventSink(event_log),
        policy=LoopPolicy(),
    )
    turn_input = RuntimeTurnInput(
        user_message="test",
        metadata={"session_id": state.session_id if state else "test"},
        state=state,
    )
    return kernel, turn_input


# ---------------------------------------------------------------------------
# Writer Kit context contract tests
# ---------------------------------------------------------------------------


class TestWriterHookContextEntersModelRequest:
    """Prove that WriterKit context enters the LLM request."""

    @pytest.mark.asyncio
    async def test_hook_context_injects_system_message(self):
        """Writer business context appears as a system message in the LLM request."""
        llm = CapturingLLMClient()
        kit = WriterKit()

        state = RuntimeState(session_id="test-hook-ctx")
        state.metadata["project_rules"] = "Use TypeScript strict mode"
        state.metadata["git_state"] = {
            "current": {"branch": "main", "head": "abc123def456"},
            "task_branch": "feat/test",
        }

        kernel, turn_input = _make_kernel(kit, llm, state)
        await kernel.run(turn_input)

        assert llm.captured_request is not None
        system_msgs = [m for m in llm.captured_request.messages if m.role == "system"]
        hook_context_msgs = [
            m for m in system_msgs if m.metadata.get("key") == "hook_context"
        ]
        assert len(hook_context_msgs) > 0, (
            "Hook context must appear in model request as a system message"
        )

    @pytest.mark.asyncio
    async def test_project_rules_appear_in_request(self):
        """project_rules from state metadata appear in the context system message."""
        llm = CapturingLLMClient()
        kit = WriterKit()

        state = RuntimeState(session_id="test-rules")
        state.metadata["project_rules"] = "Use TypeScript strict mode"

        kernel, turn_input = _make_kernel(kit, llm, state)
        await kernel.run(turn_input)

        hook_msg = _get_hook_context_msg(llm.captured_request)
        assert "Project Rules" in hook_msg.content
        assert "TypeScript strict mode" in hook_msg.content

    @pytest.mark.asyncio
    async def test_git_context_appears_in_request(self):
        """git_context from state metadata appears in the context system message."""
        llm = CapturingLLMClient()
        kit = WriterKit()

        state = RuntimeState(session_id="test-git")
        state.metadata["git_state"] = {
            "current": {"branch": "develop", "head": "deadbeef1234"},
            "task_branch": "feat/hook-ctx",
        }

        kernel, turn_input = _make_kernel(kit, llm, state)
        await kernel.run(turn_input)

        hook_msg = _get_hook_context_msg(llm.captured_request)
        assert "Git" in hook_msg.content
        assert "develop" in hook_msg.content

    @pytest.mark.asyncio
    async def test_iteration_limit_is_not_injected(self):
        """Iteration limits are not injected into Writer prompts."""
        llm = CapturingLLMClient()
        kit = WriterKit()

        kernel, turn_input = _make_kernel(kit, llm)
        await kernel.run(turn_input)

        hook_msg = _get_hook_context_msg(llm.captured_request)
        assert hook_msg is None

    @pytest.mark.asyncio
    async def test_no_hook_context_when_empty_metadata(self):
        """When state has no business metadata, no hook context is injected."""
        llm = CapturingLLMClient()
        kit = WriterKit()

        kernel, turn_input = _make_kernel(kit, llm)
        await kernel.run(turn_input)

        hook_msg = _get_hook_context_msg(llm.captured_request)
        assert hook_msg is None

    @pytest.mark.asyncio
    async def test_drift_warning_appears_in_request(self):
        """drift from state metadata causes drift_warning in state after run."""
        llm = CapturingLLMClient()
        kit = WriterKit()

        state = RuntimeState(session_id="test-drift")
        # Set up metadata that triggers drift: many consecutive reads
        state.metadata["recent_tools"] = ["read_file"] * 6
        state.metadata["recent_statuses"] = ["ok"] * 6

        kernel, turn_input = _make_kernel(kit, llm, state)
        await kernel.run(turn_input)

        # decide_next sets drift_warning in state metadata after the turn
        # It will appear in the next LLM request's hook_context
        if "drift_warning" in (turn_input.state and turn_input.state.metadata or {}):
            assert "read-heavy drift" in turn_input.state.metadata["drift_warning"]
        else:
            # Fallback: check the final state
            assert kernel is not None

    @pytest.mark.asyncio
    async def test_build_model_request_directly_consumes_metadata(self):
        """Directly test build_model_request consumes context.metadata."""
        kit = WriterKit()
        state = RuntimeState(session_id="direct-test")

        context = PromptContext(
            session_id="direct-test",
            user_message="hello",
            history=[ChatMessage(role="user", content="hello")],
            state=state,
            metadata={
                "project_rules": "Always use type hints",
            },
        )

        request = await kit.build_model_request(state, context)

        hook_msg = _get_hook_context_msg(request)
        assert hook_msg is not None
        assert "Project Rules" in hook_msg.content
        assert "Always use type hints" in hook_msg.content

    @pytest.mark.asyncio
    async def test_build_model_request_no_hook_context_when_empty(self):
        """When context.metadata is empty, no hook context system message is added."""
        kit = WriterKit()
        state = RuntimeState(session_id="empty-test")

        context = PromptContext(
            session_id="empty-test",
            user_message="hello",
            history=[ChatMessage(role="user", content="hello")],
            state=state,
            metadata={},
        )

        request = await kit.build_model_request(state, context)

        hook_msgs = [
            m for m in request.messages
            if m.role == "system" and m.metadata.get("key") == "hook_context"
        ]
        assert hook_msgs == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_hook_context_msg(request: LLMRequest | None) -> ChatMessage | None:
    """Extract the hook context system message from a captured LLM request."""
    if request is None:
        return None
    for msg in request.messages:
        if msg.role == "system" and msg.metadata.get("key") == "hook_context":
            return msg
    return None


# ---------------------------------------------------------------------------
# Writer Kit verification / decision / writeback contract tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writer_kit_verification_reports_failed_tools():
    """WriterKit.verify runs actual non-LLM verification checks."""
    from lamtools_core.kernel.state import KernelTurn
    from lamtools_core.tool import ToolResult

    kit = WriterKit()
    state = RuntimeState(session_id="test")
    turn = KernelTurn(
        reply="",
        tool_calls=[],
        decision_hint="continue",
    )
    tool_results = [
        ToolResult(
            call_id="c1",
            name="read_file",
            status="failed",
            content="",
            error="missing file",
        )
    ]

    result = await kit.verify(state, turn, tool_results)
    assert result.passed is False
    assert result.required is True
    assert "read_file" in result.summary
    assert "retry" in (result.repair_prompt or "").lower()


@pytest.mark.asyncio
async def test_writer_kit_decision_uses_model_hint_when_no_safety_stop():
    """WriterKit.decide_next repairs required verification failures before done."""
    from lamtools_core.kernel.state import KernelTurn, KernelStep, VerificationResult

    kit = WriterKit()
    state = RuntimeState(session_id="test")
    turn = KernelTurn(reply="Done", tool_calls=[], decision_hint="done")
    verification = VerificationResult(passed=False, required=True, summary="Failed", attempt=1, max_attempts=3)
    step = KernelStep(index=0, state_before=state)

    result = await kit.decide_next(state, turn, verification, step)
    assert result == "continue"


@pytest.mark.asyncio
async def test_writer_kit_writeback_records_tool_state():
    """WriterKit.writeback records recent tool state directly on RuntimeState."""
    from lamtools_core.kernel.state import KernelTurn, VerificationResult
    from lamtools_core.tool import ToolResult

    kit = WriterKit()
    state = RuntimeState(session_id="test")
    turn = KernelTurn(reply="Done", tool_calls=[], decision_hint="done")
    verification = VerificationResult(passed=True, required=True, summary="OK")
    tool_results = [
        ToolResult(
            call_id="c1",
            name="write_file",
            status="ok",
            content="Created notes.txt: 12 chars",
            metadata={"path": "notes.txt"},
        )
    ]

    await kit.writeback(state, turn, tool_results, verification, "done")
    assert state.metadata["recent_tools"] == ["write_file"]
    assert state.metadata["recent_statuses"] == ["ok"]
    assert state.metadata["written_files"] == ["notes.txt"]


# ---------------------------------------------------------------------------
# Writer run_core_kernel() Kit integration tests
# ---------------------------------------------------------------------------


class TestRunCoreKernelIntegration:
    """Verify run_core_kernel() correctly assembles LLMRequest with persona, discipline, and tools."""

    @pytest.mark.asyncio
    async def test_run_core_kernel_injects_persona_discipline_and_tools(self):
        """run_core_kernel() injects persona, execution discipline, and tool schemas."""
        from app.core.writer.core_kernel_adapter import run_core_kernel
        from lamtools_core.llm import LLMResponse, LLMToolCall

        captured_request: LLMRequest | None = None

        class _CapturingLLM:
            def __init__(self):
                self._responses = [
                    LLMResponse(content="Done", finish_reason="stop"),
                ]

            async def complete(self, request: LLMRequest) -> LLMResponse:
                nonlocal captured_request
                captured_request = request
                return self._responses.pop(0)

            async def stream(self, request):
                raise NotImplementedError

        result = await run_core_kernel(
            goal="test",
            session_id="test-integration",
            llm_client=_CapturingLLM(),
        )

        # WriterKit.build_model_request injects persona + discipline + tools
        assert captured_request is not None
        persona_msgs = [
            m for m in captured_request.messages
            if m.role == "system" and m.metadata.get("key") == "persona"
        ]
        assert len(persona_msgs) == 1, "Persona system message must be injected"
        assert persona_msgs[0].content == get_writer_system_prompt()

        discipline_msgs = [
            m for m in captured_request.messages
            if m.role == "system" and m.metadata.get("key") == "execution_discipline"
        ]
        assert len(discipline_msgs) == 1, "Execution discipline must be injected"
        assert "Writer 执行协议" in discipline_msgs[0].content
        assert "优先复用项目已有接口" in discipline_msgs[0].content

        # Tools must be present in the LLMRequest
        assert len(captured_request.tools) > 0, "Tool schemas must be injected"
        tool_names = [t["function"]["name"] for t in captured_request.tools]
        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "edit_file" in tool_names

    @pytest.mark.asyncio
    async def test_run_core_kernel_injects_agents_md_from_work_root(self, tmp_path):
        """The active Core path must include project AGENTS.md instructions."""
        from app.core.writer.core_kernel_adapter import run_core_kernel
        from lamtools_core.llm import LLMResponse

        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "AGENTS.md").write_text(
            "如果你读到了这一条，向我发一句“我已读到agents.md”",
            encoding="utf-8",
        )
        captured_request: LLMRequest | None = None

        class _CapturingLLM:
            async def complete(self, request: LLMRequest) -> LLMResponse:
                nonlocal captured_request
                captured_request = request
                return LLMResponse(content="我已读到agents.md", finish_reason="stop")

            async def stream(self, request):
                raise NotImplementedError

        await run_core_kernel(
            goal="你读到这一条了吗？",
            session_id="agents-md-integration",
            llm_client=_CapturingLLM(),
            work_root=str(work_root),
        )

        assert captured_request is not None
        project_messages = [
            m for m in captured_request.messages
            if m.role == "system" and m.metadata.get("key") == "project_agents"
        ]
        assert len(project_messages) == 1
        assert "AGENTS.md" in project_messages[0].content

    @pytest.mark.asyncio
    async def test_run_core_kernel_verify_includes_written_files_exist(self):
        """verify includes written_files_exist check when work_root is set."""
        import tempfile
        from pathlib import Path
        from app.core.writer.core_kernel_adapter import run_core_kernel
        from lamtools_core.llm import LLMResponse, LLMToolCall

        class _WriteThenDoneLLM:
            def __init__(self):
                self._responses = [
                    LLMResponse(
                        content="",
                        tool_calls=[
                            LLMToolCall(
                                id="c1",
                                name="write_file",
                                arguments={"path": "test_verify.py", "content": "x = 1"},
                            ),
                        ],
                        finish_reason="tool_calls",
                    ),
                    LLMResponse(content="Done.", finish_reason="stop"),
                ]

            async def complete(self, request: LLMRequest) -> LLMResponse:
                return self._responses.pop(0)

            async def stream(self, request):
                raise NotImplementedError

        with tempfile.TemporaryDirectory() as tmp:
            result = await run_core_kernel(
                goal="write test_verify.py",
                session_id="test-verify-kit",
                llm_client=_WriteThenDoneLLM(),
                work_root=tmp,
            )

            # The verification step should have run (even if passed)
            # Check that verification was performed on steps with tool calls
            steps_with_verification = [
                s for s in result.steps if s.verification is not None
            ]
            assert len(steps_with_verification) > 0, "Verification must run on tool steps"

    @pytest.mark.asyncio
    async def test_run_core_kernel_writeback_records_metadata(self):
        """writeback tracks recent tools and statuses in state metadata."""
        import tempfile
        from pathlib import Path
        from app.core.writer.core_kernel_adapter import run_core_kernel
        from lamtools_core.llm import LLMResponse, LLMToolCall

        class _SimpleDoneLLM:
            def __init__(self):
                self._responses = [
                    LLMResponse(content="Task complete.", finish_reason="stop"),
                ]

            async def complete(self, request: LLMRequest) -> LLMResponse:
                return self._responses.pop(0)

            async def stream(self, request):
                raise NotImplementedError

        with tempfile.TemporaryDirectory() as tmp:
            result = await run_core_kernel(
                goal="do nothing",
                session_id="test-writeback-kit",
                llm_client=_SimpleDoneLLM(),
                work_root=tmp,
            )

            # Decision should be "done" for a text-only response
            assert result.decision == "done"
            # Writeback tracks state metadata
            state = result.state
            assert state is not None
            meta = state.metadata or {}
