"""Computer Use 任务状态、安全守卫与用户接管。

一次只允许一个任务在跑：两个任务抢鼠标没有任何意义，还会让状态互相覆盖。
每次动作前都要过 guard，它检查四件事：任务在跑、没超步数、没超时、用户没有
动过真实输入。用户一动，任务自动转 paused，控制权立刻回到人手上。

user:“查一下 computer use 功能怎么做”+(用户可随时接管、干预或恢复任务，
所以接管检测放在动作执行之前，而不是事后报告)。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import win32
from .capture import Frame

# 用户输入与注入之间留的余波窗口：注入完成后系统也会更新“最后输入时间”，
# 这个窗口内的更新算我们自己造成的。
_INJECT_TAIL_MS = 350
# 光标偏离上一次注入位置超过这个距离，认定用户动了鼠标。
_CURSOR_TOLERANCE_PX = 10


class GuardError(RuntimeError):
    """动作被安全守卫拒绝。"""


@dataclass
class Step:
    index: int
    action: str
    detail: str
    ok: bool
    at: float
    screenshot: str = ""
    error: str = ""


@dataclass
class Session:
    task_id: str
    goal: str
    state: str = "running"  # running | paused | stopped | failed
    started_at: float = field(default_factory=time.monotonic)
    deadline: float = 0.0
    max_steps: int = 40
    steps: list[Step] = field(default_factory=list)
    pause_reason: str = ""
    last_error: str = ""
    last_frame: Frame | None = None
    last_action_point: tuple[int, int] | None = None
    # 最近一次 snapshot 的目标窗口。每个动作前都要确认它还在前台，
    # 否则点击会落到用户切过去的别的窗口上。
    target_window: int = 0
    _last_inject_tick: int = 0
    _last_cursor: tuple[int, int] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # -- 状态 -------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        remaining = max(0.0, self.deadline - time.monotonic()) if self.deadline else 0.0
        # 覆盖层要画 Agent 光标，坐标转成相对虚拟桌面左上角，前端直接当 CSS 坐标用。
        cursor = None
        if self.last_action_point:
            try:
                vx, vy, _, _ = win32.virtual_screen()
                cursor = [self.last_action_point[0] - vx, self.last_action_point[1] - vy]
            except Exception:
                cursor = None
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "state": self.state,
            "steps": len(self.steps),
            "max_steps": self.max_steps,
            "remaining_seconds": round(remaining, 1),
            "elapsed_seconds": round(time.monotonic() - self.started_at, 1),
            "pause_reason": self.pause_reason,
            "last_error": self.last_error,
            "cursor": cursor,
            "target_window": self.target_window,
            "last_action": (
                {
                    "action": self.steps[-1].action,
                    "detail": self.steps[-1].detail,
                    "ok": self.steps[-1].ok,
                }
                if self.steps
                else None
            ),
        }

    def record(self, action: str, detail: str, *, ok: bool, screenshot: str = "", error: str = "") -> None:
        with self._lock:
            self.steps.append(
                Step(
                    index=len(self.steps) + 1,
                    action=action,
                    detail=detail,
                    ok=ok,
                    at=time.time(),
                    screenshot=screenshot,
                    error=error,
                )
            )
            if error:
                self.last_error = error

    def mark_injected(self) -> None:
        """注入之后调用：吸收输入余波并记住光标位置。"""
        time.sleep(_INJECT_TAIL_MS / 1000.0)
        with self._lock:
            self._last_inject_tick = win32.last_input_tick()
            try:
                self._last_cursor = win32.cursor_position()
            except Exception:
                self._last_cursor = None

    def user_took_over(self) -> bool:
        """真实输入检测：注入余波之后又有输入，或者光标被挪走了。"""
        with self._lock:
            baseline_tick = self._last_inject_tick
            baseline_cursor = self._last_cursor
        if not baseline_tick:
            return False
        try:
            if win32.input_since(baseline_tick) > _INJECT_TAIL_MS:
                return True
            if baseline_cursor is not None:
                cx, cy = win32.cursor_position()
                if (
                    abs(cx - baseline_cursor[0]) > _CURSOR_TOLERANCE_PX
                    or abs(cy - baseline_cursor[1]) > _CURSOR_TOLERANCE_PX
                ):
                    return True
        except Exception:
            return False
        return False

    # -- 守卫 -------------------------------------------------------------

    def guard(self, action: str) -> None:
        with self._lock:
            state = self.state
            max_steps = self.max_steps
            deadline = self.deadline
            count = len(self.steps)
            goal = self.goal
        if state == "paused":
            raise GuardError(
                f"任务已暂停：{self.pause_reason or '用户接管'}。先调用 computer_use action=resume，"
                "或者向用户确认后再继续。"
            )
        if state == "stopped":
            raise GuardError("任务已结束，请重新 start 一个新任务。")
        if state == "failed":
            raise GuardError(f"任务已失败：{self.last_error}。修好问题后重新 start。")
        if count >= max_steps:
            self.fail(f"超过步数上限 {max_steps}，停在「{goal}」")
            raise GuardError(f"超过步数上限 {max_steps}，任务已结束。")
        if deadline and time.monotonic() > deadline:
            self.fail("超过时间上限")
            raise GuardError("超过时间上限，任务已结束。")
        # user:“用户输入暂停这件事儿，到时候跟覆盖层的样式一块儿去做”+
        # (自动暂停先不接进守卫；user_took_over 保留给覆盖层和以后的接管交互用)。

    # -- 转移 -------------------------------------------------------------

    def pause(self, reason: str) -> None:
        with self._lock:
            if self.state == "running":
                self.state = "paused"
                self.pause_reason = reason

    def resume(self) -> None:
        with self._lock:
            if self.state != "paused":
                raise GuardError(f"当前状态是 {self.state}，不能恢复")
            self.state = "running"
            self.pause_reason = ""
            self._last_inject_tick = 0
            self._last_cursor = None

    def stop(self, reason: str = "用户要求结束") -> None:
        with self._lock:
            self.state = "stopped"
            self.pause_reason = reason

    def fail(self, reason: str) -> None:
        with self._lock:
            self.state = "failed"
            self.last_error = reason


_current: Session | None = None
_current_lock = threading.Lock()


def current() -> Session | None:
    with _current_lock:
        return _current


def start(goal: str, *, max_steps: int = 40, timeout_seconds: int = 600) -> Session:
    global _current
    with _current_lock:
        if _current is not None and _current.state in {"running", "paused"}:
            raise GuardError(
                f"已有任务在跑：{_current.task_id}（{_current.goal}）。先 stop 掉它再开新的。"
            )
        session = Session(
            task_id=uuid.uuid4().hex[:12],
            goal=goal.strip() or "未命名桌面任务",
            max_steps=max(1, min(int(max_steps), 200)),
            deadline=time.monotonic() + max(30, min(int(timeout_seconds), 3600)),
        )
        _current = session
        return session


def clear() -> None:
    global _current
    with _current_lock:
        _current = None


def shutdown() -> None:
    """进程退出时收尾：跑着的任务标记结束，避免状态残留。"""
    global _current
    with _current_lock:
        if _current is not None and _current.state in {"running", "paused"}:
            _current.state = "stopped"
            _current.pause_reason = "后端退出"
        _current = None
