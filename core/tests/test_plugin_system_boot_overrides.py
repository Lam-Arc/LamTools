"""Step 4b acceptance tests: overrides load before import, modules and functions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from lamtools_boot.import_hook import OverrideTable, install_overrides, remove_overrides
from lamtools_boot.overrides import apply_boot_overrides, load_boot_overrides


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
            {
                "name": name,
                "version": "1.0.0",
                **({"overrides": overrides} if overrides is not None else {}),
            }
        ),
        encoding="utf-8",
    )
    for relative, content in (files or {}).items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return directory


def write_state(path: Path, name: str, enabled: bool) -> None:
    path.write_text(
        json.dumps({"plugins": {name: {"enabled": enabled}}}), encoding="utf-8"
    )


def test_boot_loader_reads_enabled_overrides(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "demo",
        overrides={"lamtools_core.prompt": "./overrides/prompt.py"},
        files={"overrides/prompt.py": "value = 'plugin'\n"},
    )

    table, errors = load_boot_overrides(
        roots=[root], state_path=tmp_path / "plugin-system.jsonc"
    )

    assert errors == []
    assert table.modules["lamtools_core.prompt"].name == "prompt.py"


def test_boot_loader_reads_function_patches(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "demo",
        overrides={
            "lamtools_core.prompt:build_system_prompt": "./overrides/patch.py"
        },
        files={"overrides/patch.py": "def build_system_prompt():\n    return 'x'\n"},
    )

    table, errors = load_boot_overrides(
        roots=[root], state_path=tmp_path / "plugin-system.jsonc"
    )

    assert errors == []
    assert table.modules == {}
    assert (
        table.patches["lamtools_core.prompt"]["build_system_prompt"].name
        == "patch.py"
    )


def test_boot_loader_skips_a_disabled_plugin(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "demo",
        overrides={"lamtools_core.prompt": "./overrides/prompt.py"},
        files={"overrides/prompt.py": "value = 'plugin'\n"},
    )
    state = tmp_path / "plugin-system.jsonc"
    write_state(state, "demo", False)

    table, errors = load_boot_overrides(roots=[root], state_path=state)

    assert table.is_empty() is True
    assert errors == []


def test_boot_loader_reports_a_duplicate_target(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    for name in ("first", "second"):
        make_plugin(
            root,
            name,
            overrides={"lamtools_core.prompt": "./overrides/prompt.py"},
            files={"overrides/prompt.py": f"value = '{name}'\n"},
        )

    table, errors = load_boot_overrides(
        roots=[root], state_path=tmp_path / "plugin-system.jsonc"
    )

    assert table.modules["lamtools_core.prompt"].read_text(
        encoding="utf-8"
    ).endswith("'first'\n")
    assert len(errors) == 1
    assert "already overridden" in errors[0]


def test_boot_loader_reports_module_and_patch_conflict(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "demo",
        overrides={
            "lamtools_core.prompt": "./overrides/prompt.py",
            "lamtools_core.prompt:build_system_prompt": "./overrides/patch.py",
        },
        files={
            "overrides/prompt.py": "value = 'module'\n",
            "overrides/patch.py": "def build_system_prompt():\n    return 'x'\n",
        },
    )

    table, errors = load_boot_overrides(
        roots=[root], state_path=tmp_path / "plugin-system.jsonc"
    )

    assert "lamtools_core.prompt" in table.modules
    assert table.patches == {}
    assert len(errors) == 1
    assert "skipped" in errors[0]


def test_boot_loader_refuses_an_escape_and_a_foreign_target(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "demo",
        overrides={
            "lamtools_core.prompt": "./../outside.py",
            "os.path": "./overrides/path.py",
        },
        files={"overrides/path.py": "value = 1\n"},
    )

    table, errors = load_boot_overrides(
        roots=[root], state_path=tmp_path / "plugin-system.jsonc"
    )

    assert table.is_empty() is True
    assert len(errors) == 2


def test_boot_loader_honours_safe_mode(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "demo",
        overrides={"lamtools_core.prompt": "./overrides/prompt.py"},
        files={"overrides/prompt.py": "value = 'plugin'\n"},
    )

    table, errors = load_boot_overrides(
        roots=[root],
        state_path=tmp_path / "plugin-system.jsonc",
        environ={"LAMTOOLS_SAFE_MODE": "1"},
    )

    assert table.is_empty() is True
    assert errors == []


def test_apply_boot_overrides_installs_the_finder(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "demo",
        overrides={"lamtools_core.prompt": "./overrides/prompt.py"},
        files={"overrides/prompt.py": "value = 'plugin'\n"},
    )

    finder = apply_boot_overrides(
        roots=[root], state_path=tmp_path / "plugin-system.jsonc"
    )

    assert finder is not None
    try:
        assert sys.meta_path[0] is finder
    finally:
        remove_overrides(finder)


def make_patch_package(tmp_path: Path) -> tuple[Path, Path]:
    package = tmp_path / "patch_demo_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "module.py").write_text(
        "def greet():\n    return 'original'\n"
        "\n"
        "def count():\n    return 1\n",
        encoding="utf-8",
    )
    patch = tmp_path / "patch.py"
    patch.write_text(
        "def greet():\n    return original() + '!'\n"
        "\n"
        "def count():\n    return original() + 1\n",
        encoding="utf-8",
    )
    return package, patch


def test_function_patch_applies_to_from_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _package, patch = make_patch_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("patch_demo_pkg.module", None)
    sys.modules.pop("patch_demo_pkg", None)

    finder = install_overrides(
        OverrideTable(patches={"patch_demo_pkg.module": {"greet": patch}})
    )
    try:
        from patch_demo_pkg.module import greet

        assert greet() == "original!"
    finally:
        remove_overrides(finder)
        sys.modules.pop("patch_demo_pkg.module", None)
        sys.modules.pop("patch_demo_pkg", None)


def test_two_functions_in_one_module_can_be_patched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _package, patch = make_patch_package(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("patch_demo_pkg.module", None)
    sys.modules.pop("patch_demo_pkg", None)

    finder = install_overrides(
        OverrideTable(
            patches={"patch_demo_pkg.module": {"greet": patch, "count": patch}}
        )
    )
    try:
        from patch_demo_pkg.module import count, greet

        assert greet() == "original!"
        assert count() == 2
    finally:
        remove_overrides(finder)
        sys.modules.pop("patch_demo_pkg.module", None)
        sys.modules.pop("patch_demo_pkg", None)


def test_function_patch_preserves_module_file_and_resources(tmp_path, monkeypatch):
    import importlib.resources

    package = tmp_path / "patch_resources_example"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from pathlib import Path\n"
        "def greet(): return Path(__file__).with_name('message.txt').read_text()\n",
        encoding="utf-8",
    )
    (package / "message.txt").write_text("hello", encoding="utf-8")
    patch = tmp_path / "patch.py"
    patch.write_text("def greet(): return original().upper()\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    finder = install_overrides(
        OverrideTable(patches={"patch_resources_example": {"greet": patch}})
    )
    try:
        import patch_resources_example

        assert patch_resources_example.greet() == "HELLO"
        assert importlib.resources.files(patch_resources_example).joinpath("message.txt").read_text() == "hello"
    finally:
        remove_overrides(finder)
        sys.modules.pop("patch_resources_example", None)
