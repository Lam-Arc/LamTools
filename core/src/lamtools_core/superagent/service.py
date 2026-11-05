"""Super-agent 编排：事件 → Inbox → Policy/Eval → Ticket → Assignment → 交付。

user:“尽可能复用现有 Agent Loop、Sub-agent、SQLite、OperationCatalog、CLI、工具与审批系统。
禁止重新造一套并行调度器”
+(所以真正排期由注入的 scheduler 完成，生产实现就是 ArrangeManager.create；
这里只负责业务状态机与权限边界)。
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
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
from .prompt import build_ticket_prompt
from .store import ConcurrentUpdate, RecordExists, SuperagentStore
from .worktree import WorktreeError

# 与 app.runtime_permissions 的档位保持一致；superagent 不反向依赖 app 层。
_PERMISSION_PRESETS = ("ask", "auto", "full_access")

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


@dataclass(frozen=True)
class ExecutionPlan:
    """一次工单执行的现场：在哪儿干、干什么、算哪次执行。"""

    ticket_id: str
    assignment_id: str
    work_root: str
    branch: str
    prompt: str
    thread_id: str = ""
    permission_preset: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "assignment_id": self.assignment_id,
            "work_root": self.work_root,
            "branch": self.branch,
            "thread_id": self.thread_id,
            "permission_preset": self.permission_preset,
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

    async def _schedule(self, ticket: Ticket) -> str:
        if self.scheduler is None:
            return ""
        result = self.scheduler(ticket)
        job_id = await result if hasattr(result, "__await__") else result
        job_id = str(job_id or "")
        # 排期过程中 scheduler 可能已经改过工单（建了工作树、记了 assignment），
        # 所以这里必须重读再写，不能拿旧 revision 去 CAS，否则会把刚写进去的现场覆盖掉。
        current = await self.get_ticket(ticket.ticket_id)
        if current is not None:
            await self._patch_ticket(
                ticket.ticket_id,
                stage="running",
                job_id=job_id or current.job_id,
            )
        await self._audit(
            f"scheduled:{ticket.ticket_id}", {"job_id": job_id, "stage": "running"}
        )
        return job_id

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
        try:
            await self._schedule(approved)
        except (WorktreeError, PermissionError, OSError, ValueError) as exc:
            # 排期失败（例如工作树建不出来）要让工单明确停在 blocked，
            # 而不是抛一个用户看不懂的异常然后工单状态还留在 open。
            await self._set_stage(ticket_id, "blocked", reason=f"schedule-failed:{exc}")
            raise
        return approved

    async def reject(self, ticket_id: str, *, reason: str = "") -> Ticket:
        return await self._set_stage(ticket_id, "closed", reason=f"rejected:{reason}")

    async def stop(self, ticket_id: str) -> Ticket:
        return await self._set_stage(ticket_id, "blocked", reason="stopped-by-user")

    async def _set_stage(self, ticket_id: str, stage: TicketStage, *, reason: str) -> Ticket:
        updated = await self._patch_ticket(ticket_id, stage=stage, decision_reason=reason)
        await self._audit(f"stage:{ticket_id}", {"stage": stage, "reason": reason})
        return updated

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
        worktree_path, branch = await self._prepare_worktree(
            ticket, base_branch=base_branch or ticket.mandate.base_branch
        )
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

    # ------------------------------------------------------------------ 用户交付
    async def submit_goal(
        self,
        goal: str,
        *,
        repo_root: str,
        title: str = "",
        base_branch: str = "",
        allowed_paths: tuple[str, ...] = (),
        can_push: bool = False,
        can_create_pr: bool = False,
        permission_preset: str = "auto",
    ) -> HandleResult:
        """用户直接把目标交给 Super-agent。

        user:“让用户能够直接交付复杂目标，由 Super-agent 自主规划、拆解、委派、执行”
        +(本地用户就是授权主体：他写下的目标可以直接开工，不必先配一个外部事件来源；
        仓库范围与推送/PR 按他这一次的明确选择记进工单，事后可查)。
        """
        text = (goal or "").strip()
        version = self.policy.config.version
        if not text:
            return HandleResult("rejected", reason="empty-goal", policy_version=version)
        preset = str(permission_preset or "auto").strip() or "auto"
        if preset not in _PERMISSION_PRESETS:
            return HandleResult(
                "rejected", reason=f"invalid-permission-preset:{preset}", policy_version=version
            )
        repo = str(repo_root or "").strip()
        if not repo:
            return HandleResult("rejected", reason="repo-required", policy_version=version)
        if not Path(repo).is_dir():
            return HandleResult(
                "rejected", reason=f"repo-not-found:{repo}", policy_version=version
            )
        allowed = self.policy.config.allowed_repos
        if allowed and repo not in allowed:
            await self._audit(
                f"deny-goal:{_digest(text)}", {"reason": "repo-not-allowed", "repo": repo}
            )
            return HandleResult(
                "rejected", reason=f"repo-not-allowed:{repo}", policy_version=version
            )

        ticket_id = f"tkt_{_digest(f'goal:{repo}:{text}')}"
        existing = await self.get_ticket(ticket_id)
        if existing is not None and existing.stage in {"open", "running", "review"}:
            return HandleResult(
                "duplicate",
                ticket_id=ticket_id,
                reason="active-ticket-exists",
                policy_version=version,
            )

        ticket = Ticket(
            ticket_id=ticket_id,
            source_id="user",
            source_event_key=f"goal:{_digest(text)}",
            thread_key=f"goal:{_digest(text)}",
            stage="open",
            mandate=Mandate(
                repo_root=repo,
                allowed_paths=tuple(allowed_paths or ()),
                allowed_tools=tuple(self.policy.config.allowed_tools),
                base_branch=str(base_branch or self.policy.config.default_base_branch),
                can_push=bool(can_push),
                can_create_pr=bool(can_create_pr),
                policy_version=version,
            ),
            instructions=text,
            decision_reason="submitted-by-user",
            policy_version=version,
            title=(title or text)[:120],
            permission_preset=preset,
        )
        # 同一个目标在关闭之后可以重新交付一次，所以这里不是 create_only。
        await self.store.put(_TICKET, ticket.ticket_id, ticket.to_dict())
        await self._audit(
            f"goal:{ticket.ticket_id}",
            {
                "repo": repo,
                "can_push": ticket.mandate.can_push,
                "can_create_pr": ticket.mandate.can_create_pr,
            },
        )
        if self.scheduler is not None:
            await self._schedule(ticket)
        return HandleResult(
            "accepted",
            ticket_id=ticket.ticket_id,
            reason="submitted-by-user",
            policy_version=version,
        )

    async def begin_execution(
        self,
        ticket_id: str,
        *,
        execution_id: str = "",
        model_id: str = "",
        context: dict[str, Any] | None = None,
    ) -> ExecutionPlan:
        """准备执行现场并生成指令：工作树、分支、assignment、提示词一次备齐。"""
        ticket = await self.get_ticket(ticket_id)
        if ticket is None:
            raise LookupError(f"ticket not found: {ticket_id}")
        execution = execution_id or f"exec_{_digest(f'{ticket_id}:{utcnow().isoformat()}')}"
        assignment = await self.start_assignment(ticket_id, execution)
        work_root = assignment.worktree_path or ticket.mandate.repo_root
        prompt = build_ticket_prompt(
            ticket,
            work_root=work_root,
            branch=assignment.branch,
            model_id=model_id,
            context=context,
        )
        await self._patch_ticket(
            ticket_id, assignment_id=assignment.assignment_id, stage="running"
        )
        return ExecutionPlan(
            ticket_id=ticket_id,
            assignment_id=assignment.assignment_id,
            work_root=work_root,
            branch=assignment.branch,
            prompt=prompt,
            thread_id=f"ticket:{ticket_id}",
            permission_preset=ticket.permission_preset or "auto",
        )

    async def record_execution_result(
        self,
        ticket_id: str,
        *,
        status: str,
        report: dict[str, Any] | None = None,
        summary: str = "",
        error: str = "",
    ) -> Ticket | None:
        """把一次执行的结果写回工单。

        user:“监控、处理异常、恢复任务、验证成果并完成交付”+(结果必须落到工单上，
        否则工单永远停在 running，用户看不到做成了什么、为什么没做成)。
        """
        ticket = await self.get_ticket(ticket_id)
        if ticket is None:
            return None
        payload = dict(report or {})
        if summary:
            payload.setdefault("summary", summary)
        if error:
            payload.setdefault("error", error)
        payload.setdefault("finished_at", utcnow().isoformat())
        if ticket.assignment_id:
            try:
                await self.finish_assignment(
                    ticket.assignment_id, status=status, report=payload
                )
            except LookupError:
                # 执行现场记录丢了也要把工单阶段改对，不能让用户看到一个永远在跑的工单。
                stage: TicketStage = "review" if status == "completed" else "blocked"
                await self._set_stage(ticket_id, stage, reason=f"execution-{status}")
        else:
            stage = "review" if status == "completed" else "blocked"
            await self._set_stage(ticket_id, stage, reason=f"execution-{status}")
        updated = await self._patch_ticket(ticket_id, result=payload)
        await self._audit(
            f"result:{ticket_id}",
            {"status": status, "error": error, "stage": updated.stage},
        )
        return updated

    async def close_ticket(
        self, ticket_id: str, *, accepted: bool = True, note: str = ""
    ) -> Ticket:
        """用户验收：收下成果，或明确退回。"""
        reason = (
            f"closed-by-user:{note}" if accepted else f"rejected-by-user:{note}"
        )
        return await self._set_stage(ticket_id, "closed", reason=reason)

    async def retry_ticket(self, ticket_id: str) -> Ticket:
        """把失败或待验收的工单重新排一次。"""
        ticket = await self.get_ticket(ticket_id)
        if ticket is None:
            raise LookupError(f"ticket not found: {ticket_id}")
        if ticket.stage == "running":
            raise ValueError("ticket is still running")
        updated = await self._patch_ticket(
            ticket_id,
            stage="open",
            job_id="",
            assignment_id="",
            decision_reason="retried-by-user",
        )
        await self._schedule(updated)
        return await self.get_ticket(ticket_id) or updated

    # ------------------------------------------------------------------ 内部
    async def _prepare_worktree(
        self, ticket: Ticket, *, base_branch: str
    ) -> tuple[str, str]:
        if self.worktree_manager is None:
            return "", ""
        try:
            info = await self.worktree_manager.ensure(
                ticket.ticket_id, ticket.mandate.repo_root, base_branch
            )
        except WorktreeError as exc:
            # 不是 git 仓库就原地执行，用户可能只是让它在普通目录里干活；
            # 是 git 仓库却建不出工作树，说明隔离失败，必须明确失败而不是偷偷改用户的检出。
            if _is_git_repo(ticket.mandate.repo_root):
                await self._set_stage(
                    ticket.ticket_id, "blocked", reason=f"worktree-failed:{exc}"
                )
                raise
            await self._audit(
                f"worktree-skip:{ticket.ticket_id}", {"reason": str(exc)}
            )
            return "", ""
        return str(info["path"]), str(info["branch"])

    async def _patch_ticket(self, ticket_id: str, **changes: Any) -> Ticket:
        last_error: Exception | None = None
        for _ in range(4):
            ticket = await self.get_ticket(ticket_id)
            if ticket is None:
                raise LookupError(f"ticket not found: {ticket_id}")
            data = {**ticket.to_dict(), **changes, "updated_at": utcnow().isoformat()}
            try:
                stored = await self.store.put(
                    _TICKET,
                    ticket_id,
                    Ticket.from_dict(data).to_dict(),
                    expected_revision=ticket.revision,
                )
            except ConcurrentUpdate as exc:
                last_error = exc
                continue
            return Ticket.from_dict(stored)
        raise ConcurrentUpdate(f"ticket {ticket_id} kept changing: {last_error}")

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


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _is_git_repo(path: str) -> bool:
    try:
        candidate = Path(path)
    except (OSError, ValueError):
        return False
    # worktree 的 .git 是文件而不是目录，两种都要认。
    return (candidate / ".git").exists()


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
    "ExecutionPlan",
    "HandleResult",
    "Scheduler",
    "SuperagentService",
]
