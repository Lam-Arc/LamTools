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
    "superagent.ingest",
    "superagent.ticket.list",
    "superagent.ticket.get",
    "superagent.ticket.approve",
    "superagent.ticket.reject",
    "superagent.ticket.stop",
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
        "superagent.ingest": superagent_ingest,
        "superagent.ticket.list": superagent_ticket_list,
        "superagent.ticket.get": superagent_ticket_get,
        "superagent.ticket.approve": superagent_ticket_approve,
        "superagent.ticket.reject": superagent_ticket_reject,
        "superagent.ticket.stop": superagent_ticket_stop,
        "superagent.assignment.list": superagent_assignment_list,
        "superagent.audit.list": superagent_audit_list,
        "superagent.policy": superagent_policy,
    }
    for name in SUPERAGENT_OPERATION_NAMES:
        catalog.register(name, handlers[name])


__all__ = ["SUPERAGENT_OPERATION_NAMES", "register_superagent_operations"]
