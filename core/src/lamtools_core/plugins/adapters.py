"""社区插件适配器（C1 共识：Claude Code + Codex 翻译层）。

原则：标准格式互通，不追求二进制兼容。适配器把社区插件的 manifest/
资产翻译为 LamTools 插件（生成 plugin.json + 复制 hooks/mcp/skills），
翻译产物走既有安装流程。

- Claude Code：hooks.json 与 LamTools 同构（事件+matcher+handler），
  事件名映射（SessionEnd→Stop；Notification/SubagentStop/PreCompact 不支持
  则跳过并记录）；SKILL.md / MCP 直通。
- Codex：插件 = 启动外部可执行暴露 MCP 工具 → 翻译为 mcp.json
  （mcpServers 配置，走既有 MCP 通道，零新架构）。
- opencode（TS 源码）/ OpenClaw（Go 源码）源码型无法进程内运行：
  仅支持资产层（SKILL.md/MCP）手动并入，本适配器不翻译源码。
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

# Claude Code 事件 → LamTools 事件（缺失 = 不支持，跳过并记录）
_CLAUDE_HOOK_EVENT_MAP = {
    "PreToolUse": "PreToolUse",
    "PostToolUse": "PostToolUse",
    "PostToolUseFailure": "PostToolUseFailure",
    "UserPromptSubmit": "UserPromptSubmit",
    "SessionStart": "SessionStart",
    "SessionEnd": "Stop",
    "Stop": "Stop",
    "PermissionRequest": "PermissionRequest",
}
_UNSUPPORTED_CLAUDE_EVENTS = {"Notification", "SubagentStop", "PreCompact"}


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return data


def _find_claude_plugin_root(src_dir: Path) -> Path:
    """Claude Code 插件根：目录本身或 .claude-plugin 子目录。"""
    candidates = [
        src_dir,
        src_dir / ".claude-plugin",
    ]
    for candidate in candidates:
        if (candidate / "plugin.json").exists():
            return candidate
    raise ValueError(f"no Claude Code plugin.json found under {src_dir}")


def import_claude_code_plugin(src_dir: Path, target_dir: Path) -> dict[str, Any]:
    """把 Claude Code 插件翻译为 LamTools 插件并写入 target_dir。

    Returns:
        {"name", "version", "warnings": [str, ...]}
    """
    root = _find_claude_plugin_root(src_dir)
    manifest = _read_json(root / "plugin.json")
    name = str(manifest.get("name") or root.name).strip()
    if not name:
        raise ValueError("Claude Code plugin.json is missing 'name'")
    warnings: list[str] = []

    # 1. manifest 基础字段
    lam_manifest: dict[str, Any] = {
        "name": name,
        "version": str(manifest.get("version") or "0.0.0"),
        "description": str(manifest.get("description") or ""),
        "manifest_version": "1",
    }

    # 2. skills：SKILL.md 目录（Claude Skills 事实标准，直通）
    skill_sources: list[Path] = []
    for candidate in (
        src_dir / "skills",
        root / "skills",
        src_dir / "SKILL.md",
    ):
        if candidate.is_dir():
            skill_sources.append(candidate)
        elif candidate.is_file() and candidate.name == "SKILL.md":
            skill_sources.append(candidate.parent)
    if skill_sources:
        target_skills = target_dir / "skills"
        target_skills.mkdir(parents=True, exist_ok=True)
        seen: set[str] = set()
        for source in skill_sources:
            if (source / "SKILL.md").exists():
                # 单文件形态：skill 目录即 SKILL.md 所在目录
                dest = target_skills / source.name
                if dest.name not in seen:
                    seen.add(dest.name)
                    shutil.copytree(source, dest)
            else:
                # 目录形态：每个子目录一个 SKILL.md
                for skill_dir in sorted(source.glob("*/SKILL.md")):
                    dest = target_skills / skill_dir.parent.name
                    if dest.name in seen:
                        continue
                    seen.add(dest.name)
                    shutil.copytree(skill_dir.parent, dest)
        lam_manifest["skills"] = ["./skills"]

    # 3. hooks：hooks.json 形状同构（事件映射）
    hooks_source: Path | None = None
    for candidate in (root / "hooks.json", src_dir / "hooks.json", root / "hooks" / "hooks.json"):
        if candidate.exists():
            hooks_source = candidate
            break
    if hooks_source is not None:
        try:
            hooks_raw = _read_json(hooks_source)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            warnings.append(f"hooks skipped (unreadable): {exc}")
        else:
            mapped: dict[str, Any] = {"hooks": {}}
            sections = hooks_raw.get("hooks", {}) if isinstance(hooks_raw, dict) else {}
            for event, groups in sections.items() if isinstance(sections, dict) else []:
                if event in _UNSUPPORTED_CLAUDE_EVENTS:
                    warnings.append(f"hook event '{event}' is not supported and was skipped")
                    continue
                mapped_event = _CLAUDE_HOOK_EVENT_MAP.get(event, event)
                mapped["hooks"].setdefault(mapped_event, []).extend(
                    groups if isinstance(groups, list) else []
                )
            target_hooks = target_dir / "hooks"
            target_hooks.mkdir(parents=True, exist_ok=True)
            (target_hooks / "hooks.json").write_text(
                json.dumps(mapped, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            lam_manifest["hooks"] = ["./hooks/hooks.json"]

    # 4. mcp：.mcp.json / mcp.json 直通（mcpServers 同形状）
    mcp_source: Path | None = None
    for candidate in (root / ".mcp.json", src_dir / ".mcp.json", root / "mcp.json"):
        if candidate.exists():
            mcp_source = candidate
            break
    if mcp_source is not None:
        target_mcp = target_dir / "mcp"
        target_mcp.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(mcp_source, target_mcp / "mcp.json")
        lam_manifest["mcpServers"] = ["./mcp/mcp.json"]

    # 5. 写 LamTools manifest
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "plugin.json").write_text(
        json.dumps(lam_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"name": name, "version": lam_manifest["version"], "warnings": warnings}


def import_codex_plugin(src_dir: Path, target_dir: Path) -> dict[str, Any]:
    """把 Codex CLI 插件翻译为 LamTools 插件。

    Codex 插件 = 启动外部可执行暴露 MCP 工具 → 翻译为 mcp.json
    （mcpServers 走既有 MCP 通道）；skills（SKILL.md）直通复制。
    """
    manifest_path = src_dir / "plugin.json"
    if not manifest_path.exists():
        raise ValueError(f"no Codex plugin.json found under {src_dir}")
    manifest = _read_json(manifest_path)
    name = str(manifest.get("id") or manifest.get("name") or src_dir.name).strip()
    if not name:
        raise ValueError("Codex plugin.json is missing 'id'")
    warnings: list[str] = []

    lam_manifest: dict[str, Any] = {
        "name": name,
        "version": str(manifest.get("version") or "0.0.0"),
        "description": str(manifest.get("description") or ""),
        "manifest_version": "1",
    }

    # 1. 外部可执行 → mcpServers（走既有 MCP 通道）
    executable = str(manifest.get("executable") or "").strip()
    if not executable:
        warnings.append("plugin has no 'executable' — no MCP server was generated")
    else:
        server_config: dict[str, Any] = {
            "command": executable,
            "args": [str(item) for item in (manifest.get("args") or []) if isinstance(item, str)],
        }
        env = manifest.get("env")
        if isinstance(env, dict):
            server_config["env"] = {str(k): str(v) for k, v in env.items() if isinstance(v, str)}
        target_mcp = target_dir / "mcp"
        target_mcp.mkdir(parents=True, exist_ok=True)
        (target_mcp / "mcp.json").write_text(
            json.dumps({"mcpServers": {name: server_config}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        lam_manifest["mcpServers"] = ["./mcp/mcp.json"]

    # 2. skills（SKILL.md 直通）
    skill_sources: list[Path] = []
    for candidate in (src_dir / "skills", src_dir / ".codex" / "skills"):
        if candidate.is_dir() and any(candidate.glob("*/SKILL.md")):
            skill_sources.append(candidate)
    if skill_sources:
        target_skills = target_dir / "skills"
        target_skills.mkdir(parents=True, exist_ok=True)
        seen: set[str] = set()
        for source in skill_sources:
            for skill_dir in sorted(source.glob("*/SKILL.md")):
                dest = target_skills / skill_dir.parent.name
                if dest.name in seen:
                    continue
                seen.add(dest.name)
                shutil.copytree(skill_dir.parent, dest)
        lam_manifest["skills"] = ["./skills"]

    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "plugin.json").write_text(
        json.dumps(lam_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"name": name, "version": lam_manifest["version"], "warnings": warnings}


ADAPTERS = {
    "cc": import_claude_code_plugin,
    "claude-code": import_claude_code_plugin,
    "codex": import_codex_plugin,
}
