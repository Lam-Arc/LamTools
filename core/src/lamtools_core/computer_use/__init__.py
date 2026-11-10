"""Computer Use：让 Agent 像人一样看屏幕、动鼠标键盘。

分层：
- ``win32``   系统调用，无状态，坐标一律物理像素
- ``capture`` 截图编码、缩放、标注
- ``uia``     常驻 PowerShell 助手，读无障碍树并做语义点击
- ``session`` 任务状态、安全守卫、用户接管
- ``tools``   对模型暴露的 computer_use 工具

user:“查一下 computer use 功能怎么做”+(屏幕理解、鼠标键盘、窗口管理、多步骤
任务，用户可随时接管)。
"""

from .session import GuardError, Session, current, shutdown as shutdown_session
from .tools import handle as handle_tool
from .tools import make_computer_use_handler
from .uia import shutdown_shared

__all__ = [
    "GuardError",
    "Session",
    "current",
    "handle_tool",
    "make_computer_use_handler",
    "shutdown",
]


def shutdown() -> None:
    """进程退出时收掉助手子进程，避免残留 PowerShell。"""
    shutdown_session()
    shutdown_shared()
