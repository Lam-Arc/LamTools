"""user:“Question 是纯提问工具…三种提问类型 single / multiple / text”+(提问数据结构
统一规范：id/title/description/type/required/options/placeholder，并兼容旧调用。)

These tests lock the question payload contract:

* an old-style call (``question`` + ``options`` + ``multiSelect``) normalises to
  exactly one question with a stable id, a type derived from its options and
  ``required`` defaulting to true (asking used to mean waiting),
* a new-style ``questions`` list keeps every declared field,
* a question without options degrades to plain text,
* malformed payloads are rejected instead of reaching the interface.
"""
from __future__ import annotations

import pytest

from lamtools_core.tool.question_spec import normalize_questions


def test_legacy_single_question_normalises():
    questions = normalize_questions(
        {"question": "要继续吗？", "options": [{"label": "继续"}, {"label": "停止"}], "context": "背景"}
    )
    assert len(questions) == 1
    item = questions[0]
    assert item["id"] == "q1"
    assert item["title"] == "要继续吗？"
    assert item["type"] == "single"
    assert item["required"] is True
    assert item["placeholder"] == ""
    assert [option["label"] for option in item["options"]] == ["继续", "停止"]


def test_legacy_multi_select_becomes_multiple():
    questions = normalize_questions(
        {"question": "选哪些？", "multiSelect": True, "options": [{"label": "A"}, {"label": "B"}]}
    )
    assert questions[0]["type"] == "multiple"


def test_question_without_options_degrades_to_text():
    questions = normalize_questions({"question": "说说你的想法"})
    assert questions[0]["type"] == "text"
    assert questions[0]["options"] == []


def test_new_style_questions_keep_declared_fields():
    questions = normalize_questions(
        {
            "questions": [
                {
                    "id": "doc",
                    "title": "用哪份文档？",
                    "description": "只选一份",
                    "type": "single",
                    "required": False,
                    "options": [{"label": "A", "description": "旧版"}, "B"],
                    "placeholder": "或者直接说文件名",
                },
                {"id": "why", "title": "为什么？", "type": "text", "required": True},
            ]
        }
    )
    assert [item["id"] for item in questions] == ["doc", "why"]
    assert questions[0]["required"] is False
    assert questions[0]["placeholder"] == "或者直接说文件名"
    assert questions[0]["options"][1] == {"label": "B", "description": ""}
    assert questions[1]["type"] == "text"


def test_declared_text_type_drops_options():
    questions = normalize_questions(
        {"questions": [{"title": "随便说", "type": "text", "options": [{"label": "A"}]}]}
    )
    assert questions[0]["type"] == "text"
    assert questions[0]["options"] == []


def test_too_many_questions_is_rejected():
    with pytest.raises(ValueError):
        normalize_questions({"questions": [{"title": f"问题{i}"} for i in range(11)]})


def test_empty_payload_is_rejected():
    with pytest.raises(ValueError):
        normalize_questions({})


def test_duplicate_ids_are_rejected():
    with pytest.raises(ValueError):
        normalize_questions(
            {"questions": [{"id": "same", "title": "一"}, {"id": "same", "title": "二"}]}
        )


def test_unknown_type_is_rejected():
    with pytest.raises(ValueError):
        normalize_questions({"questions": [{"title": "题目", "type": "range"}]})


def test_duplicate_option_labels_are_rejected():
    with pytest.raises(ValueError):
        normalize_questions(
            {"questions": [{"title": "题目", "options": [{"label": "A"}, {"label": "A"}]}]}
        )


def test_non_boolean_required_is_rejected():
    with pytest.raises(ValueError):
        normalize_questions({"questions": [{"title": "题目", "required": "yes"}]})


def test_blank_title_is_rejected():
    with pytest.raises(ValueError):
        normalize_questions({"questions": [{"title": "   "}]})
