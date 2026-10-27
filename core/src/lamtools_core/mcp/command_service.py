"""user:“把 MCP 从 toolbox 里面拿出去，通过 command 运行”+(协议与连接由命令服务独立管理)。"""
from __future__ import annotations

import asyncio
import json
import shlex
from typing import Any


def parse_mcp_command(command: str) -> tuple[str, dict[str, Any]] | None:
    """Parse our argv directly; MCP arguments never pass through a shell."""
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        if command.strip().startswith("core mcp"):
            raise
        return None
    if not argv:
        return None
    executable = argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    if executable in {"python", "python3", "python.exe", "py", "py.exe"}:
        rest = argv[1:]
        if executable in {"py", "py.exe"} and rest and rest[0].startswith("-3"):
            rest = rest[1:]
        if rest[:3] != ["-m", "lamtools_core.cli", "mcp"]:
            return None
        argv = ["core", *rest[2:]]
    elif executable in {"core", "core.exe"} and argv[1:2] == ["mcp"]:
        argv = ["core", *argv[1:]]
    else:
        return None
    if len(argv) != 7 or argv[:3] != ["core", "mcp", "call"] or argv[3] != "--tool" or argv[5] != "--arguments":
        raise ValueError("Use: core mcp call --tool mcp__SERVER__TOOL --arguments '<JSON object>'")
    arguments = json.loads(argv[6])
    if not isinstance(arguments, dict):
        raise ValueError("MCP arguments must be a JSON object")
    return argv[4], arguments


class MCPCommandService:
    def __init__(self, registry: Any, *, loaded: bool = False, allowed_tools: frozenset[str] | None = None) -> None:
        self.registry = registry
        self.config_files = getattr(registry, "config_files", ())
        self._loaded = loaded
        self._lock = asyncio.Lock()
        self.allowed_tools = allowed_tools

    async def _ensure_loaded(self) -> None:
        async with self._lock:
            if not self._loaded:
                servers = {name.split("__", 2)[1] for name in self.allowed_tools or () if name.startswith("mcp__") and len(name.split("__", 2)) == 3}
                await self.registry.load(server_names=servers if self.allowed_tools is not None else None)
                self._loaded = True

    def check_command(self, command: str) -> tuple[str, dict[str, Any]] | None:
        parsed = parse_mcp_command(command)
        if self.allowed_tools is not None:
            if parsed is None or parsed[0] not in self.allowed_tools:
                raise ValueError("This profile only permits its declared MCP commands")
        return parsed

    def check_tool_allowed(self, tool_name: str) -> None:
        """Enforce the run profile's MCP tool whitelist for direct mcp action=run calls."""
        if self.allowed_tools is not None and tool_name not in self.allowed_tools:
            raise ValueError("This profile only permits its declared MCP tools")

    def level_for_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> int:
        """Read the installed declaration without launching any MCP process."""
        from .config import load_mcp_server_configs
        from .client import encode_mcp_tool_name, safe_name

        name = str(tool_name or "")
        args = arguments if isinstance(arguments, dict) else {}
        loader = getattr(self.registry, "config_loader", None)
        work_root = getattr(self.registry, "work_root", ".")
        configs = loader(work_root) if loader else load_mcp_server_configs(work_root, config_files=self.config_files)
        parts = name.split("__", 2)
        for config in configs:
            if len(parts) != 3 or safe_name(config.name) != parts[1]:
                continue
            original_name = next((key for key in config.tool_levels if encode_mcp_tool_name(config.name, key) == name), parts[2])
            return config.level_for_tool(original_name, args)
        tool = self.registry.resolve(name)
        return getattr(tool, "level", 3) if tool is not None else 3

    def level_for_command(self, command: str) -> int:
        parsed = parse_mcp_command(command)
        if parsed is None:
            return 3
        return self.level_for_tool(parsed[0], parsed[1])

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute one MCP tool after the same whitelist/level checks as the command path."""
        name = str(tool_name or "").strip()
        if not name:
            raise ValueError("MCP tool_name is required")
        args = arguments if isinstance(arguments, dict) else {}
        self.check_tool_allowed(name)
        if self.level_for_tool(name, args) == 0:
            raise ValueError(f"MCP operation is hard-blocked: {name}")
        await self._ensure_loaded()
        tool = self.registry.resolve(name)
        if tool is None:
            raise ValueError(f"Unknown MCP tool: {name}")
        if tool.permission == "hard_block":
            raise ValueError(f"MCP tool is hard-blocked: {name}")
        result = await self.registry.call(name, args)
        if result.startswith("MCP TOOL ERROR:"):
            raise RuntimeError(result)
        return result

    async def execute_command(self, command: str) -> str:
        parsed = self.check_command(command)
        if parsed is None:
            raise ValueError("Not an MCP command")
        tool_name, arguments = parsed
        return await self.execute_tool(tool_name, arguments)

    async def inspect(self, action: str = "servers", server_name: str = "", tool_name: str = "") -> dict[str, Any]:
        if action not in {"servers", "tools", "schema"}:
            raise ValueError("MCP is query-only here; run one tool with action=run, tool_name, and arguments")
        await self._ensure_loaded()
        tools = [tool for tool in self.registry.tools if tool.permission != "hard_block"
                 and (getattr(tool, "level", 3) != 0 or any(value > 0 for value in getattr(tool, "action_levels", {}).values()))
                 and (self.allowed_tools is None or tool.function_name in self.allowed_tools)]
        if action == "servers":
            return {"servers": sorted({t.server for t in tools})}
        if action == "schema":
            tool = next((t for t in tools if t.function_name == tool_name), None)
            if tool is None:
                raise ValueError(f"Unknown MCP tool: {tool_name}")
            return {"tool_name": tool.function_name, "description": tool.description,
                    "input_schema": tool.input_schema,
                    "level": getattr(tool, "level", 3),
                    "action_levels": getattr(tool, "action_levels", {}),
                    "run": {"action": "run", "tool_name": tool.function_name, "arguments": {}},
                    "command": f"core mcp call --tool {tool.function_name} --arguments '<JSON object>'"}
        return {"tools": [{"tool_name": t.function_name, "description": t.description}
                          for t in tools if not server_name or t.server == server_name]}

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Hook integration uses the same lazily owned protocol connection."""
        await self._ensure_loaded()
        return await self.registry.call(tool_name, arguments)

    async def close(self) -> None:
        await self.registry.close()
        self._loaded = False
