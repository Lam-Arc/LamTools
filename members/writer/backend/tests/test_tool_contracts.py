# -*- coding: utf-8 -*-
"""Contract checks for Writer tool exposure and default execution."""

from __future__ import annotations

import shutil
import subprocess

import httpx
import pytest
from pathlib import Path

from lamtools_core.llm import LLMRequest, LLMResponse, LLMToolCall
from lamtools_core.kernel import KernelTurn, VerificationResult
from lamtools_core.prompt import PromptContext
from lamtools_core.runtime import RuntimeState
from lamtools_core.tool import ToolCall

from app.core.prompt_assembler import WRITER_TOOLS
from lamtools_core.tool import web_tools
from app.core.writer.core_kernel_adapter import ReadWriteToolExecutor, WriterKit, run_core_kernel
from app.core.writer.permission import TOOL_PERMISSIONS
from app.core.writer.tool_specs import WRITER_TOOL_SPECS, writer_model_tools


def _writer_tool_names() -> set[str]:
    return {str(tool["function"]["name"]) for tool in WRITER_TOOLS}


class _FakeLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        _ = request
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="done", finish_reason="stop")


class _FakeAgentLLM:
    async def chat_full(self, messages, tools=None, **kwargs):
        _ = messages, tools, kwargs
        return LLMResponse(content="{}", finish_reason="stop")

    def stream(self, request: LLMRequest):
        _ = request
        raise NotImplementedError


def test_default_runtime_does_not_advertise_missing_regular_tools(tmp_path):
    executor = ReadWriteToolExecutor(tmp_path).as_dict()
    kit = WriterKit(tool_executor=executor, work_root=str(tmp_path))

    effective = {str(tool["function"]["name"]) for tool in kit._effective_tools}
    advertised = _writer_tool_names()

    assert "browser_check" in executor
    assert "browser_check" in effective
    assert effective <= set(executor.keys())
    assert effective == advertised & set(executor.keys())


def test_default_executor_tools_have_declarative_specs(tmp_path):
    executor = ReadWriteToolExecutor(tmp_path).as_dict()
    spec_names = {str(spec["name"]) for spec in WRITER_TOOL_SPECS}

    assert set(executor.keys()) <= spec_names


@pytest.mark.asyncio
async def test_load_skill_is_available_and_loads_body_on_demand(tmp_path):
    skill_dir = tmp_path / ".agents" / "skills" / "reviewer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: reviewer\ndescription: Review code changes\n---\n"
        "FULL REVIEW WORKFLOW\n",
        encoding="utf-8",
    )
    executor = ReadWriteToolExecutor(tmp_path)

    result = await executor.load_skill(ToolCall(id="skill-1", name="load_skill", arguments={"name": "reviewer"}))

    assert result.status == "ok"
    assert "FULL REVIEW WORKFLOW" in result.content
    assert result.metadata["found"] is True


@pytest.mark.asyncio
async def test_load_skill_discovers_codex_skills(tmp_path):
    skill_dir = tmp_path / ".codex" / "skills" / "reviewer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: reviewer\ndescription: Review code changes\n---\n"
        "CODEX REVIEW WORKFLOW\n",
        encoding="utf-8",
    )
    executor = ReadWriteToolExecutor(tmp_path)

    result = await executor.load_skill(ToolCall(id="skill-codex", name="load_skill", arguments={"name": "reviewer"}))

    assert result.status == "ok"
    assert "CODEX REVIEW WORKFLOW" in result.content
    assert str(skill_dir).replace("\\", "/") in result.metadata["resource_roots"]


