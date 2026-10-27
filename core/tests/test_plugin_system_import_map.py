"""收尾方案步骤 6 验收（主机侧）：双键族解析 / import map 生成与注入 /
安全模式 / boot 忽略前端键。

user:“前端模块替换”+``@/...`` 键走 import map，``lamtools_core.*`` 键走
boot 查找器；同一目标只能一个插件接管；注入在任何模块脚本之前。
"""

from __future__ import annotations

import json
from pathlib import Path

from lamtools_core.plugin_system import PluginHost
from lamtools_core.plugin_system.import_map import (
    build_import_map,
    inject_import_map,
    load_base_map,
)
from lamtools_core.plugin_system.overrides import assemble_overrides


def _make_plugin(root: Path, name: str, overrides: dict | None, files: dict | None = None) -> Path:
    plugin = root / name
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "plugin.json").write_text(
        json.dumps({"name": name, "version": "1.0.0", **({"overrides": overrides} if overrides else {})}),
        encoding="utf-8",
    )
    for relative, content in (files or {}).items():
        target = plugin / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return plugin


def test_overrides_accept_both_key_families(tmp_path: Path) -> None:
    _make_plugin(
        tmp_path,
        "mixed",
        overrides={
            "lamtools_core.prompt": "./overrides/prompt.py",
            "@/components/StreamingFade.vue": "./overrides/fade.js",
        },
        files={"overrides/prompt.py": "value = 1\n", "overrides/fade.js": "export const fade = () => {}\n"},
    )
    host = PluginHost(roots=[tmp_path], state_path=tmp_path / "s.jsonc")
    assembly = assemble_overrides(host.discover())

    assert assembly.errors == []
    backend = assembly.backend_overrides()
    frontend = assembly.frontend_overrides()
    assert set(backend) == {"lamtools_core.prompt"}
    assert set(frontend) == {"@/components/StreamingFade.vue"}


def test_frontend_override_conflicts_are_rejected(tmp_path: Path) -> None:
    _make_plugin(
        tmp_path,
        "first",
        overrides={"@/components/Fade.vue": "./fade.js"},
        files={"fade.js": "export {}\n"},
    )
    _make_plugin(
        tmp_path,
        "second",
        overrides={"@/components/Fade.vue": "./fade.js"},
        files={"fade.js": "export {}\n"},
    )
    host = PluginHost(roots=[tmp_path], state_path=tmp_path / "s.jsonc")
    assembly = assemble_overrides(host.discover())

    winners = assembly.frontend_overrides()
    assert set(winners) == {"@/components/Fade.vue"}
    assert winners["@/components/Fade.vue"].plugin == "first"
    assert any(item["plugin"] == "second" and "already overridden" in item["error"] for item in assembly.errors)


def test_build_import_map_merges_base_with_plugin_entries(tmp_path: Path) -> None:
    frontend = tmp_path / "dist"
    frontend.mkdir()
    (frontend / "importmap.base.json").write_text(
        json.dumps(
            {
                "imports": {
                    "@/components/Fade.vue": "/assets/Fade.abc123.js",
                    "@/components/Other.vue": "/assets/Other.def456.js",
                }
            }
        ),
        encoding="utf-8",
    )
    _make_plugin(
        tmp_path,
        "painter",
        overrides={"@/components/Fade.vue": "./particle.js"},
        files={"particle.js": "export const fade = () => 'particles'\n"},
    )
    host = PluginHost(roots=[tmp_path], state_path=tmp_path / "s.jsonc")

    mapping = build_import_map(host, frontend_dir=frontend)

    # user:“插件顶掉基础映射”+被声明的模块指向插件资产路由，其余保持。
    assert mapping["@/components/Fade.vue"] == "/api/core/plugin-system/painter/assets/particle.js"
    assert mapping["@/components/Other.vue"] == "/assets/Other.def456.js"


def test_safe_mode_returns_only_the_base_map(tmp_path: Path, monkeypatch) -> None:
    frontend = tmp_path / "dist"
    frontend.mkdir()
    (frontend / "importmap.base.json").write_text(
        json.dumps({"imports": {"@/a.vue": "/assets/a.js"}}),
        encoding="utf-8",
    )
    _make_plugin(
        tmp_path,
        "painter",
        overrides={"@/a.vue": "./particle.js"},
        files={"particle.js": "export {}\n"},
    )
    host = PluginHost(roots=[tmp_path], state_path=tmp_path / "s.jsonc")
    monkeypatch.setenv("LAMTOOLS_SAFE_MODE", "1")

    mapping = build_import_map(host, frontend_dir=frontend)

    assert mapping == {"@/a.vue": "/assets/a.js"}


def test_inject_import_map_lands_before_any_module_script() -> None:
    html = "<html><head><title>x</title></head><body><script type=\"module\" src=\"/app.js\"></script></body></html>"
    out = inject_import_map(html, {"@/a.vue": "/assets/a.js"})
    importmap_at = out.find('<script type="importmap">')
    module_at = out.find('<script type="module"')
    assert importmap_at != -1 and importmap_at < module_at
    assert json.loads(out[importmap_at + len('<script type="importmap">'):out.find("</script>", importmap_at)]) == {
        "imports": {"@/a.vue": "/assets/a.js"}
    }
    # 无映射时页面原样。
    assert inject_import_map(html, {}) == html


def test_inject_import_map_replaces_the_embedded_base_map() -> None:
    # user:“a3 无法使用，界面卡住了，查一查”+(构建页自带基础映射，Core 返回时原地替换为合并结果)
    base = '<script type="importmap">{"imports":{"@/a.vue":"/assets/a.js"}}</script>'
    html = (
        "<html><head>"
        f"{base}"
        '<script type="module" src="/assets/main.js"></script>'
        "</head><body></body></html>"
    )
    out = inject_import_map(html, {"@/a.vue": "/api/core/plugin-system/painter/assets/a.js"})

    assert out.count('type="importmap"') == 1
    importmap_at = out.find('<script type="importmap">')
    module_at = out.find('<script type="module"')
    assert importmap_at != -1 and importmap_at < module_at
    payload = json.loads(
        out[importmap_at + len('<script type="importmap">') : out.find("</script>", importmap_at)]
    )
    assert payload == {"imports": {"@/a.vue": "/api/core/plugin-system/painter/assets/a.js"}}


def test_boot_loader_ignores_frontend_keys(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from lamtools_boot.overrides import load_boot_overrides

    _make_plugin(
        tmp_path,
        "both",
        overrides={
            "@/components/Fade.vue": "./particle.js",
            "lamtools_core.demo": "./mod.py",
        },
        files={"particle.js": "export {}\n", "mod.py": "value = 1\n"},
    )
    state = tmp_path / "plugin-system.jsonc"
    state.write_text(json.dumps({"plugins": {"both": {"enabled": True}}}), encoding="utf-8")

    mapping, errors = load_boot_overrides(environ={}, roots=[tmp_path], state_path=state)

    assert errors == []
    assert set(mapping) == {"lamtools_core.demo"}


def test_load_base_map_tolerates_a_missing_file(tmp_path: Path) -> None:
    assert load_base_map(tmp_path) == {}
    assert load_base_map(None) == {}
