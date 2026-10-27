"""user:“把 MCP 从 toolbox 里面拿出去，通过 command 运行”+(验证真实命令通路与隔离)。"""
import json
import sys
from types import SimpleNamespace

import pytest

from lamtools_core.tool import ToolCall, ToolSpec
from lamtools_core.tool.default_toolbox import build_core_toolbox


class Registry:
    server_names = ["local"]
    tools = [SimpleNamespace(server="local", name="echo", function_name="mcp__local__echo",
                             description="Echo", input_schema={"type": "object"}, permission="auto_allow")]

    def __init__(self):
        self.calls = []

    def resolve(self, name):
        return next((t for t in self.tools if t.function_name == name), None)

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        return "echo:" + arguments["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["core", "core.exe", "python -m lamtools_core.cli", "py -3.14 -m lamtools_core.cli"])
async def test_cli_aliases_use_the_same_mcp_permission_route(prefix):
    from lamtools_core.mcp.command_service import MCPCommandService
    service = MCPCommandService(Registry(), loaded=True)
    command = prefix + " mcp call --tool mcp__local__echo --arguments '{\"text\":\"alias\"}'"
    assert service.level_for_command(command) == 3
    assert await service.execute_command(command) == "echo:alias"


@pytest.mark.asyncio
async def test_mcp_query_and_execution_are_separate(tmp_path):
    registry = Registry()
    toolbox = build_core_toolbox(work_root=tmp_path, mcp_caller=registry,
        mcp_tool_specs=[ToolSpec(name="mcp__local__echo", description="Echo", input_schema={})],
        approval_policy="auto_approve", permission_preset="full_access")
    names = {s.name for s in toolbox.tool_specs()}
    assert "mcp" in names
    assert not ({"mcp_activate", "mcp_tool", "mcp__local__echo"} & names)
    query = await toolbox.execute(ToolCall(id="query", name="mcp", arguments={"action": "schema", "tool_name": "mcp__local__echo"}))
    assert query.status == "ok" and "input_schema" in query.content
    assert registry.calls == []
    command = "core mcp call --tool mcp__local__echo --arguments '{\"text\":\"hello; $world\"}'"
    result = await toolbox.execute(ToolCall(id="call", name="run_command", arguments={"command": command}))
    assert result.status == "ok" and "echo:hello; $world" in result.content
    assert registry.calls == [("mcp__local__echo", {"text": "hello; $world"})]
    for old in ("mcp_activate", "mcp_tool", "mcp__local__echo"):
        rejected = await toolbox.execute(ToolCall(id=old, name=old, arguments={}))
        assert rejected.status != "ok"


@pytest.mark.asyncio
async def test_profile_command_cannot_escape_mcp_whitelist(tmp_path):
    from lamtools_core.plugin_system.profiles import ProfileSpec, apply_profile
    registry = Registry()
    toolbox = build_core_toolbox(work_root=tmp_path, mcp_caller=registry, approval_policy="auto_approve")
    apply_profile(toolbox, ProfileSpec("sample:duty", "sample", "duty", tools=("mcp", "run_command"),
                                     mcp_tools=("mcp__local__echo",)))
    for command in ("echo unsafe", "core mcp call --tool mcp__other__write --arguments '{}'",
                    "core mcp call --tool mcp__local__echo --arguments '{}' ; echo unsafe"):
        result = await toolbox.execute(ToolCall(id="denied", name="run_command", arguments={"command": command}))
        assert result.status != "ok"
    assert registry.calls == []


@pytest.mark.asyncio
async def test_command_approval_is_not_bypassed(tmp_path):
    registry = Registry()
    toolbox = build_core_toolbox(work_root=tmp_path, mcp_caller=registry, approval_policy="require")
    call = ToolCall(id="pending", name="run_command", arguments={"command": "core mcp call --tool mcp__local__echo --arguments '{}'"})
    assert toolbox.prepare_call(call).requires_approval
    assert (await toolbox.execute(call)).status != "ok"
    assert not registry.calls


@pytest.mark.asyncio
async def test_command_bridge_uses_real_stdio_and_closes_server(tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("mcp_fixture", Path(__file__).with_name("test_core_mcp_registry.py"))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    _write_server, _write_mcp_config = fixture._write_server, fixture._write_mcp_config
    from lamtools_core.mcp import MCPToolRegistry
    from lamtools_core.mcp.command_service import MCPCommandService
    config = tmp_path / "mcp.json"
    _write_mcp_config(config, _write_server(tmp_path))
    registry = MCPToolRegistry(tmp_path, config_files=[config])
    service = MCPCommandService(registry)
    try:
        result = await service.execute_command("core mcp call --tool mcp__local__echo --arguments '{\"text\":\"real\"}'")
        assert result == "echo:real"
        assert registry.server_names == ["local"]
    finally:
        await service.close()
    assert registry.server_names == []


@pytest.mark.asyncio
async def test_mcp_tool_run_uses_the_same_registry_and_level(tmp_path):
    registry = Registry()
    toolbox = build_core_toolbox(
        work_root=tmp_path,
        mcp_caller=registry,
        approval_policy="auto_approve",
        permission_preset="full_access",
    )
    result = await toolbox.execute(
        ToolCall(
            id="run",
            name="mcp",
            arguments={
                "action": "run",
                "tool_name": "mcp__local__echo",
                "arguments": {"text": "hi"},
            },
        )
    )
    assert result.status == "ok" and "echo:hi" in result.content
    assert registry.calls == [("mcp__local__echo", {"text": "hi"})]


@pytest.mark.asyncio
async def test_profile_mcp_whitelist_covers_mcp_action_run(tmp_path):
    from lamtools_core.plugin_system.profiles import ProfileSpec, apply_profile

    registry = Registry()
    toolbox = build_core_toolbox(
        work_root=tmp_path,
        mcp_caller=registry,
        approval_policy="auto_approve",
        permission_preset="full_access",
    )
    apply_profile(
        toolbox,
        ProfileSpec(
            "sample:duty",
            "sample",
            "duty",
            tools=("mcp",),
            mcp_tools=("mcp__local__echo",),
            approved_tools=("mcp__local__echo",),
        ),
    )
    denied = await toolbox.execute(
        ToolCall(
            id="denied",
            name="mcp",
            arguments={"action": "run", "tool_name": "mcp__other__write", "arguments": {}},
        )
    )
    assert denied.status == "blocked"
    allowed = await toolbox.execute(
        ToolCall(
            id="allowed",
            name="mcp",
            arguments={
                "action": "run",
                "tool_name": "mcp__local__echo",
                "arguments": {"text": "ok"},
            },
        )
    )
    assert allowed.status == "ok" and "echo:ok" in allowed.content
    assert registry.calls == [("mcp__local__echo", {"text": "ok"})]


@pytest.mark.asyncio
async def test_background_runner_preloads_rules_and_uses_command(tmp_path):
    from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner
    from lamtools_core.plugin_system.profiles import ProfileSpec
    from lamtools_core.llm import LLMStreamEvent, LLMToolCall

    class Model:
        requests = []
        async def stream(self, request):
            self.requests.append(request)
            assert any("preloaded duty rule" in str(m.content) for m in request.messages)
            assert not any(t["function"]["name"].startswith("mcp__") for t in request.tools)
            yield LLMStreamEvent(kind="content_delta", content="done")
            yield LLMStreamEvent(kind="done")
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=Model(), model_id="test-model",
        skill_registry=SimpleNamespace(prompt_index=lambda *a, **k: "", load_prompt_content=lambda *a, **k: "preloaded duty rule"),
        activated_mcp_servers={"baseline"})
    profile = ProfileSpec("test:duty", "test", "duty", tools=("mcp", "run_command"),
                          skills=("duty",), mcp_servers=("local",), mcp_tools=("mcp__local__echo",))
    result = await runner.run(task="do duty", agent="duty", profile_spec=profile)
    assert result.decision == "done"
    assert runner.activated_mcp_servers == {"baseline"}


@pytest.mark.asyncio
async def test_cli_executes_same_real_command_service(tmp_path, capsys):
    import importlib.util
    from pathlib import Path
    from lamtools_core.cli_commands.mcp import register_mcp
    import argparse
    spec = importlib.util.spec_from_file_location("cli_mcp_fixture", Path(__file__).with_name("test_core_mcp_registry.py"))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    config = tmp_path / "mcp.json"
    fixture._write_mcp_config(config, fixture._write_server(tmp_path))
    parser = argparse.ArgumentParser()
    register_mcp(parser.add_subparsers())
    args = parser.parse_args(["mcp", "call", "--config", str(config), "--work-root", str(tmp_path),
                             "--tool", "mcp__local__echo", "--arguments", '{"text":"cli"}'])
    assert await args.func(args) == 0
    assert "echo:cli" in capsys.readouterr().out


def test_readonly_assistant_capability_stays_a_hard_boundary(tmp_path):
    toolbox = build_core_toolbox(work_root=tmp_path, permission_preset="full_access")
    toolbox.capability_tool_whitelist = frozenset({"read_file"})
    assert {tool["function"]["name"] for tool in toolbox.model_tools()} == {"read_file"}


@pytest.mark.asyncio
async def test_main_chat_executes_plugin_mcp_only_through_command(tmp_path):
    import importlib.util
    from pathlib import Path
    from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
    from lamtools_core.llm import LLMStreamEvent, LLMToolCall
    spec = importlib.util.spec_from_file_location("main_mcp_fixture", Path(__file__).with_name("test_core_mcp_registry.py"))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    root = tmp_path / "plugins/sample"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({"name": "sample", "version": "1.0.0", "mcp": ["./mcp/mcp.json"]}), encoding="utf8")
    config = root / "mcp/mcp.json"
    fixture._write_mcp_config(config, fixture._write_server(tmp_path))
    data = json.loads(config.read_text(encoding="utf8"))
    data["mcpServers"]["local"]["toolLevels"] = {"echo": 1}
    config.write_text(json.dumps(data), encoding="utf8")
    class Model:
        calls = 0
        async def complete(self, request):
            raise AssertionError("streaming expected")
        async def stream(self, request):
            self.calls += 1
            names = {tool["function"]["name"] for tool in request.tools}
            assert "mcp" in names and not any(name.startswith("mcp__") for name in names)
            if self.calls == 1:
                yield LLMStreamEvent(kind="done", tool_calls=[LLMToolCall(id="echo", name="run_command", arguments={
                    "command": "core mcp call --tool mcp__local__echo --arguments '{\"text\":\"main\"}'"})])
            else:
                yield LLMStreamEvent(kind="content_delta", content="done")
                yield LLMStreamEvent(kind="done")
    model = Model()
    catalog = create_core_agent_operations(spec=CoreAgentSpec(), paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
                                          model_provider=model, plugin_roots=[root.parent])
    result = await catalog.execute("turn.start", {"thread_id": "main-mcp-command", "message": "echo"})
    assert result.status == "ok"
    assert model.calls == 2
    results = [item for item in result.payload["run_items"] if item["kind"] == "tool_result"]
    assert any("echo:main" in item["payload"]["tool_result"] for item in results)


