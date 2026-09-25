from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from .schemas import MCPServerConfig
from lamtools_core.plugins._jsonc import load_jsonc_text

_log = logging.getLogger(__name__)


def load_mcp_server_configs(
    work_root: str | Path,
    *,
    config_files: list[Path | str] | tuple[Path | str, ...] | None = None,
    env_var: str = "LAMTOOLS_MCP_CONFIG",
    default_paths: list[Path | str] | tuple[Path | str, ...] | None = None,
    include_builtin_playwright: bool = False,
    builtin_playwright_env_var: str = "LAMTOOLS_BUILTIN_PLAYWRIGHT_MCP",
    builtin_playwright_cli: Path | str | None = None,
    builtin_playwright_output_dir: Path | str | None = None,
) -> list[MCPServerConfig]:
    servers: dict[str, Any] = {}
    for path in _config_paths(work_root, config_files=config_files, env_var=env_var, default_paths=default_paths):
        if not path.exists():
            continue
        try:
            data = load_jsonc_text(path)
        except (OSError, ValueError):
            # A corrupt or empty mcp.json must never take the whole app down.
            _log.warning("Skipping unreadable MCP config: %s", path)
            continue
        raw_servers = data.get("mcpServers", data.get("servers", data)) if isinstance(data, dict) else {}
        if isinstance(raw_servers, dict):
            servers.update(raw_servers)

    configs: list[MCPServerConfig] = []
    for name, raw in servers.items():
        if not isinstance(raw, dict):
            continue
        command = str(raw.get("command", "")).strip()
        if not command:
            continue
        configs.append(
            MCPServerConfig(
                name=str(raw.get("name") or name),
                command=command,
                args=[str(arg) for arg in raw.get("args", [])],
                env={str(key): str(value) for key, value in (raw.get("env", {}) or {}).items()},
                timeout_seconds=float(raw.get("timeout_seconds", raw.get("timeout", 30)) or 30),
                permission=raw.get("permission", "ask_user"),
                enabled=bool(raw.get("enabled", True)),
                transport=raw.get("transport", "headers"),
            )
        )
    configs = [config for config in configs if config.enabled]
    if include_builtin_playwright:
        configs.extend(
            _builtin_playwright_mcp_configs(
                work_root,
                existing_names={config.name for config in configs},
                env_var=builtin_playwright_env_var,
                cli_path=Path(builtin_playwright_cli) if builtin_playwright_cli else None,
                output_dir=Path(builtin_playwright_output_dir) if builtin_playwright_output_dir else None,
            )
        )
    return configs


def _config_paths(
    work_root: str | Path,
    *,
    config_files: list[Path | str] | tuple[Path | str, ...] | None,
    env_var: str,
    default_paths: list[Path | str] | tuple[Path | str, ...] | None,
) -> list[Path]:
    """MCP 配置来源：用户配置 + 显式指定的文件。

    2026-09-25 审计 P1：不再自动读取工作区里的 ``.lamtools/mcp.json`` /
    ``.mcp.json`` / ``mcp.json``——它们可以声明任意 ``command``，而 MCP 服务
    在加载时就会启动进程，等于"打开一个仓库即可执行任意命令"。调用方仍可
    通过 ``config_files``（插件清单声明的文件）或 ``default_paths`` 显式加入
    来源。
    """
    from lamtools_core.config.root import core_config_file

    paths: list[Path] = []
    # 1. Unified config directory (user-modifiable after packaging)
    paths.append(core_config_file("mcp.json"))
    explicit = os.environ.get(env_var, "").strip()
    if explicit:
        paths.append(Path(explicit))
    del work_root  # 工作区不再参与默认配置发现（见 docstring）
    if default_paths is not None:
        paths.extend(Path(item) for item in default_paths)
    paths.extend(Path(item) for item in config_files or ())
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def _builtin_playwright_mcp_configs(
    work_root: str | Path,
    *,
    existing_names: set[str],
    env_var: str,
    cli_path: Path | None,
    output_dir: Path | None,
) -> list[MCPServerConfig]:
    enabled = os.environ.get(env_var, "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return []
    if "playwright" in existing_names:
        return []

    command, args = _playwright_mcp_command(cli_path=cli_path)
    if not command:
        return []

    root = Path(work_root).resolve()
    resolved_output_dir = output_dir or root / ".lamtools-artifacts" / "mcp" / "playwright"
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    args.extend([
        "--headless",
        "--browser",
        "msedge",
        "--isolated",
        "--output-dir",
        str(resolved_output_dir),
        "--console-level",
        "error",
        "--timeout-action",
        "10000",
        "--timeout-navigation",
        "60000",
    ])

    return [
        MCPServerConfig(
            name="playwright",
            command=command,
            args=args,
            timeout_seconds=60,
            permission="ask_user",
            enabled=True,
            builtin=True,
            transport="json_lines",
        )
    ]


def _playwright_mcp_command(*, cli_path: Path | None = None) -> tuple[str, list[str]]:
    node = shutil.which("node")
    if cli_path is not None and cli_path.exists():
        return (node or "node"), [str(cli_path)]

    npx = shutil.which("npx")
    if npx:
        return npx, ["-y", "@playwright/mcp@latest"]
    return "", []
