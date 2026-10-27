"""user:“通过 command 运行”+(命令行和代理命令共用 MCP 服务，不另写协议客户端)。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def register_mcp(sub) -> None:
    parser = sub.add_parser("mcp", help="Inspect MCP tools or execute an MCP command")
    parser.add_argument("action", choices=["servers", "tools", "schema", "call"])
    parser.add_argument("--tool", default="")
    parser.add_argument("--server", default="")
    parser.add_argument("--arguments", default="{}")
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--config", type=Path, action="append", default=[])
    parser.set_defaults(func=cmd_mcp)


async def cmd_mcp(args: argparse.Namespace) -> int:
    from .config import _default_work_root, _default_cli_plugin_state_path
    from lamtools_core.app.base_agent import default_core_agent_plugin_roots
    from lamtools_core.plugin_system import PluginHost, assemble_capabilities
    from lamtools_core.mcp import MCPToolRegistry
    from lamtools_core.mcp.command_service import MCPCommandService
    import shlex

    root = args.work_root or _default_work_root()
    host = PluginHost(roots=default_core_agent_plugin_roots(root), state_path=_default_cli_plugin_state_path())
    assembly = assemble_capabilities(host.discover())
    service = MCPCommandService(MCPToolRegistry(root, config_files=[*assembly.mcp_files, *args.config]))
    try:
        if args.action == "call":
            command = "core mcp call --tool " + shlex.quote(args.tool) + " --arguments " + shlex.quote(args.arguments)
            result = await service.execute_command(command)
            print(result, flush=True)
        else:
            print(json.dumps(await service.inspect(args.action, args.server, args.tool), ensure_ascii=False), flush=True)
        return 0
    finally:
        await service.close()
