"""Durable live events, operation results and snapshot read boundaries."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
from typing import Any
from lamtools_core.event import RunItemEvent
from sqlalchemy.ext.asyncio import AsyncSession
from ..event_store import AppEventEnvelope, AppEventInput
from ..turn_acceptance import CoreAppEventSpec
from .context import CoreLiveContext


async def _append_app_event(
    db: AsyncSession,
    *,
    context: CoreLiveContext,
    event: AppEventInput,
) -> AppEventEnvelope:
    return await context.persistence.append(db, event)


def _app_event_input(spec: CoreAppEventSpec) -> AppEventInput:
    return AppEventInput(
        event_id=spec.event_id,
        thread_id=spec.thread_id,
        method=spec.method,
        payload=spec.payload,
        turn_id=spec.turn_id,
        item_id=spec.item_id,
        parent_item_id=spec.parent_item_id,
        client_message_id=spec.client_message_id,
    )


async def _append_run_item(
    db: AsyncSession,
    *,
    context: CoreLiveContext,
    event: RunItemEvent,
) -> AppEventEnvelope:
    return await context.persistence.append_run_item(db, event)


def _get_running_loop() -> asyncio.AbstractEventLoop:
    return asyncio.get_running_loop()


async def _persist_operation_result(
    *,
    context: CoreLiveContext,
    thread_id: str,
    turn_id: str,
    result: Any,
) -> None:
    payload = dict(getattr(result, "payload", {}) or {})
    if payload.get("events_persisted_live") is True:
        return
    raw_items = payload.get("run_items")
    if not isinstance(raw_items, list):
        return
    async def write(db: AsyncSession) -> list[AppEventEnvelope]:
        run_item_list: list[RunItemEvent] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            item = RunItemEvent.from_dict({**raw, "thread_id": raw.get("thread_id") or thread_id, "turn_id": raw.get("turn_id") or turn_id})
            run_item_list.append(item)
        if not run_item_list:
            return []
        return await context.persistence.append_batch(db, run_item_events=run_item_list)

    events = await context.persistence.write(write)
    for event in events:
        await context.hub.publish(event)