@pytest.mark.asyncio
async def test_load_skill_discovers_core_and_member_resource_skills(monkeypatch, tmp_path):
    core_root = tmp_path / "runtime" / "core"
    writer_root = tmp_path / "runtime" / "members" / "writer"
    core_skill = core_root / "skills" / "shared-review"
    writer_skill = writer_root / "skills" / "shared-review"
    core_only = core_root / "skills" / "core-only"
    core_skill.mkdir(parents=True)
    writer_skill.mkdir(parents=True)
    core_only.mkdir(parents=True)
    (core_skill / "SKILL.md").write_text(
        "---\nname: shared-review\ndescription: Shared review\n---\nCORE WORKFLOW\n",
        encoding="utf-8",
    )
    (writer_skill / "SKILL.md").write_text(
        "---\nname: shared-review\ndescription: Writer review\n---\nWRITER WORKFLOW\n",
        encoding="utf-8",
    )
    (core_only / "SKILL.md").write_text(
        "---\nname: core-only\ndescription: Core only\n---\nCORE ONLY WORKFLOW\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LAMTOOLS_CORE_RESOURCE_DIR", str(core_root))
    monkeypatch.setenv("LAMWRITER_MEMBER_RESOURCE_DIR", str(writer_root))
    executor = ReadWriteToolExecutor(tmp_path)

    shared = await executor.load_skill(ToolCall(id="skill-shared", name="load_skill", arguments={"name": "shared-review"}))
    core = await executor.load_skill(ToolCall(id="skill-core", name="load_skill", arguments={"name": "core-only"}))

    assert shared.status == "ok"
    assert "WRITER WORKFLOW" in shared.content
    assert "CORE WORKFLOW" not in shared.content
    assert core.status == "ok"
    assert "CORE ONLY WORKFLOW" in core.content


@pytest.mark.asyncio
async def test_core_prompt_injects_skill_index_after_stable_prefix(tmp_path):
    skill_dir = tmp_path / ".agents" / "skills" / "reviewer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: reviewer\ndescription: Review code changes\n---\n"
        "FULL REVIEW WORKFLOW\n",
        encoding="utf-8",
    )
    kit = WriterKit(work_root=str(tmp_path))
    state = RuntimeState(session_id="skill-index")
    context = PromptContext(
        session_id="skill-index",
        user_message="review",
        history=[],
        state=state,
    )

    request = await kit.build_model_request(state, context)
    system_messages = [message for message in request.messages if message.role == "system"]
    keys = [str(message.metadata.get("key") or "") for message in system_messages]

    assert keys[:4] == ["persona", "execution_discipline", "platform", "skill_index"]
    skill_msg = next(message for message in system_messages if message.metadata.get("key") == "skill_index")
    assert "<name>reviewer</name>" in skill_msg.content
    assert "Review code changes" in skill_msg.content
    assert "FULL REVIEW WORKFLOW" not in skill_msg.content
    assert keys.index("skill_index") < keys.index("runtime_now")


def test_advertised_tools_have_permissions_and_declarative_specs():
    spec_names = {str(spec["name"]) for spec in WRITER_TOOL_SPECS}
    for name in _writer_tool_names():
        assert name in TOOL_PERMISSIONS, f"{name} missing permission"
        assert name in spec_names, f"{name} missing tool spec"


def test_advertised_tools_are_generated_from_declarative_specs():
    assert WRITER_TOOLS == writer_model_tools()


def test_writer_tool_specs_are_the_single_schema_source():
    source = (Path(__file__).resolve().parents[1] / "app/core/writer/tool_specs.py").read_text(encoding="utf-8")

    assert "MODEL_TOOL_FUNCTIONS" not in source


def test_writer_default_executor_reuses_core_toolbox_for_base_tools():
    source = (Path(__file__).resolve().parents[1] / "app/core/writer/tools.py").read_text(encoding="utf-8")

    assert "build_core_toolbox" in source
    assert "make_write_file_handler" not in source
    assert "make_edit_file_handler" not in source
    assert "CommandToolHandlers" not in source
    assert "make_git_status_handler" not in source
    assert "make_web_search_handler" not in source


def test_advertised_tool_input_schemas_match_declarative_specs():
    specs = {str(spec["name"]): spec for spec in WRITER_TOOL_SPECS}
    for tool in WRITER_TOOLS:
        function = tool["function"]
        name = str(function["name"])
        assert specs[name]["input_schema"] == function["parameters"], (
            f"{name} input schema drifted from model schema"
        )


