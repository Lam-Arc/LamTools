"""Manifest-mounted CLI coverage for the bundled Workflow plugin."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lamtools_core.cli import build_parser
from lamtools_core.plugins.bundled.workflow.backend import cli as workflow_cli
from lamtools_core.plugins.registry import bundled_plugins_dir


class _FakeClient:
    def __init__(self, calls: list[tuple[str, dict[str, Any]]]) -> None:
        self.calls = calls

    async def request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, payload))
        return {
            "run": {
                "status": "completed",
                "run_id": "cli-run",
                "node_states": {},
                "output": {"ok": True},
            }
        }


@pytest.mark.asyncio
async def test_workflow_cli_is_manifest_mounted_and_executes_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_invoke(args: Any, operation: Any) -> dict[str, Any]:
        return await operation(_FakeClient(calls))

    monkeypatch.setattr(workflow_cli, "_invoke_live", fake_invoke)
    parser = build_parser(
        plugin_roots=[bundled_plugins_dir()],
        plugin_state_path=tmp_path / "plugins.jsonc",
    )
    args = parser.parse_args(
        [
            "workflow",
            "run",
            "demo",
            "--work-root",
            str(tmp_path / "project"),
            "--input",
            "count=3",
            "--input",
            "enabled=true",
            "--input",
            'payload={"a":1}',
            "--raw",
        ]
    )

    assert args._plugin_cli_plugin == "workflow"
    assert args._plugin_cli_command == "workflow run"
    assert await args.func(args) == 0
    assert calls == [
        (
            "workflow.run",
            {
                "name": "demo",
                "work_root": str((tmp_path / "project").resolve()),
                "inputs": {"count": 3, "enabled": True, "payload": {"a": 1}},
            },
        )
    ]


def test_disabled_workflow_cli_is_not_mounted(tmp_path: Path) -> None:
    from lamtools_core.plugins.registry import PluginStateStore

    state_path = tmp_path / "plugins.jsonc"
    PluginStateStore(state_path).set_enabled("workflow", False)
    parser = build_parser(plugin_roots=[bundled_plugins_dir()], plugin_state_path=state_path)

    with pytest.raises(SystemExit):
        parser.parse_args(["workflow", "run", "demo"])
