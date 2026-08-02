from __future__ import annotations

import pytest

from lamtools_core.agent import SubAgentRunResult
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import build_core_toolbox


class FakeMCPCaller:
    def __init__(self) -> None:
        self.calls = []

    async def call(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        return f"mcp:{tool_name}:{arguments['value']}"


class FakeSubAgentRunner:
    def __init__(self) -> None:
        self.calls = []

    async def run(
        self,
        *,
        task,
        agent="",
        model="",
        mode="",
        attachments=None,
        parent_call_id="",
        parent_run_id="",
        parent_turn_id="",
    ):
        self.calls.append(
            {
                "task": task,
                "agent": agent,
                "model": model,
                "mode": mode,
                "attachments": attachments,
                "parent_call_id": parent_call_id,
                "parent_run_id": parent_run_id,
                "parent_turn_id": parent_turn_id,
            }
        )
        return f"sub:{task}"


class FailingSubAgentRunner:
    def __init__(self) -> None:
        self.calls = 0

    async def run(
        self,
        *,
        task,
        agent="",
        model="",
        mode="",
        attachments=None,
        parent_call_id="",
        parent_run_id="",
        parent_turn_id="",
    ):
        self.calls += 1
        return SubAgentRunResult(
            session_id="parent:sub:worker",
            run_id=f"child-run-{self.calls}",
            decision="failed",
        )


class NoProgressSubAgentRunner:
    async def run(self, **_kwargs):
        return SubAgentRunResult(
            session_id="parent:sub:worker",
            run_id="child-run-wait",
            decision="wait",
            pending_waiting_request={
                "request_kind": "no_progress",
                "message": "same failure observed four times",
            },
        )


class FakeSkillRegistry:
    def __init__(self, skill_dir):
        self.skill_dir = skill_dir

    def prompt_index(self, work_root):
        return f"fake index for {work_root}"

    def load_prompt_content(self, work_root, name):
        _ = work_root
        return f'<skill_content name="{name}">Fake Skill</skill_content>'

    def get(self, work_root, name):
        _ = work_root, name

        class SkillRef:
            location = self.skill_dir / "SKILL.md"

        return SkillRef()


def test_core_toolbox_exposes_generic_tool_specs(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path)

    names = [spec.name for spec in toolbox.tool_specs()]
    specs = {spec.name: spec for spec in toolbox.tool_specs()}

    assert "read_file" in names
    assert "document_normalize" in names
    assert "write_file" in names
    assert "run_command" in names
    assert "git_diff" in names
    assert "web_fetch" in names
    assert "mcp_tool" in names
    assert "load_skill" in names
    assert "sub_agent" in names
    assert toolbox.tool_permissions["write_file"] == "ask_user"
    assert toolbox.tool_permissions["read_file"] == "auto_allow"
    assert toolbox.tool_permissions["document_normalize"] == "ask_user"
    assert toolbox.tool_permissions["load_skill"] == "auto_allow"
    assert "DOCX" in specs["read_file"].description
    assert "PDF" in specs["read_file"].description
    assert "path_outside_root" in {
        item["type"] for item in specs["write_file"].metadata["failure_modes"]
    }
    assert specs["write_file"].metadata["recovery"]


@pytest.mark.asyncio
async def test_core_toolbox_executes_read_file(tmp_path):
    (tmp_path / "note.txt").write_text("hello core\n", encoding="utf-8")
    toolbox = build_core_toolbox(work_root=tmp_path)

    result = await toolbox.execute(ToolCall(id="call-1", name="read_file", arguments={"path": "note.txt"}))

    assert result.status == "ok"
    assert "hello core" in result.content


def test_core_toolbox_marks_approval_required_tools(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path)

    write_call = toolbox.prepare_call(
        ToolCall(id="write-1", name="write_file", arguments={"path": "out.txt", "content": "hello"})
    )
    mcp_call = toolbox.prepare_call(
        ToolCall(id="mcp-1", name="mcp_tool", arguments={"tool_name": "server.tool", "arguments": {}})
    )
    normalize_call = toolbox.prepare_call(
        ToolCall(id="doc-1", name="document_normalize", arguments={"path": "report.docx"})
    )

    assert write_call.requires_approval is True
    assert write_call.metadata["approval"]["tier"] == "ask_user"
    assert mcp_call.requires_approval is True
    assert mcp_call.metadata["approval"]["tier"] == "ask_user"
    assert normalize_call.requires_approval is True
    assert normalize_call.metadata["approval"]["tier"] == "ask_user"


def test_core_toolbox_auto_approve_keeps_hard_blocks(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path, approval_policy="auto_approve")

    write_call = toolbox.prepare_call(
        ToolCall(id="write-1", name="write_file", arguments={"path": "out.txt", "content": "hello"})
    )
    escape_call = toolbox.prepare_call(
        ToolCall(id="write-escape", name="write_file", arguments={"path": "../outside.txt", "content": "bad"})
    )

    assert write_call.requires_approval is False
    assert write_call.metadata["approval"]["auto_approved"] is True
    assert escape_call.requires_approval is False
    assert escape_call.metadata["approval"]["blocked"] is True


@pytest.mark.asyncio
async def test_core_toolbox_blocks_path_escape_before_execution(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path)
    call = toolbox.prepare_call(
        ToolCall(id="write-escape", name="write_file", arguments={"path": "../outside.txt", "content": "bad"})
    )

    result = await toolbox.execute(call)

    assert result.status == "blocked"
    assert "outside work_root" in result.error
    assert not (tmp_path.parent / "outside.txt").exists()


@pytest.mark.asyncio
async def test_core_toolbox_executes_injected_mcp_caller(tmp_path):
    caller = FakeMCPCaller()
    toolbox = build_core_toolbox(work_root=tmp_path, mcp_caller=caller, approval_policy="auto_approve")

    call = toolbox.prepare_call(
        ToolCall(
            id="mcp-1",
            name="mcp_tool",
            arguments={"tool_name": "server.echo", "arguments": {"value": "ok"}},
        )
    )
    result = await toolbox.execute(call)

    assert result.status == "ok"
    assert result.content == "mcp:server.echo:ok"
    assert caller.calls == [("server.echo", {"value": "ok"})]


@pytest.mark.asyncio
async def test_core_toolbox_executes_injected_sub_agent_runner(tmp_path):
    runner = FakeSubAgentRunner()
    toolbox = build_core_toolbox(work_root=tmp_path, sub_agent_runner=runner)

    result = await toolbox.execute(
        ToolCall(
            id="sub-1",
            name="sub_agent",
            arguments={"task": "inspect", "agent": "reader"},
        )
    )

    assert result.status == "ok"
    assert result.content == "sub:inspect"
    assert runner.calls[0]["agent"] == "reader"


@pytest.mark.asyncio
async def test_core_toolbox_forwards_sub_agent_model_and_mode(tmp_path):
    runner = FakeSubAgentRunner()
    toolbox = build_core_toolbox(work_root=tmp_path, sub_agent_runner=runner)

    result = await toolbox.execute(
        ToolCall(
            id="sub-model-mode",
            name="sub_agent",
            arguments={
                "task": "inspect",
                "agent": "reader",
                "model": "strong-model",
                "mode": "consider",
            },
        )
    )

    assert result.status == "ok"
    assert runner.calls[0]["model"] == "strong-model"
    assert runner.calls[0]["mode"] == "consider"


@pytest.mark.asyncio
async def test_core_toolbox_defaults_sub_agent_model_and_mode_to_empty(tmp_path):
    runner = FakeSubAgentRunner()
    toolbox = build_core_toolbox(work_root=tmp_path, sub_agent_runner=runner)

    await toolbox.execute(
        ToolCall(
            id="sub-defaults",
            name="sub_agent",
            arguments={"task": "inspect", "agent": "reader"},
        )
    )

    # When omitted, model/mode are empty so the sub-agent follows the main model and full access.
    assert runner.calls[0]["model"] == ""
    assert runner.calls[0]["mode"] == ""


@pytest.mark.asyncio
async def test_core_toolbox_forwards_sub_agent_attachments(tmp_path):
    runner = FakeSubAgentRunner()
    toolbox = build_core_toolbox(work_root=tmp_path, sub_agent_runner=runner)

    await toolbox.execute(
        ToolCall(
            id="sub-att",
            name="sub_agent",
            arguments={
                "task": "describe the image",
                "agent": "viewer",
                "model": "xopkimik26",
                "attachments": ["att-1", "att-2"],
            },
        )
    )

    assert runner.calls[0]["attachments"] == ["att-1", "att-2"]
    assert runner.calls[0]["model"] == "xopkimik26"


@pytest.mark.asyncio
async def test_core_toolbox_does_not_rerun_identical_failed_sub_agent_task(tmp_path):
    runner = FailingSubAgentRunner()
    toolbox = build_core_toolbox(work_root=tmp_path, sub_agent_runner=runner)

    first = await toolbox.execute(ToolCall(
        id="sub-failed-1",
        name="sub_agent",
        arguments={"task": "inspect", "agent": "worker"},
    ))
    second = await toolbox.execute(ToolCall(
        id="sub-failed-2",
        name="sub_agent",
        arguments={"task": "inspect", "agent": "worker"},
    ))

    assert first.status == "failed"
    assert second.status == "failed"
    assert runner.calls == 1
    assert second.metadata["duplicate_failure_blocked"] is True


@pytest.mark.asyncio
async def test_core_toolbox_propagates_sub_agent_no_progress_without_calling_it_approval(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path, sub_agent_runner=NoProgressSubAgentRunner())

    result = await toolbox.execute(ToolCall(
        id="sub-wait-1",
        name="sub_agent",
        arguments={"task": "inspect", "agent": "worker"},
    ))

    assert result.status == "blocked"
    assert result.content == "Sub-agent paused after making no progress."
    assert result.metadata["wait_reason"] == "no_progress"
    assert result.metadata["pending_approval"] == {}
    assert result.metadata["pending_waiting_request"]["request_kind"] == "no_progress"


@pytest.mark.asyncio
async def test_core_toolbox_loads_skill_and_adds_resource_root(tmp_path):
    skill_dir = tmp_path / ".agents" / "skills" / "sample"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: sample\n"
        "description: Sample skill for Core.\n"
        "---\n"
        "# Sample Skill\n"
        "Read helper.txt when asked.\n",
        encoding="utf-8",
    )
    (skill_dir / "helper.txt").write_text("skill helper content\n", encoding="utf-8")
    toolbox = build_core_toolbox(work_root=tmp_path)

    load_result = await toolbox.execute(
        ToolCall(id="skill-1", name="load_skill", arguments={"name": "sample"})
    )
    read_result = await toolbox.execute(
        ToolCall(id="read-helper", name="read_file", arguments={"path": "helper.txt"})
    )

    assert load_result.status == "ok"
    assert "<skill_content name=\"sample\">" in load_result.content
    assert "Read helper.txt when asked." in load_result.content
    assert read_result.status == "ok"
    assert "skill helper content" in read_result.content


@pytest.mark.asyncio
async def test_core_toolbox_accepts_custom_skill_registry(tmp_path):
    skill_dir = tmp_path / "member-skills" / "sample"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Sample\n", encoding="utf-8")
    (skill_dir / "helper.txt").write_text("custom registry helper\n", encoding="utf-8")
    toolbox = build_core_toolbox(work_root=tmp_path, skill_registry=FakeSkillRegistry(skill_dir))

    load_result = await toolbox.execute(
        ToolCall(id="skill-custom", name="load_skill", arguments={"name": "sample"})
    )
    read_result = await toolbox.execute(
        ToolCall(id="read-custom-helper", name="read_file", arguments={"path": "helper.txt"})
    )

    assert load_result.status == "ok"
    assert read_result.status == "ok"
    assert "custom registry helper" in read_result.content
