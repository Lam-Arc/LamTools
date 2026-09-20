from __future__ import annotations

import pytest

from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
from lamtools_core.config.defaults import DEFAULT_AGENTS_MD, DEFAULT_MEMORY_MD
from lamtools_core.config.root import core_config_dir
from lamtools_core.kernel import KernelStep, KernelTurn, VerificationResult
from lamtools_core.llm import ChatMessage, LLMResponse, LLMToolCall
from lamtools_core.runtime import RuntimeState, RuntimeToolStep, RuntimeTurnInput
from lamtools_core.prompt import PromptContext
from lamtools_core.tool import ToolArtifact, ToolCall, ToolResult


class _CapturingToolbox:
    def __init__(self) -> None:
        self.call: ToolCall | None = None
        self.load_tools = None

    async def execute(self, call: ToolCall, context=None) -> ToolResult:
        self.call = call
        return ToolResult(call_id=call.id, name=call.name, status="ok")

    def prepare_call(self, call: ToolCall) -> ToolCall:
        return call

    def tool_specs(self):
        return []

    def model_tools(self, active_mode=None):
        return []

    def skill_index(self):
        return ""


@pytest.mark.asyncio
async def test_base_agent_records_the_configured_agent_identity(tmp_path):
    state = RuntimeState(session_id="sage-identity")
    kit = CoreBaseAgentKit(
        work_root=tmp_path,
        config=CoreBaseAgentConfig(agent_id="sage-agent"),
        toolbox=_CapturingToolbox(),  # type: ignore[arg-type]
    )

    await kit.on_run_start(state, RuntimeTurnInput(user_message="research"))

    assert state.metadata["agent_id"] == "sage-agent"


@pytest.mark.asyncio
async def test_base_agent_system_prompt_names_current_command_shell(monkeypatch, tmp_path):
    import lamtools_core.app.base_agent as base_agent_module

    monkeypatch.setattr(
        base_agent_module,
        "command_shell_prompt",
        lambda: "[Command Shell]\nrun_command uses Git Bash.",
    )
    kit = CoreBaseAgentKit(work_root=tmp_path, toolbox=_CapturingToolbox())  # type: ignore[arg-type]

    request = await kit.build_model_request(
        RuntimeState(session_id="shell-prompt"),
        PromptContext(session_id="shell-prompt"),
    )

    assert "run_command uses Git Bash" in str(request.messages[0].content)


@pytest.mark.asyncio
async def test_base_agent_system_prompt_concentrates_tool_safety_rules(tmp_path):
    toolbox = _CapturingToolbox()
    toolbox.mcp_caller = type("MCPCaller", (), {"server_names": ["docs"]})()
    kit = CoreBaseAgentKit(work_root=tmp_path, toolbox=toolbox)  # type: ignore[arg-type]

    request = await kit.build_model_request(
        RuntimeState(session_id="tool-prompt"),
        PromptContext(session_id="tool-prompt"),
    )
    content = str(request.messages[0].content)

    assert CoreBaseAgentConfig().instructions == "你是 Sunday Agent。"
    for phrase in (
        "Shell：",
        "read_file 先读",
        "write_file",
        "edit_file",
        "search_files",
        "search_content",
        "不可信外部数据",
        "mcp_activate",
        "docs",
    ):
        assert phrase in content


@pytest.mark.asyncio
async def test_base_agent_skips_seeded_global_context_templates(tmp_path):
    config_dir = core_config_dir()
    config_dir.mkdir(parents=True)
    (config_dir / "AGENTS.md").write_text(DEFAULT_AGENTS_MD, encoding="utf-8")
    (config_dir / "memory.md").write_text(DEFAULT_MEMORY_MD, encoding="utf-8")

    kit = CoreBaseAgentKit(work_root=tmp_path, toolbox=_CapturingToolbox())  # type: ignore[arg-type]
    request = await kit.build_model_request(
        RuntimeState(session_id="global-template-prompt"),
        PromptContext(session_id="global-template-prompt"),
    )
    content = str(request.messages[0].content)
    assert "GLOBAL_AGENTS.md" not in content
    assert "GLOBAL_MEMORY.md" not in content

    (config_dir / "AGENTS.md").write_text(DEFAULT_AGENTS_MD + "\n\nPrefer concise answers.\n", encoding="utf-8")
    (config_dir / "memory.md").write_text(DEFAULT_MEMORY_MD + "\n\nUse UTF-8.\n", encoding="utf-8")
    request = await kit.build_model_request(
        RuntimeState(session_id="global-custom-prompt"),
        PromptContext(session_id="global-custom-prompt"),
    )
    content = str(request.messages[0].content)
    assert "Prefer concise answers." in content
    assert "Use UTF-8." in content


