"""user:“支持一下”+(插件自绘页面可发现、分屏打开，声明失败不影响别的插件)。"""
import json
from pathlib import Path

import pytest

from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.plugin_system import PluginHost
from lamtools_core.plugin_system.manifest import load_manifest
from lamtools_core.plugin_system.capabilities import CapabilityError
from lamtools_core.plugin_system.operations import register_plugin_system_operations
from lamtools_core.plugin_system.ui import read_ui, assemble_ui


def plugin(root, name="demo", pages=None):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "page.js").write_text("export function mount(root, context) { return () => {} }", encoding="utf8")
    (folder / "plugin.json").write_text(json.dumps({"name": name, "version": "1.0.0", "ui": {
        "pages": pages if pages is not None else [{"id": "wall", "title": "Card wall", "entry": "./page.js"}]
    }}), encoding="utf8")
    return folder / "plugin.json"


def test_pages_are_namespaced_and_separate_from_modes(tmp_path):
    first = load_manifest(plugin(tmp_path, "first"))
    second = load_manifest(plugin(tmp_path, "second"))
    assembly = assemble_ui([first, second])
    assert [(p.plugin, p.id) for p in assembly.pages] == [("first", "wall"), ("second", "wall")]
    assert not assembly.modes


@pytest.mark.parametrize("pages", [
    [{"id": "wall", "entry": "../escape.js"}],
    [{"id": "wall", "entry": "./missing.js"}],
    [{"id": "wall", "entry": "./page.ts"}],
    [{"id": "", "entry": "./page.js"}],
    [{"id": "wall", "entry": "./page.js"}, {"id": "wall", "entry": "./page.js"}],
    "not-an-array",
])
def test_invalid_page_declarations_fail_explicitly(tmp_path, pages):
    with pytest.raises(CapabilityError):
        read_ui(load_manifest(plugin(tmp_path, pages=pages)))


@pytest.mark.asyncio
async def test_ui_rpc_only_lists_enabled_pages_with_asset_urls(tmp_path):
    plugin(tmp_path)
    host = PluginHost(roots=[tmp_path], state_path=tmp_path / "state.json")
    catalog = OperationCatalog()
    register_plugin_system_operations(catalog, host)
    payload = (await catalog.execute("plugin.system.ui", {})).payload
    page = payload["pages"][0]
    assert page["plugin"] == "demo" and page["id"] == "wall"
    assert page["entry_url"] == "/api/core/plugin-system/demo/assets/page.js"
    assert page["version"] == "1.0.0"
    host.disable("demo")
    assert (await catalog.execute("plugin.system.ui", {})).payload["pages"] == []


def test_broken_page_does_not_hide_other_plugins(tmp_path):
    broken = load_manifest(plugin(tmp_path, "broken", [{"id": "oops", "entry": "./absent.js"}]))
    good = load_manifest(plugin(tmp_path, "good"))
    assembly = assemble_ui([broken, good])
    assert [p.plugin for p in assembly.pages] == ["good"]
    assert assembly.errors[0]["plugin"] == "broken"


def test_card_wall_plugin_exposes_a_real_split_page():
    manifest = load_manifest(Path(__file__).resolve().parents[2] / "plugins/bili-scroll/plugin.json")
    page = next(page for page in read_ui(manifest).pages if page.id == "wall")
    assert page.title == "B站卡片墙"
    assert page.entry.name == "wall-page.mjs" and page.entry.is_file()
