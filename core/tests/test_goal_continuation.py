"""Goal continuation: separate reminder message and compaction exclusion."""

from __future__ import annotations

from lamtools_core.kernel.loop import compaction_input_messages
from lamtools_core.llm import ChatMessage
from lamtools_core.runtime.goal_continuation import (
    GOAL_CONTINUATION_KEY,
    goal_continuation_message,
    goal_continuation_text,
    is_goal_continuation,
    should_continue_goal,
)


def test_goal_continuation_text_uses_objective() -> None:
    assert goal_continuation_text("整理本周会议记录") == "存在目标：整理本周会议记录 未完成，请继续。"


def test_goal_continuation_text_ignores_blank_objective() -> None:
    assert goal_continuation_text("   ") == "存在目标： 未完成，请继续。"


def test_goal_continuation_message_is_separate_and_marked() -> None:
    message = goal_continuation_message("存在目标：写报告 未完成，请继续。")
    assert message.role == "user"
    assert message.content == "存在目标：写报告 未完成，请继续。"
    assert message.metadata == {GOAL_CONTINUATION_KEY: True}
    assert is_goal_continuation(message) is True


def test_is_goal_continuation_checks_metadata() -> None:
    marked = ChatMessage(role="user", content="继续", metadata={GOAL_CONTINUATION_KEY: True})
    normal = ChatMessage(role="user", content="继续", metadata={})
    assert is_goal_continuation(marked) is True
    assert is_goal_continuation(normal) is False


def test_only_natural_completion_continues_goal() -> None:
    assert should_continue_goal(status="ok", decision="done") is True
    assert should_continue_goal(status="error", decision="done") is False
    assert should_continue_goal(status="ok", decision="wait") is False
    assert should_continue_goal(status="ok", decision="cancelled") is False
    assert should_continue_goal(status="ok", decision="") is False


def test_compaction_keeps_queued_message_and_drops_reminder() -> None:
    queued = ChatMessage(role="user", content="用户排队消息", metadata={})
    reminder = goal_continuation_message("存在目标：写报告 未完成，请继续。")
    assert compaction_input_messages([queued, reminder]) == [queued]
