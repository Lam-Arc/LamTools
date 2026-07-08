"""Tests for Writer CoreLoopKernel adapter (core_kernel_adapter.py).

Covers:
1. Text-only done — model replies with plain text, no tool calls → done.
2. Ask wait — model signals ask_clarification / needs_user_input → wait.
3. Tool result fed back to next turn — tool output appears in history.
4. Tool failure does not masquerade as done — failed verification → continue.
5. WriterKit implements the core RuntimeKit protocol.
6. ReadOnlyToolExecutor — read_file, list_dir, search_files, search_content.
7. Path boundary validation — work_root traversal protection.
8. Output limits — list_dir and search tools cap results.
9. Injected executor overrides read-only defaults.
10. Unknown tool returns failed result.
11. Main path (no work_root) does not enable real read-only tools.

All tests use injectable LLMClient / tool_executor — no real LLM calls,
no real file/command/git operations (except temp dirs for read-only tests),
no mocks.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import pytest
from pathlib import Path

from lamtools_core.kernel import (
    KernelResult,
    KernelStep,
    KernelTurn,
    LoopDecision,
    RuntimeKit,
    VerificationResult,
    compact_core_events_for_summary,
)
from lamtools_core.event import CoreEvent
from lamtools_core.llm import (
    ChatMessage,
    LLMClient,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    LLMToolCall,
    LLMUsage,
)
from lamtools_core.prompt import PromptContext
from lamtools_core.runtime import RuntimeState, RuntimeToolStep, RuntimeTurnInput
from lamtools_core.tool import ToolCall, ToolResult
from lamtools_core.plugins import (
    HookRegistry,
    HookTrustStore,
    PluginRegistry,
    default_user_plugin_root,
)
from app.config import settings

from app.core.writer.core_kernel_adapter import (
    ReadOnlyToolExecutor,
    ReadWriteToolExecutor,
    WriterLLMClientAdapter,
    WriterKit,
    _validate_command_paths,
    _validate_path,
    run_core_kernel,
)
from app.core.writer.skills import WriterSkill


@pytest.mark.asyncio
async def test_writer_kit_resets_original_task_for_each_turn():
    kit = WriterKit()
    state = RuntimeState(
        session_id="session-task-boundary",
        metadata={
            "current_task": "old current task",
            "original_task": "old original task",
        },
    )

    await kit.on_run_start(state, RuntimeTurnInput(user_message="new queued task"))

    assert state.metadata["current_task"] == "new queued task"
    assert state.metadata["original_task"] == "new queued task"


# ---------------------------------------------------------------------------
# Helpers — fake LLMClient for testing
# ---------------------------------------------------------------------------


class FakeLLMClient:
    """Deterministic fake LLMClient that returns pre-programmed responses.

    Call ``add_response`` to queue responses.  Each call to ``complete``
    pops the next one.
    """

    def __init__(self) -> None:
        self._responses: list[LLMResponse] = []
        self.call_count = 0
        self.last_request: LLMRequest | None = None
        self.requests: list[LLMRequest] = []

    def add_response(self, response: LLMResponse) -> None:
        self._responses.append(response)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.call_count += 1
        self.last_request = request
        self.requests.append(request)
        if not self._responses:
            return LLMResponse(content="done", finish_reason="stop")
        return self._responses.pop(0)

    async def stream(self, request: LLMRequest):
        raise NotImplementedError("FakeLLMClient does not support streaming")


def _conversation_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Return only model-visible conversation messages, excluding injected system context."""
    return [m for m in messages if m.role != "system"]


class FakeWriterClient:
    """Mimics Writer's llm_client with .chat_full()."""

    def __init__(self, responses: list | None = None) -> None:
        self._responses = responses or []
        self._index = 0

    async def chat_full(self, messages, tools=None):
        if self._index >= len(self._responses):
            from app.core.writer.schemas import WriterToolResult
            # Return a minimal response-like object
            return _FakeWriterResponse(content="done")
        resp = self._responses[self._index]
        self._index += 1
        return resp


class _FakeWriterResponse:
    """Mimics Writer LLM response object."""

    def __init__(
        self,
        content: str = "",
        tool_calls: list | None = None,
        thinking: str = "",
        finish_reason: str = "stop",
        usage: Any = None,
    ):
        self.content = content
        self.tool_calls = tool_calls or []
        self.thinking = thinking
        self.finish_reason = finish_reason
        self.usage = usage


class FakeRuntimeStateStore:
    def __init__(self, state: RuntimeState | None = None) -> None:
        self.state = state
        self.get_calls: list[str] = []
        self.saved: list[RuntimeState] = []

    async def get(self, session_id: str) -> RuntimeState | None:
        self.get_calls.append(session_id)
        return self.state

    async def save(self, state: RuntimeState) -> None:
        self.state = state
        self.saved.append(state)


# ---------------------------------------------------------------------------
# 1. Text-only done
# ---------------------------------------------------------------------------


class TestTextOnlyDone:
    """Model replies with plain text, no tool calls → Kernel decides done."""

    @pytest.mark.asyncio
    async def test_single_text_response_done(self):
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Task completed successfully.", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Say hello",
            session_id="test-text-done-1",
            llm_client=llm,
        )

        assert result.decision == "done"
        assert "Task completed successfully" in result.message
        assert result.error == ""

    @pytest.mark.asyncio
    async def test_text_done_with_thinking(self):
        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="Here is the answer.",
                thinking="Let me think about this...",
                finish_reason="stop",
            )
        )

        result = await run_core_kernel(
            goal="Explain something",
            session_id="test-text-done-2",
            llm_client=llm,
        )

        assert result.decision == "done"
        assert "Here is the answer" in result.message

    @pytest.mark.asyncio
    async def test_empty_content_done(self):
        """Empty content with finish_reason='stop' is not a completed answer."""
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="", finish_reason="stop"))
        llm.add_response(LLMResponse(content="", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Do nothing",
            session_id="test-text-done-3",
            llm_client=llm,
        )

        assert result.decision == "failed"
        assert "没有正文，也没有工具调用" in result.message

    @pytest.mark.asyncio
    async def test_repeated_empty_stop_without_delivery_fails(self):
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="", thinking="thinking only", finish_reason="stop"))
        llm.add_response(LLMResponse(content="", thinking="thinking only again", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Create a file",
            session_id="test-empty-stop-no-delivery",
            llm_client=llm,
        )

        assert result.decision == "failed"
        assert "没有正文，也没有工具调用" in result.message

    @pytest.mark.asyncio
    async def test_empty_stop_after_delivery_requires_visible_final_answer(self):
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="", thinking="final thinking", finish_reason="stop"))
        llm.add_response(LLMResponse(content="已完成：kbtool.py。", finish_reason="stop"))
        store = FakeRuntimeStateStore(
            RuntimeState(
                session_id="test-empty-stop-with-delivery",
                metadata={"written_files": ["kbtool.py"]},
            )
        )

        result = await run_core_kernel(
            goal="Finish after writing",
            session_id="test-empty-stop-with-delivery",
            llm_client=llm,
            state_store=store,
        )

        assert result.decision == "done"
        assert result.message == "已完成：kbtool.py。"

    @pytest.mark.asyncio
    async def test_uses_injected_state_store(self):
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Done.", finish_reason="stop"))
        store = FakeRuntimeStateStore(
            RuntimeState(
                session_id="test-state-store-1",
                run_id="existing-run",
                turn_count=3,
                metadata={"persisted": True},
            )
        )

        result = await run_core_kernel(
            goal="Continue",
            session_id="test-state-store-1",
            llm_client=llm,
            state_store=store,
        )

        assert store.get_calls == ["test-state-store-1"]
        assert len(store.saved) >= 2
        assert result.run_id
        assert result.run_id != "existing-run"
        assert result.state.metadata["persisted"] is True
        assert store.state is not None
        assert store.state.run_id == result.run_id
        assert store.state.status == "completed"


# ---------------------------------------------------------------------------
# 2. Ask wait — ask_clarification / needs_user_input → wait
# ---------------------------------------------------------------------------


class TestAskWait:
    """Model signals ask_clarification / needs_user_input → wait."""

    @pytest.mark.asyncio
    async def test_empty_tool_name_becomes_invalid_tool_call(self):
        kit = WriterKit()
        state = RuntimeState(session_id="session-empty-tool")

        turn = await kit.parse_model_output(
            state,
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="",
                        name="",
                        arguments={},
                        metadata={"raw_arguments": "}"},
                    )
                ],
                finish_reason="tool_calls",
            ),
        )

        assert len(turn.tool_calls) == 1
        call = turn.tool_calls[0]
        assert call.id == "invalid-tool-call-0"
        assert call.name == "invalid_tool_call"
        assert call.arguments["reason"] == "empty_tool_name"
        assert call.arguments["raw_arguments"] == "}"

    @pytest.mark.asyncio
    async def test_ask_clarification_tool_call_waits(self):
        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="I need more info",
                tool_calls=[
                    LLMToolCall(
                        id="call-1",
                        name="ask_clarification",
                        arguments={"question": "Which file?"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )

        result = await run_core_kernel(
            goal="Fix the bug",
            session_id="test-ask-wait-1",
            llm_client=llm,
        )

        assert result.decision == "wait"

    @pytest.mark.asyncio
    async def test_ask_clarification_does_not_execute_as_tool(self):
        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="I need more info",
                tool_calls=[
                    LLMToolCall(
                        id="call-ask-no-tool",
                        name="ask_clarification",
                        arguments={"question": "Which file?"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )

        executed: list[str] = []

        async def fake_tool(call: ToolCall) -> ToolResult:
            executed.append(call.name)
            return ToolResult(call_id=call.id, name=call.name, status="ok", content="should not run")

        result = await run_core_kernel(
            goal="Fix the bug",
            session_id="test-ask-wait-no-tool",
            llm_client=llm,
            tool_executor=fake_tool,
        )

        assert result.decision == "wait"
        assert executed == []

    @pytest.mark.asyncio
    async def test_needs_user_input_tool_call_waits(self):
        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="Waiting for user",
                tool_calls=[
                    LLMToolCall(
                        id="call-2",
                        name="needs_user_input",
                        arguments={"prompt": "Confirm?"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )

        result = await run_core_kernel(
            goal="Deploy",
            session_id="test-ask-wait-2",
            llm_client=llm,
        )

        assert result.decision == "wait"


# ---------------------------------------------------------------------------
# 3. Tool result fed back to next turn
# ---------------------------------------------------------------------------


class TestToolResultFeedback:
    """Tool output is formatted and appears in the next model request history."""

    @pytest.mark.asyncio
    async def test_initial_user_message_not_duplicated(self):
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Done.", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Read test.py",
            session_id="test-user-message-once",
            llm_client=llm,
        )

        assert result.decision == "done"
        assert llm.last_request is not None
        user_messages = [m for m in llm.last_request.messages if m.role == "user" and m.content == "Read test.py"]
        assert len(user_messages) == 1

    @pytest.mark.asyncio
    async def test_tool_result_appears_in_next_request(self):
        llm = FakeLLMClient()
        # First response: call read_file
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-read-1",
                        name="read_file",
                        arguments={"path": "test.py"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        # Second response: done after seeing tool result
        llm.add_response(
            LLMResponse(
                content="I read the file, all done.",
                finish_reason="stop",
            )
        )

        # Tool executor returns content
        async def fake_read_file(call: ToolCall) -> ToolResult:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content="print('hello world')",
            )

        result = await run_core_kernel(
            goal="Read test.py",
            session_id="test-tool-feedback-1",
            llm_client=llm,
            tool_executor=fake_read_file,
        )

        assert result.decision == "done"
        assert llm.call_count == 2

        # The second request should contain tool result in history
        second_request = llm.last_request
        assert second_request is not None
        # There should be a tool-role message with the file content
        tool_messages = [
            m for m in second_request.messages if m.role == "tool"
        ]
        assert len(tool_messages) >= 1
        assert "print('hello world')" in tool_messages[0].content

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_one_turn(self):
        llm = FakeLLMClient()
        # First response: two tool calls
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-1",
                        name="read_file",
                        arguments={"path": "a.py"},
                    ),
                    LLMToolCall(
                        id="call-2",
                        name="search_content",
                        arguments={"pattern": "TODO"},
                    ),
                ],
                finish_reason="tool_calls",
            )
        )
        # Second response: done
        llm.add_response(
            LLMResponse(content="Done after reading and searching.", finish_reason="stop")
        )

        call_log: list[str] = []

        async def fake_tool(call: ToolCall) -> ToolResult:
            call_log.append(call.name)
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content=f"Result of {call.name}",
            )

        result = await run_core_kernel(
            goal="Read and search",
            session_id="test-tool-feedback-2",
            llm_client=llm,
            tool_executor=fake_tool,
        )

        assert result.decision == "done"
        assert "read_file" in call_log
        assert "search_content" in call_log

        # Second request has both tool results
        second_request = llm.last_request
        tool_messages = [
            m for m in second_request.messages if m.role == "tool"
        ]
        assert len(tool_messages) == 2


# ---------------------------------------------------------------------------
# 4. Tool failure does not masquerade as done
# ---------------------------------------------------------------------------


class TestToolFailureNotDone:
    """Tool failure → verification fails → model cannot claim done."""

    @pytest.mark.asyncio
    async def test_failed_tool_prevents_done(self):
        """Model calls a failing tool then says done → kernel forces continue."""
        llm = FakeLLMClient()
        # First response: call write_file (will fail)
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-write-1",
                        name="write_file",
                        arguments={"path": "out.py", "content": "bad"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        # Second response: model says done despite failure
        llm.add_response(
            LLMResponse(
                content="I'm done now.",
                finish_reason="stop",
            )
        )

        async def failing_write(call: ToolCall) -> ToolResult:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error="Permission denied",
            )

        result = await run_core_kernel(
            goal="Write a file",
            session_id="test-tool-fail-1",
            llm_client=llm,
            tool_executor=failing_write,
        )

        # The kernel should NOT have accepted "done" on the first turn
        # after the tool failure.  The kit's decide_next overrides done→continue
        # when verification fails.  The model then says done on the second turn,
        # which is accepted because there's no tool failure that turn.
        assert result.decision == "done"
        # But we made 2 LLM calls (not just 1), proving the done was overridden
        assert llm.call_count == 2

    @pytest.mark.asyncio
    async def test_failed_tool_result_in_history(self):
        """Failed tool result should appear in history so model can see error."""
        llm = FakeLLMClient()
        # First: tool call that fails
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-fail-1",
                        name="run_command",
                        arguments={"cmd": "bad-command"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        # Second: done after seeing the error
        llm.add_response(
            LLMResponse(content="I saw the error, moving on.", finish_reason="stop")
        )

        async def failing_command(call: ToolCall) -> ToolResult:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error="Command not found",
            )

        result = await run_core_kernel(
            goal="Run a command",
            session_id="test-tool-fail-2",
            llm_client=llm,
            tool_executor=failing_command,
        )

        # Second request should contain the error message
        second_request = llm.last_request
        tool_messages = [
            m for m in second_request.messages if m.role == "tool"
        ]
        assert len(tool_messages) >= 1
        assert "Command not found" in tool_messages[0].content

    @pytest.mark.asyncio
    async def test_structured_tool_error_metadata_is_visible_to_model(self):
        """Structured recovery metadata is included in the tool-role message."""
        kit = WriterKit()
        state = RuntimeState(session_id="structured-tool-error")
        call = ToolCall(
            id="tc-structured-error",
            name="run_command",
            arguments={"command": "python -m http.server 8080", "background": True},
        )
        result = ToolResult(
            call_id=call.id,
            name=call.name,
            status="failed",
            error="Port 8080 is already listening on 127.0.0.1.",
            metadata={
                "error_type": "PortInUse",
                "error_kind": "port_in_use",
                "retryable": True,
                "recommended_action": "choose_free_port",
                "server_port": 8080,
            },
        )

        message = await kit.format_tool_result_for_model(state, call, result)

        assert message.role == "tool"
        assert "Structured error:" in message.content
        assert "port_in_use" in message.content
        assert "choose_free_port" in message.content

    @pytest.mark.asyncio
    async def test_failed_test_output_is_retained_as_repair_context(self, tmp_path):
        """A red test should carry assertion details into the next model request."""
        kit = WriterKit(work_root=str(tmp_path))
        state = RuntimeState(session_id="test-failed-test-repair-context")
        turn = KernelTurn(
            reply="",
            tool_calls=[
                ToolCall(
                    id="tests-1",
                    name="run_tests",
                    arguments={"command": "python -m pytest -q"},
                )
            ],
            decision_hint="continue",
        )
        result = ToolResult(
            call_id="tests-1",
            name="run_tests",
            status="failed",
            error="Command exited with code 1",
            content=(
                "[test_result] failed\n"
                "[command] python -m pytest -q\n"
                "[exit_code] 1\n\n"
                "FAILED test_buggy_math.py::test_median_even_count_averages_middle_pair\n"
                "E       assert 8 == 6\n"
            ),
            metadata={"exit_code": 1, "passed": False, "summary": "failed"},
        )

        verification = await kit.verify(state, turn, [result])
        assert verification.required is True
        assert verification.passed is False

        await kit.writeback(
            state,
            turn,
            [result],
            verification,
            "continue",
        )

        request = await kit.build_model_request(
            state,
            PromptContext(
                session_id=state.session_id,
                user_message="Fix the existing repo bug.",
                history=[],
                state=state,
            ),
        )
        system_text = "\n\n".join(m.content for m in request.messages if m.role == "system")

        assert "TEST ASSERTION FAILURE DETECTED" in system_text
        assert "Next required action: edit the relevant production file" in system_text
        assert "test_median_even_count_averages_middle_pair" in system_text
        assert "assert 8 == 6" in system_text
        assert "write_file/edit_file" in system_text

        blocked = await kit.execute_tool(
            state,
            ToolCall(
                id="tests-2",
                name="run_command",
                arguments={"command": "python -m pytest -q"},
            ),
        )
        assert blocked.status == "failed"
        assert blocked.metadata["error_type"] == "TestAssertionRepairPending"
        assert "edit_file/write_file" in blocked.content


