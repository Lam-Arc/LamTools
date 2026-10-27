"""Generic chat-channel contracts.

A channel plugin implements an adapter (send text/file, open a stream, ask
approval/questions) and the host runtime owns the peer→child-session mapping,
the turn loop, outbound event routing, queueing and lifecycle.  This is the
host capability that QQ/Telegram/Discord-style plugins previously rebuilt for
every port.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol


@dataclass
class ChannelTarget:
    scope: str
    target_id: str
    reply_id: str = ""
    event_id: str = ""

    @property
    def key(self) -> str:
        return f"{self.scope}:{self.target_id}"


@dataclass
class ChannelMessage:
    channel: str
    scope: str
    peer_id: str
    sender_id: str
    text: str
    message_id: str
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    sender_name: str = ""
    group_id: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    target: ChannelTarget | None = None

    @property
    def reply_target(self) -> ChannelTarget:
        return self.target or ChannelTarget(self.scope, self.peer_id, self.message_id)


@dataclass
class ChannelSession:
    key: str
    scope: str
    peer_id: str
    sender_id: str
    agent_name: str
    target: ChannelTarget
    model: str = ""
    preset: str = ""
    session_id: str = ""
    transcript: list[dict[str, str]] = field(default_factory=list)
    usage: dict[str, int] = field(
        default_factory=lambda: {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}
    )
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    task: asyncio.Task | None = None
    last_activity: float = field(default_factory=time.time)
    message_count: int = 0
    generation: int = 0
    last_error: str = ""
    last_result: Any = None


@dataclass
class ChannelPolicy:
    """Optional hooks the plugin uses to keep its own access/context rules."""

    allow: Callable[[ChannelMessage], bool] | None = None
    should_answer: Callable[[ChannelMessage], bool] | None = None
    prepare: Callable[[ChannelMessage], Awaitable[str | None]] | None = None
    after_turn: Callable[[ChannelSession, ChannelMessage], Awaitable[None] | None] | None = None
    history_limit: int = 10


class ChannelAdapter(Protocol):
    name: str

    async def send_text(self, target: ChannelTarget, text: str, keyboard: Any | None = None) -> Any: ...

    async def send_file(self, target: ChannelTarget, path: str, file_name: str = "") -> dict[str, Any]: ...

    def open_stream(self, target: ChannelTarget) -> Any | None: ...

    async def ask_approval(self, session: ChannelSession, pending: dict[str, Any], timeout_ms: int) -> str: ...

    async def ask_questions(
        self, session: ChannelSession, pending: dict[str, Any], timeout_ms: int
    ) -> Any: ...

    def handle_interaction(self, event: Any) -> bool: ...

    def handle_text(self, scope: str, peer_id: str, text: str) -> bool: ...

    def cancel_pending(self, session: ChannelSession) -> None: ...

    def acknowledge_interaction(self, event: Any) -> None: ...


__all__ = [
    "ChannelTarget",
    "ChannelMessage",
    "ChannelSession",
    "ChannelPolicy",
    "ChannelAdapter",
]
