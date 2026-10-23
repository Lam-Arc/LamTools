"""RPC surface for the redesigned plugin system (step 1).

user:“插件页能看到它”+列表、启停、卸载必须能从操作目录直接调用。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system import PluginHost
from lamtools_core.plugin_system.operations import register_plugin_system_operations


def make_catalog(tmp_path: Path) -> OperationCatalog:
    root = tmp_path / "plugins"
    plugin_dir = root / "hello"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "hello", "version": "0.1.0"}), encoding="utf-8"
    )
    (plugin_dir / "data").mkdir()
    (plugin_dir / "data" / "kept.txt").write_text("kept", encoding="utf-8")
    host = PluginHost(roots=[root], state_path=tmp_path / "plugin-system.jsonc")
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)
    return catalog


async def test_list_returns_minimal_plugin(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)

    result = await catalog.execute("plugin.system.list", {})

    assert result.status == "ok"
    assert result.payload["plugins"] == [
        {
            "name": "hello",
            "version": "0.1.0",
            "description": "",
            "enabled": True,
            "scope": "global",
            "root": str((tmp_path / "plugins" / "hello").resolve()),
        }
    ]
    assert result.payload["errors"] == []


async def test_disable_and_enable_round_trip(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)

    disabled = await catalog.execute("plugin.system.disable", {"name": "hello"})
    assert disabled.status == "ok"
    assert disabled.payload["enabled"] is False

    listed = await catalog.execute("plugin.system.list", {})
    assert listed.payload["plugins"][0]["enabled"] is False

    enabled = await catalog.execute("plugin.system.enable", {"name": "hello"})
    assert enabled.payload["enabled"] is True


async def test_uninstall_keeps_data(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)

    result = await catalog.execute(
        "plugin.system.uninstall", {"name": "hello", "keep_data": True}
    )

    assert result.status == "ok"
    assert not (tmp_path / "plugins" / "hello" / "plugin.json").exists()
    assert (tmp_path / "plugins" / "hello" / "data" / "kept.txt").is_file()
    assert (await catalog.execute("plugin.system.list", {})).payload["plugins"] == []


async def test_missing_name_is_an_operation_error(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)

    result = await catalog.execute("plugin.system.disable", {})

    assert result.status == "error"
    assert "name" in result.payload["error"]


async def test_unknown_plugin_is_an_operation_error(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)

    result = await catalog.execute("plugin.system.enable", {"name": "missing"})

    assert result.status == "error"
    assert "not installed" in result.payload["error"]
