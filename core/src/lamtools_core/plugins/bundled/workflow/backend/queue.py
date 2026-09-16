"""Durable workflow run queue and history service."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import tempfile
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from lamtools_core.event.run_item import RunItemEvent

from .runtime import (
    WorkflowDef,
    WorkflowExecutionContext,
    WorkflowNodeState,
    WorkflowRunResult,
    public_workflow_value,
)


QueueStatus = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "paused",
]
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
QUEUE_STORE_VERSION = 3


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return value


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_nonnegative_int(value: Any, *, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _as_priority(value: Any, *, default: int = 0, strict: bool = False) -> int:
    """Read the queue priority while keeping legacy records loadable."""

    if isinstance(value, bool):
        if strict:
            raise ValueError("queue priority must be an integer")
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    # Old JSON writers occasionally serialised scalar numbers as strings.
    # Accept those on migration, while new enqueue calls remain strict.
    if not strict and isinstance(value, str):
        try:
            return int(value.strip())
        except (TypeError, ValueError):
            return default
    if strict:
        raise ValueError("queue priority must be an integer")
    return default


@dataclass
class WorkflowQueueItem:
    """A queue entry, including its terminal result for durable history."""

    queue_id: str
    workflow_id: str = ""
    # Immutable execution identity captured when the run is accepted.  Old
    # queue files omit these fields and are pinned once, before their first
    # post-migration execution.
    workflow_revision: int = 0
    workflow_definition: dict[str, Any] = field(default_factory=dict)
    workflow_name: str = ""
    work_root: str = ""
    thread_id: str = ""
    run_id: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    status: QueueStatus = "queued"
    # Higher priority is claimed first; created_at remains the stable tie
    # breaker so the default (zero) queue is still FIFO.
    priority: int = 0
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    max_steps: int | None = None
    start_node: str | None = None
    single_node: str | None = None
    prior_values: dict[str, Any] = field(default_factory=dict)
    prior_node_states: dict[str, WorkflowNodeState] = field(default_factory=dict)
    result: WorkflowRunResult | None = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.queue_id

    @property
    def name(self) -> str:
        return self.workflow_name

    def to_dict(self) -> dict[str, Any]:
        """Return the secret-safe public queue/RPC projection."""
        return public_workflow_value(self.to_storage_dict())

    def to_storage_dict(self) -> dict[str, Any]:
        """Return the complete durable record used only by the queue store."""
        return {
            "queue_id": self.queue_id,
            "id": self.queue_id,
            "workflow_id": self.workflow_id,
            "workflow_revision": self.workflow_revision,
            "workflow_definition": _json_copy(self.workflow_definition),
            "workflow_name": self.workflow_name,
            "name": self.workflow_name,
            "work_root": self.work_root,
            "thread_id": self.thread_id,
            "run_id": self.run_id,
            "inputs": _json_copy(self.inputs),
            "status": self.status,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "max_steps": self.max_steps,
            "start_node": self.start_node,
            "single_node": self.single_node,
            "prior_values": _json_copy(self.prior_values),
            "prior_node_states": {key: value.to_dict() for key, value in self.prior_node_states.items()},
            "result": self.result.to_dict() if self.result is not None else None,
            "error": self.error,
            "metadata": _json_copy(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowQueueItem":
        raw_states = value.get("prior_node_states") or value.get("priorNodeStates") or {}
        states = {
            str(key): raw if isinstance(raw, WorkflowNodeState) else WorkflowNodeState.from_dict(raw or {}, node_id=str(key))
            for key, raw in raw_states.items()
            if isinstance(raw, (Mapping, WorkflowNodeState))
        } if isinstance(raw_states, Mapping) else {}
        raw_result = value.get("result")
        result = WorkflowRunResult.from_dict(raw_result) if isinstance(raw_result, Mapping) else None
        raw_status = str(value.get("status") or "queued")
        if raw_status not in {"queued", "running", "completed", "failed", "cancelled", "paused"}:
            raw_status = "queued"
        raw_max_steps = value.get("max_steps", value.get("maxSteps"))
        try:
            max_steps = int(raw_max_steps) if raw_max_steps not in (None, "") else None
        except (TypeError, ValueError):
            max_steps = None
        return cls(
            queue_id=str(value.get("queue_id") or value.get("id") or _new_id("wfq")),
            workflow_id=str(value.get("workflow_id") or value.get("workflowId") or ""),
            workflow_revision=_as_nonnegative_int(value.get("workflow_revision") or value.get("workflowRevision")),
            workflow_definition=dict(value.get("workflow_definition") or value.get("workflowDefinition") or {}),
            workflow_name=str(value.get("workflow_name") or value.get("workflowName") or value.get("name") or ""),
            work_root=str(value.get("work_root") or value.get("workRoot") or ""),
            thread_id=str(value.get("thread_id") or value.get("threadId") or ""),
            run_id=str(value.get("run_id") or value.get("runId") or ""),
            inputs=dict(value.get("inputs") or {}),
            status=raw_status,  # type: ignore[arg-type]
            priority=_as_priority(value.get("priority", value.get("queue_priority", 0))),
            created_at=_parse_dt(value.get("created_at")) or _utcnow(),
            updated_at=_parse_dt(value.get("updated_at")) or _utcnow(),
            started_at=_parse_dt(value.get("started_at")),
            finished_at=_parse_dt(value.get("finished_at")),
            max_steps=max_steps,
            start_node=str(value.get("start_node") or value.get("startNode") or "") or None,
            single_node=str(value.get("single_node") or value.get("singleNode") or "") or None,
            prior_values=dict(value.get("prior_values") or value.get("priorValues") or {}),
            prior_node_states=states,
            result=result,
            error=str(value.get("error") or ""),
            metadata=dict(value.get("metadata") or {}),
        )


class WorkflowQueueStore:
    """Atomic JSON persistence for queue entries and their history."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        path: str | Path | None = None,
        store_path: str | Path | None = None,
        data_dir: str | Path | None = None,
    ) -> None:
        path = path or store_path
        if path is not None:
            candidate = Path(path).expanduser().resolve()
            self.path = candidate if candidate.suffix.lower() == ".json" else candidate / "queue.json"
        elif root is not None:
            self.path = Path(root).expanduser().resolve() / ".lam" / "workflow" / "queue.json"
        elif data_dir is not None:
            self.path = Path(data_dir).expanduser().resolve() / "workflow" / "queue.json"
        else:
            self.path = Path(".lam/workflow/queue.json").resolve()
        self._items: dict[str, WorkflowQueueItem] = {}
        self._loaded = False
        self._lock = asyncio.Lock()

    def _load_sync(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            values = raw.get("items", raw) if isinstance(raw, Mapping) else []
            if isinstance(values, list):
                self._items = {
                    item.queue_id: item
                    for value in values
                    if isinstance(value, Mapping)
                    for item in [WorkflowQueueItem.from_dict(value)]
                }
                # Priority was added after the original queue wire shape.
                # Rewrite the same file atomically on first load so a process
                # restart cannot lose the migrated default.  No legacy file
                # is deleted or moved, and a failed rewrite still leaves the
                # in-memory compatibility projection usable.
                try:
                    raw_version = int(raw.get("version", 0) or 0) if isinstance(raw, Mapping) else 0
                except (TypeError, ValueError):
                    raw_version = 0
                if (
                    raw_version < QUEUE_STORE_VERSION
                    or any("priority" not in value for value in values if isinstance(value, Mapping))
                ):
                    try:
                        self._write_sync()
                    except OSError:
                        pass
        except (OSError, ValueError, TypeError):
            self._items = {}

    def _write_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": QUEUE_STORE_VERSION, "items": [item.to_storage_dict() for item in self._items.values()]}
        fd, name = tempfile.mkstemp(prefix=".workflow-queue-", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            Path(name).replace(self.path)
        finally:
            try:
                Path(name).unlink(missing_ok=True)
            except OSError:
                pass

    async def load(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._load_sync)

    async def save(self, item: WorkflowQueueItem) -> WorkflowQueueItem:
        async with self._lock:
            self._load_sync()
            self._items[item.queue_id] = item
            try:
                await asyncio.to_thread(self._write_sync)
            except OSError:
                # Queue operation still returns the in-memory item; callers can
                # observe an explicit persistence flag from the service.
                pass
        return item

    async def get(self, queue_id: str) -> WorkflowQueueItem | None:
        async with self._lock:
            self._load_sync()
            item = self._items.get(str(queue_id or ""))
            return WorkflowQueueItem.from_dict(item.to_storage_dict()) if item else None

    async def values(self) -> list[WorkflowQueueItem]:
        async with self._lock:
            self._load_sync()
            return [WorkflowQueueItem.from_dict(item.to_storage_dict()) for item in self._items.values()]

    async def delete(self, queue_id: str) -> bool:
        async with self._lock:
            self._load_sync()
            if str(queue_id or "") not in self._items:
                return False
            del self._items[str(queue_id)]
            try:
                await asyncio.to_thread(self._write_sync)
            except OSError:
                pass
            return True

    async def clear(self, *, predicate: Callable[[WorkflowQueueItem], bool], confirm: bool = False) -> int:
        if not confirm:
            raise ValueError("clearing workflow queue/history requires confirm=True")
        async with self._lock:
            self._load_sync()
            removed = [key for key, item in self._items.items() if predicate(item)]
            for key in removed:
                self._items.pop(key, None)
            if removed:
                try:
                    await asyncio.to_thread(self._write_sync)
                except OSError:
                    pass
            return len(removed)


EventSink = Callable[[RunItemEvent], Awaitable[None] | None]


class WorkflowRunQueue:
    """FIFO queue that executes saved workflow definitions one at a time."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        manager: Any | None = None,
        runner: Any | None = None,
        store: WorkflowQueueStore | None = None,
        work_root: str | Path | None = None,
        data_dir: str | Path | None = None,
        store_path: str | Path | None = None,
        emit: EventSink | None = None,
        auto_start: bool = True,
    ) -> None:
        self.manager = manager
        self.runner = runner
        effective_root = work_root if work_root is not None else root
        self.store = store or WorkflowQueueStore(root=effective_root, store_path=store_path, data_dir=data_dir)
        self.emit = emit
        self.auto_start = auto_start
        self._started = False
        self._stopping = False
        # Kept separate from the runner's user-cancellation token.  Setting it
        # during host shutdown makes an in-flight run resumable; explicit
        # queue.cancel leaves it clear and therefore remains terminal.
        self._stop_requested = asyncio.Event()
        self._worker: asyncio.Task[Any] | None = None
        self._wake = asyncio.Event()
        self._active_tasks: dict[str, asyncio.Task[Any]] = {}
        self._waiters: dict[str, list[asyncio.Future[WorkflowQueueItem]]] = {}
        self._lock = asyncio.Lock()

    @property
    def queue_path(self) -> Path:
        return self.store.path

    async def start(self) -> None:
        if self._started:
            return
        await self.store.load()
        # A process that exited while executing leaves a running/paused item.
        # Requeue it with the same IDs; WorkflowRunner's durable snapshot will
        # supply the last completed value table on the next attempt.
        items = await self.store.values()
        for item in items:
            item_changed = False
            if item.status == "running":
                item.status = "queued"
                item.updated_at = _utcnow()
                item_changed = True
            elif item.status == "paused" and not _has_wait_descriptor(item):
                # Paused entries are continuable by design.  Keep explicit
                # paused status visible until the next worker turn, then run.
                item.status = "queued"
                item.updated_at = _utcnow()
                item_changed = True
            if item_changed:
                await self.store.save(item)
        self._started = True
        self._stopping = False
        self._stop_requested.clear()
        self._worker = asyncio.create_task(self._worker_loop(), name="workflow:queue")
        self._wake.set()

    async def stop(self) -> None:
        self._stop_requested.set()
        self._stopping = True
        self._started = False
        active_ids = list(self._active_tasks)
        # Persist the latest runner state before propagating task cancellation.
        # This covers adapters that do not observe the pause token themselves;
        # the normal WorkflowRunner also writes the same snapshot idempotently.
        for queue_id in active_ids:
            item = await self.store.get(queue_id)
            if item is None or item.status != "running":
                continue
            interrupt = getattr(self.runner, "interrupt", None)
            if callable(interrupt):
                try:
                    await _maybe_await(interrupt(item.thread_id, item.run_id))
                except Exception:
                    # The cancellation path below still records an interrupted
                    # queue item even when an embedded runner lacks snapshots.
                    pass
        worker = self._worker
        self._worker = None
        if worker is not None and not worker.done():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        # Any active operation is persisted as paused/interrupted.  Its
        # snapshot remains available for continuation after a fresh process
        # starts.  Do not silently convert it to terminal cancellation.
        for queue_id in active_ids:
            item = await self.store.get(queue_id)
            if item is not None and item.status in {"running", "cancelled"}:
                await self._mark_interrupted(item)
        self._active_tasks.clear()

    async def enqueue(
        self,
        workflow: WorkflowDef | None = None,
        *,
        workflow_name: str = "",
        workflow_id: str = "",
        name: str = "",
        work_root: str | Path | None = None,
        inputs: Mapping[str, Any] | None = None,
        thread_id: str = "",
        run_id: str = "",
        max_steps: int | None = None,
        start_node: str | None = None,
        single_node: str | None = None,
        prior_values: Mapping[str, Any] | None = None,
        prior_node_states: Mapping[str, WorkflowNodeState | Mapping[str, Any]] | None = None,
        metadata: Mapping[str, Any] | None = None,
        queue_id: str = "",
        priority: int | float | None = None,
        auto_start: bool | None = None,
    ) -> WorkflowQueueItem:
        if workflow is None and self.manager is not None:
            target_name = workflow_name or name
            if target_name:
                workflow = await _maybe_await(self.manager.get(target_name, work_root=str(work_root) if work_root else None))
        if workflow is not None:
            workflow_name = workflow_name or workflow.name
            workflow_id = workflow_id or workflow.id
        workflow_name = str(workflow_name or name or "").strip()
        if not workflow_name and not workflow_id:
            raise ValueError("workflow_name or workflow_id is required")
        if priority is None:
            # A document-level priority is a convenient authoring seam.  The
            # queue item stores a scalar copy, so later document edits cannot
            # reorder an already accepted run.
            priority = 0
            document = getattr(workflow, "document", None)
            if isinstance(document, Mapping):
                policies = document.get("policies")
                if isinstance(policies, Mapping) and "priority" in policies:
                    priority = policies.get("priority")
        priority = _as_priority(priority, strict=True)
        now = _utcnow()
        item = WorkflowQueueItem(
            queue_id=queue_id or _new_id("wfq"),
            workflow_id=str(workflow_id or ""),
            workflow_revision=max(0, int(workflow.revision)) if workflow is not None else 0,
            workflow_definition=_pinned_definition(workflow) if workflow is not None else {},
            workflow_name=workflow_name,
            work_root=str(work_root or (workflow.work_root if workflow is not None else "")),
            thread_id=str(thread_id or f"workflow:{workflow_id or workflow_name}"),
            run_id=str(run_id or _new_id("workflow_run")),
            inputs=dict(inputs or {}),
            status="queued",
            priority=priority,
            created_at=now,
            updated_at=now,
            max_steps=max_steps,
            start_node=start_node,
            single_node=single_node,
            prior_values=dict(prior_values or {}),
            prior_node_states={
                str(key): value if isinstance(value, WorkflowNodeState) else WorkflowNodeState.from_dict(value, node_id=str(key))
                for key, value in (prior_node_states or {}).items()
                if isinstance(value, (WorkflowNodeState, Mapping))
            },
            metadata=dict(metadata or {}),
        )
        await self.store.save(item)
        await self._emit_status(item, "queued")
        should_start = self.auto_start if auto_start is None else bool(auto_start)
        if should_start and self.manager is not None and self.runner is not None:
            await self.start()
            self._wake.set()
        return item

    async def list(
        self,
        *,
        status: str | Iterable[str] | None = None,
        work_root: str | Path | None = None,
        workflow_id: str = "",
        workflow_name: str = "",
        include_history: bool = True,
        limit: int | None = None,
    ) -> list[WorkflowQueueItem]:
        items = await self.store.values()
        statuses = {str(value) for value in status} if isinstance(status, (list, tuple, set, frozenset)) else ({str(status)} if status else None)
        root = str(Path(work_root).expanduser().resolve()) if work_root else ""
        values = [
            item for item in items
            if (statuses is None or item.status in statuses)
            and (not root or _same_root(item.work_root, root))
            and (not workflow_id or item.workflow_id == workflow_id)
            and (not workflow_name or item.workflow_name == workflow_name)
            and (include_history or item.status not in TERMINAL_STATUSES)
        ]
        # Queue consumers claim queued work in this order.  Applying the same
        # deterministic order to a queued-only listing makes the contract
        # observable to CLI/UI callers without changing chronological history
        # ordering for mixed terminal records.
        if statuses is not None and statuses and statuses <= {"queued"}:
            values.sort(key=lambda item: (-item.priority, item.created_at, item.queue_id))
        else:
            values.sort(key=lambda item: (item.created_at, item.queue_id))
        if limit is not None and limit >= 0:
            values = values[:limit]
        return values

    async def history(
        self,
        *,
        work_root: str | Path | None = None,
        workflow_id: str = "",
        workflow_name: str = "",
        status: str | Iterable[str] | None = None,
        limit: int | None = None,
        include_active: bool = False,
    ) -> list[WorkflowQueueItem]:
        values = await self.list(
            status=status,
            work_root=work_root,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            include_history=True,
            limit=limit,
        )
        if not include_active and status is None:
            values = [item for item in values if item.status in TERMINAL_STATUSES or item.status == "paused"]
        return values

    async def get(self, queue_id: str = "", *, run_id: str = "") -> WorkflowQueueItem | None:
        if queue_id:
            item = await self.store.get(queue_id)
            if item is not None:
                return item
        if run_id:
            for item in await self.store.values():
                if item.run_id == run_id:
                    return item
        return None

    async def cancel(self, queue_id: str = "", *, run_id: str = "") -> WorkflowQueueItem | None:
        item = await self.get(queue_id, run_id=run_id)
        if item is None:
            return None
        if item.status == "queued":
            item.status = "cancelled"
            item.error = "cancelled"
            item.finished_at = _utcnow()
            item.updated_at = item.finished_at
            item.result = WorkflowRunResult(status="cancelled", error="cancelled", run_id=item.run_id)
            await self.store.save(item)
            await self._emit_status(item, "cancelled")
            self._resolve_waiters(item)
            return item
        if item.status == "running":
            task = self._active_tasks.get(item.queue_id)
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            else:
                registry = getattr(self.runner, "runtime_task_registry", None)
                cancel = getattr(registry, "cancel", None)
                if callable(cancel):
                    cancel(item.thread_id, run_id=item.run_id, force=True)
                # A stale running record may outlive its process task. Mark it
                # terminal once the host cancellation request was accepted so
                # history never leaves an unbounded "running" ghost.
                current = await self.get(item.queue_id, run_id=item.run_id)
                if current is not None and current.status == "running":
                    current.status = "cancelled"
                    current.error = "cancelled"
                    current.finished_at = _utcnow()
                    current.updated_at = current.finished_at
                    current.result = WorkflowRunResult(status="cancelled", error="cancelled", run_id=current.run_id)
                    await self.store.save(current)
                    await self._emit_status(current, "cancelled")
                    self._resolve_waiters(current)
            return await self.get(item.queue_id, run_id=item.run_id) or item
        return item

    async def clear(
        self,
        *,
        confirm: bool = False,
        all_items: bool = False,
        work_root: str | Path | None = None,
        workflow_id: str = "",
        workflow_name: str = "",
    ) -> int:
        if not confirm:
            raise ValueError("clearing workflow queue/history requires confirm=True")
        if all_items and not confirm:
            raise ValueError("clearing all workflow queue/history requires confirm=True")
        root = str(Path(work_root).expanduser().resolve()) if work_root else ""
        return await self.store.clear(
            confirm=True,
            predicate=lambda item: (
                (all_items or item.status in TERMINAL_STATUSES)
                and (not root or _same_root(item.work_root, root))
                and (not workflow_id or item.workflow_id == workflow_id)
                and (not workflow_name or item.workflow_name == workflow_name)
            ),
        )

    async def wait(self, queue_id: str, *, timeout: float | None = None) -> WorkflowQueueItem | None:
        item = await self.get(queue_id)
        if item is None or item.status in TERMINAL_STATUSES or item.status == "paused":
            return item
        loop = asyncio.get_running_loop()
        future: asyncio.Future[WorkflowQueueItem] = loop.create_future()
        self._waiters.setdefault(queue_id, []).append(future)
        try:
            return await asyncio.wait_for(future, timeout=timeout) if timeout is not None else await future
        finally:
            waiters = self._waiters.get(queue_id, [])
            if future in waiters:
                waiters.remove(future)
            if not waiters:
                self._waiters.pop(queue_id, None)

    async def update_from_result(self, run_id: str, result: WorkflowRunResult) -> WorkflowQueueItem | None:
        """Synchronize a paused queue record after out-of-band signal resume."""
        item = await self.get(run_id=run_id)
        if item is None:
            return None
        item.result = result
        item.status = result.status  # type: ignore[assignment]
        item.error = result.error
        item.updated_at = _utcnow()
        if result.status == "paused":
            item.prior_values = dict(result.values)
            item.prior_node_states = dict(result.node_states)
            item.finished_at = None
        else:
            item.finished_at = item.finished_at or _utcnow()
        await self.store.save(item)
        await self._emit_status(item, result.status, result=result)
        self._resolve_waiters(item)
        return item

    async def update_from_result(self, run_id: str, result: WorkflowRunResult) -> WorkflowQueueItem | None:
        """Synchronize a paused queue record after an out-of-band signal."""
        item = await self.get(run_id=run_id)
        if item is None:
            return None
        item.result = result
        item.status = result.status  # type: ignore[assignment]
        item.error = result.error
        item.updated_at = _utcnow()
        item.prior_values = dict(result.values)
        item.prior_node_states = dict(result.node_states)
        item.finished_at = None if result.status == "paused" else _utcnow()
        await self.store.save(item)
        await self._emit_status(item, result.status, result=result)
        self._resolve_waiters(item)
        return item

    async def _worker_loop(self) -> None:
        while not self._stopping:
            items = await self.list(status="queued", include_history=False)
            if not items:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                continue
            item = items[0]
            task = asyncio.create_task(self._execute_item(item), name=f"workflow:queue:{item.queue_id}")
            self._active_tasks[item.queue_id] = task
            try:
                await task
            except asyncio.CancelledError:
                if self._stopping:
                    raise
            finally:
                self._active_tasks.pop(item.queue_id, None)

    async def _execute_item(self, item: WorkflowQueueItem) -> None:
        current = await self.store.get(item.queue_id)
        if current is None or current.status != "queued":
            return
        item = current
        item.status = "running"
        item.started_at = item.started_at or _utcnow()
        item.updated_at = _utcnow()
        await self.store.save(item)
        await self._emit_status(item, "running")
        if self.manager is None or self.runner is None:
            item.status = "failed"
            item.error = "workflow queue runner is not configured"
            item.finished_at = _utcnow()
            item.updated_at = item.finished_at
            item.result = WorkflowRunResult(status="failed", error=item.error, run_id=item.run_id)
            await self.store.save(item)
            await self._emit_status(item, "failed")
            self._resolve_waiters(item)
            return
        try:
            definition = _definition_from_pin(item.workflow_definition)
            if definition is None:
                definition = await _maybe_await(self.manager.get(item.workflow_name, work_root=item.work_root or None))
            if definition is None and item.workflow_id:
                definition = await _maybe_await(
                    self.manager.get_by_id(item.workflow_id, work_root=item.work_root or None)
                )
            if definition is None:
                raise LookupError(f"Workflow not found: {item.workflow_name or item.workflow_id}")
            if item.workflow_id and definition.id != item.workflow_id:
                raise LookupError(
                    f"Workflow identity mismatch: queued {item.workflow_id}, found {definition.id}"
                )
            if item.workflow_revision and definition.revision != item.workflow_revision:
                raise LookupError(
                    f"Workflow revision {item.workflow_revision} is not available; current revision is {definition.revision}"
                )
            # Migration boundary for version-1 queue records: persist the exact
            # definition before invoking any node, then always resume from it.
            if not item.workflow_definition:
                item.workflow_id = definition.id
                item.workflow_revision = max(0, int(definition.revision))
                item.workflow_definition = _pinned_definition(definition)
                item.updated_at = _utcnow()
                await self.store.save(item)
            context_event_metadata = {
                "permission_policy_required": True,
                **{
                    key: item.metadata[key]
                    for key in ("trace_id", "correlation_id", "actor_id", "actor_kind", "model_id")
                    if isinstance(item.metadata, Mapping) and key in item.metadata
                },
            }
            result = await self.runner.run(
                definition,
                inputs=dict(item.inputs),
                work_root=item.work_root or definition.work_root,
                thread_id=item.thread_id,
                run_id=item.run_id,
                # Leave absent prior values as ``None`` so Runner can hydrate
                # the durable snapshot after a process restart. An explicit
                # non-empty table (from a caller's partial run) still wins.
                prior_values=dict(item.prior_values) if item.prior_values else None,
                prior_node_states=dict(item.prior_node_states) or None,
                max_steps=item.max_steps,
                start_node=item.start_node,
                single_node=item.single_node,
                execution_context=WorkflowExecutionContext(
                    parent_session_id=item.thread_id,
                    parent_run_id=item.run_id,
                    cwd=item.work_root or definition.work_root,
                    cancellation=getattr(
                        getattr(self.runner, "runtime_task_registry", None),
                        "get_cancel_event",
                        lambda _thread_id: None,
                    )(item.thread_id),
                    permissions=dict(item.metadata.get("permissions") or item.metadata.get("runtime_permissions") or {})
                    if isinstance(item.metadata, Mapping)
                    else {},
                    pause_on_cancel=self._stop_requested,
                    event_metadata=context_event_metadata,
                ),
            )
            item.result = result
            item.error = result.error or ("cancelled" if result.status == "cancelled" else "")
            item.status = result.status  # type: ignore[assignment]
            item.updated_at = _utcnow()
            if result.status == "paused":
                # A paused item remains in history and is eligible for a later
                # explicit continuation.  The worker does not spin it again.
                item.prior_values = dict(result.values)
                item.prior_node_states = dict(result.node_states)
                item.finished_at = None
            else:
                item.finished_at = item.finished_at or _utcnow()
            await self.store.save(item)
            await self._emit_status(item, result.status)
            await self._emit_status(item, "progress", result=result)
            self._resolve_waiters(item)
        except asyncio.CancelledError:
            if self._stopping:
                await self._mark_interrupted(item)
                return
            item.status = "cancelled"
            item.error = "cancelled"
            item.finished_at = _utcnow()
            item.updated_at = item.finished_at
            item.result = WorkflowRunResult(status="cancelled", error="cancelled", run_id=item.run_id)
            await self.store.save(item)
            await self._emit_status(item, "cancelled")
            self._resolve_waiters(item)
        except Exception as exc:  # noqa: BLE001 - queue boundary
            item.status = "failed"
            item.error = str(exc) or type(exc).__name__
            item.finished_at = _utcnow()
            item.updated_at = item.finished_at
            item.result = WorkflowRunResult(status="failed", error=item.error, run_id=item.run_id)
            await self.store.save(item)
            await self._emit_status(item, "failed")
            self._resolve_waiters(item)

    async def _mark_interrupted(self, item: WorkflowQueueItem) -> WorkflowQueueItem:
        """Persist a paused queue record while preserving runner progress."""
        current = await self.store.get(item.queue_id) or item
        result: WorkflowRunResult | None = None
        interrupt = getattr(self.runner, "interrupt", None)
        if callable(interrupt):
            try:
                candidate = await _maybe_await(interrupt(current.thread_id, current.run_id))
                if isinstance(candidate, WorkflowRunResult):
                    result = candidate
            except Exception:
                result = None
        if result is None and isinstance(current.result, WorkflowRunResult):
            # A third-party runner may have returned a cancellation result
            # just before the queue observed shutdown.  Reuse its partial
            # values/states when converting that result to resumable paused
            # semantics instead of discarding progress.
            result = WorkflowRunResult.from_dict(current.result.to_dict())
        if result is None:
            snapshots = getattr(self.runner, "_run_snapshots", None)
            if isinstance(snapshots, Mapping):
                candidate = snapshots.get((current.thread_id, current.run_id))
                if isinstance(candidate, WorkflowRunResult):
                    result = WorkflowRunResult.from_dict(candidate.to_dict())
        if result is None:
            active_runs = getattr(self.runner, "_active_runs", None)
            active = active_runs.get((current.thread_id, current.run_id)) if isinstance(active_runs, Mapping) else None
            if active is not None:
                result = WorkflowRunResult(
                    status="paused",
                    node_states={
                        node_id: WorkflowNodeState.from_dict(state.to_dict(), node_id=node_id)
                        for node_id, state in active.node_states.items()
                    },
                    values=_json_copy(active.values),
                    run_id=current.run_id,
                    steps_remaining=max(0, len(active.order) - active.steps_taken),
                )
        if result is None:
            # A third-party runner may not expose snapshots.  Preserve any
            # partial state already carried by the queue item rather than
            # turning shutdown into irreversible cancellation.
            result = WorkflowRunResult(
                status="paused",
                node_states=dict(current.prior_node_states),
                values=_json_copy(current.prior_values),
                run_id=current.run_id,
            )
        result.status = "paused"
        result.finished_at = None
        current.status = "paused"
        current.error = "interrupted"
        current.finished_at = None
        current.updated_at = _utcnow()
        current.result = result
        current.prior_values = dict(result.values)
        current.prior_node_states = dict(result.node_states)
        await self.store.save(current)
        await self._emit_status(current, "paused")
        self._resolve_waiters(current)
        return current

    async def _emit_status(self, item: WorkflowQueueItem, status: str, *, result: WorkflowRunResult | None = None) -> None:
        if self.emit is None:
            return
        # ``RunItemEvent`` predates workflow's ``progress``/``paused`` names;
        # retain the canonical object while carrying the extended status as a
        # data value (runtime does not enforce Literal types at execution time).
        event_status = status
        workflow_id = item.workflow_id
        payload: dict[str, Any] = {
            "plugin_id": "workflow",
            "workflow_id": workflow_id,
            "workflow_revision": item.workflow_revision,
            "queue_id": item.queue_id,
            "run_id": item.run_id,
            "thread_id": item.thread_id,
            "status": status,
            "workflow_name": item.workflow_name,
        }
        correlation_keys = ("parent_session_id", "parent_run_id", "parent_turn_id", "parent_call_id", "trace_id", "correlation_id")
        for key in correlation_keys:
            if isinstance(item.metadata, Mapping) and item.metadata.get(key):
                payload[key] = item.metadata[key]
        if result is not None:
            payload.update({
                "steps_remaining": result.steps_remaining,
                "output": _json_copy(result.output),
                "error": result.error,
                "completed_nodes": sum(1 for state in result.node_states.values() if state.status in {"done", "skipped"}),
            })
        metadata = {
            "plugin_id": "workflow",
            "workflow_id": workflow_id,
            "workflow_revision": item.workflow_revision,
            "queue_id": item.queue_id,
            "run_id": item.run_id,
            "thread_id": item.thread_id,
        }
        for key in correlation_keys:
            if isinstance(item.metadata, Mapping) and item.metadata.get(key):
                metadata[key] = item.metadata[key]
        try:
            emitted = self.emit(
                RunItemEvent(
                    kind="status",
                    thread_id=item.thread_id,
                    run_id=item.run_id,
                    turn_id=item.run_id,
                    item_id=item.queue_id,
                    status=event_status,  # type: ignore[arg-type]
                    payload=payload,
                    source="plugin:workflow",
                    metadata=metadata,
                )
            )
            if inspect.isawaitable(emitted):
                await emitted
        except Exception:
            pass

    def _resolve_waiters(self, item: WorkflowQueueItem) -> None:
        if item.status not in TERMINAL_STATUSES and item.status != "paused":
            return
        for future in self._waiters.pop(item.queue_id, []):
            if not future.done():
                future.set_result(WorkflowQueueItem.from_dict(item.to_storage_dict()))


WorkflowQueueService = WorkflowRunQueue
WorkflowQueue = WorkflowRunQueue
WorkflowRunQueueItem = WorkflowQueueItem


def _pinned_definition(workflow: WorkflowDef) -> dict[str, Any]:
    value = workflow.to_dict()
    if workflow.document is not None:
        value["document"] = _json_copy(workflow.document)
    return _json_copy(value)


def _definition_from_pin(value: Mapping[str, Any] | None) -> WorkflowDef | None:
    if not isinstance(value, Mapping) or not value:
        return None
    definition = WorkflowDef.from_dict(dict(value))
    document = value.get("document")
    if isinstance(document, Mapping):
        definition.document = _json_copy(document)
    return definition


def _has_wait_descriptor(item: WorkflowQueueItem) -> bool:
    """Whether a paused run is waiting for an external signal/token.

    A durable wait is not ordinary continuation work: requeueing it during
    process startup would immediately execute the node again and bypass the
    signal/approval hand-off.  ``result`` is the authoritative source; the
    prior node state fallback covers old queue records that persisted only
    node state.
    """

    if item.result is not None and isinstance(item.result.wait_descriptor, Mapping):
        if item.result.wait_descriptor:
            return True
    return any(
        isinstance(state.wait_descriptor, Mapping) and bool(state.wait_descriptor)
        for state in item.prior_node_states.values()
    )


def _same_root(value: str, root: str) -> bool:
    if not value:
        return False
    try:
        return Path(value).expanduser().resolve() == Path(root).expanduser().resolve()
    except OSError:
        return str(value) == str(root)


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


__all__ = [
    "QueueStatus",
    "QUEUE_STORE_VERSION",
    "TERMINAL_STATUSES",
    "WorkflowQueue",
    "WorkflowQueueItem",
    "WorkflowQueueService",
    "WorkflowQueueStore",
    "WorkflowRunQueue",
    "WorkflowRunQueueItem",
]
