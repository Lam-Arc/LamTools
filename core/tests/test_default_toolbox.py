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


class DiagnosticFailingSubAgentRunner:
    """Returns a failed result with full diagnostics for failure-forwarding tests."""

    async def run(self, **_kwargs):
        return SubAgentRunResult(
            session_id="parent:sub:worker",
            run_id="child-run-diag",
            decision="failed",
            model_rounds=5,
            tool_call_count=5,
            tool_call_breakdown={"read_file": 4, "write_file": 1},
            death_scene=(
                "--- Sub-agent death scene (last model round) ---\n"
                "Model reply: (empty — no text produced)\n"
                "Tools called this round: (none)"
            ),
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
    assert "document_normalize" not in names
    assert "write_spreadsheet" not in names
    assert "run_tests" not in names
    assert "browser_check" not in names
    assert "write_file" in names
    assert "run_command" in names
    # S3：git/web_search/generate_image 已外移为内置插件（基础集 15）
    assert "git_diff" not in names
    assert "git_status" not in names
    assert "web_search" not in names
    assert "generate_image" not in names
    assert "web_fetch" in names
    assert "mcp_tool" in names
    assert "load_skill" in names
    assert "sub_agent" in names
    assert toolbox.tool_permissions["write_file"] == "ask_user"
    assert toolbox.tool_permissions["read_file"] == "auto_allow"
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
    command_call = toolbox.prepare_call(
        ToolCall(id="edit-1", name="edit_file", arguments={"path": "a.txt", "old_string": "x", "new_string": "y"})
    )

    assert write_call.requires_approval is True
    assert write_call.metadata["approval"]["tier"] == "ask_user"
    assert mcp_call.requires_approval is True
    assert mcp_call.metadata["approval"]["tier"] == "ask_user"
    assert command_call.requires_approval is True
    assert command_call.metadata["approval"]["tier"] == "ask_user"


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


def test_core_toolbox_question_always_requires_approval(tmp_path):
    """question bypasses ApprovalGate — always requires user input,
    even under auto_approve (full_edit) and regardless of active_tier."""
    toolbox = build_core_toolbox(work_root=tmp_path, approval_policy="auto_approve")

    call = toolbox.prepare_call(
        ToolCall(id="q-1", name="question", arguments={"question": "公仓还是私仓？"})
    )

    assert call.requires_approval is True
    assert call.metadata["approval"]["requires_approval"] is True
    assert call.metadata["approval"]["blocked"] is False
    # Must NOT be auto-approved
    assert call.metadata["approval"].get("auto_approved") is not True
    assert call.metadata["approval"]["reason"] == "Question requires user input"


def test_core_toolbox_question_requires_approval_under_require_policy(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path, approval_policy="require")

    call = toolbox.prepare_call(
        ToolCall(id="q-2", name="question", arguments={"question": "继续？"})
    )

    assert call.requires_approval is True
    assert call.metadata["approval"]["requires_approval"] is True


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
async def test_core_toolbox_allow_access_outside_workdir(tmp_path):
    root = tmp_path / "root"
    workspace = root / "project"
    outside = root / "outside"
    workspace.mkdir(parents=True)
    outside.mkdir()
    (outside / "secret.txt").write_text("top secret\n", encoding="utf-8")

    async def run(toolbox, call):
        return await toolbox.execute(toolbox.prepare_call(call))

    # Default (restricted): the approval gate blocks out-of-workspace reads
    # before the handler ever runs.
    restricted = build_core_toolbox(work_root=workspace, approval_policy="auto_approve")
    result = await run(
        restricted,
        ToolCall(id="read-blocked", name="read_file", arguments={"path": str(outside / "secret.txt")}),
    )
    assert result.status == "blocked"
    assert "outside work_root" in result.error

    allowed = build_core_toolbox(
        work_root=workspace,
        approval_policy="auto_approve",
        allow_access_outside_workdir=True,
    )
    result = await run(
        allowed,
        ToolCall(id="read-ok", name="read_file", arguments={"path": str(outside / "secret.txt")}),
    )
    assert result.status == "ok"
    assert "top secret" in result.content

    result = await run(
        allowed,
        ToolCall(id="write-ok", name="write_file", arguments={"path": str(outside / "new.txt"), "content": "new\n"}),
    )
    assert result.status == "ok"
    assert (outside / "new.txt").read_text(encoding="utf-8") == "new\n"

    # Sensitive-pattern hard blocks still apply even when out-of-workspace
    # access is allowed.
    result = await run(
        allowed,
        ToolCall(id="env-blocked", name="write_file", arguments={"path": str(outside / ".env"), "content": "KEY=1"}),
    )
    assert result.status == "blocked"
    assert "sensitive pattern" in result.error


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
async def test_core_toolbox_sub_agent_failure_forwards_diagnostics(tmp_path):
    """Failed sub-agent results must forward model_rounds, tool_call_breakdown,
    and death_scene to the parent agent in both content and metadata."""
    runner = DiagnosticFailingSubAgentRunner()
    toolbox = build_core_toolbox(work_root=tmp_path, sub_agent_runner=runner)

    result = await toolbox.execute(ToolCall(
        id="sub-diag-1",
        name="sub_agent",
        arguments={"task": "inspect", "agent": "worker"},
    ))

    assert result.status == "failed"
    # Metadata carries the raw diagnostic fields
    assert result.metadata["model_rounds"] == 5
    assert result.metadata["tool_call_breakdown"] == {"read_file": 4, "write_file": 1}
    assert "death_scene" in result.metadata
    # Content is a rich multi-line message the model can read
    assert "SUB_AGENT FAILED:" in result.content
    assert "model_rounds: 5" in result.content
    assert "tool_calls: 5 (read_file=4, write_file=1)" in result.content
    assert "death scene" in result.content
    assert "Model reply: (empty" in result.content
    assert "Tools called this round: (none)" in result.content
    # The error field itself must carry the death scene (wired via
    # failure_message()) so callers that surface only the error — e.g. the
    # approval-continuation path in default_agent — still see the reason.
    assert result.error.startswith("Sub-agent failed without a final response.")
    assert "death scene" in result.error
    assert "Model reply: (empty" in result.error
    # No duplication: the death scene renders exactly once in content
    assert result.content.count("death scene") == 1


def test_sub_agent_run_result_failure_message_embeds_death_scene():
    """failure_message() must append the death scene so the parent agent sees
    why the sub-agent died (model reply + tool statuses), not a generic line."""
    result = SubAgentRunResult(
        session_id="s",
        run_id="r",
        decision="failed",
        death_scene=(
            "--- Sub-agent death scene (last model round) ---\n"
            "Model reply: I could not find the file\n"
            "Tools called this round: (none)"
        ),
    )
    message = result.failure_message()
    assert message.startswith("Sub-agent failed without a final response.")
    assert "death scene" in message
    assert "Model reply: I could not find the file" in message

    # Without a death scene the message stays as before
    plain = SubAgentRunResult(session_id="s", run_id="r", decision="failed").failure_message()
    assert plain == "Sub-agent failed without a final response."

    # An explicit error wins as the summary; the death scene is still appended
    with_error = SubAgentRunResult(
        session_id="s",
        run_id="r",
        decision="failed",
        error="boom",
        death_scene="--- Sub-agent death scene (last model round) ---\nModel reply: nope",
    ).failure_message()
    assert with_error.startswith("boom")
    assert "Model reply: nope" in with_error


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
    skill_dir = tmp_path / ".lam" / "skills" / "sample"
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


# ---------------------------------------------------------------------------
# loadtools mode enforcement at execution time
# ---------------------------------------------------------------------------

MODE_BLOCK_SUFFIX = "Please make the plan prepared and ask user to switch mode."


def _consider_toolbox(tmp_path):
    from lamtools_core.tool.loadtools import default_load_tools

    return build_core_toolbox(
        work_root=tmp_path,
        load_tools=default_load_tools(),
        active_mode="consider",
    )


def test_core_toolbox_mode_enforcement_blocks_write_in_consider(tmp_path):
    toolbox = _consider_toolbox(tmp_path)

    for name in ("write_file", "edit_file", "run_command"):
        call = toolbox.prepare_call(ToolCall(id=f"mode-{name}", name=name, arguments={}))

        approval = call.metadata["approval"]
        assert approval["blocked"] is True
        assert call.requires_approval is False
        assert approval["reason"] == (
            f"You are in the consider mode, you can't use {name}. {MODE_BLOCK_SUFFIX}"
        )


def test_core_toolbox_mode_enforcement_allows_read_in_consider(tmp_path):
    toolbox = _consider_toolbox(tmp_path)

    call = toolbox.prepare_call(
        ToolCall(id="mode-read", name="read_file", arguments={"path": "x.txt"})
    )

    assert call.metadata["approval"]["blocked"] is False


@pytest.mark.asyncio
async def test_core_toolbox_mode_blocked_call_returns_error_to_model(tmp_path):
    toolbox = _consider_toolbox(tmp_path)

    call = toolbox.prepare_call(
        ToolCall(id="mode-write", name="write_file", arguments={"path": "out.txt", "content": "x"})
    )
    result = await toolbox.execute(call)

    assert result.status == "blocked"
    assert result.error == (
        "You are in the consider mode, you can't use write_file. "
        "Please make the plan prepared and ask user to switch mode."
    )


def test_core_toolbox_mode_execute_mode_is_full_access(tmp_path):
    from lamtools_core.tool.loadtools import default_load_tools

    toolbox = build_core_toolbox(
        work_root=tmp_path,
        load_tools=default_load_tools(),
        active_mode="execute",
    )

    call = toolbox.prepare_call(ToolCall(id="mode-exec", name="write_file", arguments={}))

    # Mode does not block; normal approval gating still applies.
    assert call.metadata["approval"]["blocked"] is False
    assert call.requires_approval is True


def test_core_toolbox_mode_unknown_mode_does_not_block(tmp_path):
    from lamtools_core.tool.loadtools import default_load_tools

    toolbox = build_core_toolbox(
        work_root=tmp_path,
        load_tools=default_load_tools(),
        active_mode="bogus-mode",
    )

    call = toolbox.prepare_call(ToolCall(id="mode-unknown", name="write_file", arguments={}))

    assert call.metadata["approval"]["blocked"] is False


def test_core_toolbox_mode_without_loadtools_does_not_block(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path, active_mode="consider")

    call = toolbox.prepare_call(ToolCall(id="mode-noload", name="write_file", arguments={}))

    assert call.metadata["approval"]["blocked"] is False


def test_core_toolbox_workflow_mode_allows_dynamic_workflow_tools(tmp_path):
    from lamtools_core.tool import ToolSpec
    from lamtools_core.tool.loadtools import default_load_tools

    class FakeWorkflowBundle:
        specs = [ToolSpec(name="wf_run_dynamic", metadata={"category": "workflow"}, permission="auto_allow")]
        handlers = {}

    toolbox = build_core_toolbox(
        work_root=tmp_path,
        load_tools=default_load_tools(),
        active_mode="workflow",
        workflow_tool_provider=lambda: FakeWorkflowBundle,
    )

    dynamic = toolbox.prepare_call(ToolCall(id="wf-dyn", name="wf_run_dynamic", arguments={}))
    assert dynamic.metadata["approval"]["blocked"] is False
    # write_file is not in the workflow whitelist — still blocked.
    write = toolbox.prepare_call(ToolCall(id="wf-write", name="write_file", arguments={}))
    assert write.metadata["approval"]["blocked"] is True


def test_core_toolbox_consider_mode_blocks_dynamic_workflow_tools(tmp_path):
    from lamtools_core.tool import ToolSpec
    from lamtools_core.tool.loadtools import default_load_tools

    class FakeWorkflowBundle:
        specs = [ToolSpec(name="wf_run_dynamic", metadata={"category": "workflow"}, permission="auto_allow")]
        handlers = {}

    toolbox = build_core_toolbox(
        work_root=tmp_path,
        load_tools=default_load_tools(),
        active_mode="consider",
        workflow_tool_provider=lambda: FakeWorkflowBundle,
    )

    call = toolbox.prepare_call(ToolCall(id="wf-dyn-consider", name="wf_run_dynamic", arguments={}))
    assert call.metadata["approval"]["blocked"] is True


# ── generate_image ──────────────────────────────────────────────────────────

class FakeImageResponse:
    def __init__(self, status_code=200, json_data=None, content=b"", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        assert self.status_code < 400, f"HTTP {self.status_code}"


class FakeImageClient:
    """In-memory httpx.AsyncClient stand-in; routes keyed by 'post:<url>' / 'get:<url>'."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.posts = []
        self.multipart_posts = []
        self.gets = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, files=None, data=None):
        self.posts.append((url, json))
        if files is not None:
            self.multipart_posts.append((url, files, data))
        return self.routes.get("post:" + url, FakeImageResponse())

    async def get(self, url):
        self.gets.append(url)
        return self.routes.get("get:" + url, FakeImageResponse())


def _install_fake_image_client(monkeypatch, client):
    monkeypatch.setattr("lamtools_core.tool.image_tools.httpx.AsyncClient", lambda *a, **k: client)


_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24

IMAGE_CONFIG = {
    "enabled": True,
    "api_url": "https://img.example.com/v1",
    "api_key": "sk-test",
    "model": "img-model-1",
}


def test_core_toolbox_exposes_generate_image_spec(tmp_path):
    # S3：generate_image 经内置插件装配（半声明式：spec 从 core 常量按名补全）
    from lamtools_core.plugins.models import PluginToolSpec
    from lamtools_core.plugins.tools import complete_plugin_tool_specs
    from lamtools_core.tool.default_toolbox import bundled_core_tool_specs

    base_specs = {spec.name: spec for spec in bundled_core_tool_specs()}
    plugin_specs = complete_plugin_tool_specs(
        [PluginToolSpec(name="generate_image", permission="ask_user", handler="x:y")],
        plugin_name="imagegen",
        plugin_root=tmp_path,
        base_specs_by_name=base_specs,
    )
    assert plugin_specs[0].metadata["category"] == "image"  # 半声明式从 core 常量补全
    toolbox = build_core_toolbox(
        work_root=tmp_path,
        imagegen_config=IMAGE_CONFIG,
        plugin_tool_specs=plugin_specs,
    )

    specs = {spec.name: spec for spec in toolbox.tool_specs()}
    assert "generate_image" in specs
    spec = specs["generate_image"]
    assert spec.permission == "ask_user"
    assert spec.metadata["category"] == "image"
    assert "prompt" in {key for key in spec.input_schema["properties"]}
    assert "reference_urls" in spec.input_schema["properties"]
    assert {item["type"] for item in spec.metadata["failure_modes"]} >= {"missing_image_provider", "api_timeout"}
    assert spec.metadata["recovery"]


def test_generate_image_disabled_tool_hidden(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path, disabled_tools={"generate_image"})

    names = [spec.name for spec in toolbox.tool_specs()]
    assert "generate_image" not in names
    assert toolbox.tool_permissions["generate_image"] == "hard_block"


def test_generate_image_requires_approval(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path, imagegen_config=IMAGE_CONFIG)

    call = toolbox.prepare_call(ToolCall(id="img-1", name="generate_image", arguments={"prompt": "a cat"}))

    assert call.requires_approval is True
    assert call.metadata["approval"]["tier"] == "ask_user"

    auto = build_core_toolbox(work_root=tmp_path, imagegen_config=IMAGE_CONFIG, approval_policy="auto_approve")
    call2 = auto.prepare_call(ToolCall(id="img-2", name="generate_image", arguments={"prompt": "a cat"}))
    assert call2.requires_approval is False
    assert call2.metadata["approval"]["auto_approved"] is True


@pytest.mark.asyncio
async def test_generate_image_missing_provider(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path, imagegen_config=None)

    result = await toolbox.execute(ToolCall(id="img-1", name="generate_image", arguments={"prompt": "a cat"}))

    assert result.status == "failed"
    assert result.metadata.get("error") == "missing_image_provider"


@pytest.mark.asyncio
async def test_generate_image_text_to_image(tmp_path, monkeypatch):
    import base64

    client = FakeImageClient(routes={
        "post:https://img.example.com/v1/images/generations": FakeImageResponse(
            json_data={"data": [{"b64_json": base64.b64encode(_PNG_BYTES).decode()}]}
        ),
    })
    _install_fake_image_client(monkeypatch, client)
    toolbox = build_core_toolbox(work_root=tmp_path, imagegen_config=IMAGE_CONFIG, approval_policy="auto_approve")

    result = await toolbox.execute(
        ToolCall(id="img-1", name="generate_image", arguments={"prompt": "a red cat", "count": 2})
    )

    assert result.status == "ok"
    url, payload = client.posts[0]
    assert url.endswith("/images/generations")
    assert payload["prompt"] == "a red cat"
    assert payload["n"] == 2
    assert payload["model"] == "img-model-1"
    assert result.artifacts and result.artifacts[0].kind == "image"
    rel = result.artifacts[0].uri
    assert rel.startswith(".lam/artifacts/images/")
    saved = tmp_path / rel
    assert saved.exists()
    assert saved.read_bytes() == _PNG_BYTES


@pytest.mark.asyncio
async def test_generate_image_reference_edit_with_local_reference(tmp_path, monkeypatch):
    import base64

    (tmp_path / "ref.png").write_bytes(_PNG_BYTES)
    client = FakeImageClient(routes={
        "post:https://img.example.com/v1/images/edits": FakeImageResponse(
            json_data={"data": [{"b64_json": base64.b64encode(_PNG_BYTES).decode()}]}
        ),
    })
    _install_fake_image_client(monkeypatch, client)
    toolbox = build_core_toolbox(work_root=tmp_path, imagegen_config=IMAGE_CONFIG, approval_policy="auto_approve")

    result = await toolbox.execute(
        ToolCall(
            id="img-edit-1",
            name="generate_image",
            arguments={"prompt": "make it night", "reference_urls": ["ref.png"]},
        )
    )

    assert result.status == "ok"
    assert client.multipart_posts, "expected a multipart /images/edits request"
    url, files, data = client.multipart_posts[0]
    assert url.endswith("/images/edits")
    assert data["prompt"] == "make it night"
    assert data["model"] == "img-model-1"
    assert files[0][0] == "image"
    assert files[0][1][1] == _PNG_BYTES  # local reference uploaded as file bytes
    assert files[0][1][2] == "image/png"
    assert result.artifacts and result.artifacts[0].kind == "image"
    assert (tmp_path / result.artifacts[0].uri).exists()


@pytest.mark.asyncio
async def test_generate_image_reference_edit_with_http_url(tmp_path, monkeypatch):
    import base64

    client = FakeImageClient(routes={
        "get:https://cdn.example.com/ref.png": FakeImageResponse(
            content=_PNG_BYTES, headers={"content-type": "image/png"}
        ),
        "post:https://img.example.com/v1/images/edits": FakeImageResponse(
            json_data={"data": [{"b64_json": base64.b64encode(_PNG_BYTES).decode()}]}
        ),
    })
    _install_fake_image_client(monkeypatch, client)
    toolbox = build_core_toolbox(work_root=tmp_path, imagegen_config=IMAGE_CONFIG, approval_policy="auto_approve")

    result = await toolbox.execute(
        ToolCall(
            id="img-edit-2",
            name="generate_image",
            arguments={"prompt": "make it night", "reference_urls": ["https://cdn.example.com/ref.png"]},
        )
    )

    assert result.status == "ok"
    assert client.gets == ["https://cdn.example.com/ref.png"]
    assert client.multipart_posts and client.multipart_posts[0][0].endswith("/images/edits")
    assert client.multipart_posts[0][1][0][1][1] == _PNG_BYTES


@pytest.mark.asyncio
async def test_generate_image_timeout_returns_failed(tmp_path, monkeypatch):
    import httpx

    class SlowClient(FakeImageClient):
        async def post(self, url, json=None):
            raise httpx.ReadTimeout("timed out", request=None)

    _install_fake_image_client(monkeypatch, SlowClient())
    toolbox = build_core_toolbox(work_root=tmp_path, imagegen_config=IMAGE_CONFIG, approval_policy="auto_approve")

    result = await toolbox.execute(ToolCall(id="img-t", name="generate_image", arguments={"prompt": "slow"}))

    assert result.status == "failed"
    assert "超时" in result.error