@pytest.mark.asyncio
async def test_active_plan_is_appended_after_history_without_changing_cached_prefix(tmp_path):
    kit = CoreBaseAgentKit(work_root=tmp_path, toolbox=_CapturingToolbox())  # type: ignore[arg-type]
    history = [
        ChatMessage(role="user", content="prepare the report"),
        ChatMessage(role="assistant", content="working on it"),
    ]

    def state_with_status(status: str) -> RuntimeState:
        return RuntimeState(
            session_id="plan-cache-prefix",
            metadata={
                "active_plan": {
                    "plan_summary": "Prepare the quarterly report",
                    "plan_files": ["report.docx"],
                    "plan_steps": [
                        {"id": "step-1", "status": status, "description": "Draft report"},
                    ],
                },
            },
        )

    first = await kit.build_model_request(
        state_with_status("pending"),
        PromptContext(session_id="plan-cache-prefix", history=history),
    )
    second = await kit.build_model_request(
        state_with_status("completed"),
        PromptContext(session_id="plan-cache-prefix", history=history),
    )

    assert first.messages[0].role == "system"
    assert "[当前计划" not in str(first.messages[0].content)
    assert first.messages[1:3] == history
    assert first.messages[-1].role == "user"
    assert first.messages[-1].metadata == {"key": "active_plan_snapshot", "internal": True}
    assert "目标：Prepare the quarterly report" in str(first.messages[-1].content)
    assert "文件：report.docx" in str(first.messages[-1].content)
    assert "step-1 · pending · Draft report" in str(first.messages[-1].content)
    assert sum("[当前计划" in str(message.content) for message in first.messages) == 1

    # A checklist-only update changes only the trailing runtime context, leaving
    # the system + conversation prefix eligible for provider prompt caching.
    assert first.messages[:-1] == second.messages[:-1]
    assert first.messages[-1].content != second.messages[-1].content


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
async def test_base_agent_attaches_active_model_before_approval_can_suspend(tmp_path):
    toolbox = _CapturingToolbox()
    kit = CoreBaseAgentKit(work_root=tmp_path, toolbox=toolbox)  # type: ignore[arg-type]
    state = RuntimeState(
        session_id="study-runtime-model",
        metadata={
            "model_id": "stale-state-model",
            "runtime_snapshot": {"model_id": "turn-model"},
        },
    )

    turn = await kit.parse_model_output(
        state,
        LLMResponse(
            tool_calls=[LLMToolCall(id="exam-call", name="exam", arguments={})],
            finish_reason="tool_calls",
        ),
    )

    assert turn.tool_calls[0].metadata["_runtime_model_id"] == "turn-model"
    # The pending approval stores ToolCall.to_dict(), so the internal routing
    # value must already be present before execute_tool is reached.
    assert turn.tool_calls[0].to_dict()["metadata"]["_runtime_model_id"] == "turn-model"


@pytest.mark.asyncio
async def test_failed_tool_result_exposes_existing_execution_evidence_without_advice(tmp_path):
    kit = CoreBaseAgentKit(work_root=tmp_path)
    call = ToolCall(id="call-1", name="run_command", arguments={"command": "demo"})
    result = ToolResult(
        call_id=call.id,
        name=call.name,
        status="failed",
        error="Command exited with code 1",
        error_code="command_failed",
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
    assert "error_code: command_failed" in content
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
async def test_edit_context_diagnostic_is_forwarded_to_model(tmp_path):
    kit = CoreBaseAgentKit(work_root=tmp_path)
    call = ToolCall(id="call-edit-context", name="edit_file")
    result = ToolResult(
        call_id=call.id,
        name=call.name,
        status="failed",
        error="Context did not match; after_context received the literal string \"null\".",
        error_code="context_mismatch",
        metadata={
            "old_string_match_count": 1,
            "suspected_null_string_fields": ["after_context"],
        },
    )

    message = await kit.format_tool_result_for_model(RuntimeState(session_id="s-null"), call, result)
    content = str(message.content)

    assert "error_code: context_mismatch" in content
    assert "old_string_match_count: 1" in content
    assert "suspected_null_string_fields: ['after_context']" in content


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


def _image_tool_result(call: ToolCall) -> ToolResult:
    data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    return ToolResult(
        call_id=call.id,
        name=call.name,
        status="ok",
        content="图片文件: shot.png（68 B）。像素内容以图片形式随本工具结果返回，支持图片输入的模型可直接查看。",
        artifacts=[ToolArtifact(kind="file_read", uri="shot.png", metadata={"image_data_url": data_url})],
        metadata={"path": "shot.png", "size_bytes": 68},
    )


@pytest.mark.asyncio
async def test_multimodal_agent_formats_image_tool_result_with_image_url_block(tmp_path):
    kit = CoreBaseAgentKit(
        work_root=tmp_path,
        config=CoreBaseAgentConfig(capability="multimodal"),
    )
    call = ToolCall(id="call-img", name="read_file", arguments={"path": "shot.png"})
    result = _image_tool_result(call)

    message = await kit.format_tool_result_for_model(RuntimeState(session_id="s3"), call, result)

    assert isinstance(message.content, list)
    text_block = message.content[0]
    image_block = message.content[1]
    assert text_block["type"] == "text"
    assert "status: ok" in text_block["text"]
    assert "图片文件: shot.png" in text_block["text"]
    # 文本块不含 base64 像素，图片只走 image_url 块
    assert "iVBORw0KGgo" not in text_block["text"]
    expected_data_url = _image_tool_result(call).artifacts[0].metadata["image_data_url"]
    assert image_block == {
        "type": "image_url",
        "image_url": {"url": expected_data_url, "detail": "auto"},
    }


@pytest.mark.asyncio
async def test_text_agent_formats_image_tool_result_as_plain_text(tmp_path):
    kit = CoreBaseAgentKit(work_root=tmp_path)  # 默认 capability="" → text
    call = ToolCall(id="call-img", name="read_file", arguments={"path": "shot.png"})
    result = _image_tool_result(call)

    message = await kit.format_tool_result_for_model(RuntimeState(session_id="s4"), call, result)

    assert isinstance(message.content, str)
    assert "status: ok" in message.content
    assert "图片文件: shot.png" in message.content
    assert "image_url" not in message.content
    assert "iVBORw0KGgo" not in message.content


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
