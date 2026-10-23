"""Step 2b acceptance tests: six capabilities become runtime artifacts.

user:“六样都生效”+一次装配产出工具、技能、钩子、MCP、命令、上下文六类产物；
禁用插件时六类一起消失，启用时一起回来。
"""

from __future__ import annotations

import json
from pathlib import Path

from lamtools_core.plugin_system import PluginHost, PluginSystemRuntime


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


def make_runtime(tmp_path: Path, root: Path) -> PluginSystemRuntime:
    host = PluginHost(roots=[root], state_path=tmp_path / "plugin-system.jsonc")
    return PluginSystemRuntime(host)


def make_full_plugin(root: Path) -> Path:
    return make_plugin(
        root,
        "demo",
        manifest={
            "tools": ["./tools.jsonc"],
            "skills": ["./skills"],
            "hooks": ["./hooks.json"],
            "mcp": ["./mcp.json"],
            "commands": [{"name": "demo", "operation": "demo.open"}],
            "context": [{"file": "./context/rules.md", "order": 30}],
        },
        files={
            "tools.jsonc": {
                "tools": [
                    {
                        "name": "demo_echo",
                        "description": "Echo",
                        "handler": "handlers:echo",
                        "permission": "auto_allow",
                        "timeout": 30,
                    }
                ]
            },
            "skills/demo/SKILL.md": "---\nname: demo-skill\ndescription: Demo\n---\nBody\n",
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


def test_all_six_artifacts_are_assembled(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_full_plugin(root)
    runtime = make_runtime(tmp_path, root)

    artifacts = runtime.assemble()

    assert [tool.name for tool in artifacts.tools] == ["demo_echo"]
    tool = artifacts.tools[0]
    assert tool.permission == "auto_allow"
    assert tool.metadata["handler"] == "handlers:echo"
    assert tool.metadata["plugin"] == "demo"
    assert tool.metadata["plugin_root"] == str((root / "demo").resolve())
    assert tool.metadata["timeout"] == 30.0
    assert [skill.name for skill in artifacts.skills] == ["demo-skill"]
    assert artifacts.skill_roots == [(root / "demo" / "skills").resolve()]
    assert [hook.event for hook in artifacts.hooks] == ["PreToolUse"]
    assert [path.name for path in artifacts.mcp_files] == ["mcp.json"]
    assert [command.name for command in artifacts.commands] == ["demo"]
    assert [entry.order for entry in artifacts.context] == [30]
    assert artifacts.errors == []
    assert artifacts.is_empty() is False


def test_disabling_the_plugin_removes_every_artifact(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_full_plugin(root)
    runtime = make_runtime(tmp_path, root)
    runtime.host.disable("demo")

    artifacts = runtime.assemble()

    assert artifacts.is_empty() is True
    assert artifacts.tools == []
    assert artifacts.skills == []
    assert artifacts.hooks == []
    assert artifacts.mcp_files == []
    assert artifacts.commands == []
    assert artifacts.context == []


def test_re_enabling_restores_every_artifact(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_full_plugin(root)
    runtime = make_runtime(tmp_path, root)
    runtime.host.disable("demo")
    assert runtime.assemble().is_empty() is True

    runtime.host.enable("demo")
    artifacts = runtime.assemble()

    assert artifacts.is_empty() is False
    assert [tool.name for tool in artifacts.tools] == ["demo_echo"]


def test_a_broken_plugin_does_not_block_the_healthy_one(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "healthy",
        manifest={"tools": ["./tools.jsonc"]},
        files={"tools.jsonc": {"tools": [{"name": "ok", "handler": "a:f"}]}},
    )
    make_plugin(
        root,
        "broken",
        manifest={"tools": ["./tools.jsonc"]},
        files={"tools.jsonc": {"tools": [{"name": "bad"}]}},
    )
    runtime = make_runtime(tmp_path, root)

    artifacts = runtime.assemble()

    assert [tool.name for tool in artifacts.tools] == ["ok"]
    assert artifacts.errors[0]["plugin"] == "broken"
    assert "handler" in artifacts.errors[0]["error"]


def test_a_plugin_without_capabilities_produces_empty_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "empty")
    runtime = make_runtime(tmp_path, root)

    artifacts = runtime.assemble()

    assert artifacts.is_empty() is True
    assert artifacts.errors == []


def test_agent_plan_is_resolved_from_enabled_plugins(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "focus",
        manifest={
            "scope": "mode",
            "agent": {"mode": "focus", "prompt": "./prompt.md"},
        },
        files={"prompt.md": "Focused."},
    )
    runtime = make_runtime(tmp_path, root)

    plan = runtime.agent_plan(active_mode="focus:focus")

    assert plan is not None
    assert plan.source == "mode"
    assert plan.agent.prompt_text == "Focused."

    runtime.host.disable("focus")
    assert runtime.agent_plan(active_mode="focus:focus") is None
