from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugins import HookRegistry, HookTrustStore, PluginManifest


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_hook_registry_loads_project_user_and_plugin_hooks(tmp_path: Path):
    project = tmp_path / "project"
    user = tmp_path / "user" / "hooks.json"
    plugin_root = tmp_path / "plugins" / "repo-policy"
    plugin_hooks = plugin_root / "hooks" / "hooks.json"
    hook_body = {
        "hooks": {
            "PreToolUse": [
                {"matcher": "run_command", "hooks": [{"type": "command", "command": "python check.py"}]}
            ]
        }
    }
    write_json(project / ".lamtools" / "hooks.json", hook_body)
    write_json(user, hook_body)
    write_json(plugin_hooks, hook_body)

    registry = HookRegistry(
        project_root=project,
        user_hooks_path=user,
        plugins=[
            PluginManifest(
                name="repo-policy",
                version="0.1.0",
                root=plugin_root,
                hook_files=[plugin_hooks],
            )
        ],
        trust_store=HookTrustStore(tmp_path / "trust.json"),
    )

    hooks = registry.load()

    assert [hook.source for hook in hooks] == ["project", "user", "plugin"]
    assert {hook.event for hook in hooks} == {"PreToolUse"}
    assert {hook.matcher for hook in hooks} == {"run_command"}
    assert all(hook.definition_hash for hook in hooks)
    assert all(hook.trusted is False for hook in hooks)
    assert all(hook.status == "pending_review" for hook in hooks)


def test_hook_registry_skips_disabled_plugin_hooks(tmp_path: Path):
    plugin_root = tmp_path / "plugins" / "disabled"
    plugin_hooks = plugin_root / "hooks" / "hooks.json"
    write_json(plugin_hooks, {
        "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python x.py"}]}]}
    })

    registry = HookRegistry(
        plugins=[
            PluginManifest(
                name="disabled",
                version="0.1.0",
                root=plugin_root,
                enabled=False,
                hook_files=[plugin_hooks],
            )
        ],
    )

    assert registry.load() == []


def test_hook_registry_marks_trusted_hooks(tmp_path: Path):
    project = tmp_path / "project"
    write_json(project / ".lamtools" / "hooks.json", {
        "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python ok.py"}]}]}
    })
    trust = HookTrustStore(tmp_path / "trust.json")
    first = HookRegistry(project_root=project, trust_store=trust).load()[0]
    trust.trust(first.definition_hash)

    second = HookRegistry(project_root=project, trust_store=trust).load()[0]

    assert second.trusted is True
    assert second.status == "trusted"


def test_hook_registry_skips_unsupported_handler_type(tmp_path: Path):
    """A broken handler must be skipped, not raise — one bad entry must not
    take the whole hook registry down (audit 11)."""
    project = tmp_path / "project"
    write_json(project / ".lamtools" / "hooks.json", {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "socket", "command": "x"},
                        {"type": "command", "command": "echo ok"},
                    ],
                }
            ]
        }
    })

    registry = HookRegistry(project_root=project)

    hooks = registry.load()
    assert len(hooks) == 1
    assert hooks[0].handler.type == "command"


def test_hook_registry_skips_structurally_broken_groups(tmp_path: Path):
    project = tmp_path / "project"
    write_json(project / ".lamtools" / "hooks.json", {
        "hooks": {
            "PreToolUse": "not-a-list",
            "PostToolUse": [{"matcher": "not-a-dict"}],
            "Stop": [{"matcher": "*", "hooks": [{"command": "echo fine"}]}],
        }
    })

    registry = HookRegistry(project_root=project)

    hooks = registry.load()
    assert len(hooks) == 1
    assert hooks[0].event == "Stop"


def test_hook_registry_tolerates_non_numeric_timeout(tmp_path: Path):
    project = tmp_path / "project"
    write_json(project / ".lamtools" / "hooks.json", {
        "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "x", "timeout": "abc"}]}]}
    })

    hooks = HookRegistry(project_root=project).load()

    assert len(hooks) == 1
    assert hooks[0].handler.timeout == 10.0
