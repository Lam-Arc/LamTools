"""Tests for settings.jsonc (two-level namespaced app settings)."""
from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from lamtools_core.config.settings_store import delete_setting, get_setting, set_setting


def test_get_missing_namespace_returns_none(isolated_config_root: Path) -> None:
    assert get_setting("core.dreaming") is None
    assert not (isolated_config_root / "settings.jsonc").exists()


def test_set_and_get_round_trip(isolated_config_root: Path) -> None:
    set_setting("core.dreaming", {"enabled": True, "min_turns": 5})
    assert get_setting("core.dreaming") == {"enabled": True, "min_turns": 5}


def test_set_preserves_other_groups(isolated_config_root: Path) -> None:
    set_setting("core.dreaming", {"enabled": True})
    set_setting("core.imagegen", {"enabled": False, "model": "gpt-5"})
    set_setting("lamtools.modelRouting", {"routes": {"core": {"model_id": "m1"}}})

    data = __import__("json").loads((isolated_config_root / "settings.jsonc").read_text(encoding="utf-8"))
    assert data["core"]["dreaming"] == {"enabled": True}
    assert data["core"]["imagegen"] == {"enabled": False, "model": "gpt-5"}
    assert data["lamtools"]["modelRouting"]["routes"]["core"]["model_id"] == "m1"


def test_set_overwrites_namespace_value(isolated_config_root: Path) -> None:
    set_setting("core.dreaming", {"enabled": True, "min_turns": 3})
    set_setting("core.dreaming", {"enabled": False})
    assert get_setting("core.dreaming") == {"enabled": False}


def test_delete_removes_namespace(isolated_config_root: Path) -> None:
    set_setting("core.dreaming", {"enabled": True})
    assert delete_setting("core.dreaming") is True
    assert get_setting("core.dreaming") is None
    assert delete_setting("core.dreaming") is False


def test_delete_removes_group_when_last_key(isolated_config_root: Path) -> None:
    set_setting("core.dreaming", {"enabled": True})
    delete_setting("core.dreaming")
    data = __import__("json").loads((isolated_config_root / "settings.jsonc").read_text(encoding="utf-8"))
    assert "core" not in data or "dreaming" not in data["core"]


def test_jsonc_comments_and_trailing_commas_are_tolerated(isolated_config_root: Path) -> None:
    path = isolated_config_root / "settings.jsonc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{\n'
        '  "core": {\n'
        '    "dreaming": { "enabled": true, }, // trailing comma + comment\n'
        '  },\n'
        '}\n',
        encoding="utf-8",
    )
    assert get_setting("core.dreaming") == {"enabled": True}


@pytest.mark.parametrize("content", ["{ broken", "[]"])
def test_set_preserves_malformed_settings_before_recovery(
    isolated_config_root: Path,
    content: str,
) -> None:
    path = isolated_config_root / "settings.jsonc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    set_setting("core.dreaming", {"enabled": True})

    backups = list(path.parent.glob("settings.jsonc.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == content
    assert get_setting("core.dreaming") == {"enabled": True}


def test_concurrent_updates_preserve_every_namespace(isolated_config_root: Path) -> None:
    def write(index: int) -> None:
        set_setting(f"concurrent.value_{index}", index)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(40)))

    assert get_setting("concurrent") == {f"value_{index}": index for index in range(40)}


def test_failed_corrupt_backup_blocks_overwrite(
    isolated_config_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = isolated_config_root / "settings.jsonc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ broken", encoding="utf-8")

    def fail_rename(self: Path, target: Path) -> Path:
        raise PermissionError("backup denied")

    monkeypatch.setattr(Path, "rename", fail_rename)
    with pytest.raises(PermissionError, match="backup denied"):
        set_setting("core.dreaming", {"enabled": True})
    assert path.read_text(encoding="utf-8") == "{ broken"


@pytest.mark.parametrize("namespace", ["", ".key", "   "])
def test_empty_namespace_group_is_rejected(isolated_config_root: Path, namespace: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        set_setting(namespace, True)
    assert not (isolated_config_root / "settings.jsonc").exists()
