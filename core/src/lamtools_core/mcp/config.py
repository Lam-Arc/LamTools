from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .schemas import MCPServerConfig


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
        data = json.loads(path.read_text(encoding="utf-8-sig"))
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
    from lamtools_core.config.root import core_config_file

    paths: list[Path] = []
    # 1. Unified config directory (user-modifiable after packaging)
    paths.append(core_config_file("mcp.json"))
    explicit = os.environ.get(env_var, "").strip()
    if explicit:
        paths.append(Path(explicit))
    root = Path(work_root)
    if default_paths is None:
        paths.extend([root / ".lamtools" / "mcp.json", root / ".mcp.json", root / "mcp.json"])
    else:
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
