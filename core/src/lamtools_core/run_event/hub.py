from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Callable
from uuid import uuid4

from . import InMemoryRuntimeEventStore, RuntimeEventRecord, RuntimeEventStore

_logger = logging.getLogger(__name__)


class RuntimeEventHub:
    """In-memory runtime event log plus SSE subscriber fan-out."""

    #: A subscriber that goes quiet for this long is dropped as stale.
    QUEUE_STALE_SECONDS = 300.0

    def __init__(
        self,
        *,
        max_events: int = 2000,
        max_queue_size: int = 256,
        event_store: RuntimeEventStore | None = None,
    ) -> None:
        self._max_events = max_events
        self._event_store = event_store or InMemoryRuntimeEventStore()
        self._queue_registry: dict[str, tuple[asyncio.Queue, str | None, float]] = {}
        self._session_queues: dict[str, list[str]] = {}
        self._queue_counter = 0
        self._max_queue_size = max_queue_size
        # Queue ids that already logged a drop warning; used to warn once per
        # stuck subscriber instead of once per dropped event (audit 07 S4).
        self._drop_warned: set[str] = set()

    @property
    def queue_count(self) -> int:
        return len(self._queue_registry)

    def serialize_sse(self, record: RuntimeEventRecord) -> str:
        data = json.dumps(self.runtime_event_payload(record), ensure_ascii=False, default=str)
        return f"id: {record.id}\ndata: {data}\n\n"

    def runtime_event_payload(self, record: RuntimeEventRecord) -> dict[str, Any]:
        payload = self._public_payload(record)
        timestamp_ms = int(record.created_at.timestamp() * 1000)
        return {
            "id": record.id,
            "session_id": record.session_id,
            "name": record.name,
            "type": record.name,
            "category": record.category,
            "run_id": record.run_id,
            "timestamp": timestamp_ms,
            "created_at": record.created_at.isoformat(),
            "data": payload,
        }

    def publish_runtime_record(
        self,
        *,
        name: str,
        session_id: str,
        run_id: str = "",
        data: dict[str, Any] | None = None,
    ) -> tuple[str, int]:
        self._sweep_stale_queues()
        record = self._append_runtime_record(
            name=name,
            session_id=session_id,
            run_id=run_id,
            data=data or {},
        )
        sse_line = self.serialize_sse(record)
        is_checkpoint = name == "checkpoint_required"
        if session_id:
            self._put_to_session_queues(session_id, sse_line)

        delivered = self._put_to_matching_queues(
            sse_line,
            include=lambda _qid, q_sid: (q_sid is None or is_checkpoint) and q_sid != session_id,
        )
        return record.id, delivered

    def list_events(self, *, session_id: str | None = None) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for event in self._event_store.list(session_id=session_id)[-self._max_events :]:
            records.append(self.runtime_event_payload(event))
        return records

    async def subscribe(
        self,
        *,
        session_id: str | None = None,
        last_event_id: str | None = None,
        tail: int | None = None,
        replay_skip_types: set[str] | None = None,
    ) -> tuple[str, asyncio.Queue, bool]:
        """Register a subscriber queue.

        Returns ``(queue_id, queue, replay_gap)``. ``replay_gap`` is True
        when ``last_event_id`` was requested but is no longer in the store
        (trimmed or never existed) — the caller should treat the replay as
        incomplete and re-fetch the full state instead of silently missing
        events (audit 11).
        """
        self._queue_counter += 1
        queue_id = f"q_{self._queue_counter}"
        queue = asyncio.Queue(maxsize=self._max_queue_size)
        self._queue_registry[queue_id] = (queue, session_id, self._now())
        if session_id:
            self._session_queues.setdefault(session_id, []).append(queue_id)

        replay_gap = False
        if last_event_id:
            known_ids = {record.id for record in self._event_store.list(session_id=session_id)}
            replay_gap = last_event_id not in known_ids

        replay_tail = (0 if last_event_id else 50) if tail is None else tail
        skip_types = replay_skip_types or set()
        for record in self._replay_records(session_id=session_id, last_event_id=last_event_id, tail=replay_tail):
            if record.name in skip_types:
                continue
            self._try_put(queue_id, queue, self.serialize_sse(record))
        return queue_id, queue, replay_gap

    def unsubscribe(self, queue_id: str) -> None:
        q_info = self._queue_registry.pop(queue_id, None)
        if not q_info or not q_info[1]:
            return
        session_id = q_info[1]
        if session_id not in self._session_queues:
            return
        self._session_queues[session_id] = [qid for qid in self._session_queues[session_id] if qid != queue_id]
        if not self._session_queues[session_id]:
            del self._session_queues[session_id]

    def _put_to_session_queues(self, session_id: str, sse_line: str) -> int:
        delivered = 0
        for queue_id in self._session_queues.get(session_id, []):
            q_info = self._queue_registry.get(queue_id)
            if q_info and self._try_put(queue_id, q_info[0], sse_line):
                delivered += 1
        return delivered

    def _put_to_matching_queues(self, sse_line: str, *, include: Callable[[str, str | None], bool]) -> int:
        delivered = 0
        for queue_id, (queue, q_session_id, _ts) in self._queue_registry.items():
            if not include(queue_id, q_session_id):
                continue
            if self._try_put(queue_id, queue, sse_line):
                delivered += 1
        return delivered

    def _try_put(self, queue_id: str, queue: asyncio.Queue, sse_line: str) -> bool:
        try:
            queue.put_nowait(sse_line)
        except asyncio.QueueFull:
            # A slow consumer losing events silently is worse than a noisy
            # log: its cursor drifts and the gap is only detected via replay
            # much later (audit 07 S4). Warn once until the queue drains so a
            # single stuck subscriber does not spam per-event.
            if queue_id not in self._drop_warned:
                self._drop_warned.add(queue_id)
                _logger.warning(
                    "[run_event:hub] subscriber %s full (maxsize=%d) — dropping events; "
                    "client should re-sync via last_event_id replay",
                    queue_id,
                    queue.maxsize,
                )
            return False
        self._drop_warned.discard(queue_id)
        # Any successful delivery counts as liveness for the stale sweep.
        info = self._queue_registry.get(queue_id)
        if info is not None:
            self._queue_registry[queue_id] = (info[0], info[1], self._now())
        return True

    def _sweep_stale_queues(self) -> None:
        """Drop subscribers that have gone quiet past the staleness TTL.

        Subscribers that disconnect without calling ``unsubscribe`` otherwise
        leak their queue forever and keep consuming fan-out work (audit 11).
        """
        cutoff = self._now() - self.QUEUE_STALE_SECONDS
        stale = [qid for qid, (_q, _sid, ts) in self._queue_registry.items() if ts < cutoff]
        for queue_id in stale:
            self.unsubscribe(queue_id)

    @staticmethod
    def _now() -> float:
        import time

        return time.monotonic()

    def _append_runtime_record(
        self,
        *,
        name: str,
        session_id: str,
        run_id: str = "",
        data: dict[str, Any] | None = None,
        event_id: str | None = None,
        created_at: datetime | None = None,
    ) -> RuntimeEventRecord:
        payload = dict(data or {})
        record = RuntimeEventRecord(
            id=event_id or uuid4().hex[:16],
            session_id=session_id,
            name=name,
            category="runtime",
            payload=payload,
            run_id=run_id,
            created_at=created_at or datetime.now(),
        )
        self._event_store.append(record)
        self._trim_events()
        return record

    def _replay_records(
        self,
        *,
        session_id: str | None,
        last_event_id: str | None,
        tail: int,
    ) -> list[RuntimeEventRecord]:
        records = self._event_store.list(session_id=session_id)
        if last_event_id:
            for index, record in enumerate(records):
                if record.id == last_event_id:
                    return records[index + 1 :]
            return []
        if tail > 0:
            return records[-tail:]
        return records

    def _trim_events(self) -> None:
        records = self._event_store.list()
        if len(records) <= self._max_events:
            return
        keep_ids = {record.id for record in records[-self._max_events :]}
        self._event_store.clear()
        for record in records:
            if record.id in keep_ids:
                self._event_store.append(record)

    @staticmethod
    def _public_payload(record: RuntimeEventRecord) -> dict[str, Any]:
        return {key: value for key, value in record.payload.items() if not key.startswith("_")}


__all__ = ["RuntimeEventHub"]
