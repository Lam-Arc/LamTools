"""user:“并完成验证”+(用真实 MCP 子进程和宿主客户端验证原服务器，绝不借用用户凭证)。"""
import ast
import json
import os
from pathlib import Path

import pytest

from lamtools_core.mcp.client import MCPClient
from lamtools_core.mcp.config import load_mcp_server_configs
from lamtools_core.plugin_system.loading import load_module
from tests.test_bili_scroll_rebuild import installed


@pytest.fixture
async def mcp(installed):
    interpreter = os.environ.get("BILI_ACCEPTANCE_PYTHON")
    if not interpreter:
        pytest.skip("set BILI_ACCEPTANCE_PYTHON to an environment with the declared MCP dependencies")
    host, manager, catalog, calls = installed
    root = host.get("bili-scroll").root
    configs = load_mcp_server_configs(root, config_files=[root / "mcp/mcp.json"], default_paths=[])
    config = next(item for item in configs if item.name == "bilibili")
    config.command = interpreter
    config.timeout_seconds = 20
    client = MCPClient(config)
    try:
        await client.start()
        yield client, root, catalog
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_original_mcp_tool_inventory_and_schemas_are_preserved(mcp):
    client, root, catalog = mcp
    source = ast.parse((root / "vendor/bilibili-mcp/mcp_server.py").read_text(encoding="utf-8"))
    expected = {node.name for node in source.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and any(isinstance(item, ast.Call) and getattr(item.func, "id", "") == "tool" for item in node.decorator_list)}
    allowed = set(client.config.env["BILI_MCP_TOOLS"].split(","))
    tools = {tool.name: tool for tool in await client.list_tools()}
    assert set(tools) == expected & allowed
    assert len(tools) == 34
    assert "keyword" in tools["bili_search"].input_schema["properties"]
    assert "force" in tools["bili_reply"].input_schema["properties"]


@pytest.mark.asyncio
async def test_real_server_report_dedup_archive_and_write_guards(mcp):
    client, root, catalog = mcp
    paths = await client.call_tool("duty_paths", {})
    payload = json.loads(paths["content"][0]["text"])
    assert Path(payload["home"]).resolve() == (root / "data/duty").resolve()
    await client.call_tool("duty_report_append", {"text": "### BV1234567890\n验收日报"})
    await client.call_tool("duty_seen_append", {"bvid": "BV1234567890", "title": "Test", "up": "UP", "status": "picked"})
    await client.call_tool("duty_digest_append", {"text": "验收归档"})
    recent = await client.call_tool("duty_seen_recent", {"bvid": "BV1234567890"})
    assert "BV1234567890" in recent["content"][0]["text"]
    report = await catalog.execute("bili-scroll.report_read")
    assert "验收日报" in report.payload["text"]
    # A real MCP request reaches the execution guard; no account action occurs.
    denied = await client.call_tool("bili_reply", {"bvid": "BV1234567890", "text": "must not publish"})
    assert json.loads(denied["content"][0]["text"])["blocked"]
    denied = await client.call_tool("bili_send_message", {"receiver_uid": 42, "text": "must not send"})
    assert json.loads(denied["content"][0]["text"])["blocked"]


@pytest.mark.asyncio
async def test_transcription_job_is_observable_while_other_mcp_calls_continue(mcp):
    client, root, catalog = mcp
    # No ASR environment is installed in this private test home. The server
    # must still return a job immediately and keep serving other requests.
    response = await client.call_tool("bili_transcribe_start", {"bvid": "BV1234567890"})
    body = json.loads(response["content"][0]["text"])
    assert body.get("ok") is False and body.get("error"), body
    await client.call_tool("duty_paths", {})
    result = await client.call_tool("bili_transcribe_result", {"job_id": "unknown-acceptance-job"})
    assert not result.get("isError"), result


@pytest.mark.asyncio
async def test_actual_agent_profile_calls_mcp_and_writes_report(mcp, monkeypatch):
    from dataclasses import replace
    from lamtools_core.llm import LLMStreamEvent, LLMToolCall
    from lamtools_core.plugin_system.profiles import resolve_profile
    from lamtools_core.plugin_system.manifest import load_manifest
    from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner
    from tests.test_core_sub_agent_runner import _write_project_model
    client, root, catalog = mcp
    _write_project_model(root, "fake-model", "text")
    spec = replace(resolve_profile([load_manifest(root / "plugin.json")], "bili-scroll:duty"), model_scene="", skills=())
    steps = [("duty_paths", {}), ("duty_report_append", {"text": "### BV1234567890\n受控模型通过宿主写出的日报"}),
             ("duty_seen_append", {"bvid": "BV1234567890", "title": "Probe", "up": "Probe", "status": "picked"})]
    class Model:
        def __init__(self):
            self.index = 0
        async def complete(self, request):
            raise AssertionError("the real agent must use streaming")
        async def stream(self, request):
            assert {item["function"]["name"] for item in request.tools} == {"mcp"}
            if self.index < len(steps):
                name, args = steps[self.index]
                self.index += 1
                yield LLMStreamEvent(kind="done", tool_calls=[LLMToolCall(id=f"call-{self.index}", name="mcp",
                    arguments={"action": "run", "tool_name": "mcp__bilibili__" + name, "arguments": args})])
            else:
                yield LLMStreamEvent(kind="content_delta", content="验收完成")
                yield LLMStreamEvent(kind="done")
    from lamtools_core.mcp.registry import MCPToolRegistry
    config = client.config
    registry = MCPToolRegistry(root, config_loader=lambda _: [config])
    await registry.load()
    try:
        runner = KernelSubAgentRunner(work_root=root, llm_client=Model(), model_id="fake-model", mcp_caller=registry,
                                      permission_preset="auto", approval_policy="auto_approve")
        result = await runner.run(task="验收值守轮", agent="bili-acceptance", profile_spec=spec)
        assert result.decision == "done", result
        report = (await catalog.execute("bili-scroll.report_read")).payload["text"]
        assert "受控模型通过宿主写出的日报" in report
    finally:
        await registry.close()


@pytest.mark.asyncio
async def test_actual_mcp_process_is_closed_by_plugin_disable(mcp, installed):
    from lamtools_core.mcp.registry import MCPToolRegistry
    client, root, catalog = mcp
    host, manager, _, _ = installed
    registry = MCPToolRegistry(root, config_files=[root / "mcp/mcp.json"], config_loader=lambda _: [client.config], plugin_host=host)
    await registry.load()
    process = registry._clients["bilibili"]._proc
    assert process.returncode is None
    assert "home" in await registry.call("mcp__bilibili__duty_paths", {})
    result = await catalog.execute("plugin.system.disable", {"name": "bili-scroll"})
    assert result.status == "ok"
    assert registry.server_names == []
    assert process.returncode is not None


@pytest.mark.asyncio
async def test_standalone_diagnostic_client_resolves_current_templates(mcp):
    # user:“都试一试”+(诊断客户端也解析同一环境模板，不残留旧机器路径)。
    import asyncio
    import subprocess
    client, root, catalog = mcp
    await catalog.execute("bili-scroll.config_update", {"pythonPath": client.config.command})
    result = await asyncio.to_thread(subprocess.run, [client.config.command, "-X", "utf8", str(root / "scripts/mcp_call.py"), "--list"],
                                     capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    assert "bili_search" in result.stdout and "duty_report_append" in result.stdout
