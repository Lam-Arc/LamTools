"""Canonical run item events.

These events are the product-neutral facts emitted by the Core runner. Product
members may attach labels or domain payloads, but they should not create their
own runtime event language for the same facts.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

RunItemKind = Literal[
    "message",
    "thinking",
    "tool_call",
    "tool_result",
    "approval_request",
    "approval_response",
    "artifact",
    "verification",
    "handoff",
    "usage",
    "error",
    "status",
    # Live-only model-request progress (building / sent / first token). It is
    # not a transcript row; clients apply it to the turn that owns it.
    "model_phase",
]

RunItemStatus = Literal[
    "queued",
    "running",
    "waiting",
    "completed",
    "failed",
    "cancelled",
    "skipped",
]


def _new_event_id() -> str:
    return uuid.uuid4().hex[:16]


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class RunItemEvent:
    """A single canonical runtime fact.

    ``thread_id`` is the product-neutral conversation id. Existing members may
    map this from session_id or their local thread id, but downstream snapshot
    reducers should not need member-specific event names.
    """

    kind: RunItemKind
    thread_id: str
    event_id: str = field(default_factory=_new_event_id)
    run_id: str = ""
    turn_id: str = ""
    item_id: str = ""
    parent_item_id: str = ""
    seq: int = 0
    status: RunItemStatus = "running"
    payload: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    created_at_ms: int = field(default_factory=_now_ms)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": self.kind,
            "thread_id": self.thread_id,
            "event_id": self.event_id,
            "status": self.status,
            "payload": self.payload,
            "created_at_ms": self.created_at_ms,
        }
        if self.run_id:
            data["run_id"] = self.run_id
        if self.turn_id:
            data["turn_id"] = self.turn_id
        if self.item_id:
            data["item_id"] = self.item_id
        if self.parent_item_id:
            data["parent_item_id"] = self.parent_item_id
        if self.seq:
            data["seq"] = self.seq
        if self.artifacts:
            data["artifacts"] = self.artifacts
        if self.usage:
            data["usage"] = self.usage
        if self.source:
            data["source"] = self.source
        if self.metadata:
            data["metadata"] = self.metadata
        return data

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RunItemEvent":
        return cls(
            kind=value["kind"],
            thread_id=value["thread_id"],
            event_id=str(value.get("event_id") or _new_event_id()),
            run_id=str(value.get("run_id") or ""),
            turn_id=str(value.get("turn_id") or ""),
            item_id=str(value.get("item_id") or ""),
            parent_item_id=str(value.get("parent_item_id") or ""),
            seq=int(value.get("seq") or 0),
            status=value.get("status") or "running",
            payload=dict(value.get("payload") or {}),
            artifacts=list(value.get("artifacts") or []),
            usage=dict(value.get("usage") or {}),
            source=str(value.get("source") or ""),
            created_at_ms=int(value.get("created_at_ms") or _now_ms()),
            metadata=dict(value.get("metadata") or {}),
        )


__all__ = [
    "RunItemEvent",
    "RunItemKind",
    "RunItemStatus",
]
