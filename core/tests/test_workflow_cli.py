"""Manifest-mounted CLI coverage for the bundled Workflow plugin."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
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


def test_workflow_runtime_rpc_cli_commands_are_manifest_mounted(tmp_path: Path) -> None:
    parser = build_parser(
        plugin_roots=[bundled_plugins_dir()],
        plugin_state_path=tmp_path / "plugins.jsonc",
    )
    commands = {
        ("workflow", "list-grouped"): "workflow list-grouped",
        ("workflow", "save", "--from-file", "definition.json"): "workflow save",
        ("workflow", "update", "demo"): "workflow update",
        ("workflow", "rename", "before", "after"): "workflow rename",
        ("workflow", "delete", "demo"): "workflow delete",
        ("workflow", "activate", "demo"): "workflow activate",
        ("workflow", "deactivate", "demo"): "workflow deactivate",
        ("workflow", "activations", "demo"): "workflow activations",
        ("workflow", "object-info"): "workflow object-info",
        ("workflow", "tools", "list"): "workflow tools list",
    }
    for argv, expected in commands.items():
        args = parser.parse_args(list(argv))
        assert args._plugin_cli_plugin == "workflow"
        assert args._plugin_cli_command == expected
        assert callable(args.func)


@pytest.mark.asyncio
async def test_workflow_runtime_rpc_cli_handlers_match_operation_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class Client:
        async def request(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
            calls.append((name, payload))
            return {"workflow": {"name": "demo"}, "deleted": True, "object_info": {}, "tools": [], "groups": {}}

    async def fake_invoke(args: Any, operation: Any) -> dict[str, Any]:
        return await operation(Client())

    monkeypatch.setattr(workflow_cli, "_invoke_live", fake_invoke)
    definition_path = tmp_path / "definition.json"
    definition_path.write_text('{"name":"demo","nodes":[]}', encoding="utf-8")

    assert await workflow_cli.workflow_list_grouped(
        SimpleNamespace(work_root=[str(tmp_path)], raw=True)
    ) == 0
    assert await workflow_cli.workflow_save(
        SimpleNamespace(
            from_file=str(definition_path), name="", work_root="", expected_revision=None,
            exposed=False, raw=True,
        )
    ) == 0
    assert await workflow_cli.workflow_update(
        SimpleNamespace(
            name="demo", work_root="", from_file="", description=None, nodes=None,
            edges=None, input_params=None, output_port=None, tool_name=None,
            exposed=False, unexposed=False, expected_revision=None, raw=True,
        )
    ) == 0
    assert await workflow_cli.workflow_rename(
        SimpleNamespace(name="before", new_name="after", work_root="", raw=True)
    ) == 0
    assert await workflow_cli.workflow_delete(
        SimpleNamespace(name="demo", work_root="", raw=True)
    ) == 0
    assert await workflow_cli.workflow_activate(
        SimpleNamespace(name="demo", work_root="", trigger_id="", replace=False, raw=True)
    ) == 0
    assert await workflow_cli.workflow_deactivate(
        SimpleNamespace(name="demo", work_root="", trigger_id="", replace=False, raw=True)
    ) == 0
    assert await workflow_cli.workflow_activation_list(
        SimpleNamespace(name="demo", work_root="", trigger_id="", replace=False, raw=True)
    ) == 0
    assert await workflow_cli.workflow_object_info(SimpleNamespace(name="content", raw=True)) == 0
    assert await workflow_cli.workflow_tools_list(SimpleNamespace(raw=True)) == 0

    assert [name for name, _ in calls] == [
        "workflow.list_grouped",
        "workflow.save",
        "workflow.update",
        "workflow.rename",
        "workflow.delete",
        "workflow.activate",
        "workflow.deactivate",
        "workflow.activation.list",
        "workflow.object_info",
        "workflow.tools.list",
    ]
    assert calls[0][1] == {"work_roots": [str(tmp_path)]}
    assert calls[1][1]["name"] == "demo"
    assert calls[2][1] == {"name": "demo"}
    assert calls[3][1] == {"name": "before", "new_name": "after"}
    assert calls[4][1] == {"name": "demo"}
    assert calls[5][1] == {"name": "demo"}
    assert calls[6][1] == {"name": "demo"}
    assert calls[7][1] == {"name": "demo"}
    assert calls[8][1] == {"name": "content"}
    assert calls[9][1] == {}
