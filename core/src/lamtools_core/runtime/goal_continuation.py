"""Goal continuation reminder helpers.

user:“有 goal 生效时，模型主动结束回合和起一个新的回合并追加：存在目标：xxx 未完成，请继续”
+目标仍激活时，回合自然结束就起新回合；提醒单独成一条消息，与排队消息一起进入同一回合。
user:“但是用压缩后自动追加用户消息里面剔除”+提醒带标记，压缩输入会跳过它。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from lamtools_core.llm import ChatMessage

GOAL_CONTINUATION_KEY = "goal_continuation"


def goal_continuation_text(
    objective: str, completion_criteria: Iterable[str] = ()
) -> str:
    """Return the reminder appended to the next turn, or "" without an objective.

    user:“完成标准”+(标准没有外部校验，但要随提醒回到模型眼前，否则它没法判断该不该收口)。
    """
    clean = str(objective or "").strip()
    if not clean:
        return ""
    reminder = f"存在目标：{clean} 未完成，请继续。"
    criteria = [str(item or "").strip() for item in completion_criteria]
    criteria = [item for item in criteria if item]
    if criteria:
        reminder += "完成标准：" + "；".join(criteria)
    return reminder


def goal_continuation_message(reminder: str) -> ChatMessage:
    """Build the reminder as its own user message, marked for compaction exclusion."""
    return ChatMessage(
        role="user",
        content=reminder,
        metadata={GOAL_CONTINUATION_KEY: True},
    )


def should_continue_goal(*, status: str, decision: str) -> bool:
    """Only a successful, naturally finished turn may start a goal turn.

    API errors, retries, pauses and stops must not start another turn, or the
    goal would loop on a failing provider forever.
    """
    return str(status or "") == "ok" and str(decision or "") == "done"


def is_goal_continuation(message: Any) -> bool:
    """True when a message was added by goal continuation, not by the user."""
    metadata = getattr(message, "metadata", None)
    return isinstance(metadata, dict) and metadata.get(GOAL_CONTINUATION_KEY) is True
