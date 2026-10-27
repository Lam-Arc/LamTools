from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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
    # user:“他家的 MCP 可以提前声明等级吗”+(默认三级，安装配置可细化到工具及 action)。
    level: int = Field(default=3, ge=0, strict=True)
    tool_levels: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tool_levels")
    @classmethod
    def validate_levels(cls, definitions):
        from lamtools_core.tool.operation_levels import valid_level
        for definition in definitions.values():
            if isinstance(definition, dict):
                actions = definition.get("actions", {})
                if not valid_level(definition.get("default", 3)) or not isinstance(actions, dict) or any(not valid_level(value) for value in actions.values()):
                    raise ValueError("MCP tool level must be a non-negative integer")
            elif not valid_level(definition):
                raise ValueError("MCP tool level must be a non-negative integer")
        return definitions

    def level_for_tool(self, name: str, arguments: dict[str, Any] | None = None) -> int:
        if self.permission == "hard_block":
            return 0
        value = self.tool_levels.get(name, self.level)
        if isinstance(value, dict):
            return value.get("actions", {}).get(str((arguments or {}).get("action") or ""), value.get("default", self.level))
        return value


class MCPTool(BaseModel):
    server: str
    name: str
    function_name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    permission: MCPPermission = "ask_user"
    level: int = Field(default=3, ge=0, strict=True)
    action_levels: dict[str, int] = Field(default_factory=dict)