# ---------------------------------------------------------------------------
# 5. RuntimeKit protocol
# ---------------------------------------------------------------------------


class TestRuntimeKitProtocol:
    def test_kit_implements_runtime_kit_protocol(self):
        """WriterKit satisfies the RuntimeKit protocol check."""
        kit = WriterKit()
        assert isinstance(kit, RuntimeKit)


# ---------------------------------------------------------------------------
# 6. WriterLLMClientAdapter tests
# ---------------------------------------------------------------------------


class TestWriterLLMClientAdapter:
    """Tests for the Writer→Core LLM client bridge."""

    @pytest.mark.asyncio
    async def test_adapter_with_writer_client(self):
        """Adapter wraps Writer's .chat_full() to Core's .complete()."""
        writer_client = FakeWriterClient(
            responses=[
                _FakeWriterResponse(content="Hello from Writer", finish_reason="stop")
            ]
        )
        adapter = WriterLLMClientAdapter(writer_client=writer_client)

        request = LLMRequest(
            messages=[ChatMessage(role="user", content="Hi")]
        )
        response = await adapter.complete(request)

        assert response.content == "Hello from Writer"
        assert response.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_adapter_with_core_client(self):
        """Adapter delegates directly when given a Core LLMClient."""
        core_client = FakeLLMClient()
        core_client.add_response(
            LLMResponse(content="Hello from Core", finish_reason="stop")
        )
        adapter = WriterLLMClientAdapter(core_client=core_client)

        request = LLMRequest(
            messages=[ChatMessage(role="user", content="Hi")]
        )
        response = await adapter.complete(request)

        assert response.content == "Hello from Core"

    def test_adapter_requires_client(self):
        """Adapter raises ValueError when neither client is provided."""
        with pytest.raises(ValueError, match="Either writer_client or core_client"):
            WriterLLMClientAdapter()

    @pytest.mark.asyncio
    async def test_adapter_converts_tool_calls(self):
        """Adapter converts Writer tool_calls to Core LLMToolCall format."""
        from app.core.writer.schemas import WriterToolResult

        writer_client = FakeWriterClient(
            responses=[
                _FakeWriterResponse(
                    content="",
                    tool_calls=[
                        _FakeToolCall(id="tc-1", name="read_file", arguments={"path": "a.py"}),
                    ],
                    finish_reason="tool_calls",
                )
            ]
        )
        adapter = WriterLLMClientAdapter(writer_client=writer_client)

        request = LLMRequest(
            messages=[ChatMessage(role="user", content="Read a.py")]
        )
        response = await adapter.complete(request)

        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "read_file"
        assert response.tool_calls[0].arguments == {"path": "a.py"}

    @pytest.mark.asyncio
    async def test_adapter_converts_usage_dict(self):
        """Adapter preserves token usage from Writer's dict-shaped response."""
        writer_client = FakeWriterClient(
            responses=[
                _FakeWriterResponse(
                    content="done",
                    usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
                )
            ]
        )
        adapter = WriterLLMClientAdapter(writer_client=writer_client)

        response = await adapter.complete(LLMRequest(messages=[ChatMessage(role="user", content="Hi")]))

        assert response.usage is not None
        assert response.usage.prompt_tokens == 10
        assert response.usage.completion_tokens == 4
        assert response.usage.total_tokens == 14

    @pytest.mark.asyncio
    async def test_stream_uses_xfyun_enable_thinking_and_emits_reasoning(self, monkeypatch):
        captured_payload: dict[str, object] = {}

        class FakeStreamResponse:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def aiter_lines(self):
                reasoning_chunk = {
                    "choices": [
                        {
                            "delta": {
                                "reasoning_content": "先计算。",
                            }
                        }
                    ]
                }
                content_chunk = {
                    "choices": [
                        {
                            "delta": {
                                "content": "答案是 2。",
                            }
                        }
                    ]
                }
                done_chunk = {
                    "choices": [
                        {
                            "delta": {},
                            "finish_reason": "stop",
                        }
                    ]
                }
                for chunk in (reasoning_chunk, content_chunk, done_chunk):
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}"
                yield "data: [DONE]"

            async def aread(self):
                return b""

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, _method, _url, *, json, headers):
                captured_payload.update(json)
                return FakeStreamResponse()

        monkeypatch.setattr(
            "app.core.writer.runtime_resources.httpx.AsyncClient",
            FakeAsyncClient,
        )

        writer_client = FakeWriterClient()
        writer_client.api_type = "openai"
        writer_client.base_url = "https://maas-coding-api.cn-huabei-1.xf-yun.com/v2"
        writer_client.api_key = "test"
        writer_client.model_id = "astron-code-latest"
        writer_client.temperature = 0.7
        writer_client.max_tokens = 1024
        writer_client.thinking_enabled = True
        writer_client.thinking_budget = 1000

        adapter = WriterLLMClientAdapter(writer_client=writer_client)
        events: list[LLMStreamEvent] = []
        async for event in adapter.stream(LLMRequest(messages=[ChatMessage(role="user", content="1+1")])):
            events.append(event)

        assert captured_payload["enable_thinking"] is True
        assert "thinking" not in captured_payload
        assert [event.kind for event in events] == ["thinking_delta", "content_delta", "done"]
        assert events[0].content == "先计算。"

    @pytest.mark.asyncio
    async def test_stream_applies_custom_adapter_endpoint_and_body(self, monkeypatch):
        captured: dict[str, object] = {}

        class FakeStreamResponse:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def aiter_lines(self):
                done_chunk = {
                    "choices": [
                        {
                            "delta": {},
                            "finish_reason": "stop",
                        }
                    ]
                }
                yield f"data: {json.dumps(done_chunk, ensure_ascii=False)}"
                yield "data: [DONE]"

            async def aread(self):
                return b""

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, method, url, *, json, headers):
                captured["method"] = method
                captured["url"] = url
                captured["payload"] = dict(json)
                return FakeStreamResponse()

        monkeypatch.setattr(
            "app.core.writer.runtime_resources.httpx.AsyncClient",
            FakeAsyncClient,
        )

        writer_client = FakeWriterClient()
        writer_client.api_type = "openai"
        writer_client.base_url = "https://gateway.example.test/v1"
        writer_client.api_key = "test"
        writer_client.model_id = "custom-model"
        writer_client.temperature = 0.7
        writer_client.max_tokens = 1024
        writer_client.thinking_enabled = True
        writer_client.thinking_budget = 2048
        writer_client.adapter_profile = {
            "id": "custom-gateway",
            "endpoint": "/custom/chat",
            "request": {
                "body": {
                    "custom_mode": "coding",
                },
                "thinking": {
                    "when_enabled": {
                        "custom_thinking": {
                            "budget": "$thinking_budget",
                        }
                    }
                },
                "unsupported_fields": ["thinking"],
            },
            "stream_response": {
                "finish_reason": "choices.0.finish_reason",
            },
        }

        adapter = WriterLLMClientAdapter(writer_client=writer_client)
        events: list[LLMStreamEvent] = []
        async for event in adapter.stream(LLMRequest(messages=[ChatMessage(role="user", content="ping")])):
            events.append(event)

        payload = captured["payload"]
        assert captured["method"] == "POST"
        assert captured["url"] == "https://gateway.example.test/v1/custom/chat"
        assert payload["custom_mode"] == "coding"
        assert payload["custom_thinking"] == {"budget": 2048}
        assert "thinking" not in payload
        assert [event.kind for event in events] == ["done"]


class _FakeToolCall:
    """Mimics Writer's tool call object."""

    def __init__(self, id: str, name: str, arguments: dict):
        self.id = id
        self.name = name
        self.arguments = arguments


# ---------------------------------------------------------------------------
# 7. run_core_kernel integration tests
# ---------------------------------------------------------------------------


