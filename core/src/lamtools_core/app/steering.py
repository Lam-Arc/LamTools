"""Recover accepted steering from existing events/history, without executing a turn."""
from __future__ import annotations

import hashlib
from typing import Any
from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased
from lamtools_core.runtime import normalize_run_id
from .core_db import CoreAppEvent, CoreHistoryEntry
from .event_store import AppEventInput

# user:“将回合暂停并输入引导信息并发送的时候，有可能会将大量已经成功发送并被处理过的用户信息再次发送”+(引导是否已被内核消费必须是持久事件事实；历史消息会在暂停时被压缩视图整体回写，不能再拿它当消费凭据)。
GUIDANCE_CONSUMED_METHOD = "guidance/consumed"
GUIDANCE_HANDOFF_IDS = "guidance_handoff_ids"


def _consumed_event_id(thread_id: str, guidance_id: str) -> str:
    digest = hashlib.sha256(f"{thread_id}\0{guidance_id}".encode("utf-8")).hexdigest()
    return f"gc{digest[:14]}"


async def record_consumed_guidance(
    session_factory: Any,
    *,
    thread_id: str,
    turn_id: str,
    guidance_ids: list[str],
    event_store: Any,
    write_coordinator: Any,
) -> None:
    """Persist the consumption fact independently of the compactable history rows.

    Each guidance id gets its own deterministic event id so retries and repeated
    acknowledgements are idempotent instead of growing the event log.
    """
    ids = list(dict.fromkeys(
        str(guidance_id).strip()
        for guidance_id in guidance_ids
        if str(guidance_id or "").strip()
    ))
    if not ids or session_factory is None or event_store is None or write_coordinator is None:
        return

    async def write(db: Any) -> None:
        for guidance_id in ids:
            await event_store.append(db, AppEventInput(
                event_id=_consumed_event_id(thread_id, guidance_id),
                thread_id=thread_id,
                turn_id=turn_id or None,
                client_message_id=guidance_id,
                method=GUIDANCE_CONSUMED_METHOD,
                payload={"guidance_ids": [guidance_id]},
            ))

    await write_coordinator.run(write)


async def pending_steering(
    session_factory: Any,
    thread_id: str,
    *,
    turn_id: str | None = None,
    event_store: Any | None = None,
    write_coordinator: Any | None = None,
) -> list[dict[str, Any]]:
    # user:“全修”+(先在事件表按引导编号排除已消费和已转交的记录；只有仍待确认的编号才检查旧历史)。
    receipt = aliased(CoreAppEvent)
    consumed = select(receipt.event_id).where(
        receipt.thread_id == CoreAppEvent.thread_id,
        receipt.client_message_id == CoreAppEvent.client_message_id,
        receipt.method == GUIDANCE_CONSUMED_METHOD,
    ).exists()
    handoff_ids = func.json_each(
        receipt.payload_json, f"$.{GUIDANCE_HANDOFF_IDS}",
    ).table_valued("value", joins_implicitly=True)
    handoffs = select(handoff_ids.c.value).where(
        receipt.thread_id == thread_id,
        receipt.method.in_(("turn/accepted", "queue/itemAccepted")),
        handoff_ids.c.value.is_not(None),
    )
    # Legacy receipts can have only payload IDs. Current receipts each carry one indexed client ID.
    legacy_ids = func.json_each(receipt.payload_json, "$.guidance_ids").table_valued("value", joins_implicitly=True)
    legacy_receipts = select(legacy_ids.c.value).where(
        receipt.thread_id == thread_id,
        receipt.method == GUIDANCE_CONSUMED_METHOD,
        legacy_ids.c.value.is_not(None),
        or_(receipt.client_message_id.is_(None), legacy_ids.c.value != receipt.client_message_id),
    )
    pending = select(CoreAppEvent).where(
        CoreAppEvent.thread_id == thread_id,
        CoreAppEvent.method == "turn/steered",
        CoreAppEvent.client_message_id.is_not(None),
        CoreAppEvent.client_message_id != "",
        CoreAppEvent.payload_json["guidance_id"].as_string().is_not(None),
        ~consumed,
        CoreAppEvent.client_message_id.not_in(handoffs.union_all(legacy_receipts)),
    )
    if turn_id is not None:
        target = normalize_run_id(thread_id, turn_id)
        pending = pending.where(CoreAppEvent.turn_id.in_([target, f"{thread_id}:turn:{target}"]))

    async with session_factory() as db:
        candidates = (await db.scalars(pending.order_by(CoreAppEvent.seq))).all()
        if not candidates:
            return []
        history_ids = func.json_each(
            CoreHistoryEntry.message_json, "$.metadata.guidance_ids",
        ).table_valued("value", joins_implicitly=True)
        legacy = set((await db.scalars(select(history_ids.c.value).where(
            CoreHistoryEntry.thread_id == thread_id,
            CoreHistoryEntry.message_json["role"].as_string().in_(("user", "system")),
            history_ids.c.value.in_([record.client_message_id for record in candidates]),
        ).distinct())).all())

    if legacy and event_store is not None and write_coordinator is not None:
        by_turn: dict[str, list[str]] = {}
        for record in candidates:
            if record.client_message_id in legacy:
                by_turn.setdefault(str(record.turn_id or ""), []).append(str(record.client_message_id))
        for legacy_turn, ids in by_turn.items():
            await record_consumed_guidance(
                session_factory,
                thread_id=thread_id,
                turn_id=legacy_turn,
                guidance_ids=ids,
                event_store=event_store,
                write_coordinator=write_coordinator,
            )

    from .queue_state import input_items_text
    recovered = []
    for record in candidates:
        if record.client_message_id not in legacy:
            items = record.payload_json.get("runtime_input") or record.payload_json.get("input") or []
            recovered.append({"id": str(record.client_message_id), "input": items, "content": input_items_text(items)})
    return recovered
