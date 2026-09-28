from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugins import HookRegistry, HookTrustStore, PluginRegistry, PluginStateStore
from lamtools_core.plugins.operations import build_plugin_operation_catalog
from lamtools_core.plugins.registry import bundled_plugins_dir


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _plugin(root: Path, *, name: str = "Display Alpha", plugin_id: str = "alpha") -> Path:
    plugin = root / plugin_id
    module = f"widget_ops_{plugin_id.replace('-', '_')}"
    (plugin / f"{module}.py").parent.mkdir(parents=True, exist_ok=True)
    (plugin / f"{module}.py").write_text(
        "from lamtools_core.app import OperationResult\n"
        "async def snapshot(request, **kwargs):\n"
        "    return OperationResult(name=request.name, payload={\n"
        "      'schema_version': 1, 'state': 'ok',\n"
        "      'summary': request.payload.get('work_root', ''),\n"
        "      'blocks': [{'type': 'text', 'text': request.payload.get('thread_id', '')}],\n"
        "      'actions': [{'id': 'rebuild'}]})\n"
        "async def rebuild(request, **kwargs):\n"
        "    return OperationResult(name=request.name, payload=dict(request.payload))\n",
        encoding="utf-8",
    )
    _write(
        plugin / "operations.jsonc",
        {
            "operations": [
                {"name": f"{plugin_id}.snapshot", "handler": f"{module}:snapshot"},
                {"name": f"{plugin_id}.rebuild", "handler": f"{module}:rebuild"},
            ]
        },
    )
    _write(
        plugin / "plugin.json",
        {
            "id": plugin_id,
            "name": name,
            "operations": ["./operations.jsonc"],
            "ui": {
                "sidebar": {
                    "widgets": [
                        {
                            "id": f"{plugin_id}.status",
                            "title": "Status",
                            "renderer": "blocks",
                            "scope": "session",
                            "snapshotOperation": f"{plugin_id}.snapshot",
                            "actions": [
                                {
                                    "id": "rebuild",
                                    "title": "Rebuild",
                                    "operation": f"{plugin_id}.rebuild",
                                    "dangerous": True,
                                    "mutates": True,
                                    "inputSchema": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["limit"],
                                        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 10}},
                                    },
                                }
                            ],
                        }
                    ]
                }
            },
        },
    )
    return plugin


def _catalog(root: Path, work_root: Path):
    state = PluginStateStore(root / "state.json")
    return build_plugin_operation_catalog(
        plugin_registry=PluginRegistry(plugin_roots=[root / "plugins"], state_store=state),
        plugin_state_store=state,
        hook_registry_factory=lambda: HookRegistry(),
        hook_trust_store=HookTrustStore(root / "trust.json"),
        work_root=work_root,
        data_dir=root / "data",
    )


@pytest.mark.asyncio
async def test_widget_facade_uses_canonical_id_and_authoritative_scope(tmp_path: Path) -> None:
    _plugin(tmp_path / "plugins")
    catalog = _catalog(tmp_path, tmp_path / "fallback")

    listed = await catalog.execute("plugin.widget.list")
    descriptor = listed.payload["widgets"][0]
    assert descriptor["pluginId"] == "alpha"
    assert descriptor["id"] == "alpha.status"
    assert "operation" not in descriptor["actions"][0]

    actual_root = tmp_path / "actual"
    shown = await catalog.execute(
        "plugin.widget.get",
        {"id": "alpha.status", "work_root": str(tmp_path / "spoofed"), "thread_id": "spoofed"},
        metadata={"work_root": str(actual_root), "thread_id": "thread-1"},
    )
    assert shown.status == "ok"
    assert shown.payload["snapshot"]["summary"] == str(actual_root.resolve())
    assert shown.payload["snapshot"]["blocks"][0]["text"] == "thread-1"


@pytest.mark.asyncio
async def test_widget_action_enforces_declaration_schema_confirmation_and_idempotency(tmp_path: Path) -> None:
    _plugin(tmp_path / "plugins")
    catalog = _catalog(tmp_path, tmp_path / "workspace")
    base = {"id": "alpha.status", "action": "rebuild", "thread_id": "thread-1"}

    assert (await catalog.execute("plugin.widget.invoke", {**base, "input": {"limit": 0}})).status == "error"
    assert (await catalog.execute("plugin.widget.invoke", {**base, "input": {"limit": 2}})).status == "error"
    missing_key = await catalog.execute(
        "plugin.widget.invoke", {**base, "input": {"limit": 2}, "confirmed": True}
    )
    assert missing_key.status == "error"
    invoked = await catalog.execute(
        "plugin.widget.invoke",
        {**base, "input": {"limit": 2}, "confirmed": True, "idempotency_key": "once-1"},
    )
    assert invoked.status == "ok"
    assert invoked.payload["result"]["limit"] == 2
    assert invoked.payload["result"]["work_root"] == str((tmp_path / "workspace").resolve())
    assert invoked.payload["result"]["thread_id"] == "thread-1"
    assert invoked.payload["result"]["idempotency_key"] == "once-1"


