"""user:“查一下信箱的实现，唤醒有什么触发？”+(唤醒链路改为由信箱承载：消息带
唤醒标记即唤醒；完成/失败/message/question 全部连上唤醒标记，事件表降级为审计。)

These tests lock the mailbox-driven wake contract:

* the mailbox carries ``tags`` / ``wake`` / ``wake_count`` and an old database
  gains the columns in place (no data loss),
* a message marked ``wake`` is what makes a parent thread wake-worthy — a
  plain ``message`` without the flag never does,
* peeking never claims, claiming happens only after a turn actually started,
* undelivered legacy events are migrated to wake messages exactly once,
* a question the parent ignored twice is auto-released instead of waking the
  parent forever.
"""
from __future__ import annotations

import json
import sqlite3
import time

from lamtools_core.sub_agent_supervisor import (
    SubAgentSupervisor,
    auto_release_unanswered,
    bump_wake_counts,
    list_threads_with_pending_wakes,
    mark_mailbox_wake_delivered,
    migrate_pending_member_events_to_wake,
    peek_wake_messages,
)

OLD_MAILBOX_DDL = """
CREATE TABLE sub_agent_mailbox (
  id TEXT PRIMARY KEY, parent_thread_id TEXT NOT NULL, name TEXT NOT NULL,
  direction TEXT NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL,
  message_key TEXT NOT NULL, created_at REAL NOT NULL, delivered_at REAL,
  UNIQUE(parent_thread_id, name, direction, message_key)
)
"""


class _Runner:
    work_root = ""


def _supervisor(tmp_path, thread: str = "parent") -> SubAgentSupervisor:
    return SubAgentSupervisor(
        parent_thread_id=thread,
        runner=_Runner(),
        database_path=tmp_path / "state.sqlite3",
    )


def _columns(path) -> set[str]:
    with sqlite3.connect(path) as db:
        return {str(row[1]) for row in db.execute("PRAGMA table_info(sub_agent_mailbox)")}


def _seed_event(path, *, event: str = "member_finished", key: str = "k1") -> None:
    payload = {
        "event": event,
        "name": "worker",
        "type": "member",
        "status": "completed",
        "summary": "done",
    }
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO sub_agent_events(id,parent_thread_id,name,payload,event_key,created_at) "
            "VALUES(?,?,?,?,?,?)",
            ("e1", "parent", "worker", json.dumps(payload), key, time.time()),
        )


def test_old_mailbox_gains_wake_columns_in_place(tmp_path):
    path = tmp_path / "state.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(OLD_MAILBOX_DDL)
        db.execute(
            "INSERT INTO sub_agent_mailbox(id,parent_thread_id,name,direction,body,digest,message_key,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("m1", "parent", "worker", "child_to_parent", "旧消息", "d", "k1", time.time()),
        )
    _supervisor(tmp_path)
    assert {"tags", "wake", "wake_count"} <= _columns(path)
    # 旧行保留，且默认不唤醒
    assert list_threads_with_pending_wakes(path) == []


def test_wake_message_makes_thread_wake_worthy(tmp_path):
    supervisor = _supervisor(tmp_path)
    assert supervisor._mail(
        "worker", "child_to_parent", "需要你回答", message_key="q1", tags="question", wake=1
    )
    assert list_threads_with_pending_wakes(supervisor.database_path) == ["parent"]
    items = peek_wake_messages(supervisor.database_path, "parent")
    assert len(items) == 1
    assert items[0]["tags"] == "question"
    assert items[0]["body"] == "需要你回答"


def test_plain_message_without_wake_never_wakes(tmp_path):
    supervisor = _supervisor(tmp_path)
    assert supervisor._mail(
        "worker", "child_to_parent", "进度汇报", message_key="p1", tags="message", wake=0
    )
    assert list_threads_with_pending_wakes(supervisor.database_path) == []


def test_peek_does_not_claim_and_claim_clears_wake(tmp_path):
    supervisor = _supervisor(tmp_path)
    supervisor._mail("worker", "child_to_parent", "要删除吗", message_key="q1", tags="question", wake=1)
    items = peek_wake_messages(supervisor.database_path, "parent")
    assert peek_wake_messages(supervisor.database_path, "parent") == items  # 未被 claim
    mark_mailbox_wake_delivered(
        supervisor.database_path, "parent", [str(item["id"]) for item in items]
    )
    assert peek_wake_messages(supervisor.database_path, "parent") == []
    assert list_threads_with_pending_wakes(supervisor.database_path) == []


def test_legacy_events_migrate_to_wake_messages_once(tmp_path):
    supervisor = _supervisor(tmp_path)
    _seed_event(supervisor.database_path)
    migrated = migrate_pending_member_events_to_wake(supervisor.database_path)
    assert migrated == 1
    items = peek_wake_messages(supervisor.database_path, "parent")
    assert len(items) == 1
    assert items[0]["tags"] == "member_finished"
    assert "done" in items[0]["body"]
    # 幂等：第二次不再新增，事件行已被标记投递
    assert migrate_pending_member_events_to_wake(supervisor.database_path) == 0
    assert len(peek_wake_messages(supervisor.database_path, "parent")) == 1
    with sqlite3.connect(supervisor.database_path) as db:
        assert db.execute("SELECT delivered_at FROM sub_agent_events").fetchone()[0] is not None


def test_ignored_question_is_auto_released_not_woken_forever(tmp_path):
    supervisor = _supervisor(tmp_path)
    supervisor._mail("worker", "child_to_parent", "要删除吗", message_key="q1", tags="question", wake=1)
    items = peek_wake_messages(supervisor.database_path, "parent")
    ids = [str(item["id"]) for item in items]
    mark_mailbox_wake_delivered(supervisor.database_path, "parent", ids)
    assert bump_wake_counts(supervisor.database_path, "parent", ids) == 1
    assert auto_release_unanswered(supervisor.database_path, "parent") == []
    mark_mailbox_wake_delivered(supervisor.database_path, "parent", ids)
    bump_wake_counts(supervisor.database_path, "parent", ids)
    # 已达上限：不再唤醒，改为写一条「按合理默认继续」给子代理
    assert auto_release_unanswered(supervisor.database_path, "parent") == ["worker"]
    replies = supervisor.pending_guidance("worker")
    assert replies and "默认" in replies[0]["body"]
    assert auto_release_unanswered(supervisor.database_path, "parent") == []
