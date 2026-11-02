"""A turn that settles must reach every client's session list, not just its own.

The sidebar reads each session's status from ``/sessions`` and only refreshes
that list when the server says something changed. Terminal run items used to be
published to the owning thread's subscribers only, so a session finishing in the
background never reached a client watching another session: its row kept
spinning until the user opened it (reported 2026-10-31 as "做完了还是在这转啊，
也没有弹窗提示，只有点进去才知道已经完成任务了").
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from lamtools_core.app.event_store import AppEventEnvelope
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.session_notifications import settled_session_notice
from lamtools_core.event import RunItemEvent

THREAD = "thread-background"
OTHER_THREAD = "thread-visible"


def _envelope(run_item: RunItemEvent) -> AppEventEnvelope:
    return AppEventEnvelope(
        event_id=run_item.event_id,
        protocol_version="core.app_server.v1",
        seq=run_item.seq or 1,
        thread_id=run_item.thread_id,
        method="core/runItem",
        payload=run_item.to_dict(),
        created_at=datetime.now(),
        turn_id=run_item.turn_id,
        item_id=run_item.item_id,
    )


def _turn_status(
    status: str,
    *,
    payload: dict | None = None,
    thread_id: str = THREAD,
    turn_id: str = "turn-1",
) -> RunItemEvent:
    return RunItemEvent(
        kind="status",
        thread_id=thread_id,
        event_id=f"{thread_id}:{turn_id}:{status}",
        run_id="run-1",
        turn_id=turn_id,
        item_id="turn-1:terminal",
        status=status,  # type: ignore[arg-type]
        payload={"type": "turn", "status": status, **(payload or {})},
    )


async def _drain(queue: asyncio.Queue) -> list[object]:
    items: list[object] = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


async def test_terminal_status_becomes_a_session_updated_notice_for_every_connection():
    hub = CoreAppEventHub()
    owner = hub.subscribe(THREAD)
    viewer = hub.subscribe(OTHER_THREAD)

    await hub.publish(_envelope(_turn_status("completed")))

    notices = [item for item in await _drain(viewer) if isinstance(item, dict)]
    assert notices, "a client watching another session must be told the background one settled"
    assert notices[-1] == {
        "method": "session/updated",
        "thread_id": THREAD,
        "turn_id": "turn-1",
        "payload": {"session": {"id": THREAD, "status": "completed"}},
    }
    # The owning connection still receives its terminal item, then the notice.
    owner_items = await _drain(owner)
    assert any(not isinstance(item, dict) for item in owner_items), "the terminal item is unchanged"
    assert any(isinstance(item, dict) for item in owner_items), "the owner gets the notice too"


async def test_non_terminal_and_child_rows_do_not_notify():
    hub = CoreAppEventHub()
    viewer = hub.subscribe(OTHER_THREAD)

    running = _turn_status("running", payload={"status": "running"})
    member_done = RunItemEvent(
        kind="message",
        thread_id=THREAD,
        event_id="member-done",
        turn_id="turn-1",
        item_id="worker:status",
        status="completed",
        payload={"type": "subAgentStatus", "sub_agent": {"name": "worker", "status": "idle"}},
    )
    for item in (running, member_done):
        await hub.publish(_envelope(item))

    assert await _drain(viewer) == [], "only a settled turn refreshes the session list"


def test_paused_and_failed_also_settle_the_row():
    for status in ("failed", "paused", "cancelled"):
        notice = settled_session_notice(_envelope(_turn_status(status)))
        assert notice is not None, status
        assert notice["payload"]["session"]["status"] == status


def test_backfilled_terminal_status_without_a_payload_type_still_settles():
    # The queue-drain path writes a bare terminal status item (no payload.type);
    # it must settle the row just like the kernel's own terminal projection.
    event = RunItemEvent(
        kind="status",
        thread_id=THREAD,
        event_id="turn-1:terminal",
        run_id="turn-1",
        turn_id="turn-1",
        item_id="turn-1:terminal",
        status="completed",
    )
    notice = settled_session_notice(_envelope(event))
    assert notice is not None
    assert notice["payload"]["session"] == {"id": THREAD, "status": "completed"}


def test_notice_is_derived_from_the_run_item_payload_not_its_method():
    assert settled_session_notice({"method": "session/updated", "thread_id": THREAD}) is None
    assert settled_session_notice(_envelope(_turn_status("running"))) is None


def test_slash_command_terminal_status_does_not_settle_the_session():
    # /compact 在主线回合仍在跑时写一条合成 turn 的终态；若据此刷新会话列表，
    # 侧栏会在任务进行中显示“已完成/失败”。
    compact = _turn_status(
        "completed",
        thread_id=THREAD,
        turn_id=f"{THREAD}:command:compact:abc123",
    )
    assert settled_session_notice(_envelope(compact)) is None


async def test_repeated_terminal_status_is_broadcast_once():
    hub = CoreAppEventHub()
    viewer = hub.subscribe(OTHER_THREAD)
    event = _envelope(_turn_status("completed"))

    await hub.publish(event)
    await hub.publish(event)

    notices = [item for item in await _drain(viewer) if isinstance(item, dict)]
    assert len(notices) == 1
