"""Derived human-task views for durable workflow waits.

Human tasks are deliberately *not* a second workflow state store.  A task is
projected from the resumable workflow snapshot and the append-only run journal
(``wait.created``/``wait.signalled`` events).  The resume token therefore
stays an implementation detail of this module: callers complete a task by its
stable ``task_id`` and never receive the token in a list, detail, audit, or
Arrange payload.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .credentials import SECRET_KEYS
from .durable import WorkflowRunEvent


# A resume token is not a credential, but it is a bearer secret and must obey
# the same output boundary.  ``token`` is included because older snapshots
# used that short spelling for the resume token.
_PRIVATE_KEYS = {
    *(str(value).strip().lower().replace("-", "_") for value in SECRET_KEYS),
    "resume_token",
    "continuation_token",
    "token",
    "authorization",
    "auth",
}


def _normalise_key(value: Any) -> str:
    text = str(value).strip().replace("-", "_")
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text).lower()


def _safe(value: Any) -> Any:
    """Return a JSON-safe projection with bearer/credential values removed."""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            name = str(key)
            if _normalise_key(name) in _PRIVATE_KEYS:
                # Never echo a resume token, even as ``[REDACTED]``: callers
                # must not be able to distinguish or collect bearer values.
                if _normalise_key(name) in {
                    "resume_token",
                    "continuation_token",
                    "token",
                }:
                    continue
                result[name] = "[REDACTED]" if nested is not None else None
                continue
            result[name] = _safe(nested)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return _safe(value.to_dict())
        except Exception:  # noqa: BLE001 - a view must tolerate malformed data
            return str(value)
    return str(value)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            candidate = to_dict()
        except Exception:  # noqa: BLE001
            return {}
        return dict(candidate) if isinstance(candidate, Mapping) else {}
    return {}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: Any) -> str | None:
    parsed = _parse_dt(value)
    return parsed.isoformat() if parsed is not None else (str(value) if value else None)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "all"}
    return bool(value)


def _resolved_root(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    try:
        return str(Path(text).expanduser().resolve())
    except OSError:
        return text


def _store_root(store: Any) -> str:
    """Infer the workspace root represented by a snapshot/event store."""

    candidate = getattr(store, "work_root", None) or getattr(store, "root", None)
    if candidate:
        return _resolved_root(candidate)
    directory = getattr(store, "directory", None)
    if not directory:
        return ""
    try:
        path = Path(directory).expanduser().resolve()
        # WorkflowSnapshotStore/EventStore use {root}/.lam/workflow/{kind}.
        if path.name in {"snapshots", "events"} and path.parent.name == "workflow":
            return str(path.parent.parent.parent)
        return str(path)
    except OSError:
        return str(directory)


def _stores(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [item for item in value.values() if item is not None]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [item for item in value if item is not None]
    return [value]


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _list_store(store: Any) -> list[Any]:
    method = getattr(store, "list", None)
    if callable(method):
        try:
            value = await _maybe_await(method())
        except TypeError:
            # A few host adapters expose ``list(work_root=...)`` only.  The
            # center already applies scope, so an empty call is safest.
            value = []
        return list(value) if isinstance(value, (list, tuple)) else []
    method = getattr(store, "list_sync", None)
    if callable(method):
        try:
            value = await asyncio.to_thread(method)
        except TypeError:
            value = []
        return list(value) if isinstance(value, (list, tuple)) else []
    return []


async def _list_events(store: Any, run_id: str = "") -> list[Any]:
    """Read events from an adapter, falling back to JSONL journal files."""

    for method_name in ("list_all", "all", "events"):
        method = getattr(store, method_name, None)
        if not callable(method):
            continue
        try:
            value = await _maybe_await(method())
        except TypeError:
            continue
        if isinstance(value, (list, tuple)):
            return list(value)

    method = getattr(store, "list", None)
    if run_id and callable(method):
        try:
            value = await _maybe_await(method(run_id))
        except TypeError:
            value = []
        if isinstance(value, (list, tuple)):
            return list(value)

    directory = getattr(store, "directory", None)
    if not directory:
        return []
    try:
        paths = sorted(Path(directory).glob("*.jsonl"))
    except OSError:
        return []
    result: list[Any] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                raw = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(raw, Mapping):
                continue
            if run_id and str(raw.get("run_id") or "") != run_id:
                continue
            try:
                result.append(WorkflowRunEvent.from_dict(raw))
            except (TypeError, ValueError):
                continue
    return result


def _event_dict(value: Any) -> dict[str, Any]:
    return _mapping(value)


def _event_sort_key(value: Any) -> tuple[int, str]:
    event = _event_dict(value)
    try:
        sequence = int(event.get("sequence") or 0)
    except (TypeError, ValueError):
        sequence = 0
    return sequence, _text(event.get("occurred_at"))


def _node_map(definition: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw_nodes = definition.get("nodes")
    if not isinstance(raw_nodes, list):
        graph = definition.get("graph")
        raw_nodes = graph.get("nodes") if isinstance(graph, Mapping) else []
    result: dict[str, dict[str, Any]] = {}
    for raw in raw_nodes if isinstance(raw_nodes, list) else []:
        node = _mapping(raw)
        node_id = _text(node.get("id") or node.get("node_id") or node.get("nodeId"))
        if node_id:
            result[node_id] = node
    return result


def _node_config(node: Mapping[str, Any]) -> dict[str, Any]:
    config = node.get("config")
    if isinstance(config, Mapping):
        return dict(config)
    params = node.get("params")
    return dict(params) if isinstance(params, Mapping) else {}


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


@dataclass
class _RunRecord:
    source_root: str = ""
    thread_id: str = ""
    run_id: str = ""
    workflow_id: str = ""
    workflow_name: str = ""
    revision: int = 0
    work_root: str = ""
    definition: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _TaskRecord:
    task_id: str
    run: _RunRecord
    node_id: str
    descriptor: dict[str, Any]
    node: dict[str, Any]
    status: str
    outcome: dict[str, Any] | None = None
    completed_at: str | None = None

    @property
    def resume_token(self) -> str:
        return _text(self.descriptor.get("resume_token") or self.descriptor.get("token"))

    def to_dict(self, *, include_audit: bool = False) -> dict[str, Any]:
        descriptor = self.descriptor
        config = _node_config(self.node)
        task_title = _text(
            _first_value(
                descriptor.get("title"),
                descriptor.get("task_title"),
                config.get("task_title"),
                config.get("title"),
                self.node.get("title"),
                self.node_id,
            )
        )
        kind = _text(descriptor.get("kind") or config.get("kind") or "wait_event") or "wait_event"
        workflow = self.run.workflow_id or self.run.workflow_name
        assignee = _text(
            _first_value(
                descriptor.get("assignee"),
                descriptor.get("assigned_to"),
                descriptor.get("assignedTo"),
                config.get("assignee"),
                config.get("assigned_to"),
                config.get("assignedTo"),
            )
        )
        group = _text(
            _first_value(
                descriptor.get("group"),
                descriptor.get("group_id"),
                descriptor.get("groupId"),
                config.get("group"),
                config.get("group_id"),
                config.get("groupId"),
            )
        )
        form = _first_value(
            descriptor.get("form"),
            descriptor.get("form_schema"),
            descriptor.get("formSchema"),
            config.get("form"),
            config.get("form_schema"),
            config.get("formSchema"),
        )
        due_at = _first_value(
            descriptor.get("due_at"),
            descriptor.get("dueAt"),
            descriptor.get("deadline"),
            config.get("due_at"),
            config.get("dueAt"),
            config.get("deadline"),
            config.get("timeout_at"),
        )
        created_at = _first_value(descriptor.get("created_at"), descriptor.get("createdAt"))
        result: dict[str, Any] = {
            "task_id": self.task_id,
            "id": self.task_id,
            "status": self.status,
            "run_id": self.run.run_id,
            "run": self.run.run_id,
            "thread_id": self.run.thread_id,
            "thread": self.run.thread_id,
            "workflow_id": self.run.workflow_id,
            "workflow_name": self.run.workflow_name,
            "workflow": workflow,
            "workflow_revision": self.run.revision,
            "revision": self.run.revision,
            "node_id": self.node_id,
            "node": self.node_id,
            "kind": kind,
            "title": task_title,
            "assignee": assignee or None,
            "group": group or None,
            "form": _safe(form if form is not None else {}),
            "due_at": _iso(due_at),
            "event_type": _text(descriptor.get("event_type") or descriptor.get("eventType") or "event"),
            "created_at": _iso(created_at),
            "completed_at": self.completed_at,
            "outcome": _safe(self.outcome) if self.outcome is not None else None,
            "work_root": self.run.work_root,
        }
        if include_audit:
            result["audit"] = [
                _audit_event(event)
                for event in sorted(self.run.events, key=_event_sort_key)
            ]
        return _safe(result)


def _audit_event(event: Mapping[str, Any]) -> dict[str, Any]:
    return _safe(
        {
            "event_id": event.get("event_id"),
            "sequence": event.get("sequence", 0),
            "kind": event.get("kind"),
            "occurred_at": event.get("occurred_at"),
            "workflow_id": event.get("workflow_id"),
            "workflow_revision": event.get("workflow_revision", 0),
            "node_id": event.get("node_id"),
            "attempt_id": event.get("attempt_id"),
            "payload": event.get("payload") or {},
        }
    )


def _status_from_outcome(value: Any) -> str:
    status = _text(value).lower()
    if status in {"approved", "approve", "accepted", "received", "rejected", "reject", "timed_out", "timeout", "completed"}:
        return "completed"
    return "completed" if status else "completed"


class HumanTaskCenter:
    """Project and complete workflow human tasks from durable stores."""

    def __init__(
        self,
        *,
        snapshot_store: Any | None = None,
        event_store: Any | None = None,
        runner: Any | None = None,
        workflow_store: Any | None = None,
        work_root: str | Path | None = None,
        snapshot_stores: Iterable[Any] | Mapping[str, Any] | None = None,
        event_stores: Iterable[Any] | Mapping[str, Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.snapshot_stores = [*(_stores(snapshot_stores)), *(_stores(snapshot_store))]
        self.event_stores = [*(_stores(event_stores)), *(_stores(event_store))]
        self.runner = runner
        self.workflow_store = workflow_store
        self.work_root = _resolved_root(work_root)
        self.clock = clock or getattr(runner, "clock", None) or (lambda: datetime.now(timezone.utc))

    @classmethod
    def from_context(cls, context: Any, *, runtime: Any | None = None) -> "HumanTaskCenter":
        runtime = runtime or (context.service("workflow") if context is not None else None)
        runner = getattr(runtime, "runner", None)
        workflow_store = getattr(runtime, "store", None)
        snapshot_store = (
            context.service("workflow_snapshot_store") if context is not None else None
        ) or getattr(runner, "snapshot_store", None)
        event_store = (
            context.service("workflow_event_store") if context is not None else None
        ) or getattr(runner, "event_store", None)
        snapshot_stores = context.service("workflow_snapshot_stores") if context is not None else None
        event_stores = context.service("workflow_event_stores") if context is not None else None
        work_root = getattr(context, "work_root", None) if context is not None else None
        return cls(
            snapshot_store=snapshot_store,
            event_store=event_store,
            snapshot_stores=snapshot_stores,
            event_stores=event_stores,
            runner=runner,
            workflow_store=workflow_store,
            work_root=work_root,
        )

    async def _records(self) -> list[_RunRecord]:
        records: dict[tuple[str, str], _RunRecord] = {}
        snapshots = [
            (store, item)
            for store in self.snapshot_stores
            for item in await _list_store(store)
        ]
        for store, raw_item in snapshots:
            raw = _mapping(raw_item)
            result = _mapping(raw.get("result", raw))
            run_id = _text(raw.get("run_id") or result.get("run_id"))
            if not run_id:
                continue
            definition = _mapping(raw.get("workflow_definition"))
            source_root = _store_root(store)
            work_root = _resolved_root(
                raw.get("work_root")
                or definition.get("work_root")
                or source_root
            )
            key = (work_root or source_root, run_id)
            record = records.setdefault(key, _RunRecord(source_root=source_root, run_id=run_id))
            record.thread_id = _text(raw.get("thread_id") or result.get("thread_id") or record.thread_id)
            record.workflow_id = _text(raw.get("workflow_id") or result.get("workflow_id") or definition.get("id"))
            record.workflow_name = _text(raw.get("workflow_name") or definition.get("name"))
            try:
                record.revision = int(raw.get("workflow_revision") or result.get("workflow_revision") or definition.get("revision") or 0)
            except (TypeError, ValueError):
                record.revision = 0
            record.work_root = work_root
            record.definition = definition
            record.result = result

        # First consume adapter-level all-events methods / filesystem journals.
        for store in self.event_stores:
            events = await _list_events(store)
            if not events:
                continue
            source_root = _store_root(store)
            for raw_event in events:
                event = _event_dict(raw_event)
                run_id = _text(event.get("run_id"))
                if not run_id:
                    continue
                # Prefer an existing snapshot's exact scope.  When only a
                # journal remains, its directory is the best available scope.
                matching = [
                    key for key, item in records.items()
                    if item.run_id == run_id and (not source_root or item.source_root == source_root or item.work_root == source_root)
                ]
                key = matching[0] if matching else (source_root, run_id)
                record = records.setdefault(key, _RunRecord(source_root=source_root, run_id=run_id))
                record.events.append(event)
                if not record.workflow_id:
                    record.workflow_id = _text(event.get("workflow_id"))
                if not record.revision:
                    try:
                        record.revision = int(event.get("workflow_revision") or 0)
                    except (TypeError, ValueError):
                        record.revision = 0
                payload = _mapping(event.get("payload"))
                descriptor = _mapping(payload.get("descriptor")) or payload
                if event.get("kind") == "run.started" and not record.thread_id:
                    record.thread_id = _text(payload.get("thread_id") or payload.get("threadId"))
                if event.get("kind") == "wait.created":
                    if not record.thread_id:
                        record.thread_id = _text(descriptor.get("thread_id") or descriptor.get("threadId"))
                    if not record.workflow_id:
                        record.workflow_id = _text(descriptor.get("workflow_id") or descriptor.get("workflowId"))
                    if not record.work_root:
                        record.work_root = source_root

        # Custom event adapters may only support list(run_id).  Fill journals
        # for snapshot runs without duplicating events already discovered.
        for store in self.event_stores:
            source_root = _store_root(store)
            for key, record in list(records.items()):
                if record.events:
                    continue
                if record.run_id == "":
                    continue
                events = await _list_events(store, record.run_id)
                if events:
                    record.events = [_event_dict(item) for item in events]
                    if not record.source_root:
                        record.source_root = source_root
        for record in records.values():
            record.events.sort(key=_event_sort_key)
            if not record.work_root:
                record.work_root = record.source_root
            if not record.thread_id:
                # Snapshot records normally have this field; keep task lookup
                # deterministic for old journals that omitted it.
                started = next((e for e in record.events if e.get("kind") == "run.started"), {})
                record.thread_id = _text(_mapping(started.get("payload")).get("thread_id"))
        # ``records`` is keyed by (source_root, run_id); hydrate the record
        # values, not the mapping iterator's tuple keys.  Passing the mapping
        # itself makes ``_hydrate_definitions`` receive tuples and breaks the
        # live human-task list before any approval can be shown.
        await self._hydrate_definitions(records.values())
        return sorted(records.values(), key=lambda item: (item.work_root, item.run_id))

    async def _hydrate_definitions(self, records: Iterable[_RunRecord]) -> None:
        """Recover display metadata for completed runs after snapshot cleanup."""

        if self.workflow_store is None:
            return
        by_root: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            if record.definition and record.workflow_name:
                continue
            root = record.work_root or record.source_root
            if root not in by_root:
                method = getattr(self.workflow_store, "list", None)
                if not callable(method):
                    by_root[root] = []
                else:
                    try:
                        values = await _maybe_await(method(work_root=root or None))
                    except (TypeError, ValueError, OSError):
                        values = []
                    by_root[root] = [_mapping(item) for item in values] if isinstance(values, (list, tuple)) else []
            candidates = by_root[root]
            match = next(
                (
                    item
                    for item in candidates
                    if (
                        record.workflow_id
                        and _text(item.get("id")) == record.workflow_id
                    )
                    or (
                        record.workflow_name
                        and _text(item.get("name")) == record.workflow_name
                    )
                ),
                None,
            )
            if match is not None:
                record.definition = match
                record.workflow_name = record.workflow_name or _text(match.get("name"))
                record.workflow_id = record.workflow_id or _text(match.get("id"))

    @staticmethod
    def _scope_matches(record: _RunRecord, root: str, include_all: bool) -> bool:
        if include_all or not root:
            return True
        candidate = _resolved_root(record.work_root or record.source_root)
        return candidate == root

    async def _project(self) -> list[_TaskRecord]:
        records = await self._records()
        projected: list[_TaskRecord] = []
        for record in records:
            definition_nodes = _node_map(record.definition)
            result_states = _mapping(record.result.get("node_states"))
            descriptors: dict[str, dict[str, Any]] = {}
            # Current paused state is the primary source for pending tasks.
            root_descriptor = _mapping(record.result.get("wait_descriptor"))
            if root_descriptor:
                node_id = _text(root_descriptor.get("node_id") or root_descriptor.get("nodeId"))
                if node_id:
                    descriptors[node_id] = root_descriptor
            for node_id, raw_state in result_states.items():
                state = _mapping(raw_state)
                descriptor = _mapping(state.get("wait_descriptor") or state.get("waitDescriptor"))
                if descriptor:
                    descriptors[_text(descriptor.get("node_id") or node_id)] = descriptor

            signal_by_node: dict[str, dict[str, Any]] = {}
            created_events: list[dict[str, Any]] = []
            for event in record.events:
                kind = _text(event.get("kind"))
                payload = _mapping(event.get("payload"))
                if kind == "wait.created":
                    descriptor = _mapping(payload.get("descriptor")) or payload
                    node_id = _text(event.get("node_id") or descriptor.get("node_id") or descriptor.get("nodeId"))
                    if node_id:
                        descriptors.setdefault(node_id, descriptor)
                    created_events.append(event)
                elif kind == "wait.signalled":
                    node_id = _text(event.get("node_id") or payload.get("node_id") or payload.get("nodeId"))
                    if node_id:
                        signal_by_node[node_id] = event

            # A malformed/torn descriptor should not create a task without a
            # stable node identity.  The event journal remains available via
            # the run audit for diagnosis.
            for node_id, descriptor in descriptors.items():
                if not node_id:
                    continue
                node = definition_nodes.get(node_id, {})
                state = _mapping(result_states.get(node_id))
                signal_event = signal_by_node.get(node_id)
                outcome: dict[str, Any] | None = None
                completed_at: str | None = None
                if signal_event is not None:
                    payload = _mapping(signal_event.get("payload"))
                    candidate = payload.get("result")
                    outcome = _mapping(candidate) if isinstance(candidate, Mapping) else None
                    completed_at = _iso(signal_event.get("occurred_at"))
                    status = _status_from_outcome(_mapping(outcome).get("status") if outcome else "completed")
                else:
                    state_status = _text(state.get("status")).lower()
                    state_output = _mapping(state.get("output"))
                    terminal = next(
                        (event for event in reversed(record.events) if _text(event.get("kind")).startswith("run.")),
                        None,
                    )
                    terminal_kind = _text(terminal.get("kind") if terminal else "")
                    terminal_status = terminal_kind.split(".", 1)[1] if "." in terminal_kind else ""
                    run_status = _text(record.result.get("status")).lower()
                    if terminal_status in {"failed", "cancelled"}:
                        status = terminal_status
                        completed_at = _iso(terminal.get("occurred_at") if terminal else None)
                    elif run_status in {"failed", "cancelled"}:
                        status = run_status
                        completed_at = _iso(record.result.get("finished_at") or record.result.get("finishedAt"))
                    elif state_status in {"waiting", "pending"} or run_status == "paused":
                        status = "pending"
                    elif state_status in {"done", "completed"} or state_output.get("status"):
                        outcome = state_output or None
                        status = "completed"
                        completed_at = _iso(state.get("finished_at") or state.get("finishedAt"))
                    else:
                        status = terminal_kind.split(".", 1)[1] if "." in terminal_kind else "pending"
                        if status in {"started", "running", "paused", ""}:
                            status = "pending"
                        else:
                            completed_at = _iso(terminal.get("occurred_at") if terminal else None)
                # Preserve descriptor metadata from ``wait.created`` when the
                # snapshot's descriptor was a legacy minimal shape.
                if not descriptor.get("event_type") and signal_event:
                    descriptor = {**descriptor, "event_type": _mapping(signal_event.get("payload")).get("event_type")}
                task_id = f"{record.run_id}:{node_id}"
                projected.append(
                    _TaskRecord(
                        task_id=task_id,
                        run=record,
                        node_id=node_id,
                        descriptor=descriptor,
                        node=node,
                        status=status,
                        outcome=outcome,
                        completed_at=completed_at,
                    )
                )
        # A repeated wait-created event for the same run/node is one task.  Use
        # the latest projection because it contains the most recent outcome.
        unique: dict[tuple[str, str], _TaskRecord] = {}
        for task in projected:
            unique[(task.run.run_id, task.node_id)] = task
        return sorted(unique.values(), key=lambda item: (item.run.work_root, item.run.run_id, item.node_id))

    async def list(
        self,
        *,
        work_root: str | Path | None = None,
        include_all: bool = False,
        status: str | None = "pending",
        workflow_id: str = "",
        workflow_name: str = "",
        thread_id: str = "",
        limit: int | None = 100,
        include_audit: bool = False,
    ) -> list[dict[str, Any]]:
        root = _resolved_root(work_root) or self.work_root
        requested = _text(status).lower() or "pending"
        if requested in {"all", "*"}:
            requested = ""
        tasks = []
        for task in await self._project():
            if not self._scope_matches(task.run, root, include_all):
                continue
            if requested and task.status != requested:
                continue
            if workflow_id and task.run.workflow_id != _text(workflow_id):
                continue
            if workflow_name and task.run.workflow_name != _text(workflow_name):
                continue
            if thread_id and task.run.thread_id != _text(thread_id):
                continue
            tasks.append(task.to_dict(include_audit=include_audit))
        if limit is None:
            return tasks
        try:
            count = max(0, int(limit))
        except (TypeError, ValueError):
            count = 100
        return tasks[:count]

    async def get(
        self,
        task_id: str,
        *,
        work_root: str | Path | None = None,
        include_all: bool = False,
    ) -> dict[str, Any] | None:
        target = _text(task_id)
        if not target:
            return None
        root = _resolved_root(work_root) or self.work_root
        for task in await self._project():
            if task.task_id == target and self._scope_matches(task.run, root, include_all):
                return task.to_dict(include_audit=True)
        return None

    async def _find_private(
        self,
        task_id: str,
        *,
        work_root: str | Path | None = None,
        include_all: bool = False,
    ) -> _TaskRecord | None:
        target = _text(task_id)
        root = _resolved_root(work_root) or self.work_root
        for task in await self._project():
            if task.task_id == target and self._scope_matches(task.run, root, include_all):
                return task
        return None

    async def complete(
        self,
        task_id: str,
        *,
        decision: str = "",
        payload: Mapping[str, Any] | None = None,
        work_root: str | Path | None = None,
        include_all: bool = False,
    ) -> dict[str, Any]:
        task = await self._find_private(task_id, work_root=work_root, include_all=include_all)
        if task is None:
            raise LookupError(f"Human task not found: {task_id}")
        before_status = task.status
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be an object")
        safe_payload = dict(payload)
        if before_status == "pending":
            if self.runner is None or not callable(getattr(self.runner, "signal", None)):
                raise RuntimeError("workflow signal runner is not configured")
            event_type = _text(task.descriptor.get("event_type") or task.descriptor.get("eventType") or "event")
            result = await _maybe_await(
                self.runner.signal(
                    thread_id=task.run.thread_id,
                    run_id=task.run.run_id,
                    resume_token=task.resume_token,
                    event_type=event_type,
                    payload=safe_payload,
                    decision=_text(decision),
                )
            )
            projected = await self._find_private(task_id, work_root=work_root, include_all=include_all)
            if projected is not None and projected.status != "pending":
                task = projected
            else:
                # An embedded test/host runner may acknowledge the signal
                # without writing the journal synchronously.  Return a
                # truthful completed projection for this response; subsequent
                # reads still use durable state.
                task.status = "completed"
                task.outcome = {
                    "status": "approved" if _text(decision).lower() == "approve" else "rejected" if _text(decision).lower() == "reject" else "received",
                    "event_type": event_type,
                    "payload": safe_payload,
                }
            return {
                "task": task.to_dict(include_audit=True),
                "run": _safe(result),
                "idempotent": False,
            }

        # Terminal task completion is an idempotent read.  In particular, do
        # not ask callers to recover or resend a bearer token from an old UI.
        return {
            "task": task.to_dict(include_audit=True),
            "run": None,
            "idempotent": True,
        }

    async def timeout(
        self,
        task_id: str,
        *,
        work_root: str | Path | None = None,
        include_all: bool = False,
    ) -> dict[str, Any]:
        """Resolve a due task with the runner's normal signal contract.

        Arrange invokes this operation without a resume token.  The token is
        read only from the durable snapshot here, and a task that was already
        completed is an idempotent no-op.
        """

        task = await self._find_private(task_id, work_root=work_root, include_all=include_all)
        if task is None:
            return {"task": None, "timed_out": False, "idempotent": True}
        if task.status != "pending":
            return {"task": task.to_dict(include_audit=True), "timed_out": False, "idempotent": True}
        deadline = _parse_dt(
            task.descriptor.get("deadline")
            or task.descriptor.get("due_at")
            or task.descriptor.get("dueAt")
        )
        now = self.clock()
        if deadline is None or now < deadline:
            return {
                "task": task.to_dict(include_audit=True),
                "timed_out": False,
                "not_due": True,
                "idempotent": False,
            }
        if self.runner is None or not callable(getattr(self.runner, "signal", None)):
            raise RuntimeError("workflow signal runner is not configured")
        event_type = _text(task.descriptor.get("event_type") or task.descriptor.get("eventType") or "event")
        result = await _maybe_await(
            self.runner.signal(
                thread_id=task.run.thread_id,
                run_id=task.run.run_id,
                resume_token=task.resume_token,
                event_type=event_type,
                payload={},
                decision="",
            )
        )
        projected = await self._find_private(task_id, work_root=work_root, include_all=include_all)
        if projected is not None and projected.status != "pending":
            task = projected
        else:
            task.status = "completed"
            task.outcome = {"status": "timed_out", "event_type": event_type, "payload": None}
        return {
            "task": task.to_dict(include_audit=True),
            "run": _safe(result),
            "timed_out": True,
            "idempotent": False,
        }


def task_scope(payload: Mapping[str, Any], *, default_work_root: str = "") -> tuple[str, bool]:
    """Normalize the public scope contract used by RPC and CLI adapters."""

    raw_root = payload.get("work_root", payload.get("workRoot", default_work_root))
    all_scopes = _truthy(payload.get("all")) or _truthy(payload.get("include_all")) or _truthy(payload.get("includeAll"))
    return _resolved_root(raw_root), all_scopes


__all__ = [
    "HumanTaskCenter",
    "task_scope",
]