def test_sub_agent_tool_schema_is_mvp_minimal():
    spec = next(spec for spec in WRITER_TOOL_SPECS if spec["name"] == "sub_agent")
    schema = spec["input_schema"]
    properties = schema["properties"]

    assert set(properties) == {"task", "agent", "model", "expected_output"}
    assert "options" not in properties
    assert "write_scope" not in str(schema)
    assert "isolated" not in str(schema)


def test_every_tool_spec_has_category_display_and_output_contract():
    valid_categories = {
        "file_read",
        "file_write",
        "command",
        "git",
        "web",
        "browser",
        "memory",
        "skill",
        "agent",
        "mcp",
        "control",
    }
    for spec in WRITER_TOOL_SPECS:
        name = spec["name"]
        assert spec.get("category") in valid_categories, f"{name} missing valid category"
        assert isinstance(spec.get("display"), dict), f"{name} missing display contract"
        assert spec["display"].get("card"), f"{name} missing display.card"
        assert isinstance(spec.get("output_schema"), dict), f"{name} missing output schema"
        assert "status" in spec["output_schema"].get("properties", {}), f"{name} output schema missing status"


def test_spec_only_tools_are_explicitly_internal():
    advertised = _writer_tool_names()
    spec_only = [spec for spec in WRITER_TOOL_SPECS if spec["name"] not in advertised]
    assert {spec["name"] for spec in spec_only} == {
        "ask_clarification",
        "chat_only",
        "mcp_tool",
        "self_critique",
    }
    assert all(spec.get("internal_only") is True for spec in spec_only)


def test_advertised_tool_schemas_are_strict_openai_function_schemas():
    def assert_strict_object_schema(schema: dict, name: str) -> None:
        schema_type = schema.get("type")
        is_object = schema_type == "object" or (
            isinstance(schema_type, list) and "object" in schema_type
        )
        if is_object or "properties" in schema:
            properties = schema.get("properties") or {}
            assert schema.get("additionalProperties") is False, f"{name} allows extra args"
            assert set(schema.get("required") or []) == set(properties.keys()), (
                f"{name} strict schema must require every property"
            )
            for child_name, child_schema in properties.items():
                if isinstance(child_schema, dict):
                    assert_strict_object_schema(child_schema, f"{name}.{child_name}")
        items = schema.get("items")
        if isinstance(items, dict):
            assert_strict_object_schema(items, f"{name}[]")

    for tool in WRITER_TOOLS:
        assert tool.get("type") == "function"
        function = tool.get("function") or {}
        name = function.get("name")
        params = function.get("parameters") or {}

        assert function.get("strict") is True, f"{name} is not strict"
        assert params.get("type") == "object", f"{name} parameters must be object"
        assert_strict_object_schema(params, str(name))


def test_run_command_timeout_contract_uses_seconds():
    run_command = next(tool for tool in WRITER_TOOLS if tool["function"]["name"] == "run_command")
    timeout = run_command["function"]["parameters"]["properties"]["timeout"]
    description = timeout["description"].lower()
    assert "seconds" in description
    assert "milliseconds" not in description


def test_run_command_contract_exposes_explicit_readiness_probe():
    run_command = next(tool for tool in WRITER_TOOLS if tool["function"]["name"] == "run_command")
    properties = run_command["function"]["parameters"]["properties"]

    assert properties["readiness_url"]["type"] == ["string", "null"]
    assert properties["readiness_text"]["type"] == ["string", "null"]
    assert "background=true" in properties["readiness_url"]["description"]


