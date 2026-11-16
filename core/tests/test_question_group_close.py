"""Closing a question group: the answered path and the skipped path share one close."""
from __future__ import annotations

from types import SimpleNamespace

from lamtools_core.app.live.question_groups import close_pending_question_groups


def make_state(groups):
    return SimpleNamespace(metadata={"question_groups": groups})


def make_group(group_id: str, status: str = "pending", question_status: str = "pending"):
    return {
        "group_id": group_id,
        "status": status,
        "questions": [
            {"id": "q1", "title": "要不要继续？", "status": question_status},
            {"id": "q2", "title": "补充说明", "status": question_status},
        ],
    }


def test_skip_closes_the_group_without_inventing_answers():
    group = make_group("g1")
    state = make_state([group])

    closed = close_pending_question_groups(state, reason="skipped")

    assert closed == 1
    assert group["status"] == "done"
    assert group["closed_reason"] == "skipped"
    assert isinstance(group["closed_at_ms"], int)
    # 跳过不产生答案：题级状态原样保留
    assert [question["status"] for question in group["questions"]] == ["pending", "pending"]
    assert all("answer" not in question for question in group["questions"])


def test_answered_path_backfills_only_the_answers_it_received():
    group = make_group("g1")
    state = make_state([group])

    closed = close_pending_question_groups(
        state,
        reason="user_message",
        answers={"g1": {"q1": "继续"}},
    )

    assert closed == 1
    assert group["closed_reason"] == "user_message"
    assert group["questions"][0]["status"] == "answered"
    assert group["questions"][0]["answer"] == "继续"
    # 没回答的那题不能被补成空答案
    assert group["questions"][1]["status"] == "pending"
    assert "answer" not in group["questions"][1]


def test_already_closed_groups_are_left_alone():
    done = make_group("g1", status="done")
    done["closed_reason"] = "user_message"
    pending = make_group("g2")
    state = make_state([done, pending])

    closed = close_pending_question_groups(state, reason="skipped")

    assert closed == 1
    assert done["closed_reason"] == "user_message"
    assert pending["closed_reason"] == "skipped"


def test_nothing_to_close_reports_zero():
    assert close_pending_question_groups(make_state([]), reason="skipped") == 0
    assert close_pending_question_groups(SimpleNamespace(metadata={}), reason="skipped") == 0
    assert close_pending_question_groups(SimpleNamespace(metadata=None), reason="skipped") == 0
