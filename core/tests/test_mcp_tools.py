from __future__ import annotations

from typing import Any

import pytest

from lamtools_core.tool import ToolCall
from lamtools_core.tool.mcp_tools import (
    clean_mcp_arguments,
    execute_mcp_tool_call,
    format_mcp_result,
    mcp_call_args,
)


class FakeCaller:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        self.calls.append((tool_name, arguments))
        return "ok"


def test_mcp_call_args_supports_generic_and_direct_tool_names():
    generic = ToolCall(
        id="call-mcp",
        name="mcp_tool",
        arguments={"tool_name": "mcp__local__echo", "arguments": {"text": "hi"}},
    )
    direct = ToolCall(id="call-direct", name="mcp__local__echo", arguments={"text": "hi"})

    assert mcp_call_args(generic)[:2] == ("mcp__local__echo", {"text": "hi"})
    assert mcp_call_args(direct)[:2] == ("mcp__local__echo", {"text": "hi"})


@pytest.mark.asyncio
async def test_execute_mcp_tool_call_maps_to_tool_result():
    caller = FakeCaller()

    result = await execute_mcp_tool_call(
        ToolCall(id="call-mcp", name="mcp__local__echo", arguments={"text": "hi"}),
        caller=caller,
    )

    assert result.status == "ok"
    assert result.content == "ok"
    assert caller.calls == [("mcp__local__echo", {"text": "hi"})]


@pytest.mark.asyncio
async def test_execute_mcp_tool_call_reports_missing_registry():
    result = await execute_mcp_tool_call(
        ToolCall(id="call-mcp", name="mcp__local__echo", arguments={}),
        caller=None,
        unavailable_error="MCP not available (no work_root configured)",
    )

    assert result.status == "failed"
    assert result.error == "MCP not available (no work_root configured)"


def test_clean_mcp_arguments_removes_runtime_keys():
    assert clean_mcp_arguments({"text": "hi", "_tool_call_id": "x"}) == {"text": "hi"}


def test_format_mcp_result_formats_text_and_error_content():
    assert format_mcp_result({"content": [{"type": "text", "text": "hello"}]}) == "hello"
    assert format_mcp_result({"isError": True, "content": [{"type": "text", "text": "bad"}]}) == "MCP TOOL ERROR: bad"


class TestMCPSchemas:
    def test_server_config_defaults_and_validation(self):
        from pydantic import ValidationError

        from lamtools_core.mcp.schemas import MCPServerConfig

        config = MCPServerConfig(name="srv", command="python mcp.py")
        assert config.args == []
        assert config.timeout_seconds == 30.0
        assert config.permission == "ask_user"
        assert config.enabled is True
        assert config.transport == "headers"

        with pytest.raises(ValidationError):
            MCPServerConfig(name="srv", command="python mcp.py", transport="udp")
        with pytest.raises(ValidationError):
            MCPServerConfig(name="srv", command="python mcp.py", permission="always")

    def test_tool_schema_shape(self):
        from lamtools_core.mcp.schemas import MCPTool

        tool = MCPTool(server="srv", name="read_file", function_name="mcp__srv__read_file")
        assert tool.description == ""
        assert tool.input_schema == {}
        assert tool.permission == "ask_user"
