"""Step 6 acceptance tests: engine, config, updates and local packaging."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from lamtools_core.plugin_system import CapabilityError, PluginHost
from lamtools_core.plugin_system.engine import (
    PluginEngine,
    check_engine,
    host_engine_info,
    read_engine,
    satisfies,
)
from lamtools_core.plugin_system.manifest import load_manifest
from lamtools_core.plugin_system.settings import read_config


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


def make_host(tmp_path: Path, root: Path) -> PluginHost:
    return PluginHost(roots=[root], state_path=tmp_path / "plugin-system.jsonc")


def test_engine_defaults_to_python(tmp_path: Path) -> None:
    directory = make_plugin(tmp_path / "plugins", "plain")

    engine = read_engine(load_manifest(directory / "plugin.json"))

    assert engine.runtime == "python"
    assert engine.python == ""
    assert engine.app == ""


def test_engine_parses_constraints(tmp_path: Path) -> None:
    directory = make_plugin(
        tmp_path / "plugins",
        "engine",
        manifest={
            "engine": {
                "runtime": "python",
                "python": ">=3.14,<3.15",
                "app": ">=0.4",
                "platform": "windows-x64",
            }
        },
    )

    engine = read_engine(load_manifest(directory / "plugin.json"))

    assert engine.runtime == "python"
    assert engine.python == ">=3.14,<3.15"
    assert engine.app == ">=0.4"
    assert engine.platform == "windows-x64"


def test_unknown_runtime_is_rejected(tmp_path: Path) -> None:
    directory = make_plugin(
        tmp_path / "plugins",
        "bad",
        manifest={"engine": {"runtime": "rust"}},
    )

    with pytest.raises(CapabilityError, match="runtime"):
        read_engine(load_manifest(directory / "plugin.json"))


@pytest.mark.parametrize(
    ("version", "constraint", "expected"),
    [
        ("3.14.0", ">=3.14,<3.15", True),
        ("3.15.0", ">=3.14,<3.15", False),
        ("0.3.22", ">=0.4", False),
        ("0.4.0", ">=0.4", True),
        ("1.2.3", "", True),
    ],
)
def test_version_constraints(version: str, constraint: str, expected: bool) -> None:
    assert satisfies(version, constraint) is expected


def test_check_engine_reports_each_mismatch() -> None:
    problems = check_engine(
        PluginEngine(runtime="python", python=">=3.15", platform="linux-x64"),
        host={"python": "3.14.0", "app": "0.4.0", "platform": "windows-x64"},
    )

    assert len(problems) == 2
    assert any("python" in item for item in problems)
    assert any("platform" in item for item in problems)


def test_host_engine_info_has_the_three_fields() -> None:
    info = host_engine_info()

    assert set(info) == {"python", "app", "platform"}
    assert info["python"]
    assert info["app"]


def test_config_parses_schema_and_panel(tmp_path: Path) -> None:
    directory = make_plugin(
        tmp_path / "plugins",
        "config",
        manifest={
            "config": {
                "schema": "./config/schema.jsonc",
                "panel": "./ui/panel.js",
            }
        },
        files={
            "config/schema.jsonc": '{"type": "object"}',
            "ui/panel.js": "export {}",
        },
    )

    config = read_config(load_manifest(directory / "plugin.json"))

    assert config.schema is not None and config.schema.name == "schema.jsonc"
    assert config.panel is not None and config.panel.name == "panel.js"


def test_config_paths_must_stay_inside_the_root(tmp_path: Path) -> None:
    directory = make_plugin(
        tmp_path / "plugins",
        "escape",
        manifest={"config": {"schema": "./../outside.jsonc"}},
    )

    with pytest.raises(CapabilityError, match="outside"):
        read_config(load_manifest(directory / "plugin.json"))


def test_update_from_directory_preserves_data(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    installed = make_plugin(
        root,
        "diary",
        files={"main.py": "version = 1\n", "data/entry.txt": "kept"},
    )
    host = make_host(tmp_path, root)
    staging = tmp_path / "staging" / "diary"
    make_plugin(
        tmp_path / "staging",
        "diary",
        files={"main.py": "version = 2\n"},
    )

    host.update_from_directory(staging)

    assert (installed / "main.py").read_text(encoding="utf-8") == "version = 2\n"
    assert (installed / "data" / "entry.txt").read_text(encoding="utf-8") == "kept"


def test_update_rejects_a_mismatched_name(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "diary")
    host = make_host(tmp_path, root)
    staging = tmp_path / "staging" / "other"
    make_plugin(tmp_path / "staging", "other")

    with pytest.raises(ValueError, match="name"):
        host.update_from_directory(staging)


def test_install_from_zip_extracts_a_single_root(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    archive = tmp_path / "plugin.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("pkg/plugin.json", json.dumps({"name": "zipped", "version": "1.0.0"}))
        bundle.writestr("pkg/main.py", "value = 1\n")
    host = make_host(tmp_path, root)

    installed = host.install_from_zip(archive)

    assert installed == (root / "zipped").resolve()
    assert (installed / "main.py").is_file()
    assert [item.name for item in host.discover()] == ["zipped"]


def test_install_from_zip_refuses_path_traversal(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("pkg/plugin.json", json.dumps({"name": "evil", "version": "1.0.0"}))
        bundle.writestr("../escaped.txt", "boom")
    host = make_host(tmp_path, root)

    with pytest.raises(ValueError, match="traversal"):
        host.install_from_zip(archive)


def test_install_rejects_an_unmet_engine(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    staging = make_plugin(
        tmp_path / "staging",
        "future",
        manifest={"engine": {"python": ">=3.99"}},
    )
    host = make_host(tmp_path, root)

    with pytest.raises(ValueError, match="python"):
        host.install_from_directory(staging)

    assert not (root / "future").exists()


def test_logs_directory_is_created_on_demand(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "diary")
    host = make_host(tmp_path, root)

    logs = host.logs_dir("diary")

    assert logs == (root / "diary" / "data" / "logs").resolve()
    assert logs.is_dir()
