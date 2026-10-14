"""Recover accepted steering from existing events/history, without executing a turn."""
from __future__ import annotations

from typing import Any
from sqlalchemy import select
from .core_db import CoreAppEvent, CoreHistoryEntry


async def pending_steering(session_factory: Any, thread_id: str) -> list[dict[str, Any]]:
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
    consumed = {str(guidance_id) for value in metadata if isinstance(value, dict)
                for guidance_id in value.get("guidance_ids", [])}
    from .live_operations import input_items_text
    return [{"id": str(event.client_message_id), "content": input_items_text(event.payload_json.get("runtime_input") or event.payload_json.get("input") or [])}
            for event in accepted if event.client_message_id and str(event.client_message_id) not in consumed]
