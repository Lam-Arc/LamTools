"""user:“已确认但尚未提交的回答应与该消息一并携带”+(输入栏回答没有结构化参数，
界面拼出的 `Q<n> <题目>：<回答>` 行必须能回填到组里的题级状态。)
"""
from __future__ import annotations

from lamtools_core.app.default_agent import _question_answers_from_message


def _group(*ids: str) -> dict:
    return {"questions": [{"id": identifier, "title": f"题{index}"} for index, identifier in enumerate(ids)]}


def test_answers_are_mapped_by_question_order():
    message = "Q1 要继续吗？：对，继续\nQ2 用哪份文档：旧版"
    assert _question_answers_from_message(message, _group("q1", "q2")) == {
        "q1": "对，继续",
        "q2": "旧版",
    }


def test_blank_or_out_of_range_lines_are_ignored():
    message = "Q1 要继续吗？：\nQ9 不存在：忽略\n随便一句：也不是答案"
    assert _question_answers_from_message(message, _group("q1")) == {}


def test_full_width_and_half_width_colons_both_work():
    message = "Q1 a:b\nQ2 c：d"
    assert _question_answers_from_message(message, _group("q1", "q2")) == {
        "q1": "b",
        "q2": "d",
    }