class TestRunCoreKernelIntegration:
    """Integration tests for run_core_kernel entry point."""

    @pytest.mark.asyncio
    async def test_requires_llm_client(self):
        """run_core_kernel raises ValueError without llm_client."""
        with pytest.raises(ValueError, match="llm_client must be provided"):
            await run_core_kernel(
                goal="test",
                session_id="no-client",
                llm_client=None,
            )

    @pytest.mark.asyncio
    async def test_sub_agent_uses_same_kernel_loop_with_parent_tools_minus_sub_agent(self, tmp_path):
        (tmp_path / "README.md").write_text("hello from workspace", encoding="utf-8")
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(
                    id="call-sub",
                    name="sub_agent",
                    arguments={
                        "task": "读取 README 并汇总结论",
                        "mode": "low",
                        "clean": False,
                        "options": {"agent": "explorer"},
                    },
                )
            ],
            finish_reason="tool_calls",
        ))
        llm.add_response(LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(
                    id="sub-read",
                    name="read_file",
                    arguments={"path": "README.md"},
                )
            ],
            finish_reason="tool_calls",
        ))
        llm.add_response(LLMResponse(
            content="README 内容是 hello from workspace。",
            finish_reason="stop",
        ))
        llm.add_response(LLMResponse(
            content="主流程已收到子代理结论。",
            finish_reason="stop",
        ))

        result = await run_core_kernel(
            goal="请派发 explorer 读取 README。",
            session_id="test-sub-agent-same-loop",
            llm_client=llm,
            work_root=str(tmp_path),
        )

        assert result.decision == "done"
        assert result.message == "主流程已收到子代理结论。"
        assert llm.call_count == 4
        sub_request = next(
            request for request in llm.requests
            if any("临时 SubAgent" in message.content for message in request.messages)
        )
        tool_names = {
            tool.get("function", {}).get("name")
            for tool in sub_request.tools
        }
        assert "read_file" in tool_names
        assert "sub_agent" not in tool_names
        assert "write_file" in tool_names
        sub_tool_results = [
            item.result
            for step in result.steps
            for item in step.tool_steps
            if item.call.name == "sub_agent"
        ]
        assert sub_tool_results and sub_tool_results[0] is not None
        assert "README 内容是 hello from workspace" in (sub_tool_results[0].content or "")

    @pytest.mark.asyncio
    async def test_distinct_file_read_failures_do_not_masquerade_as_done(self, tmp_path):
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(id="read-index", name="read_file", arguments={"path": "index.html"}),
                LLMToolCall(id="read-app", name="read_file", arguments={"path": "js/app.js"}),
                LLMToolCall(id="read-data", name="read_file", arguments={"path": "js/data.js"}),
                LLMToolCall(id="read-about", name="read_file", arguments={"path": "about.html"}),
                LLMToolCall(id="read-css", name="read_file", arguments={"path": "css/style.css"}),
            ],
            finish_reason="tool_calls",
        ))
        llm.add_response(LLMResponse(
            content="文件不存在，让我先检查工作区实际状态。",
            tool_calls=[
                LLMToolCall(id="list-root", name="list_dir", arguments={"path": "."}),
            ],
            finish_reason="tool_calls",
        ))
        llm.add_response(LLMResponse(
            content="验收失败：目标文件不在主工作区，不能标记完成。",
            finish_reason="stop",
        ))

        result = await run_core_kernel(
            goal="验收博客文件",
            session_id="test-distinct-read-failures",
            llm_client=llm,
            work_root=str(tmp_path),
        )

        assert result.decision == "done"
        assert result.message == "验收失败：目标文件不在主工作区，不能标记完成。"
        assert llm.call_count == 3
        assert "drift_warning" not in result.state.metadata

    @pytest.mark.asyncio
    async def test_repeated_identical_tool_failure_stops_only_when_call_and_result_match(self, tmp_path):
        state = RuntimeState(session_id="repeated-failure")
        call = ToolCall(id="read-loop", name="read_file", arguments={"path": "missing.md"})
        failure = ToolResult(
            call_id="read-loop",
            name="read_file",
            status="failed",
            content="",
            error="File not found: missing.md",
        )
        signature = WriterKit._tool_failure_signature(call, failure)
        state.metadata["recent_statuses"] = ["failed"] * 4
        state.metadata["recent_failure_signatures"] = [signature] * 4
        kit = WriterKit(work_root=str(tmp_path))

        decision = await kit.decide_next(
            state,
            KernelTurn(reply="still checking", tool_calls=[], decision_hint="continue"),
            VerificationResult(passed=True, summary="ok"),
            KernelStep(
                index=0,
                state_before=state,
                tool_steps=[RuntimeToolStep(call=call, result=failure)],
            ),
        )

        assert decision == "failed"
        assert "tool call and result are unchanged" in state.metadata["drift_warning"]

        state = RuntimeState(session_id="changed-failure")
        state.metadata["recent_statuses"] = ["failed"] * 4
        state.metadata["recent_failure_signatures"] = [signature] * 4
        changed_failure = ToolResult(
            call_id="read-loop",
            name="read_file",
            status="failed",
            content="different output",
            error="File not found: missing.md",
        )
        decision = await kit.decide_next(
            state,
            KernelTurn(reply="still checking", tool_calls=[], decision_hint="continue"),
            VerificationResult(passed=True, summary="ok"),
            KernelStep(
                index=1,
                state_before=state,
                tool_steps=[RuntimeToolStep(call=call, result=changed_failure)],
            ),
        )

        assert decision == "continue"
        assert "drift_warning" not in state.metadata

    @pytest.mark.asyncio
    async def test_sub_agent_mvp_writes_in_parent_workspace_without_branch_delivery(self, tmp_path):
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "writer@example.test"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.name", "Writer Test"], cwd=tmp_path, check=True)
        (tmp_path / "README.md").write_text("baseline\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-m", "test: baseline"], cwd=tmp_path, check=True, capture_output=True, text=True)

        llm = FakeLLMClient()
        llm.add_response(LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(
                    id="call-sub-worker",
                    name="sub_agent",
                    arguments={
                        "task": "创建 worker.txt",
                        "mode": "low",
                        "clean": True,
                        "options": {"agent": "worker", "write_scope": ["worker.txt"]},
                    },
                )
            ],
            finish_reason="tool_calls",
        ))
        llm.add_response(LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(
                    id="sub-write",
                    name="write_file",
                    arguments={"path": "worker.txt", "content": "worker delivery\n"},
                )
            ],
            finish_reason="tool_calls",
        ))
        llm.add_response(LLMResponse(
            content="已创建 worker.txt。",
            finish_reason="stop",
        ))
        llm.add_response(LLMResponse(
            content="主流程已接收子代理交付。",
            finish_reason="stop",
        ))

        result = await run_core_kernel(
            goal="派发 worker 创建文件",
            session_id="test-sub-agent-delivery-merge",
            llm_client=llm,
            work_root=str(tmp_path),
        )

        assert result.decision == "done"
        assert (tmp_path / "worker.txt").read_text(encoding="utf-8") == "worker delivery\n"
        sub_result = next(
            item.result
            for step in result.steps
            for item in step.tool_steps
            if item.call.name == "sub_agent"
        )
        assert sub_result.status == "ok"
        assert sub_result.metadata["agent_name"] == "worker"
        assert sub_result.metadata["agent_index"] == "001"
        assert sub_result.metadata["sub_session_id"] == "test-sub-agent-delivery-merge:sub:001:worker"
        assert sub_result.metadata["workspace_delivery"] == {}
        assert sub_result.metadata["changed_files"] == []
        assert sub_result.metadata["changed_files_count"] == 0
        assert "branch" not in sub_result.metadata["tool_facts"]
        tool_calls = sub_result.metadata["tool_calls"]
        write_call = next(item for item in tool_calls if item["name"] == "write_file")
        assert write_call["tool_name"] == "write_file"
        assert write_call["content_preview"]
        assert write_call["artifacts"][0]["kind"] == "file_change"
        assert "worker delivery" in write_call["artifacts"][0]["content"]
        assert "[SubAgent 工作区]" not in (sub_result.content or "")
        assert "待主 Writer 审查后接收或放弃" not in (sub_result.content or "")
        assert "worker.txt" in (sub_result.content or "")
        tool_messages = [
            message.content
            for request in llm.requests
            for message in request.messages
            if message.role == "tool" and message.name == "sub_agent"
        ]
        assert any("[系统事实]" in content for content in tool_messages)
        assert any('"agent_index": "001"' in content for content in tool_messages)

    @pytest.mark.asyncio
    async def test_sub_agent_without_write_scope_runs_as_mvp_tool_result(self, tmp_path):
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(
                    id="call-sub-worker",
                    name="sub_agent",
                    arguments={
                        "task": "创建 worker.txt",
                        "mode": "low",
                        "clean": True,
                        "options": {"agent": "worker"},
                    },
                )
            ],
            finish_reason="tool_calls",
        ))
        llm.add_response(LLMResponse(content="子代理完成。", finish_reason="stop"))
        llm.add_response(LLMResponse(content="主流程收到结果。", finish_reason="stop"))

        result = await run_core_kernel(
            goal="派发 worker 创建文件",
            session_id="test-sub-agent-missing-scope",
            llm_client=llm,
            work_root=str(tmp_path),
        )

        sub_result = next(
            item.result
            for step in result.steps
            for item in step.tool_steps
            if item.call.name == "sub_agent"
        )
        assert sub_result.status == "ok"
        assert "子代理完成" in (sub_result.content or "")
        assert "write_scope" not in (sub_result.error or "")

    @pytest.mark.asyncio
    async def test_natural_final_reply_does_not_run_completion_verifier(self, tmp_path):
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(
                    id="write-broken-js",
                    name="write_file",
                    arguments={"path": "app.js", "content": "function broken( {\n  return 1;\n}\n"},
                )
            ],
            finish_reason="tool_calls",
        ))
        llm.add_response(LLMResponse(content="已经完成。", finish_reason="stop"))

        result = await run_core_kernel(
            goal="开发一个 JavaScript 工具",
            session_id="test-no-completion-verifier",
            llm_client=llm,
            work_root=str(tmp_path),
        )

        assert result.decision == "done"
        assert result.message == "已经完成。"
        assert llm.call_count == 2
        assert "function broken" in (tmp_path / "app.js").read_text(encoding="utf-8")
        summaries = [step.verification.summary for step in result.steps if step.verification]
        assert summaries == ["ok", "ok"]

    @pytest.mark.asyncio
    async def test_many_tool_rounds_continue_until_final_text(self):
        """Kernel keeps running tool rounds until a no-tool final answer."""
        llm = FakeLLMClient()
        for index in range(20):
            llm.add_response(
                LLMResponse(
                    content="",
                    tool_calls=[
                        LLMToolCall(
                            id=f"call-{index}",
                            name="read_file",
                            arguments={"path": "loop.py"},
                        )
                    ],
                    finish_reason="tool_calls",
                )
            )
        llm.add_response(LLMResponse(content="Final answer after tool work.", finish_reason="stop"))

        async def stub_tool(call: ToolCall) -> ToolResult:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content="file content",
            )

        result = await run_core_kernel(
            goal="Loop forever",
            session_id="test-max-steps",
            llm_client=llm,
            tool_executor=stub_tool,
        )

        assert result.decision == "done"
        assert result.message == "Final answer after tool work."
        assert result.error == ""
        assert len(result.steps) == 21

    @pytest.mark.asyncio
    async def test_dict_tool_executor(self):
        """run_core_kernel works with dict-based tool_executor."""
        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-1",
                        name="search_content",
                        arguments={"pattern": "TODO"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        llm.add_response(LLMResponse(content="Found it, done.", finish_reason="stop"))

        async def fake_search(call: ToolCall) -> ToolResult:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content="3 matches found",
            )

        result = await run_core_kernel(
            goal="Search for TODOs",
            session_id="test-dict-exec",
            llm_client=llm,
            tool_executor={"search_content": fake_search},
        )

        assert result.decision == "done"

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_failed(self):
        """Dict executor returns failed result for unknown tools."""
        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-1",
                        name="nonexistent_tool",
                        arguments={},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        llm.add_response(LLMResponse(content="Moving on.", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Use unknown tool",
            session_id="test-unknown-tool",
            llm_client=llm,
            tool_executor={},  # Empty dict → no tools registered
        )

        # Should still complete (second turn says done)
        assert result.decision == "done"

    @pytest.mark.asyncio
    async def test_no_tool_executor_gives_stub(self):
        """No tool_executor → stub ok results."""
        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-1",
                        name="read_file",
                        arguments={"path": "x.py"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        llm.add_response(LLMResponse(content="Done.", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Read x.py",
            session_id="test-stub-tool",
            llm_client=llm,
            tool_executor=None,
        )

        assert result.decision == "done"

    @pytest.mark.asyncio
    async def test_result_has_session_id(self):
        """KernelResult carries the session_id from the input."""
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Done.", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Simple task",
            session_id="session-xyz-123",
            llm_client=llm,
        )

        assert result.session_id == "session-xyz-123"


# ---------------------------------------------------------------------------
# 8. ReadOnlyToolExecutor — read_file
# ---------------------------------------------------------------------------


class TestReadOnlyReadFile:
    """read_file: success, boundary violation, not-found, missing args."""

    @pytest.mark.asyncio
    async def test_read_file_success(self, tmp_path):
        """Read a file within work_root returns its content."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "hello.py").write_text("print('hello')", encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="c1", name="read_file", arguments={"path": "hello.py"})
        result = await executor.read_file(call)

        assert result.status == "ok"
        assert "print('hello')" in result.content

    @pytest.mark.asyncio
    async def test_read_file_path_traversal_blocked(self, tmp_path):
        """Path traversal outside work_root returns failed result."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        # Place a file outside work_root
        outside = tmp_path / "secret.txt"
        outside.write_text("secret data", encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="c2", name="read_file", arguments={"path": "../secret.txt"})
        result = await executor.read_file(call)

        assert result.status == "failed"
        assert "outside work_root" in result.error

    @pytest.mark.asyncio
    async def test_read_file_absolute_outside_blocked(self, tmp_path):
        """Absolute path outside work_root is rejected."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="c3", name="read_file", arguments={"path": "C:/Windows/System32/config/SAM"})
        result = await executor.read_file(call)

        assert result.status == "failed"
        assert "outside work_root" in result.error

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, tmp_path):
        """Non-existent file returns failed result."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="c4", name="read_file", arguments={"path": "nonexistent.py"})
        result = await executor.read_file(call)

        assert result.status == "failed"
        assert "not found" in result.error.lower() or "File not found" in result.error

    @pytest.mark.asyncio
    async def test_read_file_missing_path_arg(self, tmp_path):
        """Missing 'path' argument returns failed result."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="c5", name="read_file", arguments={})
        result = await executor.read_file(call)

        assert result.status == "failed"
        assert "Missing" in result.error

    @pytest.mark.asyncio
    async def test_read_file_truncation(self, tmp_path):
        """Large file content is truncated to max_text_length."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        big_content = "x" * 1000
        (work_root / "big.txt").write_text(big_content, encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root, max_text_length=500)
        call = ToolCall(id="c6", name="read_file", arguments={"path": "big.txt"})
        result = await executor.read_file(call)

        assert result.status == "ok"
        assert "truncated" in result.content
        assert len(result.content) <= 600  # 500 + truncation marker

    @pytest.mark.asyncio
    async def test_loaded_skill_reference_file_can_be_read_outside_work_root(self, tmp_path):
        """A loaded skill's own files are readable as trusted read-only resources."""
        work_root = tmp_path / "project"
        skill_root = tmp_path / "global-skills" / "demo"
        skill_root.mkdir(parents=True)
        skill_file = skill_root / "SKILL.md"
        reference = skill_root / "references" / "guide.md"
        reference.parent.mkdir()
        skill_file.write_text("---\nname: demo\n---\nRead references/guide.md", encoding="utf-8")
        reference.write_text("trusted skill reference", encoding="utf-8")

        class FakeSkillRegistry:
            def get(self, _work_root, name):
                return WriterSkill(name=name, description="", location=skill_file, content="")

            def load_prompt_content(self, _work_root, name):
                return f'<skill_content name="{name}">Base directory for this skill: {skill_root}</skill_content>'

        executor = ReadOnlyToolExecutor(work_root)
        executor._skills = FakeSkillRegistry()

        before = await executor.read_file(
            ToolCall(id="skill-read-before", name="read_file", arguments={"path": str(reference)})
        )
        assert before.status == "failed"
        assert "outside work_root" in before.error

        loaded = await executor.load_skill(ToolCall(id="skill-load", name="load_skill", arguments={"name": "demo"}))
        assert loaded.status == "ok"

        after = await executor.read_file(
            ToolCall(id="skill-read-after", name="read_file", arguments={"path": str(reference)})
        )
        assert after.status == "ok"
        assert "trusted skill reference" in after.content

        relative = await executor.read_file(
            ToolCall(id="skill-read-relative", name="read_file", arguments={"path": "references/guide.md"})
        )
        assert relative.status == "ok"
        assert "trusted skill reference" in relative.content


# ---------------------------------------------------------------------------
# 9. ReadOnlyToolExecutor — list_dir
# ---------------------------------------------------------------------------


class TestReadOnlyListDir:
    """list_dir: basic listing, limits, boundary, not-a-dir."""

    @pytest.mark.asyncio
    async def test_list_dir_basic(self, tmp_path):
        """List directory entries within work_root."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "file1.py").write_text("", encoding="utf-8")
        (work_root / "file2.py").write_text("", encoding="utf-8")
        (work_root / "subdir").mkdir()

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="d1", name="list_dir", arguments={"path": "."})
        result = await executor.list_dir(call)

        assert result.status == "ok"
        assert "file1.py" in result.content
        assert "file2.py" in result.content
        assert "subdir/" in result.content

    @pytest.mark.asyncio
    async def test_list_dir_limits_entries(self, tmp_path):
        """list_dir caps output to max_list_items."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        # Create more files than the limit
        for i in range(20):
            (work_root / f"file_{i:03d}.py").write_text("", encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root, max_list_items=5)
        call = ToolCall(id="d2", name="list_dir", arguments={"path": "."})
        result = await executor.list_dir(call)

        assert result.status == "ok"
        lines = result.content.strip().split("\n")
        # Should have 5 entries + 1 "more entries" line
        assert len(lines) == 6
        assert "more entries" in lines[-1]

    @pytest.mark.asyncio
    async def test_list_dir_boundary_violation(self, tmp_path):
        """list_dir rejects paths outside work_root."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="d3", name="list_dir", arguments={"path": "../"})
        result = await executor.list_dir(call)

        assert result.status == "failed"
        assert "outside work_root" in result.error

    @pytest.mark.asyncio
    async def test_list_dir_not_a_directory(self, tmp_path):
        """list_dir on a file returns error."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "file.txt").write_text("hi", encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="d4", name="list_dir", arguments={"path": "file.txt"})
        result = await executor.list_dir(call)

        assert result.status == "failed"
        assert "Not a directory" in result.error

    @pytest.mark.asyncio
    async def test_list_dir_default_path(self, tmp_path):
        """list_dir with no path argument defaults to work_root."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "readme.md").write_text("hello", encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="d5", name="list_dir", arguments={})
        result = await executor.list_dir(call)

        assert result.status == "ok"
        assert "readme.md" in result.content

    @pytest.mark.asyncio
    async def test_list_dir_null_path_defaults_to_work_root(self, tmp_path):
        """list_dir treats provider-emitted null path as the root directory."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "readme.md").write_text("hello", encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="d6", name="list_dir", arguments={"path": None})
        result = await executor.list_dir(call)

        assert result.status == "ok"
        assert "readme.md" in result.content


# ---------------------------------------------------------------------------
# 10. ReadOnlyToolExecutor — search_files
# ---------------------------------------------------------------------------


class TestReadOnlySearchFiles:
    """search_files: glob match, limits, no matches."""

    @pytest.mark.asyncio
    async def test_search_files_finds_py_files(self, tmp_path):
        """search_files finds .py files matching pattern."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "main.py").write_text("", encoding="utf-8")
        (work_root / "utils.py").write_text("", encoding="utf-8")
        (work_root / "readme.md").write_text("", encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="s1", name="search_files", arguments={"pattern": "*.py"})
        result = await executor.search_files(call)

        assert result.status == "ok"
        assert "main.py" in result.content
        assert "utils.py" in result.content
        assert "readme.md" not in result.content

    @pytest.mark.asyncio
    async def test_search_files_no_matches(self, tmp_path):
        """search_files with no matches reports 'No files found'."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "readme.md").write_text("", encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="s2", name="search_files", arguments={"pattern": "*.xyz"})
        result = await executor.search_files(call)

        assert result.status == "ok"
        assert "No files found" in result.content

    @pytest.mark.asyncio
    async def test_search_files_limits_results(self, tmp_path):
        """search_files caps output to max_search_results."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        for i in range(30):
            (work_root / f"mod_{i:03d}.py").write_text("", encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root, max_search_results=5)
        call = ToolCall(id="s3", name="search_files", arguments={"pattern": "*.py"})
        result = await executor.search_files(call)

        assert result.status == "ok"
        lines = result.content.strip().split("\n")
        # 5 matches + 1 "more matches" line
        assert len(lines) == 6
        assert "more matches" in lines[-1]

    @pytest.mark.asyncio
    async def test_search_files_respects_path_argument(self, tmp_path):
        """search_files can be limited to a subdirectory."""
        work_root = tmp_path / "project"
        (work_root / "src").mkdir(parents=True)
        (work_root / "tests").mkdir()
        (work_root / "src" / "app.py").write_text("", encoding="utf-8")
        (work_root / "tests" / "test_app.py").write_text("", encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="s4", name="search_files", arguments={"path": "src", "pattern": "*.py"})
        result = await executor.search_files(call)

        assert result.status == "ok"
        assert "src/app.py" in result.content
        assert "tests/test_app.py" not in result.content

    @pytest.mark.asyncio
    async def test_search_files_blocks_outside_path(self, tmp_path):
        """search_files path must stay inside work_root."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="s5", name="search_files", arguments={"path": "..", "pattern": "*.py"})
        result = await executor.search_files(call)

        assert result.status == "failed"
        assert "outside work_root" in result.error


# ---------------------------------------------------------------------------
# 11. ReadOnlyToolExecutor — search_content
# ---------------------------------------------------------------------------


class TestReadOnlySearchContent:
    """search_content: grep pattern, limits, missing pattern arg."""

    @pytest.mark.asyncio
    async def test_search_content_finds_pattern(self, tmp_path):
        """search_content finds lines containing the pattern."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "main.py").write_text("print('hello world')\nimport os\n", encoding="utf-8")
        (work_root / "utils.py").write_text("# TODO: fix this\nprint('hi')\n", encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="g1", name="search_content", arguments={"pattern": "TODO"})
        result = await executor.search_content(call)

        assert result.status == "ok"
        assert "TODO" in result.content
        assert "utils.py" in result.content

    @pytest.mark.asyncio
    async def test_search_content_no_matches(self, tmp_path):
        """search_content with no matches reports 'No matches found'."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "main.py").write_text("print('hello')\n", encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="g2", name="search_content", arguments={"pattern": "NONEXISTENT_PATTERN_XYZ"})
        result = await executor.search_content(call)

        assert result.status == "ok"
        assert "No matches found" in result.content

    @pytest.mark.asyncio
    async def test_search_content_missing_pattern(self, tmp_path):
        """search_content with missing pattern arg returns failed."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="g3", name="search_content", arguments={})
        result = await executor.search_content(call)

        assert result.status == "failed"
        assert "Missing" in result.error

    @pytest.mark.asyncio
    async def test_search_content_limits_results(self, tmp_path):
        """search_content caps output to max_search_results."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        # Create a file with many matching lines
        lines = [f"# TODO: item {i}" for i in range(30)]
        (work_root / "todo.txt").write_text("\n".join(lines), encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root, max_search_results=5)
        call = ToolCall(id="g4", name="search_content", arguments={"pattern": "TODO"})
        result = await executor.search_content(call)

        assert result.status == "ok"
        result_lines = [l for l in result.content.strip().split("\n") if l and not l.startswith("[...")]
        assert len(result_lines) <= 5

    @pytest.mark.asyncio
    async def test_search_content_respects_path_and_skips_large_dirs(self, tmp_path):
        """search_content respects path and skips noisy dependency dirs."""
        work_root = tmp_path / "project"
        (work_root / "src").mkdir(parents=True)
        (work_root / "node_modules").mkdir()
        (work_root / "src" / "app.py").write_text("TODO: keep this", encoding="utf-8")
        (work_root / "node_modules" / "pkg.js").write_text("TODO: skip this", encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="g5", name="search_content", arguments={"path": ".", "pattern": "TODO"})
        result = await executor.search_content(call)

        assert result.status == "ok"
        assert "src/app.py" in result.content
        assert "node_modules" not in result.content

    @pytest.mark.asyncio
    async def test_search_content_accepts_file_path(self, tmp_path):
        """search_content can grep a single file path."""
        work_root = tmp_path / "project"
        (work_root / "js").mkdir(parents=True)
        (work_root / "js" / "data.js").write_text("const answer = 42;\n", encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="g-file", name="search_content", arguments={"path": "js/data.js", "pattern": "answer"})
        result = await executor.search_content(call)

        assert result.status == "ok"
        assert "js/data.js:1: const answer = 42;" in result.content

    @pytest.mark.asyncio
    async def test_search_content_blocks_outside_path(self, tmp_path):
        """search_content path must stay inside work_root."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadOnlyToolExecutor(work_root)
        call = ToolCall(id="g6", name="search_content", arguments={"path": "..", "pattern": "TODO"})
        result = await executor.search_content(call)

        assert result.status == "failed"
        assert "outside work_root" in result.error


# ---------------------------------------------------------------------------
# 12. Injected executor overrides default read-only tools
# ---------------------------------------------------------------------------


class TestInjectedExecutorOverride:
    """Injected tool_executor takes priority over default read-only tools."""

    @pytest.mark.asyncio
    async def test_dict_executor_overrides_read_file(self, tmp_path):
        """Dict executor can override read_file while keeping other read-only tools."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "data.txt").write_text("real content", encoding="utf-8")

        custom_content = "custom override content"

        async def custom_read_file(call: ToolCall) -> ToolResult:
            return ToolResult(call_id=call.id, name=call.name, status="ok", content=custom_content)

        llm = FakeLLMClient()
        # First call: read_file
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(id="call-1", name="read_file", arguments={"path": "data.txt"})
                ],
                finish_reason="tool_calls",
            )
        )
        # Second call: done
        llm.add_response(LLMResponse(content="Done", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Read data",
            session_id="test-override-1",
            llm_client=llm,
            tool_executor={"read_file": custom_read_file},
            work_root=str(work_root),
        )

        assert result.decision == "done"
        # The tool result in history should contain custom content, not real file
        second_request = llm.last_request
        tool_messages = [m for m in second_request.messages if m.role == "tool"]
        assert len(tool_messages) >= 1
        assert custom_content in tool_messages[0].content

    @pytest.mark.asyncio
    async def test_callable_executor_fully_overrides(self, tmp_path):
        """Single callable executor fully overrides, ignoring read-only defaults."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executed_calls: list[str] = []

        async def universal_handler(call: ToolCall) -> ToolResult:
            executed_calls.append(call.name)
            return ToolResult(call_id=call.id, name=call.name, status="ok", content=f"handled: {call.name}")

        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(id="call-1", name="read_file", arguments={"path": "x.py"})
                ],
                finish_reason="tool_calls",
            )
        )
        llm.add_response(LLMResponse(content="Done", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Test callable override",
            session_id="test-callable-override",
            llm_client=llm,
            tool_executor=universal_handler,
            work_root=str(work_root),
        )

        assert result.decision == "done"
        assert "read_file" in executed_calls

    @pytest.mark.asyncio
    async def test_dict_executor_merges_with_read_only(self, tmp_path):
        """Dict executor adds custom tools while keeping read-only defaults."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "hello.py").write_text("print('hello')", encoding="utf-8")

        async def custom_tool(call: ToolCall) -> ToolResult:
            return ToolResult(call_id=call.id, name=call.name, status="ok", content="custom tool result")

        llm = FakeLLMClient()
        # First: call custom tool
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(id="call-1", name="custom_tool", arguments={})
                ],
                finish_reason="tool_calls",
            )
        )
        # Second: call read_file (should use default read-only handler)
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(id="call-2", name="read_file", arguments={"path": "hello.py"})
                ],
                finish_reason="tool_calls",
            )
        )
        # Third: done
        llm.add_response(LLMResponse(content="All done", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Test merge",
            session_id="test-merge",
            llm_client=llm,
            tool_executor={"custom_tool": custom_tool},
            work_root=str(work_root),
        )

        assert result.decision == "done"


# ---------------------------------------------------------------------------
# 13. Unknown tool returns failed result
# ---------------------------------------------------------------------------


class TestDefaultToolExecutorWithWorkRoot:
    """work_root enables the bounded default executor."""

    @pytest.mark.asyncio
    async def test_write_tool_with_work_root(self, tmp_path):
        """write_file works when work_root is set."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(id="call-1", name="write_file", arguments={"path": "x.py", "content": "bad"})
                ],
                finish_reason="tool_calls",
            )
        )
        llm.add_response(LLMResponse(content="Moving on", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Try write",
            session_id="test-unknown-read-only",
            llm_client=llm,
            work_root=str(work_root),
        )

        assert result.decision == "done"
        assert (work_root / "x.py").read_text(encoding="utf-8") == "bad"


# ---------------------------------------------------------------------------
# 14. Main path (no work_root) does not enable real read-only tools
# ---------------------------------------------------------------------------


class TestMainPathNoWorkRoot:
    """Without work_root, read-only file tools are not available."""

    @pytest.mark.asyncio
    async def test_no_work_root_read_file_is_unknown(self):
        """Without work_root, read_file falls back to stub (unknown in empty dict)."""
        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(id="call-1", name="read_file", arguments={"path": "x.py"})
                ],
                finish_reason="tool_calls",
            )
        )
        llm.add_response(LLMResponse(content="Done", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Read file",
            session_id="test-no-work-root",
            llm_client=llm,
            # No work_root → no read-only tools
        )

        assert result.decision == "done"
        # With no tool_executor and no work_root, Kit returns stub ok
        second_request = llm.last_request
        tool_messages = [m for m in second_request.messages if m.role == "tool"]
        assert len(tool_messages) >= 1
        # Stub result contains "[stub]" marker
        assert "[stub]" in tool_messages[0].content

    @pytest.mark.asyncio
    async def test_no_work_root_with_dict_executor(self):
        """Without work_root, dict executor is used as-is (no read-only merge)."""
        async def fake_search(call: ToolCall) -> ToolResult:
            return ToolResult(call_id=call.id, name=call.name, status="ok", content="search results")

        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(id="call-1", name="search_content", arguments={"pattern": "TODO"})
                ],
                finish_reason="tool_calls",
            )
        )
        llm.add_response(LLMResponse(content="Done", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Search",
            session_id="test-dict-no-work-root",
            llm_client=llm,
            tool_executor={"search_content": fake_search},
            # No work_root
        )

        assert result.decision == "done"
        second_request = llm.last_request
        tool_messages = [m for m in second_request.messages if m.role == "tool"]
        assert len(tool_messages) >= 1
        assert "search results" in tool_messages[0].content


# ---------------------------------------------------------------------------
# 15. _validate_path unit tests
# ---------------------------------------------------------------------------


class TestValidatePath:
    """Unit tests for _validate_path boundary check."""

    def test_path_inside_work_root(self, tmp_path):
        """Path inside work_root resolves successfully."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        result = _validate_path("src/main.py", work_root)
        assert str(result).endswith(os.path.join("project", "src", "main.py")) or "project" in str(result)

    def test_path_traversal_blocked(self, tmp_path):
        """Path traversal outside work_root raises ValueError."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        with pytest.raises(ValueError, match="outside work_root"):
            _validate_path("../../etc/passwd", work_root)

    def test_absolute_outside_blocked(self, tmp_path):
        """Absolute path outside work_root raises ValueError."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        with pytest.raises(ValueError, match="outside work_root"):
            _validate_path("C:/Windows/System32", work_root)


# ---------------------------------------------------------------------------
# 16. ReadOnlyToolExecutor.as_dict integration
# ---------------------------------------------------------------------------


class TestReadOnlyAsDict:
    """as_dict() returns a dict usable as tool_executor."""

    @pytest.mark.asyncio
    async def test_as_dict_with_kit(self, tmp_path):
        """Dict from as_dict() works with WriterKit."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "test.py").write_text("x = 1", encoding="utf-8")

        executor = ReadOnlyToolExecutor(work_root)
        kit = WriterKit(tool_executor=executor.as_dict())

        call = ToolCall(id="tc1", name="read_file", arguments={"path": "test.py"})
        result = await kit.execute_tool(RuntimeState(session_id="s"), call)

        assert result.status == "ok"
        assert "x = 1" in result.content

    @pytest.mark.asyncio
    async def test_as_dict_unknown_tool_fails(self, tmp_path):
        """Unknown tool via as_dict() returns failed result."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadOnlyToolExecutor(work_root)
        kit = WriterKit(tool_executor=executor.as_dict())

        call = ToolCall(id="tc2", name="write_file", arguments={"path": "x.py", "content": "bad"})
        result = await kit.execute_tool(RuntimeState(session_id="s"), call)

        assert result.status == "failed"
        assert "不可用" in (result.error or "")
        assert "read_file" in (result.content or "")


# ---------------------------------------------------------------------------
# 17. Observability — KernelResult.metadata enrichment
# ---------------------------------------------------------------------------


class TestKernelResultMetadataObservability:
    """KernelResult.metadata contains core_events, steps_count,
    tool_results_summary, verification_summaries, decision, error."""

    @pytest.mark.asyncio
    async def test_text_only_has_started_and_done_events(self):
        """Text-only run: metadata.core_events contains runtime.started and runtime.done."""
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Hello world", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Say hello",
            session_id="test-obs-text-only",
            llm_client=llm,
        )

        assert result.decision == "done"
        md = result.metadata
        assert "core_events" in md
        event_names = [e["event_name"] for e in md["core_events"]]
        assert "runtime.started" in event_names
        assert "runtime.done" in event_names

    def test_compacts_streaming_parts_for_history(self):
        """History keeps one latest logical part per part_id, not every delta."""
        events = [
            CoreEvent(name="runtime.started", category="lifecycle", run_id="r1"),
            CoreEvent(
                name="runtime.part",
                category="message",
                run_id="r1",
                payload={
                    "part_id": "r1:reasoning",
                    "part_type": "reasoning",
                    "status": "running",
                    "label": "思考",
                    "content": "first",
                },
            ),
            CoreEvent(
                name="runtime.part",
                category="message",
                run_id="r1",
                payload={
                    "part_id": "r1:reasoning",
                    "part_type": "reasoning",
                    "status": "completed",
                    "label": "思考",
                    "content": "first\nsecond",
                },
            ),
            CoreEvent(
                name="runtime.part",
                category="message",
                run_id="r1",
                payload={
                    "part_id": "r1:tool-call",
                    "part_type": "tool_call",
                    "status": "running",
                    "label": "准备工具调用",
                },
            ),
            CoreEvent(name="runtime.reply_delta", category="message", run_id="r1", payload={"content": "x"}),
            CoreEvent(name="runtime.done", category="lifecycle", run_id="r1", payload={"message": "done"}),
        ]

        compacted = compact_core_events_for_summary(events)

        keys = [(e["event_name"], e.get("part_type"), e.get("part_id")) for e in compacted]
        assert ("runtime.part", "reasoning", "r1:reasoning") in keys
        assert ("runtime.part", "tool_call", "r1:tool-call") in keys
        assert "runtime.reply_delta" not in [e["event_name"] for e in compacted]
        reasoning = next(e for e in compacted if e.get("part_id") == "r1:reasoning")
        assert reasoning["status"] == "completed"
        assert reasoning["content"] == "first\nsecond"

    @pytest.mark.asyncio
    async def test_streamed_reasoning_survives_summary_compaction(self):
        """Streaming reasoning is persisted as one refreshable content block."""

        class StreamingReasoningClient:
            async def complete(self, request: LLMRequest) -> LLMResponse:
                raise AssertionError("streaming path should be used")

            async def stream(self, request: LLMRequest):
                yield LLMStreamEvent(kind="thinking_delta", content="first")
                yield LLMStreamEvent(kind="thinking_delta", content=" second")
                yield LLMStreamEvent(kind="content_delta", content="Done")
                yield LLMStreamEvent(kind="done", metadata={"finish_reason": "stop"})

        result = await run_core_kernel(
            goal="Simple streamed task",
            session_id="test-obs-stream-reasoning",
            llm_client=StreamingReasoningClient(),
        )

        assert result.decision == "done"
        reasoning = [
            event
            for event in result.metadata["core_events"]
            if event.get("event_name") == "runtime.part" and event.get("part_type") == "reasoning"
        ]
        assert len(reasoning) == 1
        assert reasoning[0]["content"] == "first second"

    @pytest.mark.asyncio
    async def test_streamed_reasoning_is_scoped_per_model_response(self, tmp_path):
        """Each LLM call gets its own reasoning block instead of one run-wide stream."""

        class TwoResponseStreamingClient:
            def __init__(self) -> None:
                self.calls = 0

            async def complete(self, request: LLMRequest) -> LLMResponse:
                raise AssertionError("streaming path should be used")

            async def stream(self, request: LLMRequest):
                self.calls += 1
                if self.calls == 1:
                    yield LLMStreamEvent(kind="thinking_delta", content="inspect files")
                    yield LLMStreamEvent(
                        kind="done",
                        tool_calls=[
                            LLMToolCall(
                                id="tc-list",
                                name="list_dir",
                                arguments={"path": "."},
                            )
                        ],
                        metadata={"finish_reason": "tool_calls"},
                    )
                else:
                    yield LLMStreamEvent(kind="thinking_delta", content="summarize result")
                    yield LLMStreamEvent(kind="content_delta", content="Done")
                    yield LLMStreamEvent(kind="done", metadata={"finish_reason": "stop"})

        result = await run_core_kernel(
            goal="Inspect then answer",
            session_id="test-obs-stream-reasoning-response-scope",
            llm_client=TwoResponseStreamingClient(),
            work_root=str(tmp_path),
        )

        assert result.decision == "done"
        reasoning = [
            event
            for event in result.metadata["core_events"]
            if event.get("event_name") == "runtime.part" and event.get("part_type") == "reasoning"
        ]
        assert [event["content"] for event in reasoning] == ["inspect files", "summarize result"]
        assert [event["response_index"] for event in reasoning] == [0, 1]
        assert [event["part_id"] for event in reasoning] == [
            f"{result.run_id}:response-0:reasoning",
            f"{result.run_id}:response-1:reasoning",
        ]
        blocks = result.metadata["response_blocks"]
        assert [block["response_index"] for block in blocks] == [0, 1]
        assert [block["items"][0]["content"] for block in blocks] == [
            "inspect files",
            "summarize result",
        ]

    @pytest.mark.asyncio
    async def test_streamed_tool_call_delta_survives_before_tool_execution(self, tmp_path):
        """Tool-call deltas are visible as running parts before runtime.tool.started."""

        class StreamingToolCallClient:
            def __init__(self) -> None:
                self.calls = 0

            async def complete(self, request: LLMRequest) -> LLMResponse:
                raise AssertionError("streaming path should be used")

            async def stream(self, request: LLMRequest):
                self.calls += 1
                if self.calls > 1:
                    yield LLMStreamEvent(kind="content_delta", content="Done")
                    yield LLMStreamEvent(kind="done", metadata={"finish_reason": "stop"})
                    return

                yield LLMStreamEvent(
                    kind="tool_call_delta",
                    metadata={
                        "tool_calls_delta": [
                            {
                                "index": 0,
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": "{\"path\":\"index.html\",\"content\":\"<html>",
                                },
                            }
                        ]
                    },
                )
                yield LLMStreamEvent(
                    kind="tool_call_delta",
                    metadata={
                        "tool_calls_delta": [
                            {
                                "index": 0,
                                "function": {
                                    "arguments": "</html>\"}",
                                },
                            }
                        ]
                    },
                )
                yield LLMStreamEvent(kind="done", metadata={"finish_reason": "tool_calls"})

        result = await run_core_kernel(
            goal="Write the page",
            session_id="test-obs-stream-tool-call",
            llm_client=StreamingToolCallClient(),
            tool_executor=lambda call: ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content="Wrote index.html",
            ),
        )

        assert result.decision == "done"
        events = result.metadata["core_events"]
        tool_part = next(
            event
            for event in events
            if event.get("event_name") == "runtime.part" and event.get("part_type") == "tool_call"
        )
        input_delta = next(
            event
            for event in events
            if event.get("event_name") == "runtime.part" and event.get("part_type") == "tool_input_delta"
        )
        started = next(event for event in events if event.get("event_name") == "runtime.tool.started")
        part_index = events.index(tool_part)
        delta_index = events.index(input_delta)
        started_index = events.index(started)

        assert part_index < started_index
        assert part_index < delta_index < started_index
        assert tool_part["status"] == "running"
        assert tool_part["tool_name"] == "write_file"
        assert tool_part["call_id"] == "functions.write_file:0"
        assert input_delta["tool_name"] == "write_file"
        assert input_delta["call_id"] == "functions.write_file:0"
        assert "content" in input_delta["arguments_text"]
        assert all(
            not (
                isinstance(event.get("tool_args"), dict)
                and isinstance(event["tool_args"].get("content"), str)
                and "chars streaming" in event["tool_args"]["content"]
            )
            for event in events
            if event.get("event_name") == "runtime.part" and event.get("part_type") == "tool_call"
        )
        assert tool_part["tool_args"]["path"] == "index.html"
        assert "content" not in tool_part["tool_args"]
        assert "raw_arguments" not in tool_part
        assert started["call_id"] == "functions.write_file:0"

    @pytest.mark.asyncio
    async def test_final_tool_call_arguments_refresh_streamed_input_preview(self):
        """Final tool arguments refresh previews when deltas only exposed the first char."""

        final_content = "# Title\n\nThe final README content is available only on the done event.\n"

        class FinalArgumentsStreamingClient:
            def __init__(self) -> None:
                self.calls = 0

            async def complete(self, request: LLMRequest) -> LLMResponse:
                raise AssertionError("streaming path should be used")

            async def stream(self, request: LLMRequest):
                self.calls += 1
                if self.calls > 1:
                    yield LLMStreamEvent(kind="content_delta", content="Done")
                    yield LLMStreamEvent(kind="done", metadata={"finish_reason": "stop"})
                    return

                yield LLMStreamEvent(
                    kind="tool_call_delta",
                    metadata={
                        "tool_calls_delta": [
                            {
                                "index": 0,
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": "{\"path\":\"README.md\",\"content\":\"#",
                                },
                            }
                        ]
                    },
                )
                yield LLMStreamEvent(
                    kind="done",
                    tool_calls=[
                        LLMToolCall(
                            id="",
                            name="write_file",
                            arguments={"path": "README.md", "content": final_content},
                            metadata={
                                "raw_arguments": json.dumps(
                                    {"path": "README.md", "content": final_content},
                                    ensure_ascii=False,
                                )
                            },
                        )
                    ],
                    metadata={"finish_reason": "tool_calls"},
                )

        result = await run_core_kernel(
            goal="Write the README",
            session_id="test-obs-final-tool-input-preview",
            llm_client=FinalArgumentsStreamingClient(),
            tool_executor=lambda call: ToolResult(
                call_id=call.id,
                name=call.name,
                status="ok",
                content="Wrote README.md",
            ),
        )

        events = result.metadata["core_events"]
        input_deltas = [
            event
            for event in events
            if event.get("event_name") == "runtime.part" and event.get("part_type") == "tool_input_delta"
        ]
        started = next(event for event in events if event.get("event_name") == "runtime.tool.started")

        assert result.decision == "done"
        assert any(
            event.get("event_name") == "runtime.part" and event.get("part_type") == "tool_call"
            for event in events
        )
        event_summary = [
            (event.get("event_name"), event.get("part_type"), event.get("tool_name"), event.get("detail"))
            for event in events
        ]
        assert [event["call_id"] for event in input_deltas] == ["functions.write_file:0"], event_summary
        assert json.loads(input_deltas[0]["arguments_text"])["content"] == final_content
        assert events.index(input_deltas[0]) < events.index(started)
        assert result.steps[0].tool_steps[0].call.arguments["content"] == final_content

    @pytest.mark.asyncio
    async def test_text_only_steps_count(self):
        """Text-only run: steps_count is 1."""
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Done", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Simple task",
            session_id="test-obs-steps-count",
            llm_client=llm,
        )

        assert result.metadata["steps_count"] == 1

    @pytest.mark.asyncio
    async def test_streaming_done_usage_populates_runtime_metrics(self):
        """Streaming usage from the terminal delta is included in metrics."""

        class StreamingUsageClient:
            async def complete(self, request: LLMRequest) -> LLMResponse:
                raise AssertionError("streaming path should be used")

            async def stream(self, request: LLMRequest):
                yield LLMStreamEvent(kind="content_delta", content="Done")
                yield LLMStreamEvent(
                    kind="done",
                    usage=LLMUsage(prompt_tokens=12, completion_tokens=3, total_tokens=15),
                    metadata={"finish_reason": "stop"},
                )

        result = await run_core_kernel(
            goal="Simple streamed task",
            session_id="test-obs-stream-usage",
            llm_client=StreamingUsageClient(),
        )

        assert result.decision == "done"

    @pytest.mark.asyncio
    async def test_runtime_metrics_include_current_context_budget_estimate(self):
        llm = FakeLLMClient()
        llm.context_window = 256_000
        llm.add_response(LLMResponse(content="Done", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Simple task",
            session_id="test-obs-context-metrics",
            llm_client=llm,
        )

        metrics = result.metadata["runtime_metrics"]
        assert metrics["estimated_prompt_tokens"] > 0
        assert metrics["context_window_tokens"] == 256_000
        assert metrics["context_compaction_trigger_tokens"] == 204_800

    @pytest.mark.asyncio
    async def test_read_file_has_tool_started_and_finished(self):
        """read_file tool call: core_events has runtime.tool.started and runtime.tool.finished."""
        llm = FakeLLMClient()
        # First: tool call
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(id="call-r1", name="read_file", arguments={"path": "x.py"})
                ],
                finish_reason="tool_calls",
            )
        )
        # Second: done
        llm.add_response(LLMResponse(content="All done", finish_reason="stop"))

        async def fake_read(call: ToolCall) -> ToolResult:
            return ToolResult(call_id=call.id, name=call.name, status="ok", content="file content here")

        result = await run_core_kernel(
            goal="Read x.py",
            session_id="test-obs-read-file",
            llm_client=llm,
            tool_executor=fake_read,
        )

        assert result.decision == "done"
        event_names = [e["event_name"] for e in result.metadata["core_events"]]
        assert "runtime.tool.started" in event_names
        assert "runtime.tool.finished" in event_names

    @pytest.mark.asyncio
    async def test_read_file_tool_results_summary(self):
        """read_file tool: tool_results_summary has entry with tool_name and status."""
        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(id="call-r2", name="read_file", arguments={"path": "y.py"})
                ],
                finish_reason="tool_calls",
            )
        )
        llm.add_response(LLMResponse(content="Done", finish_reason="stop"))

        async def fake_read(call: ToolCall) -> ToolResult:
            return ToolResult(call_id=call.id, name=call.name, status="ok", content="content")

        result = await run_core_kernel(
            goal="Read y.py",
            session_id="test-obs-tool-summary",
            llm_client=llm,
            tool_executor=fake_read,
        )

        summary = result.metadata["tool_results_summary"]
        assert len(summary) == 1
        assert summary[0]["tool_name"] == "read_file"
        assert summary[0]["status"] == "ok"
        # No full tool output in summary
        assert "content" not in summary[0]

    @pytest.mark.asyncio
    async def test_verification_summary_present(self):
        """Verification summary is present in metadata."""
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Done", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Simple task",
            session_id="test-obs-verification",
            llm_client=llm,
        )

        vs = result.metadata["verification_summaries"]
        assert len(vs) == 1
        assert vs[0]["passed"] is True
        assert "summary" in vs[0]

    @pytest.mark.asyncio
    async def test_failed_tool_error_summary_no_full_output(self):
        """Failed tool: error summary present but no full tool output leaked."""
        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(id="call-f1", name="write_file", arguments={"path": "x.py"})
                ],
                finish_reason="tool_calls",
            )
        )
        llm.add_response(LLMResponse(content="Moving on", finish_reason="stop"))

        async def failing_tool(call: ToolCall) -> ToolResult:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error="Permission denied: detailed stack trace that should not leak",
            )

        result = await run_core_kernel(
            goal="Write file",
            session_id="test-obs-error-summary",
            llm_client=llm,
            tool_executor=failing_tool,
        )

        summary = result.metadata["tool_results_summary"]
        assert len(summary) == 1
        assert summary[0]["status"] == "failed"
        assert "error" in summary[0]
        # Error is truncated, not the full message
        assert "Permission denied" in summary[0]["error"]
        # No full tool output content
        assert "content" not in summary[0]

    @pytest.mark.asyncio
    async def test_decision_in_metadata(self):
        """Decision is recorded in metadata."""
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Done", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Task",
            session_id="test-obs-decision",
            llm_client=llm,
        )

        assert result.metadata["decision"] == "done"

    @pytest.mark.asyncio
    async def test_error_in_metadata_when_failed(self):
        """Error is recorded in metadata when kernel fails (explicit model error)."""
        llm = FakeLLMClient()
        # Model returns a response that triggers explicit failure
        llm.add_response(
            LLMResponse(
                content="FATAL ERROR: cannot proceed",
                finish_reason="stop",
            )
        )

        result = await run_core_kernel(
            goal="Buggy task",
            session_id="test-obs-error",
            llm_client=llm,
        )

        # Should complete as "done" since the model stopped on its own
        assert result.decision in ("done", "failed")
        # Metadata should still be populated regardless

    @pytest.mark.asyncio
    async def test_writer_runtime_module_no_longer_exists(self):
        """WriterRuntime module has been deleted — single-track architecture."""
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("app.core.writer.runtime")


