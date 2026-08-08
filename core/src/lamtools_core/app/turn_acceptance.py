from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lamtools_core.event import RunItemEvent


# Dedup method scopes. Each acceptance operation dedupes only against its own
# prior accepted-event method, so a client_message_id collision across
# turn.start and queue.create cannot cause one operation to be silently
# deduped against the other.
TURN_ACCEPTED_METHODS = {"turn/accepted"}
QUEUE_ITEM_ACCEPTED_METHODS = {"queue/itemAccepted"}


@dataclass(frozen=True)
class CoreAppEventSpec:
    thread_id: str
    method: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str | None = None
    turn_id: str | None = None
    item_id: str | None = None
    parent_item_id: str | None = None
    client_message_id: str | None = None


@dataclass(frozen=True)
class TurnAcceptancePlan:
    turn_accepted: CoreAppEventSpec
    user_item: CoreAppEventSpec
    running_status: RunItemEvent

    @property
    def app_events(self) -> list[CoreAppEventSpec]:
        return [self.turn_accepted, self.user_item]


def build_turn_acceptance_plan(
    *,
    thread_id: str,
    turn_id: str,
    user_item_id: str,
    client_message_id: str,
    input_items: list[dict[str, Any]],
    work_root: str | None = None,
    turn_payload_extra: dict[str, Any] | None = None,
    user_payload_extra: dict[str, Any] | None = None,
    include_turn_status: bool = True,
) -> TurnAcceptancePlan:
    turn_payload: dict[str, Any] = {
        "type": "turn",
        "input": input_items,
        "work_root": work_root or "",
    }
    if include_turn_status:
        turn_payload["status"] = "running"
    if turn_payload_extra:
        turn_payload.update(turn_payload_extra)

    user_payload: dict[str, Any] = {
        "type": "userMessage",
        "status": "completed",
        "content": input_items,
    }
    if user_payload_extra:
        user_payload.update(user_payload_extra)

    return TurnAcceptancePlan(
        turn_accepted=CoreAppEventSpec(
            thread_id=thread_id,
            method="turn/accepted",
            turn_id=turn_id,
            client_message_id=client_message_id,
            payload=turn_payload,
        ),
        user_item=CoreAppEventSpec(
            thread_id=thread_id,
            method="item/started",
            turn_id=turn_id,
            item_id=user_item_id,
            client_message_id=client_message_id,
            payload=user_payload,
        ),
        running_status=RunItemEvent(
            kind="status",
            thread_id=thread_id,
            event_id=f"{turn_id}:running",
            run_id=turn_id,
            turn_id=turn_id,
            item_id=f"{turn_id}:running",
            status="running",
            payload={"type": "turn", "status": "running"},
        ),
    )


def build_cancelled_turn_event(
    *,
    thread_id: str,
    turn_id: str,
    message: str = "",
) -> RunItemEvent:
    payload: dict[str, Any] = {
        "type": "turn",
        "status": "cancelled",
        "raw_end_reason": "user_interrupt",
    }
    if message:
        payload["message"] = message
    return RunItemEvent(
        kind="status",
        thread_id=thread_id,
        event_id=f"{turn_id}:cancelled",
        run_id=turn_id,
        turn_id=turn_id,
        item_id=f"{turn_id}:cancelled",
        status="cancelled",
        payload=payload,
    )


__all__ = [
    "CoreAppEventSpec",
    "QUEUE_ITEM_ACCEPTED_METHODS",
    "TURN_ACCEPTED_METHODS",
    "TurnAcceptancePlan",
    "build_cancelled_turn_event",
    "build_turn_acceptance_plan",
]
