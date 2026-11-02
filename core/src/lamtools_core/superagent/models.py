"""Super-agent 的数据模型。

user:“实现 Source、Policy、Eval、Ticket、Assignment、独立 Worktree 和可靠结果交付”
+(这七件事各自有独立生命周期，不能塞进 Arrange 的一个状态字段里)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

TicketStage = Literal["open", "running", "review", "blocked", "closed"]
Decision = Literal["accept", "ignore", "ask_human"]
EffectStatus = Literal["pending", "done", "failed"]
AssignmentStatus = Literal["running", "completed", "failed", "stopped"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass(frozen=True)
class SourceActor:
    """事件发起者。信任与否由宿主判定，不由事件正文自述。"""

    actor_id: str
    login: str = ""
    trusted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"actor_id": self.actor_id, "login": self.login, "trusted": self.trusted}


@dataclass(frozen=True)
class SourceEvent:
    source_id: str
    event_id: str
    event_type: str
    actor: SourceActor
    payload: dict[str, Any] = field(default_factory=dict)
    subject: str = ""
    thread_key: str = ""
    occurred_at: datetime = field(default_factory=utcnow)
    repo: str = ""

    @property
    def stable_key(self) -> str:
        return f"{self.source_id}:{self.event_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "actor": self.actor.to_dict(),
            "payload": dict(self.payload),
            "subject": self.subject,
            "thread_key": self.thread_key,
            "occurred_at": _iso(self.occurred_at),
            "repo": self.repo,
        }


@dataclass(frozen=True)
class Mandate:
    """固定一次工单的权限范围。只能收窄，不能由外部文本扩大。"""

    repo_root: str
    allowed_paths: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    base_branch: str = "main"
    can_push: bool = False
    can_create_pr: bool = False
    policy_version: str = ""
    revoked: bool = False

    def permits_repo(self, repo: str) -> bool:
        if not repo:
            return False
        return repo.strip().lower() == self.repo_root.strip().lower()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_root": self.repo_root,
            "allowed_paths": list(self.allowed_paths),
            "allowed_tools": list(self.allowed_tools),
            "base_branch": self.base_branch,
            "can_push": self.can_push,
            "can_create_pr": self.can_create_pr,
            "policy_version": self.policy_version,
            "revoked": self.revoked,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Mandate":
        return cls(
            repo_root=str(raw.get("repo_root") or ""),
            allowed_paths=tuple(raw.get("allowed_paths") or ()),
            allowed_tools=tuple(raw.get("allowed_tools") or ()),
            base_branch=str(raw.get("base_branch") or "main"),
            can_push=bool(raw.get("can_push")),
            can_create_pr=bool(raw.get("can_create_pr")),
            policy_version=str(raw.get("policy_version") or ""),
            revoked=bool(raw.get("revoked")),
        )


@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    source_id: str
    source_event_key: str
    thread_key: str
    stage: TicketStage
    mandate: Mandate
    instructions: str = ""
    decision_reason: str = ""
    policy_version: str = ""
    revision: int = 1
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "source_id": self.source_id,
            "source_event_key": self.source_event_key,
            "thread_key": self.thread_key,
            "stage": self.stage,
            "mandate": self.mandate.to_dict(),
            "instructions": self.instructions,
            "decision_reason": self.decision_reason,
            "policy_version": self.policy_version,
            "revision": self.revision,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Ticket":
        return cls(
            ticket_id=str(raw["ticket_id"]),
            source_id=str(raw.get("source_id") or ""),
            source_event_key=str(raw.get("source_event_key") or ""),
            thread_key=str(raw.get("thread_key") or ""),
            stage=str(raw.get("stage") or "open"),  # type: ignore[arg-type]
            mandate=Mandate.from_dict(dict(raw.get("mandate") or {})),
            instructions=str(raw.get("instructions") or ""),
            decision_reason=str(raw.get("decision_reason") or ""),
            policy_version=str(raw.get("policy_version") or ""),
            revision=int(raw.get("revision") or 1),
            created_at=_parse_dt(raw.get("created_at")),
            updated_at=_parse_dt(raw.get("updated_at")),
        )


@dataclass(frozen=True)
class Assignment:
    assignment_id: str
    ticket_id: str
    execution_id: str
    worktree_path: str = ""
    branch: str = ""
    status: AssignmentStatus = "running"
    report: dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=utcnow)
    ended_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignment_id": self.assignment_id,
            "ticket_id": self.ticket_id,
            "execution_id": self.execution_id,
            "worktree_path": self.worktree_path,
            "branch": self.branch,
            "status": self.status,
            "report": dict(self.report),
            "started_at": _iso(self.started_at),
            "ended_at": _iso(self.ended_at),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Assignment":
        return cls(
            assignment_id=str(raw["assignment_id"]),
            ticket_id=str(raw.get("ticket_id") or ""),
            execution_id=str(raw.get("execution_id") or ""),
            worktree_path=str(raw.get("worktree_path") or ""),
            branch=str(raw.get("branch") or ""),
            status=str(raw.get("status") or "running"),  # type: ignore[arg-type]
            report=dict(raw.get("report") or {}),
            started_at=_parse_dt(raw.get("started_at")),
            ended_at=_parse_dt(raw.get("ended_at")) if raw.get("ended_at") else None,
        )


@dataclass(frozen=True)
class Effect:
    effect_id: str
    ticket_id: str
    kind: str
    idempotency_key: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: EffectStatus = "pending"
    attempts: int = 0
    remote_ref: str = ""
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect_id": self.effect_id,
            "ticket_id": self.ticket_id,
            "kind": self.kind,
            "idempotency_key": self.idempotency_key,
            "payload": dict(self.payload),
            "status": self.status,
            "attempts": self.attempts,
            "remote_ref": self.remote_ref,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Effect":
        return cls(
            effect_id=str(raw["effect_id"]),
            ticket_id=str(raw.get("ticket_id") or ""),
            kind=str(raw.get("kind") or ""),
            idempotency_key=str(raw.get("idempotency_key") or ""),
            payload=dict(raw.get("payload") or {}),
            status=str(raw.get("status") or "pending"),  # type: ignore[arg-type]
            attempts=int(raw.get("attempts") or 0),
            remote_ref=str(raw.get("remote_ref") or ""),
            last_error=str(raw.get("last_error") or ""),
        )


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return utcnow()
    return utcnow()


__all__ = [
    "Assignment",
    "AssignmentStatus",
    "Decision",
    "Effect",
    "EffectStatus",
    "Mandate",
    "SourceActor",
    "SourceEvent",
    "Ticket",
    "TicketStage",
    "utcnow",
]
