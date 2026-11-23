"""把子进程的窗口藏起来：统一的 ``CREATE_NO_WINDOW`` + ``SW_HIDE`` 拼装。

user:“启动后台任务时会弹命令行窗，能不能隐藏掉？”
+(凡是宿主自己拉起的子进程——后端、传输进程、workflow runner、命令工具、
搜索引擎、git、netstat/tasklist、引擎安装——都必须以「不建可见窗口」的方式创建)

为什么要有这个模块：宿主是 ``windows_subsystem = "windows"`` 的 GUI 进程，
它自己**没有**控制台。这时用默认参数去 spawn 一个控制台子系统程序，Windows
会给子进程新分配一个控制台窗口并显示出来，用户就看到黑窗一闪。加
``CREATE_NO_WINDOW`` 之后子进程照样有控制台（输出重定向依旧正常），只是窗口
从不显示。

user:“不能因为隐藏窗口而丢失输出”+(隐藏的是窗口，不是管道：这里只碰
``creationflags`` 与 ``startupinfo``，绝不改写 ``stdout``/``stderr``/``stdin``,
调用方原有的管道/文件重定向原样保留)。
"""

from __future__ import annotations

import sys
from typing import Any

IS_WINDOWS = sys.platform == "win32"

# Win32 常量。不读 ``subprocess`` 上的同名属性：它们在非 Windows 构建上不存在，
# 而且这里要在任何平台都能安全导入。
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
STARTF_USESHOWWINDOW = 0x00000001
SW_HIDE = 0


def creation_flags(*, new_process_group: bool = False) -> int:
    """子进程创建标志：Windows 上恒含 ``CREATE_NO_WINDOW``。

    ``new_process_group`` 只给「需要 Ctrl+Break / 整组终止」的调用方加；它本身
    也会让子进程忽略宿主的 Ctrl+C，不影响窗口可见性。
    """
    if not IS_WINDOWS:
        return 0
    flags = CREATE_NO_WINDOW
    if new_process_group:
        flags |= CREATE_NEW_PROCESS_GROUP
    return flags


def startup_info() -> Any | None:
    """带 ``SW_HIDE`` 的 STARTUPINFO；非 Windows 返回 None。

    ``CREATE_NO_WINDOW`` 已经足够，但少数程序（自己 ``ShowWindow`` 的安装器、
    部分 ``cmd.exe`` 变体）会无视它。``STARTF_USESHOWWINDOW`` 把「第一次显示
    窗口时的状态」钉成隐藏，两层一起上。
    """
    if not IS_WINDOWS:
        return None
    import subprocess

    info = subprocess.STARTUPINFO()
    info.dwFlags |= STARTF_USESHOWWINDOW
    info.wShowWindow = SW_HIDE
    return info


def hidden_kwargs(*, new_process_group: bool = False) -> dict[str, Any]:
    """给 ``subprocess.Popen`` / ``subprocess.run`` 用的隐藏窗口关键字。"""
    if not IS_WINDOWS:
        return {}
    return {
        "creationflags": creation_flags(new_process_group=new_process_group),
        "startupinfo": startup_info(),
    }


def apply_hidden_window(
    kwargs: dict[str, Any],
    *,
    new_process_group: bool = False,
) -> dict[str, Any]:
    """就地给 ``asyncio.create_subprocess_exec`` 的 kwargs 合入隐藏窗口参数。

    asyncio 的 ``create_subprocess_exec`` 把 kwargs 直接转给 ``subprocess.Popen``，
    所以能收 ``creationflags``/``startupinfo``。已有的 ``creationflags`` 会被
    按位或进来（例如调用方已经要了 ``CREATE_NEW_PROCESS_GROUP``），不覆盖。
    """
    if not IS_WINDOWS:
        return kwargs
    existing = int(kwargs.get("creationflags") or 0)
    kwargs["creationflags"] = existing | creation_flags(new_process_group=new_process_group)
    if kwargs.get("startupinfo") is None:
        info = startup_info()
        if info is not None:
            kwargs["startupinfo"] = info
    return kwargs


__all__ = [
    "CREATE_NEW_PROCESS_GROUP",
    "CREATE_NO_WINDOW",
    "IS_WINDOWS",
    "STARTF_USESHOWWINDOW",
    "SW_HIDE",
    "apply_hidden_window",
    "creation_flags",
    "hidden_kwargs",
    "startup_info",
]
