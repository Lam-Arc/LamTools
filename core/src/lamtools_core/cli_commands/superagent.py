"""`core superagent` 命令实现（只做参数整形与展示，业务全在宿主侧）。"""

from __future__ import annotations

import argparse
import json
from typing import Any


async def _call(args: argparse.Namespace, name: str, params: dict[str, Any]) -> dict[str, Any]:
    from .connection import _invoke_live

    async def op(client: Any) -> dict[str, Any]:
        return await client.request(name, params)

    result = await _invoke_live(args, op)
    return result if isinstance(result, dict) else {}


def _print_ticket(ticket: dict[str, Any]) -> None:
    if not isinstance(ticket, dict):
        return
    for key in (
        "ticket_id",
        "stage",
        "source_id",
        "source_event_key",
        "thread_key",
        "decision_reason",
        "policy_version",
        "instructions",
    ):
        value = ticket.get(key)
        if value not in (None, ""):
            print(f"  {key}: {value}")
    mandate = ticket.get("mandate")
    if isinstance(mandate, dict):
        print(f"  mandate: repo={mandate.get('repo_root')} push={mandate.get('can_push')} "
              f"pr={mandate.get('can_create_pr')} revoked={mandate.get('revoked')}")


async def cmd_superagent_ingest(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {"text": str(args.text or "")}
    if args.requested_actions:
        payload["requested_actions"] = [
            item.strip() for item in str(args.requested_actions).split(",") if item.strip()
        ]
    params = {
        "source_id": args.source,
        "event_id": args.event_id,
        "event_type": args.event_type,
        "actor": {
            "actor_id": args.actor,
            "login": args.actor,
            "trusted": bool(args.trusted),
        },
        "repo": args.repo,
        "thread_key": args.thread_key,
        "payload": payload,
    }
    result = await _call(args, "superagent.ingest", params)
    print(json.dumps(result.get("result", result), ensure_ascii=False, indent=2))
    return 0


async def cmd_superagent_goal(args: argparse.Namespace) -> int:
    """用户直接交付一个目标。

    user:“让用户能够直接交付复杂目标”+(界面和命令行走同一条路：都提交到
    superagent.goal.submit，不各自维护一套建单逻辑)。
    """
    params = {
        "goal": str(args.goal or ""),
        "repo_root": str(args.repo or ""),
        "title": str(args.title or ""),
        "base_branch": str(args.base_branch or ""),
        "can_push": bool(args.allow_push),
        "can_create_pr": bool(args.allow_pr),
        "permission_preset": str(args.permission_preset or "auto"),
        "require_approval": bool(args.require_approval),
    }
    result = await _call(args, "superagent.goal.submit", params)
    print(json.dumps(result.get("result", result), ensure_ascii=False, indent=2))
    return 0


async def cmd_superagent_report(args: argparse.Namespace) -> int:
    result = await _call(args, "superagent.ticket.report", {"ticket_id": args.ticket_id})
    if result.get("status") == "error":
        print(f"error: {result.get('payload', {}).get('error')}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


async def cmd_superagent_close(args: argparse.Namespace) -> int:
    result = await _call(
        args,
        "superagent.ticket.close",
        {
            "ticket_id": args.ticket_id,
            "accepted": not bool(args.reject),
            "note": str(args.note or ""),
        },
    )
    if result.get("status") == "error":
        print(f"error: {result.get('payload', {}).get('error')}")
        return 1
    _print_ticket(result.get("ticket") or {})
    return 0


async def cmd_superagent_retry(args: argparse.Namespace) -> int:
    result = await _call(args, "superagent.ticket.retry", {"ticket_id": args.ticket_id})
    if result.get("status") == "error":
        print(f"error: {result.get('payload', {}).get('error')}")
        return 1
    _print_ticket(result.get("ticket") or {})
    return 0


async def cmd_superagent_tickets(args: argparse.Namespace) -> int:
    result = await _call(args, "superagent.ticket.list", {"stage": args.stage})
    tickets = result.get("tickets") or []
    if not tickets:
        print("no tickets")
        return 0
    for ticket in tickets:
        print(
            f"{str(ticket.get('ticket_id'))[:20]:22s} {str(ticket.get('stage') or '?'):10s} "
            f"{str(ticket.get('instructions') or '')[:60]}"
        )
    return 0


async def cmd_superagent_show(args: argparse.Namespace) -> int:
    result = await _call(args, "superagent.ticket.get", {"ticket_id": args.ticket_id})
    if result.get("status") == "error":
        print(f"error: {result.get('payload', {}).get('error')}")
        return 1
    _print_ticket(result.get("ticket") or {})
    return 0


async def cmd_superagent_approve(args: argparse.Namespace) -> int:
    result = await _call(
        args,
        "superagent.ticket.approve",
        {"ticket_id": args.ticket_id, "approver": args.approver},
    )
    if result.get("status") == "error":
        print(f"error: {result.get('payload', {}).get('error')}")
        return 1
    _print_ticket(result.get("ticket") or {})
    return 0


async def cmd_superagent_reject(args: argparse.Namespace) -> int:
    result = await _call(
        args,
        "superagent.ticket.reject",
        {"ticket_id": args.ticket_id, "reason": args.reason},
    )
    if result.get("status") == "error":
        print(f"error: {result.get('payload', {}).get('error')}")
        return 1
    _print_ticket(result.get("ticket") or {})
    return 0


async def cmd_superagent_stop(args: argparse.Namespace) -> int:
    result = await _call(args, "superagent.ticket.stop", {"ticket_id": args.ticket_id})
    if result.get("status") == "error":
        print(f"error: {result.get('payload', {}).get('error')}")
        return 1
    _print_ticket(result.get("ticket") or {})
    return 0


async def cmd_superagent_assignments(args: argparse.Namespace) -> int:
    result = await _call(
        args, "superagent.assignment.list", {"ticket_id": args.ticket_id}
    )
    assignments = result.get("assignments") or []
    if not assignments:
        print("no assignments")
        return 0
    for item in assignments:
        print(
            f"{str(item.get('assignment_id'))[:18]:20s} {str(item.get('status') or '?'):10s} "
            f"{str(item.get('branch') or '')}"
        )
    return 0


async def cmd_superagent_audit(args: argparse.Namespace) -> int:
    result = await _call(args, "superagent.audit.list", {})
    print(json.dumps(result.get("audit") or [], ensure_ascii=False, indent=2))
    return 0


async def cmd_superagent_policy(args: argparse.Namespace) -> int:
    result = await _call(args, "superagent.policy", {})
    print(json.dumps(result.get("policy") or {}, ensure_ascii=False, indent=2))
    return 0


__all__ = [
    "cmd_superagent_approve",
    "cmd_superagent_assignments",
    "cmd_superagent_audit",
    "cmd_superagent_close",
    "cmd_superagent_goal",
    "cmd_superagent_ingest",
    "cmd_superagent_policy",
    "cmd_superagent_reject",
    "cmd_superagent_report",
    "cmd_superagent_retry",
    "cmd_superagent_show",
    "cmd_superagent_stop",
    "cmd_superagent_tickets",
]
