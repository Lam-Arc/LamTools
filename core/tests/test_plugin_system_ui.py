"""Step 3 acceptance tests: UI declarations become regions, styles and scripts.

user:“界面四档全开”+第 3 步先把样式、区域、脚本从清单里读出来，挂到现有
位置；自绘入口和前端模块替换放后面。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugin_system.capabilities import CapabilityError
from lamtools_core.plugin_system.manifest import load_manifest
from lamtools_core.plugin_system.ui import assemble_ui, read_ui


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


def test_styles_regions_and_script_are_parsed(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "demo",
        manifest={
            "ui": {
                "styles": ["./style.css"],
                "script": "./main.js",
                "regions": [
                    {
                        "region": "right",
                        "order": 20,
                        "blocks": [{"type": "text", "label": "Status", "value": "Ready"}],
                        "actions": [
                            {
                                "id": "refresh",
                                "title": "Refresh",
                                "operation": "demo.refresh",
                            }
                        ],
                    }
                ],
            }
        },
        files={"style.css": "body{}", "main.js": "export {}"},
    )

    spec = read_ui(load_manifest(manifest_path))

    assert [asset.path.name for asset in spec.styles] == ["style.css"]
    assert spec.script is not None and spec.script.path.name == "main.js"
    region = spec.regions[0]
    assert region.region == "right"
    assert region.order == 20
    assert region.blocks[0].type == "text"
    assert region.blocks[0].label == "Status"
    assert region.actions[0].id == "refresh"
    assert region.actions[0].operation == "demo.refresh"


def test_all_supported_block_types_are_parsed(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "blocks",
        manifest={
            "ui": {
                "regions": [
                    {
                        "region": "settings",
                        "blocks": [
                            {"type": "text", "text": "hello"},
                            {"type": "status", "label": "State", "value": "ok", "state": "ok"},
                            {"type": "metric", "label": "Count", "value": 3},
                            {"type": "progress", "label": "Load", "value": 1, "max": 4},
                            {"type": "list", "label": "Items", "items": ["a", "b"]},
                        ],
                    }
                ]
            }
        },
    )

    spec = read_ui(load_manifest(manifest_path))

    assert [block.type for block in spec.regions[0].blocks] == [
        "text",
        "status",
        "metric",
        "progress",
        "list",
    ]
    assert spec.regions[0].blocks[3].max == 4
    assert spec.regions[0].blocks[4].items == ("a", "b")


def test_unknown_region_is_rejected(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "badregion",
        manifest={"ui": {"regions": [{"region": "sidebar", "blocks": []}]}},
    )

    with pytest.raises(CapabilityError, match="sidebar"):
        read_ui(load_manifest(manifest_path))


def test_unknown_block_type_is_rejected(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "badblock",
        manifest={
            "ui": {"regions": [{"region": "right", "blocks": [{"type": "video"}]}]}
        },
    )

    with pytest.raises(CapabilityError, match="video"):
        read_ui(load_manifest(manifest_path))


def test_style_path_must_stay_inside_the_plugin_root(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "escape",
        manifest={"ui": {"styles": ["./../outside.css"]}},
    )

    with pytest.raises(CapabilityError, match="outside"):
        read_ui(load_manifest(manifest_path))


def test_missing_style_file_is_rejected(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "missing",
        manifest={"ui": {"styles": ["./style.css"]}},
    )

    with pytest.raises(CapabilityError, match="style"):
        read_ui(load_manifest(manifest_path))


def test_actions_require_an_operation(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "action",
        manifest={
            "ui": {
                "regions": [
                    {"region": "right", "actions": [{"id": "x", "title": "X"}]}
                ]
            }
        },
    )

    with pytest.raises(CapabilityError, match="operation"):
        read_ui(load_manifest(manifest_path))


def test_regions_are_ordered_by_order_then_plugin(tmp_path: Path) -> None:
    first = make_plugin(
        tmp_path,
        "zeta",
        manifest={"ui": {"regions": [{"region": "right", "order": 10, "blocks": []}]}},
    )
    second = make_plugin(
        tmp_path,
        "alpha",
        manifest={"ui": {"regions": [{"region": "right", "order": 10, "blocks": []}]}},
    )
    third = make_plugin(
        tmp_path,
        "middle",
        manifest={"ui": {"regions": [{"region": "right", "order": 5, "blocks": []}]}},
    )

    assembly = assemble_ui(
        [load_manifest(first), load_manifest(second), load_manifest(third)]
    )

    assert [(item.plugin, item.order) for item in assembly.regions] == [
        ("middle", 5),
        ("alpha", 10),
        ("zeta", 10),
    ]


def test_disabled_plugins_are_not_assembled(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "sleeping",
        manifest={"ui": {"regions": [{"region": "right", "blocks": []}]}},
    )

    assembly = assemble_ui([load_manifest(manifest_path, enabled=False)])

    assert assembly.regions == []
    assert assembly.styles == []


def test_a_broken_plugin_does_not_block_the_healthy_one(tmp_path: Path) -> None:
    healthy = make_plugin(
        tmp_path,
        "healthy",
        manifest={"ui": {"regions": [{"region": "right", "blocks": []}]}},
    )
    broken = make_plugin(
        tmp_path,
        "broken",
        manifest={"ui": {"regions": [{"region": "nowhere", "blocks": []}]}},
    )

    assembly = assemble_ui([load_manifest(healthy), load_manifest(broken)])

    assert [region.plugin for region in assembly.regions] == ["healthy"]
    assert assembly.errors[0]["plugin"] == "broken"


def test_two_replace_regions_on_the_same_target_conflict(tmp_path: Path) -> None:
    first = make_plugin(
        tmp_path,
        "first",
        manifest={"ui": {"regions": [{"region": "main", "replace": True, "blocks": []}]}},
    )
    second = make_plugin(
        tmp_path,
        "second",
        manifest={"ui": {"regions": [{"region": "main", "replace": True, "blocks": []}]}},
    )

    assembly = assemble_ui([load_manifest(first), load_manifest(second)])

    assert [region.plugin for region in assembly.regions] == ["first"]
    assert assembly.errors[0]["plugin"] == "second"
    assert "already replaced" in assembly.errors[0]["error"]


def test_windows_are_parsed(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "pet",
        manifest={
            "ui": {
                "windows": [
                    {
                        "id": "pet",
                        "title": "Desk Pet",
                        "entry": "./window.html",
                        "width": 300,
                        "height": 400,
                    }
                ]
            }
        },
        files={"window.html": "<html></html>"},
    )

    spec = read_ui(load_manifest(manifest_path))

    window = spec.windows[0]
    assert window.id == "pet"
    assert window.title == "Desk Pet"
    assert window.entry.name == "window.html"
    assert window.width == 300
    assert window.height == 400
    assert window.plugin == "pet"


def test_duplicate_window_ids_conflict(tmp_path: Path) -> None:
    first = make_plugin(
        tmp_path,
        "first",
        manifest={"ui": {"windows": [{"id": "pet", "entry": "./window.html"}]}},
        files={"window.html": "<html></html>"},
    )
    second = make_plugin(
        tmp_path,
        "second",
        manifest={"ui": {"windows": [{"id": "pet", "entry": "./window.html"}]}},
        files={"window.html": "<html></html>"},
    )

    assembly = assemble_ui([load_manifest(first), load_manifest(second)])

    assert [window.plugin for window in assembly.windows] == ["first"]
    assert "already declared" in assembly.errors[0]["error"]


def test_window_size_must_be_positive(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "bad",
        manifest={"ui": {"windows": [{"id": "pet", "entry": "./window.html", "width": 0}]}},
        files={"window.html": "<html></html>"},
    )

    with pytest.raises(CapabilityError, match="width"):
        read_ui(load_manifest(manifest_path))


def test_window_entry_must_exist(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "missing",
        manifest={"ui": {"windows": [{"id": "pet", "entry": "./window.html"}]}},
    )

    with pytest.raises(CapabilityError, match="missing"):
        read_ui(load_manifest(manifest_path))
