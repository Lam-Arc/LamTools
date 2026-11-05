"""Super-agent 操作面（HTTP / CLI 共用同一套 OperationCatalog）。

user:“CLI 先行，最小可用实现优先”“界面只消费这些 API”
+(所以这里只做操作注册；Tauri 面板之后只读这些返回值，不自己写业务逻辑)。
"""

from __future__ import annotations

from typing import Any

from lamtools_core.superagent.models import SourceActor, SourceEvent
from lamtools_core.superagent.service import SuperagentService

from .operation_catalog import OperationCatalog, OperationRequest, OperationResult


SUPERAGENT_OPERATION_NAMES: tuple[str, ...] = (
    "superagent.goal.submit",
    "superagent.ingest",
    "superagent.ticket.list",
    "superagent.ticket.get",
    "superagent.ticket.report",
    "superagent.ticket.approve",
    "superagent.ticket.reject",
    "superagent.ticket.stop",
    "superagent.ticket.close",
    "superagent.ticket.retry",
    "superagent.assignment.list",
    "superagent.audit.list",
    "superagent.policy",
)


def register_superagent_operations(
    catalog: OperationCatalog,
    *,
    service: SuperagentService,
) -> None:
    def _error(request: OperationRequest, exc: object) -> OperationResult:
        return OperationResult(
            name=request.name,
            status="error",
            payload={"error": str(exc)},
        )

    def _ticket_id(payload: dict[str, Any]) -> str:
        return str(
            payload.get("ticket_id") or payload.get("ticketId") or payload.get("id") or ""
        ).strip()

    async def superagent_ingest(request: OperationRequest) -> OperationResult:
        payload = dict(request.payload)
        actor_raw = dict(payload.get("actor") or {})
        event = SourceEvent(
            source_id=str(payload.get("source_id") or payload.get("sourceId") or "").strip(),
            event_id=str(payload.get("event_id") or payload.get("eventId") or "").strip(),
            event_type=str(payload.get("event_type") or payload.get("eventType") or "").strip(),
            actor=SourceActor(
                actor_id=str(actor_raw.get("actor_id") or actor_raw.get("id") or "").strip(),
                login=str(actor_raw.get("login") or "").strip(),
                trusted=bool(actor_raw.get("trusted")),
            ),
            payload=dict(payload.get("payload") or {}),
            subject=str(payload.get("subject") or ""),
            thread_key=str(payload.get("thread_key") or payload.get("threadKey") or ""),
            repo=str(payload.get("repo") or ""),
        )
        try:
            result = await service.handle_event(event)
        except (LookupError, PermissionError, RuntimeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(
            name=request.name,
            payload={"result": result.to_dict(), "policy_version": result.policy_version},
        )

    async def superagent_goal_submit(request: OperationRequest) -> OperationResult:
        """用户直接把目标交给 Super-agent。

        user:“让用户能够直接交付复杂目标”+(界面只需要把目标、仓库和授权范围送进来，
        建工单、开工作树、排期全部复用既有能力，不在这里写第二套逻辑)。
        """
        payload = dict(request.payload)
        goal = str(
            payload.get("goal") or payload.get("text") or payload.get("message") or ""
        )
        repo_root = str(
            payload.get("repo_root")
            or payload.get("repoRoot")
            or payload.get("work_root")
            or payload.get("workRoot")
            or ""
        )
        try:
            result = await service.submit_goal(
                goal,
                repo_root=repo_root,
                title=str(payload.get("title") or ""),
                base_branch=str(
                    payload.get("base_branch") or payload.get("baseBranch") or ""
                ),
                allowed_paths=tuple(
                    payload.get("allowed_paths") or payload.get("allowedPaths") or ()
                ),
                can_push=bool(payload.get("can_push") or payload.get("canPush")),
                can_create_pr=bool(
                    payload.get("can_create_pr") or payload.get("canCreatePr")
                ),
            )
        except (LookupError, PermissionError, RuntimeError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(
            name=request.name,
            payload={
                "result": result.to_dict(),
                "ticket_id": result.ticket_id,
            },
        )

    async def superagent_ticket_report(request: OperationRequest) -> OperationResult:
        """一张工单的完整交付视图：工单本身加每次执行现场。"""
        ticket_id = _ticket_id(request.payload)
        ticket = await service.get_ticket(ticket_id)
        if ticket is None:
            return OperationResult(
                request.name,
                status="error",
                payload={"code": "not-found", "error": "Ticket not found"},
            )
        assignments = await service.list_assignments(ticket_id)
        return OperationResult(
            name=request.name,
            payload={
                "ticket": ticket.to_dict(),
                "assignments": [item.to_dict() for item in assignments],
            },
        )

    async def superagent_ticket_close(request: OperationRequest) -> OperationResult:
        """用户验收：收下成果或明确退回。"""
        payload = dict(request.payload)
        accepted = payload.get("accepted")
        accepted = True if accepted is None else bool(accepted)
        try:
            ticket = await service.close_ticket(
                _ticket_id(payload), accepted=accepted, note=str(payload.get("note") or "")
            )
        except (LookupError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"ticket": ticket.to_dict()})

    async def superagent_ticket_retry(request: OperationRequest) -> OperationResult:
        """把失败或待验收的工单重新排一次。"""
        try:
            ticket = await service.retry_ticket(_ticket_id(request.payload))
        except (LookupError, ValueError, RuntimeError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"ticket": ticket.to_dict()})

    async def superagent_ticket_list(request: OperationRequest) -> OperationResult:
        stage = str(request.payload.get("stage") or "").strip()
        tickets = await service.list_tickets(stage=stage)
        return OperationResult(
            name=request.name,
            payload={"tickets": [item.to_dict() for item in tickets]},
        )

    async def superagent_ticket_get(request: OperationRequest) -> OperationResult:
        ticket = await service.get_ticket(_ticket_id(request.payload))
        if ticket is None:
            return OperationResult(
                request.name,
                status="error",
                payload={"code": "not-found", "error": "Ticket not found"},
            )
        return OperationResult(name=request.name, payload={"ticket": ticket.to_dict()})

    async def superagent_ticket_approve(request: OperationRequest) -> OperationResult:
        approver = str(request.payload.get("approver") or "human").strip() or "human"
        try:
            ticket = await service.approve(_ticket_id(request.payload), approver=approver)
        except (LookupError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"ticket": ticket.to_dict()})

    async def superagent_ticket_reject(request: OperationRequest) -> OperationResult:
        reason = str(request.payload.get("reason") or "").strip()
        try:
            ticket = await service.reject(_ticket_id(request.payload), reason=reason)
        except (LookupError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"ticket": ticket.to_dict()})

    async def superagent_ticket_stop(request: OperationRequest) -> OperationResult:
        try:
            ticket = await service.stop(_ticket_id(request.payload))
        except (LookupError, ValueError) as exc:
            return _error(request, exc)
        return OperationResult(name=request.name, payload={"ticket": ticket.to_dict()})

    async def superagent_assignment_list(request: OperationRequest) -> OperationResult:
        assignments = await service.list_assignments(_ticket_id(request.payload))
        return OperationResult(
            name=request.name,
            payload={"assignments": [item.to_dict() for item in assignments]},
        )

    async def superagent_audit_list(request: OperationRequest) -> OperationResult:
        return OperationResult(
            name=request.name, payload={"audit": await service.list_audit()}
        )

    async def superagent_policy(request: OperationRequest) -> OperationResult:
        config = service.policy.config
        return OperationResult(
            name=request.name,
            payload={
                "policy": {
                    "version": config.version,
                    "allowed_sources": sorted(config.allowed_sources),
                    "allowed_event_types": sorted(config.allowed_event_types),
                    "trusted_actors": sorted(config.trusted_actors),
                    "allowed_repos": sorted(config.allowed_repos),
                    "allow_push": config.allow_push,
                    "allow_create_pr": config.allow_create_pr,
                }
            },
        )

    handlers = {
        "superagent.goal.submit": superagent_goal_submit,
        "superagent.ingest": superagent_ingest,
        "superagent.ticket.list": superagent_ticket_list,
        "superagent.ticket.get": superagent_ticket_get,
        "superagent.ticket.report": superagent_ticket_report,
        "superagent.ticket.approve": superagent_ticket_approve,
        "superagent.ticket.reject": superagent_ticket_reject,
        "superagent.ticket.stop": superagent_ticket_stop,
        "superagent.ticket.close": superagent_ticket_close,
        "superagent.ticket.retry": superagent_ticket_retry,
        "superagent.assignment.list": superagent_assignment_list,
        "superagent.audit.list": superagent_audit_list,
        "superagent.policy": superagent_policy,
    }
    for name in SUPERAGENT_OPERATION_NAMES:
        catalog.register(name, handlers[name])


__all__ = ["SUPERAGENT_OPERATION_NAMES", "register_superagent_operations"]
