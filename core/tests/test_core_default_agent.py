from __future__ import annotations

import json

import pytest

from lamtools_core.app.default_agent import (
    CoreAgentPaths,
    CoreAgentSpec,
    create_core_agent_operations,
)
from lamtools_core.app.base_agent import build_core_plugin_operation_catalog
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.llm.shallow_thinking import SHALLOW_THINKING_PROMPT
from lamtools_core.plugins.hook_config import HookRegistry
from lamtools_core.plugins.registry import PluginRegistry
from lamtools_core.plugins.trust import HookTrustStore


async def _fake_model(turn):
    from lamtools_core.app import ModelTurnOutput

    return ModelTurnOutput(message=f"core handled: {turn.user_message}")


class ScriptedCoreAgentLLM:
    def __init__(self, *, path: str = "input.txt") -> None:
        self.requests: list[LLMRequest] = []
        self.path = path

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core agent operation should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield LLMStreamEvent(kind="thinking_delta", content="Need to inspect the file.")
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(id="call-read", name="read_file", arguments={"path": self.path}),
                ],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="The file says hello core.")
        yield LLMStreamEvent(kind="done")


class ScriptedApprovalLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core agent operation should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield LLMStreamEvent(kind="thinking_delta", content="Need approval before writing.")
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[
                    LLMToolCall(
                        id="call-write",
                        name="write_file",
                        arguments={"path": "approved.md", "content": "approved content\n"},
                    ),
                ],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="Saved approved.md.")
        yield LLMStreamEvent(kind="done")


class ScriptedLoadSkillLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core agent operation should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            tool_names = {tool["function"]["name"] for tool in request.tools or []}
            assert "load_skill" in tool_names
            assert "Available skills:" in request.messages[0].content
            assert "<name>sample</name>" in request.messages[0].content
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[LLMToolCall(id="call-skill", name="load_skill", arguments={"name": "sample"})],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="Loaded sample skill.")
        yield LLMStreamEvent(kind="done")


class CapturingCoreAgentLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("core agent operation should use streaming when available")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        yield LLMStreamEvent(kind="content_delta", content="done")
        yield LLMStreamEvent(kind="done")


@pytest.mark.asyncio
async def test_core_agent_runs_independent_turn_with_in_memory_store(tmp_path):
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path, work_root=tmp_path),
        model_provider=_fake_model,
    )

    result = await catalog.execute(
        "turn.start",
        {"thread_id": "thread-1", "message": "do work"},
    )

    assert result.status == "ok"
    assert result.payload["message"] == "core handled: do work"
    assert result.payload["snapshot"]["thread_id"] == "thread-1"
    assert result.payload["snapshot"]["status"] == "completed"


@pytest.mark.asyncio
async def test_core_agent_operations_expose_turn_start(tmp_path):
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path, work_root=tmp_path),
        model_provider=_fake_model,
    )

    assert catalog.has("turn.start")
    assert "turn.start" in catalog.list()


def test_core_agent_operations_include_core_plugin_and_hook_catalog(tmp_path):
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path),
        model_provider=_fake_model,
    )

    assert {"plugin.list", "plugin.enable", "plugin.disable", "hook.list", "hook.trust"} <= set(catalog.list())


@pytest.mark.asyncio
async def test_core_agent_operations_expose_command_catalog(tmp_path):
    core_root = tmp_path / "core-root"
    command_dir = core_root / "command"
    command_dir.mkdir(parents=True)
    (command_dir / "inspect.json").write_text(
        json.dumps(
            {
                "name": "inspect",
                "title": "Inspect",
                "description": "Inspect context",
                "icon": "search",
                "action": "insert_token",
            }
        ),
        encoding="utf-8",
    )
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=_fake_model,
        command_core_roots=[core_root],
    )

    result = await catalog.execute("command.catalog", {})

    assert result.status == "ok"
    assert result.payload["commands"] == [
        {
            "name": "inspect",
            "title": "Inspect",
            "description": "Inspect context",
            "icon": "search",
            "action": "insert_token",
            "source": "core",
            "accepts_args": False,
        }
    ]


def test_core_agent_spec_accepts_member_paths_without_product_names(tmp_path):
    spec = CoreAgentSpec(member_id="sample", name="Sample Agent")
    paths = CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work")

    assert spec.member_id == "sample"
    assert spec.id == "core-agent"
    assert paths.data_dir.name == "data"
    assert paths.work_root.name == "work"


