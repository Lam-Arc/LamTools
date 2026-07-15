from __future__ import annotations

import pytest

from lamtools_core.app.base_agent import CoreBaseAgentKit
from lamtools_core.kernel import KernelStep, KernelTurn, VerificationResult
from lamtools_core.runtime import RuntimeState, RuntimeToolStep
from lamtools_core.tool import ToolArtifact, ToolCall, ToolResult


class _CapturingToolbox:
    def __init__(self) -> None:
        self.call: ToolCall | None = None

    async def execute(self, call: ToolCall) -> ToolResult:
        self.call = call
        return ToolResult(call_id=call.id, name=call.name, status="ok")


@pytest.mark.asyncio
async def test_base_agent_attaches_runtime_ownership_to_every_tool_call(tmp_path):
    toolbox = _CapturingToolbox()
    kit = CoreBaseAgentKit(work_root=tmp_path, toolbox=toolbox)  # type: ignore[arg-type]
    state = RuntimeState(session_id="parent:sub:worker", run_id="child-run")

    await kit.execute_tool(
        state,
        ToolCall(id="call-ownership", name="run_command", arguments={"command": "echo ok"}),
    )

    assert toolbox.call is not None
    assert toolbox.call.metadata["_runtime_session_id"] == "parent:sub:worker"
    assert toolbox.call.metadata["_runtime_run_id"] == "child-run"


@pytest.mark.asyncio
async def test_failed_tool_result_exposes_existing_execution_evidence_without_advice(tmp_path):
    kit = CoreBaseAgentKit(work_root=tmp_path)
    call = ToolCall(id="call-1", name="run_command", arguments={"command": "demo"})
    result = ToolResult(
        call_id=call.id,
        name=call.name,
        status="failed",
        error="Command exited with code 1",
        artifacts=[ToolArtifact(
            kind="command_output",
            metadata={"stdout": "out", "stderr": "boom"},
        )],
        metadata={
            "cwd": str(tmp_path),
            "exit_code": 1,
            "stdout_log": str(tmp_path / "stdout.log"),
            "stderr_log": str(tmp_path / "stderr.log"),
            "recommended_action": "guess_a_fix",
            "retryable": False,
        },
    )

    message = await kit.format_tool_result_for_model(RuntimeState(session_id="s1"), call, result)
    content = str(message.content)

    assert "status: failed" in content
    assert "error: Command exited with code 1" in content
    assert "exit_code: 1" in content
    assert f"cwd: {tmp_path}" in content
    assert "stdout: out" in content
    assert "stderr: boom" in content
    assert "stdout_log:" in content
    assert "stderr_log:" in content
    assert "recommended_action" not in content
    assert "retryable" not in content


@pytest.mark.asyncio
async def test_tool_evidence_is_redacted_and_truncated(tmp_path):
    kit = CoreBaseAgentKit(work_root=tmp_path)
    call = ToolCall(id="call-2", name="run_command")
    result = ToolResult(
        call_id=call.id,
        name=call.name,
        status="failed",
        content="Authorization: Bearer secret-value\n" + ("x" * 40_000),
        metadata={"exit_code": 1},
    )

    message = await kit.format_tool_result_for_model(RuntimeState(session_id="s2"), call, result)
    content = str(message.content)

    assert "secret-value" not in content
    assert "[REDACTED]" in content
    assert "[tool evidence truncated]" in content
    assert len(content) < 20_000


@pytest.mark.asyncio
async def test_base_agent_returns_delegated_no_progress_to_parent_loop(tmp_path):
    kit = CoreBaseAgentKit(work_root=tmp_path)
    state = RuntimeState(session_id="parent")
    call = ToolCall(id="sub-1", name="sub_agent")
    result = ToolResult(
        call_id=call.id,
        name=call.name,
        status="blocked",
        metadata={
            "decision": "wait",
            "wait_reason": "no_progress",
            "pending_waiting_request": {
                "request_kind": "no_progress",
                "message": "same failure observed four times",
            },
            "delegated_session": {"session_id": "parent:sub:worker"},
        },
    )
    step = KernelStep(
        index=0,
        state_before=state,
        tool_steps=[RuntimeToolStep(call=call, result=result)],
    )

    decision = await kit.decide_next(
        state,
        KernelTurn(tool_calls=[call]),
        VerificationResult(passed=False),
        step,
    )

    assert decision == "continue"
    assert "no_progress" not in state.metadata
    assert "pending_waiting_request" not in state.metadata
    assert "pending_approval" not in state.metadata
