"""Tests for manifest-declared plugin UI contributions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugins import HookRegistry, HookTrustStore, PluginRegistry, PluginStateStore
from lamtools_core.plugins.operations import build_plugin_operation_catalog


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _ui_plugin(root: Path, name: str, *, modes: list[dict] | None = None, views: list[dict] | None = None) -> Path:
    plugin = root / name
    entry = plugin / "ui" / "index.ts"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("export default {}", encoding="utf-8")
    _write(
        plugin / "plugin.json",
        {
            "name": name,
            "version": "1.0.0",
            "builtin": name == "builtin-ui",
            "ui": {
                "modes": modes or [{"id": "main", "title": "Main", "entry": "./ui/index.ts"}],
                "views": views or [],
            },
        },
    )
    return plugin


def _catalog(root: Path, state: PluginStateStore):
    registry = PluginRegistry(plugin_roots=[root], state_store=state)
    return build_plugin_operation_catalog(
        plugin_registry=registry,
        plugin_state_store=state,
        hook_registry_factory=lambda: HookRegistry(),
        hook_trust_store=HookTrustStore(root / "trust.json"),
        data_dir=root / "data",
    )


def test_manifest_without_ui_is_valid(tmp_path: Path) -> None:
    _write(tmp_path / "plain" / "plugin.json", {"name": "plain", "version": "1.0.0"})
    item = PluginRegistry(plugin_roots=[tmp_path]).discover()[0]
    assert item.ui is None


@pytest.mark.asyncio
async def test_plugin_ui_list_returns_modes_and_excludes_disabled(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _ui_plugin(root, "alpha")
    _ui_plugin(root, "beta", modes=[{"id": "editor", "title": "Editor", "entry": "./ui/index.ts"}])
    state = PluginStateStore(tmp_path / "state.jsonc")
    state.set_enabled("beta", False)

    catalog = _catalog(root, state)
    result = await catalog.execute("plugin.ui.list")

    assert result.status == "ok"
    assert [(item["pluginId"], item["id"]) for item in result.payload["modes"]] == [("alpha", "main")]
    assert result.payload["views"] == []


@pytest.mark.asyncio
async def test_plugin_ui_list_supports_multiple_contributions_and_plugin_list_metadata(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _ui_plugin(
        root,
        "builtin-ui",
        modes=[{"id": "workflow", "title": "Workflow", "entry": "./ui/index.ts", "icon": "workflow"}],
        views=[{"id": "inspector", "title": "Inspector", "entry": "./ui/index.ts"}],
    )
    _ui_plugin(root, "other")
    state = PluginStateStore(tmp_path / "state.jsonc")
    catalog = _catalog(root, state)

    listed = await catalog.execute("plugin.list")
    plugin = next(item for item in listed.payload["plugins"] if item["name"] == "builtin-ui")
    assert plugin["builtin"] is True
    assert plugin["ui"]["modes"][0]["id"] == "workflow"

    ui = await catalog.execute("plugin.ui.list")
    assert {(item["pluginId"], item["id"]) for item in ui.payload["modes"]} == {
        ("builtin-ui", "workflow"),
        ("other", "main"),
    }
    assert ui.payload["views"][0]["id"] == "inspector"


def test_invalid_ui_manifest_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path / "bad" / "plugin.json",
        {
            "name": "bad",
            "ui": {"modes": [{"id": "workflow", "entry": "./ui/missing.ts"}]},
        },
    )
    registry = PluginRegistry(plugin_roots=[tmp_path])
    assert registry.discover() == []
    assert registry.discover_errors
    assert "existing" in registry.discover_errors[0]["error"]


@pytest.mark.asyncio
async def test_plugin_ui_list_carries_the_mode_capability_declaration(tmp_path: Path) -> None:
    """模式的能力声明要走到界面真正读它的那个通道。

    界面通过 plugin.ui.list 取模式，只有 plugin.list 带声明时，Study 的 notes
    声明在共享界面等于没声明（2026-09-28 修）。
    """
    root = tmp_path / "plugins"
    _ui_plugin(
        root,
        "claiming",
        modes=[{"id": "study", "title": "Study", "entry": "./ui/index.ts", "capabilities": ["notes"]}],
    )
    _ui_plugin(root, "silent", modes=[{"id": "main", "title": "Main", "entry": "./ui/index.ts"}])
    state = PluginStateStore(tmp_path / "state.jsonc")
    catalog = _catalog(root, state)

    ui = await catalog.execute("plugin.ui.list")
    by_id = {item["id"]: item for item in ui.payload["modes"]}

    assert by_id["study"]["capabilities"] == ["notes"]
    # 未声明则整个字段不出现，界面读作"没有声明"而不是"什么都不支持"。
    assert "capabilities" not in by_id["main"]


@pytest.mark.asyncio
async def test_plugin_list_reports_the_declared_platform_class(tmp_path: Path) -> None:
    """插件列表带上分类，插件页据此分组。"""
    root = tmp_path / "plugins"
    _ui_plugin(root, "shared")
    manifest = json.loads((root / "shared" / "plugin.json").read_text(encoding="utf-8"))
    manifest["platforms"] = "desktop"
    (root / "shared" / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    state = PluginStateStore(tmp_path / "state.jsonc")
    catalog = _catalog(root, state)

    listed = await catalog.execute("plugin.list")
    entry = next(item for item in listed.payload["plugins"] if item["name"] == "shared")

    assert entry["platforms"] == "desktop"
