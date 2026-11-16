"""Recover accepted steering from existing events/history, without executing a turn."""
from __future__ import annotations

import hashlib
from typing import Any
from sqlalchemy import select
from .core_db import CoreAppEvent, CoreHistoryEntry
from .event_store import AppEventInput

# user:“将回合暂停并输入引导信息并发送的时候，有可能会将大量已经成功发送并被处理过的用户信息再次发送”+(引导是否已被内核消费必须是持久事件事实；历史消息会在暂停时被压缩视图整体回写，不能再拿它当消费凭据)。
GUIDANCE_CONSUMED_METHOD = "guidance/consumed"


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
    event_store: Any | None = None,
    write_coordinator: Any | None = None,
) -> list[dict[str, Any]]:
    async with session_factory() as db:
        accepted = (await db.execute(select(CoreAppEvent).where(
            CoreAppEvent.thread_id == thread_id, CoreAppEvent.method == "turn/steered",
            CoreAppEvent.payload_json["guidance_id"].as_string().is_not(None),
        ).order_by(CoreAppEvent.seq))).scalars().all()
        if not accepted:
            return []
        metadata = (await db.execute(select(CoreHistoryEntry.message_json["metadata"]).where(
            CoreHistoryEntry.thread_id == thread_id,
            CoreHistoryEntry.message_json["role"].as_string().in_(["user", "system"]),
        ))).scalars().all()
        consumed_events = (await db.execute(select(CoreAppEvent).where(
            CoreAppEvent.thread_id == thread_id,
            CoreAppEvent.method == GUIDANCE_CONSUMED_METHOD,
        ))).scalars().all()
    consumed = {
        str(guidance_id)
        for event in consumed_events
        for guidance_id in (event.payload_json or {}).get("guidance_ids") or []
    }
    history_consumed = {str(guidance_id) for value in metadata if isinstance(value, dict)
                        for guidance_id in value.get("guidance_ids", [])}
    # Older builds only recorded consumption in history rows. Backfill those
    # receipts before the caller can replace history with its compacted view.
    legacy = history_consumed - consumed
    if legacy and event_store is not None and write_coordinator is not None:
        turns_by_guidance = {
            str(event.client_message_id): str(event.turn_id or "")
            for event in accepted
            if event.client_message_id
        }
        turns = {turns_by_guidance.get(guidance_id, "") for guidance_id in legacy}
        for turn_id in turns:
            await record_consumed_guidance(
                session_factory,
                thread_id=thread_id,
                turn_id=turn_id,
                guidance_ids=sorted(
                    guidance_id for guidance_id in legacy
                    if turns_by_guidance.get(guidance_id, "") == turn_id
                ),
                event_store=event_store,
                write_coordinator=write_coordinator,
            )
        consumed |= legacy
    consumed |= history_consumed
    from .live_operations import input_items_text
    # user:“把它作为一个引导信息发进去”+(恢复时保留原始输入中的附件引用)。
    return [{"id": str(event.client_message_id),
             "input": event.payload_json.get("runtime_input") or event.payload_json.get("input") or [],
             "content": input_items_text(event.payload_json.get("runtime_input") or event.payload_json.get("input") or [])}
            for event in accepted
            if event.client_message_id and str(event.client_message_id) not in consumed]
