"""Canonical turn-control domain model.

The model separates the logical unit of user intent (``Turn``) from one
execution attempt (``Run``), and makes every human wait a first-class
``Interaction`` instead of an approval special case.

Nothing in this module performs IO.  Storage lives in :mod:`turn.store`,
orchestration in :mod:`turn.coordinator`, and the user-facing ask lifecycle in
:mod:`turn.broker`.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

TURN_SCHEMA_VERSION = 2

TurnStatus = Literal[
    "queued",
    "running",
    "waiting",
    "paused",
    "stopping",
    "completed",
    "failed",
    "cancelled",
]
TERMINAL_TURN_STATUSES: frozenset[str] = frozenset(
    {"completed", "failed", "cancelled", "skipped"}
)
ACTIVE_TURN_STATUSES: frozenset[str] = frozenset({"queued", "running", "waiting", "stopping"})
#: Statuses in which the session must refuse an unrelated new turn.  A paused
#: turn owns the session until it is continued or terminated.
SESSION_OWNING_STATUSES: frozenset[str] = frozenset(
    {"queued", "running", "waiting", "paused", "stopping"}
)
#: Snapshot/runtime statuses that still own a thread. ``interrupting`` is the
#: legacy spelling kept by persisted snapshots and older event streams.
BUSY_TURN_STATUSES: frozenset[str] = SESSION_OWNING_STATUSES | {"interrupting"}
#: Runtime-state statuses in which a process may still be executing the turn.
LIVE_RUNTIME_STATUSES: frozenset[str] = frozenset(
    {"running", "waiting", "interrupting"}
)
#: Run-item statuses whose text is final and replaces accumulated deltas.
TERMINAL_ITEM_STATUSES: frozenset[str] = frozenset(
    {"completed", "done", "ok", "failed", "error", "cancelled"}
)

RunStatus = Literal["created", "running", "paused", "completed", "failed", "cancelled"]

InteractionKind = Literal["approval", "question", "clarification", "plan"]
InteractionStatus = Literal[
    "open",
    "deferred",
    "processing",
    "answered",
    "cancelled",
    "expired",
]

ControlIntentKind = Literal["start", "pause", "resume", "cancel", "terminate", "force_reset"]
ControlIntentStatus = Literal["pending", "applied", "rejected", "superseded"]

AgentRunStatus = Literal[
    "idle",
    "running",
    "paused",
    "suspended",
    "interrupted",
    "terminated",
    "closed",
    "deleted",
    "failed",
    "completed",
    "lease_expired",
]

MAIN_SCOPE = "main"


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str = "") -> str:
    value = uuid.uuid4().hex
    return f"{prefix}{value}" if prefix else value


def agent_scope(agent_run_id: str) -> str:
    return f"agent:{agent_run_id}"


def is_agent_scope(scope: str) -> bool:
    return str(scope).startswith("agent:")


def agent_run_id_from_scope(scope: str) -> str:
    value = str(scope)
    return value.split(":", 1)[1] if is_agent_scope(value) else ""


#: Allowed turn transitions.  Keys are the facts that drive the transition, not
#: free-form status names, so a caller cannot jump from ``queued`` straight to
#: ``completed`` by writing whatever it wants.
TURN_TRANSITIONS: dict[str, dict[str, str]] = {
    "queued": {
        "run_started": "running",
        "cancel_applied": "cancelled",
    },
    "running": {
        "interaction_opened": "waiting",
        "pause_applied": "paused",
        "cancel_applied": "stopping",
        "run_completed": "completed",
        "run_failed": "failed",
    },
    "waiting": {
        "interaction_answered": "running",
        "resume_applied": "running",
        "pause_applied": "paused",
        "cancel_applied": "stopping",
    },
    "paused": {
        "resume_applied": "running",
        "cancel_applied": "cancelled",
    },
    "stopping": {
        "run_ended": "cancelled",
        "cancel_settled": "cancelled",
    },
    "completed": {},
    "failed": {},
    "cancelled": {},
}


def can_transition(current: str, event: str) -> str | None:
    """Return the target status for *event* from *current*, or ``None``."""
    return TURN_TRANSITIONS.get(str(current), {}).get(str(event))


@dataclass
class Turn:
    turn_id: str
    thread_id: str
    status: TurnStatus = "queued"
    epoch: int = 0
    active_run_id: str = ""
    waiting_reason: str = ""
    waiting_on: list[str] = field(default_factory=list)
    created_seq: int = 0
    updated_seq: int = 0
    input: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_TURN_STATUSES

    @property
    def owns_session(self) -> bool:
        return self.status in SESSION_OWNING_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "thread_id": self.thread_id,
            "status": self.status,
            "epoch": int(self.epoch),
            "active_run_id": self.active_run_id,
            "waiting_reason": self.waiting_reason,
            "waiting_on": list(self.waiting_on),
            "created_seq": int(self.created_seq),
            "updated_seq": int(self.updated_seq),
            "input": dict(self.input),
            "error": dict(self.error),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Turn":
        return cls(
            turn_id=str(value.get("turn_id") or ""),
            thread_id=str(value.get("thread_id") or ""),
            status=str(value.get("status") or "queued"),  # type: ignore[arg-type]
            epoch=int(value.get("epoch") or 0),
            active_run_id=str(value.get("active_run_id") or ""),
            waiting_reason=str(value.get("waiting_reason") or ""),
            waiting_on=[str(item) for item in value.get("waiting_on") or []],
            created_seq=int(value.get("created_seq") or 0),
            updated_seq=int(value.get("updated_seq") or 0),
            input=dict(value.get("input") or {}),
            error=dict(value.get("error") or {}),
        )


@dataclass
class Run:
    run_id: str
    turn_id: str
    attempt: int = 1
    epoch: int = 0
    status: RunStatus = "created"
    started_at_ms: int = 0
    ended_at_ms: int = 0
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "attempt": int(self.attempt),
            "epoch": int(self.epoch),
            "status": self.status,
            "started_at_ms": int(self.started_at_ms),
            "ended_at_ms": int(self.ended_at_ms),
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Run":
        return cls(
            run_id=str(value.get("run_id") or ""),
            turn_id=str(value.get("turn_id") or ""),
            attempt=int(value.get("attempt") or 1),
            epoch=int(value.get("epoch") or 0),
            status=str(value.get("status") or "created"),  # type: ignore[arg-type]
            started_at_ms=int(value.get("started_at_ms") or 0),
            ended_at_ms=int(value.get("ended_at_ms") or 0),
            error=str(value.get("error") or ""),
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass
class InteractionOption:
    id: str
    label: str
    description: str = ""
    response: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "response": self.response or self.label,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "InteractionOption":
        option_id = str(value.get("id") or value.get("label") or "")
        label = str(value.get("label") or option_id)
        return cls(
            id=option_id,
            label=label,
            description=str(value.get("description") or ""),
            response=str(value.get("response") or label),
        )


@dataclass
class InteractionAnswer:
    """The user's answer.  ``kind`` is explicit so no decision verb is reused."""

    kind: Literal["option", "text", "skip", "cancel"]
    option_id: str = ""
    text: str = ""
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "option_id": self.option_id,
            "text": self.text,
            "skipped": self.skipped,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "InteractionAnswer | None":
        if not isinstance(value, dict):
            return None
        kind = str(value.get("kind") or "text")
        if kind not in {"option", "text", "skip", "cancel"}:
            kind = "text"
        return cls(
            kind=kind,  # type: ignore[arg-type]
            option_id=str(value.get("option_id") or ""),
            text=str(value.get("text") or ""),
            skipped=bool(value.get("skipped") or kind == "skip"),
        )


