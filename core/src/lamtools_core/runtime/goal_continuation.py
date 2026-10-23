"""Goal continuation reminder helpers.

user:“有 goal 生效时，模型主动结束回合和起一个新的回合并追加：存在目标：xxx 未完成，请继续”
+目标仍激活时，回合自然结束就起新回合；提醒单独成一条消息，与排队消息一起进入同一回合。
user:“但是用压缩后自动追加用户消息里面剔除”+提醒带标记，压缩输入会跳过它。
"""

from __future__ import annotations

from typing import Any

from lamtools_core.llm import ChatMessage

GOAL_CONTINUATION_KEY = "goal_continuation"


def goal_continuation_text(objective: str) -> str:
    """Return the fixed reminder appended to the next turn."""
    return f"存在目标：{str(objective or '').strip()} 未完成，请继续。"


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
