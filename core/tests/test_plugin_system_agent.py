"""Step 5 acceptance tests: agent takeover declarations and priority."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugin_system import CapabilityError
from lamtools_core.plugin_system.agent import (
    assemble_agents,
    read_agent,
    resolve_agent_plan,
)
from lamtools_core.plugin_system.manifest import load_manifest


def make_plugin(
    root: Path,
    name: str,
    *,
    manifest: dict | None = None,
    files: dict[str, str] | None = None,
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
        path.write_text(content, encoding="utf-8")
    return directory / "plugin.json"


def test_agent_declaration_is_parsed(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "focus",
        manifest={
            "scope": "mode",
            "agent": {
                "mode": "focus",
                "prompt": "./prompt.md",
                "tools": ["read_file", "write_file"],
                "approval": "ask",
                "context": ["./context/rules.md"],
                "exclusiveTools": True,
            },
        },
        files={
            "prompt.md": "You are a focused writing agent.",
            "context/rules.md": "Write in the user's voice.",
        },
    )

    agent = read_agent(load_manifest(manifest_path))

    assert agent is not None
    assert agent.scope == "mode"
    assert agent.mode == "focus"
    assert agent.prompt_text == "You are a focused writing agent."
    assert agent.tools == ("read_file", "write_file")
    assert agent.approval == "ask"
    assert [path.name for path in agent.context] == ["rules.md"]
    assert agent.exclusive_tools is True


def test_missing_agent_is_none(tmp_path: Path) -> None:
    manifest_path = make_plugin(tmp_path, "plain")

    assert read_agent(load_manifest(manifest_path)) is None


def test_agent_prompt_must_stay_inside_the_plugin_root(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "escape",
        manifest={"agent": {"prompt": "./../outside.md"}},
    )

    with pytest.raises(CapabilityError, match="outside"):
        read_agent(load_manifest(manifest_path))


def test_agent_prompt_must_exist(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "missing",
        manifest={"agent": {"prompt": "./prompt.md"}},
    )

    with pytest.raises(CapabilityError, match="missing"):
        read_agent(load_manifest(manifest_path))


def test_invalid_approval_is_rejected(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "bad",
        manifest={"agent": {"approval": "sometimes"}},
    )

    with pytest.raises(CapabilityError, match="approval"):
        read_agent(load_manifest(manifest_path))


def test_duplicate_tools_are_rejected(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "dupe",
        manifest={"agent": {"tools": ["read_file", "read_file"]}},
    )

    with pytest.raises(CapabilityError, match="duplicate"):
        read_agent(load_manifest(manifest_path))


def test_mode_scope_requires_a_mode(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "nomode",
        manifest={"scope": "mode", "agent": {"approval": "ask"}},
    )

    with pytest.raises(CapabilityError, match="mode"):
        read_agent(load_manifest(manifest_path))


def test_two_global_agents_conflict(tmp_path: Path) -> None:
    first = make_plugin(
        tmp_path,
        "first",
        manifest={"scope": "global", "agent": {"approval": "ask"}},
    )
    second = make_plugin(
        tmp_path,
        "second",
        manifest={"scope": "global", "agent": {"approval": "ask"}},
    )

    assembly = assemble_agents([load_manifest(first), load_manifest(second)])

    assert [agent.plugin for agent in assembly.agents] == ["first"]
    assert assembly.errors[0]["plugin"] == "second"
    assert "global" in assembly.errors[0]["error"]


def test_resolution_prefers_session_then_mode_then_global(tmp_path: Path) -> None:
    global_agent = make_plugin(
        tmp_path,
        "global-plugin",
        manifest={"name": "global-plugin", "scope": "global", "agent": {"approval": "auto"}},
    )
    mode_agent = make_plugin(
        tmp_path,
        "mode-plugin",
        manifest={
            "name": "mode-plugin",
            "scope": "mode",
            "agent": {"mode": "focus", "approval": "ask"},
        },
    )
    session_agent = make_plugin(
        tmp_path,
        "session-plugin",
        manifest={
            "name": "session-plugin",
            "scope": "session",
            "agent": {"approval": "block"},
        },
    )
    agents = assemble_agents(
        [
            load_manifest(global_agent),
            load_manifest(mode_agent),
            load_manifest(session_agent),
        ]
    ).agents

    session_plan = resolve_agent_plan(
        agents, active_mode="mode-plugin:focus", session_plugin="session-plugin"
    )
    assert session_plan is not None
    assert session_plan.source == "session"
    assert session_plan.agent.plugin == "session-plugin"

    mode_plan = resolve_agent_plan(agents, active_mode="mode-plugin:focus")
    assert mode_plan is not None
    assert mode_plan.source == "mode"
    assert mode_plan.agent.plugin == "mode-plugin"

    short_mode_plan = resolve_agent_plan(agents, active_mode="focus")
    assert short_mode_plan is not None
    assert short_mode_plan.agent.plugin == "mode-plugin"

    global_plan = resolve_agent_plan(agents, active_mode="something-else")
    assert global_plan is not None
    assert global_plan.source == "global"
    assert global_plan.agent.plugin == "global-plugin"


def test_short_mode_match_is_ambiguous_for_two_plugins(tmp_path: Path) -> None:
    first = make_plugin(
        tmp_path,
        "first",
        manifest={"scope": "mode", "agent": {"mode": "edit", "approval": "ask"}},
    )
    second = make_plugin(
        tmp_path,
        "second",
        manifest={"scope": "mode", "agent": {"mode": "edit", "approval": "ask"}},
    )
    agents = assemble_agents([load_manifest(first), load_manifest(second)]).agents

    assert resolve_agent_plan(agents, active_mode="edit") is None
    assert resolve_agent_plan(agents, active_mode="first:edit") is not None


def test_disabled_agent_is_ignored(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "sleeping",
        manifest={"scope": "global", "agent": {"approval": "ask"}},
    )

    assembly = assemble_agents([load_manifest(manifest_path, enabled=False)])

    assert assembly.agents == []
