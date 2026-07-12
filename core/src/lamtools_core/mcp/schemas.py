from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


MCPPermission = Literal["auto_allow", "ask_user", "hard_block"]
MCPTransport = Literal["headers", "json_lines"]


class MCPServerConfig(BaseModel):
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = 30.0
    permission: MCPPermission = "ask_user"
    enabled: bool = True
    builtin: bool = False
    transport: MCPTransport = "headers"


class MCPTool(BaseModel):
    server: str
    name: str
    function_name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    permission: MCPPermission = "ask_user"
