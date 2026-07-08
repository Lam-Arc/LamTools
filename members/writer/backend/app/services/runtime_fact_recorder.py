from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import gen_uuid
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptTurn
from app.services.app_projection_sink import AppProjectionSink
from app.services.runtime_transcript_sink import RuntimeTranscriptSink
from app.services.transcript_service import ensure_active_producer
from lamtools_core.event import CoreEvent, RunItemEvent
from lamtools_core.event.runtime_projection import (
    DEFAULT_RUNTIME_PREVIEW_CHARS,
    RuntimeProjectionBuffer,
    RuntimeProjectionInput,
    runtime_group_from_event_name,
    runtime_payload_preview,
    runtime_projection_to_run_item_events,
    runtime_summary_from_event_name,
)

RUNTIME_VISIBLE_TEXT_CHARS = DEFAULT_RUNTIME_PREVIEW_CHARS
RUNTIME_SUMMARY_CHARS = RUNTIME_VISIBLE_TEXT_CHARS
MAX_CONTEXT_SUMMARY_CHARS = 20_000


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _merge_unique(existing: list[str], incoming: list[str]) -> list[str]:
    merged = list(existing)
    seen = set(merged)
    for item in incoming:
        if item not in seen:
            merged.append(item)
            seen.add(item)
    return merged