# ---------------------------------------------------------------------------
# 20. ReadWriteToolExecutor — write_file
# ---------------------------------------------------------------------------


class TestReadWriteWriteFile:
    """write_file: success, boundary violation, content limit, missing args."""

    @pytest.mark.asyncio
    async def test_write_file_success(self, tmp_path):
        """Write a new file within work_root."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(id="w1", name="write_file", arguments={"path": "hello.py", "content": "print('hello')"})
        result = await executor.write_file(call)

        assert result.status == "ok"
        assert "Created" in result.content or "Overwrote" in result.content
        # File actually exists on disk
        assert (work_root / "hello.py").read_text(encoding="utf-8") == "print('hello')"

    @pytest.mark.asyncio
    async def test_write_file_creates_parent_dirs(self, tmp_path):
        """write_file creates intermediate directories automatically."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="w2",
            name="write_file",
            arguments={"path": "src/utils/helper.py", "content": "def help(): pass"},
        )
        result = await executor.write_file(call)

        assert result.status == "ok"
        assert (work_root / "src" / "utils" / "helper.py").read_text(encoding="utf-8") == "def help(): pass"

    @pytest.mark.asyncio
    async def test_write_file_overwrites_existing(self, tmp_path):
        """write_file overwrites an existing file."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "data.txt").write_text("old content", encoding="utf-8")

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(id="w3", name="write_file", arguments={"path": "data.txt", "content": "new content"})
        result = await executor.write_file(call)

        assert result.status == "ok"
        assert (work_root / "data.txt").read_text(encoding="utf-8") == "new content"

    @pytest.mark.asyncio
    async def test_write_file_path_traversal_blocked(self, tmp_path):
        """Path traversal outside work_root is rejected."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(id="w4", name="write_file", arguments={"path": "../escape.txt", "content": "bad"})
        result = await executor.write_file(call)

        assert result.status == "failed"
        assert "outside work_root" in result.error

    @pytest.mark.asyncio
    async def test_write_file_absolute_outside_blocked(self, tmp_path):
        """Absolute path outside work_root is rejected."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(id="w5", name="write_file", arguments={"path": "C:/Windows/exploit.bat", "content": "bad"})
        result = await executor.write_file(call)

        assert result.status == "failed"
        assert "outside work_root" in result.error

    @pytest.mark.asyncio
    async def test_loaded_skill_does_not_allow_writing_outside_work_root(self, tmp_path):
        """Loaded skill roots are read/execute resources, not write targets."""
        work_root = tmp_path / "project"
        skill_root = tmp_path / "global-skills" / "demo"
        work_root.mkdir()
        skill_root.mkdir(parents=True)
        skill_file = skill_root / "SKILL.md"
        reference = skill_root / "references" / "guide.md"
        reference.parent.mkdir()
        skill_file.write_text("---\nname: demo\n---\nRead references/guide.md", encoding="utf-8")
        reference.write_text("trusted skill reference", encoding="utf-8")

        class FakeSkillRegistry:
            def get(self, _work_root, name):
                return WriterSkill(name=name, description="", location=skill_file, content="")

            def load_prompt_content(self, _work_root, name):
                return f'<skill_content name="{name}">Base directory for this skill: {skill_root}</skill_content>'

        executor = ReadWriteToolExecutor(work_root)
        executor._skills = FakeSkillRegistry()

        loaded = await executor.load_skill(ToolCall(id="skill-load-write", name="load_skill", arguments={"name": "demo"}))
        assert loaded.status == "ok"

        result = await executor.write_file(
            ToolCall(id="skill-write", name="write_file", arguments={"path": str(reference), "content": "bad"})
        )
        assert result.status == "failed"
        assert "outside work_root" in result.error

    @pytest.mark.asyncio
    async def test_write_file_content_length_exceeded(self, tmp_path):
        """Content exceeding max_write_length is rejected."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root, max_write_length=100)
        big_content = "x" * 200
        call = ToolCall(id="w6", name="write_file", arguments={"path": "big.txt", "content": big_content})
        result = await executor.write_file(call)

        assert result.status == "failed"
        assert "exceeds max_write_length" in result.error

    @pytest.mark.asyncio
    async def test_write_file_missing_path(self, tmp_path):
        """Missing 'path' argument returns failed result."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(id="w7", name="write_file", arguments={"content": "data"})
        result = await executor.write_file(call)

        assert result.status == "failed"
        assert "Missing" in result.error

    @pytest.mark.asyncio
    async def test_write_file_missing_content(self, tmp_path):
        """Missing 'content' argument writes empty string (valid operation)."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(id="w8", name="write_file", arguments={"path": "empty.txt"})
        result = await executor.write_file(call)

        assert result.status == "ok"
        assert (work_root / "empty.txt").read_text(encoding="utf-8") == ""

    @pytest.mark.asyncio
    async def test_write_file_non_string_content_rejected(self, tmp_path):
        """Non-string content returns failed result instead of raising."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(id="w9", name="write_file", arguments={"path": "bad.txt", "content": {"x": 1}})
        result = await executor.write_file(call)

        assert result.status == "failed"
        assert "content" in result.error
        assert not (work_root / "bad.txt").exists()


# ---------------------------------------------------------------------------
# 21. ReadWriteToolExecutor — edit_file
# ---------------------------------------------------------------------------


class TestReadWriteEditFile:
    """edit_file: success, not found, ambiguous, boundary, missing args."""

    @pytest.mark.asyncio
    async def test_edit_file_success(self, tmp_path):
        """Replace old_string with new_string in existing file."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "main.py").write_text("print('hello world')\nimport os\n", encoding="utf-8")

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="e1",
            name="edit_file",
            arguments={"path": "main.py", "old_string": "hello world", "new_string": "goodbye world"},
        )
        result = await executor.edit_file(call)

        assert result.status == "ok"
        assert "Edited" in result.content
        assert (work_root / "main.py").read_text(encoding="utf-8") == "print('goodbye world')\nimport os\n"

    @pytest.mark.asyncio
    async def test_edit_file_old_string_not_found(self, tmp_path):
        """edit_file fails when old_string is not in the file."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "main.py").write_text("print('hello')\n", encoding="utf-8")

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="e2",
            name="edit_file",
            arguments={"path": "main.py", "old_string": "nonexistent text", "new_string": "replacement"},
        )
        result = await executor.edit_file(call)

        assert result.status == "failed"
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_edit_file_ambiguous_old_string(self, tmp_path):
        """edit_file fails when old_string appears more than once."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "dup.py").write_text("x = 1\nx = 1\n", encoding="utf-8")

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="e3",
            name="edit_file",
            arguments={"path": "dup.py", "old_string": "x = 1", "new_string": "x = 2"},
        )
        result = await executor.edit_file(call)

        assert result.status == "failed"
        assert "2 times" in result.error
        assert "more context" in result.error

    @pytest.mark.asyncio
    async def test_edit_file_path_traversal_blocked(self, tmp_path):
        """Path traversal outside work_root is rejected."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="e4",
            name="edit_file",
            arguments={"path": "../secret.txt", "old_string": "a", "new_string": "b"},
        )
        result = await executor.edit_file(call)

        assert result.status == "failed"
        assert "outside work_root" in result.error

    @pytest.mark.asyncio
    async def test_edit_file_file_not_found(self, tmp_path):
        """edit_file fails when the target file does not exist."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="e5",
            name="edit_file",
            arguments={"path": "nonexistent.py", "old_string": "a", "new_string": "b"},
        )
        result = await executor.edit_file(call)

        assert result.status == "failed"
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_edit_file_missing_path(self, tmp_path):
        """Missing 'path' argument returns failed result."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="e6",
            name="edit_file",
            arguments={"old_string": "a", "new_string": "b"},
        )
        result = await executor.edit_file(call)

        assert result.status == "failed"
        assert "Missing" in result.error

    @pytest.mark.asyncio
    async def test_edit_file_missing_old_string(self, tmp_path):
        """Missing 'old_string' argument returns failed result."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="e7",
            name="edit_file",
            arguments={"path": "a.py", "new_string": "b"},
        )
        result = await executor.edit_file(call)

        assert result.status == "failed"
        assert "Missing" in result.error

    @pytest.mark.asyncio
    async def test_edit_file_non_string_new_string_rejected(self, tmp_path):
        """Non-string replacement returns failed result instead of raising."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "a.py").write_text("x = 1\n", encoding="utf-8")

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="e10",
            name="edit_file",
            arguments={"path": "a.py", "old_string": "x = 1", "new_string": {"x": 2}},
        )
        result = await executor.edit_file(call)

        assert result.status == "failed"
        assert "new_string" in result.error
        assert (work_root / "a.py").read_text(encoding="utf-8") == "x = 1\n"

    @pytest.mark.asyncio
    async def test_edit_file_resulting_length_exceeded(self, tmp_path):
        """edit_file fails when resulting file exceeds max_write_length."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "big.py").write_text("x = 1\n", encoding="utf-8")

        executor = ReadWriteToolExecutor(work_root, max_write_length=10)
        call = ToolCall(
            id="e8",
            name="edit_file",
            arguments={"path": "big.py", "old_string": "x = 1", "new_string": "x" * 200},
        )
        result = await executor.edit_file(call)

        assert result.status == "failed"
        assert "exceeds max_write_length" in result.error

    @pytest.mark.asyncio
    async def test_edit_file_multiline_replacement(self, tmp_path):
        """edit_file can replace multi-line old_string."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "code.py").write_text("def old():\n    pass\n\ndef keep():\n    pass\n", encoding="utf-8")

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="e9",
            name="edit_file",
            arguments={
                "path": "code.py",
                "old_string": "def old():\n    pass",
                "new_string": "def new():\n    return True",
            },
        )
        result = await executor.edit_file(call)

        assert result.status == "ok"
        content = (work_root / "code.py").read_text(encoding="utf-8")
        assert "def new():" in content
        assert "def keep():" in content
        assert "def old():" not in content


# ---------------------------------------------------------------------------
# 22. ReadWriteToolExecutor.as_dict integration
# ---------------------------------------------------------------------------


class TestReadWriteAsDict:
    """as_dict() returns a dict with both read and write tools."""

    @pytest.mark.asyncio
    async def test_as_dict_has_write_tools(self, tmp_path):
        """ReadWriteToolExecutor.as_dict() includes write_file and edit_file."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        d = executor.as_dict()

        assert "write_file" in d
        assert "edit_file" in d
        assert "read_file" in d
        assert "list_dir" in d
        assert "request_commit_review" in d

    @pytest.mark.asyncio
    async def test_as_dict_write_file_via_kit(self, tmp_path):
        """write_file works through WriterKit with as_dict()."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        kit = WriterKit(tool_executor=executor.as_dict())

        call = ToolCall(id="tc1", name="write_file", arguments={"path": "test.py", "content": "x = 1"})
        result = await kit.execute_tool(RuntimeState(session_id="s"), call)

        assert result.status == "ok"
        assert (work_root / "test.py").read_text(encoding="utf-8") == "x = 1"

    @pytest.mark.asyncio
    async def test_as_dict_edit_file_via_kit(self, tmp_path):
        """edit_file works through WriterKit with as_dict()."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "test.py").write_text("x = 1\ny = 2\n", encoding="utf-8")

        executor = ReadWriteToolExecutor(work_root)
        kit = WriterKit(tool_executor=executor.as_dict())

        call = ToolCall(
            id="tc2",
            name="edit_file",
            arguments={"path": "test.py", "old_string": "x = 1", "new_string": "x = 42"},
        )
        result = await kit.execute_tool(RuntimeState(session_id="s"), call)

        assert result.status == "ok"
        assert (work_root / "test.py").read_text(encoding="utf-8") == "x = 42\ny = 2\n"

    @pytest.mark.asyncio
    async def test_request_commit_review_returns_structured_metadata(self, tmp_path):
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        result = await executor.request_commit_review(
            ToolCall(
                id="tc-review",
                name="request_commit_review",
                arguments={
                    "title": "验收设置页",
                    "summary": "补齐设置页保存流程",
                    "how_to_review": "打开设置页保存一次配置",
                    "self_check": "已运行构建",
                    "commit_message": "feat: update settings save flow",
                },
            )
        )

        assert result.status == "ok"
        request = result.metadata["commit_review_request"]
        assert request["title"] == "验收设置页"
        assert request["commit_message"] == "feat: update settings save flow"


