"""Backfill the turn-control read models from an existing thread snapshot.

Upgrading an installation must not lose a turn that is already waiting for the
user.  The event log remains the source of truth; this pass derives the new
``turn_control`` and ``interactions`` rows from the snapshot that older builds
already persisted.  It is idempotent and never overwrites a newer row.
"""

from __future__ import annotations

import logging
from typing import Any

from .model import (
    Interaction,
    InteractionOption,
    Turn,
    now_ms,
)
from .store import TurnStore

_logger = logging.getLogger(__name__)

_ALLOWED_TURN_STATUSES = {
    "queued",
    "running",
    "waiting",
    "paused",
    "stopping",
    "completed",
    "failed",
    "cancelled",
}


def _merged_turns(snapshot: dict[str, Any]) -> dict[str, Any]:
    turns: dict[str, Any] = {}
    outer = snapshot.get("turns")
    if isinstance(outer, dict):
        turns.update(outer)
    core = snapshot.get("core")
    core_turns = core.get("turns") if isinstance(core, dict) else None
    if isinstance(core_turns, dict):
        turns.update(core_turns)
    return turns


def _merged_requests(snapshot: dict[str, Any]) -> dict[str, Any]:
    requests: dict[str, Any] = {}
    outer = snapshot.get("requests")
    if isinstance(outer, dict):
        requests.update(outer)
    core = snapshot.get("core")
    core_requests = core.get("requests") if isinstance(core, dict) else None
    if isinstance(core_requests, dict):
        requests.update(core_requests)
    return requests


async def backfill_snapshot(
    store: TurnStore,
    thread_id: str,
    snapshot: dict[str, Any],
) -> int:
    """Derive turns and open interactions from one thread snapshot."""
    if not thread_id or not isinstance(snapshot, dict):
        return 0
    written = 0
    turns = _merged_turns(snapshot)
    turn_ids: list[str] = []
    for raw_turn_id, raw_turn in turns.items():
        if not isinstance(raw_turn, dict):
            continue
        turn_id = str(raw_turn.get("turn_id") or raw_turn_id)
        status = str(raw_turn.get("status") or "completed")
        if status not in _ALLOWED_TURN_STATUSES:
            status = "completed"
        turn_ids.append(turn_id)
        existing = await store.get_turn(turn_id)
        if existing is not None:
            continue
        run_id = str(raw_turn.get("run_id") or "")
        await store.create_turn(
            Turn(
                turn_id=turn_id,
                thread_id=thread_id,
                status=status,  # type: ignore[arg-type]
                epoch=0,
                active_run_id=run_id if status in {"running", "waiting", "paused"} else "",
                created_seq=int(raw_turn.get("first_seq") or raw_turn.get("seq") or 0),
                updated_seq=int(raw_turn.get("last_seq") or raw_turn.get("seq") or 0),
                input={"input": raw_turn.get("input") or []},
            )
        )
        written += 1

    requests = _merged_requests(snapshot)
    latest_turn = turn_ids[-1] if turn_ids else ""
    for request_id, request in requests.items():
        if not isinstance(request, dict):
            continue
        if str(request.get("status") or "") != "open":
            continue
        tool_name = str(request.get("tool_name") or "")
        kind = "question" if tool_name == "question" else "approval"
        turn_id = str(request.get("turn_id") or latest_turn)
        if not turn_id:
            continue
        options = [
            InteractionOption.from_dict(option)
            for option in request.get("options") or []
            if isinstance(option, dict)
        ]
        interaction = Interaction(
            interaction_id=str(request.get("request_id") or request_id),
            turn_id=turn_id,
            thread_id=thread_id,
            run_id=str(request.get("run_id") or ""),
            scope="main",
            kind=kind,  # type: ignore[arg-type]
            status="open",
            tool_call_id=str(request.get("tool_call_id") or ""),
            legacy_request_id=str(request.get("request_id") or request_id),
            title=str(request.get("message") or ""),
            context=str(request.get("context") or ""),
            options=options,
            # A restart starts a fresh question window; approvals never expire.
            expires_at_ms=(now_ms() + 5 * 60 * 1000) if kind == "question" else 0,
            metadata={"backfilled": True, "item_id": str(request.get("item_id") or "")},
        )
        existing = await store.get_interaction(interaction.interaction_id)
        if existing is not None:
            continue
        await store.create_interaction(interaction)
        written += 1
    if written:
        _logger.info(
            "[turn-migrate] backfilled %d row(s) thread_id=%s", written, thread_id
        )
    return written


__all__ = ["backfill_snapshot"]
