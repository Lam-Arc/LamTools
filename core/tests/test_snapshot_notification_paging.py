"""Unsolicited snapshot pushes must not serialize a whole long thread.

user:“也不是完全发不出去 反正卡住了好久”+(64.5MB 的 thread/snapshot 通知会把发送
通道占住几十秒；超过阈值时只推最近 10 个回合的一页，并带上 history_page 供客户端
按页往前翻。)
"""

from __future__ import annotations

from lamtools_core.app.live_router import (
    SNAPSHOT_NOTIFICATION_MAX_ITEMS,
    _snapshot_for_notification,
)


def _snapshot(item_count: int) -> dict:
    items: dict[str, dict] = {}
    order: list[str] = []
    turns: dict[str, dict] = {}
    for index in range(item_count):
        turn_id = f"turn-{index // 10}"
        item_id = f"item-{index}"
        items[item_id] = {
            "item_id": item_id,
            "turn_id": turn_id,
            "seq": index + 1,
            "type": "message",
            "content": [{"type": "text", "text": "x" * 80}],
        }
        order.append(item_id)
        turn = turns.setdefault(
            turn_id, {"turn_id": turn_id, "status": "completed", "items": []}
        )
        turn["items"].append(item_id)
    return {
        "thread_id": "thread-page",
        "snapshot_seq": item_count,
        "revision": 3,
        "items": {},
        "item_order": [],
        "turns": {},
        "core": {
            "thread_id": "thread-page",
            "snapshot_seq": item_count,
            "revision": 3,
            "items": items,
            "item_order": order,
            "turns": turns,
        },
    }


def test_small_snapshot_notification_is_not_paged() -> None:
    snapshot = _snapshot(20)
    assert _snapshot_for_notification(snapshot) is snapshot


def test_large_snapshot_notification_is_paged_by_turns() -> None:
    snapshot = _snapshot(SNAPSHOT_NOTIFICATION_MAX_ITEMS + 120)
    paged = _snapshot_for_notification(snapshot)

    assert paged is not snapshot
    page = paged.get("history_page")
    assert isinstance(page, dict)
    assert page.get("has_more") is True
    assert len(paged["core"]["item_order"]) < len(snapshot["core"]["item_order"])
    assert len(paged["core"]["item_order"]) <= 10 * 10
    # The newest items survive; older ones are reachable through the page cursor.
    assert paged["core"]["item_order"][-1] == snapshot["core"]["item_order"][-1]
