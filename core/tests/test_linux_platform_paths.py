from __future__ import annotations

from pathlib import Path

import desktop_backend
from lamtools_core.plugins import hook_config


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
    ) == Path("C:/Users/example/AppData/Roaming/LamCore")


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
