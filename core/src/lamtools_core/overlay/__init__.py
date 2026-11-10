"""Desktop Overlay：Agent 与用户共用的交互层。

user:“AI 直接在屏幕上标记、绘制、互动、发弹幕：箭头、框选、高亮、涂鸦、文字、
悬浮控件、动态提示。标记可跟随窗口和对象，用户能直接点击、圈选、批注，与
Agent 实时互动。”+(标注状态放 Core，覆盖层窗口只负责画；用户批注能从屏幕回到
发起标记的会话)。

分层：
- ``store`` 标注集合、过期、窗口绑定、用户批注队列
- ``tools`` 对模型暴露的 ``desktop_overlay`` 工具
"""

from . import store
from .store import Store, current
from .tools import (
    DESKTOP_OVERLAY_TOOL_DESCRIPTION,
    DESKTOP_OVERLAY_TOOL_NAME,
    DESKTOP_OVERLAY_TOOL_SCHEMA,
    handle,
    make_desktop_overlay_handler,
)

__all__ = [
    "DESKTOP_OVERLAY_TOOL_DESCRIPTION",
    "DESKTOP_OVERLAY_TOOL_NAME",
    "DESKTOP_OVERLAY_TOOL_SCHEMA",
    "Store",
    "current",
    "handle",
    "make_desktop_overlay_handler",
    "store",
]
