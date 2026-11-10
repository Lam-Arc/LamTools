"""Windows 桌面能力：显示器、窗口、截图、输入注入、前台激活、用户接管检测。

所有坐标一律使用物理像素和虚拟桌面坐标。这台机器 150% 缩放，逻辑坐标一旦
混进来，点击必然偏移，所以这里不提供任何逻辑坐标接口。

user:“查一下 computer use 功能怎么做”+(Agent 要像人一样看屏幕、动鼠标键盘，
所以能力层只做无状态的系统调用，任务状态与安全判断留给 session)。
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes as w
from dataclasses import dataclass

IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:  # 非 Windows 上导入不炸，调用时由上层报平台错误
    user32 = gdi32 = kernel32 = None

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
BI_RGB = 0

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
DWMWA_CLOAKED = 14

SW_RESTORE = 9
SW_SHOW = 5

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_EXTENDEDKEY = 0x0001

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010

VK_MENU = 0x12

# 后台输入：直接向目标窗口投递消息，不动真实光标。
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_ACTIVATE = 0x0006
WM_SETFOCUS = 0x0007
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
MK_MBUTTON = 0x0010
PW_RENDERFULLCONTENT = 0x00000002

# 组合键里可用的按键名到虚拟键码。大小写不敏感。
VK_NAMES: dict[str, int] = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "menu": 0x12,
    "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C, "cmd": 0x5B,
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "backspace": 0x08, "back": 0x08, "delete": 0x2E, "del": 0x2E,
    "insert": 0x2D, "ins": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "capslock": 0x14, "printscreen": 0x2C, "pause": 0x13,
    "minus": 0xBD, "equal": 0xBB, "plus": 0xBB,
    "comma": 0xBC, "period": 0xBE, "dot": 0xBE, "slash": 0xBF,
    "backslash": 0xDC, "semicolon": 0xBA, "quote": 0xDE,
    "leftbracket": 0xDB, "rightbracket": 0xDD, "backtick": 0xC0,
}
for _i in range(1, 13):
    VK_NAMES[f"f{_i}"] = 0x6F + _i
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK_NAMES[_c] = ord(_c.upper())
for _d in "0123456789":
    VK_NAMES[_d] = ord(_d)


# ---------------------------------------------------------------------------
# 结构体与 API 声明
# ---------------------------------------------------------------------------

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", w.LONG), ("dy", w.LONG), ("mouseData", w.DWORD),
        ("dwFlags", w.DWORD), ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD),
        ("time", w.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", w.DWORD), ("wParamL", w.WORD), ("wParamH", w.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", w.DWORD), ("u", _INPUTUNION)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG),
        ("biPlanes", w.WORD), ("biBitCount", w.WORD), ("biCompression", w.DWORD),
        ("biSizeImage", w.DWORD), ("biXPelsPerMeter", w.LONG),
        ("biYPelsPerMeter", w.LONG), ("biClrUsed", w.DWORD),
        ("biClrImportant", w.DWORD),
    ]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD), ("rcMonitor", w.RECT), ("rcWork", w.RECT),
        ("dwFlags", w.DWORD), ("szDevice", w.WCHAR * 32),
    ]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", w.UINT), ("dwTime", w.DWORD)]


if IS_WINDOWS:
    user32.SetProcessDPIAware()

    # user:“你看，很明显，你这个截图就没有截全，你只截了左上半部分”+
    # (后端进程可能被宿主设成 DPI 不感知，窗口尺寸会按逻辑像素返回，
    #  PrintWindow 却按物理像素绘制，结果只画出左上角一块。每个线程入口
    #  都切到 per-monitor v2，保证尺寸和截图都按物理像素算。)
    user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
    user32.GetCursorPos.restype = w.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = w.BOOL
    user32.GetForegroundWindow.restype = w.HWND
    user32.GetForegroundWindow.argtypes = []
    user32.WindowFromPoint.argtypes = [w.POINT]
    user32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user32.PostMessageW.restype = w.BOOL
    user32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.ScreenToClient.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
    user32.ScreenToClient.restype = w.BOOL
    user32.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
    user32.ClientToScreen.restype = w.BOOL
    user32.PrintWindow.argtypes = [w.HWND, w.HDC, w.UINT]
    user32.PrintWindow.restype = w.BOOL
    user32.GetWindowDC.argtypes = [w.HWND]
    user32.GetWindowDC.restype = w.HDC
    user32.WindowFromPoint.restype = w.HWND
    user32.GetAncestor.argtypes = [w.HWND, w.UINT]
    user32.GetAncestor.restype = w.HWND
    user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    user32.GetWindowThreadProcessId.restype = w.DWORD
    user32.AttachThreadInput.argtypes = [w.DWORD, w.DWORD, w.BOOL]
    user32.AttachThreadInput.restype = w.BOOL
    user32.SetForegroundWindow.argtypes = [w.HWND]
    user32.SetForegroundWindow.restype = w.BOOL
    user32.BringWindowToTop.argtypes = [w.HWND]
    user32.BringWindowToTop.restype = w.BOOL
    user32.SetFocus.argtypes = [w.HWND]
    user32.SetFocus.restype = w.HWND
    user32.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
    user32.ShowWindow.restype = w.BOOL
    user32.IsWindowVisible.argtypes = [w.HWND]
    user32.IsWindowVisible.restype = w.BOOL
    user32.IsIconic.argtypes = [w.HWND]
    user32.IsIconic.restype = w.BOOL
    user32.IsWindow.argtypes = [w.HWND]
    user32.IsWindow.restype = w.BOOL
    user32.GetWindowTextLengthW.argtypes = [w.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    user32.GetWindowRect.restype = w.BOOL
    user32.EnumWindows.argtypes = [ctypes.c_void_p, w.LPARAM]
    user32.EnumWindows.restype = w.BOOL
    user32.EnumDisplayMonitors.argtypes = [w.HDC, ctypes.c_void_p, ctypes.c_void_p, w.LPARAM]
    user32.EnumDisplayMonitors.restype = w.BOOL
    user32.GetMonitorInfoW.argtypes = [w.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
    user32.GetMonitorInfoW.restype = w.BOOL
    user32.MonitorFromPoint.argtypes = [w.POINT, w.DWORD]
    user32.MonitorFromPoint.restype = w.HMONITOR
    user32.SendInput.argtypes = [w.UINT, ctypes.c_void_p, ctypes.c_int]
    user32.SendInput.restype = w.UINT
    user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
    user32.GetLastInputInfo.restype = w.BOOL
    user32.GetDC.argtypes = [w.HWND]
    user32.GetDC.restype = w.HDC
    user32.ReleaseDC.argtypes = [w.HWND, w.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.GetWindowLongW.argtypes = [w.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = w.LONG
    if hasattr(user32, "GetWindowLongPtrW"):
        user32.GetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t

    gdi32.CreateCompatibleDC.argtypes = [w.HDC]
    gdi32.CreateCompatibleDC.restype = w.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = w.HBITMAP
    gdi32.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
    gdi32.SelectObject.restype = w.HGDIOBJ
    gdi32.BitBlt.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HDC, ctypes.c_int, ctypes.c_int, w.DWORD]
    gdi32.BitBlt.restype = w.BOOL
    gdi32.GetDIBits.argtypes = [w.HDC, w.HBITMAP, w.UINT, w.UINT, ctypes.c_void_p, ctypes.POINTER(BITMAPINFOHEADER), w.UINT]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [w.HGDIOBJ]
    gdi32.DeleteObject.restype = w.BOOL
    gdi32.DeleteDC.argtypes = [w.HDC]
    gdi32.DeleteDC.restype = w.BOOL

    kernel32.GetCurrentThreadId.restype = w.DWORD
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel32.OpenProcess.restype = w.HANDLE
    kernel32.CloseHandle.argtypes = [w.HANDLE]
    kernel32.CloseHandle.restype = w.BOOL

    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        dwmapi.DwmGetWindowAttribute.argtypes = [w.HWND, w.DWORD, ctypes.c_void_p, w.DWORD]
        dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
    except OSError:  # pragma: no cover - 只有极老系统没有 dwmapi
        dwmapi = None
else:  # pragma: no cover
    dwmapi = None


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class Monitor:
    id: str
    x: int
    y: int
    width: int
    height: int
    primary: bool
    scale: float

    def to_dict(self) -> dict:
        return {
            "id": self.id, "x": self.x, "y": self.y,
            "width": self.width, "height": self.height,
            "primary": self.primary, "scale": self.scale,
        }


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    pid: int
    x: int
    y: int
    width: int
    height: int
    z: int
    minimized: bool
    elevated: bool

    def to_dict(self) -> dict:
        return {
            "window_id": str(self.hwnd),
            "title": self.title,
            "class_name": self.class_name,
            "pid": self.pid,
            "bounds": [self.x, self.y, self.width, self.height],
            "z": self.z,
            "minimized": self.minimized,
            "elevated": self.elevated,
        }


class Win32Error(RuntimeError):
    """系统调用失败，携带 Win32 错误码。"""


# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
_DPI_PER_MONITOR_V2 = -4


def _ensure_dpi_aware() -> None:
    """把当前线程切到 per-monitor v2，避免拿到逻辑像素尺寸。"""
    if not IS_WINDOWS:
        return
    try:
        user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(_DPI_PER_MONITOR_V2))
    except Exception:
        pass


def _require_windows() -> None:
    if not IS_WINDOWS:
        raise Win32Error("computer use 只在 Windows 上可用")
    _ensure_dpi_aware()


def _last_error(prefix: str) -> Win32Error:
    return Win32Error(f"{prefix} failed: {ctypes.get_last_error()}")


# ---------------------------------------------------------------------------
# 显示器与虚拟桌面
# ---------------------------------------------------------------------------

_MONITOR_ENUM_PROC = ctypes.WINFUNCTYPE(
    w.BOOL, w.HMONITOR, w.HDC, ctypes.POINTER(w.RECT), w.LPARAM
)


def _dpi_scale(hmon: w.HMONITOR) -> float:
    try:
        shcore = ctypes.WinDLL("shcore")
        dx = ctypes.c_uint(96)
        dy = ctypes.c_uint(96)
        if shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
            return max(dx.value, 1) / 96.0
    except OSError:
        pass
    return 1.0


def monitors() -> list[Monitor]:
    _require_windows()
    result: list[Monitor] = []

    def _collect(hmon, _hdc, _rect, _data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return True
        name = "".join(ch for ch in info.szDevice if ch != "\x00")
        rect = info.rcMonitor
        result.append(
            Monitor(
                id=name,
                x=rect.left, y=rect.top,
                width=rect.right - rect.left,
                height=rect.bottom - rect.top,
                primary=bool(info.dwFlags & 1),
                scale=_dpi_scale(hmon),
            )
        )
        return True

    callback = _MONITOR_ENUM_PROC(_collect)
    if not user32.EnumDisplayMonitors(None, None, callback, 0):
        raise _last_error("EnumDisplayMonitors")
    if not result:
        raise Win32Error("no display monitors reported")
    result.sort(key=lambda m: (m.x, m.y))
    return result


def virtual_screen() -> tuple[int, int, int, int]:
    _require_windows()
    return (
        user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CXVIRTUALSCREEN),
        user32.GetSystemMetrics(SM_CYVIRTUALSCREEN),
    )


def monitor_at(x: int, y: int) -> Monitor:
    _require_windows()
    for monitor in monitors():
        if monitor.x <= x < monitor.x + monitor.width and monitor.y <= y < monitor.y + monitor.height:
            return monitor
    raise Win32Error(f"no monitor contains point {x},{y}")


def cursor_position() -> tuple[int, int]:
    _require_windows()
    point = w.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise _last_error("GetCursorPos")
    return point.x, point.y


# ---------------------------------------------------------------------------
# 截图
# ---------------------------------------------------------------------------


def capture_rect(x: int, y: int, width: int, height: int) -> tuple[int, int, bytes]:
    """抓虚拟桌面指定区域，返回物理像素尺寸与 RGBA 字节。"""
    _require_windows()
    if width <= 0 or height <= 0:
        raise Win32Error(f"invalid capture size {width}x{height}")
    screen_dc = user32.GetDC(None)
    if not screen_dc:
        raise _last_error("GetDC")
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    if not mem_dc:
        user32.ReleaseDC(None, screen_dc)
        raise _last_error("CreateCompatibleDC")
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    if not bitmap:
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)
        raise _last_error("CreateCompatibleBitmap")
    previous = gdi32.SelectObject(mem_dc, bitmap)
    try:
        if not gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc, x, y, SRCCOPY | CAPTUREBLT):
            raise Win32Error("BitBlt failed, the desktop may be locked or protected")
        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height  # 负高度 = 自上而下，省一次翻转
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = BI_RGB
        buffer = ctypes.create_string_buffer(width * height * 4)
        lines = gdi32.GetDIBits(
            mem_dc, bitmap, 0, height, buffer, ctypes.byref(header), DIB_RGB_COLORS
        )
        if lines == 0:
            raise _last_error("GetDIBits")
        return width, height, buffer.raw
    finally:
        gdi32.SelectObject(mem_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)


def capture_monitor(monitor: Monitor) -> tuple[int, int, bytes]:
    return capture_rect(monitor.x, monitor.y, monitor.width, monitor.height)


# ---------------------------------------------------------------------------
# 窗口
# ---------------------------------------------------------------------------


def _window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def _class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def _is_cloaked(hwnd: int) -> bool:
    if dwmapi is None:
        return False
    value = w.DWORD(0)
    result = dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)
    )
    return result == 0 and value.value != 0


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = w.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise _last_error("GetWindowRect")
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def _window_pid(hwnd: int) -> int:
    pid = w.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def process_is_elevated(pid: int) -> bool:
    """目标进程权限高于当前进程时，SendInput 会被 UIPI 拦掉。"""
    _require_windows()
    if pid <= 0:
        return False
    handle = kernel32.OpenProcess(PROCESS_VM_READ, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return False
    return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED


_ENUM_PROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)


def list_windows(*, exclude_pids: set[int] | None = None, include_hidden: bool = False) -> list[WindowInfo]:
    """按 Z 序返回顶层窗口，最上面的在前。"""
    _require_windows()
    exclude = exclude_pids or set()
    rows: list[WindowInfo] = []

    def _collect(hwnd, _data):
        if not user32.IsWindowVisible(hwnd):
            return True
        if _is_cloaked(hwnd):
            return True
        style = 0
        if hasattr(user32, "GetWindowLongPtrW"):
            style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        else:  # pragma: no cover
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if style & WS_EX_TOOLWINDOW:
            return True
        title = _window_text(hwnd)
        if not include_hidden and not title.strip():
            return True
        pid = _window_pid(hwnd)
        if pid in exclude:
            return True
        try:
            x, y, width, height = _window_rect(hwnd)
        except Win32Error:
            return True
        rows.append(
            WindowInfo(
                hwnd=int(hwnd), title=title, class_name=_class_name(hwnd), pid=pid,
                x=x, y=y, width=width, height=height, z=len(rows),
                minimized=bool(user32.IsIconic(hwnd)),
                elevated=process_is_elevated(pid),
            )
        )
        return True

    callback = _ENUM_PROC(_collect)
    if not user32.EnumWindows(callback, 0):
        raise _last_error("EnumWindows")
    return rows


def window_info(hwnd: int) -> WindowInfo:
    _require_windows()
    if not user32.IsWindow(hwnd):
        raise Win32Error(f"window {hwnd} does not exist")
    x, y, width, height = _window_rect(hwnd)
    pid = _window_pid(hwnd)
    return WindowInfo(
        hwnd=hwnd, title=_window_text(hwnd), class_name=_class_name(hwnd), pid=pid,
        x=x, y=y, width=width, height=height, z=0,
        minimized=bool(user32.IsIconic(hwnd)),
        elevated=process_is_elevated(pid),
    )


def foreground_window() -> int:
    _require_windows()
    return int(user32.GetForegroundWindow() or 0)


def window_from_point(x: int, y: int) -> int:
    """屏幕坐标命中的最上层窗口。用来确认点击落点没有被别的窗口挡住。"""
    _require_windows()
    point = w.POINT(x, y)
    return int(user32.WindowFromPoint(point) or 0)


def root_window(hwnd: int) -> int:
    """取顶层父窗口：命中控件时也要能追到它所属的窗口。"""
    _require_windows()
    if not hwnd:
        return 0
    return int(user32.GetAncestor(hwnd, 2) or hwnd)  # GA_ROOT = 2


def activate_window(hwnd: int) -> bool:
    """把窗口拉到前台。三级兜底：直接设置、线程挂接、Alt 键解锁前台锁。"""
    _require_windows()
    if not user32.IsWindow(hwnd):
        raise Win32Error(f"window {hwnd} does not exist")
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    if foreground_window() == hwnd:
        return True

    current = kernel32.GetCurrentThreadId()
    foreground = foreground_window()
    attached: list[int] = []
    for tid in (
        user32.GetWindowThreadProcessId(foreground, None) if foreground else 0,
        user32.GetWindowThreadProcessId(hwnd, None),
    ):
        if tid and tid != current and user32.AttachThreadInput(current, tid, True):
            attached.append(tid)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        for tid in attached:
            user32.AttachThreadInput(current, tid, False)
    if foreground_window() == hwnd:
        return True

    # 系统认为“用户刚刚有输入”时才允许切前台，所以先敲一下 Alt。
    _send_vk(VK_MENU, 0)
    _send_vk(VK_MENU, KEYEVENTF_KEYUP)
    time.sleep(0.03)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    return foreground_window() == hwnd


# ---------------------------------------------------------------------------
# 输入注入
# ---------------------------------------------------------------------------


def _send_inputs(events: list[tuple]) -> int:
    if not events:
        return 0
    array = (INPUT * len(events))()
    for index, event in enumerate(events):
        kind = event[0]
        array[index].type = kind
        if kind == INPUT_MOUSE:
            _, dx, dy, data, flags = event
            array[index].mi = MOUSEINPUT(dx, dy, data, flags, 0, 0)
        else:
            _, vk, scan, flags = event
            array[index].ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    sent = user32.SendInput(len(events), ctypes.byref(array), ctypes.sizeof(INPUT))
    if sent != len(events):
        raise _last_error(f"SendInput sent {sent}/{len(events)}")
    return int(sent)


def _send_vk(vk: int, flags: int) -> None:
    _send_inputs([(INPUT_KEYBOARD, vk, 0, flags)])


def _absolute_point(x: int, y: int) -> tuple[int, int]:
    vx, vy, vw, vh = virtual_screen()
    ax = int(round((x - vx) * 65535 / max(vw - 1, 1)))
    ay = int(round((y - vy) * 65535 / max(vh - 1, 1)))
    return max(0, min(65535, ax)), max(0, min(65535, ay))


def move_mouse(x: int, y: int) -> None:
    _require_windows()
    ax, ay = _absolute_point(x, y)
    _send_inputs([(INPUT_MOUSE, ax, ay, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK)])


def mouse_click(x: int, y: int, *, button: str = "left", count: int = 1) -> None:
    _require_windows()
    down, up = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }.get(button, (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP))
    ax, ay = _absolute_point(x, y)
    events: list[tuple] = [(INPUT_MOUSE, ax, ay, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK)]
    for _ in range(max(1, min(count, 3))):
        events.append((INPUT_MOUSE, 0, 0, 0, down))
        events.append((INPUT_MOUSE, 0, 0, 0, up))
    _send_inputs(events)


def mouse_scroll(x: int, y: int, delta: int, *, axis: str = "vertical") -> None:
    _require_windows()
    ax, ay = _absolute_point(x, y)
    flag = MOUSEEVENTF_WHEEL if axis != "horizontal" else MOUSEEVENTF_HWHEEL
    # Windows 滚轮单位是 120，模型给的是“格”，一格 = 120。
    amount = int(max(-20, min(20, delta)) * 120)
    _send_inputs([
        (INPUT_MOUSE, ax, ay, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK),
        (INPUT_MOUSE, 0, 0, amount & 0xFFFFFFFF, flag),
    ])


def mouse_drag(x1: int, y1: int, x2: int, y2: int, *, duration: float = 0.4, button: str = "left") -> None:
    _require_windows()
    down, up = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }.get(button, (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP))
    steps = max(4, min(24, int(duration * 40)))
    ax1, ay1 = _absolute_point(x1, y1)
    _send_inputs([
        (INPUT_MOUSE, ax1, ay1, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK),
        (INPUT_MOUSE, 0, 0, 0, down),
    ])
    for step in range(1, steps + 1):
        ratio = step / steps
        ax, ay = _absolute_point(
            int(round(x1 + (x2 - x1) * ratio)),
            int(round(y1 + (y2 - y1) * ratio)),
        )
        _send_inputs([(INPUT_MOUSE, ax, ay, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK)])
        time.sleep(duration / steps)
    _send_inputs([(INPUT_MOUSE, 0, 0, 0, up)])


def type_text(text: str) -> int:
    """逐字符发 Unicode，绕开输入法状态。返回实际发出的字符数。"""
    _require_windows()
    if not text:
        return 0
    events: list[tuple] = []
    for char in text:
        code = ord(char)
        if char == "\r":
            continue
        if char == "\n":
            events.append((INPUT_KEYBOARD, 0, 0x1C, KEYEVENTF_UNICODE))  # 换行按 Enter
            events.append((INPUT_KEYBOARD, 0, 0x1C, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
            continue
        if code > 0xFFFF:
            code -= 0x10000
            for unit in (0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)):
                events.append((INPUT_KEYBOARD, 0, unit, KEYEVENTF_UNICODE))
                events.append((INPUT_KEYBOARD, 0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        else:
            events.append((INPUT_KEYBOARD, 0, code, KEYEVENTF_UNICODE))
            events.append((INPUT_KEYBOARD, 0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    # 一次发太多会被系统截断，按 64 个事件一批。
    for start in range(0, len(events), 64):
        _send_inputs(events[start:start + 64])
        time.sleep(0.01)
    return len(text)


def press_keys(keys: list[str]) -> list[str]:
    """按一个组合键，例如 ["ctrl","shift","t"]。返回实际按下的键。"""
    _require_windows()
    normalized: list[str] = []
    for key in keys:
        token = str(key or "").strip().lower()
        if not token:
            continue
        if token not in VK_NAMES:
            raise Win32Error(f"unknown key: {key}")
        normalized.append(token)
    if not normalized:
        raise Win32Error("no keys given")
    modifiers = [k for k in normalized if k in {"ctrl", "control", "shift", "alt", "menu", "win", "lwin", "rwin", "cmd"}]
    main = [k for k in normalized if k not in set(modifiers)]
    for key in modifiers:
        _send_vk(VK_NAMES[key], 0)
    try:
        if main:
            for key in main:
                _send_vk(VK_NAMES[key], 0)
                _send_vk(VK_NAMES[key], KEYEVENTF_KEYUP)
        else:
            # 只按修饰键时保持一次按下抬起，避免卡住
            for key in modifiers:
                _send_vk(VK_NAMES[key], KEYEVENTF_KEYUP)
            return modifiers
    finally:
        for key in reversed(modifiers):
            _send_vk(VK_NAMES[key], KEYEVENTF_KEYUP)
    return normalized


# ---------------------------------------------------------------------------
# 用户接管检测
# ---------------------------------------------------------------------------


def last_input_tick() -> int:
    _require_windows()
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0
    return int(info.dwTime)


def input_since(tick: int) -> int:
    """返回自 tick 之后系统收到输入的毫秒数，处理 32 位回绕。"""
    now = last_input_tick()
    if not now:
        return 0
    return (now - tick) & 0xFFFFFFFF


def current_pid() -> int:
    return os.getpid()


# ---------------------------------------------------------------------------
# 剪贴板
# ---------------------------------------------------------------------------

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

if IS_WINDOWS:
    user32.OpenClipboard.argtypes = [w.HWND]
    user32.OpenClipboard.restype = w.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = w.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = w.BOOL
    user32.SetClipboardData.argtypes = [w.UINT, w.HANDLE]
    user32.SetClipboardData.restype = w.HANDLE
    kernel32.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = w.HGLOBAL
    kernel32.GlobalLock.argtypes = [w.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [w.HGLOBAL]
    kernel32.GlobalUnlock.restype = w.BOOL


def set_clipboard_text(text: str) -> None:
    """写入剪贴板。长文本走粘贴比逐字符注入快一个数量级。"""
    _require_windows()
    if not user32.OpenClipboard(None):
        raise _last_error("OpenClipboard")
    try:
        if not user32.EmptyClipboard():
            raise _last_error("EmptyClipboard")
        payload = text.encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(payload))
        if not handle:
            raise _last_error("GlobalAlloc")
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            kernel32.GlobalFree(handle)
            raise _last_error("GlobalLock")
        ctypes.memmove(pointer, payload, len(payload))
        kernel32.GlobalUnlock(handle)
        # 成功后所有权归系统，不能再释放 handle
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise _last_error("SetClipboardData")
    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------------------------
# 后台输入：向目标窗口投递消息，不移动真实光标
#
# user:“不抢占真实鼠标的方式你可以看看 叫做 okww”+(ok-script 用 PostMessage 做
# 后台输入，窗口被遮挡也能收到；代价是部分应用只认真实输入，需要前台回退)。
# ---------------------------------------------------------------------------


def _make_lparam(x: int, y: int) -> int:
    """把客户区坐标压成 lParam，负坐标按 16 位补码处理。"""
    return ((y & 0xFFFF) << 16) | (x & 0xFFFF)


def screen_to_client(hwnd: int, x: int, y: int) -> tuple[int, int]:
    _require_windows()
    point = w.POINT(x, y)
    if not user32.ScreenToClient(hwnd, ctypes.byref(point)):
        raise _last_error("ScreenToClient")
    return point.x, point.y


def client_to_screen(hwnd: int, x: int, y: int) -> tuple[int, int]:
    _require_windows()
    point = w.POINT(x, y)
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        raise _last_error("ClientToScreen")
    return point.x, point.y


_BUTTON_MESSAGES = {
    "left": (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON),
    "right": (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON),
    "middle": (WM_MBUTTONDOWN, WM_MBUTTONUP, MK_MBUTTON),
}


def background_click(hwnd: int, x: int, y: int, *, button: str = "left", count: int = 1) -> tuple[int, int]:
    """后台点击：坐标是屏幕坐标，内部转客户区。返回实际投递的客户区坐标。"""
    _require_windows()
    down, up, flag = _BUTTON_MESSAGES.get(button, _BUTTON_MESSAGES["left"])
    cx, cy = screen_to_client(hwnd, x, y)
    lparam = _make_lparam(cx, cy)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
    for _ in range(max(1, min(count, 3))):
        user32.PostMessageW(hwnd, down, flag, lparam)
        time.sleep(0.02)
        user32.PostMessageW(hwnd, up, 0, lparam)
        time.sleep(0.02)
    return cx, cy


def background_scroll(hwnd: int, x: int, y: int, delta: int, *, axis: str = "vertical") -> None:
    _require_windows()
    cx, cy = screen_to_client(hwnd, x, y)
    amount = int(max(-20, min(20, delta)) * 120)
    wparam = ((amount & 0xFFFF) << 16) | (0x0001 if axis != "horizontal" else 0x0002)
    user32.PostMessageW(hwnd, WM_MOUSEWHEEL, wparam, _make_lparam(cx, cy))


def background_type(hwnd: int, text: str) -> int:
    """按字符投递 WM_CHAR。中文依赖目标程序自己处理 Unicode 字符。"""
    _require_windows()
    # 目标窗口没被激活过时，控件拿不到键盘焦点，WM_CHAR 会被丢掉。
    # 先让窗口自认为处于活动状态，消息才有落点。
    user32.PostMessageW(hwnd, WM_ACTIVATE, 1, 0)
    user32.PostMessageW(hwnd, WM_SETFOCUS, 0, 0)
    time.sleep(0.05)
    sent = 0
    for char in text:
        if char == chr(13):
            continue
        if char == chr(10):
            user32.PostMessageW(hwnd, WM_KEYDOWN, 0x0D, 0x1C)
            user32.PostMessageW(hwnd, WM_KEYUP, 0x0D, 0x1C | 0xC0000000)
            sent += 1
            continue
        code = ord(char)
        if code > 0xFFFF:
            code -= 0x10000
            for unit in (0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)):
                user32.PostMessageW(hwnd, WM_CHAR, unit, 1)
        else:
            user32.PostMessageW(hwnd, WM_CHAR, code, 1)
        sent += 1
        time.sleep(0.005)
    return sent


def background_press_keys(hwnd: int, keys: list[str]) -> list[str]:
    """按组合键投递 WM_KEYDOWN/WM_KEYUP。"""
    _require_windows()
    normalized: list[str] = []
    for key in keys:
        token = str(key or "").strip().lower()
        if not token:
            continue
        if token not in VK_NAMES:
            raise Win32Error(f"unknown key: {key}")
        normalized.append(token)
    if not normalized:
        raise Win32Error("no keys given")
    modifiers = [k for k in normalized if k in {"ctrl", "control", "shift", "alt", "menu", "win", "lwin", "rwin", "cmd"}]
    main = [k for k in normalized if k not in set(modifiers)]
    for key in modifiers:
        user32.PostMessageW(hwnd, WM_KEYDOWN, VK_NAMES[key], 0)
    for key in main or modifiers:
        user32.PostMessageW(hwnd, WM_KEYDOWN, VK_NAMES[key], 0)
        user32.PostMessageW(hwnd, WM_KEYUP, VK_NAMES[key], 0xC0000000)
    for key in reversed(modifiers):
        user32.PostMessageW(hwnd, WM_KEYUP, VK_NAMES[key], 0xC0000000)
    return normalized


def capture_window(hwnd: int) -> tuple[int, int, bytes]:
    """抓窗口画面，被遮挡也能抓到。

    先试 PrintWindow 的 PW_RENDERFULLCONTENT，它能让 DirectX 窗口也吐内容；
    失败时退回窗口 DC 的 BitBlt，只能拿到可见部分。
    """
    _require_windows()
    x, y, width, height = _window_rect(hwnd)
    if width <= 0 or height <= 0:
        raise Win32Error(f"window {hwnd} has no drawable area")
    screen_dc = user32.GetDC(None)
    if not screen_dc:
        raise _last_error("GetDC")
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    if not mem_dc:
        user32.ReleaseDC(None, screen_dc)
        raise _last_error("CreateCompatibleDC")
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    if not bitmap:
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)
        raise _last_error("CreateCompatibleBitmap")
    previous = gdi32.SelectObject(mem_dc, bitmap)
    try:
        printed = user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)
        if not printed:
            printed = user32.PrintWindow(hwnd, mem_dc, 0)
        if not printed:
            if not gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc, x, y, SRCCOPY | CAPTUREBLT):
                raise Win32Error("PrintWindow and BitBlt both failed for this window")
        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = BI_RGB
        buffer = ctypes.create_string_buffer(width * height * 4)
        lines = gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer, ctypes.byref(header), DIB_RGB_COLORS)
        if lines == 0:
            raise _last_error("GetDIBits")
        return width, height, buffer.raw
    finally:
        gdi32.SelectObject(mem_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(None, screen_dc)