@pytest.mark.asyncio
async def test_file_tools_return_structured_read_artifact(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("alpha\nbeta\n", encoding="utf-8")
    executor = ReadWriteToolExecutor(tmp_path)

    result = await executor.read_file(
        ToolCall(id="call-read", name="read_file", arguments={"path": "notes.txt"})
    )

    assert result.status == "ok"
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.kind == "file_read"
    assert artifact.uri == "notes.txt"
    assert artifact.content == "alpha\nbeta\n"
    assert artifact.metadata["path"] == "notes.txt"
    assert artifact.metadata["line_count"] == 2
    assert artifact.metadata["truncated"] is False


@pytest.mark.asyncio
async def test_write_file_returns_structured_diff_artifact(tmp_path):
    executor = ReadWriteToolExecutor(tmp_path)

    result = await executor.write_file(
        ToolCall(id="call-write", name="write_file", arguments={"path": "new.txt", "content": "one\ntwo\n"})
    )

    assert result.status == "ok"
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.kind == "file_change"
    assert artifact.uri == "new.txt"
    assert artifact.metadata["action"] == "create"
    assert artifact.metadata["new_line_count"] == 2
    assert "+++ b/new.txt" in artifact.content
    assert "+one" in artifact.content
    assert "+two" in artifact.content


@pytest.mark.asyncio
async def test_write_checklist_returns_runtime_task_plan(tmp_path):
    executor = ReadWriteToolExecutor(tmp_path)

    result = await executor.write_checklist(
        ToolCall(
            id="call-plan",
            name="write_checklist",
            arguments={
                "files": ["app.py"],
                "design_summary": "Build a small CLI",
                "steps": [
                    {"id": "s1", "description": "Create CLI", "deliverables": ["app.py"]},
                    {"id": "s2", "description": "Run smoke test", "deliverables": []},
                ],
            },
        )
    )

    assert result.status == "ok"
    task_plan = result.metadata["task_plan"]
    assert task_plan["status"] == "active"
    assert task_plan["current_step_id"] == "s1"
    assert task_plan["steps"][0]["status"] == "in_progress"
    assert task_plan["steps"][1]["status"] == "pending"


@pytest.mark.asyncio
async def test_update_checklist_changes_runtime_plan_with_history(tmp_path):
    executor = ReadWriteToolExecutor(tmp_path)
    kit = WriterKit(tool_executor=executor.as_dict(), work_root=str(tmp_path))
    state = RuntimeState(session_id="plan-update")

    created = await executor.write_checklist(
        ToolCall(
            id="call-plan",
            name="write_checklist",
            arguments={
                "files": ["app.py"],
                "design_summary": "Build a small CLI",
                "steps": [{"id": "s1", "description": "Create CLI", "deliverables": ["app.py"]}],
            },
        )
    )
    updated = await executor.update_checklist(
        ToolCall(
            id="call-update",
            name="update_checklist",
            arguments={
                "action": "add_step",
                "step_id": "s2",
                "description": "Add smoke test",
                "deliverables": ["test_app.py"],
                "status": None,
                "steps": None,
                "files": None,
                "design_summary": None,
                "reason": "Implementation needs a verification artifact",
            },
        )
    )

    await kit.writeback(state, KernelTurn(), [created], VerificationResult(passed=True), "continue")
    await kit.writeback(state, KernelTurn(), [updated], VerificationResult(passed=True), "continue")

    plan = state.metadata["task_plan"]
    assert [step["id"] for step in plan["steps"]] == ["s1", "s2"]
    assert plan["steps"][1]["deliverables"] == ["test_app.py"]
    assert plan["history"][-1]["action"] == "add_step"
    assert state.metadata["active_plan"]["plan_steps"][1]["id"] == "s2"


@pytest.mark.asyncio
async def test_writeback_auto_advances_plan_when_deliverable_is_created(tmp_path):
    executor = ReadWriteToolExecutor(tmp_path)
    kit = WriterKit(tool_executor=executor.as_dict(), work_root=str(tmp_path))
    state = RuntimeState(session_id="plan-auto-advance")

    created = await executor.write_checklist(
        ToolCall(
            id="call-plan",
            name="write_checklist",
            arguments={
                "files": ["app.py", "README.md"],
                "design_summary": "Build a small CLI",
                "steps": [
                    {"id": "s1", "description": "Create CLI", "deliverables": ["app.py"]},
                    {"id": "s2", "description": "Document usage", "deliverables": ["README.md"]},
                ],
            },
        )
    )
    write_result = await executor.write_file(
        ToolCall(id="call-write", name="write_file", arguments={"path": "app.py", "content": "print('ok')\n"})
    )

    await kit.writeback(state, KernelTurn(), [created], VerificationResult(passed=True), "continue")
    await kit.writeback(state, KernelTurn(), [write_result], VerificationResult(passed=True), "continue")

    plan = state.metadata["task_plan"]
    assert plan["steps"][0]["status"] == "completed"
    assert plan["steps"][1]["status"] == "in_progress"
    assert plan["current_step_id"] == "s2"
    assert plan["history"][-1]["action"] == "auto_complete_step"


@pytest.mark.asyncio
async def test_edit_file_returns_structured_diff_artifact_with_add_and_delete(tmp_path):
    path = tmp_path / "edit.txt"
    path.write_text("old\nkeep\n", encoding="utf-8")
    executor = ReadWriteToolExecutor(tmp_path)

    result = await executor.edit_file(
        ToolCall(
            id="call-edit",
            name="edit_file",
            arguments={"path": "edit.txt", "old_text": "old\n", "new_text": "new\nextra\n"},
        )
    )

    assert result.status == "ok"
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.kind == "file_change"
    assert artifact.uri == "edit.txt"
    assert artifact.metadata["action"] == "edit"
    assert artifact.metadata["start_line"] == 1
    assert "--- a/edit.txt" in artifact.content
    assert "+++ b/edit.txt" in artifact.content
    assert "-old" in artifact.content
    assert "+new" in artifact.content
    assert "+extra" in artifact.content


@pytest.mark.asyncio
async def test_kernel_tool_summary_includes_artifacts_for_ui(tmp_path):
    llm = _FakeLLM([
        LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(
                    id="call-write",
                    name="write_file",
                    arguments={"path": "ui.txt", "content": "hello\n"},
                )
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="done", finish_reason="stop"),
    ])

    result = await run_core_kernel(
        goal="write a file",
        session_id="tool-summary-artifacts",
        llm_client=llm,
        work_root=str(tmp_path),
    )

    summary = result.metadata["tool_results_summary"]
    write_summary = next(item for item in summary if item["tool_name"] == "write_file")
    assert write_summary["call_id"] == "call-write"
    assert write_summary["metadata"]["path"] == "ui.txt"
    artifact = write_summary["artifacts"][0]
    assert artifact["kind"] == "file_change"
    assert artifact["uri"] == "ui.txt"
    assert "+hello" in artifact["content"]