@pytest.mark.asyncio
async def test_profile_approval_resume_keeps_mcp_rules_and_budget(tmp_path, instant_model_retry_sleep):
    import importlib.util
    from pathlib import Path
    from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner
    from lamtools_core.plugin_system.profiles import ProfileSpec, ProfileBudget
    from lamtools_core.llm import LLMStreamEvent, LLMToolCall
    spec = importlib.util.spec_from_file_location("resume_mcp_fixture", Path(__file__).with_name("test_core_mcp_registry.py"))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    config = tmp_path / "mcp.json"
    fixture._write_mcp_config(config, fixture._write_server(tmp_path))
    class Model:
        calls = 0
        async def stream(self, request):
            self.calls += 1
            assert any("resume duty rule" in str(message.content) for message in request.messages), "missing preloaded rules"
            assert {tool["function"]["name"] for tool in request.tools} <= {"mcp", "run_command"}
            if self.calls == 1:
                yield LLMStreamEvent(kind="done", tool_calls=[LLMToolCall(id="echo", name="run_command", arguments={
                    "command": "core mcp call --tool mcp__local__echo --arguments '{\"text\":\"resumed\"}'"})])
            else:
                assert any("echo:resumed" in str(message.content) for message in request.messages), str([(m.role, str(m.content)[-500:]) for m in request.messages])
                yield LLMStreamEvent(kind="content_delta", content="done")
                yield LLMStreamEvent(kind="done")
    runner = KernelSubAgentRunner(work_root=tmp_path, llm_client=Model(), model_id="test-model", mcp_config_files=[config],
        skill_registry=SimpleNamespace(prompt_index=lambda *a, **k: "", load_prompt_content=lambda *a, **k: "resume duty rule"))
    profile = ProfileSpec("sample:duty", "sample", "duty", tools=("mcp", "run_command"),
                          mcp_tools=("mcp__local__echo",), skills=("duty",), budget=ProfileBudget(max_tool_calls=2))
    waiting = await runner.run(task="test", agent="duty", profile_spec=profile)
    assert waiting.decision == "wait"
    state = await runner.state_store.get(waiting.session_id)
    result = await runner.resume_approved(session_id=waiting.session_id, pending_call=state.metadata["pending_approval"]["tool_call"],
        task="test", agent="duty", parent_call_id="")
    assert result.decision == "done"
    state = await runner.state_store.get(result.session_id)
    assert state.metadata["run_profile_budget"]["tool_calls"] == 1