@pytest.mark.asyncio
async def test_core_agent_operation_runs_kernel_tool_loop_and_projects_snapshot(tmp_path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    (work_root / "input.txt").write_text("hello core\n", encoding="utf-8")
    llm = ScriptedCoreAgentLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
    )

    result = await catalog.execute(
        "turn.start",
        {"thread_id": "thread-kernel", "message": "read the file"},
    )

    assert result.status == "ok"
    assert result.payload["message"] == "The file says hello core."
    assert result.payload["snapshot"]["status"] == "completed"
    assert any(item["kind"] == "tool_call" for item in result.payload["run_items"])
    assert any(item["kind"] == "tool_result" for item in result.payload["run_items"])
    assert len(llm.requests) == 2
    assert {tool["function"]["name"] for tool in llm.requests[0].tools or []} >= {"read_file", "write_file"}


@pytest.mark.asyncio
async def test_core_agent_kernel_uses_supplied_live_turn_as_run_and_turn_identity(tmp_path):
    llm = CapturingCoreAgentLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=llm,
    )

    result = await catalog.execute(
        "turn.start",
        {
            "thread_id": "thread-supplied-id",
            "message": "complete",
            "run_id": "turn-live-1",
            "turn_id": "turn-live-1",
        },
    )

    assert result.payload["run_id"] == "turn-live-1"
    assert result.payload["turn_id"] == "turn-live-1"
    assert {item["run_id"] for item in result.payload["run_items"]} == {"turn-live-1"}
    assert {item["turn_id"] for item in result.payload["run_items"]} == {"turn-live-1"}


@pytest.mark.asyncio
async def test_core_agent_direct_turn_generates_its_own_run_id(tmp_path):
    llm = CapturingCoreAgentLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=llm,
    )

    result = await catalog.execute("turn.start", {"thread_id": "thread-direct-id", "message": "complete"})

    assert result.payload["run_id"]
    assert result.payload["turn_id"] == f"thread-direct-id:turn:{result.payload['run_id']}"


@pytest.mark.asyncio
async def test_core_agent_operation_applies_per_turn_model_and_shallow_thinking(tmp_path):
    llm = CapturingCoreAgentLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(default_model="default-model"),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=llm,
    )

    result = await catalog.execute(
        "turn.start",
        {
            "thread_id": "thread-runtime-options",
            "message": "hello",
            "model_id": "turn-model",
            "thinking_enabled": False,
            "thinking_budget": 1234,
            "shallow_thinking_enabled": True,
        },
    )

    assert result.status == "ok"
    assert llm.requests
    assert llm.requests[0].model == "turn-model"
    assert llm.requests[0].metadata["thinking_enabled"] is False
    assert llm.requests[0].metadata["thinking_budget"] == 1234
    assert any(message.content == SHALLOW_THINKING_PROMPT for message in llm.requests[0].messages)


@pytest.mark.asyncio
async def test_core_agent_operation_loads_plugin_skill_roots(tmp_path):
    plugin_root = tmp_path / "plugins"
    sample = plugin_root / "sample"
    skill_dir = sample / "skills"
    skill_dir.mkdir(parents=True)
    (sample / "plugin.json").write_text(
        '{"name":"sample","version":"1.0.0","skills":["./skills"]}',
        encoding="utf-8",
    )
    (skill_dir / "shared.md").write_text("plugin skill resource\n", encoding="utf-8")
    llm = ScriptedCoreAgentLLM(path="shared.md")
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=llm,
        plugin_roots=[plugin_root],
    )

    result = await catalog.execute(
        "turn.start",
        {"thread_id": "thread-plugin", "message": "read plugin skill resource"},
    )

    tool_results = [item for item in result.payload["run_items"] if item["kind"] == "tool_result"]
    assert result.status == "ok"
    assert tool_results
    assert tool_results[0]["status"] == "completed"
    assert "plugin skill resource" in tool_results[0]["payload"]["tool_result"]


@pytest.mark.asyncio
async def test_core_agent_operation_exposes_load_skill_to_model(tmp_path):
    work_root = tmp_path / "work"
    skill_dir = work_root / ".agents" / "skills" / "sample"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: sample\n"
        "description: Sample Core skill.\n"
        "---\n"
        "# Sample Core Skill\n"
        "Use this content in the answer.\n",
        encoding="utf-8",
    )
    llm = ScriptedLoadSkillLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
    )

    result = await catalog.execute("turn.start", {"thread_id": "thread-skill", "message": "use sample skill"})

    tool_results = [item for item in result.payload["run_items"] if item["kind"] == "tool_result"]
    assert result.status == "ok"
    assert result.payload["message"] == "Loaded sample skill."
    assert tool_results
    assert "<skill_content name=\"sample\">" in tool_results[0]["payload"]["tool_result"]
    assert len(llm.requests) == 2


