"""Super Agent 的工单就是派工提示词：六个段落齐全，且只在 Super Agent 模式下出现。

user:“不需要单独设计实现工单和工作树功能，可以参考其概念：工单概念具象化（可作为给子代理的提示词）”
+(工单不落库、不建对象；Router 按固定格式写一份简报发给子代理，目标一段就是它的 goal；
工作范围可选，git 不可用也不影响派工)。
"""
from __future__ import annotations

from lamtools_core.app.base_agent import _runtime_context_text
from lamtools_core.app.superagent_brief import DISPATCH_BRIEF, dispatch_brief_for


def test_the_brief_only_exists_in_superagent_mode() -> None:
    assert dispatch_brief_for("auto") == DISPATCH_BRIEF
    assert dispatch_brief_for(" chat ") == ""
    assert dispatch_brief_for("work") == ""
    assert dispatch_brief_for(None) == ""


def test_the_brief_keeps_every_section_of_the_ticket_template() -> None:
    for heading in (
        "# <编号｜任务名称>",
        "## 工作范围",
        "## 1. 目标",
        "## 2. 上下文",
        "## 3. 任务",
        "## 4. 约束",
        "## 5. 验收标准",
        "## 6. 交付",
    ):
        assert heading in DISPATCH_BRIEF, f"简报缺少 {heading}"


def test_the_goal_section_is_what_the_sub_agent_optimises_for() -> None:
    assert "这一段就是子代理的 goal" in DISPATCH_BRIEF


def test_the_work_scope_is_optional_and_does_not_require_git() -> None:
    assert "留空就用当前项目目录" in DISPATCH_BRIEF
    assert "不要求 git" in DISPATCH_BRIEF


def test_the_brief_renders_after_the_mode_line() -> None:
    text = _runtime_context_text(
        {
            "mode": "Current mode: superagent — 只对话与派工",
            "dispatch_brief": dispatch_brief_for("auto"),
        }
    )

    assert text.index("Current mode: superagent") < text.index("## 1. 目标")


def test_a_work_session_renders_no_brief() -> None:
    text = _runtime_context_text({"mode": "Current mode: work — 全量工具"})

    assert "## 1. 目标" not in text