@pytest.mark.asyncio
async def test_duplicate_widget_ids_are_excluded_as_ambiguous(tmp_path: Path) -> None:
    first = _plugin(tmp_path / "plugins", plugin_id="first", name="First")
    second = _plugin(tmp_path / "plugins", plugin_id="second", name="Second")
    for plugin in (first, second):
        manifest = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))
        manifest["ui"]["sidebar"]["widgets"][0]["id"] = "shared.status"
        _write(plugin / "plugin.json", manifest)
    catalog = _catalog(tmp_path, tmp_path / "workspace")

    listed = await catalog.execute("plugin.widget.list")
    assert listed.payload["widgets"] == []
    assert listed.payload["errors"][0]["id"] == "shared.status"
    shown = await catalog.execute("plugin.widget.get", {"id": "shared.status", "thread_id": "t"})
    assert shown.status == "error"


@pytest.mark.asyncio
async def test_widget_cannot_claim_an_operation_it_does_not_own(tmp_path: Path) -> None:
    plugin = _plugin(tmp_path / "plugins")
    manifest = json.loads((plugin / "plugin.json").read_text(encoding="utf-8"))
    manifest["ui"]["sidebar"]["widgets"][0]["snapshotOperation"] = "plugin.list"
    _write(plugin / "plugin.json", manifest)
    catalog = _catalog(tmp_path, tmp_path / "workspace")

    shown = await catalog.execute("plugin.widget.get", {"id": "alpha.status", "thread_id": "t"})
    assert shown.status == "error"
    assert "owned by another plugin" in shown.payload["error"]


def test_component_widget_entry_must_stay_inside_plugin_root(tmp_path: Path) -> None:
    plugin = tmp_path / "plugins" / "bad"
    (tmp_path / "outside.ts").write_text("export default {}", encoding="utf-8")
    _write(
        plugin / "plugin.json",
        {
            "name": "bad",
            "ui": {
                "sidebar": {
                    "widgets": [
                        {"id": "bad.component", "renderer": "component", "scope": "global", "entry": "./../outside.ts"}
                    ]
                }
            },
        },
    )
    registry = PluginRegistry(plugin_roots=[tmp_path / "plugins"])
    assert registry.discover() == []
    assert "outside plugin root" in registry.discover_errors[0]["error"]


@pytest.mark.asyncio
async def test_bundled_websearch_widget_has_valid_snapshot(tmp_path: Path) -> None:
    # websearch 默认关闭（清单 defaultEnabled=false），先显式启用再取快照。
    state = PluginStateStore(tmp_path / "state.json")
    state.set_enabled("websearch", True)
    catalog = build_plugin_operation_catalog(
        plugin_registry=PluginRegistry(plugin_roots=[bundled_plugins_dir()], state_store=state),
        plugin_state_store=state,
        hook_registry_factory=lambda: HookRegistry(),
        hook_trust_store=HookTrustStore(tmp_path / "trust.json"),
        work_root=tmp_path / "workspace",
        data_dir=tmp_path / "data",
    )
    shown = await catalog.execute("plugin.widget.get", {"id": "websearch.engine"})
    assert shown.status == "ok"
    assert shown.payload["snapshot"]["schema_version"] == 1
    assert shown.payload["snapshot"]["actions"] == [{"id": "test", "enabled": True}]


def test_cli_parser_exposes_widget_commands() -> None:
    from lamtools_core.cli import build_parser, cmd_plugin_widget_action, cmd_plugin_widget_list, cmd_plugin_widget_show

    parser = build_parser()
    assert parser.parse_args(["plugin", "widget", "list"]).func is cmd_plugin_widget_list
    assert parser.parse_args(["plugin", "widget", "show", "alpha.status"]).func is cmd_plugin_widget_show
    action = parser.parse_args(
        ["plugin", "widget", "action", "alpha.status", "rebuild", "--input", '{"limit":2}', "--yes"]
    )
    assert action.func is cmd_plugin_widget_action
    assert action.yes is True
