"""S5 生态适配器测试：Claude Code / Codex 插件翻译为 LamTools 插件。"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from lamtools_core.plugins.adapters import (
    import_claude_code_plugin,
    import_codex_plugin,
)
from lamtools_core.plugins.registry import PluginRegistry, PluginStateStore


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Claude Code 适配器 ────────────────────────────────────────────

def _make_claude_plugin(tmp_path: Path) -> Path:
    root = tmp_path / "my-cc-plugin"
    cc = root / ".claude-plugin"
    _write_json(cc / "plugin.json", {
        "name": "my-cc-plugin",
        "version": "1.2.0",
        "description": "A Claude Code plugin",
    })
    # hooks.json（CC 形状：事件 + matcher + hooks 数组）
    _write_json(cc / "hooks.json", {
        "hooks": {
            "PreToolUse": [
                {"matcher": "read_file", "hooks": [{"type": "command", "command": "echo blocked"}]}
            ],
            "SessionEnd": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "echo bye"}]}
            ],
            "Notification": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "echo nope"}]}
            ],
        }
    })
    # skills（Claude Skills 事实标准）
    skill = root / "skills" / "demo-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo-skill\ndescription: demo\n---\ncontent", encoding="utf-8")
    # mcp
    _write_json(root / ".mcp.json", {"mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]}}})
    return root


def test_import_claude_code_plugin(tmp_path):
    src = _make_claude_plugin(tmp_path)
    target = tmp_path / "out" / "my-cc-plugin"
    result = import_claude_code_plugin(src, target)
    assert result["name"] == "my-cc-plugin"
    assert result["version"] == "1.2.0"
    # 不支持的事件跳过并警告
    assert any("Notification" in w for w in result["warnings"])

    manifest = json.loads((target / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "my-cc-plugin"
    assert manifest["manifest_version"] == "1"
    assert manifest["skills"] == ["./skills"]
    assert manifest["hooks"] == ["./hooks/hooks.json"]
    assert manifest["mcpServers"] == ["./mcp/mcp.json"]

    # hooks 事件映射：SessionEnd → Stop
    hooks = json.loads((target / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    assert "PreToolUse" in hooks["hooks"]
    assert "Stop" in hooks["hooks"]
    assert "Notification" not in hooks["hooks"]
    # skills / mcp 复制
    assert (target / "skills" / "demo-skill" / "SKILL.md").exists()
    mcp = json.loads((target / "mcp" / "mcp.json").read_text(encoding="utf-8"))
    assert "filesystem" in mcp["mcpServers"]


def test_import_claude_code_plugin_requires_manifest(tmp_path):
    empty = tmp_path / "not-a-plugin"
    empty.mkdir()
    with pytest.raises(ValueError, match="plugin.json"):
        import_claude_code_plugin(empty, tmp_path / "out")


# ── Codex 适配器 ─────────────────────────────────────────────────

def test_import_codex_plugin(tmp_path):
    src = tmp_path / "my-codex-plugin"
    _write_json(src / "plugin.json", {
        "id": "my-codex-plugin",
        "name": "My Codex Plugin",
        "version": "0.3.0",
        "description": "Codex plugin",
        "runtime": "node",
        "executable": "node",
        "args": ["/path/to/index.js"],
        "env": {"TOKEN": "abc"},
    })
    skill = src / "skills" / "codex-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: codex-skill\ndescription: x\n---\nbody", encoding="utf-8")

    target = tmp_path / "out" / "my-codex-plugin"
    result = import_codex_plugin(src, target)
    assert result["name"] == "my-codex-plugin"

    manifest = json.loads((target / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["mcpServers"] == ["./mcp/mcp.json"]
    assert manifest["skills"] == ["./skills"]
    # 外部可执行 → mcpServers 配置（走既有 MCP 通道）
    mcp = json.loads((target / "mcp" / "mcp.json").read_text(encoding="utf-8"))
    server = mcp["mcpServers"]["my-codex-plugin"]
    assert server["command"] == "node"
    assert server["args"] == ["/path/to/index.js"]
    assert server["env"] == {"TOKEN": "abc"}
    assert (target / "skills" / "codex-skill" / "SKILL.md").exists()


def test_import_codex_plugin_missing_executable_warns(tmp_path):
    src = tmp_path / "bare-codex"
    _write_json(src / "plugin.json", {"id": "bare-codex", "version": "0.1.0"})
    result = import_codex_plugin(src, tmp_path / "out" / "bare-codex")
    assert any("executable" in w for w in result["warnings"])
    assert not (tmp_path / "out" / "bare-codex" / "mcp").exists()


# ── 经 plugin.install 全链（cc source） ───────────────────────────

@pytest.fixture()
def adapter_catalog(tmp_path):
    from lamtools_core.plugins.operations import build_plugin_operation_catalog

    roots = tmp_path / "roots"
    roots.mkdir()
    catalog = build_plugin_operation_catalog(
        plugin_registry=PluginRegistry(plugin_roots=[roots], state_store=PluginStateStore(tmp_path / "data" / "plugins.jsonc")),
        plugin_state_store=PluginStateStore(tmp_path / "data" / "plugins.jsonc"),
        hook_registry_factory=lambda: None,
        hook_trust_store=type("T", (), {"untrust": lambda self, h: None})(),
        work_root=tmp_path / "work",
        data_dir=tmp_path / "data",
        install_root=roots,
    )
    return catalog, roots


async def test_plugin_install_cc_source_end_to_end(adapter_catalog, tmp_path):
    catalog, roots = adapter_catalog
    src = _make_claude_plugin(tmp_path)
    result = await catalog.execute("plugin.install", {"source": "cc", "path": str(src)})
    assert result.status == "ok", result.payload
    assert result.payload["name"] == "my-cc-plugin"
    assert (roots / "my-cc-plugin" / "plugin.json").exists()
    assert (roots / "my-cc-plugin" / "hooks" / "hooks.json").exists()
    # warnings 透出（Notification 事件被跳过）
    assert any("Notification" in w for w in result.payload.get("warnings", []))


async def test_plugin_install_codex_source_end_to_end(adapter_catalog, tmp_path):
    catalog, roots = adapter_catalog
    src = tmp_path / "codex-p"
    _write_json(src / "plugin.json", {"id": "codex-p", "version": "1.0.0", "executable": "node", "args": ["x.js"]})
    result = await catalog.execute("plugin.install", {"source": "codex", "path": str(src)})
    assert result.status == "ok", result.payload
    assert (roots / "codex-p" / "mcp" / "mcp.json").exists()
    mcp = json.loads((roots / "codex-p" / "mcp" / "mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["codex-p"]["command"] == "node"
