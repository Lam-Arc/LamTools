"""Migration bridge: v2 plugins are skipped by the legacy registry and merged."""

from __future__ import annotations

import json
from pathlib import Path

from lamtools_core.app.base_agent import assemble_core_agent_plugins
from lamtools_core.plugin_system import PluginHost
from lamtools_core.plugins.registry import PluginRegistry


def make_plugin(
    root: Path,
    name: str,
    *,
    manifest: dict | None = None,
    files: dict[str, str | dict] | None = None,
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "plugin.json").write_text(
        json.dumps({"name": name, "version": "1.0.0", **(manifest or {})}),
        encoding="utf-8",
    )
    for relative, content in (files or {}).items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            content if isinstance(content, str) else json.dumps(content),
            encoding="utf-8",
        )
    return directory


def test_legacy_registry_skips_v2_plugins(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "v2-plugin", manifest={"assembly": "v2"})
    make_plugin(root, "v1-plugin")

    legacy = PluginRegistry(plugin_roots=[root]).discover()
    modern = PluginHost(
        roots=[root], state_path=tmp_path / "plugin-system.jsonc"
    ).discover()

    assert [item.name for item in legacy] == ["v1-plugin"]
    assert [item.name for item in modern] == ["v1-plugin", "v2-plugin"]
    assert {item.name: item.assembly for item in modern} == {
        "v1-plugin": "v1",
        "v2-plugin": "v2",
    }


def test_v2_capabilities_are_merged_into_the_agent_assembly(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "demo",
        manifest={
            "assembly": "v2",
            "scope": "mode",
            "tools": ["./tools.jsonc"],
            "skills": ["./skills"],
            "hooks": ["./hooks.json"],
            "mcp": ["./mcp.json"],
            "context": [{"file": "./context/rules.md", "order": 10}],
            "agent": {"mode": "demo", "prompt": "./prompt.md"},
        },
        files={
            "tools.jsonc": {
                "tools": [
                    {
                        "name": "v2_tool",
                        "handler": "handlers:echo",
                        "permission": "auto_allow",
                    }
                ]
            },
            "skills/demo/SKILL.md": "---\nname: v2-skill\ndescription: V2\n---\nBody\n",
            "hooks.json": {
                "hooks": {
                    "PreToolUse": [
                        {"matcher": "*", "hooks": [{"type": "command", "command": "echo v2"}]}
                    ]
                }
            },
            "mcp.json": {"mcpServers": {"demo": {"command": "demo-server"}}},
            "context/rules.md": "Rules",
            "prompt.md": "You are the v2 demo agent.",
        },
    )

    result = assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[root],
    )

    assert "v2_tool" in {spec.name for spec in result["plugin_runtime_specs"]}
    assert any(path.name == "skills" for path in result["skill_roots"])
    engine = result["hook_engine"]
    assert engine is not None
    assert any(hook.plugin_name == "demo" for hook in engine.hooks)
    assert any(path.name == "mcp.json" for path in result["mcp_files"])
    assert result["plugin_context_files"][0]["plugin"] == "demo"
    assert result["plugin_agents"][0].plugin == "demo"
    assert result["plugin_agents"][0].prompt_text == "You are the v2 demo agent."


def test_v1_plugin_still_uses_the_legacy_assembly(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "legacy",
        manifest={"tools": ["./tools.jsonc"]},
        files={"tools.jsonc": {"tools": [{"name": "legacy_tool", "handler": "a:f"}]}},
    )

    result = assemble_core_agent_plugins(
        data_dir=tmp_path / "data",
        work_root=tmp_path,
        plugin_roots=[root],
    )

    groups = {group["name"]: group for group in result["plugin_tool_groups"]}
    assert "legacy" in groups
    assert [tool.name for tool in groups["legacy"]["tools"]] == ["legacy_tool"]
