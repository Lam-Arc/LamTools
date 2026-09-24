from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugins import PluginRegistry, PluginStateStore
from lamtools_core.plugins import operations


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

def _ui_mode_plugin(tmp_path: Path, modes: list[dict]) -> Path:
    plugin = tmp_path / "plugins" / "study"
    (plugin / "ui").mkdir(parents=True, exist_ok=True)
    (plugin / "ui" / "index.ts").write_text("export default {}", encoding="utf-8")
    write_json(plugin / "plugin.json", {
        "name": "study",
        "version": "1.0.0",
        "description": "Study",
        "ui": {"modes": modes},
    })
    return plugin


def test_ui_mode_capabilities_separate_absent_from_empty(tmp_path: Path):
    """A mode declares host capabilities; absence must stay distinct from empty.

    The shared UI keeps every surface available when a host makes no claim, so
    a host that cannot serve the Study Note vault declares an empty list
    instead of being silently treated as capable.
    """
    _ui_mode_plugin(tmp_path, [
        {"id": "study", "title": "Study", "entry": "./ui/index.ts", "capabilities": ["notes"]},
        {"id": "plain", "title": "Plain", "entry": "./ui/index.ts"},
    ])
    modes = {
        mode.id: mode
        for mode in PluginRegistry(plugin_roots=[tmp_path / "plugins"]).discover()[0].ui.modes
    }
    assert modes["study"].capabilities == ["notes"]
    assert modes["plain"].capabilities is None

    _ui_mode_plugin(tmp_path, [
        {"id": "study", "title": "Study", "entry": "./ui/index.ts", "capabilities": []},
    ])
    modes = {
        mode.id: mode
        for mode in PluginRegistry(plugin_roots=[tmp_path / "plugins"]).discover()[0].ui.modes
    }
    assert modes["study"].capabilities == []


def test_ui_mode_capabilities_reject_invalid_declarations(tmp_path: Path):
    """An invalid declaration is refused at discovery instead of half-applied."""
    for invalid in (["notes", "notes"], [""], "notes", [7]):
        _ui_mode_plugin(tmp_path, [
            {"id": "study", "title": "Study", "entry": "./ui/index.ts", "capabilities": invalid},
        ])
        assert PluginRegistry(plugin_roots=[tmp_path / "plugins"]).discover() == []


def test_bundled_study_mode_declares_the_note_vault_capability():
    bundled = Path(__file__).resolve().parents[1] / "src" / "lamtools_core" / "plugins" / "bundled"
    modes = {
        f"{manifest.name}:{mode.id}": mode
        for manifest in PluginRegistry(plugin_roots=[bundled]).discover()
        if manifest.ui is not None
        for mode in manifest.ui.modes
    }
    # The desktop Study mode owns the Note vault, so its workspace stays offered.
    assert modes["study:study"].capabilities == ["notes"]
    # Workflow makes no claim, which keeps its surfaces available everywhere.
    assert modes["workflow:workflow"].capabilities is None

    # The declaration must also survive the plugin.ui.list boundary, because
    # that payload is what the shared UI gates its surfaces on.
    payloads = {
        manifest.name: operations._ui_payload(manifest)
        for manifest in PluginRegistry(plugin_roots=[bundled]).discover()
    }
    study_mode = payloads["study"]["modes"][0]
    assert study_mode["capabilities"] == ["notes"]
    # An undeclared mode omits the field entirely, which the UI reads as "make
    # no claim" rather than "supports nothing".
    assert "capabilities" not in payloads["workflow"]["modes"][0]
