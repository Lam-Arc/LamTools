from __future__ import annotations

from lamtools_core.mcp import client as _core_client
from lamtools_core.mcp.client import MCPClient, MCPError, encode_mcp_tool_name, read_message

subprocess = _core_client.subprocess
sys = _core_client.sys
_subprocess_start_kwargs = _core_client.subprocess_start_kwargs
_read_message = read_message
encode_writer_tool_name = encode_mcp_tool_name

__all__ = [
    "MCPClient",
    "MCPError",
    "_read_message",
    "_subprocess_start_kwargs",
    "encode_writer_tool_name",
]
