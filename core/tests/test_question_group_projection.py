"""Closed question groups must reach the transcript as facts.

user:“我这一张卡明明回答了…随后又出现在我的回答下方，且变成了未回答，但是根据模型的回复
它确实收到了我的回答”+(关闭提问组以前只改运行状态，投影永远看到 waiting，界面只能靠本地
记忆判断"已回答"。这里钉住两件事：关闭时能交出被关的组；投影按关闭原因转成 completed 并
带上答案，且身份与原提问分片一致。)
"""
from __future__ import annotations

from types import SimpleNamespace

from lamtools_core.app.live.question_groups import close_pending_question_groups
from lamtools_core.event.runtime_projection import (
    RuntimeProjectionInput,
    runtime_projection_to_run_item_events,
)


def make_group(group_id: str = "g1") -> dict:
    return {
        "group_id": group_id,
        "call_id": "call-1",
        "run_id": "run-1",
        "status": "pending",
        "asked_at_ms": 1,
        "questions": [
            {"id": "q1", "title": "要不要继续？", "type": "single", "required": True,
             "options": [{"label": "继续"}, {"label": "停止"}], "status": "pending"},
        ],
    }


def project(payload: dict) -> list:
    fact = RuntimeProjectionInput(
        id="e1",
        thread_id="t1",
        group="plan",
        source="core",
        phase="runtime.question_group",
        status="waiting",
        sequence=1,
        metadata={"payload": payload},
    )
    return runtime_projection_to_run_item_events(fact)


def test_close_reports_the_groups_it_closed():
    state = SimpleNamespace(metadata={"question_groups": [make_group()]})
    closed = []

    count = close_pending_question_groups(
        state,
        reason="user_message",
        answers={"g1": {"q1": "继续"}},
        closed_out=closed,
    )

    assert count == 1
    assert [group["group_id"] for group in closed] == ["g1"]
    assert closed[0]["status"] == "done"
    assert closed[0]["closed_reason"] == "user_message"
    assert closed[0]["questions"][0]["answer"] == "继续"


def test_projection_keeps_a_pending_group_waiting():
    events = project({
        "group_id": "g1",
        "call_id": "call-1",
        "run_id": "run-1",
        "status": "pending",
        "questions": [{"id": "q1", "title": "要不要继续？", "required": True}],
    })

    assert events[0].status == "waiting"
    assert "closed_reason" not in events[0].payload


def test_projection_turns_a_closed_group_into_completed_with_answers():
    events = project({
        "group_id": "g1",
        "call_id": "call-1",
        "run_id": "run-1",
        "status": "done",
        "closed_reason": "user_message",
        "questions": [
            {"id": "q1", "title": "要不要继续？", "required": True,
             "status": "answered", "answer": "继续"},
        ],
    })

    event = events[0]
    assert event.status == "completed"
    assert event.payload["closed_reason"] == "user_message"
    assert event.payload["questions"][0]["answer"] == "继续"
    # 同一 run_id + call_id 必须落回同一张卡
    assert event.item_id.endswith(":call-1:tool:question")


def test_projection_identity_matches_the_original_question_event():
    payload = {
        "group_id": "g1",
        "call_id": "call-1",
        "run_id": "run-1",
        "questions": [{"id": "q1", "title": "要不要继续？"}],
    }
    pending = project({**payload, "status": "pending"})[0]
    closed = project({**payload, "status": "done", "closed_reason": "skipped"})[0]
    assert pending.item_id == closed.item_id


def test_a_closed_group_accepts_an_appended_answer():
    """user:“已回答过的卡展开之后再补充回答，点确定之后会出问题”+(
    已关闭的组必须收下补答：以前整组跳过，补答既不进组状态也不发事件。)"""
    state = SimpleNamespace(metadata={"question_groups": [make_group()]})
    close_pending_question_groups(state, reason="user_message", answers={"g1": {"q1": "继续"}})

    appended = []
    count = close_pending_question_groups(
        state,
        reason="user_message",
        answers={"g1": {"q1": "停止"}},
        closed_out=appended,
    )

    # 不重复计一次关闭，但要交出被更新的组，且答案被覆盖成最新一次
    assert count == 0
    assert [group["group_id"] for group in appended] == ["g1"]
    assert appended[0]["questions"][0]["answer"] == "停止"
    assert appended[0]["closed_reason"] == "user_message"
