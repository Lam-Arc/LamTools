from __future__ import annotations

from lamtools_core.mcp.registry import MCPToolRegistry as CoreMCPToolRegistry

from .config import load_mcp_server_configs


class MCPToolRegistry(CoreMCPToolRegistry):
    def __init__(self, work_root: str):
        super().__init__(work_root, config_loader=load_mcp_server_configs)
