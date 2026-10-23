"""Session-automation preferences (设置 → 通用).

``core.askAutoContinue`` = ``{"enabled": bool}`` — 「提问自动继续」.

开启后，模型的**提问卡**（``question`` 工具）满 :data:`ASK_AUTO_CONTINUE_TIMEOUT_MINUTES`
分钟无人回答，就按「用户跳过」回传，本轮继续往下走。

**权限审批卡不在此列**：审批是安全边界，超时不代表同意，只有人（或用户显式配置的
权限策略）能放行；审批卡会一直等下去。

The timer本身 runs in the desktop shell (it is the surface that renders and
answers the card); this module owns the stored preference, its validation and
the CLI/status view so the switch has one canonical home.
"""

from __future__ import annotations

from typing import Any

from lamtools_core.config.settings_store import get_setting

ASK_AUTO_CONTINUE_NAMESPACE = "core.askAutoContinue"

#: 无人回答的等待窗口（分钟）——与 ZCode 常规页的 5 分钟一致。
ASK_AUTO_CONTINUE_TIMEOUT_MINUTES = 5

#: The exact answer the backend submits when the window expires.  The wording
#: tells the model this was a timeout, not a user choice.
ASK_SKIP_GUIDANCE = "用户跳过回答：等待 5 分钟未响应，未收集到用户答案。"


def ask_auto_continue_enabled() -> bool:
    stored = get_setting(ASK_AUTO_CONTINUE_NAMESPACE)
    return bool(isinstance(stored, dict) and stored.get("enabled"))


def merge_ask_auto_continue(current: Any, incoming: dict[str, Any]) -> dict[str, Any] | None:
    """Merge a ``core.askAutoContinue`` update; ``None`` rejects an invalid value."""
    merged = {**(current if isinstance(current, dict) else {})}
    for key, raw in incoming.items():
        if key != "enabled":
            # Unknown keys are dropped rather than persisted.
            continue
        if not isinstance(raw, bool):
            return None
        merged[key] = raw
    merged.setdefault("enabled", False)
    return merged


def ask_auto_continue_status() -> dict[str, Any]:
    return {
        "enabled": ask_auto_continue_enabled(),
        "timeout_minutes": ASK_AUTO_CONTINUE_TIMEOUT_MINUTES,
        "applies_to": "question",
    }


__all__ = [
    "ASK_AUTO_CONTINUE_NAMESPACE",
    "ASK_AUTO_CONTINUE_TIMEOUT_MINUTES",
    "ASK_SKIP_GUIDANCE",
    "ask_auto_continue_enabled",
    "ask_auto_continue_status",
    "merge_ask_auto_continue",
]