class RuntimeFactRecorder:
    def __init__(
        self,
        *,
        db: AsyncSession,
        session_id: str,
        turn: WriterTranscriptTurn,
        app_projection_sink: AppProjectionSink,
        model_context: dict[str, Any] | None = None,
    ) -> None:
        self._db = db
        self._session_id = session_id
        self._turn = turn
        self._app_projection_sink = app_projection_sink
        self._lock = asyncio.Lock()
        self._projection_buffer = RuntimeProjectionBuffer()
        self._sequence = 0
        self._seen_terminal_core_event = False
        self.transcript_sink = RuntimeTranscriptSink(db=db, turn=turn, model_context=model_context)

    @property
    def sequence(self) -> int:
        return self._sequence

    @property
    def seen_terminal_core_event(self) -> bool:
        return self._seen_terminal_core_event

    @seen_terminal_core_event.setter
    def seen_terminal_core_event(self, value: bool) -> None:
        self._seen_terminal_core_event = value

    async def start_runtime_producer(self) -> None:
        await ensure_active_producer(
            self._db,
            turn=self._turn,
            producer_id=f"{self._turn.id}:runtime",
            kind="runtime",
        )
        await self._db.commit()

    async def record_core_event(self, event: CoreEvent) -> None:
        payload = event.payload or {}
        event_name = event.name
        if event_name in {"runtime.done", "runtime.failed", "runtime.waiting"}:
            self._seen_terminal_core_event = True
        if event_name == "runtime.context_compacted":
            await self._persist_context_compaction(payload)
        await self.record(
            group=runtime_group_from_event_name(event_name),
            source="core",
            phase=event_name,
            status=str(payload.get("status") or ""),
            summary=runtime_summary_from_event_name(event_name, payload),
            preview=str(payload.get("content") or payload.get("summary") or payload.get("message") or "")[
                :RUNTIME_VISIBLE_TEXT_CHARS
            ],
            metadata={
                "event_id": event.event_id,
                "run_id": event.run_id,
                "sequence": event.sequence,
                "payload": {
                    **runtime_payload_preview(payload),
                    "run_id": event.run_id,
                },
            },
        )

    async def _persist_context_compaction(self, payload: dict[str, Any]) -> None:
        summary = str(payload.get("summary") or payload.get("content") or "").strip()
        if not summary:
            return
        session = await self._db.get(WriterSession, self._session_id)
        if session is None:
            return

        existing_state = session.runtime_state if isinstance(session.runtime_state, dict) else {}
        existing_compaction = (
            existing_state.get("manual_compaction")
            if isinstance(existing_state.get("manual_compaction"), dict)
            else {}
        )
        compacted_ids = _string_list(payload.get("compacted_message_ids"))
        retained_ids = _string_list(payload.get("retained_message_ids"))
        existing_compacted_ids = _string_list(existing_compaction.get("compacted_message_ids"))
        manual_compaction = {
            **existing_compaction,
            "compacted_at": datetime.now(timezone.utc).isoformat(),
            "trigger": str(payload.get("trigger") or "auto"),
            "compacted_message_ids": _merge_unique(existing_compacted_ids, compacted_ids),
            "retained_message_ids": retained_ids,
            "retained_message_count": len(retained_ids),
        }
        for key in ("before_tokens", "after_tokens", "target_tokens", "trigger_tokens", "window_tokens"):
            if key in payload:
                manual_compaction[key] = payload.get(key)

        session.context_summary = summary[:MAX_CONTEXT_SUMMARY_CHARS]
        session.runtime_state = {**existing_state, "manual_compaction": manual_compaction}

    async def record(
        self,
        *,
        group: str,
        source: str,
        phase: str | None = None,
        status: str | None = None,
        summary: str = "",
        preview: str = "",
        full_text: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        metadata = dict(metadata or {})
        metadata.setdefault("turn_id", self._turn.id)
        payload_for_turn = metadata.get("payload")
        if isinstance(payload_for_turn, dict):
            payload_for_turn.setdefault("turn_id", self._turn.id)

        async with self._lock:
            sequence = self._next_sequence(metadata.get("sequence"))
            if phase == "runtime.reply_delta":
                await self.transcript_sink.sync_fact(
                    phase=phase,
                    status=status,
                    summary=summary,
                    preview=preview,
                    full_text=full_text,
                    sequence=sequence,
                    metadata=metadata,
                )
                bridge_event = self._projection_fact(
                    fact_id=f"{self._session_id}:runtime:{sequence}:reply_delta",
                    group=group,
                    source=source,
                    phase=phase,
                    status=status,
                    sequence=sequence,
                    summary=summary,
                    preview=preview,
                    full_text=full_text,
                    metadata=metadata,
                )
                await self._db.commit()
                await self._publish_run_item_projection(bridge_event)
                return

            event = self._projection_fact(
                fact_id=gen_uuid(),
                group=group,
                source=source,
                phase=phase,
                status=status,
                sequence=sequence,
                summary=summary,
                preview=preview,
                full_text=full_text,
                metadata=metadata,
            )
            projection_fact = self._projection_buffer.merge_part_growth(event)
            await self.transcript_sink.sync_fact(
                phase=phase,
                status=status,
                summary=summary,
                preview=preview,
                full_text=full_text,
                sequence=sequence,
                metadata=metadata,
            )
            await self._db.commit()
            await self._publish_run_item_projection(projection_fact)

    def _next_sequence(self, raw_sequence: Any) -> int:
        sequence: int | None = None
        if isinstance(raw_sequence, int):
            sequence = raw_sequence
        elif isinstance(raw_sequence, str) and raw_sequence.isdigit():
            sequence = int(raw_sequence)
        if sequence is None:
            self._sequence += 1
            return self._sequence
        self._sequence = max(self._sequence, sequence)
        return sequence

    def _projection_fact(
        self,
        *,
        fact_id: str,
        group: str,
        source: str,
        phase: str | None,
        status: str | None,
        sequence: int,
        summary: str,
        preview: str,
        full_text: str,
        metadata: dict[str, Any],
    ) -> RuntimeProjectionInput:
        return RuntimeProjectionInput(
            id=fact_id,
            thread_id=self._session_id,
            group=group,
            source=source,
            phase=phase,
            status=status,
            sequence=sequence,
            summary=summary[:RUNTIME_SUMMARY_CHARS],
            preview=preview[:RUNTIME_VISIBLE_TEXT_CHARS],
            full_text=full_text[:RUNTIME_VISIBLE_TEXT_CHARS],
            metadata=metadata or None,
            created_at=datetime.now(timezone.utc),
        )

    async def _publish_run_item_projection(self, fact: RuntimeProjectionInput) -> None:
        await self._publish_run_items(
            runtime_projection_to_run_item_events(fact),
            source_event_id=fact.id,
        )

    async def _publish_run_items(self, events: list[RunItemEvent], *, source_event_id: str) -> None:
        await self._app_projection_sink.publish(
            events,
            session_id=self._session_id,
            source_event_id=source_event_id,
        )
