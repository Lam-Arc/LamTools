"""Tests for settings.jsonc (two-level namespaced app settings)."""
from __future__ import annotations

from pathlib import Path

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
