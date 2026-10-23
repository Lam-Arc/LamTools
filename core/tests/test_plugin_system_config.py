"""Step 6 acceptance tests: per-plugin config storage and validation."""

from __future__ import annotations

import json
from pathlib import Path

from lamtools_core.app import OperationCatalog
from lamtools_core.plugin_system import PluginHost
from lamtools_core.plugin_system.config_store import (
    read_config_values,
    validate_config,
    write_config_values,
)
from lamtools_core.plugin_system.manifest import load_manifest
from lamtools_core.plugin_system.operations import register_plugin_system_operations


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
    return directory


def make_catalog(tmp_path: Path, root: Path) -> tuple[OperationCatalog, PluginHost]:
    host = PluginHost(roots=[root], state_path=tmp_path / "plugin-system.jsonc")
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)
    return catalog, host


SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {
            "endpoint": {"type": "string"},
            "retries": {"type": "integer"},
            "enabled": {"type": "boolean"},
            "mode": {"type": "string", "enum": ["fast", "safe"]},
        },
        "required": ["endpoint"],
    }
)


def test_config_values_round_trip(tmp_path: Path) -> None:
    directory = make_plugin(
        tmp_path / "plugins",
        "demo",
        manifest={"config": {"schema": "./config/schema.jsonc"}},
        files={"config/schema.jsonc": SCHEMA},
    )
    manifest = load_manifest(directory / "plugin.json")

    write_config_values(manifest, {"endpoint": "https://example.test"})

    assert read_config_values(manifest) == {"endpoint": "https://example.test"}
    assert (directory / "data" / "config.jsonc").is_file()


def test_validation_reports_type_errors() -> None:
    schema = json.loads(SCHEMA)

    problems = validate_config(schema, {"endpoint": 1, "retries": "many", "enabled": "yes"})

    assert len(problems) == 3
    assert all("string" in item or "integer" in item or "boolean" in item for item in problems)


def test_validation_reports_missing_required_and_bad_enum() -> None:
    schema = json.loads(SCHEMA)

    assert any("endpoint" in item for item in validate_config(schema, {}))
    assert any("mode" in item for item in validate_config(schema, {"mode": "slow"}))


async def test_config_operations_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "demo",
        manifest={"config": {"schema": "./config/schema.jsonc"}},
        files={"config/schema.jsonc": SCHEMA},
    )
    catalog, _host = make_catalog(tmp_path, root)

    initial = await catalog.execute("plugin.system.config.get", {"name": "demo"})
    assert initial.status == "ok"
    assert initial.payload["config"] == {}
    assert initial.payload["has_schema"] is True

    saved = await catalog.execute(
        "plugin.system.config.update",
        {"name": "demo", "config": {"endpoint": "https://example.test"}},
    )
    assert saved.status == "ok"

    loaded = await catalog.execute("plugin.system.config.get", {"name": "demo"})
    assert loaded.payload["config"] == {"endpoint": "https://example.test"}


async def test_config_operation_rejects_invalid_values(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "demo",
        manifest={"config": {"schema": "./config/schema.jsonc"}},
        files={"config/schema.jsonc": SCHEMA},
    )
    catalog, _host = make_catalog(tmp_path, root)

    result = await catalog.execute(
        "plugin.system.config.update",
        {"name": "demo", "config": {"endpoint": 4}},
    )

    assert result.status == "error"
    assert "string" in result.payload["error"]


async def test_config_get_reports_the_panel_and_identity(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "demo",
        manifest={
            "description": "demo plugin",
            "config": {"schema": "./config/schema.jsonc", "panel": "./config/panel.js"},
        },
        files={
            "config/schema.jsonc": SCHEMA,
            "config/panel.js": "window.LamToolsPluginPanels = window.LamToolsPluginPanels || {};",
        },
    )
    catalog, _host = make_catalog(tmp_path, root)

    result = await catalog.execute("plugin.system.config.get", {"name": "demo"})

    assert result.payload["version"] == "1.0.0"
    assert result.payload["description"] == "demo plugin"
    assert result.payload["has_panel"] is True
    assert result.payload["panel_url"] == "/api/core/plugin-system/demo/assets/config/panel.js"


async def test_plugin_without_panel_falls_back_to_the_default_form(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "plain")
    catalog, _host = make_catalog(tmp_path, root)

    result = await catalog.execute("plugin.system.config.get", {"name": "plain"})

    assert result.payload["has_panel"] is False
    assert result.payload["panel_url"] == ""
    assert result.payload["has_schema"] is False


async def test_plugin_without_schema_accepts_any_object(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "plain")
    catalog, _host = make_catalog(tmp_path, root)

    result = await catalog.execute(
        "plugin.system.config.update",
        {"name": "plain", "config": {"anything": True}},
    )

    assert result.status == "ok"
    loaded = await catalog.execute("plugin.system.config.get", {"name": "plain"})
    assert loaded.payload["config"] == {"anything": True}
    assert loaded.payload["has_schema"] is False