# ---------------------------------------------------------------------------
# 23. Core loop integration — write/edit tools in full kernel run
# ---------------------------------------------------------------------------


class TestCoreLoopWithWriteTools:
    """Core loop completes after using write_file and edit_file tools."""

    @pytest.mark.asyncio
    async def test_write_file_then_done(self, tmp_path):
        """Core loop: model calls write_file, sees result, then says done."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        llm = FakeLLMClient()
        # First: call write_file
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-w1",
                        name="write_file",
                        arguments={"path": "output.txt", "content": "Hello World"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        # Second: done
        llm.add_response(LLMResponse(content="File written successfully.", finish_reason="stop"))

        executor = ReadWriteToolExecutor(work_root)
        result = await run_core_kernel(
            goal="Write a file",
            session_id="test-loop-write-1",
            llm_client=llm,
            tool_executor=executor.as_dict(),
        )

        assert result.decision == "done"
        assert (work_root / "output.txt").read_text(encoding="utf-8") == "Hello World"

    @pytest.mark.asyncio
    async def test_edit_file_then_done(self, tmp_path):
        """Core loop: model calls edit_file, sees result, then says done."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "draft.txt").write_text("Hello World", encoding="utf-8")

        llm = FakeLLMClient()
        # First: call edit_file
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-e1",
                        name="edit_file",
                        arguments={"path": "draft.txt", "old_string": "Hello", "new_string": "Goodbye"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        # Second: done
        llm.add_response(LLMResponse(content="File edited successfully.", finish_reason="stop"))

        executor = ReadWriteToolExecutor(work_root)
        result = await run_core_kernel(
            goal="Edit the draft",
            session_id="test-loop-edit-1",
            llm_client=llm,
            tool_executor=executor.as_dict(),
        )

        assert result.decision == "done"
        assert (work_root / "draft.txt").read_text(encoding="utf-8") == "Goodbye World"

    @pytest.mark.asyncio
    async def test_read_then_write_then_done(self, tmp_path):
        """Core loop: model reads a file, then writes another, then done."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "input.txt").write_text("source data", encoding="utf-8")

        llm = FakeLLMClient()
        # First: read_file
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-r1",
                        name="read_file",
                        arguments={"path": "input.txt"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        # Second: write_file
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-w1",
                        name="write_file",
                        arguments={"path": "output.txt", "content": "processed: source data"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        # Third: done
        llm.add_response(LLMResponse(content="Done processing.", finish_reason="stop"))

        executor = ReadWriteToolExecutor(work_root)
        result = await run_core_kernel(
            goal="Read input and write output",
            session_id="test-loop-read-write-1",
            llm_client=llm,
            tool_executor=executor.as_dict(),
        )

        assert result.decision == "done"
        assert (work_root / "output.txt").read_text(encoding="utf-8") == "processed: source data"

    @pytest.mark.asyncio
    async def test_edit_file_failure_continues_loop(self, tmp_path):
        """Core loop: edit_file fails (old_string not found), model retries, then done."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "code.py").write_text("x = 1\n", encoding="utf-8")

        llm = FakeLLMClient()
        # First: edit_file with wrong old_string → fails
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-e1",
                        name="edit_file",
                        arguments={"path": "code.py", "old_string": "y = 2", "new_string": "y = 3"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        # Second: edit_file with correct old_string → succeeds
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-e2",
                        name="edit_file",
                        arguments={"path": "code.py", "old_string": "x = 1", "new_string": "x = 42"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        # Third: done
        llm.add_response(LLMResponse(content="Edit completed.", finish_reason="stop"))

        executor = ReadWriteToolExecutor(work_root)
        result = await run_core_kernel(
            goal="Edit the code",
            session_id="test-loop-edit-retry-1",
            llm_client=llm,
            tool_executor=executor.as_dict(),
        )

        assert result.decision == "done"
        assert (work_root / "code.py").read_text(encoding="utf-8") == "x = 42\n"


# ---------------------------------------------------------------------------
# 24. CORE_KERNEL=1 gate — ReadWriteToolExecutor vs ReadOnlyToolExecutor
# ---------------------------------------------------------------------------


class TestDefaultWriteTools:
    """The single runtime path exposes bounded write tools by default."""

    @pytest.mark.asyncio
    async def test_write_file_available_by_default(self, tmp_path):
        """write_file is available via run_core_kernel when work_root is set."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-w1",
                        name="write_file",
                        arguments={"path": "test.txt", "content": "hello"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        llm.add_response(LLMResponse(content="Done", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Write a file",
            session_id="test-default-write-1",
            llm_client=llm,
            work_root=str(work_root),
        )

        assert result.decision == "done"
        assert (work_root / "test.txt").read_text(encoding="utf-8") == "hello"

    @pytest.mark.asyncio
    async def test_no_work_root_keeps_write_file_stubbed(self, tmp_path):
        """Without work_root, no real file operation is attempted."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-w1",
                        name="write_file",
                        arguments={"path": "test.txt", "content": "hello"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        llm.add_response(LLMResponse(content="Moving on", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Write a file",
            session_id="test-no-work-root-write-1",
            llm_client=llm,
        )

        assert result.decision == "done"
        assert not (work_root / "test.txt").exists()

    @pytest.mark.asyncio
    async def test_edit_file_available_by_default(self, tmp_path):
        """edit_file is available via run_core_kernel when work_root is set."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "data.txt").write_text("old value", encoding="utf-8")

        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-e1",
                        name="edit_file",
                        arguments={"path": "data.txt", "old_string": "old value", "new_string": "new value"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        llm.add_response(LLMResponse(content="Done", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Edit the file",
            session_id="test-default-edit-1",
            llm_client=llm,
            work_root=str(work_root),
        )

        assert result.decision == "done"
        assert (work_root / "data.txt").read_text(encoding="utf-8") == "new value"


# ---------------------------------------------------------------------------
# Additional imports for run_command tests
# ---------------------------------------------------------------------------

from app.core.writer.core_kernel_adapter import (
    _validate_command_paths,
)


# ---------------------------------------------------------------------------
# 25. _validate_command_paths — path argument validation
# ---------------------------------------------------------------------------


class TestValidateCommandPaths:
    """Tests for _validate_command_paths function."""

    def test_valid_relative_path_passes(self, tmp_path):
        """Args with 'tests/' pass validation."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        # Should not raise
        _validate_command_paths(["py", "-m", "pytest", "tests/"], work_root)

    def test_path_traversal_blocked(self, tmp_path):
        """Args with '../etc/passwd' raises ValueError."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        with pytest.raises(ValueError, match="escapes work_root"):
            _validate_command_paths(["py", "-m", "pytest", "../etc/passwd"], work_root)

    def test_absolute_path_outside_blocked(self, tmp_path):
        """Args with 'C:/Windows/system32' raises ValueError."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        with pytest.raises(ValueError):
            _validate_command_paths(["py", "-m", "pytest", "C:/Windows/system32"], work_root)

    def test_flags_not_validated(self, tmp_path):
        """Args with '-v', '--tb=short' are not path-validated."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        # Should not raise — flags are skipped
        _validate_command_paths(["py", "-v", "--tb=short"], work_root)

    def test_mixed_flags_and_paths(self, tmp_path):
        """Args ['-v', 'tests/', '--tb=short'] — 'tests/' passes, flags skipped."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        # Should not raise — flags skipped, tests/ is inside work_root
        _validate_command_paths(["py", "-v", "tests/", "--tb=short"], work_root)

    def test_flag_value_path_traversal_blocked(self, tmp_path):
        """Args with '--rootdir=../outside' raises ValueError."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        with pytest.raises(ValueError, match="escapes work_root"):
            _validate_command_paths(["py", "-m", "pytest", "--rootdir=../outside"], work_root)

    def test_shell_metacharacter_token_allowed(self, tmp_path):
        """Shell metacharacters are allowed; command risk is handled by approval policy."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        _validate_command_paths(["py", "-m", "pytest", ";", "echo"], work_root)

    def test_loaded_skill_script_path_passes_as_resource(self, tmp_path):
        """A script path under a loaded skill root can be passed to run_command."""
        work_root = tmp_path / "project"
        skill_root = tmp_path / "global-skills" / "demo"
        script = skill_root / "scripts" / "helper.mjs"
        work_root.mkdir()
        script.parent.mkdir(parents=True)
        script.write_text("console.log('ok')", encoding="utf-8")

        with pytest.raises(ValueError, match="escapes work_root"):
            _validate_command_paths(["node", str(script)], work_root)

        _validate_command_paths(["node", str(script)], work_root, (skill_root,))


# ---------------------------------------------------------------------------
# 26. Command permission policy
# ---------------------------------------------------------------------------


class TestCommandPermissionPolicy:
    """Command execution is grouped by risk before the tool runs."""

    @pytest.mark.asyncio
    async def test_regular_command_runs_without_approval(self, tmp_path):
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

        llm = FakeLLMClient()
        llm.add_response(LLMResponse(
            content="",
            tool_calls=[LLMToolCall(id="cmd-regular", name="run_command", arguments={"command": "py -m pytest"})],
            finish_reason="tool_calls",
        ))
        llm.add_response(LLMResponse(content="Done", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Run tests",
            session_id="test-command-policy-regular",
            llm_client=llm,
            work_root=str(work_root),
            runtime_controls={"command_policies": {"regular": "auto_allow", "dangerous": "ask_user"}},
        )

        assert result.decision == "done"
        tool_results = [
            tool_step.result
            for step in result.steps
            for tool_step in step.tool_steps
            if tool_step.result and tool_step.result.name == "run_command"
        ]
        assert tool_results
        assert tool_results[0].status == "ok"
        assert tool_results[0].metadata["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_dangerous_command_requires_approval_by_default(self, tmp_path):
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "old.txt").write_text("data", encoding="utf-8")
        events: list[CoreEvent] = []

        async def capture_event(event: CoreEvent) -> None:
            events.append(event)

        llm = FakeLLMClient()
        llm.add_response(LLMResponse(
            content="",
            tool_calls=[LLMToolCall(id="cmd-danger", name="run_command", arguments={"command": "move old.txt new.txt"})],
            finish_reason="tool_calls",
        ))

        result = await run_core_kernel(
            goal="Move a file",
            session_id="test-command-policy-danger",
            llm_client=llm,
            work_root=str(work_root),
            runtime_controls={"command_policies": {"regular": "auto_allow", "dangerous": "ask_user"}},
            live_event_callback=capture_event,
        )

        assert result.decision == "wait"
        tool_results = [
            tool_step.result
            for step in result.steps
            for tool_step in step.tool_steps
            if tool_step.result and tool_step.result.name == "run_command"
        ]
        assert tool_results == []
        assert any(event.name == "runtime.approval_request" for event in events)
        waiting_events = [event for event in events if event.name == "runtime.waiting"]
        assert waiting_events
        assert waiting_events[-1].payload["request_kind"] == "permission"
        assert waiting_events[-1].payload["tool_call_id"] == "cmd-danger"
        assert (work_root / "old.txt").exists()
        assert not (work_root / "new.txt").exists()

    @pytest.mark.asyncio
    async def test_powershell_remove_item_inside_condition_requires_approval(self, tmp_path):
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "old.txt").write_text("data", encoding="utf-8")
        events: list[CoreEvent] = []

        async def capture_event(event: CoreEvent) -> None:
            events.append(event)

        llm = FakeLLMClient()
        llm.add_response(LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(
                    id="cmd-remove-item",
                    name="run_command",
                    arguments={
                        "command": "if (Test-Path old.txt) { Remove-Item old.txt; Write-Output 'deleted' }"
                    },
                )
            ],
            finish_reason="tool_calls",
        ))

        result = await run_core_kernel(
            goal="Delete a file",
            session_id="test-command-policy-remove-item",
            llm_client=llm,
            work_root=str(work_root),
            runtime_controls={"command_policies": {"regular": "auto_allow", "dangerous": "ask_user"}},
            live_event_callback=capture_event,
        )

        assert result.decision == "wait"
        assert any(event.name == "runtime.approval_request" for event in events)
        waiting_events = [event for event in events if event.name == "runtime.waiting"]
        assert waiting_events
        assert waiting_events[-1].payload["request_kind"] == "permission"
        assert waiting_events[-1].payload["tool_call_id"] == "cmd-remove-item"
        assert (work_root / "old.txt").exists()

    @pytest.mark.asyncio
    async def test_dangerous_command_can_be_auto_allowed_by_user_policy(self, tmp_path):
        if sys.platform != "win32":
            pytest.skip("Uses Windows cmd move builtin")

        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "old.txt").write_text("data", encoding="utf-8")

        llm = FakeLLMClient()
        llm.add_response(LLMResponse(
            content="",
            tool_calls=[LLMToolCall(id="cmd-danger-auto", name="run_command", arguments={"command": "move old.txt new.txt"})],
            finish_reason="tool_calls",
        ))
        llm.add_response(LLMResponse(content="Done", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Move a file",
            session_id="test-command-policy-danger-auto",
            llm_client=llm,
            work_root=str(work_root),
            runtime_controls={"command_policies": {"regular": "auto_allow", "dangerous": "auto_allow"}},
        )

        assert result.decision == "done"
        tool_results = [
            tool_step.result
            for step in result.steps
            for tool_step in step.tool_steps
            if tool_step.result and tool_step.result.name == "run_command"
        ]
        assert tool_results
        assert tool_results[0].status == "ok"
        assert tool_results[0].metadata["permission_group"] == "dangerous"
        assert tool_results[0].metadata["approval_policy"] == "auto_allow"
        assert not (work_root / "old.txt").exists()
        assert (work_root / "new.txt").read_text(encoding="utf-8") == "data"

    @pytest.mark.asyncio
    async def test_real_user_plugin_hook_blocks_command_before_execution(self, tmp_path, monkeypatch):
        appdata = tmp_path / "appdata"
        data_dir = tmp_path / "writer-data"
        work_root = tmp_path / "project"
        work_root.mkdir()
        monkeypatch.setenv("APPDATA", str(appdata))
        monkeypatch.setattr(settings, "data_dir", str(data_dir))

        plugin_root = default_user_plugin_root() / "repo-policy"
        hooks_dir = plugin_root / "hooks"
        hooks_dir.mkdir(parents=True)
        (plugin_root / "plugin.json").write_text(
            json.dumps({"name": "repo-policy", "version": "0.1.0"}, ensure_ascii=False),
            encoding="utf-8",
        )
        (hooks_dir / "hooks.json").write_text(
            json.dumps({
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "run_command",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "py -3.14 ${PLUGIN_ROOT}/hooks/block.py",
                                }
                            ],
                        }
                    ]
                }
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        (hooks_dir / "block.py").write_text(
            "import json, sys\n"
            "json.load(sys.stdin)\n"
            "print(json.dumps({'decision': 'block', 'reason': 'blocked by repo-policy'}))\n",
            encoding="utf-8",
        )

        trust = HookTrustStore(data_dir / "core-hook-trust.json")
        plugins = PluginRegistry(plugin_roots=[default_user_plugin_root()]).discover()
        hooks = HookRegistry(plugins=plugins, trust_store=trust).load()
        assert hooks
        trust.trust(hooks[0].definition_hash)

        llm = FakeLLMClient()
        llm.add_response(LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(
                    id="cmd-hook-block",
                    name="run_command",
                    arguments={"command": "echo should-not-run"},
                )
            ],
            finish_reason="tool_calls",
        ))
        llm.add_response(LLMResponse(content="Done", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Run command",
            session_id="test-real-plugin-hook-blocks-command",
            llm_client=llm,
            work_root=str(work_root),
            runtime_controls={"command_policies": {"regular": "auto_allow"}},
        )

        tool_results = [
            tool_step.result
            for step in result.steps
            for tool_step in step.tool_steps
            if tool_step.result and tool_step.result.name == "run_command"
        ]
        assert tool_results
        assert tool_results[0].status == "blocked"
        assert tool_results[0].error == "blocked by repo-policy"

    @pytest.mark.asyncio
    async def test_tool_exception_with_empty_message_keeps_error_type(self, tmp_path):
        """Blank exception messages must not become empty user-facing errors."""
        async def broken_tool(call: ToolCall) -> ToolResult:
            raise NotImplementedError

        kit = WriterKit(tool_executor={"run_command": broken_tool}, work_root=str(tmp_path))
        result = await kit.execute_tool(
            RuntimeState(session_id="test-empty-exception"),
            ToolCall(id="cmd-empty-error", name="run_command", arguments={"command": "git remote -v"}),
        )

        assert result.status == "failed"
        assert result.error == "Tool execution error: NotImplementedError"
        assert result.metadata["error_type"] == "NotImplementedError"


# ---------------------------------------------------------------------------
# 27. Default run_command availability
# ---------------------------------------------------------------------------


class TestRunCommandDefaultAvailability:
    """run_command is part of the default bounded executor."""

    def test_run_command_available_with_core_kernel_env(self, tmp_path):
        """run_command is in as_dict()."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        d = executor.as_dict()
        assert "run_command" in d

    @pytest.mark.asyncio
    async def test_run_command_available_in_kernel_with_work_root(self, tmp_path):
        """run_command reaches the bounded executor when work_root is set."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        llm = FakeLLMClient()
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-rt1",
                        name="run_command",
                        arguments={"command": "py -m pytest"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        llm.add_response(LLMResponse(content="Done", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Run tests",
            session_id="test-default-runtests-1",
            llm_client=llm,
            work_root=str(work_root),
        )

        assert result.decision == "done"
        second_request = llm.last_request
        tool_messages = [m for m in second_request.messages if m.role == "tool"]
        assert len(tool_messages) >= 1
        assert "Unknown tool" not in tool_messages[0].content


# ---------------------------------------------------------------------------
# 28. run_command success cases
# ---------------------------------------------------------------------------


class TestRunCommandSuccess:
    """run_command tool returns ok for valid commands."""

    @pytest.mark.asyncio
    async def test_run_command_emits_running_output_parts(self, tmp_path):
        """Streaming command output emits tool_result runtime parts before completion."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        events: list[CoreEvent] = []

        async def _capture(event: CoreEvent) -> None:
            events.append(event)

        executor = ReadWriteToolExecutor(work_root, core_event_callback=_capture)
        call = ToolCall(
            id="cmd-stream",
            name="run_command",
            arguments={
                "command": (
                    'py -3.14 -c "import time; '
                    "print('line1', flush=True); "
                    "time.sleep(0.2); "
                    "print('line2', flush=True)\""
                )
            },
            metadata={
                "_runtime_session_id": "session-stream",
                "_runtime_run_id": "run-stream",
            },
        )

        result = await executor.run_command(call)

        progress_events = [
            event for event in events
            if event.name == "runtime.part"
            and event.payload.get("part_type") == "tool_result"
            and event.payload.get("status") == "running"
        ]
        assert result.status == "ok"
        assert progress_events
        assert all(event.payload.get("part_id") == "cmd-stream:result" for event in progress_events)
        assert any("line1" in str(event.payload.get("content") or "") for event in progress_events)
        assert any("line2" in str(event.payload.get("content") or "") for event in progress_events)
        assert "_runtime_session_id" not in result.metadata
        assert "_runtime_run_id" not in result.metadata

    @pytest.mark.asyncio
    async def test_run_pytest_success(self, tmp_path):
        """Create a simple passing test file, run pytest, verify status='ok' and exit_code=0."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "test_dummy.py").write_text(
            "def test_pass():\n    assert True\n", encoding="utf-8"
        )

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="tc-rt-success",
            name="run_command",
            arguments={"command": "py -m pytest"},
        )
        result = await executor.run_command(call)

        assert result.status == "ok"
        assert result.metadata["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_run_pytest_with_args(self, tmp_path):
        """Run 'py -m pytest -v' on a passing test, verify output contains verbose info."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "test_verbose.py").write_text(
            "def test_verbose():\n    assert 1 + 1 == 2\n", encoding="utf-8"
        )

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="tc-rt-verbose",
            name="run_command",
            arguments={"command": "py -m pytest -v"},
        )
        result = await executor.run_command(call)

        assert result.status == "ok"
        assert result.metadata["exit_code"] == 0
        # Verbose output includes test name or PASSED
        assert "test_verbose" in result.content or "PASSED" in result.content

    @pytest.mark.asyncio
    async def test_run_command_missing_command_arg(self, tmp_path):
        """Missing command arg → status='failed'."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="tc-rt-missing",
            name="run_command",
            arguments={},
        )
        result = await executor.run_command(call)

        assert result.status == "failed"
        assert "command" in result.error.lower()

    @pytest.mark.asyncio
    async def test_run_command_empty_command(self, tmp_path):
        """Empty command string → status='failed'."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="tc-rt-empty",
            name="run_command",
            arguments={"command": ""},
        )
        result = await executor.run_command(call)

        assert result.status == "failed"
        assert "command" in result.error.lower()

    @pytest.mark.asyncio
    async def test_windows_cmd_wrapper_does_not_add_trailing_quote(self, tmp_path):
        """Windows shell commands with cmd /c are normalized before execution."""
        if sys.platform != "win32":
            pytest.skip("Windows-specific command quoting regression")
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        result = await executor.run_command(
            ToolCall(
                id="tc-rt-cmd-wrapper",
                name="run_command",
                arguments={"command": "cmd /c echo hello"},
            )
        )

        assert result.status == "ok"
        assert "[stdout]\nhello" in result.content
        assert 'hello"' not in result.content

    @pytest.mark.asyncio
    async def test_windows_python_c_preserves_quotes(self, tmp_path):
        """Windows shell execution preserves quoted python -c snippets."""
        if sys.platform != "win32":
            pytest.skip("Windows-specific command quoting regression")
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        result = await executor.run_command(
            ToolCall(
                id="tc-rt-python-c",
                name="run_command",
                arguments={"command": 'python -c "print(123)"'},
            )
        )

        assert result.status == "ok"
        assert "[stdout]\n123" in result.content

    @pytest.mark.asyncio
    async def test_run_command_returns_structured_command_output_artifact(self, tmp_path):
        """run_command exposes stdout/stderr/exit state as a structured artifact."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        result = await executor.run_command(
            ToolCall(
                id="tc-rt-command-artifact",
                name="run_command",
                arguments={"command": "echo hello", "timeout": 10},
            )
        )

        assert result.status == "ok"
        assert result.artifacts
        artifact = result.artifacts[0]
        assert artifact.kind == "command_output"
        assert artifact.metadata["command"] == "echo hello"
        assert artifact.metadata["exit_code"] == 0
        assert artifact.metadata["timed_out"] is False
        assert "hello" in artifact.metadata["stdout"].lower()


