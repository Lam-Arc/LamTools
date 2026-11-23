"""内置浏览器的 Agent 侧：请求通道 + browser 工具。

user:“让 Agent Loop 能直接调用：打开/切换标签、快照、点击、输入、等待、截图”+
(工具在 Core 进程，浏览器在桌面宿主的子 webview 里；中间只有一条内存队列，
主窗口把它翻译成 Tauri 命令执行。没有第二条通道，也没有特权。)

分层：
- ``agent``  请求队列、等待与超时、不可信信封
- ``tools``  对模型暴露的 ``browser`` 工具（ref 驱动，不接受即席脚本）
"""

from __future__ import annotations

from .agent import (
    BrowserChannelError,
    envelope,
    call,
    queue,
    submit_result,
    take_pending,
)
from .tools import (
    BROWSER_ACTIONS,
    BROWSER_TOOL_DESCRIPTION,
    BROWSER_TOOL_NAME,
    BROWSER_TOOL_SCHEMA,
    HIGH_RISK_INTENTS,
    WRITE_ACTIONS,
    make_browser_handler,
)

__all__ = [
    "BROWSER_ACTIONS",
    "BROWSER_TOOL_DESCRIPTION",
    "BROWSER_TOOL_NAME",
    "BROWSER_TOOL_SCHEMA",
    "BrowserChannelError",
    "HIGH_RISK_INTENTS",
    "WRITE_ACTIONS",
    "call",
    "envelope",
    "make_browser_handler",
    "queue",
    "submit_result",
    "take_pending",
]
