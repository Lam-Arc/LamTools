"""Durable execution records and engine-owned node execution policy.

The journal is append-only and deliberately local-file based.  It records
commands/results rather than attempting to replay arbitrary Python code.  A
snapshot projected from these events is an acceleration structure; the JSONL
journal remains the recovery/audit source of truth.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


AttemptStatus = Literal["started", "completed", "failed", "timed_out", "interrupted"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


@dataclass(frozen=True)
class NodeExecutionPolicy:
    """Normalized Engine policy; legacy node config remains accepted."""

    max_attempts: int = 1
    timeout_seconds: float | None = None
    retry_delays_seconds: tuple[float, ...] = ()

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "NodeExecutionPolicy":
        execution = config.get("execution")
        execution = execution if isinstance(execution, Mapping) else {}
        retry = execution.get("retry")
        retry = retry if isinstance(retry, Mapping) else {}
        raw_retries = retry.get("retries", execution.get("retries", config.get("retries", 0)))
        try:
            retries = max(0, int(raw_retries or 0))
        except (TypeError, ValueError):
            retries = 0

        raw_timeout = execution.get(
            "timeout_seconds",
            execution.get("timeout", config.get("timeout")),
        )
        try:
            timeout = float(raw_timeout) if raw_timeout not in (None, "") else None
        except (TypeError, ValueError):
            timeout = None
        if timeout is not None and timeout <= 0:
            timeout = None

        raw_delays = retry.get(
            "delays_seconds",
            execution.get("retry_delays_seconds", config.get("retry_delays_seconds")),
        )
        delays: list[float] = []
        if isinstance(raw_delays, (list, tuple)):
            for value in raw_delays:
                try:
                    delays.append(max(0.0, float(value)))
                except (TypeError, ValueError):
                    continue
        if not delays:
            raw_backoff = retry.get("backoff_seconds", execution.get("retry_backoff_seconds"))
            try:
                base = max(0.0, float(raw_backoff)) if raw_backoff is not None else 0.1
            except (TypeError, ValueError):
                base = 0.1
            delays = [base * (index + 1) for index in range(retries)]
        return cls(max_attempts=retries + 1, timeout_seconds=timeout, retry_delays_seconds=tuple(delays))

    def delay_after(self, failed_attempt_index: int) -> float:
        if not self.retry_delays_seconds:
            return 0.0
        index = min(max(0, failed_attempt_index), len(self.retry_delays_seconds) - 1)
        return self.retry_delays_seconds[index]


@dataclass
class WorkflowAttempt:
    attempt_id: str
    number: int
    idempotency_key: str
    status: AttemptStatus = "started"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "number": self.number,
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
        }


@dataclass
class WorkflowNodeRun:
    node_id: str
    status: str = "idle"
    attempts: list[WorkflowAttempt] = field(default_factory=list)
    output: Any = None
    error: str = ""
    cache_status: str = ""
    cache_key: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "status": self.status,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "output": _json_copy(self.output),
            "error": self.error,
            "cache_status": self.cache_status,
            "cache_key": self.cache_key,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "audit": _json_copy(self.audit),
        }


@dataclass
class WorkflowRunEvent:
    event_id: str
    run_id: str
    kind: str
    sequence: int = 0
    occurred_at: datetime = field(default_factory=_utcnow)
    workflow_id: str = ""
    workflow_revision: int = 0
    node_id: str = ""
    attempt_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "kind": self.kind,
            "sequence": self.sequence,
            "occurred_at": self.occurred_at.isoformat(),
            "workflow_id": self.workflow_id,
            "workflow_revision": self.workflow_revision,
            "node_id": self.node_id,
            "attempt_id": self.attempt_id,
            "payload": _json_copy(self.payload),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowRunEvent":
        return cls(
            event_id=str(value.get("event_id") or uuid.uuid4().hex),
            run_id=str(value.get("run_id") or ""),
            kind=str(value.get("kind") or ""),
            sequence=max(0, int(value.get("sequence") or 0)),
            occurred_at=_parse_dt(value.get("occurred_at")) or _utcnow(),
            workflow_id=str(value.get("workflow_id") or ""),
            workflow_revision=max(0, int(value.get("workflow_revision") or 0)),
            node_id=str(value.get("node_id") or ""),
            attempt_id=str(value.get("attempt_id") or ""),
            payload=dict(value.get("payload") or {}),
        )


@dataclass
class WorkflowRun:
    run_id: str
    workflow_id: str = ""
    workflow_revision: int = 0
    definition_digest: str = ""
    status: str = "queued"
    nodes: dict[str, WorkflowNodeRun] = field(default_factory=dict)
    last_sequence: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_revision": self.workflow_revision,
            "definition_digest": self.definition_digest,
            "status": self.status,
            "nodes": {key: node.to_dict() for key, node in self.nodes.items()},
            "last_sequence": self.last_sequence,
            "error": self.error,
        }


class WorkflowRunProjector:
    """Pure event projector used for derived snapshots and CLI/RPC output."""

    def apply(self, state: WorkflowRun | None, event: WorkflowRunEvent) -> WorkflowRun:
        if state is None:
            state = WorkflowRun(run_id=event.run_id)
        state.last_sequence = max(state.last_sequence, event.sequence)
        state.workflow_id = event.workflow_id or state.workflow_id
        state.workflow_revision = event.workflow_revision or state.workflow_revision
        if event.kind == "run.started":
            state.status = "running"
            state.definition_digest = str(event.payload.get("definition_digest") or state.definition_digest)
        elif event.kind.startswith("run."):
            state.status = event.kind.split(".", 1)[1]
            state.error = str(event.payload.get("error") or "")
        if event.node_id:
            node = state.nodes.setdefault(event.node_id, WorkflowNodeRun(node_id=event.node_id))
            if event.kind.startswith("node."):
                node.status = event.kind.split(".", 1)[1]
                node.output = event.payload.get("output", node.output)
                node.error = str(event.payload.get("error") or node.error)
                node.cache_status = str(event.payload.get("cache_status") or node.cache_status)
                node.cache_key = str(event.payload.get("cache_key") or node.cache_key)
                node.started_at = _parse_dt(event.payload.get("started_at")) or node.started_at
                node.finished_at = _parse_dt(event.payload.get("finished_at")) or node.finished_at
                audit = event.payload.get("audit")
                if isinstance(audit, Mapping):
                    node.audit = dict(audit)
            elif event.kind.startswith("attempt."):
                attempt = next((item for item in node.attempts if item.attempt_id == event.attempt_id), None)
                if attempt is None:
                    attempt = WorkflowAttempt(
                        attempt_id=event.attempt_id,
                        number=max(1, int(event.payload.get("number") or len(node.attempts) + 1)),
                        idempotency_key=str(event.payload.get("idempotency_key") or ""),
                    )
                    node.attempts.append(attempt)
                attempt.status = event.kind.split(".", 1)[1]  # type: ignore[assignment]
                attempt.started_at = attempt.started_at or event.occurred_at
                if attempt.status != "started":
                    attempt.finished_at = event.occurred_at
                attempt.error = str(event.payload.get("error") or attempt.error)
        return state

    def replay(self, events: list[WorkflowRunEvent]) -> WorkflowRun | None:
        state: WorkflowRun | None = None
        for event in sorted(events, key=lambda item: item.sequence):
            state = self.apply(state, event)
        return state


class WorkflowRunEventStore:
    """Append-only JSONL run journal with idempotent event identifiers."""

    def __init__(self, root: str | Path | None = None, *, data_dir: str | Path | None = None) -> None:
        if root is not None:
            self.directory = Path(root).expanduser().resolve() / ".lam" / "workflow" / "events"
        elif data_dir is not None:
            self.directory = Path(data_dir).expanduser().resolve() / "workflow" / "events"
        else:
            self.directory = Path(".lam/workflow/events").resolve()
        self._locks: dict[str, asyncio.Lock] = {}
        self._append_lock_path = self.directory / ".append-lock.sqlite3"

    def event_path(self, run_id: str) -> Path:
        digest = hashlib.sha256(str(run_id).encode("utf-8", errors="replace")).hexdigest()
        return self.directory / f"{digest}.jsonl"

    def _read_sync(self, run_id: str) -> list[WorkflowRunEvent]:
        path = self.event_path(run_id)
        if not path.is_file():
            return []
        events: list[WorkflowRunEvent] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                raw = json.loads(line)
                if isinstance(raw, Mapping):
                    events.append(WorkflowRunEvent.from_dict(raw))
            except (TypeError, ValueError):
                # A torn final append is ignored; all earlier records remain valid.
                continue
        return events

    async def list(self, run_id: str, *, after_sequence: int = 0) -> list[WorkflowRunEvent]:
        events = await asyncio.to_thread(self._read_sync, run_id)
        return [event for event in events if event.sequence > after_sequence]

    async def append(self, event: WorkflowRunEvent) -> WorkflowRunEvent:
        lock = self._locks.setdefault(event.run_id, asyncio.Lock())
        async with lock:
            # Keep this read outside the cross-process transaction. Besides a
            # cheap idempotency fast path, callers may instrument reads for
            # concurrency tests and must not wait while holding the SQLite lock.
            existing = await asyncio.to_thread(self._read_sync, event.run_id)
            duplicate = next((item for item in existing if item.event_id == event.event_id), None)
            if duplicate is not None:
                return duplicate
            return await asyncio.to_thread(self._append_coordinated_sync, event)

    def _append_coordinated_sync(self, event: WorkflowRunEvent) -> WorkflowRunEvent:
        """Allocate and append while a SQLite write transaction fences writers."""
        self.directory.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._append_lock_path, timeout=15.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=15000")
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._read_sync(event.run_id)
            duplicate = next((item for item in existing if item.event_id == event.event_id), None)
            if duplicate is not None:
                connection.commit()
                return duplicate
            event.sequence = max((item.sequence for item in existing), default=0) + 1
            path = self.event_path(event.run_id)
            line = json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
            self._append_sync(path, line)
            connection.commit()
            return event
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _append_sync(path: Path, line: str) -> None:
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    async def project(self, run_id: str) -> WorkflowRun | None:
        return WorkflowRunProjector().replay(await self.list(run_id))


def definition_digest(definition: Mapping[str, Any]) -> str:
    canonical = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def attempt_identity(run_id: str, node_id: str, number: int) -> tuple[str, str]:
    seed = f"{run_id}\x00{node_id}\x00{number}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return (f"attempt_{digest[:20]}", f"workflow:{digest}")


__all__ = [
    "NodeExecutionPolicy",
    "WorkflowAttempt",
    "WorkflowNodeRun",
    "WorkflowRun",
    "WorkflowRunEvent",
    "WorkflowRunEventStore",
    "WorkflowRunProjector",
    "attempt_identity",
    "definition_digest",
]
