"""Step 3 acceptance tests: plugin assets are served only from the plugin root.

user:“样式注入主界面”+CSS 和图片要能以同源 URL 取到，但不能越出插件根，
也不能从已禁用的插件里取。
"""

from __future__ import annotations

import json
from pathlib import Path

from lamtools_core.plugin_system import PluginHost, resolve_plugin_asset
from lamtools_core.plugin_system.assets import media_type_for


def make_host(tmp_path: Path, *, enabled: bool = True) -> PluginHost:
    root = tmp_path / "plugins"
    plugin_dir = root / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "1.0.0"}), encoding="utf-8"
    )
    (plugin_dir / "style.css").write_text("body{}", encoding="utf-8")
    (plugin_dir / "img").mkdir()
    (plugin_dir / "img" / "bg.svg").write_text("<svg/>", encoding="utf-8")
    (root / "outside.css").write_text("outside{}", encoding="utf-8")
    host = PluginHost(roots=[root], state_path=tmp_path / "plugin-system.jsonc")
    if not enabled:
        host.disable("demo")
    return host


def test_asset_inside_the_plugin_root_is_resolved(tmp_path: Path) -> None:
    host = make_host(tmp_path)

    target = resolve_plugin_asset(host, "demo", "style.css")

    assert target is not None
    assert target.name == "style.css"
    assert target.parent == (tmp_path / "plugins" / "demo").resolve()


def test_nested_asset_is_resolved(tmp_path: Path) -> None:
    host = make_host(tmp_path)

    target = resolve_plugin_asset(host, "demo", "img/bg.svg")

    assert target is not None
    assert target.name == "bg.svg"


def test_path_traversal_is_refused(tmp_path: Path) -> None:
    host = make_host(tmp_path)

    assert resolve_plugin_asset(host, "demo", "../outside.css") is None
    assert resolve_plugin_asset(host, "demo", "../../outside.css") is None


def test_disabled_plugin_assets_are_refused(tmp_path: Path) -> None:
    host = make_host(tmp_path, enabled=False)

    assert resolve_plugin_asset(host, "demo", "style.css") is None


def test_unknown_plugin_and_missing_file_are_refused(tmp_path: Path) -> None:
    host = make_host(tmp_path)

    assert resolve_plugin_asset(host, "missing", "style.css") is None
    assert resolve_plugin_asset(host, "demo", "missing.css") is None


def test_media_types_are_explicit() -> None:
    assert media_type_for(Path("a.css")) == "text/css; charset=utf-8"
    assert media_type_for(Path("a.js")) == "text/javascript; charset=utf-8"
    assert media_type_for(Path("a.svg")) == "image/svg+xml"
    assert media_type_for(Path("a.bin")) == "application/octet-stream"
