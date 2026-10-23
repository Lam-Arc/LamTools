"""Step 4b acceptance tests: overrides are loaded before the host imports."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from lamtools_boot.import_hook import remove_overrides
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
            {"name": name, "version": "1.0.0", **({"overrides": overrides} if overrides is not None else {})}
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

    mapping, errors = load_boot_overrides(
        roots=[root], state_path=tmp_path / "plugin-system.jsonc"
    )

    assert errors == []
    assert mapping["lamtools_core.prompt"].name == "prompt.py"


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

    mapping, errors = load_boot_overrides(roots=[root], state_path=state)

    assert mapping == {}
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

    mapping, errors = load_boot_overrides(
        roots=[root], state_path=tmp_path / "plugin-system.jsonc"
    )

    assert mapping["lamtools_core.prompt"].read_text(encoding="utf-8").endswith("'first'\n")
    assert len(errors) == 1
    assert "already overridden" in errors[0]


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

    mapping, errors = load_boot_overrides(
        roots=[root], state_path=tmp_path / "plugin-system.jsonc"
    )

    assert mapping == {}
    assert len(errors) == 2


def test_boot_loader_honours_safe_mode(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "demo",
        overrides={"lamtools_core.prompt": "./overrides/prompt.py"},
        files={"overrides/prompt.py": "value = 'plugin'\n"},
    )

    mapping, errors = load_boot_overrides(
        roots=[root],
        state_path=tmp_path / "plugin-system.jsonc",
        environ={"LAMTOOLS_SAFE_MODE": "1"},
    )

    assert mapping == {}
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