@pytest.mark.asyncio
async def test_core_agent_operation_runs_trusted_pre_tool_hook(tmp_path):
    data_dir = tmp_path / "data"
    work_root = tmp_path / "work"
    work_root.mkdir()
    (work_root / "input.txt").write_text("hook should block this\n", encoding="utf-8")
    plugin_root = tmp_path / "plugins"
    sample = plugin_root / "sample"
    hooks_dir = sample / "hooks"
    hooks_dir.mkdir(parents=True)
    hook_script = sample / "block_read.py"
    hook_script.write_text(
        "import json\n"
        "print(json.dumps({'decision':'block','reason':'blocked by trusted hook'}))\n",
        encoding="utf-8",
    )
    (sample / "plugin.json").write_text(
        '{"name":"sample","version":"1.0.0","hooks":["./hooks/hooks.json"]}',
        encoding="utf-8",
    )
    (hooks_dir / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "read_file",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": f'py -3.14 "{hook_script}"',
                                    "timeout": 5,
                                    "required": True,
                                }
                            ],
                        }
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    plugins = PluginRegistry(plugin_roots=[plugin_root]).discover()
    hooks = HookRegistry(
        project_root=work_root,
        plugins=plugins,
        trust_store=HookTrustStore(data_dir / "hook_trust.json"),
    ).load()
    trust_store = HookTrustStore(data_dir / "hook_trust.json")
    trust_store.trust(hooks[0].definition_hash)
    llm = ScriptedCoreAgentLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=data_dir, work_root=work_root),
        model_provider=llm,
        plugin_roots=[plugin_root],
    )

    result = await catalog.execute("turn.start", {"thread_id": "thread-hook", "message": "read the file"})

    tool_results = [item for item in result.payload["run_items"] if item["kind"] == "tool_result"]
    assert result.status == "ok"
    assert tool_results
    assert tool_results[0]["status"] == "failed"
    assert "blocked by trusted hook" in tool_results[0]["payload"]["tool_result"]


@pytest.mark.asyncio
async def test_core_plugin_operation_catalog_uses_user_and_project_roots(tmp_path, monkeypatch):
    appdata = tmp_path / "appdata"
    data_dir = tmp_path / "data"
    work_root = tmp_path / "work"
    user_plugin = appdata / "LamTools" / "plugins" / "user-policy"
    project_plugin = work_root / ".lamtools" / "plugins" / "project-policy"
    monkeypatch.setenv("APPDATA", str(appdata))
    user_plugin.mkdir(parents=True)
    project_plugin.mkdir(parents=True)
    (user_plugin / "plugin.json").write_text('{"name":"user-policy","version":"1.0.0"}', encoding="utf-8")
    (project_plugin / "plugin.json").write_text('{"name":"project-policy","version":"1.0.0"}', encoding="utf-8")

    catalog = build_core_plugin_operation_catalog(
        data_dir=data_dir,
        work_root=work_root,
        include_user_plugins=True,
    )
    listed = await catalog.execute("plugin.list")
    await catalog.execute("plugin.disable", {"name": "user-policy"})

    assert {item["name"] for item in listed.payload["plugins"]} == {"user-policy", "project-policy"}
    assert (data_dir / "plugins.json").exists()
    assert not (data_dir / "core-plugin-state.json").exists()


@pytest.mark.asyncio
async def test_core_agent_approval_respond_executes_pending_tool_and_continues(tmp_path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    llm = ScriptedApprovalLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
    )

    waiting = await catalog.execute("turn.start", {"thread_id": "thread-approval", "message": "write a file"})
    approved = await catalog.execute("approval.respond", {"thread_id": "thread-approval", "action": "approve"})

    assert waiting.status == "ok"
    assert waiting.payload["decision"] == "wait"
    assert approved.status == "ok"
    assert approved.payload["decision"] == "done"
    assert approved.payload["message"] == "Saved approved.md."
    assert (work_root / "approved.md").read_text(encoding="utf-8") == "approved content\n"
    assert len(llm.requests) == 2


@pytest.mark.asyncio
async def test_core_agent_approval_respond_normalizes_legacy_thread_action_and_response(tmp_path):
    work_root = tmp_path / "work"
    work_root.mkdir()
    llm = ScriptedApprovalLLM()
    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=work_root),
        model_provider=llm,
    )

    waiting = await catalog.execute("turn.start", {"thread_id": "thread-legacy", "message": "write a file"})
    approved = await catalog.execute(
        "approval.respond",
        {"thread_id": "thread-legacy", "action": "approve_for_session", "response": ""},
    )

    assert waiting.payload["decision"] == "wait"
    assert approved.status == "ok"
    assert (work_root / "approved.md").read_text(encoding="utf-8") == "approved content\n"
