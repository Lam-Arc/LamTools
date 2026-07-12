from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lamtools_core.tool import ToolSpec
from lamtools_core.tool.default_toolbox import DEFAULT_OUTPUT_SCHEMA, strict_tool_schema
from lamtools_core.tool.mcp_tools import clean_mcp_arguments, format_mcp_result

from .client import MCPClient
from .config import load_mcp_server_configs
from .schemas import MCPServerConfig, MCPTool

logger = logging.getLogger(__name__)

ConfigLoader = Callable[[str | Path], list[MCPServerConfig]]


class MCPToolRegistry:
    def __init__(
        self,
        work_root: str | Path,
        *,
        config_files: list[Path | str] | tuple[Path | str, ...] | None = None,
        config_loader: ConfigLoader | None = None,
    ) -> None:
        self.work_root = Path(work_root)
        self.config_files = tuple(Path(item) for item in config_files or ())
        self.config_loader = config_loader
        self._clients: dict[str, MCPClient] = {}
        self._tools_by_name: dict[str, MCPTool] = {}

    @property
    def tools(self) -> list[MCPTool]:
        return list(self._tools_by_name.values())

    async def load(self) -> None:
        configs = self.config_loader(self.work_root) if self.config_loader else load_mcp_server_configs(
            self.work_root,
            config_files=self.config_files,
        )
        for config in configs:
            client = MCPClient(config)
            try:
                await client.start()
                tools = await client.list_tools()
            except Exception as exc:
                logger.warning("MCP server %s load failed: %s", config.name, exc)
                await client.close()
                continue
            self._clients[config.name] = client
            for tool in tools:
                self._tools_by_name[tool.function_name] = tool

    async def close(self) -> None:
        clients = list(self._clients.values())
        self._clients.clear()
        self._tools_by_name.clear()
        for client in clients:
            try:
                await client.close()
            except Exception as exc:
                logger.warning("MCP client close failed: %s", exc)

    def tool_specs(self) -> list[ToolSpec]:
        specs: list[ToolSpec] = []
        for tool in self.tools:
            if tool.permission == "hard_block":
                continue
            schema = tool.input_schema or {"type": "object", "properties": {}}
            if schema.get("type") != "object":
                schema = {"type": "object", "properties": {}}
            specs.append(
                ToolSpec(
                    name=tool.function_name,
                    description=f"[MCP:{tool.server}] {tool.description or tool.name}",
                    input_schema=strict_tool_schema(schema),
                    output_schema=DEFAULT_OUTPUT_SCHEMA,
                    permission=tool.permission,
                    metadata={"category": "mcp", "display": {"card": "tool", "default_collapsed": True}},
                )
            )
        return specs

    def tool_definitions(self) -> list[dict[str, Any]]:
        definitions: list[dict[str, Any]] = []
        for spec in self.tool_specs():
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "strict": True,
                        "parameters": spec.input_schema,
                    },
                }
            )
        return definitions

    def resolve(self, tool_name: str) -> MCPTool | None:
        return self._tools_by_name.get(tool_name)

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        tool = self.resolve(tool_name)
        if tool is None:
            return f"MCP TOOL ERROR: unknown tool {tool_name}"
        if tool.permission == "hard_block":
            return f"MCP TOOL ERROR: tool {tool_name} is hard-blocked"
        client = self._clients.get(tool.server)
        if client is None:
            return f"MCP TOOL ERROR: server {tool.server} is not connected"
        clean_args = clean_mcp_arguments(arguments)
        try:
            result = await client.call_tool(tool.name, clean_args)
        except Exception as exc:
            return f"MCP TOOL ERROR: {tool.server}.{tool.name}: {exc}"
        return format_mcp_result(result)