@dataclass
class Interaction:
    interaction_id: str
    turn_id: str
    thread_id: str = ""
    run_id: str = ""
    scope: str = MAIN_SCOPE
    kind: InteractionKind = "approval"
    status: InteractionStatus = "open"
    tool_call_id: str = ""
    title: str = ""
    body: str = ""
    context: str = ""
    facts: list[dict[str, Any]] = field(default_factory=list)
    options: list[InteractionOption] = field(default_factory=list)
    default_answer: dict[str, Any] = field(default_factory=dict)
    answer: InteractionAnswer | None = None
    expires_at_ms: int = 0
    claim_token: str = ""
    created_seq: int = 0
    resolved_seq: int = 0
    legacy_request_id: str = ""
    #: Decision-pool provenance. The pool is ordered by ``created_seq``; these
    #: fields answer "what is this, who delivered it, and where does it live".
    project_id: str = ""
    agent_name: str = ""
    agent_session_id: str = ""
    delivered_by: str = "main"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def decision_id(self) -> str:
        """Stable hash identity for cross-window dedupe and event replay."""
        import hashlib

        return "dec_" + hashlib.sha256(
            self.interaction_id.encode("utf-8")
        ).hexdigest()[:32]

    @property
    def open(self) -> bool:
        return self.status == "open"

    @property
    def terminal(self) -> bool:
        return self.status in {"answered", "cancelled", "expired"}

    @property
    def lifecycle_state(self) -> str:
        """The card's user-visible phase: appearing, processing, or ending.

        This is the single vocabulary shared by the server snapshot and the
        UI. ``deferred`` is still a visible card (appearing) while a turn is
        parked; a terminal row is always ending and must not render.
        """
        if self.terminal:
            return "ending"
        if self.status == "processing":
            return "processing"
        return "appearing"

    def option(self, option_id: str) -> InteractionOption | None:
        for option in self.options:
            if option.id == option_id:
                return option
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "interaction_id": self.interaction_id,
            "turn_id": self.turn_id,
            "thread_id": self.thread_id,
            "run_id": self.run_id,
            "scope": self.scope,
            "kind": self.kind,
            "status": self.status,
            "lifecycle": self.lifecycle_state,
            "decision_id": self.decision_id,
            "sequence": int(self.created_seq),
            "project_id": self.project_id,
            "agent_name": self.agent_name,
            "agent_session_id": self.agent_session_id,
            "delivered_by": self.delivered_by,
            "tool_call_id": self.tool_call_id,
            "title": self.title,
            "body": self.body,
            "context": self.context,
            "facts": list(self.facts),
            "options": [option.to_dict() for option in self.options],
            "default_answer": dict(self.default_answer),
            "answer": self.answer.to_dict() if self.answer else None,
            "expires_at_ms": int(self.expires_at_ms),
            "claim_token": self.claim_token,
            "created_seq": int(self.created_seq),
            "resolved_seq": int(self.resolved_seq),
            "legacy_request_id": self.legacy_request_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Interaction":
        return cls(
            interaction_id=str(value.get("interaction_id") or ""),
            turn_id=str(value.get("turn_id") or ""),
            thread_id=str(value.get("thread_id") or ""),
            run_id=str(value.get("run_id") or ""),
            scope=str(value.get("scope") or MAIN_SCOPE),
            kind=str(value.get("kind") or "approval"),  # type: ignore[arg-type]
            status=str(value.get("status") or "open"),  # type: ignore[arg-type]
            tool_call_id=str(value.get("tool_call_id") or ""),
            title=str(value.get("title") or ""),
            body=str(value.get("body") or ""),
            context=str(value.get("context") or ""),
            facts=[dict(item) for item in value.get("facts") or [] if isinstance(item, dict)],
            options=[
                InteractionOption.from_dict(item)
                for item in value.get("options") or []
                if isinstance(item, dict)
            ],
            default_answer=dict(value.get("default_answer") or {}),
            answer=InteractionAnswer.from_dict(value.get("answer")),
            expires_at_ms=int(value.get("expires_at_ms") or 0),
            claim_token=str(value.get("claim_token") or ""),
            created_seq=int(value.get("created_seq") or 0),
            resolved_seq=int(value.get("resolved_seq") or 0),
            legacy_request_id=str(value.get("legacy_request_id") or ""),
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass
class ControlIntent:
    intent_id: str
    turn_id: str
    expected_epoch: int
    kind: ControlIntentKind
    status: ControlIntentStatus = "pending"
    payload: dict[str, Any] = field(default_factory=dict)
    created_at_ms: int = 0
    applied_at_ms: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "turn_id": self.turn_id,
            "expected_epoch": int(self.expected_epoch),
            "kind": self.kind,
            "status": self.status,
            "payload": dict(self.payload),
            "created_at_ms": int(self.created_at_ms),
            "applied_at_ms": int(self.applied_at_ms),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ControlIntent":
        return cls(
            intent_id=str(value.get("intent_id") or ""),
            turn_id=str(value.get("turn_id") or ""),
            expected_epoch=int(value.get("expected_epoch") or 0),
            kind=str(value.get("kind") or "start"),  # type: ignore[arg-type]
            status=str(value.get("status") or "pending"),  # type: ignore[arg-type]
            payload=dict(value.get("payload") or {}),
            created_at_ms=int(value.get("created_at_ms") or 0),
            applied_at_ms=int(value.get("applied_at_ms") or 0),
            error=str(value.get("error") or ""),
        )


@dataclass
class AgentRun:
    agent_run_id: str
    parent_turn_id: str
    parent_thread_id: str = ""
    parent_run_id: str = ""
    name: str = ""
    type: str = "execute"
    model_id: str = ""
    reasoning_level: str = ""
    status: AgentRunStatus = "idle"
    lease_until_ms: int = 0
    sub_session_id: str = ""
    source_call_id: str = ""
    source_run_id: str = ""
    source_turn_id: str = ""
    summary: str = ""
    started_at_ms: int = 0
    completed_at_ms: int = 0
    elapsed_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_run_id": self.agent_run_id,
            "parent_turn_id": self.parent_turn_id,
            "parent_thread_id": self.parent_thread_id,
            "parent_run_id": self.parent_run_id,
            "name": self.name,
            "type": self.type,
            "model_id": self.model_id,
            "reasoning_level": self.reasoning_level,
            "status": self.status,
            "lease_until_ms": int(self.lease_until_ms),
            "sub_session_id": self.sub_session_id,
            "source_call_id": self.source_call_id,
            "source_run_id": self.source_run_id,
            "source_turn_id": self.source_turn_id,
            "summary": self.summary,
            "started_at_ms": int(self.started_at_ms),
            "completed_at_ms": int(self.completed_at_ms),
            "elapsed_ms": int(self.elapsed_ms),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentRun":
        return cls(
            agent_run_id=str(value.get("agent_run_id") or ""),
            parent_turn_id=str(value.get("parent_turn_id") or ""),
            parent_thread_id=str(value.get("parent_thread_id") or ""),
            parent_run_id=str(value.get("parent_run_id") or ""),
            name=str(value.get("name") or ""),
            type=str(value.get("type") or "execute"),
            model_id=str(value.get("model_id") or ""),
            reasoning_level=str(value.get("reasoning_level") or ""),
            status=str(value.get("status") or "idle"),  # type: ignore[arg-type]
            lease_until_ms=int(value.get("lease_until_ms") or 0),
            sub_session_id=str(value.get("sub_session_id") or ""),
            source_call_id=str(value.get("source_call_id") or ""),
            source_run_id=str(value.get("source_run_id") or ""),
            source_turn_id=str(value.get("source_turn_id") or ""),
            summary=str(value.get("summary") or ""),
            started_at_ms=int(value.get("started_at_ms") or 0),
            completed_at_ms=int(value.get("completed_at_ms") or 0),
            elapsed_ms=int(value.get("elapsed_ms") or 0),
            metadata=dict(value.get("metadata") or {}),
        )


# ---------------------------------------------------------------------------
# Typed facts.  The projection only lets ``TurnFact`` change a turn's status.
# ---------------------------------------------------------------------------


@dataclass
class Fact:
    event_id: str
    thread_id: str
    turn_id: str
    run_id: str = ""
    epoch: int = 0
    scope: str = MAIN_SCOPE
    seq: int = 0
    created_at_ms: int = 0
    schema_version: int = TURN_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def fact_type(self) -> str:
        raise NotImplementedError

    def to_payload(self) -> dict[str, Any]:
        raise NotImplementedError

    def envelope(self) -> dict[str, Any]:
        return {
            "fact_type": self.fact_type,
            "event_id": self.event_id,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "run_id": self.run_id,
            "epoch": int(self.epoch),
            "scope": self.scope,
            "seq": int(self.seq),
            "created_at_ms": int(self.created_at_ms or now_ms()),
            "schema_version": int(self.schema_version),
            "metadata": dict(self.metadata),
            **self.to_payload(),
        }


@dataclass
class TurnFact(Fact):
    event: str = ""
    status: str = ""
    waiting_reason: str = ""
    waiting_on: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def fact_type(self) -> str:
        return "turn"

    def to_payload(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "status": self.status,
            "waiting_reason": self.waiting_reason,
            "waiting_on": list(self.waiting_on),
            "payload": dict(self.payload),
        }


@dataclass
class ItemFact(Fact):
    item_id: str = ""
    kind: str = "message"
    status: str = ""
    parent_item_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    item_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def fact_type(self) -> str:
        return "item"

    def to_payload(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "kind": self.kind,
            "status": self.status,
            "parent_item_id": self.parent_item_id,
            "payload": dict(self.payload),
            "item_metadata": dict(self.item_metadata),
        }


@dataclass
class InteractionFact(Fact):
    interaction_id: str = ""
    event: str = ""
    status: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def fact_type(self) -> str:
        return "interaction"

    def to_payload(self) -> dict[str, Any]:
        return {
            "interaction_id": self.interaction_id,
            "event": self.event,
            "status": self.status,
            "payload": dict(self.payload),
        }


@dataclass
class AgentFact(Fact):
    agent_run_id: str = ""
    event: str = ""
    status: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def fact_type(self) -> str:
        return "agent"

    def to_payload(self) -> dict[str, Any]:
        return {
            "agent_run_id": self.agent_run_id,
            "event": self.event,
            "status": self.status,
            "payload": dict(self.payload),
        }


def fact_from_payload(value: dict[str, Any]) -> Fact | None:
    """Rebuild a typed fact from an event payload (defensive, for replay)."""
    if not isinstance(value, dict):
        return None
    base = {
        "event_id": str(value.get("event_id") or ""),
        "thread_id": str(value.get("thread_id") or ""),
        "turn_id": str(value.get("turn_id") or ""),
        "run_id": str(value.get("run_id") or ""),
        "epoch": int(value.get("epoch") or 0),
        "scope": str(value.get("scope") or MAIN_SCOPE),
        "seq": int(value.get("seq") or 0),
        "created_at_ms": int(value.get("created_at_ms") or 0),
        "schema_version": int(value.get("schema_version") or TURN_SCHEMA_VERSION),
        "metadata": dict(value.get("metadata") or {}),
    }
    fact_type = str(value.get("fact_type") or "")
    if fact_type == "turn":
        return TurnFact(
            **base,
            event=str(value.get("event") or ""),
            status=str(value.get("status") or ""),
            waiting_reason=str(value.get("waiting_reason") or ""),
            waiting_on=[str(item) for item in value.get("waiting_on") or []],
            payload=dict(value.get("payload") or {}),
        )
    if fact_type == "item":
        return ItemFact(
            **base,
            item_id=str(value.get("item_id") or ""),
            kind=str(value.get("kind") or "message"),
            status=str(value.get("status") or ""),
            parent_item_id=str(value.get("parent_item_id") or ""),
            payload=dict(value.get("payload") or {}),
            item_metadata=dict(value.get("item_metadata") or {}),
        )
    if fact_type == "interaction":
        return InteractionFact(
            **base,
            interaction_id=str(value.get("interaction_id") or ""),
            event=str(value.get("event") or ""),
            status=str(value.get("status") or ""),
            payload=dict(value.get("payload") or {}),
        )
    if fact_type == "agent":
        return AgentFact(
            **base,
            agent_run_id=str(value.get("agent_run_id") or ""),
            event=str(value.get("event") or ""),
            status=str(value.get("status") or ""),
            payload=dict(value.get("payload") or {}),
        )
    return None


__all__ = [
    "ACTIVE_TURN_STATUSES",
    "AgentFact",
    "AgentRun",
    "AgentRunStatus",
    "ControlIntent",
    "ControlIntentKind",
    "ControlIntentStatus",
    "Fact",
    "Interaction",
    "InteractionAnswer",
    "InteractionFact",
    "InteractionKind",
    "InteractionOption",
    "InteractionStatus",
    "ItemFact",
    "MAIN_SCOPE",
    "Run",
    "RunStatus",
    "SESSION_OWNING_STATUSES",
    "TERMINAL_TURN_STATUSES",
    "TURN_SCHEMA_VERSION",
    "TURN_TRANSITIONS",
    "Turn",
    "TurnFact",
    "TurnStatus",
    "agent_run_id_from_scope",
    "agent_scope",
    "can_transition",
    "fact_from_payload",
    "is_agent_scope",
    "new_id",
    "now_ms",
]
