from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugins import PluginRegistry, PluginStateStore


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_registry_discovers_plugin_resources(tmp_path: Path):
    plugin = tmp_path / "plugins" / "repo-policy"
    write_json(plugin / "plugin.json", {
        "name": "repo-policy",
        "version": "0.1.0",
        "description": "Repo policy",
        "skills": ["./skills"],
        "hooks": ["./hooks/hooks.json"],
        "mcpServers": "./mcp/mcp.json",
        "agents": ["./agents"],
        "permissions": {"commands": "ask_user"},
    })

    registry = PluginRegistry(plugin_roots=[tmp_path / "plugins"])
    plugins = registry.discover()

    assert [item.name for item in plugins] == ["repo-policy"]
    assert plugins[0].version == "0.1.0"
    assert plugins[0].root == plugin.resolve()
    assert plugins[0].hook_files == [plugin.resolve() / "hooks" / "hooks.json"]
    assert plugins[0].skill_roots == [plugin.resolve() / "skills"]
    assert plugins[0].mcp_files == [plugin.resolve() / "mcp" / "mcp.json"]
    assert plugins[0].agent_roots == [plugin.resolve() / "agents"]


def test_registry_uses_default_hook_and_mcp_paths(tmp_path: Path):
    plugin = tmp_path / "plugins" / "defaulted"
    write_json(plugin / "plugin.json", {"name": "defaulted", "version": "1.0.0"})
    write_json(plugin / "hooks" / "hooks.json", {"hooks": {}})
    write_json(plugin / ".mcp.json", {"mcpServers": {}})

    registry = PluginRegistry(plugin_roots=[tmp_path / "plugins"])
    item = registry.discover()[0]

    assert item.hook_files == [plugin.resolve() / "hooks" / "hooks.json"]
    assert item.mcp_files == [plugin.resolve() / ".mcp.json"]


def test_registry_rejects_paths_outside_plugin_root(tmp_path: Path):
    plugin = tmp_path / "plugins" / "bad"
    write_json(plugin / "plugin.json", {
        "name": "bad",
        "version": "1.0.0",
        "hooks": ["./../outside.json"],
    })

    registry = PluginRegistry(plugin_roots=[tmp_path / "plugins"])

    with pytest.raises(ValueError, match="outside plugin root"):
        registry.discover()


def test_plugin_state_store_controls_enabled_flag(tmp_path: Path):
    state = PluginStateStore(tmp_path / "plugin-state.json")
    state.set_enabled("repo-policy", False)
    state.set_enabled("other", True)

    registry = PluginRegistry(
        plugin_roots=[tmp_path / "plugins"],
        state_store=state,
    )
    plugin = tmp_path / "plugins" / "repo-policy"
    write_json(plugin / "plugin.json", {"name": "repo-policy", "version": "0.1.0"})

    discovered = registry.discover()[0]

    assert discovered.enabled is False
    assert state.is_enabled("other") is True
