"""v2 slash commands join the existing composer command catalog."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from lamtools_core.composer_commands import build_composer_command_catalog
from lamtools_core.plugin_system import PluginHost
from lamtools_core.plugin_system.commands import composer_plugin_handles


def make_host(tmp_path: Path, manifest: dict) -> PluginHost:
    root = tmp_path / "plugins"
    plugin_dir = root / manifest["name"]
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"version": "1.0.0", "assembly": "v2", **manifest}),
        encoding="utf-8",
    )
    return PluginHost(roots=[root], state_path=tmp_path / "plugin-system.jsonc")


def build_catalog(tmp_path: Path, host: PluginHost):
    return build_composer_command_catalog(
        core_roots=[],
        member_roots=[],
        work_root=tmp_path,
        skill_registry=SimpleNamespace(available=lambda work_root: []),
        plugin_manifests=composer_plugin_handles(host),
    )


def test_declared_command_reaches_the_catalog_with_its_operation(tmp_path: Path) -> None:
    host = make_host(
        tmp_path,
        {
            "name": "demo",
            "commands": [
                {
                    "name": "demo-hello",
                    "title": "Demo Hello",
                    "description": "say hi",
                    "operation": "plugin.system.list",
                    "payload": {"scope": "demo"},
                }
            ],
        },
    )

    catalog = build_catalog(tmp_path, host)

    definition = next(item for item in catalog if item.name == "demo-hello")
    assert definition.source == "plugin"
    assert definition.title == "Demo Hello"
    assert definition.description == "say hi"
    assert definition.accepts_args is True
    assert definition.metadata["plugin_name"] == "demo"
    assert definition.metadata["operation"] == "plugin.system.list"
    assert definition.metadata["payload"] == {"scope": "demo"}


def test_disabled_plugin_contributes_no_commands(tmp_path: Path) -> None:
    host = make_host(
        tmp_path,
        {
            "name": "demo",
            "commands": [{"name": "demo-hello", "operation": "plugin.system.list"}],
        },
    )
    host.disable("demo")

    assert composer_plugin_handles(host) == []
    assert build_catalog(tmp_path, host) == []


def test_effect_only_command_keeps_its_effect(tmp_path: Path) -> None:
    host = make_host(
        tmp_path,
        {
            "name": "demo",
            "commands": [
                {
                    "name": "demo-panel",
                    "title": "demo-panel",
                    "effect": {"open": "panel"},
                }
            ],
        },
    )

    handles = composer_plugin_handles(host)

    command = handles[0].commands[0]
    assert command.operation == ""
    assert command.accepts_args is False
    assert command.effect == {"open": "panel"}
