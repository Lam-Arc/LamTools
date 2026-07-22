from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from lamtools_core.event import RunItemEvent

from .persistence import append_run_item_event_and_apply_snapshot
from .protocol import WriterAppEventEnvelope
from .runtime_side_effects import persist_run_item_side_effects


async def persist_run_item_events_as_app_events(
    db: AsyncSession,
    events: list[RunItemEvent],
) -> list[WriterAppEventEnvelope]:
    envelopes: list[WriterAppEventEnvelope] = []
    for run_item_event in events:
        await persist_run_item_side_effects(db, run_item_event)
        envelope = await append_run_item_event_and_apply_snapshot(db, run_item_event)
        envelopes.append(envelope)
    return envelopes
