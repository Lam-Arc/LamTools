"""Step 2 acceptance tests: the six declarative capabilities.

user:“技能、工具、钩子、mcp、斜杠命令、上下文片段”+每一类都能从清单声明
读出来；一条坏声明只影响自己那颗插件，重名按显式冲突处理。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugin_system.capabilities import (
    CapabilityError,
    assemble_capabilities,
    read_capabilities,
)
from lamtools_core.plugin_system.manifest import load_manifest


def make_plugin(
    root: Path,
    name: str,
    *,
    manifest: dict | None = None,
    files: dict[str, str | dict] | None = None,
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"name": name, "version": "1.0.0", **(manifest or {})}
    (directory / "plugin.json").write_text(json.dumps(payload), encoding="utf-8")
    for relative, content in (files or {}).items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            content if isinstance(content, str) else json.dumps(content),
            encoding="utf-8",
        )
    return directory / "plugin.json"


def test_all_six_capabilities_are_read(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "demo",
        manifest={
            "tools": ["./tools.jsonc"],
            "skills": ["./skills"],
            "hooks": ["./hooks.json"],
            "mcp": ["./mcp.json"],
            "commands": [
                {"name": "demo", "title": "Demo", "operation": "demo.open"}
            ],
            "context": [{"file": "./context/rules.md", "order": 30}],
        },
        files={
            "tools.jsonc": {
                "tools": [
                    {
                        "name": "demo_echo",
                        "description": "Echo",
                        "handler": "handlers:echo",
                        "input_schema": {"type": "object"},
                        "permission": "auto_allow",
                    }
                ]
            },
            "skills/demo/SKILL.md": "---\nname: demo-skill\ndescription: Demo skill\n---\n\nBody\n",
            "hooks.json": {
                "hooks": {
                    "PreToolUse": [
                        {"matcher": "*", "hooks": [{"type": "command", "command": "echo hi"}]}
                    ]
                }
            },
            "mcp.json": {"mcpServers": {"demo": {"command": "demo-server"}}},
            "context/rules.md": "Rules",
        },
    )

    capabilities = read_capabilities(load_manifest(manifest_path))

    assert [tool.name for tool in capabilities.tools] == ["demo_echo"]
    assert capabilities.tools[0].handler == "handlers:echo"
    assert [skill.name for skill in capabilities.skills] == ["demo-skill"]
    assert [hook.event for hook in capabilities.hooks] == ["PreToolUse"]
    assert [path.name for path in capabilities.mcp_files] == ["mcp.json"]
    assert [command.name for command in capabilities.commands] == ["demo"]
    assert [entry.order for entry in capabilities.context] == [30]
    assert capabilities.context[0].file.name == "rules.md"


def test_minimal_plugin_has_no_capabilities(tmp_path: Path) -> None:
    manifest_path = make_plugin(tmp_path, "empty")

    capabilities = read_capabilities(load_manifest(manifest_path))

    assert capabilities.tools == []
    assert capabilities.skills == []
    assert capabilities.hooks == []
    assert capabilities.mcp_files == []
    assert capabilities.commands == []
    assert capabilities.context == []


def test_paths_must_stay_inside_the_plugin_root(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "escape",
        manifest={"tools": ["./../outside.jsonc"]},
    )

    with pytest.raises(CapabilityError, match="outside"):
        read_capabilities(load_manifest(manifest_path))


def test_declared_paths_must_start_with_dot_slash(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "bare",
        manifest={"tools": ["tools.jsonc"]},
    )

    with pytest.raises(CapabilityError, match="\\./"):
        read_capabilities(load_manifest(manifest_path))


def test_invalid_tool_permission_is_rejected(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "badtool",
        manifest={"tools": ["./tools.jsonc"]},
        files={
            "tools.jsonc": {
                "tools": [{"name": "x", "handler": "h:f", "permission": "sometimes"}]
            }
        },
    )

    with pytest.raises(CapabilityError, match="permission"):
        read_capabilities(load_manifest(manifest_path))


def test_on_load_tool_requires_a_skill(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "visibility",
        manifest={"tools": ["./tools.jsonc"]},
        files={
            "tools.jsonc": {
                "tools": [
                    {"name": "x", "handler": "h:f", "visibility": "on_load"}
                ]
            }
        },
    )

    with pytest.raises(CapabilityError, match="skill"):
        read_capabilities(load_manifest(manifest_path))


def test_unknown_hook_event_is_rejected(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "badevent",
        manifest={"hooks": ["./hooks.json"]},
        files={"hooks.json": {"hooks": {"EveryTurn": []}}},
    )

    with pytest.raises(CapabilityError, match="EveryTurn"):
        read_capabilities(load_manifest(manifest_path))


def test_duplicate_tool_names_across_plugins_are_a_conflict(tmp_path: Path) -> None:
    first = make_plugin(
        tmp_path,
        "first",
        manifest={"tools": ["./tools.jsonc"]},
        files={"tools.jsonc": {"tools": [{"name": "same", "handler": "a:f"}]}},
    )
    second = make_plugin(
        tmp_path,
        "second",
        manifest={"tools": ["./tools.jsonc"]},
        files={"tools.jsonc": {"tools": [{"name": "same", "handler": "b:f"}]}},
    )

    assembly = assemble_capabilities(
        [load_manifest(first), load_manifest(second)]
    )

    assert [tool.handler for tool in assembly.tools] == ["a:f"]
    assert assembly.errors[0]["plugin"] == "second"
    assert "same" in assembly.errors[0]["error"]


def test_a_broken_plugin_does_not_hide_the_healthy_one(tmp_path: Path) -> None:
    healthy = make_plugin(
        tmp_path,
        "healthy",
        manifest={"tools": ["./tools.jsonc"]},
        files={"tools.jsonc": {"tools": [{"name": "ok", "handler": "a:f"}]}},
    )
    broken = make_plugin(
        tmp_path,
        "broken",
        manifest={"tools": ["./tools.jsonc"]},
        files={"tools.jsonc": {"tools": [{"name": "bad"}]}},
    )

    assembly = assemble_capabilities(
        [load_manifest(healthy), load_manifest(broken)]
    )

    assert [tool.name for tool in assembly.tools] == ["ok"]
    assert assembly.errors[0]["plugin"] == "broken"


def test_context_is_sorted_by_order_then_file_name(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "context",
        manifest={
            "context": [
                {"file": "./context/zeta.md", "order": 10},
                {"file": "./context/alpha.md", "order": 10},
                {"file": "./context/first.md", "order": 5},
            ]
        },
        files={
            "context/zeta.md": "z",
            "context/alpha.md": "a",
            "context/first.md": "f",
        },
    )

    capabilities = read_capabilities(load_manifest(manifest_path))
    ordered = sorted(capabilities.context, key=lambda item: (item.order, item.file.name))

    assert [entry.file.name for entry in ordered] == ["first.md", "alpha.md", "zeta.md"]


def test_duplicate_command_names_across_plugins_are_a_conflict(tmp_path: Path) -> None:
    first = make_plugin(
        tmp_path,
        "first",
        manifest={"commands": [{"name": "run", "operation": "a.run"}]},
    )
    second = make_plugin(
        tmp_path,
        "second",
        manifest={"commands": [{"name": "run", "operation": "b.run"}]},
    )

    assembly = assemble_capabilities(
        [load_manifest(first), load_manifest(second)]
    )

    assert [command.operation for command in assembly.commands] == ["a.run"]
    assert assembly.errors[0]["plugin"] == "second"


def test_disabled_plugins_are_not_assembled(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "sleeping",
        manifest={"tools": ["./tools.jsonc"]},
        files={"tools.jsonc": {"tools": [{"name": "x", "handler": "h:f"}]}},
    )
    manifest = load_manifest(manifest_path, enabled=False)

    assembly = assemble_capabilities([manifest])

    assert assembly.tools == []
