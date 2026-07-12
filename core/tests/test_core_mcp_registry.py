from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from lamtools_core.app import CoreAgentPaths, CoreAgentSpec, create_core_agent_operations
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent, LLMToolCall
from lamtools_core.mcp import MCPToolRegistry, load_mcp_server_configs


SERVER_CODE = r'''
import json
import sys


def read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        text = line.decode("ascii").strip()
        if text == "":
            break
        key, value = text.split(":", 1)
        headers[key.lower()] = value.strip()
    body = sys.stdin.buffer.read(int(headers["content-length"]))
    return json.loads(body.decode("utf-8"))


def send(payload):
    body = json.dumps(payload).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


while True:
    msg = read_message()
    if msg is None:
        break
    method = msg.get("method")
    if "id" not in msg:
        continue
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"capabilities": {"tools": {}}}})
    elif method == "tools/list":
        send({
            "jsonrpc": "2.0",
            "id": msg["id"],
            "result": {
                "tools": [{
                    "name": "echo",
                    "description": "Echo text",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"]
                    }
                }]
            }
        })
    elif method == "tools/call":
        args = msg.get("params", {}).get("arguments", {})
        send({
            "jsonrpc": "2.0",
            "id": msg["id"],
            "result": {"content": [{"type": "text", "text": "echo:" + args.get("text", "")}]}
        })
    else:
        send({"jsonrpc": "2.0", "id": msg["id"], "error": {"message": "unknown method"}})
'''


class ScriptedMcpLLM:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core MCP test should use streaming")

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        if len(self.requests) == 1:
            tool_names = {tool["function"]["name"] for tool in request.tools or []}
            assert "mcp__local__echo" in tool_names
            yield LLMStreamEvent(kind="thinking_delta", content="Need MCP echo.")
            yield LLMStreamEvent(
                kind="done",
                tool_calls=[LLMToolCall(id="call-mcp", name="mcp__local__echo", arguments={"text": "ok"})],
            )
            return
        yield LLMStreamEvent(kind="content_delta", content="MCP returned echo:ok.")
        yield LLMStreamEvent(kind="done")


def _write_server(tmp_path: Path) -> Path:
    server = tmp_path / "mcp_echo_server.py"
    server.write_text(SERVER_CODE, encoding="utf-8")
    return server


def _write_mcp_config(path: Path, server: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "local": {
                        "command": sys.executable,
                        "args": [str(server)],
                        "timeout": 5,
                        "permission": "auto_allow",
                    }
                }
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_core_mcp_registry_loads_config_and_calls_tool(tmp_path: Path):
    server = _write_server(tmp_path)
    config = tmp_path / "mcp.json"
    _write_mcp_config(config, server)
    registry = MCPToolRegistry(tmp_path, config_files=[config])
    try:
        configs = load_mcp_server_configs(tmp_path, config_files=[config])
        assert configs[0].name == "local"

        await registry.load()
        definitions = registry.tool_definitions()

        assert definitions[0]["function"]["name"] == "mcp__local__echo"
        assert definitions[0]["function"]["strict"] is True
        assert definitions[0]["function"]["parameters"]["required"] == ["text"]
        assert await registry.call("mcp__local__echo", {"text": "hello", "_tool_call_id": "x"}) == "echo:hello"
    finally:
        await registry.close()


@pytest.mark.asyncio
async def test_core_agent_operation_loads_plugin_mcp_tools(tmp_path: Path):
    server = _write_server(tmp_path)
    plugin_root = tmp_path / "plugins"
    plugin = plugin_root / "sample"
    (plugin / "mcp").mkdir(parents=True)
    (plugin / "plugin.json").write_text(
        json.dumps({"name": "sample", "version": "1.0.0", "mcpServers": "./mcp/mcp.json"}),
        encoding="utf-8",
    )
    _write_mcp_config(plugin / "mcp" / "mcp.json", server)
    llm = ScriptedMcpLLM()

    catalog = create_core_agent_operations(
        spec=CoreAgentSpec(),
        paths=CoreAgentPaths(data_dir=tmp_path / "data", work_root=tmp_path / "work"),
        model_provider=llm,
        plugin_roots=[plugin_root],
    )

    result = await catalog.execute("turn.start", {"thread_id": "thread-mcp", "message": "call mcp"})

    tool_results = [item for item in result.payload["run_items"] if item["kind"] == "tool_result"]
    assert result.status == "ok"
    assert tool_results
    assert tool_results[0]["status"] == "completed"
    assert "echo:ok" in tool_results[0]["payload"]["tool_result"]
