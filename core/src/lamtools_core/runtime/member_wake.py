"""Bookkeeping for the automatic wake that delivers finished sub-agents.

A member's lifecycle event is drained by the kernel while a parent turn is
alive. When the turn has already ended nobody drains it, so the watchdog in
``app/memory_resume_supervisor.py`` starts a new turn in the same session to
consume it. That is the second (and last) thing in the product that may start a
turn nobody asked for, so it is bounded the same way the memory auto-resume is:
a consecutive-attempt counter on the session's runtime state, reset when a
user-originated turn starts, and reported rather than silently dropped once the
budget is spent.

The counter is deliberately *not* cleared by the wake's own turn. The wake marks
the state before it starts the turn (``mark_member_wake_autostart``) so the
kernel can tell its own automatic turn apart from a turn the user sent; only the
latter resets the streak.
"""

from __future__ import annotations

from typing import Any

#: Consecutive automatic member wakes without an intervening user turn.
#: Mirrors ``memory_guard.MEMORY_RESUME_MAX_ATTEMPTS`` in spirit: enough for a
#: real fan-out of members finishing at different times, small enough that a
#: member which rediscovers itself and finishes in a loop cannot spin forever.
MEMBER_WAKE_MAX_CONSECUTIVE = 10

#: Runtime-state metadata key holding the streak.
MEMBER_WAKE_STREAK_KEY = "member_wake_streak"

#: Runtime-state metadata flag marking a turn the watchdog started itself.
MEMBER_WAKE_AUTOSTART_KEY = "member_wake_autostart"


def _metadata(state: Any) -> dict[str, Any]:
    metadata = getattr(state, "metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def member_wake_streak(state: Any) -> int:
    raw = _metadata(state).get(MEMBER_WAKE_STREAK_KEY)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0
    return max(0, raw)


def member_wake_exhausted(state: Any) -> bool:
    return member_wake_streak(state) >= MEMBER_WAKE_MAX_CONSECUTIVE


def note_member_wake(state: Any) -> None:
    _metadata(state)[MEMBER_WAKE_STREAK_KEY] = member_wake_streak(state) + 1


def clear_member_wake_streak(state: Any) -> None:
    _metadata(state).pop(MEMBER_WAKE_STREAK_KEY, None)


def mark_member_wake_autostart(state: Any) -> None:
    _metadata(state)[MEMBER_WAKE_AUTOSTART_KEY] = True


def clear_member_wake_autostart(state: Any) -> None:
    _metadata(state).pop(MEMBER_WAKE_AUTOSTART_KEY, None)


def consume_member_wake_autostart(state: Any) -> bool:
    """Read and clear the autostart flag; True when THIS turn was our wake."""
    return bool(_metadata(state).pop(MEMBER_WAKE_AUTOSTART_KEY, False))


def member_wake_exhausted_message(limit: int = MEMBER_WAKE_MAX_CONSECUTIVE) -> str:
    return (
        f"成员事件已连续自动续跑 {limit} 次，不再自动开启新一轮；"
        "请在会话里发一条消息继续。"
    )


__all__ = [
    "MEMBER_WAKE_AUTOSTART_KEY",
    "MEMBER_WAKE_MAX_CONSECUTIVE",
    "MEMBER_WAKE_STREAK_KEY",
    "clear_member_wake_autostart",
    "clear_member_wake_streak",
    "consume_member_wake_autostart",
    "mark_member_wake_autostart",
    "member_wake_exhausted",
    "member_wake_exhausted_message",
    "member_wake_streak",
    "note_member_wake",
]
