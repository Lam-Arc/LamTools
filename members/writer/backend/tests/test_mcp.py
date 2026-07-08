from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from app.core.mcp.client import MCPClient
from app.core.mcp import client as mcp_client_module
from app.core.mcp.config import load_mcp_server_configs
from app.core.mcp.registry import MCPToolRegistry
from app.core.mcp.schemas import MCPServerConfig
from app.core.writer.permission import PermissionChecker
from app.core.writer.schemas import WriterAction


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
                        "required": ["text"],
                    },
                }]
            },
        })
    elif method == "tools/call":
        args = msg.get("params", {}).get("arguments", {})
        send({
            "jsonrpc": "2.0",
            "id": msg["id"],
            "result": {"content": [{"type": "text", "text": "echo:" + args.get("text", "")}]},
        })
    else:
        send({"jsonrpc": "2.0", "id": msg["id"], "error": {"message": "unknown method"}})
'''


SERVER_CODE_LINES = r'''
import json
import sys


while True:
    line = sys.stdin.buffer.readline()
    if not line:
        break
    msg = json.loads(line.decode("utf-8"))
    method = msg.get("method")
    if "id" not in msg:
        continue
    if method == "initialize":
        payload = {"jsonrpc": "2.0", "id": msg["id"], "result": {"capabilities": {"tools": {}}}}
    elif method == "tools/list":
        payload = {"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [{"name": "ping", "description": "Ping", "inputSchema": {"type": "object", "properties": {}}}]}}
    elif method == "tools/call":
        payload = {"jsonrpc": "2.0", "id": msg["id"], "result": {"content": [{"type": "text", "text": "pong"}]}}
    else:
        payload = {"jsonrpc": "2.0", "id": msg["id"], "error": {"message": "unknown method"}}
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()
'''


def test_windows_mcp_creationflags_hide_console(monkeypatch):
    monkeypatch.setattr(mcp_client_module.sys, "platform", "win32")
    monkeypatch.setattr(mcp_client_module.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    kwargs = mcp_client_module._subprocess_start_kwargs(env={"LAMWRITER_TEST": "1"})

    assert kwargs["creationflags"] & 0x08000000


def write_server(tmp_path: Path) -> Path:
    server = tmp_path / "mcp_echo_server.py"
    server.write_text(SERVER_CODE, encoding="utf-8")
    return server


def write_json_lines_server(tmp_path: Path) -> Path:
    server = tmp_path / "mcp_lines_server.py"
    server.write_text(SERVER_CODE_LINES, encoding="utf-8")
    return server


def set_env(name: str, value: str | None):
    old = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    return old


def restore_env(name: str, old: str | None) -> None:
    if old is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = old


@pytest.mark.asyncio
async def test_stdio_mcp_client_lists_and_calls_tool(tmp_path: Path):
    server = write_server(tmp_path)
    client = MCPClient(MCPServerConfig(
        name="local",
        command=sys.executable,
        args=[str(server)],
        timeout_seconds=5,
    ))
    try:
        await client.start()
        tools = await client.list_tools()
        assert [tool.writer_name for tool in tools] == ["mcp__local__echo"]

        result = await client.call_tool("echo", {"text": "ok"})
        assert result["content"][0]["text"] == "echo:ok"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_json_lines_mcp_client_lists_and_calls_tool(tmp_path: Path):
    server = write_json_lines_server(tmp_path)
    client = MCPClient(MCPServerConfig(
        name="lines",
        command=sys.executable,
        args=[str(server)],
        timeout_seconds=5,
        transport="json_lines",
    ))
    try:
        await client.start()
        tools = await client.list_tools()
        assert [tool.writer_name for tool in tools] == ["mcp__lines__ping"]

        result = await client.call_tool("ping", {})
        assert result["content"][0]["text"] == "pong"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mcp_registry_loads_config_and_formats_result(tmp_path: Path):
    server = write_server(tmp_path)
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({
        "servers": {
            "local": {
                "command": sys.executable,
                "args": [str(server)],
                "timeout_seconds": 5,
                "permission": "auto_allow",
            }
        }
    }), encoding="utf-8")
    old = set_env("LAMWRITER_MCP_CONFIG", str(config))
    old_builtin = set_env("LAMWRITER_BUILTIN_PLAYWRIGHT_MCP", "0")
    registry = MCPToolRegistry(str(tmp_path))
    try:
        configs = load_mcp_server_configs(str(tmp_path))
        assert configs[0].name == "local"

        await registry.load()
        definitions = registry.tool_definitions()
        assert definitions[0]["function"]["name"] == "mcp__local__echo"
        assert definitions[0]["function"]["parameters"]["required"] == ["text"]

        output = await registry.call("mcp__local__echo", {"text": "hello", "_tool_call_id": "x"})
        assert output == "echo:hello"
    finally:
        await registry.close()
        restore_env("LAMWRITER_MCP_CONFIG", old)
        restore_env("LAMWRITER_BUILTIN_PLAYWRIGHT_MCP", old_builtin)


def test_builtin_playwright_mcp_config_is_available(tmp_path: Path):
    old_config = set_env("LAMWRITER_MCP_CONFIG", None)
    old_builtin = set_env("LAMWRITER_BUILTIN_PLAYWRIGHT_MCP", "1")
    try:
        configs = load_mcp_server_configs(str(tmp_path))
    finally:
        restore_env("LAMWRITER_MCP_CONFIG", old_config)
        restore_env("LAMWRITER_BUILTIN_PLAYWRIGHT_MCP", old_builtin)

    playwright = [config for config in configs if config.name == "playwright"]
    assert playwright
    assert playwright[0].builtin is True
    assert playwright[0].permission == "ask_user"
    assert playwright[0].transport == "json_lines"
    assert "--headless" in playwright[0].args


def test_mcp_action_permission_requires_user_confirmation():
    checker = PermissionChecker(work_root="C:/safe_workspace")
    allowed, reason = checker.check(WriterAction(action_type="mcp_tool"))
    assert allowed is False
    assert "requires user confirmation" in reason
