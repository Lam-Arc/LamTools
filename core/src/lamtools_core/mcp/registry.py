from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lamtools_core.tool import ToolSpec
from lamtools_core.tool.mcp_tools import clean_mcp_arguments, format_mcp_result

from .client import MCPClient, safe_name
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
        plugin_host: Any = None,
    ) -> None:
        self.work_root = Path(work_root)
        self.config_files = tuple(Path(item) for item in config_files or ())
        self.config_loader = config_loader
        self.plugin_host = plugin_host
        self._owners = {}
        self._generations = {}
        self._resource_closers = {}
        if plugin_host is not None:
            from lamtools_core.plugin_system.jsonc import load_jsonc_text
            for manifest in plugin_host.discover():
                for file in self.config_files:
                    if file.resolve().is_relative_to(manifest.root):
                        raw = load_jsonc_text(file)
                        for name in raw.get("mcpServers", raw.get("servers", {})):
                            self._owners[name] = manifest.name
        self._clients: dict[str, MCPClient] = {}
        self._tools_by_name: dict[str, MCPTool] = {}
        # user:“MCP 列表空”+(向调用方保留启动失败原因，区分未配置与连接失败)。
        self.load_errors: dict[str, str] = {}

    @property
    def server_names(self) -> list[str]:
        return list(self._clients.keys())

    @property
    def tools(self) -> list[MCPTool]:
        return list(self._tools_by_name.values())

    def tool_summary(self, server_name: str) -> str:
        tools = [t for t in self._tools_by_name.values() if t.server == server_name]
        if not tools:
            available = self.server_names
            return (
                f"MCP server '{server_name}' not found. "
                f"Available servers: {', '.join(available) if available else 'none'}"
            )
        lines = [f"[MCP:{server_name}] {len(tools)} tools available:"]
        for tool in tools:
            desc = str(tool.description or tool.name).strip()
            lines.append(f"  {tool.function_name} — {desc}")
        return "\n".join(lines)

    async def load(self, *, server_names: set[str] | None = None) -> None:
        configs = self.config_loader(self.work_root) if self.config_loader else load_mcp_server_configs(
            self.work_root,
            config_files=self.config_files,
        )
        # Reload semantics: close any previously started clients first so a
        # hot-reload never leaks MCP server subprocesses / reader tasks
        # (audit 11).
        await self.close()
        for config in configs:
            if server_names is not None and config.name not in server_names and safe_name(config.name) not in server_names:
                continue
            client = MCPClient(config)
            owner = self._owners.get(config.name)
            manager = getattr(self.plugin_host, "backend_manager", None)
            if owner and not self.plugin_host.available(owner):
                continue
            try:
                if owner and manager:
                    async with manager.lease(owner):
                        await client.start()
                        tools = await client.list_tools()
                    self._generations[config.name] = manager.generation.get(owner, 0)
                    from functools import partial
                    close = self._resource_closers.setdefault(owner, partial(self.close_plugin, owner))
                    manager.own_resource(owner, close)
                else:
                    await client.start()
                    tools = await client.list_tools()
            except BaseException as exc:
                # user:“该修修”+(初始化取消也必须回收尚未登记的子进程)。
                await client.close()
                if not isinstance(exc, Exception):
                    raise
                self.load_errors[config.name] = f"{config.command}: {str(exc) or type(exc).__name__}"
                logger.warning("MCP server %s load failed: %s", config.name, exc)
                continue
            self._clients[config.name] = client
            for tool in tools:
                self._tools_by_name[tool.function_name] = tool

    async def close_plugin(self, plugin):
        # user:“该重建就重建”+(插件 MCP 子进程归宿主管，停用先排空再关闭)。
        for name in [key for key, owner in self._owners.items() if owner == plugin]:
            client = self._clients.pop(name, None)
            if client is not None:
                await client.close()
            self._tools_by_name = {key: tool for key, tool in self._tools_by_name.items() if tool.server != name}

    async def close(self) -> None:
        self.load_errors.clear()
        clients = list(self._clients.values())
        self._clients.clear()
        self._tools_by_name.clear()
        for client in clients:
            try:
                await client.close()
            except Exception as exc:
                logger.warning("MCP client close failed: %s", exc)
        manager = getattr(self.plugin_host, "backend_manager", None)
        if manager:
            for owner, close in self._resource_closers.items():
                manager.resources.get(owner, set()).discard(close)

    def tool_specs(self) -> list[ToolSpec]:
        # Compatibility API for SDK consumers; model toolboxes no longer use these schemas.
        from lamtools_core.tool.default_toolbox import DEFAULT_OUTPUT_SCHEMA, strict_tool_schema
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
        if client.config.level_for_tool(tool.name, arguments) == 0:
            return f"MCP TOOL ERROR: operation {tool_name} is hard-blocked"
        clean_args = clean_mcp_arguments(arguments)
        try:
            owner = self._owners.get(tool.server)
            manager = getattr(self.plugin_host, "backend_manager", None)
            if owner and manager:
                if manager.generation.get(owner, 0) != self._generations.get(tool.server):
                    return "MCP TOOL ERROR: plugin was updated; reload this server"
                async with manager.lease(owner):
                    result = await client.call_tool(tool.name, clean_args)
            else:
                result = await client.call_tool(tool.name, clean_args)
        except Exception as exc:
            return f"MCP TOOL ERROR: {tool.server}.{tool.name}: {exc}"
        return format_mcp_result(result)

