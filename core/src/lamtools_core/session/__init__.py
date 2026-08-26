"""Session protocol types and interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4


@dataclass
class SessionRecord:
    """A session record — owned by a member, holds conversation messages."""

    id: str
    member_id: str
    title: str
    status: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "member_id": self.member_id,
            "title": self.title,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class MessageRecord:
    """A message within a session — role, content, and structured parts."""

    id: str
    session_id: str
    role: str
    content: str
    parts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
        }
        if self.parts:
            d["parts"] = self.parts
        if self.metadata:
            d["metadata"] = self.metadata
        return d


def build_session_record(
    *,
    member_id: str,
    title: str,
    status: str = "idle",
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> SessionRecord:
    """Build a new session using the canonical Core session defaults."""
    return SessionRecord(
        id=str(session_id or uuid4().hex),
        member_id=str(member_id),
        title=str(title).strip() or "New Session",
        status=str(status).strip() or "idle",
        metadata=dict(metadata or {}),
    )


@runtime_checkable
class SessionStore(Protocol):
    """Protocol for session persistence — create, read, update sessions and messages."""

    def create(self, session: SessionRecord) -> SessionRecord: ...
    def get(self, session_id: str) -> SessionRecord | None: ...
    def list(self, member_id: str | None = None) -> list[SessionRecord]: ...
    def update(self, session: SessionRecord) -> SessionRecord: ...
    def delete(self, session_id: str) -> bool: ...
    def add_message(self, message: MessageRecord) -> MessageRecord: ...
    def list_messages(self, session_id: str) -> list[MessageRecord]: ...


class InMemorySessionStore:
    """In-memory session store — uses dicts for sessions and messages."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._messages: dict[str, list[MessageRecord]] = {}

    def create(self, session: SessionRecord) -> SessionRecord:
        """Store a new session and return it."""
        if session.id in self._sessions:
            raise ValueError(f"Session '{session.id}' already exists")
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> SessionRecord | None:
        """Retrieve a session by id, or None if not found."""
        return self._sessions.get(session_id)

    def list(self, member_id: str | None = None) -> list[SessionRecord]:
        """List all sessions, optionally filtered by member_id, sorted by id."""
        sessions = self._sessions.values()
        if member_id is not None:
            sessions = [s for s in sessions if s.member_id == member_id]
        return sorted(sessions, key=lambda s: s.id)

    def update(self, session: SessionRecord) -> SessionRecord:
        """Update a stored session and refresh its updated_at timestamp."""
        session.updated_at = datetime.now()
        self._sessions[session.id] = session
        return session

    def delete(self, session_id: str) -> bool:
        """Delete a session by id. Returns True if found and deleted."""
        if session_id not in self._sessions:
            return False
        del self._sessions[session_id]
        self._messages.pop(session_id, None)
        return True

    def add_message(self, message: MessageRecord) -> MessageRecord:
        """Append a message to its session's message list."""
        if message.session_id not in self._messages:
            self._messages[message.session_id] = []
        self._messages[message.session_id].append(message)
        return message

    def list_messages(self, session_id: str) -> list[MessageRecord]:
        """List messages for a session, ordered by created_at ascending."""
        messages = self._messages.get(session_id, [])
        return sorted(messages, key=lambda m: m.created_at)


__all__ = [
    "SessionRecord",
    "MessageRecord",
    "build_session_record",
    "SessionStore",
    "InMemorySessionStore",
]
