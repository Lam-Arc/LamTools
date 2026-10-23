"""Reconcile the durable member registry with runtime and parent projections.

This performs no agent execution. Registry transitions and Core projection writes
are idempotent, so a crash between the two databases is repaired on the next pass.
"""
from __future__ import annotations

import sqlite3
import time
from collections import Counter
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

from lamtools_core.runtime_owner import owner_is_live, read_owner
from lamtools_core.sub_agent_supervisor import SubAgentSupervisor, find_sub_agent_supervisor
from .base_agent import core_events_to_run_items
from .core_db import CoreAppEvent, CoreHistoryEntry


class _ProjectionSink:
    def __init__(self, context: Any) -> None:
        self.context = context

    async def emit(self, event: Any) -> None:
        context = self.context
        items = core_events_to_run_items([event], thread_id=event.session_id)
        async def write(db):
            missing = [item for item in items if await db.get(CoreAppEvent, item.event_id) is None]
            return await context.persistence.append_batch(db, run_item_events=missing)
        envelopes = await context.persistence.write(write)
        if context.hub is not None:
            for envelope in envelopes:
                await context.hub.publish(envelope)


async def reconcile_sub_agent_state(*, context: Any, data_dir: Path | str,
                                    acknowledge_legacy_mail: bool = False) -> int:
    database = Path(data_dir) / "sub_agents.sqlite3"
    if not database.is_file() or context.runtime_state_store is None:
        return 0
    with closing(sqlite3.connect(database)) as db:
        parents = [row[0] for row in db.execute("SELECT DISTINCT parent_thread_id FROM sub_agents")]
    repaired = 0
    for parent in parents:
        # user:“修 问题严重的话 就重新设计”+(对账复用真实所有者；冷启动的投影对象不取得执行权)。
        supervisor = find_sub_agent_supervisor(parent, data_dir=database.parent) or SubAgentSupervisor(
            parent_thread_id=parent,
            database_path=database,
            runner=SimpleNamespace(state_store=context.runtime_state_store,
                                   parent_event_sink=_ProjectionSink(context)),
            agent_run_store=getattr(context, "turn_store", None),
        )
        await supervisor.recover()
        try:
            await supervisor.sync_agent_runs()
        except BaseException:
            # The projection is a read model; never let it block registry
            # repair or member finalization below.
            pass
        for payload in await supervisor.list():
            record = supervisor._required(payload["name"])
            if record.status == "running":
                if record.lease_until and time.time() > record.lease_until:
                    expired = await supervisor.expire_lease(record.name)
                    if expired is not None:
                        repaired += 1
                        continue
                # recover deliberately leaves live cross-process owners alone.
                continue
            state = await context.runtime_state_store.get(record.sub_session_id) if record.sub_session_id else None
            if (record.status in {"interrupted", "closed"} and state is not None
                    and state.status in {"running", "waiting"}
                    and not owner_is_live(read_owner(state.metadata))):
                from .live_operations import _save_runtime_state_with_retry, _close_active_turns
                def settle(current):
                    if (current.run_id != state.run_id
                            or owner_is_live(read_owner(current.metadata))):
                        return
                    current.status = "cancelled"
                    current.loop_state = "failed"
                    current.metadata.pop("pending_approval", None)
                    current.metadata.pop("pending_waiting_request", None)
                    current.metadata["failure_code"] = "sub_agent_process_interrupted"
                    current.metadata["failure_message"] = "Sub-agent execution was interrupted when its owning process stopped."
                await _save_runtime_state_with_retry(context.runtime_state_store, record.sub_session_id, mutate=settle)
                async def close(db):
                    latest = await context.runtime_state_store.get(record.sub_session_id)
                    if latest is None or latest.run_id != state.run_id or latest.status != "cancelled":
                        return []
                    expected_turns = {state.run_id, str(state.metadata.get("turn_id") or ""),
                                      f"{record.sub_session_id}:turn:{state.run_id}"}
                    return await _close_active_turns(
                        context=context, db=db, thread_id=record.sub_session_id,
                        verdict_for=lambda turn, _snapshot: (
                            "cancelled", "sub_agent_process_interrupted",
                            "Sub-agent execution was interrupted when its owning process stopped.",
                        ) if turn in expected_turns else None,
                    )
                envelopes = await context.persistence.write(close)
                if context.hub is not None:
                    for _, envelope in envelopes:
                        await context.hub.publish(envelope)
                repaired += 1
            if record.status == "paused":
                # A paused record means the member was waiting at a human
                # boundary.  If its runtime state is already cancelled/failed,
                # the continuation ended without syncing the registry.
                state = (
                    await context.runtime_state_store.get(record.sub_session_id)
                    if record.sub_session_id
                    else None
                )
                if state is not None and state.status in {"cancelled", "failed"}:
                    await supervisor.finalize_terminal(
                        record.name,
                        status="failed" if state.status == "failed" else "interrupted",
                        summary=str(state.metadata.get("failure_message") or "Sub-agent continuation ended."),
                    )
                    repaired += 1
            if acknowledge_legacy_mail and record.sub_session_id:
                await _acknowledge_legacy_mail(context, supervisor, record)
            # Include already-interrupted records: old lazy recovery may have
            # written only the registry, with no sink bound to publish a status.
            event = "member_finished" if record.status == "idle" else f"member_{record.status}"
            if record.completed_at is not None:
                # A process can stop after the registry commit but before its
                # outbox insert. Reconstruct the same idempotent lifecycle fact.
                supervisor._write_member_event(record, event)
            await supervisor._publish_member_status(record, event=event)
    return repaired


async def _acknowledge_legacy_mail(context: Any, supervisor: SubAgentSupervisor, record: Any) -> None:
    """Backfill old NULL receipts only when an exact user-history row proves delivery.

    New messages carry IDs and are acknowledged by the kernel checkpoint. Count
    occurrences so repeated identical prompts are not all claimed by one row.
    """
    pending = supervisor.pending_guidance(record.name)
    if not pending:
        return
    async with context.session_factory() as db:
        rows = (await db.execute(select(CoreHistoryEntry.message_json).where(
            CoreHistoryEntry.thread_id == record.sub_session_id,
            CoreHistoryEntry.message_json["role"].as_string() == "user",
        ).order_by(CoreHistoryEntry.seq))).scalars().all()
    evidence = Counter(
        row["content"] for row in rows
        if isinstance(row, dict) and isinstance(row.get("content"), str)
        and not row.get("metadata", {}).get("guidance_ids")
    )
    with supervisor._connection() as db:
        delivered = db.execute(
            "SELECT body FROM sub_agent_mailbox WHERE parent_thread_id=? AND name=? "
            "AND direction='parent_to_child' AND delivered_at IS NOT NULL",
            (record.parent_thread_id, record.name),
        ).fetchall()
    for row in delivered:
        evidence[row["body"]] -= 1
    ids = []
    for row in pending:
        if evidence[row["body"]] > 0:
            evidence[row["body"]] -= 1
            ids.append(row["id"])
    supervisor.acknowledge_guidance(record.name, ids)
