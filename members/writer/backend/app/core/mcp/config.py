from __future__ import annotations

from pathlib import Path

from lamtools_core.mcp.config import load_mcp_server_configs as load_core_mcp_server_configs


def load_mcp_server_configs(work_root: str):
    root = Path(work_root)
    repo_member_root = Path(__file__).resolve().parents[4]
    local_playwright_cli = repo_member_root / "frontend" / "node_modules" / "@playwright" / "mcp" / "cli.js"
    return load_core_mcp_server_configs(
        work_root,
        env_var="LAMWRITER_MCP_CONFIG",
        default_paths=(root / ".lamwriter" / "mcp.json", root / "mcp.json"),
        include_builtin_playwright=True,
        builtin_playwright_env_var="LAMWRITER_BUILTIN_PLAYWRIGHT_MCP",
        builtin_playwright_cli=local_playwright_cli,
        builtin_playwright_output_dir=root.resolve() / ".writer-artifacts" / "mcp" / "playwright",
    )
