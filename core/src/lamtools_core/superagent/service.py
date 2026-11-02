"""Super-agent 编排：事件 → Inbox → Policy/Eval → Ticket → Assignment → 交付。

user:“尽可能复用现有 Agent Loop、Sub-agent、SQLite、OperationCatalog、CLI、工具与审批系统。
禁止重新造一套并行调度器”
+(所以真正排期由注入的 scheduler 完成，生产实现就是 ArrangeManager.create；
这里只负责业务状态机与权限边界)。
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Awaitable, Callable, Literal, Protocol, runtime_checkable

from .models import (
    Assignment,
    Decision,
    Mandate,
    SourceEvent,
    Ticket,
    TicketStage,
    utcnow,
)
from .policy import PolicyGate
from .store import RecordExists, SuperagentStore

_INBOX = "inbox"
_TICKET = "ticket"
_ASSIGNMENT = "assignment"
_AUDIT = "audit"

HandleStatus = Literal["accepted", "duplicate", "rejected", "ask_human", "ignored"]


@dataclass(frozen=True)
class HandleResult:
    status: HandleStatus
    ticket_id: str = ""
    reason: str = ""
    policy_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ticket_id": self.ticket_id,
            "reason": self.reason,
            "policy_version": self.policy_version,
        }


@runtime_checkable
class EvalEngine(Protocol):
    """判断"接单 / 忽略 / 待人工"。只能建议，不能授权。"""

    async def assess(
        self,
        event: SourceEvent,
        *,
        open_tickets: list[Ticket] | None = None,
    ) -> tuple[Decision, str]: ...


class DefaultEvalEngine:
    """确定性默认实现：关键词只用来降级到人工，不用来扩权。"""

    _IGNORE_HINTS = ("[ignore]", "无需处理", "duplicate of")
    _HUMAN_HINTS = ("需要确认", "不确定", "=> ask", "[ask]")

    async def assess(
        self,
        event: SourceEvent,
        *,
        open_tickets: list[Ticket] | None = None,
    ) -> tuple[Decision, str]:
        text = str(event.payload.get("text") or "").strip()
        lowered = text.lower()
        for hint in self._IGNORE_HINTS:
            if hint in lowered:
                return "ignore", f"eval-ignore-hint:{hint}"
        for hint in self._HUMAN_HINTS:
            if hint in lowered:
                return "ask_human", f"eval-ask-hint:{hint}"
        if not text:
            return "ask_human", "eval-no-instructions"
        return "accept", "eval-accept"


Scheduler = Callable[[Ticket], Awaitable[str] | str]


class SuperagentService:
    def __init__(
        self,
        *,
        store: SuperagentStore,
        policy: PolicyGate,
        eval_engine: EvalEngine | None = None,
        scheduler: Scheduler | None = None,
        worktree_manager: Any = None,
    ) -> None:
        self.store = store
        self.policy = policy
        self.eval_engine = eval_engine or DefaultEvalEngine()
        self.scheduler = scheduler
        self.worktree_manager = worktree_manager

    # ------------------------------------------------------------------ 入口
    async def handle_event(self, event: SourceEvent) -> HandleResult:
        inbox_key = event.stable_key
        payload = event.to_dict()
        inbox_payload = dict(payload)
        inbox_payload["payload_hash"] = _hash_payload(payload)
        try:
            await self.store.put(_INBOX, inbox_key, inbox_payload, create_only=True)
        except RecordExists:
            existing = await self.store.get(_INBOX, inbox_key) or {}
            if str(existing.get("payload_hash") or "") != inbox_payload["payload_hash"]:
                # 同一个稳定 ID 内容不同：拒绝并留痕，不覆盖也不静默吞掉。
                await self._audit(
                    f"conflict:{inbox_key}",
                    {"reason": "conflicting-event-id", "inbox": inbox_key},
                )
                return HandleResult(
                    "rejected", reason="conflicting-event-id", policy_version=self.policy.config.version
                )
            ticket_id = str(existing.get("ticket_id") or "")
            if not ticket_id:
                ticket_id = _ticket_id_for(event)
            return HandleResult(
                "duplicate", ticket_id=ticket_id, reason="duplicate-event", policy_version=self.policy.config.version
            )

        verdict = self.policy.evaluate(event)
        if verdict.outcome == "deny":
            await self._audit(f"deny:{inbox_key}", {"reason": verdict.reason})
            await self._remember_ticket(inbox_key, "")
            return HandleResult(
                "rejected", reason=verdict.reason, policy_version=self.policy.config.version
            )

        decision, reason = await self.eval_engine.assess(event, open_tickets=await self.list_tickets())
        if decision == "ignore":
            await self._audit(f"ignore:{inbox_key}", {"reason": reason})
            return HandleResult(
                "ignored", reason=reason, policy_version=self.policy.config.version
            )

        stage: TicketStage = "blocked" if (decision == "ask_human" or verdict.outcome == "ask_human") else "open"
        ticket = Ticket(
            ticket_id=_ticket_id_for(event),
            source_id=event.source_id,
            source_event_key=inbox_key,
            thread_key=event.thread_key or inbox_key,
            stage=stage,
            mandate=verdict.mandate or Mandate(repo_root=event.repo),
            instructions=str(event.payload.get("text") or ""),
            decision_reason=reason if decision != "accept" else verdict.reason,
            policy_version=self.policy.config.version,
        )
        try:
            await self.store.put(_TICKET, ticket.ticket_id, ticket.to_dict(), create_only=True)
        except RecordExists:
            # 相同事件重复投递只建一张 Ticket：确定性 ID + create_only 就够，
            # 不依赖上一步的 inbox 记录是否写成功（崩溃后重放同样安全）。
            return HandleResult(
                "duplicate",
                ticket_id=ticket.ticket_id,
                reason="duplicate-ticket",
                policy_version=self.policy.config.version,
            )

        await self._remember_ticket(inbox_key, ticket.ticket_id)
        if stage == "open" and self.scheduler is not None:
            await self._schedule(ticket)
        return HandleResult(
            "accepted" if stage == "open" else "ask_human",
            ticket_id=ticket.ticket_id,
            reason=ticket.decision_reason,
            policy_version=self.policy.config.version,
        )

    async def _schedule(self, ticket: Ticket) -> None:
        assert self.scheduler is not None
        result = self.scheduler(ticket)
        if hasattr(result, "__await__"):
            job_id = await result  # type: ignore[misc]
        else:
            job_id = result
        updated = Ticket.from_dict(
            {
                **ticket.to_dict(),
                "stage": "running",
                "revision": ticket.revision,
            }
        )
        await self.store.put(
            _TICKET, ticket.ticket_id, updated.to_dict(), expected_revision=ticket.revision
        )
        await self._audit(
            f"scheduled:{ticket.ticket_id}", {"job_id": str(job_id or ""), "stage": "running"}
        )

    # ------------------------------------------------------------------ 查询
    async def get_ticket(self, ticket_id: str) -> Ticket | None:
        record = await self.store.get(_TICKET, str(ticket_id or ""))
        return Ticket.from_dict(record) if record else None

    async def list_tickets(self, *, stage: str = "") -> list[Ticket]:
        items = await self.store.list(_TICKET)
        tickets = [Ticket.from_dict(item) for item in items]
        if stage:
            tickets = [item for item in tickets if item.stage == stage]
        return tickets

    async def list_audit(self) -> list[dict[str, Any]]:
        return await self.store.list(_AUDIT)

    # ------------------------------------------------------------------ 人工关口
    async def approve(self, ticket_id: str, *, approver: str) -> Ticket:
        ticket = await self.get_ticket(ticket_id)
        if ticket is None:
            raise LookupError(f"ticket not found: {ticket_id}")
        if ticket.stage not in {"blocked", "open", "review"}:
            raise ValueError(f"ticket cannot be approved from stage {ticket.stage}")
        updated = Ticket.from_dict(
            {**ticket.to_dict(), "stage": "open", "decision_reason": f"approved-by:{approver}"}
        )
        stored = await self.store.put(
            _TICKET, ticket.ticket_id, updated.to_dict(), expected_revision=ticket.revision
        )
        await self._audit(
            f"approve:{ticket.ticket_id}", {"approver": approver}
        )
        approved = Ticket.from_dict(stored)
        await self._schedule(approved)
        return approved

    async def reject(self, ticket_id: str, *, reason: str = "") -> Ticket:
        return await self._set_stage(ticket_id, "closed", reason=f"rejected:{reason}")

    async def stop(self, ticket_id: str) -> Ticket:
        return await self._set_stage(ticket_id, "blocked", reason="stopped-by-user")

    async def _set_stage(self, ticket_id: str, stage: TicketStage, *, reason: str) -> Ticket:
        ticket = await self.get_ticket(ticket_id)
        if ticket is None:
            raise LookupError(f"ticket not found: {ticket_id}")
        updated = Ticket.from_dict(
            {**ticket.to_dict(), "stage": stage, "decision_reason": reason}
        )
        stored = await self.store.put(
            _TICKET, ticket.ticket_id, updated.to_dict(), expected_revision=ticket.revision
        )
        await self._audit(f"stage:{ticket.ticket_id}", {"stage": stage, "reason": reason})
        return Ticket.from_dict(stored)

    # ------------------------------------------------------------------ 执行
    async def start_assignment(
        self, ticket_id: str, execution_id: str, *, base_branch: str = ""
    ) -> Assignment:
        ticket = await self.get_ticket(ticket_id)
        if ticket is None:
            raise LookupError(f"ticket not found: {ticket_id}")
        if ticket.mandate.revoked:
            await self._set_stage(ticket_id, "blocked", reason="mandate-revoked")
            raise PermissionError("mandate revoked")
        worktree_path = ""
        branch = ""
        if self.worktree_manager is not None:
            info = await self.worktree_manager.ensure(
                ticket.ticket_id,
                ticket.mandate.repo_root,
                base_branch or ticket.mandate.base_branch,
            )
            worktree_path = str(info["path"])
            branch = str(info["branch"])
        assignment = Assignment(
            assignment_id=f"asg_{hashlib.sha256((ticket_id + execution_id).encode()).hexdigest()[:16]}",
            ticket_id=ticket_id,
            execution_id=execution_id,
            worktree_path=worktree_path,
            branch=branch,
            status="running",
        )
        await self.store.put(
            _ASSIGNMENT, assignment.assignment_id, assignment.to_dict(), create_only=True
        )
        return assignment

    async def finish_assignment(
        self,
        assignment_id: str,
        *,
        status: str,
        report: dict[str, Any] | None = None,
    ) -> Assignment:
        record = await self.store.get(_ASSIGNMENT, assignment_id)
        if record is None:
            raise LookupError(f"assignment not found: {assignment_id}")
        assignment = Assignment.from_dict(record)
        updated = Assignment.from_dict(
            {
                **assignment.to_dict(),
                "status": status,
                "report": dict(report or {}),
                "ended_at": utcnow().isoformat(),
            }
        )
        # Assignment 是纯值对象，版本号在存储记录上，CAS 必须取记录里的 revision。
        expected_revision = int(record.get("revision") or 0)
        await self.store.put(
            _ASSIGNMENT,
            assignment_id,
            updated.to_dict(),
            expected_revision=expected_revision,
        )
        stage: TicketStage = "review" if status == "completed" else "blocked"
        await self._set_stage(updated.ticket_id, stage, reason=f"assignment-{status}")
        return updated

    async def list_assignments(self, ticket_id: str = "") -> list[Assignment]:
        items = await self.store.list(_ASSIGNMENT)
        assignments = [Assignment.from_dict(item) for item in items]
        if ticket_id:
            assignments = [item for item in assignments if item.ticket_id == ticket_id]
        return assignments

    # ------------------------------------------------------------------ 内部
    async def _remember_ticket(self, inbox_key: str, ticket_id: str) -> None:
        existing = await self.store.get(_INBOX, inbox_key)
        if existing is None:
            return
        await self.store.put(
            _INBOX,
            inbox_key,
            {**existing, "ticket_id": ticket_id},
            expected_revision=int(existing.get("revision") or 0),
        )

    async def _audit(self, key: str, payload: dict[str, Any]) -> None:
        await self.store.put(
            _AUDIT, key, {**payload, "at": utcnow().isoformat()}
        )


def _ticket_id_for(event: SourceEvent) -> str:
    digest = hashlib.sha256(f"ticket:{event.stable_key}".encode("utf-8")).hexdigest()[:16]
    return f"tkt_{digest}"


def _hash_payload(payload: dict[str, Any]) -> str:
    import json

    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


__all__ = [
    "DefaultEvalEngine",
    "EvalEngine",
    "HandleResult",
    "Scheduler",
    "SuperagentService",
]
