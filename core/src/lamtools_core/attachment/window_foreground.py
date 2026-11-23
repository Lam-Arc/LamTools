"""让「以默认应用打开」的程序窗口真的到前台。

user:“‘以默认应用打开’后窗口不再最上层，还要单独翻任务栏”
+(用户点开一个文件，目标程序的新窗口必须自己来到前台——否则用户还得去任务栏
里翻。只在「用户刚点了这一次」主动置前，之后不抢焦点。)

为什么不能只靠 ``os.startfile``：它等于 ``ShellExecuteW`` 默认参数，只负责
「把程序起起来」。Windows 的前台锁（foreground lock）会把「非用户输入触发的
进程主动 SetForegroundWindow」静默降级成一个任务栏闪烁，于是窗口起在下面。

这里的组合手段（按顺序退化）：
1. ``AllowSetForegroundWindow(ASFW_ANY)``：先放开本进程/子进程置前的许可；
2. ``ShellExecuteExW``（``SEE_MASK_NOASYNC | SEE_MASK_NOCLOSEPROCESS``）拉起目标，
   拿到它的 PID——这是后面按 PID 找窗口的前提；
3. 3 秒内轮询：按启动的 PID 枚举顶层窗口 → ``ShowWindow(SW_RESTORE)`` +
   ``SetForegroundWindow``；失败就用 ``AttachThreadInput`` 挂到当前前台线程再设一次；
4. 轮询过半仍没成功，模拟一次 Alt 键（``keybd_event``）解除前台锁再试；
5. 超时仍失败：不静默——``FlashWindowEx`` 闪任务栏，并如实返回结果。

纯逻辑（何时按键、何时放弃、轮询节奏）与 Win32 调用分离，见 ``await_foreground``，
它只依赖注入进来的几个可调用对象，因此可以在任何平台上测。
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Any, Callable

IS_WINDOWS = sys.platform == "win32"

# ---------------------------------------------------------------- Win32 常量
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NOASYNC = 0x00000100
SEE_MASK_FLAG_NO_UI = 0x00000400
SW_SHOWNORMAL = 1
SW_RESTORE = 9
ASFW_ANY = -1
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002
FLASHW_ALL = 0x00000003
FLASHW_TIMERNOFG = 0x0000000C
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002


@dataclass(frozen=True)
class ForegroundPlan:
    """置前的节奏。3 秒是用户还能忍的「怎么还不出来」上限。"""

    timeout: float = 3.0
    interval: float = 0.05
    nudge_after: float = 0.5
    max_nudges: int = 2


@dataclass
class ForegroundResult:
    #: ``foreground`` 已到前台 / ``flashed`` 没置前但闪了任务栏 / ``gave-up`` 什么都没成
    outcome: str = "gave-up"
    window: int | None = None
    elapsed: float = 0.0
    nudges: int = 0
    message: str = ""
    #: 拉起的进程 PID（拿不到时 None，例如走 shell 兜底）
    pid: int | None = None

    @property
    def raised(self) -> bool:
        return self.outcome == "foreground"

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "raised": self.raised,
            "window": self.window,
            "pid": self.pid,
            "elapsed": round(self.elapsed, 3),
            "nudges": self.nudges,
            "message": self.message,
        }


def should_nudge(elapsed: float, nudges: int, plan: ForegroundPlan) -> bool:
    """该不该敲一次 Alt 解除前台锁。次数用满后不再敲。"""
    if nudges >= plan.max_nudges:
        return False
    return elapsed >= plan.nudge_after * (nudges + 1)


def should_give_up(elapsed: float, plan: ForegroundPlan) -> bool:
    return elapsed >= plan.timeout


def await_foreground(
    *,
    find_window: Callable[[], int | None],
    raise_window: Callable[[int], bool],
    nudge: Callable[[], None] | None = None,
    flash: Callable[[int | None], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    plan: ForegroundPlan | None = None,
) -> ForegroundResult:
    """轮询直到窗口到前台、或超时退化。

    ``find_window`` 返回目标窗口句柄（还没有就 None）；``raise_window`` 返回是否
    真的到了前台。``nudge`` 是解除前台锁的补充手段，``flash`` 是超时兜底。
    """
    plan = plan or ForegroundPlan()
    started = clock()
    nudges = 0
    window: int | None = None
    while True:
        window = find_window()
        if window is not None and raise_window(window):
            return ForegroundResult(
                outcome="foreground",
                window=window,
                elapsed=clock() - started,
                nudges=nudges,
            )
        elapsed = clock() - started
        if nudge is not None and should_nudge(elapsed, nudges, plan):
            nudges += 1
            nudge()
            continue
        if should_give_up(elapsed, plan):
            break
        sleep(plan.interval)

    elapsed = clock() - started
    if flash is not None:
        flash(window)
        return ForegroundResult(
            outcome="flashed",
            window=window,
            elapsed=elapsed,
            nudges=nudges,
            message="窗口没能置前，已闪任务栏提醒" if window else "没等到窗口，已请求任务栏提醒",
        )
    return ForegroundResult(
        outcome="gave-up",
        window=window,
        elapsed=elapsed,
        nudges=nudges,
        message="窗口没能置前",
    )


# ------------------------------------------------------------------ Windows
if IS_WINDOWS:  # pragma: no cover - 真机分支，只有 Windows 会执行
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    class _FLASHWINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("hwnd", wintypes.HWND),
            ("dwFlags", wintypes.DWORD),
            ("uCount", wintypes.UINT),
            ("dwTimeout", wintypes.DWORD),
        ]

    def _enum_top_level() -> list[tuple[int, int, int]]:
        """可见顶层窗口 → (hwnd, pid, 面积)。面积用来在兜底策略里挑主窗口。"""
        found: list[tuple[int, int, int]] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def visit(hwnd: int, _param: int) -> bool:
            if not _user32.IsWindowVisible(hwnd):
                return True
            if _user32.GetWindow(hwnd, 4):  # GW_OWNER：有 owner 的多是弹窗/工具窗
                return True
            owner = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            rect = wintypes.RECT()
            _user32.GetWindowRect(hwnd, ctypes.byref(rect))
            area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
            found.append((int(hwnd), int(owner.value), area))
            return True

        callback = callback_type(visit)
        _user32.EnumWindows(callback, 0)
        return found

    def _force_foreground(hwnd: int) -> bool:
        """把窗口恢复到正常状态并置前；不行就挂到前台线程再试一次。"""
        _user32.ShowWindow(hwnd, SW_RESTORE)
        if _user32.SetForegroundWindow(hwnd):
            return True
        fore = _user32.GetForegroundWindow()
        own_thread = _kernel32.GetCurrentThreadId()
        fore_thread = (
            _user32.GetWindowThreadProcessId(fore, None) if fore else 0
        )
        if fore_thread and fore_thread != own_thread:
            if _user32.AttachThreadInput(fore_thread, own_thread, True):
                try:
                    _user32.BringWindowToTop(hwnd)
                    _user32.SetForegroundWindow(hwnd)
                finally:
                    _user32.AttachThreadInput(fore_thread, own_thread, False)
        if fore and _user32.SetForegroundWindow(hwnd):
            return True
        return int(_user32.GetForegroundWindow() or 0) == hwnd

    def _alt_nudge() -> None:
        """模拟一次 Alt 键：用户输入会解除前台锁。"""
        _user32.keybd_event(VK_MENU, 0, 0, 0)
        _user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

    def _flash(hwnd: int | None) -> None:
        if not hwnd:
            return
        info = _FLASHWINFO(
            cbSize=ctypes.sizeof(_FLASHWINFO),
            hwnd=hwnd,
            dwFlags=FLASHW_ALL | FLASHW_TIMERNOFG,
            uCount=3,
            dwTimeout=0,
        )
        _user32.FlashWindowEx(ctypes.byref(info))

    def _shell_execute(path: str) -> tuple[bool, int | None, str]:
        """``ShellExecuteExW``：返回 (是否成功, PID, 错误说明)。

        ``SEE_MASK_NOASYNC`` 保证返回时程序已经起好（否则偶发拿到无效 hProcess）；
        ``SEE_MASK_NOCLOSEPROCESS`` 才让 hProcess 有效，这是拿 PID 的唯一途径。
        """
        info = _SHELLEXECUTEINFOW()
        info.cbSize = ctypes.sizeof(_SHELLEXECUTEINFOW)
        info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC | SEE_MASK_FLAG_NO_UI
        info.lpVerb = "open"
        info.lpFile = str(path)
        info.nShow = SW_SHOWNORMAL
        if not _shell32.ShellExecuteExW(ctypes.byref(info)):
            error = ctypes.get_last_error()
            return False, None, f"ShellExecuteExW 失败（错误码 {error}）"
        pid = None
        if info.hProcess:
            pid = int(_kernel32.GetProcessId(info.hProcess)) or None
            _kernel32.CloseHandle(info.hProcess)
        return True, pid, ""

    def open_and_raise(path: str, *, plan: ForegroundPlan | None = None) -> ForegroundResult:
        """用默认应用打开 ``path``，并把它的窗口带到前台。"""
        plan = plan or ForegroundPlan()
        # 先放开置前许可：不然目标进程自己 SetForegroundWindow 也会被降级。
        with_suppress(lambda: _user32.AllowSetForegroundWindow(ASFW_ANY))

        baseline = {hwnd for hwnd, _pid, _area in _enum_top_level()}
        ok, pid, error = _shell_execute(path)
        if not ok:
            # 退回 os.startfile：至少能把程序起起来，别因为置前逻辑连打开都做不了。
            import os

            os.startfile(str(path))  # type: ignore[attr-defined]
            pid = None

        def find_window() -> int | None:
            windows = _enum_top_level()
            if pid is not None:
                owned = [item for item in windows if item[1] == pid]
                if owned:
                    return max(owned, key=lambda item: item[2])[0]
            # 没有 PID（兜底启动）或目标还没建窗：退而找「新出现且面积最大」的窗口。
            fresh = [item for item in windows if item[0] not in baseline]
            if fresh:
                return max(fresh, key=lambda item: item[2])[0]
            return None

        result = await_foreground(
            find_window=find_window,
            raise_window=_force_foreground,
            nudge=_alt_nudge,
            flash=_flash,
            plan=plan,
        )
        result.pid = pid
        if error and not result.message:
            result.message = error
        return result

else:  # pragma: no cover - 非 Windows 只做等价行为

    def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    def open_and_raise(path: str, *, plan: ForegroundPlan | None = None) -> ForegroundResult:
        import subprocess

        command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return ForegroundResult(outcome="foreground", message="已交给系统默认应用")


def with_suppress(action: Callable[[], Any]) -> None:
    """Win32 调用失败不应影响「打开文件」这件事本身。"""
    try:
        action()
    except Exception:  # noqa: BLE001 - 置前是尽力而为
        pass


__all__ = [
    "ForegroundPlan",
    "ForegroundResult",
    "await_foreground",
    "open_and_raise",
    "should_give_up",
    "should_nudge",
]
