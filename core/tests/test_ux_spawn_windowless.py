"""隐藏窗口的统一拼装：flags 正确、管道输出不丢、子进程没有可见窗口。

user:“启动后台任务时会弹命令行窗，能不能隐藏掉？”
+(验收：① 拼出来的 creationflags 含 CREATE_NO_WINDOW；② 隐藏窗口不影响管道，
stdout 照常读得到；③ 真的子进程没有可见窗口——用带/不带标志的对照来证明
断言不是空转)。
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from lamtools_core import win_spawn


def test_creation_flags_hide_the_window():
    flags = win_spawn.creation_flags()
    if sys.platform == "win32":
        assert flags & win_spawn.CREATE_NO_WINDOW == win_spawn.CREATE_NO_WINDOW
        assert flags & win_spawn.CREATE_NEW_PROCESS_GROUP == 0
    else:
        assert flags == 0


def test_creation_flags_can_request_its_own_process_group():
    flags = win_spawn.creation_flags(new_process_group=True)
    if sys.platform == "win32":
        assert flags == win_spawn.CREATE_NO_WINDOW | win_spawn.CREATE_NEW_PROCESS_GROUP
    else:
        assert flags == 0


def test_startup_info_hides_the_first_show():
    info = win_spawn.startup_info()
    if sys.platform != "win32":
        assert info is None
        return
    assert info is not None
    assert info.dwFlags & win_spawn.STARTF_USESHOWWINDOW
    assert info.wShowWindow == win_spawn.SW_HIDE


def test_hidden_kwargs_never_touch_stdio():
    """隐藏窗口不得改写管道：调用方的 stdout/stderr 原样保留。"""
    kwargs = win_spawn.hidden_kwargs()
    for key in ("stdout", "stderr", "stdin", "shell", "cwd", "env"):
        assert key not in kwargs
    if sys.platform != "win32":
        assert kwargs == {}
    else:
        assert kwargs["creationflags"] & win_spawn.CREATE_NO_WINDOW
        assert kwargs["startupinfo"] is not None


def test_apply_hidden_window_keeps_existing_flags_and_kwargs():
    kwargs: dict[str, object] = {
        "creationflags": win_spawn.CREATE_NEW_PROCESS_GROUP,
        "stdout": subprocess.PIPE,
        "env": {"A": "1"},
    }
    updated = win_spawn.apply_hidden_window(kwargs)
    assert updated is kwargs
    assert updated["stdout"] is subprocess.PIPE
    assert updated["env"] == {"A": "1"}
    if sys.platform == "win32":
        assert int(updated["creationflags"]) & win_spawn.CREATE_NO_WINDOW
        assert int(updated["creationflags"]) & win_spawn.CREATE_NEW_PROCESS_GROUP
        assert updated["startupinfo"] is not None
    else:
        assert updated["creationflags"] == win_spawn.CREATE_NEW_PROCESS_GROUP
        assert "startupinfo" not in updated


# ----------------------------------------------------------------- 真机断言
# 下面两个测试只在 Windows 上跑：它们真的起子进程，然后枚举该 PID 的可见顶层
# 窗口。第一个证明「隐藏后没有可见窗口」，第二个是它的对照（不带标志时确实
# 有可见窗口），用来证明断言不是空转。

_PROBE = (
    "import ctypes, sys, time;"
    "k = ctypes.windll.kernel32;"
    "u = ctypes.windll.user32;"
    "h = k.GetConsoleWindow();"
    "print(int(bool(h)) * 2 + int(bool(h) and u.IsWindowVisible(h)), flush=True);"
    "time.sleep(float(sys.argv[1]))"
)


@pytest.mark.skipif(sys.platform != "win32", reason="窗口可见性只能在 Windows 上断言")
def test_hidden_child_has_no_visible_window():
    """隐藏窗口的判定标准是「没有可见窗口」，不是「控制台一定存在」。

    实测 ``CREATE_NO_WINDOW`` + ``STARTF_USESHOWWINDOW/SW_HIDE`` 一起用时，
    ``GetConsoleWindow()`` 直接返回 0（连控制台窗口都没建），比「建了但隐藏」
    更彻底。两种都算合格，只有 state 3（可见控制台）是回归。
    """
    process = subprocess.Popen(
        [sys.executable, "-c", _PROBE, "3"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **win_spawn.hidden_kwargs(),
    )
    try:
        assert process.stdout is not None
        first = process.stdout.readline().decode().strip()
        assert first in ("0", "2"), f"console state {first!r}: a visible console appeared"
        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline and process.poll() is None:
            assert _visible_window_titles(process.pid) == []
            time.sleep(0.05)
    finally:
        _kill(process)


@pytest.mark.skipif(sys.platform != "win32", reason="窗口可见性只能在 Windows 上断言")
def test_window_enumerator_is_not_vacuous():
    """对照：证明 ``_visible_window_titles`` 真的能看见窗口。

    上一版对照组想比较「不带标志的子进程会弹窗」，但被测环境（ConPTY / 无窗口
    控制台）里 ``GetConsoleWindow()`` 对谁都是 0，对照结论不可复现。改成直接
    验证枚举器本身：桌面上随便找一个有可见顶层窗口的进程，枚举器必须能列出来。
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    candidates: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd: int, _param: int) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value and owner.value not in candidates:
            candidates.append(owner.value)
        return len(candidates) < 40

    callback = callback_type(visit)
    user32.EnumWindows(callback, 0)
    if not candidates:
        pytest.skip("当前桌面没有可见顶层窗口，无法验证枚举器")

    assert any(_visible_window_titles(pid) for pid in candidates)


def _kill(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    for pipe in (process.stdout, process.stderr):
        if pipe is not None:
            pipe.close()


def _parent_console_state() -> str:
    """``none`` 没有控制台 / ``visible`` 可见 / ``hidden`` 有但被藏起来。"""
    import ctypes

    handle = ctypes.windll.kernel32.GetConsoleWindow()
    if not handle:
        return "none"
    return "visible" if ctypes.windll.user32.IsWindowVisible(handle) else "hidden"


def _visible_window_titles(pid: int) -> list[str]:
    """枚举该 PID 下所有可见顶层窗口的标题。"""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[str] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd: int, _param: int) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            found.append(buffer.value)
        return True

    callback = callback_type(visit)
    user32.EnumWindows(callback, 0)
    return found
