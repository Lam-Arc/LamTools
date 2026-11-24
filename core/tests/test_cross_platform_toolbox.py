"""Linux 容器（手机）里不能因为导入 Windows 专属能力而让整轮装配失败。

user:“运行失败 module 'ctypes' has no attribute 'WINFUNCTYPE'”+(桌面操作依赖 user32，
在 Linux 上连导入都会抛异常；工具清单必须按平台裁剪，和 android_use 一样)。
"""
from __future__ import annotations

import ctypes
import sys


def _names() -> list[str]:
    from lamtools_core.tool import default_toolbox

    return [spec.name for spec in default_toolbox.default_core_tool_specs()]


def test_computer_use_is_hidden_when_the_host_cannot_drive_a_windows_desktop(monkeypatch):
    from lamtools_core.tool import default_toolbox

    monkeypatch.setattr(default_toolbox, "windows_desktop_available", lambda: False)
    assert "computer_use" not in _names()


def test_computer_use_stays_on_windows(monkeypatch):
    from lamtools_core.tool import default_toolbox

    monkeypatch.setattr(default_toolbox, "windows_desktop_available", lambda: True)
    assert "computer_use" in _names()


def test_platform_probe_follows_the_interpreter():
    from lamtools_core.tool import default_toolbox

    assert default_toolbox.windows_desktop_available() is (sys.platform == "win32")


def test_win32_module_exposes_a_callback_type_on_any_platform():
    """导入期不许依赖 ctypes.WINFUNCTYPE 是否存在（Linux 上没有这个属性）。"""
    from lamtools_core.computer_use import win32

    assert callable(win32.WINFUNCTYPE)
    if hasattr(ctypes, "WINFUNCTYPE"):
        assert win32.WINFUNCTYPE is ctypes.WINFUNCTYPE