@pytest.mark.asyncio
async def test_inspect_project_returns_structured_metadata_and_artifact(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"scripts":{"test":"vitest run","typecheck":"vue-tsc --noEmit"}}',
        encoding="utf-8",
    )
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.ts").write_text("console.log('ok')\n", encoding="utf-8")
    executor = ReadWriteToolExecutor(tmp_path)

    result = await executor.inspect_project(
        ToolCall(id="call-inspect", name="inspect_project", arguments={"path": ".", "max_files": 20})
    )

    assert result.status == "ok"
    assert "package.json" in result.metadata["manifests"]
    assert "typescript" in result.metadata["likely_stack"]
    assert "npm run test" in result.metadata["test_commands"]
    assert result.artifacts[0].kind == "project_inspection"
    assert result.artifacts[0].metadata["file_sample_count"] >= 1


@pytest.mark.asyncio
async def test_agent_tool_summary_includes_standard_agent_metadata(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts":{"test":"echo ok"}}', encoding="utf-8")
    llm = _FakeLLM([
        LLMResponse(
            content="",
            tool_calls=[
                LLMToolCall(
                    id="call-agent",
                    name="sub_agent",
                    arguments={
                        "task": "Review the project",
                        "mode": "low",
                        "options": {"role": "review", "expected_output": "blocking issues"},
                    },
                )
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="done", finish_reason="stop"),
    ])

    result = await run_core_kernel(
        goal="review project",
        session_id="agent-standard-metadata",
        llm_client=llm,
        work_root=str(tmp_path),
    )

    summary = result.metadata["tool_results_summary"]
    agent_summary = next(item for item in summary if item["tool_name"] == "sub_agent")
    metadata = agent_summary["metadata"]
    assert metadata["agent_name"] == "sub"
    assert metadata["agent_index"] == "001"
    assert metadata["sub_session_id"] == "agent-standard-metadata:sub:001:sub"
    assert metadata["runtime_agent"] == "sub"
    assert metadata["role"] == "review"
    assert metadata["task"] == "Review the project"
    assert all(
        item.get("label") not in {"Agent 类型", "子代理角色", "工具权限"}
        for item in metadata.get("substeps", [])
    )
    assert "final_answer" not in metadata
    assert "summary" not in metadata
    assert "handoff" not in metadata
    assert "confidence" not in metadata


@pytest.mark.asyncio
async def test_sub_agent_preflight_does_not_add_mvp_parallel_locking(tmp_path):
    kit = WriterKit(work_root=str(tmp_path), agent_llm_client=_FakeAgentLLM())
    calls = [
        ToolCall(
            id="call-agent-a",
            name="sub_agent",
            arguments={
                "task": "改 A",
                "mode": "low",
                "clean": False,
                "options": {"agent": "worker", "write_scope": ["src/auth/"]},
            },
        ),
        ToolCall(
            id="call-agent-b",
            name="sub_agent",
            arguments={
                "task": "改 B",
                "mode": "low",
                "clean": False,
                "options": {"agent": "worker", "write_scope": ["src/auth/login.ts"]},
            },
        ),
    ]

    blocked = await kit.preflight_tool_calls(RuntimeState(session_id="preflight"), calls)

    assert blocked == {}


@pytest.mark.asyncio
async def test_run_tests_returns_structured_pass_result(tmp_path):
    (tmp_path / "pass_test.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    executor = ReadWriteToolExecutor(tmp_path)
    result = await executor.run_tests(
        ToolCall(
            id="call-tests-pass",
            name="run_tests",
            arguments={"command": "py -3.14 pass_test.py", "timeout": 10},
        )
    )

    assert result.status == "ok"
    assert result.metadata["passed"] is True
    assert result.metadata["summary"] == "passed"
    assert result.metadata["exit_code"] == 0
    assert result.artifacts[0].kind == "test_result"
    assert result.artifacts[0].metadata["command"].startswith("py -3.14")


@pytest.mark.asyncio
async def test_run_tests_returns_structured_failure_result(tmp_path):
    (tmp_path / "fail_test.py").write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    executor = ReadWriteToolExecutor(tmp_path)
    result = await executor.run_tests(
        ToolCall(
            id="call-tests-fail",
            name="run_tests",
            arguments={"command": "py -3.14 fail_test.py", "timeout": 10},
        )
    )

    assert result.status == "failed"
    assert result.metadata["passed"] is False
    assert result.metadata["summary"] == "failed"
    assert result.metadata["exit_code"] == 3
    assert result.artifacts[0].kind == "test_result"
    assert "Command exited with code 3" in result.error


def test_run_tests_is_not_run_command_alias(tmp_path):
    executor = ReadWriteToolExecutor(tmp_path)
    tools = executor.as_dict()
    assert tools["run_tests"] != tools["run_command"]


@pytest.mark.asyncio
async def test_git_tools_report_status_and_path_filtered_diff(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not available")

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    tracked.write_text("after\n", encoding="utf-8")

    tools = ReadWriteToolExecutor(tmp_path).as_dict()
    status = await tools["git_status"](ToolCall(id="git-status", name="git_status", arguments={}))
    diff = await tools["git_diff"](ToolCall(id="git-diff", name="git_diff", arguments={"path": "tracked.txt"}))
    escaped = await tools["git_diff"](ToolCall(id="git-diff-escape", name="git_diff", arguments={"path": "../outside.txt"}))

    assert status.status == "ok"
    assert "tracked.txt" in status.content
    assert diff.status == "ok"
    assert "after" in diff.content
    assert escaped.status == "failed"
    assert "escapes work_root" in (escaped.error or "")


@pytest.mark.asyncio
async def test_browser_check_reports_reachability_and_expected_text(tmp_path, monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><head><title>Demo</title></head><body>Hello Writer</body></html>",
            request=request,
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=httpx.Timeout(5.0),
        headers={"User-Agent": "test"},
    )
    monkeypatch.setattr(web_tools, "_HTTP_CLIENT", client)
    try:
        tool = ReadWriteToolExecutor(tmp_path).as_dict()["browser_check"]
        result = await tool(
            ToolCall(
                id="call-1",
                name="browser_check",
                arguments={"url": "http://example.test/", "expect": "Hello Writer"},
            )
        )
    finally:
        await client.aclose()
        monkeypatch.setattr(web_tools, "_HTTP_CLIENT", None)

    assert result.status == "ok"
    assert "HTTP 200" in result.content
    assert "title: Demo" in result.content
    assert "expect_found: true" in result.content
    assert result.metadata["status_code"] == 200
    assert result.metadata["expect_found"] is True


@pytest.mark.asyncio
async def test_web_search_returns_structured_metadata_and_artifact(tmp_path, monkeypatch):
    html = """
    <html><body>
      <a class="result__a" href="https://example.test/doc">Example Docs</a>
      <a class="result__snippet">Official docs snippet</a>
    </body></html>
    """
    requested_body = ""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested_body
        requested_body = request.content.decode("utf-8", errors="replace")
        return httpx.Response(200, text=html, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(5.0))
    monkeypatch.setattr(web_tools, "_HTTP_CLIENT", client)
    try:
        tool = ReadWriteToolExecutor(tmp_path).as_dict()["web_search"]
        result = await tool(
            ToolCall(
                id="call-search",
                name="web_search",
                arguments={"query": "example docs", "limit": 1, "domains": ["example.test"]},
            )
        )
    finally:
        await client.aclose()
        monkeypatch.setattr(web_tools, "_HTTP_CLIENT", None)

    assert result.status == "ok"
    assert result.metadata["query"] == "example docs"
    assert result.metadata["domains"] == ["example.test"]
    assert result.metadata["result_count"] == 1
    assert result.metadata["results"][0]["url"] == "https://example.test/doc"
    assert result.artifacts[0].kind == "web_search_result"
    assert "site%3Aexample.test" in requested_body


@pytest.mark.asyncio
async def test_web_fetch_returns_structured_metadata_and_artifact(tmp_path, monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><head><title>Example</title></head><body><main>Hello fetch</main></body></html>",
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(5.0))
    monkeypatch.setattr(web_tools, "_HTTP_CLIENT", client)
    try:
        tool = ReadWriteToolExecutor(tmp_path).as_dict()["web_fetch"]
        result = await tool(
            ToolCall(id="call-fetch", name="web_fetch", arguments={"url": "https://example.test/doc"})
        )
    finally:
        await client.aclose()
        monkeypatch.setattr(web_tools, "_HTTP_CLIENT", None)

    assert result.status == "ok"
    assert result.metadata["url"] == "https://example.test/doc"
    assert result.metadata["status_code"] == 200
    assert result.artifacts[0].kind == "web_fetch_content"
    assert "Hello fetch" in str(result.artifacts[0].content)


@pytest.mark.asyncio
async def test_browser_check_fails_when_expected_text_is_missing(tmp_path, monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="different content", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=httpx.Timeout(5.0))
    monkeypatch.setattr(web_tools, "_HTTP_CLIENT", client)
    try:
        tool = ReadWriteToolExecutor(tmp_path).as_dict()["browser_check"]
        result = await tool(
            ToolCall(
                id="call-2",
                name="browser_check",
                arguments={"url": "http://example.test/", "expect": "missing"},
            )
        )
    finally:
        await client.aclose()
        monkeypatch.setattr(web_tools, "_HTTP_CLIENT", None)

    assert result.status == "failed"
    assert result.error == "Expected text not found: missing"
    assert "expect_found: false" in result.content
