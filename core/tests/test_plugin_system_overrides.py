"""Step 4 acceptance tests: module overrides happen before the host imports.

user:“允许插件去禁用我们的某一个文件，并且自己提供上去”+覆盖只在启动时
生效；查找器只拦截覆盖表里的模块，`from 模块 import 函数` 也要拿到插件实现。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from lamtools_boot.import_hook import install_overrides, remove_overrides
from lamtools_core.plugin_system import CapabilityError
from lamtools_core.plugin_system.manifest import load_manifest
from lamtools_core.plugin_system.overrides import assemble_overrides, read_overrides


def make_plugin(
    root: Path,
    name: str,
    *,
    overrides: dict | None = None,
    files: dict[str, str] | None = None,
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "plugin.json").write_text(
        json.dumps(
            {"name": name, "version": "1.0.0", **({"overrides": overrides} if overrides is not None else {})}
        ),
        encoding="utf-8",
    )
    for relative, content in (files or {}).items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return directory / "plugin.json"


def test_overrides_are_parsed(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "demo",
        overrides={"lamtools_core.prompt": "./overrides/prompt.py"},
        files={"overrides/prompt.py": "def build():\n    return 'plugin'\n"},
    )

    specs = read_overrides(load_manifest(manifest_path))

    assert [spec.target for spec in specs] == ["lamtools_core.prompt"]
    assert specs[0].plugin == "demo"
    assert specs[0].path.name == "prompt.py"


def test_missing_overrides_is_empty(tmp_path: Path) -> None:
    manifest_path = make_plugin(tmp_path, "plain")

    assert read_overrides(load_manifest(manifest_path)) == []


def test_target_must_be_a_host_module(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "bad",
        overrides={"os.path": "./overrides/path.py"},
        files={"overrides/path.py": "value = 1\n"},
    )

    with pytest.raises(CapabilityError, match="lamtools_core"):
        read_overrides(load_manifest(manifest_path))


def test_override_file_must_stay_inside_the_plugin_root(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "escape",
        overrides={"lamtools_core.prompt": "./../outside.py"},
    )

    with pytest.raises(CapabilityError, match="outside"):
        read_overrides(load_manifest(manifest_path))


def test_override_file_must_exist_and_be_python(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "missing",
        overrides={"lamtools_core.prompt": "./overrides/nope.py"},
    )

    with pytest.raises(CapabilityError, match="missing"):
        read_overrides(load_manifest(manifest_path))

    text_path = make_plugin(
        tmp_path,
        "text",
        overrides={"lamtools_core.prompt": "./overrides/prompt.txt"},
        files={"overrides/prompt.txt": "x"},
    )
    with pytest.raises(CapabilityError, match="\\.py"):
        read_overrides(load_manifest(text_path))


def test_two_plugins_targeting_the_same_module_conflict(tmp_path: Path) -> None:
    first = make_plugin(
        tmp_path,
        "first",
        overrides={"lamtools_core.prompt": "./overrides/prompt.py"},
        files={"overrides/prompt.py": "value = 'first'\n"},
    )
    second = make_plugin(
        tmp_path,
        "second",
        overrides={"lamtools_core.prompt": "./overrides/prompt.py"},
        files={"overrides/prompt.py": "value = 'second'\n"},
    )

    assembly = assemble_overrides([load_manifest(first), load_manifest(second)])

    assert assembly.overrides["lamtools_core.prompt"].plugin == "first"
    assert assembly.errors[0]["plugin"] == "second"
    assert "already overridden" in assembly.errors[0]["error"]


def test_safe_mode_skips_every_override(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "demo",
        overrides={"lamtools_core.prompt": "./overrides/prompt.py"},
        files={"overrides/prompt.py": "value = 'plugin'\n"},
    )

    assembly = assemble_overrides([load_manifest(manifest_path)], safe_mode=True)

    assert assembly.overrides == {}
    assert assembly.skipped is True


def test_disabled_plugins_are_not_overridden(tmp_path: Path) -> None:
    manifest_path = make_plugin(
        tmp_path,
        "sleeping",
        overrides={"lamtools_core.prompt": "./overrides/prompt.py"},
        files={"overrides/prompt.py": "value = 'plugin'\n"},
    )

    assembly = assemble_overrides([load_manifest(manifest_path, enabled=False)])

    assert assembly.overrides == {}


def _make_package(tmp_path: Path) -> tuple[Path, Path]:
    package = tmp_path / "override_demo_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "original.py").write_text("value = 'original'\n", encoding="utf-8")
    replacement = tmp_path / "replacement.py"
    replacement.write_text("value = 'replaced'\n", encoding="utf-8")
    return package, replacement


def test_finder_replaces_a_module_for_from_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _package, replacement = _make_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("override_demo_pkg.original", None)
    sys.modules.pop("override_demo_pkg", None)

    finder = install_overrides({"override_demo_pkg.original": replacement})
    try:
        assert sys.meta_path[0] is finder
        from override_demo_pkg.original import value as overridden

        assert overridden == "replaced"
    finally:
        remove_overrides(finder)
        sys.modules.pop("override_demo_pkg.original", None)
        sys.modules.pop("override_demo_pkg", None)


def test_unlisted_modules_load_normally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _package, _replacement = _make_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("override_demo_pkg.original", None)
    sys.modules.pop("override_demo_pkg", None)

    finder = install_overrides({})
    try:
        from override_demo_pkg.original import value as original

        assert original == "original"
    finally:
        remove_overrides(finder)
        sys.modules.pop("override_demo_pkg.original", None)
        sys.modules.pop("override_demo_pkg", None)


def test_remove_overrides_is_idempotent() -> None:
    finder = install_overrides({})
    remove_overrides(finder)
    remove_overrides(finder)

    assert finder not in sys.meta_path
