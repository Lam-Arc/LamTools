"""Public, host-independent Python session control contract.

user:“每一个地方 sunday 都有等价或者近似接口”+(会话调用使用明确的接收回执、被动状态和持久事件，不冒充完整 DSH Agent 对象)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal, Protocol, runtime_checkable

from .services import ServiceKey


class SessionError(RuntimeError):
    def __init__(self, code: str, session_id: str, message: str, *, details: dict | None = None) -> None:
        self.code, self.session_id, self.details = code, session_id, dict(details or {})
        super().__init__(f"{code}: {session_id}: {message}")


@dataclass(frozen=True)
class SessionState:
    session_id: str
    last_event_seq: int
    status: str
    running: bool
    active_turn_id: str | None
    active_run_id: str | None
    paused_turn_id: str | None
    queued_count: int
    queue_item_ids: tuple[str, ...]


@dataclass(frozen=True)
class MessageReceipt:
    session_id: str
    request_id: str
    message_id: str
    disposition: Literal["queued", "steered"]
    event_seq: int
    queue_item_id: str | None
    turn_id: str | None
    wake_error: str | None = None
    accepted: bool = True
    completed: bool = False


@dataclass(frozen=True)
class QueueChange:
    session_id: str
    queue_item_id: str
    applied: bool
    reason: str | None = None


@dataclass(frozen=True)
class CancelReceipt:
    session_id: str
    turn_id: str | None
    status: str
    completed: bool = False


@dataclass(frozen=True)
class SessionEventPage:
    session_id: str
    events: tuple[dict[str, Any], ...]
    next_after_seq: int
    has_more: bool


@dataclass(frozen=True)
class SessionWaitResult:
    reason: Literal["idle", "blocked", "timeout", "closed"]
    state: SessionState


@runtime_checkable
class SessionControl(Protocol):
    async def create(self, *, session_id: str | None = None, title: str = "") -> SessionState: ...
    async def state(self, session_id: str) -> SessionState: ...
    async def prompt(self, session_id: str, *, request_id: str, text: str, mode: Literal["queue", "steer"] = "queue", work_root: str = "") -> MessageReceipt: ...
    async def update_queue(self, session_id: str, queue_item_id: str, *, text: str | None = None, delete: bool = False) -> QueueChange: ...
    async def cancel(self, session_id: str, *, turn_id: str | None = None) -> CancelReceipt: ...
    async def events(self, session_id: str, *, after_seq: int = 0, limit: int = 100, max_bytes: int = 1024 * 1024) -> SessionEventPage: ...
    def follow(self, session_id: str, *, after_seq: int = 0, limit: int = 100, max_bytes: int = 1024 * 1024) -> AsyncIterator[dict[str, Any]]: ...
    async def wait(self, session_id: str, *, timeout: float = 30) -> SessionWaitResult: ...


SESSIONS = ServiceKey[SessionControl]("sessions", version=1, protocol=SessionControl)

__all__ = ["SESSIONS", "SessionControl", "SessionError", "SessionState", "MessageReceipt",
           "QueueChange", "CancelReceipt", "SessionEventPage", "SessionWaitResult"]
