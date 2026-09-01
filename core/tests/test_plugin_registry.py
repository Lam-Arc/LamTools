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


def test_registry_discovers_composer_commands(tmp_path: Path):
    plugin = tmp_path / "plugins" / "pet"
    write_json(plugin / "plugin.json", {
        "name": "pet",
        "commands": [{
            "name": "pet",
            "title": "桌宠",
            "description": "显示桌宠",
            "icon": "paw-print",
            "effect": {"type": "desktop_plugin", "action": "show"},
        }],
    })

    item = PluginRegistry(plugin_roots=[tmp_path / "plugins"]).discover()[0]

    assert len(item.commands) == 1
    assert item.commands[0].name == "pet"
    assert item.commands[0].effect == {"type": "desktop_plugin", "action": "show"}


def test_registry_uses_default_hook_and_mcp_paths(tmp_path: Path):
    plugin = tmp_path / "plugins" / "defaulted"
    write_json(plugin / "plugin.json", {"name": "defaulted", "version": "1.0.0"})
    write_json(plugin / "hooks" / "hooks.json", {"hooks": {}})
    write_json(plugin / ".mcp.json", {"mcpServers": {}})

    registry = PluginRegistry(plugin_roots=[tmp_path / "plugins"])
    item = registry.discover()[0]

    assert item.hook_files == [plugin.resolve() / "hooks" / "hooks.json"]
    assert item.mcp_files == [plugin.resolve() / ".mcp.json"]


def test_registry_skips_plugin_with_paths_outside_plugin_root(tmp_path: Path):
    """A plugin whose manifest escapes its root is skipped — one corrupt
    plugin must never hide every other plugin (audit 11)."""
    write_json(tmp_path / "plugins" / "bad" / "plugin.json", {
        "name": "bad",
        "version": "1.0.0",
        "hooks": ["./../outside.json"],
    })
    write_json(tmp_path / "plugins" / "good" / "plugin.json", {"name": "good", "version": "1.0.0"})

    registry = PluginRegistry(plugin_roots=[tmp_path / "plugins"])

    names = [item.name for item in registry.discover()]
    assert names == ["good"]


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


def test_registry_discovers_desktop_entry(tmp_path: Path):
    plugin = tmp_path / "plugins" / "pet"
    write_json(plugin / "plugin.json", {
        "name": "pet",
        "desktop": {
            "entry": "./desktop/index.html",
            "title": "Pet window",
            "window": {"collapsedWidth": 176},
        },
    })
    (plugin / "desktop" / "index.html").parent.mkdir(parents=True, exist_ok=True)
    (plugin / "desktop" / "index.html").write_text("<!doctype html>", encoding="utf-8")

    item = PluginRegistry(plugin_roots=[tmp_path / "plugins"]).discover()[0]

    assert item.desktop_entry == (plugin / "desktop" / "index.html").resolve()
    assert item.desktop_title == "Pet window"
    assert item.desktop_window == {"collapsedWidth": 176}
    assert item.desktop_card_width == 376
    assert item.desktop_card_height == 360
    assert item.desktop_file_drop is False


def test_desktop_plugin_parses_card_dimensions(tmp_path: Path):
    plugin = tmp_path / "plugins" / "pet"
    write_json(plugin / "plugin.json", {
        "name": "pet",
        "desktop": {
            "entry": "./desktop/index.html",
            "window": {"cardWidth": 412, "cardHeight": 364},
        },
    })
    (plugin / "desktop" / "index.html").parent.mkdir(parents=True, exist_ok=True)
    (plugin / "desktop" / "index.html").write_text("<!doctype html>", encoding="utf-8")

    item = PluginRegistry(plugin_roots=[tmp_path / "plugins"]).discover()[0]

    assert item.desktop_card_width == 412
    assert item.desktop_card_height == 364


def test_desktop_plugin_parses_file_drop_capability(tmp_path: Path):
    plugin = tmp_path / "plugins" / "pet"
    write_json(plugin / "plugin.json", {
        "name": "pet",
        "desktop": {
            "entry": "./desktop/index.html",
            "fileDrop": True,
        },
    })
    (plugin / "desktop" / "index.html").parent.mkdir(parents=True, exist_ok=True)
    (plugin / "desktop" / "index.html").write_text("<!doctype html>", encoding="utf-8")

    item = PluginRegistry(plugin_roots=[tmp_path / "plugins"]).discover()[0]

    assert item.desktop_file_drop is True


def test_desktop_plugin_rejects_invalid_file_drop_capability(tmp_path: Path):
    plugin = tmp_path / "plugins" / "pet"
    write_json(plugin / "plugin.json", {
        "name": "pet",
        "desktop": {
            "entry": "./desktop/index.html",
            "fileDrop": "yes",
        },
    })
    (plugin / "desktop" / "index.html").parent.mkdir(parents=True, exist_ok=True)
    (plugin / "desktop" / "index.html").write_text("<!doctype html>", encoding="utf-8")

    assert PluginRegistry(plugin_roots=[tmp_path / "plugins"]).discover() == []


def test_desktop_plugin_rejects_invalid_card_dimensions(tmp_path: Path):
    plugin = tmp_path / "plugins" / "pet"
    write_json(plugin / "plugin.json", {
        "name": "pet",
        "desktop": {
            "entry": "./desktop/index.html",
            "window": {"cardWidth": 0},
        },
    })
    (plugin / "desktop" / "index.html").parent.mkdir(parents=True, exist_ok=True)
    (plugin / "desktop" / "index.html").write_text("<!doctype html>", encoding="utf-8")

    assert PluginRegistry(plugin_roots=[tmp_path / "plugins"]).discover() == []


@pytest.mark.parametrize("entry", ["./desktop/index.js", "./../outside.html", "./desktop/missing.html"])
def test_registry_rejects_invalid_desktop_entry(tmp_path: Path, entry: str):
    plugin = tmp_path / "plugins" / "bad-pet"
    write_json(plugin / "plugin.json", {
        "name": "bad-pet",
        "desktop": {"entry": entry},
    })
    (plugin / "desktop").mkdir(parents=True, exist_ok=True)
    (plugin / "desktop" / "index.js").write_text("", encoding="utf-8")
    (tmp_path / "plugins" / "outside.html").write_text("", encoding="utf-8")

    registry = PluginRegistry(plugin_roots=[tmp_path / "plugins"])

    assert registry.discover() == []
    assert registry.discover_errors[0]["name"] == "bad-pet"