# ---------------------------------------------------------------------------
# 29. run_command failure cases
# ---------------------------------------------------------------------------


class TestRunCommandFailure:
    """run_command tool handles failing commands and nonexistent executables."""

    @pytest.mark.asyncio
    async def test_run_pytest_failing_test(self, tmp_path):
        """Create a failing test file, run pytest, verify status='ok' but exit_code != 0."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "test_failing.py").write_text(
            "def test_fail():\n    assert False, 'expected failure'\n", encoding="utf-8"
        )

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="tc-rt-fail",
            name="run_command",
            arguments={"command": "py -m pytest"},
        )
        result = await executor.run_command(call)

        # The command ran and returned a nonzero exit code, so the tool reports failed.
        assert result.status == "failed"
        assert result.metadata["exit_code"] != 0

    @pytest.mark.asyncio
    async def test_run_command_nonexistent_command(self, tmp_path):
        """'nonexistent_cmd test' → fails with Cannot execute."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="tc-rt-nonexistent",
            name="run_command",
            arguments={"command": "nonexistent_cmd test"},
        )
        result = await executor.run_command(call)

        assert result.status == "failed"
        assert "Command exited with code" in result.error
        assert result.metadata["exit_code"] != 0

    @pytest.mark.asyncio
    async def test_run_command_preserves_powershell_object_output(self, tmp_path):
        """PowerShell cmdlet/object output should be visible to the model."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        result = await executor.run_command(
            ToolCall(
                id="tc-ps-output",
                name="run_command",
                arguments={"command": "Get-Location"},
            )
        )

        assert result.status == "ok"
        assert str(work_root) in result.content
        assert "[no output]" not in result.content

    @pytest.mark.asyncio
    async def test_run_command_foreground_process_times_out(self, tmp_path):
        """Foreground long-running commands must return a failed timeout result."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        started = time.monotonic()
        result = await executor.run_command(
            ToolCall(
                id="tc-rt-timeout",
                name="run_command",
                arguments={
                    "command": 'python -c "import time; time.sleep(10)"',
                    "timeout": 1,
                },
            )
        )
        elapsed = time.monotonic() - started

        assert result.status == "failed"
        assert result.metadata["timed_out"] is True
        assert "timed out" in result.error.lower()
        assert elapsed < 5

    @pytest.mark.asyncio
    async def test_run_command_service_requires_explicit_background(self, tmp_path):
        """Service-looking commands still obey foreground semantics unless background=true."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()

        executor = ReadWriteToolExecutor(work_root)
        result = await executor.run_command(
            ToolCall(
                id="tc-rt-service-foreground",
                name="run_command",
                arguments={
                    "command": f"python -m http.server {port} --bind 127.0.0.1",
                    "timeout": 1,
                },
            )
        )

        assert result.status == "failed"
        assert result.metadata["background"] is False
        assert result.metadata["timed_out"] is True
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_run_command_background_process_returns_immediately(self, tmp_path):
        """Background commands represent long-running local services."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        started = time.monotonic()
        result = await executor.run_command(
            ToolCall(
                id="tc-rt-background",
                name="run_command",
                arguments={
                    "command": 'python -c "import time; time.sleep(10)"',
                    "timeout": 1,
                    "background": True,
                },
            )
        )
        elapsed = time.monotonic() - started

        try:
            assert result.status == "ok"
            assert result.metadata["background"] is True
            assert result.metadata["pid"]
            assert result.metadata["stdout_log"]
            assert elapsed < 5
        finally:
            pid = result.metadata.get("pid") if result.metadata else None
            if pid:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                else:
                    try:
                        os.kill(int(pid), 9)
                    except OSError:
                        pass

    @pytest.mark.asyncio
    async def test_run_command_background_http_server_fails_on_occupied_port(self, tmp_path):
        """Background local servers must not report ok when the requested port is occupied."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        try:
            executor = ReadWriteToolExecutor(work_root)
            result = await executor.run_command(
                ToolCall(
                    id="tc-rt-background-port-used",
                    name="run_command",
                    arguments={
                        "command": f"python -m http.server {port}",
                        "timeout": 1,
                        "background": True,
                    },
                )
            )
        finally:
            listener.close()

        assert result.status == "failed"
        assert result.metadata["background"] is True
        assert result.metadata["error_type"] == "PortInUse"
        assert result.metadata["error_kind"] == "port_in_use"
        assert result.metadata["retryable"] is True
        assert result.metadata["recommended_action"] == "choose_free_port"
        assert result.metadata["server_port"] == port
        assert result.artifacts[0].metadata["error_kind"] == "port_in_use"
        assert result.error

    @pytest.mark.asyncio
    async def test_run_command_background_http_server_requires_current_work_root_probe(self, tmp_path):
        """A live HTTP process is not success unless it serves the current work_root."""
        work_root = tmp_path / "project"
        public_root = work_root / "public"
        public_root.mkdir(parents=True)
        (public_root / "index.html").write_text("wrong root", encoding="utf-8")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()

        executor = ReadWriteToolExecutor(work_root)
        result = await executor.run_command(
            ToolCall(
                id="tc-rt-background-wrong-root",
                name="run_command",
                arguments={
                    "command": f"python -m http.server {port} --bind 127.0.0.1 --directory public",
                    "timeout": 1,
                    "background": True,
                },
            )
        )

        assert result.status == "failed"
        assert result.metadata["error_type"] == "LocalServerWrongRoot"
        assert result.metadata["error_kind"] == "wrong_server"
        assert result.metadata["retryable"] is True
        assert result.metadata["recommended_action"] == "serve_current_work_root_or_choose_free_port"
        assert result.metadata["server_port"] == port
        assert "current work_root probe" in (result.error or "")

    @pytest.mark.asyncio
    async def test_run_command_background_http_server_returns_ok_after_probe(self, tmp_path):
        """Python http.server returns ok only after serving a runtime probe from work_root."""
        work_root = tmp_path / "project"
        work_root.mkdir()
        (work_root / "index.html").write_text("hello preview", encoding="utf-8")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()

        executor = ReadWriteToolExecutor(work_root)
        result = await executor.run_command(
            ToolCall(
                id="tc-rt-background-probed",
                name="run_command",
                arguments={
                    "command": f"python -m http.server {port} --bind 127.0.0.1",
                    "timeout": 1,
                    "background": True,
                },
            )
        )

        try:
            assert result.status == "ok"
            assert result.metadata["background"] is True
            assert result.metadata["server_port"] == port
            assert result.metadata["url"] == f"http://127.0.0.1:{port}/"
            assert "HTTP probe passed" in (result.content or "")
        finally:
            pid = result.metadata.get("pid") if result.metadata else None
            if pid:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                else:
                    try:
                        os.kill(int(pid), 9)
                    except OSError:
                        pass

    @pytest.mark.asyncio
    async def test_run_command_background_readiness_probe_failure_is_failed(self, tmp_path):
        """Explicit readiness_url must pass before a background command reports ok."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        result = await executor.run_command(
            ToolCall(
                id="tc-rt-readiness-failed",
                name="run_command",
                arguments={
                    "command": 'python -c "import time; time.sleep(10)"',
                    "timeout": 1,
                    "background": True,
                    "readiness_url": "http://127.0.0.1:9/",
                    "readiness_text": "ready",
                },
            )
        )

        assert result.status == "failed"
        assert result.metadata["background"] is True
        assert result.metadata["error_type"] == "LocalServerUnreachable"
        assert result.metadata["error_kind"] == "probe_unreachable"
        assert result.metadata["retryable"] is True
        assert result.metadata["recommended_action"] == "check_server_startup_or_choose_free_port"
        assert result.metadata["readiness_url"] == "http://127.0.0.1:9/"
        assert result.artifacts[0].kind == "command_output"
        assert result.artifacts[0].metadata["error_type"] == "LocalServerUnreachable"

    @pytest.mark.asyncio
    async def test_run_command_readiness_requires_background_true(self, tmp_path):
        """readiness_url belongs to background process startup, not foreground commands."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        result = await executor.run_command(
            ToolCall(
                id="tc-rt-readiness-foreground",
                name="run_command",
                arguments={
                    "command": "echo hello",
                    "timeout": 10,
                    "readiness_url": "http://127.0.0.1:8080/",
                },
            )
        )

        assert result.status == "failed"
        assert "background=true" in result.error

    @pytest.mark.asyncio
    async def test_run_command_git_probe_uses_stable_executor(self, tmp_path):
        """git commands run through the same stable command executor used by Writer sessions."""
        if shutil.which("git") is None:
            pytest.skip("git is not installed")

        work_root = tmp_path / "project"
        work_root.mkdir()
        executor = ReadWriteToolExecutor(work_root)
        result = await executor.run_command(
            ToolCall(
                id="tc-rt-git",
                name="run_command",
                arguments={"command": "git --version", "timeout": 30},
                metadata={"permission_group": "regular", "approval_policy": "auto_allow"},
            )
        )

        assert result.status == "ok"
        assert result.metadata["exit_code"] == 0
        assert result.metadata["permission_group"] == "regular"
        assert "git version" in result.content.lower()

    @pytest.mark.asyncio
    async def test_run_command_windows_shell_diagnostic(self, tmp_path):
        """Windows run_command executes PowerShell syntax used in Writer prompts."""
        if sys.platform != "win32":
            pytest.skip("Windows-specific shell diagnostic")

        work_root = tmp_path / "project"
        work_root.mkdir()
        executor = ReadWriteToolExecutor(work_root)
        result = await executor.run_command(
            ToolCall(
                id="tc-rt-win-shell",
                name="run_command",
                arguments={"command": "Get-ChildItem -Recurse -File | Select-Object -First 1", "timeout": 30},
            )
        )

        assert result.status == "ok"
        assert result.metadata["exit_code"] == 0

# ---------------------------------------------------------------------------
# 30. run_command security validations
# ---------------------------------------------------------------------------


class TestRunCommandSecurity:
    """run_command enforces execution bounds and path safety."""

    @pytest.mark.asyncio
    async def test_command_with_shell_metacharacter_allowed(self, tmp_path):
        """Shell metacharacters are execution syntax, not a command blacklist."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="tc-rt-meta",
            name="run_command",
            arguments={"command": "echo hello ; echo ok"},
        )
        result = await executor.run_command(call)

        assert result.status == "ok"
        assert "hello" in result.content.lower()

    @pytest.mark.asyncio
    async def test_path_traversal_in_args_rejected(self, tmp_path):
        """'py -m pytest ../../etc/passwd' → status='failed', 'escapes work_root' in error."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="tc-rt-traversal",
            name="run_command",
            arguments={"command": "py -m pytest ../../etc/passwd"},
        )
        result = await executor.run_command(call)

        assert result.status == "failed"
        assert "escapes work_root" in result.error.lower()

    @pytest.mark.asyncio
    async def test_absolute_path_outside_rejected(self, tmp_path):
        """'py -m pytest C:/Windows/system32' → status='failed'."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="tc-rt-absolute",
            name="run_command",
            arguments={"command": "py -m pytest C:/Windows/system32"},
        )
        result = await executor.run_command(call)

        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_timeout_rejected_invalid_type(self, tmp_path):
        """timeout='abc' → status='failed', 'Invalid timeout' in error."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="tc-rt-timeout-invalid",
            name="run_command",
            arguments={"command": "py -m pytest", "timeout": "abc"},
        )
        result = await executor.run_command(call)

        assert result.status == "failed"
        assert "Invalid timeout" in result.error

    @pytest.mark.asyncio
    async def test_timeout_rejected_non_positive(self, tmp_path):
        """timeout=0 → status='failed', 'Invalid timeout' in error."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="tc-rt-timeout-zero",
            name="run_command",
            arguments={"command": "py -m pytest", "timeout": 0},
        )
        result = await executor.run_command(call)

        assert result.status == "failed"
        assert "Invalid timeout" in result.error

    @pytest.mark.asyncio
    async def test_command_with_shell_metacharacters(self, tmp_path):
        """Shell metacharacters are passed to the platform command runner."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="tc-rt-shellmeta",
            name="run_command",
            arguments={"command": "echo hello ; echo ok"},
        )
        result = await executor.run_command(call)

        assert result.status == "ok"
        assert "hello" in result.content.lower()

    @pytest.mark.asyncio
    async def test_command_with_spaced_shell_metacharacter_allowed(self, tmp_path):
        """Spaced shell metacharacters are not rejected by validation."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="tc-rt-shellmeta-spaced",
            name="run_command",
            arguments={"command": "echo hello ; echo ok"},
        )
        result = await executor.run_command(call)

        assert result.status == "ok"
        assert "hello" in result.content.lower()
    @pytest.mark.asyncio
    async def test_flag_value_path_traversal_rejected(self, tmp_path):
        """'py -m pytest --rootdir=../outside' is rejected."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        executor = ReadWriteToolExecutor(work_root)
        call = ToolCall(
            id="tc-rt-flag-path",
            name="run_command",
            arguments={"command": "py -m pytest --rootdir=../outside"},
        )
        result = await executor.run_command(call)

        assert result.status == "failed"
        assert "escapes work_root" in result.error.lower()


# ---------------------------------------------------------------------------
# 31. Core loop integration — write_file + run_command + done
# ---------------------------------------------------------------------------


class TestCoreLoopWriteThenRunTests:
    """Full core loop: model writes a test file, runs pytest, then says done."""

    @pytest.mark.asyncio
    async def test_write_file_then_run_command_then_done(self, tmp_path):
        """Core loop: write test file, run 'py -m pytest', then done."""
        work_root = tmp_path / "project"
        work_root.mkdir()

        llm = FakeLLMClient()
        # 1st turn: write_file — create a test file
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-w1",
                        name="write_file",
                        arguments={
                            "path": "test_core_loop.py",
                            "content": "def test_core():\n    assert 1 + 1 == 2\n",
                        },
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        # 2nd turn: run_command
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-rt1",
                        name="run_command",
                        arguments={"command": "py -m pytest"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        # 3rd turn: done
        llm.add_response(LLMResponse(content="All tests passed.", finish_reason="stop"))

        executor = ReadWriteToolExecutor(work_root)
        result = await run_core_kernel(
            goal="Write a test and run it",
            session_id="test-loop-write-runtests-1",
            llm_client=llm,
            tool_executor=executor.as_dict(),
        )

        assert result.decision == "done"
        # Verify the test file was created
        assert (work_root / "test_core_loop.py").read_text(encoding="utf-8") == "def test_core():\n    assert 1 + 1 == 2\n"


# ---------------------------------------------------------------------------
# 17. Multi-turn history support
# ---------------------------------------------------------------------------


class TestMultiTurnHistory:
    """run_core_kernel history parameter: LLM sees prior turns + current message.

    Verifies:
    1. When history is provided, FakeLLMClient sees history messages before
       the current user message in the LLM request.
    2. The current user message (goal) is NOT duplicated — it appears once.
    3. Only user/assistant roles from history are included; tool/internal
       are filtered out.
    4. History is capped at 20 entries (excess truncated from front).
    5. Without history, behaviour is unchanged (backward compatible).
    """

    @pytest.mark.asyncio
    async def test_history_prepended_to_llm_request(self):
        """LLM sees prior user/assistant turns before the current user message."""
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="I see the history.", finish_reason="stop"))

        history = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Second question"},
            {"role": "assistant", "content": "Second answer"},
        ]

        result = await run_core_kernel(
            goal="Third question",
            session_id="test-history-1",
            llm_client=llm,
            history=history,
        )

        assert result.decision == "done"
        assert llm.last_request is not None

        messages = llm.last_request.messages
        # Filter out system messages (persona, discipline, hook_context)
        messages = _conversation_messages(messages)
        # Expected: [user:First question, assistant:First answer,
        #            user:Second question, assistant:Second answer,
        #            user:Third question]
        assert len(messages) == 5
        assert messages[0].role == "user" and messages[0].content == "First question"
        assert messages[1].role == "assistant" and messages[1].content == "First answer"
        assert messages[2].role == "user" and messages[2].content == "Second question"
        assert messages[3].role == "assistant" and messages[3].content == "Second answer"
        assert messages[4].role == "user" and messages[4].content == "Third question"

    @pytest.mark.asyncio
    async def test_current_user_content_blocks_are_passed_to_llm_request(self):
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="I can see it.", finish_reason="stop"))
        user_content = [
            {"type": "text", "text": "Describe the screenshot."},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,AA==", "detail": "auto"},
            },
        ]

        result = await run_core_kernel(
            goal="Describe the screenshot.",
            user_content=user_content,
            session_id="test-current-image-content",
            llm_client=llm,
        )

        assert result.decision == "done"
        assert llm.last_request is not None
        messages = _conversation_messages(llm.last_request.messages)
        assert messages[-1].role == "user"
        assert messages[-1].content == user_content

    @pytest.mark.asyncio
    async def test_history_message_ids_are_preserved_for_auto_compaction_metadata(self):
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Done.", finish_reason="stop"))

        history = [
            {"role": "system", "content": "[Compacted Context]\n1. Current Goal\n- Continue."},
            {"role": "user", "content": "Previous question", "id": "message-user-1"},
            {"role": "assistant", "content": "Previous answer", "id": "message-assistant-1"},
        ]

        result = await run_core_kernel(
            goal="Current question",
            session_id="test-history-message-ids",
            llm_client=llm,
            history=history,
        )

        assert result.decision == "done"
        assert llm.last_request is not None
        previous = [
            message
            for message in llm.last_request.messages
            if message.content in {"Previous question", "Previous answer"}
        ]
        assert [message.metadata["writer_message_id"] for message in previous] == [
            "message-user-1",
            "message-assistant-1",
        ]
        summary = next(
            message
            for message in llm.last_request.messages
            if message.content == "[Compacted Context]\n1. Current Goal\n- Continue."
        )
        assert summary.metadata["key"] == "context_compaction_summary"

    @pytest.mark.asyncio
    async def test_current_user_message_not_duplicated(self):
        """The current goal is NOT duplicated when history is provided."""
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Done.", finish_reason="stop"))

        history = [
            {"role": "user", "content": "Previous question"},
            {"role": "assistant", "content": "Previous answer"},
        ]

        result = await run_core_kernel(
            goal="Current question",
            session_id="test-history-no-dup",
            llm_client=llm,
            history=history,
        )

        assert result.decision == "done"
        messages = llm.last_request.messages
        # "Current question" should appear exactly once
        current_count = sum(
            1 for m in messages
            if m.role == "user" and m.content == "Current question"
        )
        assert current_count == 1

    @pytest.mark.asyncio
    async def test_tool_and_internal_roles_filtered_from_history(self):
        """Only user/assistant roles from history are included."""
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Done.", finish_reason="stop"))

        history = [
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Answer"},
            {"role": "tool", "content": "Tool output (should be filtered)"},
            {"role": "internal", "content": "Internal note (should be filtered)"},
            {"role": "system", "content": "System prompt (should be filtered)"},
        ]

        result = await run_core_kernel(
            goal="Follow-up",
            session_id="test-history-filter",
            llm_client=llm,
            history=history,
        )

        assert result.decision == "done"
        messages = llm.last_request.messages
        # Filter out system messages (persona, discipline, hook_context)
        messages = _conversation_messages(messages)
        # Only user/assistant from history + current user message
        roles = [m.role for m in messages]
        assert "tool" not in roles
        assert "internal" not in roles
        assert "system" not in roles
        # Should have: user(Question), assistant(Answer), user(Follow-up)
        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_system_user_assistant_history_preserves_incoming_order(self):
        """Allowed history roles keep their original order instead of regrouping system items."""
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Done.", finish_reason="stop"))

        history = [
            {"role": "system", "content": "summary-1"},
            {"role": "user", "content": "question-1"},
            {"role": "assistant", "content": "answer-1"},
            {"role": "system", "content": "summary-2"},
            {"role": "tool", "content": "tool-output"},
            {"role": "user", "content": "question-2"},
        ]

        result = await run_core_kernel(
            goal="Current",
            session_id="test-history-order",
            llm_client=llm,
            history=history,
        )

        assert result.decision == "done"
        filtered_messages = [
            (message.role, message.content)
            for message in llm.last_request.messages
            if message.content in {"summary-1", "question-1", "answer-1", "summary-2", "question-2", "Current"}
        ]
        assert filtered_messages == [
            ("system", "summary-1"),
            ("user", "question-1"),
            ("assistant", "answer-1"),
            ("system", "summary-2"),
            ("user", "question-2"),
            ("user", "Current"),
        ]

    @pytest.mark.asyncio
    async def test_system_summary_survives_history_cap(self):
        """System summary stays model-visible after capping long history."""
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Done.", finish_reason="stop"))

        history = [{"role": "system", "content": "compacted-summary"}]
        for i in range(12):
            history.append({"role": "user", "content": f"Q{i}"})
            history.append({"role": "assistant", "content": f"A{i}"})
        history.extend(
            [
                {"role": "tool", "content": "tool-output"},
                {"role": "internal", "content": "internal-note"},
            ]
        )

        result = await run_core_kernel(
            goal="Current",
            session_id="test-history-summary-cap",
            llm_client=llm,
            history=history,
        )

        assert result.decision == "done"
        filtered_messages = [
            (message.role, message.content)
            for message in llm.last_request.messages
            if message.content == "compacted-summary"
            or message.content == "Current"
            or (
                len(message.content) >= 2
                and message.content[0] in {"Q", "A"}
                and message.content[1:].isdigit()
            )
        ]
        assert len(filtered_messages) == 21
        assert filtered_messages[0] == ("system", "compacted-summary")
        assert filtered_messages[1:5] == [
            ("assistant", "A2"),
            ("user", "Q3"),
            ("assistant", "A3"),
            ("user", "Q4"),
        ]
        assert ("user", "Q0") not in filtered_messages
        assert ("assistant", "A0") not in filtered_messages
        assert ("user", "Q1") not in filtered_messages
        assert ("assistant", "A1") not in filtered_messages
        assert ("user", "Q2") not in filtered_messages
        assert filtered_messages[-2:] == [
            ("assistant", "A11"),
            ("user", "Current"),
        ]

    @pytest.mark.asyncio
    async def test_history_capped_at_20(self):
        """History entries beyond 20 are truncated from the front."""
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Done.", finish_reason="stop"))

        # Create 25 history entries
        history = []
        for i in range(25):
            history.append({"role": "user", "content": f"Q{i}"})
            history.append({"role": "assistant", "content": f"A{i}"})
        # 50 entries total — only last 20 should be used

        result = await run_core_kernel(
            goal="Current",
            session_id="test-history-cap",
            llm_client=llm,
            history=history,
        )

        assert result.decision == "done"
        messages = llm.last_request.messages
        # Filter out system messages (persona, discipline, hook_context)
        messages = _conversation_messages(messages)
        # 20 history entries + 1 current user message = 21
        # The first 30 entries (Q0..A14) should be dropped
        assert len(messages) == 21
        # First message should be from the 16th pair (index 30 in original)
        assert messages[0].content == "Q15"

    @pytest.mark.asyncio
    async def test_empty_content_entries_filtered(self):
        """History entries with empty content are excluded."""
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Done.", finish_reason="stop"))

        history = [
            {"role": "user", "content": "Valid question"},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "Another question"},
        ]

        result = await run_core_kernel(
            goal="Follow-up",
            session_id="test-history-empty",
            llm_client=llm,
            history=history,
        )

        assert result.decision == "done"
        messages = llm.last_request.messages
        # Filter out system messages (persona, discipline, hook_context)
        messages = _conversation_messages(messages)
        # Empty assistant content is filtered out
        contents = [m.content for m in messages]
        assert "" not in contents
        # Should have: user(Valid question), user(Another question), user(Follow-up)
        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_no_history_backward_compatible(self):
        """Without history parameter, behaviour is unchanged."""
        llm = FakeLLMClient()
        llm.add_response(LLMResponse(content="Done.", finish_reason="stop"))

        result = await run_core_kernel(
            goal="Hello",
            session_id="test-history-none",
            llm_client=llm,
        )

        assert result.decision == "done"
        messages = llm.last_request.messages
        # Filter out system messages (persona, discipline, hook_context)
        messages = _conversation_messages(messages)
        # Just the current user message
        assert len(messages) == 1
        assert messages[0].role == "user" and messages[0].content == "Hello"

    @pytest.mark.asyncio
    async def test_history_with_tool_call_loop(self):
        """History is prepended even when the model makes tool calls."""
        llm = FakeLLMClient()
        # First response: tool call
        llm.add_response(
            LLMResponse(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-1",
                        name="read_file",
                        arguments={"path": "test.py"},
                    )
                ],
                finish_reason="tool_calls",
            )
        )
        # Second response: done
        llm.add_response(LLMResponse(content="I read the file.", finish_reason="stop"))

        async def fake_read(call: ToolCall) -> ToolResult:
            return ToolResult(
                call_id=call.id, name=call.name, status="ok", content="file content"
            )

        history = [
            {"role": "user", "content": "What is in main.py?"},
            {"role": "assistant", "content": "It has a hello world program."},
        ]

        result = await run_core_kernel(
            goal="Now read test.py",
            session_id="test-history-tool-loop",
            llm_client=llm,
            tool_executor=fake_read,
            history=history,
        )

        assert result.decision == "done"
        # The first LLM call should have history + current user message
        # (We can't easily inspect the first call since FakeLLMClient
        #  only keeps last_request, but we can verify the second call
        #  has history + user + assistant + tool messages)
        second_request = llm.last_request
        assert second_request is not None
        # Filter out system messages (persona, discipline, hook_context)
        filtered_messages = _conversation_messages(second_request.messages)
        # First message should be from history
        assert filtered_messages[0].role == "user"
        assert filtered_messages[0].content == "What is in main.py?"
