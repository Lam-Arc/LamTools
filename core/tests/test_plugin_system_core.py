"""Step 1 acceptance tests: manifest, discovery, state and uninstall.

user:“开工前先提交基线并备注清楚”+先按第 1 步“清单与装配内核”落验收测试，
再实现；一个只有名字和版本的文件夹应当能被装上、禁用、卸载。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core.plugin_system import PluginHost, PluginManifestError


def write_plugin(
    directory: Path,
    *,
    manifest: dict | None = None,
    raw_text: str | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "plugin.json").write_text(
        raw_text if raw_text is not None else json.dumps(manifest or {}, ensure_ascii=False),
        encoding="utf-8",
    )
    return directory


def make_host(tmp_path: Path, *roots: Path) -> PluginHost:
    return PluginHost(roots=list(roots), state_path=tmp_path / "plugins.jsonc")


def test_minimal_manifest_is_accepted(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    write_plugin(root / "hello", manifest={"name": "hello", "version": "0.1.0"})
    host = make_host(tmp_path, root)

    plugins = host.discover()

    assert [item.name for item in plugins] == ["hello"]
    assert plugins[0].version == "0.1.0"
    assert plugins[0].enabled is True
    assert plugins[0].root == (root / "hello").resolve()
    assert host.errors == []


def test_unknown_fields_are_kept_for_later_steps(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    write_plugin(
        root / "diary",
        manifest={
            "name": "diary",
            "version": "1.0.0",
            "scope": "mode",
            "tools": ["./tools.jsonc"],
            "ui": {"styles": ["./style.css"]},
        },
    )
    host = make_host(tmp_path, root)

    manifest = host.discover()[0]

    assert manifest.scope == "mode"
    assert manifest.raw["ui"] == {"styles": ["./style.css"]}


def test_missing_name_is_reported_without_hiding_others(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    write_plugin(root / "ok", manifest={"name": "ok", "version": "1.0.0"})
    write_plugin(root / "broken", raw_text='{"version": "1.0.0"}')
    host = make_host(tmp_path, root)

    plugins = host.discover()

    assert [item.name for item in plugins] == ["ok"]
    assert host.errors[0]["name"] == "broken"
    assert "name" in host.errors[0]["error"]


def test_missing_version_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    write_plugin(root / "noversion", manifest={"name": "noversion"})
    host = make_host(tmp_path, root)

    assert host.discover() == []
    assert "version" in host.errors[0]["error"]


@pytest.mark.parametrize("bad_name", ["../evil", "a/b", "..", ""])
def test_invalid_names_are_rejected(tmp_path: Path, bad_name: str) -> None:
    root = tmp_path / "plugins"
    directory = root / "candidate"
    write_plugin(directory, manifest={"name": bad_name, "version": "1.0.0"})
    host = make_host(tmp_path, root)

    assert host.discover() == []
    assert host.errors


def test_invalid_scope_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    write_plugin(root / "badscope", manifest={"name": "badscope", "version": "1.0.0", "scope": "everywhere"})
    host = make_host(tmp_path, root)

    assert host.discover() == []
    assert "scope" in host.errors[0]["error"]


def test_duplicate_name_across_roots_is_a_conflict(tmp_path: Path) -> None:
    first = tmp_path / "user"
    second = tmp_path / "project"
    write_plugin(first / "same", manifest={"name": "same", "version": "1.0.0"})
    write_plugin(second / "same", manifest={"name": "same", "version": "2.0.0"})
    host = make_host(tmp_path, first, second)

    plugins = host.discover()

    assert [item.version for item in plugins] == ["1.0.0"]
    assert host.errors[0]["name"] == "same"
    assert "duplicate" in host.errors[0]["error"]


def test_disable_persists_and_keeps_files(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    directory = write_plugin(root / "hello", manifest={"name": "hello", "version": "0.1.0"})
    host = make_host(tmp_path, root)
    host.discover()

    host.disable("hello")

    assert host.discover()[0].enabled is False
    assert (directory / "plugin.json").is_file()
    assert make_host(tmp_path, root).discover()[0].enabled is False

    host.enable("hello")

    assert make_host(tmp_path, root).discover()[0].enabled is True


def test_uninstall_keeps_data_when_asked(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    directory = write_plugin(root / "diary", manifest={"name": "diary", "version": "1.0.0"})
    (directory / "data").mkdir()
    (directory / "data" / "entry.txt").write_text("kept", encoding="utf-8")
    host = make_host(tmp_path, root)
    host.discover()

    host.uninstall("diary", keep_data=True)

    assert not (directory / "plugin.json").exists()
    assert (directory / "data" / "entry.txt").read_text(encoding="utf-8") == "kept"
    assert host.discover() == []


def test_uninstall_removes_directory_when_asked(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    directory = write_plugin(root / "gone", manifest={"name": "gone", "version": "1.0.0"})
    host = make_host(tmp_path, root)
    host.discover()

    host.uninstall("gone", keep_data=False)

    assert not directory.exists()
    assert host.discover() == []


def test_corrupt_state_file_does_not_crash(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    write_plugin(root / "hello", manifest={"name": "hello", "version": "0.1.0"})
    (tmp_path / "plugins.jsonc").write_text("{not json", encoding="utf-8")
    host = make_host(tmp_path, root)

    assert [item.name for item in host.discover()] == ["hello"]
    assert host.discover()[0].enabled is True


def test_install_from_directory_validates_and_copies(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    staging = tmp_path / "staging" / "hello"
    write_plugin(staging, manifest={"name": "hello", "version": "0.1.0"})
    (staging / "main.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    host = make_host(tmp_path, root)

    installed = host.install_from_directory(staging)

    assert installed == (root / "hello").resolve()
    assert (installed / "main.py").is_file()
    assert [item.name for item in host.discover()] == ["hello"]

    with pytest.raises(ValueError):
        host.install_from_directory(staging)


def test_install_rejects_a_plugin_without_a_valid_manifest(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    staging = tmp_path / "staging" / "broken"
    write_plugin(staging, manifest={"version": "1.0.0"})
    host = make_host(tmp_path, root)

    with pytest.raises(PluginManifestError):
        host.install_from_directory(staging)

    assert not (root / "broken").exists()
