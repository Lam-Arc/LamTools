"""`core superagent` 参数注册。

user:“CLI 先行，最小可用实现优先”+(先让人能在命令行里投递事件、看工单、
批准/拒绝/停止，再接界面)。
"""

from __future__ import annotations

import argparse
import os


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-url",
        default=os.environ.get("LAMTOOLS_CORE_API_URL", "http://127.0.0.1:5172"),
    )
    parser.add_argument(
        "--ws-path",
        default=os.environ.get("LAMTOOLS_CORE_WS_PATH", "/api/core/app-server"),
    )
    parser.add_argument("--token", default=os.environ.get("LAMTOOLS_CORE_TOKEN", ""))


def register_superagent(sub: argparse._SubParsersAction) -> None:
    from .superagent import (
        cmd_superagent_approve,
        cmd_superagent_assignments,
        cmd_superagent_audit,
        cmd_superagent_ingest,
        cmd_superagent_policy,
        cmd_superagent_reject,
        cmd_superagent_show,
        cmd_superagent_stop,
        cmd_superagent_tickets,
    )

    root = sub.add_parser("superagent", help="Authorized event-driven tickets (Super-agent)")
    group = root.add_subparsers(dest="superagent_command", required=True)

    ingest = group.add_parser("ingest", help="Deliver one source event")
    ingest.add_argument("--source", required=True, help="Source id (must be authorized)")
    ingest.add_argument("--event-id", required=True, help="Stable source event id")
    ingest.add_argument("--event-type", required=True, help="Event type (must be authorized)")
    ingest.add_argument("--actor", required=True, help="Actor id (must be authorized + trusted)")
    ingest.add_argument("--repo", required=True, help="Repository root the mandate covers")
    ingest.add_argument("--text", required=True, help="Instruction text")
    ingest.add_argument("--thread-key", default="", help="Thread key used to group follow-ups")
    ingest.add_argument(
        "--requested-actions",
        default="",
        help="Comma separated high-risk actions requested by the event (push,create_pr,merge,release)",
    )
    ingest.add_argument(
        "--trusted",
        action="store_true",
        help="Actor identity verified by the adapter (still needs to be on the allowlist)",
    )
    _common(ingest)
    ingest.set_defaults(func=cmd_superagent_ingest, raw=False)

    tickets = group.add_parser("tickets", help="List tickets")
    tickets.add_argument("--stage", default="", help="Filter: open/running/review/blocked/closed")
    _common(tickets)
    tickets.set_defaults(func=cmd_superagent_tickets, raw=False)

    show = group.add_parser("show", help="Show one ticket")
    show.add_argument("ticket_id")
    _common(show)
    show.set_defaults(func=cmd_superagent_show, raw=False)

    approve = group.add_parser("approve", help="Approve a blocked ticket (human gate)")
    approve.add_argument("ticket_id")
    approve.add_argument("--approver", default="cli", help="Who approved it (audited)")
    _common(approve)
    approve.set_defaults(func=cmd_superagent_approve, raw=False)

    reject = group.add_parser("reject", help="Reject a ticket")
    reject.add_argument("ticket_id")
    reject.add_argument("--reason", default="", help="Reason recorded in the audit trail")
    _common(reject)
    reject.set_defaults(func=cmd_superagent_reject, raw=False)

    stop = group.add_parser("stop", help="Stop a running ticket")
    stop.add_argument("ticket_id")
    _common(stop)
    stop.set_defaults(func=cmd_superagent_stop, raw=False)

    assignments = group.add_parser("assignments", help="List execution attempts")
    assignments.add_argument("ticket_id", nargs="?", default="")
    _common(assignments)
    assignments.set_defaults(func=cmd_superagent_assignments, raw=False)

    audit = group.add_parser("audit", help="Show the audit trail")
    _common(audit)
    audit.set_defaults(func=cmd_superagent_audit, raw=False)

    policy = group.add_parser("policy", help="Show the active authorization policy")
    _common(policy)
    policy.set_defaults(func=cmd_superagent_policy, raw=False)


__all__ = ["register_superagent"]
