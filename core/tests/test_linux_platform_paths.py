from __future__ import annotations

from pathlib import Path

import desktop_backend
from lamtools_core.plugin_system import hooks as hook_config


def test_backend_default_data_dir_uses_xdg_data_home() -> None:
    assert desktop_backend._default_data_dir(
        platform="linux",
        environ={"XDG_DATA_HOME": "/tmp/xdg-data"},
        home=Path("/home/example"),
    ) == Path("/tmp/xdg-data/LamTools")


def test_backend_default_data_dir_uses_linux_standard_fallback() -> None:
    assert desktop_backend._default_data_dir(
        platform="linux",
        environ={},
        home=Path("/home/example"),
    ) == Path("/home/example/.local/share/LamTools")


def test_backend_default_data_dir_preserves_windows_appdata_behavior() -> None:
    assert desktop_backend._default_data_dir(
        platform="win32",
        environ={"APPDATA": "C:/Users/example/AppData/Roaming"},
        home=Path("C:/Users/example"),
    ) == Path("C:/Users/example/AppData/Roaming/Sunday")


def test_user_hooks_use_xdg_config_home_on_linux(monkeypatch) -> None:
    monkeypatch.delenv("LAMTOOLS_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg-config")
    monkeypatch.setattr(hook_config.sys, "platform", "linux")
    assert hook_config.default_user_hooks_path() == Path(
        "/tmp/xdg-config/LamTools/hooks.json"
    )


def test_user_hooks_keep_portable_home_precedence_on_linux(monkeypatch) -> None:
    monkeypatch.setenv("LAMTOOLS_HOME", "/portable/.lam")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg-config")
    monkeypatch.setattr(hook_config.sys, "platform", "linux")
    assert hook_config.default_user_hooks_path() == Path("/portable/.lam/hooks.json")


def test_backend_migrates_legacy_windows_data_dir(tmp_path) -> None:
    appdata = tmp_path / "Roaming"
    legacy = appdata / "LamCore"
    legacy.mkdir(parents=True)
    (legacy / "plugin-system.jsonc").write_text("{}", encoding="utf-8")
    environ = {"APPDATA": str(appdata)}

    target = desktop_backend._default_data_dir(
        platform="win32", environ=environ, home=tmp_path
    )
    assert target == appdata / "Sunday"
    assert desktop_backend._migrate_legacy_data_dir(
        target, platform="win32", environ=environ, home=tmp_path
    )
    assert (target / "plugin-system.jsonc").read_text(encoding="utf-8") == "{}"
    assert not legacy.exists()
    # Idempotent: a second start never merges or overwrites.
    assert not desktop_backend._migrate_legacy_data_dir(
        target, platform="win32", environ=environ, home=tmp_path
    )


def test_backend_retries_migration_when_target_is_an_empty_placeholder(tmp_path) -> None:
    appdata = tmp_path / "Roaming"
    legacy = appdata / "LamCore"
    legacy.mkdir(parents=True)
    (legacy / "plugin-system.jsonc").write_text("{}", encoding="utf-8")
    target = appdata / "Sunday"
    target.mkdir()
    environ = {"APPDATA": str(appdata)}

    assert desktop_backend._migrate_legacy_data_dir(
        target, platform="win32", environ=environ, home=tmp_path
    )
    assert (target / "plugin-system.jsonc").read_text(encoding="utf-8") == "{}"
