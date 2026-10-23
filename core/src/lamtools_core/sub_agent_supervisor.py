"""Process-owned, durable sub-agent lifecycle and mailbox supervision."""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import inspect
import json
import logging
import re
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

from lamtools_core.config.model_store import ModelStore
from lamtools_core.llm import REASONING_LEVELS
from lamtools_core.runtime_owner import (
    LIVE_RUN_STATES,
    is_own_token,
    owner_is_live,
    owner_token,
    read_owner,
)

_logger = logging.getLogger(__name__)

#: A member run that exceeds this wall-clock budget is presumed hung.  The
#: watchdog (every 15s) marks it failed and notifies the parent; without a
#: bound a blocked provider call kept a member "running" indefinitely.
SUB_AGENT_MAX_RUN_SECONDS = 2 * 60 * 60

#: Upper bounds for member work.  A per-session cap keeps one supervisor from
#: spawning an unbounded number of model calls; the registry cap bounds how
#: many idle supervisors (each with a runner and MCP registry) stay resident.
SUB_AGENT_MAX_CONCURRENT_RUNS = 8
SUB_AGENT_MAX_SUPERVISORS = 64

SUB_AGENT_TYPES = ("consider", "execute")
# 允许中文名字（例如「张前端」这类稳定称呼），仍须以小写拉丁字母或汉字开头。
SUB_AGENT_NAME_PATTERN = re.compile(r"^[a-z\u4e00-\u9fff][a-z0-9_\u4e00-\u9fff]{0,63}$")
_REASONING_ALIASES = {"xh": "xhigh"}

#: Optional process-wide sink that mirrors every durable member record into the
#: turn-control read model (``core_agent_runs``). It is a projection, not a
#: second authority: ``sub_agents.sqlite3`` still owns mailboxes and recovery,
#: while snapshots/recovery can query one cross-thread table.
_agent_run_store_factory: Callable[[], Any] | None = None


def set_agent_run_store_factory(factory: Callable[[], Any] | None) -> None:
    global _agent_run_store_factory
    _agent_run_store_factory = factory


def _agent_run_from_record(parent_thread_id: str, record: "SubAgentRecord") -> Any:
    from .turn.model import AgentRun

    turn_id = str(record.source_turn_id or "")
    if not turn_id and record.source_run_id:
        turn_id = f"{parent_thread_id}:turn:{record.source_run_id}"
    if not turn_id:
        turn_id = f"{parent_thread_id}:turn:member:{record.name}"
    return AgentRun(
        agent_run_id=f"{parent_thread_id}:agent:{record.name}",
        parent_turn_id=turn_id,
        parent_thread_id=parent_thread_id,
        parent_run_id=str(record.source_run_id or ""),
        name=record.name,
        type=record.type,
        model_id=record.model_id,
        reasoning_level=record.reasoning_level,
        status=record.status,  # type: ignore[arg-type]
        lease_until_ms=int(record.lease_until * 1000) if record.lease_until else 0,
        sub_session_id=record.sub_session_id,
        source_call_id=record.source_call_id,
        source_run_id=record.source_run_id,
        source_turn_id=record.source_turn_id,
        summary=record.summary,
        started_at_ms=int(record.started_at * 1000) if record.started_at else 0,
        completed_at_ms=int(record.completed_at * 1000) if record.completed_at else 0,
        elapsed_ms=int(record.elapsed_ms or 0),
        metadata={"runtime_owner": dict(record.runtime_owner or {})},
    )
_child_identity: contextvars.ContextVar[tuple["SubAgentSupervisor", str, str] | None] = (
    contextvars.ContextVar("lamtools_sub_agent_identity", default=None)
)
_child_invocation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "lamtools_sub_agent_invocation_id", default=""
)


@dataclass
class SubAgentRecord:
    parent_thread_id: str
    type: str
    name: str
    model_id: str
    reasoning_level: str
    status: str
    summary: str = ""
    started_at: float | None = None
    completed_at: float | None = None
    elapsed_ms: int | None = None
    sub_session_id: str = ""
    source_call_id: str = ""
    source_run_id: str = ""
    source_turn_id: str = ""
    source_message_id: str = ""
    source_part_id: str = ""
    runtime_owner: dict[str, Any] = field(default_factory=dict)
    #: Absolute wall-clock deadline for the current run.  A member with no
    #: lease never expires; a run that exceeds it is marked failed by the
    #: watchdog instead of showing "running" forever.
    lease_until: float = 0.0
    # user:“修 问题严重的话 就重新设计”+(每次执行与控制动作使用持久令牌，使旧结果失去写入权)。
    execution_token: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SubAgentOperationResult:
    """Transient lifecycle semantics paired with a durable sub-agent record."""

    record: SubAgentRecord
    lifecycle_action: Literal["created", "enabled", "closed", "deleted"]

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.record.to_dict(),
            "lifecycle_action": self.lifecycle_action,
        }


def validate_name(value: object) -> str:
    name = str(value or "")
    if not SUB_AGENT_NAME_PATTERN.fullmatch(name):
        raise ValueError("name must match ^[a-z][a-z0-9_]{0,63}$")
    return name


def validate_type(value: object) -> str:
    candidate = str(value or "")
    if candidate not in SUB_AGENT_TYPES:
        raise ValueError("type must be exactly 'consider' or 'execute'")
    return candidate


def validate_reasoning(value: object) -> str:
    normalized = str(value or "").strip().lower()
    candidate = _REASONING_ALIASES.get(normalized, normalized)
    if candidate not in REASONING_LEVELS:
        raise ValueError("reasoning_level must be one of off, light, medium, high, xhigh, max")
    return candidate


def _display_keys(model: Any) -> set[str]:
    """Case-folded human-facing labels a model may be referred to by.

    The label the running agent actually sees is the ``<provider>/<display_name>``
    form rendered by the desktop model-display resolver, so the bare display
    name, the provider-prefixed label and the provider_id-prefixed label are all
    accepted as display references.  Labels are compared case-insensitively
    because models commonly echo them lower-cased; uniqueness still decides
    between a single hit and an ambiguous rejection.
    """
    display = (model.display_name or "").strip()
    if not display:
        return set()
    keys = {display}
    provider = (model.provider or "").strip()
    if provider:
        keys.add(f"{provider}/{display}")
    provider_id = (model.provider_id or "").strip()
    if provider_id:
        keys.add(f"{provider_id}/{display}")
    return {key.casefold() for key in keys}


def _model_option_label(model: Any) -> str:
    """Render one selectable model as ``"<real model_id>" (<display label>)``.

    The real model id leads because that is the value the caller should use;
    the display label is kept only as a human-readable note.
    """
    real_id = model.model_id or model.id
    display = (model.display_name or "").strip()
    provider = (model.provider or model.provider_id or "").strip()
    label = f"{provider}/{display}" if provider and display else display
    if label and label != real_id:
        return f'"{real_id}" ({label})'
    return f'"{real_id}"'


def _available_models_hint(models: list[Any], *, limit: int = 50) -> str:
    """Comma-separated selectable model ids (display labels in parentheses)."""
    options = [_model_option_label(model) for model in models[:limit]]
    text = ", ".join(options)
    if len(models) > limit:
        text += f", …(+{len(models) - limit} more)"
    return text


def resolve_model_id(value: object, *, work_root: str | Path | None = None) -> str:
    """Resolve a model reference to the canonical real ``model_id``.

    Order: an exact real model id (upstream ``model_id`` or record id) wins; a
    human-readable display label matches only when it identifies exactly one
    model.  An ambiguous label or an unknown reference fails with a message
    that lists the real model ids, so the caller can correct itself in one step
    instead of guessing again.
    """
    ref = str(value or "").strip()
    if not ref:
        raise ValueError("model is required")
    models = ModelStore().list_sync(work_root=str(work_root) if work_root else None)
    if not models:
        raise ValueError("model is required: no models are configured")
    # 1) Exact real model id (upstream model_id or the record id) — highest priority.
    exact = [model for model in models if ref == model.model_id or ref == model.id]
    if len(exact) == 1:
        return exact[0].model_id
    if len(exact) > 1:
        raise ValueError(
            f"model reference is ambiguous: {ref!r} matches "
            f"{len(exact)} models ({_available_models_hint(exact)}); "
            "use a unique model_id"
        )
    # 2) A display label may match (case-insensitively), but only when it is
    #    unambiguous; 3) a duplicated label is rejected with every colliding
    #    candidate listed.
    display = [model for model in models if ref.casefold() in _display_keys(model)]
    if len(display) == 1:
        return display[0].model_id
    if len(display) > 1:
        raise ValueError(
            f"model display label is ambiguous: {ref!r} matches "
            f"{len(display)} models ({_available_models_hint(display)}); "
            "use an exact model_id"
        )
    # 4) Nothing matched — hand back the selectable real model ids.
    raise ValueError(
        f"unknown model: {ref}. Available model IDs: {_available_models_hint(models)}"
    )


def _result_status(result: Any) -> str:
    decision = str(getattr(result, "decision", "done") or "done").strip().lower()
    error = str(getattr(result, "error", "") or "").strip().lower()
    if error == "paused":
        # The kernel parked this child on a session pause. ``paused`` is taken:
        # for a member it already means "parked at a human boundary" (a
        # question), and the two must stay distinguishable in the record.
        return "suspended"
    if decision == "wait":
        return "paused"
    if decision in {"cancelled", "canceled", "interrupted"}:
        return "interrupted"
    if decision in {"failed", "error"} or getattr(result, "error", ""):
        return "failed"
    return "idle"


def _owned_elsewhere(record: SubAgentRecord) -> bool:
    """Whether a live owner other than this process still runs the member.

    A record with no local drive task but this process's own owner token is not
    "owned elsewhere": this process already released the drive (Stop, close, or
    a finished run), so the member is free for takeover. Another host's or a
    different process's live token must still be refused.
    """
    return owner_is_live(record.runtime_owner) and not is_own_token(record.runtime_owner)


class SubAgentSupervisor:
    """Long-lived owner for one parent's named child agents.

    SQLite is deliberately separate from the turn checkpoint transaction: a
    parent turn can finish while a child continues, and mailbox writes must not
    depend on a soon-to-be-disposed turn/MCP registry.
    """

    def __init__(
        self,
        *,
        parent_thread_id: str,
        runner: Any,
        database_path: str | Path,
        agent_run_store: Any | None = None,
    ) -> None:
        self.parent_thread_id = str(parent_thread_id)
        self.runner = runner
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._agent_run_store = agent_run_store
        if self._agent_run_store is None and _agent_run_store_factory is not None:
            try:
                self._agent_run_store = _agent_run_store_factory()
            except BaseException:
                self._agent_run_store = None
        self._agent_run_tasks: set[asyncio.Task[Any]] = set()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        # Member runs executed inline by the caller (an answered question or
        # approval continuation). They are not drive tasks, but a Stop must be
        # able to cancel them like any other member work.
        self._inline_tasks: dict[str, asyncio.Task[Any]] = {}
        # Serializes every writer of one child session: drive tasks, answered
        # questions and approval continuations.  The runner's own lock is per
        # runner instance, and a continuation is built from a different runner,
        # so it cannot provide this guarantee.
        self._agent_locks: dict[str, asyncio.Lock] = {}
        self._run_semaphore = asyncio.Semaphore(SUB_AGENT_MAX_CONCURRENT_RUNS)
        self._resume_names: set[str] = set()
        self._pending_prompts: dict[str, str] = {}
        # Continuation text for a scheduled resume. ``None`` means "use the
        # runner's default (interruption-aware) text"; a user pause schedules
        # ``""`` for a pure continuation from committed history.
        self._resume_prompts: dict[str, str | None] = {}
        # Session-level pause signal shared with every child kernel this
        # supervisor drives. Set = the user paused the session; cleared = the
        # session continues.
        self._pause_event: asyncio.Event | None = None
        # Mailbox rows are the queue. These sets only reserve offers within one
        # invocation; unacknowledged rows survive process exit/checkpoint failure.
        self._offered_mail: dict[str, set[str]] = {}
        self._initial_mail_ids: dict[str, list[str]] = {}
        self._provider_messages_by_invocation: dict[str, set[str]] = {}
        self._closed = False
        self._owned_runner: Any | None = None
        # Session-scoped activity signal: set on every member state change that a
        # parent run may be waiting for (completion, failure, close, orphan).
        self._activity = asyncio.Event()
        # The turn whose "members still running" fact is currently published
        # (recorded by the kernel loop when it publishes it at a turn terminal),
        # so the fact can be retracted for that same turn once the last member
        # it named finishes. Empty when no such fact is outstanding.
        self._member_wait_turn_id = ""
        self._init_db()

    def update_runner(self, runner: Any) -> None:
        self.runner = runner

    def execution_token(self, name: str) -> str:
        return self._required(validate_name(name)).execution_token

    def result_is_current(self, name: str, token: str) -> bool:
        record = self._load(validate_name(name))
        return bool(record and record.execution_token == token
                    and record.status not in {"terminated", "closed", "deleted"})

    def agent_lock(self, name: str) -> asyncio.Lock:
        key = str(name or "")
        lock = self._agent_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._agent_locks[key] = lock
        return lock

    def has_active_work(self) -> bool:
        return any(not task.done() for task in self._tasks.values()) or any(
            not task.done() for task in self._inline_tasks.values()
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """A short-lived connection that commits (or rolls back) **and closes**.

        sqlite3's own connection context manager only commits — it never closes
        the handle — so ``with self._connect() as db`` leaked one connection per
        call, for the life of the process (2026-09-25 audit P3).
        """
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._connection() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS sub_agents (
                  parent_thread_id TEXT NOT NULL, name TEXT NOT NULL, payload TEXT NOT NULL,
                  PRIMARY KEY(parent_thread_id, name)
                )
                """
            )
            mailbox_columns = {
                str(row["name"])
                for row in db.execute("PRAGMA table_info(sub_agent_mailbox)").fetchall()
            }
            if mailbox_columns and "message_key" not in mailbox_columns:
                db.execute("ALTER TABLE sub_agent_mailbox RENAME TO sub_agent_mailbox_legacy")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS sub_agent_mailbox (
                  id TEXT PRIMARY KEY, parent_thread_id TEXT NOT NULL, name TEXT NOT NULL,
                  direction TEXT NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL,
                  message_key TEXT NOT NULL, created_at REAL NOT NULL, delivered_at REAL,
                  UNIQUE(parent_thread_id, name, direction, message_key)
                )
                """
            )
            if mailbox_columns and "message_key" not in mailbox_columns:
                db.execute(
                    """
                    INSERT OR IGNORE INTO sub_agent_mailbox(
                      id,parent_thread_id,name,direction,body,digest,message_key,created_at,delivered_at
                    )
                    SELECT id,parent_thread_id,name,direction,body,digest,id,created_at,delivered_at
                    FROM sub_agent_mailbox_legacy
                    """
                )
                db.execute("DROP TABLE sub_agent_mailbox_legacy")
            # 成员状态变化事件：与「成员来信」邮箱分开存放，避免改变既有
            # 邮箱语义；事件按 event_key 幂等，投递状态由 delivered_at 记录。
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS sub_agent_events (
                  id TEXT PRIMARY KEY, parent_thread_id TEXT NOT NULL, name TEXT NOT NULL,
                  payload TEXT NOT NULL, event_key TEXT NOT NULL, created_at REAL NOT NULL,
                  delivered_at REAL,
                  UNIQUE(parent_thread_id, event_key)
                )
                """
            )

    async def recover(self) -> None:
        """Converge orphaned process-owned work after application restart."""
        interrupted: list[SubAgentRecord] = []
        async with self._lock:
            # The registry is shared with CLI/other hosts. Never reap work still
            # owned by a live process, including the pre-kernel launch boundary.
            with self._connection() as db:
                candidates = db.execute(
                    "SELECT name,payload FROM sub_agents WHERE parent_thread_id=?",
                    (self.parent_thread_id,),
                ).fetchall()
            live_names: set[str] = set()
            store = getattr(self.runner, "state_store", None)
            for row in candidates:
                payload = json.loads(row["payload"])
                owner = payload.get("runtime_owner") or {}
                if not owner and store is not None and payload.get("sub_session_id"):
                    state = await store.get(payload["sub_session_id"])
                    owner = read_owner(getattr(state, "metadata", {}))
                if owner_is_live(owner):
                    live_names.add(row["name"])
            with self._connection() as db:
                rows = db.execute(
                    "SELECT name,payload FROM sub_agents WHERE parent_thread_id=?",
                    (self.parent_thread_id,),
                ).fetchall()
                for row in rows:
                    payload = json.loads(row["payload"])
                    if (payload.get("status") == "running" and row["name"] not in live_names
                            and not owner_is_live(payload.get("runtime_owner"))):
                        payload["status"] = "interrupted"
                        payload["completed_at"] = time.time()
                        if payload.get("started_at"):
                            payload["elapsed_ms"] = int((payload["completed_at"] - payload["started_at"]) * 1000)
                        db.execute(
                            "UPDATE sub_agents SET payload=? WHERE parent_thread_id=? AND name=?",
                            (json.dumps(payload), self.parent_thread_id, row["name"]),
                        )
                        interrupted.append(SubAgentRecord(**payload))
        # 事件写入放在连接释放之后：独立连接不会与外层写事务互相锁住。
        for record in interrupted:
            await self._record_member_event(record, "member_interrupted", detail="进程重启时该成员仍在运行")
        # user:“主子代理控制关系持久保存，重启后仍可完整恢复”+重启对账建出来的
        # 监督器就是本进程的成员所有者；登记它是为了让恢复入口按持久记录找到人，
        # 而不是碰运气看启动时是否恰好缓存过这个会话（AR-03）。
        _remember_supervisor(self)

    async def create(self, *, type: object, name: object, model: object,
                     reasoning_level: object, source_ids: dict[str, str] | None = None) -> SubAgentRecord:
        result = await self.create_operation(
            type=type,
            name=name,
            model=model,
            reasoning_level=reasoning_level,
            source_ids=source_ids,
        )
        return result.record

    async def create_operation(
        self,
        *,
        type: object,
        name: object,
        model: object,
        reasoning_level: object,
        source_ids: dict[str, str] | None = None,
    ) -> SubAgentOperationResult:
        child_type = validate_type(type)
        child_name = validate_name(name)
        model_id = resolve_model_id(model, work_root=getattr(self.runner, "work_root", None))
        reasoning = validate_reasoning(reasoning_level)
        desired = (child_type, child_name, model_id, reasoning)
        async with self._lock:
            existing = self._load(child_name)
            if existing and existing.status not in {"closed", "interrupted", "terminated", "failed"}:
                current = (existing.type, existing.name, existing.model_id, existing.reasoning_level)
                if current != desired:
                    raise ValueError("active sub-agent exists with a different configuration")
                self._refresh_source(existing, source_ids)
                self._save(existing)
                return SubAgentOperationResult(existing, "enabled")
            if existing:
                current = (existing.type, existing.name, existing.model_id, existing.reasoning_level)
                if current != desired:
                    raise ValueError("closed sub-agent can only be reopened with its exact configuration")
            ids = source_ids or {}
            source_turn_id = str(ids.get("turn_id") or "")
            source_run_id = str(ids.get("run_id") or "")
            previous = existing or SubAgentRecord(
                parent_thread_id=self.parent_thread_id,
                type=child_type,
                name=child_name,
                model_id=model_id,
                reasoning_level=reasoning,
                status="idle",
            )
            record = SubAgentRecord(
                parent_thread_id=self.parent_thread_id, type=child_type, name=child_name,
                model_id=model_id, reasoning_level=reasoning, status="idle",
                summary=previous.summary,
                sub_session_id=f"{self.parent_thread_id}:sub:{child_name}",
                source_call_id=str(ids.get("call_id") or previous.source_call_id),
                source_run_id=source_run_id or previous.source_run_id,
                source_turn_id=source_turn_id or previous.source_turn_id,
                source_message_id=str(
                    ids.get("message_id")
                    or (f"assistant:{source_turn_id}" if source_turn_id else "")
                    or (f"assistant:{source_run_id}" if source_run_id else "")
                    or previous.source_message_id
                ),
                source_part_id=str(
                    ids.get("part_id")
                    or (f"part-{ids.get('call_id')}" if ids.get("call_id") else "")
                    or previous.source_part_id
                ),
            )
            self._refresh_source(record, ids)
            self._save(record)
            return SubAgentOperationResult(record, "enabled" if existing else "created")

    def _refresh_source(
        self,
        record: SubAgentRecord,
        source_ids: dict[str, str] | None,
    ) -> None:
        """Bind a lifecycle/message action to its current parent source."""
        ids = source_ids or {}
        call_id = str(ids.get("call_id") or "")
        run_id = str(ids.get("run_id") or "")
        turn_id = str(ids.get("turn_id") or "")
        if call_id:
            record.source_call_id = call_id
            source_boundary = run_id or turn_id
            record.source_part_id = str(
                ids.get("part_id")
                or (
                    f"{self.parent_thread_id}:{source_boundary}:{call_id}:tool"
                    if source_boundary
                    else f"part-{call_id}"
                )
            )
        elif ids.get("part_id"):
            record.source_part_id = str(ids["part_id"])
        if run_id:
            record.source_run_id = run_id
        if turn_id:
            record.source_turn_id = turn_id
        message_id = str(ids.get("message_id") or "")
        if message_id:
            record.source_message_id = message_id
        elif turn_id:
            record.source_message_id = f"assistant:{turn_id}"
        elif run_id:
            record.source_message_id = f"assistant:{run_id}"

    async def close(self, *, type: object, name: object, model: object,
                    reasoning_level: object,
                    source_ids: dict[str, str] | None = None) -> SubAgentRecord:
        result = await self.close_operation(
            type=type,
            name=name,
            model=model,
            reasoning_level=reasoning_level,
            source_ids=source_ids,
        )
        return result.record

    async def close_operation(
        self,
        *,
        type: object,
        name: object,
        model: object,
        reasoning_level: object,
        source_ids: dict[str, str] | None = None,
    ) -> SubAgentOperationResult:
        child_name = validate_name(name)
        child_type = validate_type(type)
        model_id = resolve_model_id(model, work_root=getattr(self.runner, "work_root", None))
        reasoning = validate_reasoning(reasoning_level)
        task: asyncio.Task[None] | None = None
        async with self._lock:
            record = self._required(child_name)
            if (record.type, record.model_id, record.reasoning_level) != (child_type, model_id, reasoning):
                raise ValueError("close configuration does not match the durable sub-agent record")
            self._refresh_source(record, source_ids)
            previous_status = record.status
            record.status = "closed"
            if previous_status == "running":
                record.completed_at = time.time()
                if record.started_at:
                    record.elapsed_ms = int((record.completed_at - record.started_at) * 1000)
            elif record.completed_at is None:
                record.completed_at = time.time()
                record.elapsed_ms = record.elapsed_ms or 0
            self._save(record)
            self._pending_prompts.pop(child_name, None)
            task = self._tasks.pop(child_name, None)
            inline = self._inline_tasks.pop(child_name, None)
            for candidate in (task, inline):
                if candidate and not candidate.done():
                    candidate.cancel()
            if inline and inline is not task:
                task = inline if task is None else task
            await self._record_member_event(record, "member_closed")
        if task:
            await asyncio.gather(task, return_exceptions=True)
        if inline and inline is not task:
            await asyncio.gather(inline, return_exceptions=True)
        return SubAgentOperationResult(record, "closed")

    async def delete(self, *, name: object) -> dict[str, Any]:
        return await self.delete_operation(name=name)

    async def delete_operation(self, *, name: object) -> dict[str, Any]:
        """Remove one sub-agent and everything that belongs to it alone.

        Scope is explicit. Removed: the member's own record, its lifecycle
        events and its mailbox in the sub-agent database, and its own session
        family in the application database — its runtime state, its full
        internal transcript, and any attachment it uploaded that no live library
        entry references. Protected (never candidates): the session's own
        conversation and summary, the parent session's checkpoints, the library,
        and every other member. The session's conversation and checkpoints live
        under the parent thread id, not the member's sub-session id, so they are
        outside the purge by construction.

        A running member is refused rather than cancelled: it may be producing
        the user's results, and ``close`` already exists as the explicit stop.
        Deleting rows out from under a live task is exactly the half-deleted
        state to avoid, so the caller stops the member first and then deletes.
        """
        child_name = validate_name(name)
        async with self._lock:
            record = self._load(child_name)
            if record is None:
                raise ValueError(f"sub-agent not found: {child_name}")
            task = self._tasks.get(child_name)
            inline = self._inline_tasks.get(child_name)
            if (
                record.status == "running"
                or (task is not None and not task.done())
                or (inline is not None and not inline.done())
                or child_name in self._pending_prompts
            ):
                raise ValueError(
                    f"sub-agent '{child_name}' is running; stop it first with "
                    "sub_agent close, then delete"
                )
            # Publish a durable deletion marker before removing the record.
            # The member's forwarded rows live under the parent thread and are
            # not part of the child-session purge; this fact lets the snapshot
            # and the interface hide that subtree on every later load.
            record.status = "deleted"
            self._mirror_agent_run(record)
            await self._record_member_event(record, "member_deleted")
            await self._publish_member_status(record, event="member_deleted")
            # Purge the member's own session family before the durable record is
            # removed: a failure here leaves the record in place for a retry
            # instead of orphaning rows nothing can find again.
            freed = await self._purge_sub_session(record)
            with self._connection() as db:
                db.execute(
                    "DELETE FROM sub_agents WHERE parent_thread_id=? AND name=?",
                    (self.parent_thread_id, child_name),
                )
                db.execute(
                    "DELETE FROM sub_agent_events WHERE parent_thread_id=? AND name=?",
                    (self.parent_thread_id, child_name),
                )
                db.execute(
                    "DELETE FROM sub_agent_mailbox WHERE parent_thread_id=? AND name=?",
                    (self.parent_thread_id, child_name),
                )
            self._pending_prompts.pop(child_name, None)
            self._tasks.pop(child_name, None)
            self._offered_mail.pop(child_name, None)
            self._initial_mail_ids.pop(child_name, None)
            return {
                **record.to_dict(),
                "lifecycle_action": "deleted",
                "freed_sub_session": freed,
            }

    async def _purge_sub_session(self, record: SubAgentRecord) -> bool:
        """Delete the member's own session family from the application database.

        Reuses the project's session-deletion cascade, which owns the library
        protection: an attachment referenced by a live library entry survives
        even though it belongs to the member's session. The parent thread's rows
        carry a different session id and are never in scope.
        """
        session_id = str(record.sub_session_id or "")
        if not session_id:
            return False
        store = getattr(self.runner, "state_store", None)
        coordinator = getattr(store, "write_coordinator", None)
        if coordinator is None:
            # No application database reachable through this runner (an
            # in-memory/legacy store), so there are no such rows to remove.
            return False
        from .app.core_session_store import delete_session_records

        async def purge(db: Any) -> None:
            await delete_session_records(db, [session_id])

        await coordinator.run(purge)
        return True

    async def message(self, *, type: object, name: object, prompt: object,
                      source_ids: dict[str, str] | None = None) -> dict[str, Any]:
        child_type = validate_type(type)
        child_name = validate_name(name)
        body = str(prompt or "").strip()
        if not body:
            raise ValueError("prompt is required")
        async with self._lock:
            record = self._required(child_name)
            if record.type != child_type or record.status in {
                "closed", "interrupted", "terminated", "failed"
            }:
                raise ValueError("sub-agent must exist, match type, and be active")
            task = self._tasks.get(child_name)
            if record.status == "running" and (task is None or task.done()) and owner_is_live(record.runtime_owner):
                raise ValueError("sub-agent is owned by another running process")
            self._refresh_source(record, source_ids)
            self._save(record)
            ids = source_ids or {}
            call_id = str(ids.get("call_id") or "")
            run_id = str(ids.get("run_id") or "")
            message_key = f"{run_id}:{call_id}" if call_id else uuid.uuid4().hex
            inserted = self._mail(child_name, "parent_to_child", body, message_key=message_key)
            with self._connection() as db:
                message_id = db.execute(
                    "SELECT id FROM sub_agent_mailbox WHERE parent_thread_id=? AND name=? "
                    "AND direction='parent_to_child' AND message_key=?",
                    (self.parent_thread_id, child_name, message_key),
                ).fetchone()["id"]
            if not inserted:
                return {
                    "accepted": True,
                    "deduplicated": True,
                    "message_id": message_id,
                    "type": child_type,
                    "name": child_name,
                    "lifecycle_action": "message_sent",
                }
            task = self._tasks.get(child_name)
            if task is not None and not task.done():
                publish_running = False
            else:
                record.status = "running"
                record.started_at = time.time()
                record.completed_at = None
                record.elapsed_ms = None
                record.lease_until = time.time() + SUB_AGENT_MAX_RUN_SECONDS
                record.runtime_owner = owner_token()
                self._save(record)
                self._queue_initial_mail(child_name)
                self._tasks[child_name] = asyncio.create_task(
                    self._drive(child_name), name=f"sub-agent:{self.parent_thread_id}:{child_name}"
                )
                publish_running = True
        if publish_running:
            # The member's own "running" transition, published while the parent
            # turn is still open (one event per transition).
            await self._publish_member_status(record, event="member_running")
        delivery_mode = "new_turn" if publish_running else "next_boundary"
        _logger.info("sub-agent message accepted parent=%s name=%s message_id=%s delivery=%s",
                     self.parent_thread_id, child_name, message_id, delivery_mode)
        return {
            "accepted": True,
            "deduplicated": False,
            "message_id": message_id,
            "delivery_mode": delivery_mode,
            "type": child_type,
            "name": child_name,
            "lifecycle_action": "message_sent",
        }

    def track_inline_task(self, name: object, task: asyncio.Task[Any] | None) -> str:
        """Register (or clear) a member run the caller executes inline.

        The approval/question continuation runs inside the caller's request, not
        in a drive task, so without this a Stop could not reach it.
        """
        child_name = str(name or "").strip()
        if not child_name:
            return ""
        if task is None:
            self._inline_tasks.pop(child_name, None)
        else:
            record = self._required(child_name)
            if record.status in {"terminated", "closed", "deleted"}:
                raise ValueError("Sub-agent was terminated")
            record.execution_token = uuid.uuid4().hex
            self._save(record)
            self._inline_tasks[child_name] = task
            return record.execution_token
        return ""

    async def interrupt_active(
        self, *, include_paused: bool = False, final_status: str | None = None
    ) -> list[dict[str, Any]]:
        """Interrupt every locally owned active child and return its records.

        The parent turn may already be terminal, so this operation deliberately
        targets the supervisor's member tasks instead of the parent runtime
        registry.  A user pause keeps members waiting on a question: that card
        is still the user's.  A user terminate is different — it promises to
        discard unanswered member questions, so ``include_paused`` also stops
        members parked at a human boundary and clears their durable request.
        """
        victims: list[SubAgentRecord] = []
        tasks: list[asyncio.Task[None]] = []
        async with self._lock:
            names = set(self._tasks)
            with self._connection() as db:
                rows = db.execute(
                    "SELECT name,payload FROM sub_agents WHERE parent_thread_id=?",
                    (self.parent_thread_id,),
                ).fetchall()
            for row in rows:
                record = SubAgentRecord(**json.loads(row["payload"]))
                task = self._tasks.get(record.name)
                active = record.status in {"running", "pending"} or (
                    task is not None and not task.done()
                )
                if include_paused and record.status in {"paused", "suspended", "interrupted"}:
                    active = True
                if not active:
                    continue
                if task is None and record.status == "running" and _owned_elsewhere(record):
                    raise ValueError(
                        f"sub-agent '{record.name}' is owned by another running process"
                    )
                # user:“终止不能复用可恢复的 interrupted”+用户终止写独立终态，
                # 只有崩溃重启留下的 interrupted 才允许被 Resume 复活。
                record.status = final_status or (
                    "terminated" if include_paused else "interrupted"
                )
                record.execution_token = uuid.uuid4().hex
                record.completed_at = time.time()
                if record.started_at:
                    record.elapsed_ms = int((record.completed_at - record.started_at) * 1000)
                self._save(record)
                self._pending_prompts.pop(record.name, None)
                self._initial_mail_ids.pop(record.name, None)
                self._offered_mail.pop(record.name, None)
                self._resume_names.discard(record.name)
                self._resume_prompts.pop(record.name, None)
                if task is not None and not task.done():
                    task.cancel()
                    tasks.append(task)
                inline = self._inline_tasks.pop(record.name, None)
                if inline is not None and not inline.done():
                    inline.cancel()
                    tasks.append(inline)
                self._tasks.pop(record.name, None)
                victims.append(record)
            # A stale task entry with no durable row must not keep the member
            # drain signal alive after a stop.
            for name in names - {record.name for record in victims}:
                task = self._tasks.get(name)
                if task is not None and task.done():
                    self._tasks.pop(name, None)
        for record in victims:
            await self._record_member_event(
                record, "member_interrupted", detail="用户停止了该子代理"
            )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if include_paused:
            for record in victims:
                await self._clear_child_pending(record.sub_session_id)
        # Cancellation persists through the kernel's detached cancel finalizer,
        # which can still be in flight when the task is gone. A Resume issued
        # right after Stop must not race that write, so Stop only reports done
        # once each child state has left the live set (bounded; the record
        # itself is already interrupted either way and the kernel adopts its
        # own stale run).
        await self._await_children_settled(victims)
        await self._maybe_report_members_drained()
        return [record.to_dict() for record in victims]

    async def _clear_child_pending(self, session_id: str) -> None:
        """Drop a parked member's durable question when the user terminates.

        A paused member keeps its card for a *pause*; a terminate promises to
        discard it.  Clearing the runtime request here also makes the backend
        auto-continue scheduler unable to resurrect the member later.
        """
        store = getattr(self.runner, "state_store", None)
        if store is None or not session_id:
            return
        try:
            state = await store.get(session_id)
        except BaseException:
            _logger.exception("[sub-agent] could not read child state %s", session_id)
            return
        if state is None or not isinstance(getattr(state, "metadata", None), dict):
            return
        if "pending_approval" not in state.metadata and "pending_waiting_request" not in state.metadata:
            return
        state.metadata.pop("pending_approval", None)
        state.metadata.pop("pending_waiting_request", None)
        try:
            await store.save(state)
        except BaseException:
            _logger.exception("[sub-agent] could not clear child pending %s", session_id)

    async def expire_lease(self, name: str) -> dict[str, Any] | None:
        """Stop a member whose run exceeded the wall-clock lease.

        Without this a blocked provider call showed as "running" forever: the
        user had no signal and no automatic recovery.  The failure is recorded
        as a member event so the parent can be woken with the explanation.
        """
        child_name = validate_name(name)
        task: asyncio.Task[Any] | None = None
        inline: asyncio.Task[Any] | None = None
        async with self._lock:
            record = self._load(child_name)
            if record is None or record.status != "running":
                return None
            if not record.lease_until or time.time() <= record.lease_until:
                return None
            record.status = "failed"
            record.summary = "Sub-agent execution exceeded its lease and was stopped."
            record.completed_at = time.time()
            record.lease_until = 0.0
            if record.started_at:
                record.elapsed_ms = int((record.completed_at - record.started_at) * 1000)
            self._save(record)
            task = self._tasks.pop(child_name, None)
            inline = self._inline_tasks.pop(child_name, None)
            for candidate in (task, inline):
                if candidate is not None and not candidate.done():
                    candidate.cancel()
        for candidate in (task, inline):
            if candidate is not None:
                await asyncio.gather(candidate, return_exceptions=True)
        await self._record_member_event(
            record, "member_failed", detail="lease_expired"
        )
        await self._publish_member_status(record, event="member_failed")
        return record.to_dict()

    async def _await_children_settled(
        self, records: list[SubAgentRecord], *, timeout: float = 3.0
    ) -> None:
        store = getattr(self.runner, "state_store", None)
        pending = [record.sub_session_id for record in records if record.sub_session_id]
        if store is None or not pending:
            return
        deadline = time.monotonic() + timeout
        while pending and time.monotonic() < deadline:
            remaining: list[str] = []
            for session_id in pending:
                try:
                    state = await store.get(session_id)
                except BaseException:
                    continue
                if state is not None and state.status in LIVE_RUN_STATES:
                    remaining.append(session_id)
            pending = remaining
            if pending:
                await asyncio.sleep(0.025)

    @property
    def pause_event(self) -> asyncio.Event:
        """Session pause signal shared by every child kernel of this session."""
        if self._pause_event is None:
            self._pause_event = asyncio.Event()
        return self._pause_event

    async def pause_active(self, *, control_guard: Callable[[], bool] | None = None) -> list[dict[str, Any]]:
        """Park every locally owned active child without killing its work.

        The mirror image of :meth:`interrupt_active`: the child kernel observes
        the shared pause event, drops the step it is in, and keeps a resumable
        state; its record moves to ``suspended`` so the session can continue it
        later. Children parked on a question stay where they are: that card is
        still the user's to answer, and nothing here consumes it.
        """
        victims: list[SubAgentRecord] = []
        tasks: list[asyncio.Task[None]] = []
        async with self._lock:
            # user:“修 问题严重的话 就重新设计”+(等锁期间目标已换代时，旧暂停既不能发信号，也不能修改成员)。
            if control_guard is not None and not control_guard():
                return []
            self.pause_event.set()
            names = set(self._tasks)
            with self._connection() as db:
                rows = db.execute(
                    "SELECT name,payload FROM sub_agents WHERE parent_thread_id=?",
                    (self.parent_thread_id,),
                ).fetchall()
            for row in rows:
                record = SubAgentRecord(**json.loads(row["payload"]))
                task = self._tasks.get(record.name)
                active = record.status in {"running", "pending"} or (
                    task is not None and not task.done()
                )
                if not active:
                    continue
                if task is None and _owned_elsewhere(record):
                    raise ValueError(
                        f"sub-agent '{record.name}' is owned by another running process"
                    )
                record.status = "suspended"
                record.execution_token = uuid.uuid4().hex
                record.completed_at = time.time()
                if record.started_at:
                    record.elapsed_ms = int((record.completed_at - record.started_at) * 1000)
                self._save(record)
                self._pending_prompts.pop(record.name, None)
                self._initial_mail_ids.pop(record.name, None)
                self._offered_mail.pop(record.name, None)
                self._resume_names.discard(record.name)
                self._resume_prompts.pop(record.name, None)
                if task is not None and not task.done():
                    # Abort work that cannot poll the pause event (a long tool).
                    # The kernel tells this teardown apart from a cancel and
                    # still converges on the paused state.
                    task.cancel()
                    tasks.append(task)
                inline = self._inline_tasks.pop(record.name, None)
                if inline is not None and not inline.done():
                    inline.cancel()
                    tasks.append(inline)
                self._tasks.pop(record.name, None)
                victims.append(record)
            for name in names - {record.name for record in victims}:
                task = self._tasks.get(name)
                if task is not None and task.done():
                    self._tasks.pop(name, None)
        for record in victims:
            await self._record_member_event(
                record, "member_suspended", detail="用户暂停了该子代理"
            )
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._await_children_settled(victims)
        await self._maybe_report_members_drained()
        return [record.to_dict() for record in victims]

    async def resume_interrupted(self) -> list[dict[str, Any]]:
        """Schedule interrupted children from their committed child history."""
        return await self._resume_records(statuses={"interrupted"}, prompt=None)

    async def resume_suspended(self) -> list[dict[str, Any]]:
        """Continue the children a user pause parked, from committed history.

        Pure continuation: no synthetic prompt, the child's own history says
        what is left to do. The pause event is cleared first so the resumed
        kernels do not immediately park again.
        """
        event = self._pause_event
        if event is not None:
            event.clear()
        return await self._resume_records(statuses={"suspended"}, prompt="")

    async def _resume_records(
        self,
        *,
        statuses: set[str],
        prompt: str | None,
    ) -> list[dict[str, Any]]:
        # user:“修 问题严重的话 就重新设计”+(没有真实执行器时不能先写正在恢复)。
        resumed: list[SubAgentRecord] = []
        async with self._lock:
            with self._connection() as db:
                rows = db.execute(
                    "SELECT name,payload FROM sub_agents WHERE parent_thread_id=? ORDER BY name",
                    (self.parent_thread_id,),
                ).fetchall()
            for row in rows:
                record = SubAgentRecord(**json.loads(row["payload"]))
                if record.status not in statuses:
                    continue
                if not any(callable(getattr(self.runner, attr, None)) for attr in ("run", "resume_interrupted")):
                    raise ValueError("Sub-agent execution owner is not configured")
                task = self._tasks.get(record.name)
                if task is not None and not task.done():
                    continue
                if task is None and _owned_elsewhere(record):
                    continue
                record.status = "running"
                record.started_at = time.time()
                record.completed_at = None
                record.elapsed_ms = None
                record.lease_until = time.time() + SUB_AGENT_MAX_RUN_SECONDS
                record.runtime_owner = owner_token()
                record.execution_token = uuid.uuid4().hex
                self._save(record)
                self._resume_names.add(record.name)
                self._resume_prompts[record.name] = prompt
                self._tasks[record.name] = asyncio.create_task(
                    self._drive(record.name),
                    name=f"sub-agent-resume:{self.parent_thread_id}:{record.name}",
                )
                resumed.append(record)
        for record in resumed:
            # The durable outbox is what publishes this transition when no
            # parent turn holds a live sink (e.g. Resume from the lifecycle RPC
            # after a restart); the direct publish is the in-turn fast path.
            await self._record_member_event(record, "member_resumed")
            await self._publish_member_status(record, event="member_running")
        return [record.to_dict() for record in resumed]

    async def _drive(self, name: str) -> None:
        execution_token = ""
        try:
            while True:
                async with self._lock:
                    resume = name in self._resume_names
                    if resume:
                        self._resume_names.discard(name)
                    prompt = self._pending_prompts.pop(name, "")
                    resume_prompt = self._resume_prompts.pop(name, None)
                    initial_ids = self._initial_mail_ids.pop(name, [])
                    if prompt or resume:
                        record = self._required(name)
                        execution_token = record.execution_token
                        if record.status in {"closed", "terminated", "deleted"}:
                            stop_driving = True
                        else:
                            record.execution_token = uuid.uuid4().hex
                            execution_token = record.execution_token
                            stop_driving = False
                            record.status = "running"
                            record.started_at = record.started_at or time.time()
                            record.completed_at = None
                            record.elapsed_ms = None
                            record.lease_until = time.time() + SUB_AGENT_MAX_RUN_SECONDS
                            self._save(record)
                    else:
                        record = self._required(name)
                        if record.status == "running":
                            record.status = "idle"
                            self._save(record)
                        stop_driving = True
                if stop_driving:
                    await self._maybe_report_members_drained(exclude=name)
                    return
                run_runner = self._owned_runner
                signature_fn = getattr(self.runner, "config_signature", None)
                current_signature = signature_fn() if callable(signature_fn) else None
                if run_runner is not None and current_signature is not None:
                    owned_signature = getattr(run_runner, "_config_signature", None)
                    if owned_signature is not None and owned_signature != current_signature:
                        # The parent's project/model/permissions changed since
                        # the clone was built. Rebuild it instead of running a
                        # new turn with stale configuration.
                        closer = getattr(run_runner, "close", None)
                        if callable(closer):
                            try:
                                await closer()
                            except BaseException:
                                _logger.exception("[sub-agent] failed to close the stale runner")
                        run_runner = None
                        self._owned_runner = None
                if run_runner is None:
                    factory = getattr(self.runner, "create_supervisor_runner", None)
                    run_runner = await factory() if callable(factory) else self.runner
                    setattr(run_runner, "_config_signature", current_signature)
                    self._owned_runner = run_runner
                else:
                    # The owned runner preserves its independent MCP registry,
                    # but turn-local sinks must follow the latest parent run.
                    for attribute in ("parent_event_sink", "parent_guidance_sink"):
                        if hasattr(self.runner, attribute):
                            setattr(run_runner, attribute, getattr(self.runner, attribute))
                setter = getattr(run_runner, "set_pause_event", None)
                if callable(setter):
                    setter(self.pause_event)
                token = _child_identity.set((self, record.type, record.name))
                invocation_id = uuid.uuid4().hex
                self._provider_messages_by_invocation[invocation_id] = set()
                invocation_token = _child_invocation_id.set(invocation_id)
                try:
                    # Only the child invocation is serialized. The closeout
                    # below runs outside this lock so a message that arrives
                    # while the previous run is draining can start the next
                    # run instead of waiting for bookkeeping.
                    async with self.agent_lock(name):
                        async with self._run_semaphore:
                            if resume and hasattr(run_runner, "resume_interrupted"):
                                result = await run_runner.resume_interrupted(
                                    session_id=record.sub_session_id,
                                    agent=record.name,
                                    model=record.model_id,
                                    reasoning_level=record.reasoning_level,
                                    mode=record.type,
                                    parent_call_id=record.source_call_id,
                                    parent_run_id=record.source_run_id,
                                    parent_turn_id=record.source_turn_id,
                                    supervisor=self,
                                    prompt=resume_prompt,
                                )
                            else:
                                result = await run_runner.run(
                                    task=prompt or "Continue the interrupted sub-agent task using committed conversation history.",
                                    agent=record.name, model=record.model_id,
                                    reasoning_level=record.reasoning_level, mode=record.type,
                                    parent_call_id=record.source_call_id,
                                    parent_run_id=record.source_run_id,
                                    parent_turn_id=record.source_turn_id,
                                    late_context=self._late_context(record),
                                    guidance_source=lambda child=name: self.consume_guidance(child),
                                    guidance_finalizer=lambda child=name: self.finalize_guidance(child),
                                    guidance_acknowledger=lambda ids, child=name: self.acknowledge_guidance(child, ids),
                                    initial_guidance_ids=initial_ids,
                                )
                finally:
                    _child_invocation_id.reset(invocation_token)
                    _child_identity.reset(token)
                    self._provider_messages_by_invocation.pop(invocation_id, None)
                async with self._lock:
                    current = self._required(name)
                    if not self.result_is_current(name, execution_token):
                        return
                    # user:“把最多 500 字符这个限制给去掉”+(上游记录也保留完整最终消息，避免通知前已被截断。)
                    current.summary = str(getattr(result, "message", "") or getattr(result, "error", ""))
                    decision = str(getattr(result, "decision", "done"))
                    current.status = _result_status(result)
                    current.completed_at = time.time()
                    current.elapsed_ms = int((current.completed_at - (current.started_at or current.completed_at)) * 1000)
                    current.lease_until = 0.0
                    if not self._save_if_current(current, execution_token):
                        return
                    # Guidance accepted after the kernel sealed its final step
                    # becomes the immediate next run; the normal busy path is
                    # consumed inside the same run at a step boundary.
                    # A normally returned successful/waiting runner has persisted
                    # the input it accepted. The kernel acknowledges sooner, at
                    # its checkpoints; this also supports simpler host runners.
                    if decision in {"done", "wait"}:
                        self.acknowledge_guidance(name, list(self._offered_mail.get(name, set())))
                    self._offered_mail.pop(name, None)
                    if current.status == "idle":
                        self._queue_initial_mail(name)
                    await self._record_member_event(
                        current,
                        "member_finished" if current.status == "idle" else f"member_{current.status}",
                    )
                    terminal_member = current.status != "idle" or name not in self._pending_prompts
                    if terminal_member:
                        # Release ownership before any awaited closeout work.
                        # A new message must start a new drive, rather than enter
                        # a task that has already sealed its final boundary.
                        if self._tasks.get(name) is asyncio.current_task():
                            self._tasks.pop(name, None)
                if terminal_member:
                    await self._maybe_report_members_drained(exclude=name)
                    return
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            async with self._lock:
                record = self._load(name)
                if record and self.result_is_current(name, execution_token):
                    self._offered_mail.pop(name, None)
                    self._initial_mail_ids.pop(name, None)
                    record.status = "failed"
                    record.summary = str(exc)[:1000]
                    record.completed_at = time.time()
                    record.lease_until = 0.0
                    if self._save_if_current(record, execution_token):
                        await self._record_member_event(record, "member_failed", detail=str(exc))
            await self._maybe_report_members_drained(exclude=name)

    @staticmethod
    def _late_context(record: SubAgentRecord) -> str:
        return (
            "[Request-local sub-agent context]\n"
            f"name: {record.name}\ntype: {record.type}\nmodel_id: {record.model_id}\n"
            f"reasoning_level: {record.reasoning_level}\nsummary: {record.summary or '(none)'}"
        )

    async def child_message(self, message: object, *, message_id: object = "") -> dict[str, Any]:
        identity = _child_identity.get()
        if identity is None or identity[0] is not self:
            raise ValueError("message is only available inside a bound sub-agent context")
        body = str(message or "").strip()
        if not body:
            raise ValueError("message is required")
        _supervisor, child_type, name = identity
        provider_message_id = str(message_id or uuid.uuid4().hex)
        invocation_id = _child_invocation_id.get() or "legacy"
        seen = self._provider_messages_by_invocation.setdefault(invocation_id, set())
        if provider_message_id in seen:
            inserted = False
            message_key = provider_message_id
        else:
            seen.add(provider_message_id)
            message_key = provider_message_id
            inserted = self._mail(name, "child_to_parent", body, message_key=message_key)
            if not inserted:
                message_key = f"{invocation_id}:{provider_message_id}"
                inserted = self._mail(name, "child_to_parent", body, message_key=message_key)
        injected = False
        record = self._load(name)
        sink = getattr(self.runner, "parent_guidance_sink", None)
        if inserted and record is not None and callable(sink):
            guidance_id = f"sub-agent:{self.parent_thread_id}:{name}:{message_key}"
            sink_args = (
                self.parent_thread_id,
                record.source_run_id,
                body,
                guidance_id,
            )
            guidance_metadata = {
                "source": "sub_agent",
                "name": name,
                "type": child_type,
                "status": record.status,
                "summary": record.summary,
                "session_id": record.sub_session_id,
                "sub_session_id": record.sub_session_id,
                "model_id": record.model_id,
                "reasoning_level": record.reasoning_level,
                "parent_call_id": record.source_call_id,
                "parent_run_id": record.source_run_id,
                "parent_turn_id": record.source_turn_id,
                "invocation_id": invocation_id,
            }
            try:
                inspect.signature(sink).bind(*sink_args, guidance_metadata)
            except (TypeError, ValueError):
                # Keep compatibility with injected/legacy four-argument sinks.
                injected = bool(sink(*sink_args))
            else:
                injected = bool(sink(*sink_args, guidance_metadata))
            if injected and not getattr(sink, "acknowledges_after_checkpoint", False):
                with self._connection() as db:
                    db.execute(
                        "UPDATE sub_agent_mailbox SET delivered_at=? WHERE parent_thread_id=? AND name=? AND direction='child_to_parent' AND message_key=?",
                        (time.time(), self.parent_thread_id, name, message_key),
                    )
        return {"accepted": True, "deduplicated": not inserted, "injected": injected, "type": child_type, "name": name}

    def pending_guidance(self, name: str) -> list[dict[str, Any]]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT id,body,created_at FROM sub_agent_mailbox WHERE parent_thread_id=? AND name=? "
                "AND direction='parent_to_child' AND delivered_at IS NULL ORDER BY created_at,id",
                (self.parent_thread_id, name),
            ).fetchall()
        return [dict(row) for row in rows]

    def _queue_initial_mail(self, name: str) -> None:
        rows = self.pending_guidance(name)
        if not rows:
            return
        first = rows[0]
        self._pending_prompts[name] = first["body"]
        self._initial_mail_ids[name] = [first["id"]]
        self._offered_mail.setdefault(name, set()).add(first["id"])

    def consume_guidance(self, name: str) -> list[dict[str, Any]]:
        offered = self._offered_mail.setdefault(name, set())
        rows = [row for row in self.pending_guidance(name) if row["id"] not in offered]
        offered.update(row["id"] for row in rows)
        return [{"content": row["body"], "metadata": {
            "guidance_id": row["id"], "sent_at": row["created_at"], "source": "parent_to_child",
        }} for row in rows]

    def acknowledge_guidance(self, name: str, ids: list[str]) -> None:
        with self._connection() as db:
            db.executemany(
                "UPDATE sub_agent_mailbox SET delivered_at=COALESCE(delivered_at,?) "
                "WHERE id=? AND parent_thread_id=? AND name=? AND direction='parent_to_child'",
                [(time.time(), message_id, self.parent_thread_id, name) for message_id in ids],
            )

    def finalize_guidance(self, name: str) -> list[dict[str, Any]] | None:
        guidance = self.consume_guidance(name)
        return guidance or None

    async def list(self) -> list[dict[str, Any]]:
        async with self._lock:
            with self._connection() as db:
                rows = db.execute("SELECT payload FROM sub_agents WHERE parent_thread_id=? ORDER BY name", (self.parent_thread_id,)).fetchall()
            return [json.loads(row["payload"]) for row in rows]

    async def request_local_context(self, name: str) -> str:
        async with self._lock:
            return self._late_context(self._required(validate_name(name)))

    async def finalize_resumed(self, name: str, result: Any, *, expected_token: str | None = None) -> SubAgentRecord:
        """Converge the durable lifecycle record after approval continuation."""
        async with self._lock:
            record = self._required(validate_name(name))
            # user:“修 问题严重的话 就重新设计”+(终止不可被迟到的审批结果或旧执行覆盖)。
            if record.status in {"terminated", "closed", "deleted"} or (
                expected_token is not None and record.execution_token != expected_token
            ):
                return record
            # user:“把最多 500 字符这个限制给去掉”+(审批或问询恢复后的最终消息同样完整保存。)
            record.summary = str(
                getattr(result, "message", "") or getattr(result, "error", "")
            )
            record.status = _result_status(result)
            record.completed_at = time.time()
            record.lease_until = 0.0
            record.elapsed_ms = int(
                (record.completed_at - (record.started_at or record.completed_at)) * 1000
            )
            if not self._save_if_current(record, expected_token if expected_token is not None else record.execution_token):
                return self._required(validate_name(name))
            return record

    async def finalize_terminal(
        self,
        name: str,
        *,
        status: str = "failed",
        summary: str = "",
        expected_token: str | None = None,
    ) -> dict[str, Any] | None:
        """Converge a member record after a denied or failed continuation.

        The record was ``paused`` while the card waited.  Without this sync it
        stayed paused after the child state had already become cancelled or
        failed, so the interface showed a member that could never finish.
        """
        child_name = validate_name(name)
        async with self._lock:
            record = self._load(child_name)
            if record is None:
                return None
            if record.status in {"terminated", "closed", "deleted"} or (
                expected_token is not None and record.execution_token != expected_token
            ):
                return record.to_dict()
            record.status = status
            record.summary = str(summary or record.summary or "")[:1000]
            record.completed_at = time.time()
            record.lease_until = 0.0
            if record.started_at:
                record.elapsed_ms = int((record.completed_at - record.started_at) * 1000)
            if not self._save_if_current(record, expected_token if expected_token is not None else record.execution_token):
                return self._required(child_name).to_dict()
        await self._record_member_event(record, f"member_{status}")
        await self._publish_member_status(record, event=f"member_{status}")
        return record.to_dict()

    async def drain_parent_mailbox(self) -> list[dict[str, Any]]:
        async with self._lock:
            with self._connection() as db:
                rows = db.execute(
                    "SELECT id,name,body,created_at FROM sub_agent_mailbox WHERE parent_thread_id=? AND direction='child_to_parent' AND delivered_at IS NULL ORDER BY created_at,id",
                    (self.parent_thread_id,),
                ).fetchall()
                now = time.time()
                db.executemany("UPDATE sub_agent_mailbox SET delivered_at=? WHERE id=?", [(now, row["id"]) for row in rows])
            return [dict(row) for row in rows]

    # ── 成员状态变化：会话级事件（供父回合唤醒） ──────────────────────
    #
    # 成员的完成/失败/关闭/被中断会以结构化事件写入父邮箱（持久、按
    # message_key 幂等），并点亮活动信号。父回合结束前可以 drain 这些事件；
    # 若成员仍在跑，则等待下一次活动信号（有租约上限，超时如实上报）。

    def _notify_activity(self) -> None:
        self._activity.set()

    def _pending_mail_count(self) -> int:
        with self._connection() as db:
            row = db.execute(
                "SELECT COUNT(*) AS n FROM sub_agent_events WHERE parent_thread_id=? AND delivered_at IS NULL",
                (self.parent_thread_id,),
            ).fetchone()
        return int((row["n"] if row else 0) or 0)

    def _write_member_event(self, record: SubAgentRecord, event: str, *, detail: str = "") -> None:
        """Persist one member state change as a durable, session-scoped event."""
        payload = json.dumps(
            {
                "event": event,
                "name": record.name,
                "type": record.type,
                "status": record.status,
                # user:“把最多 500 字符这个限制给去掉”+(完成通知向主代理传递完整最终消息。)
                "summary": record.summary or "",
                "detail": str(detail or "")[:500],
                "elapsed_ms": record.elapsed_ms,
                "occurred_at": record.completed_at or time.time(),
            },
            ensure_ascii=False,
        )
        key = f"{event}:{record.name}:{record.completed_at or record.started_at or 0}"
        try:
            with self._connection() as db:
                cursor = db.execute(
                    "INSERT OR IGNORE INTO sub_agent_events(id,parent_thread_id,name,payload,event_key,created_at) VALUES(?,?,?,?,?,?)",
                    (uuid.uuid4().hex, self.parent_thread_id, record.name, payload, key, time.time()),
                )
        except Exception:
            # Registry state survives; the application reconciliation retries
            # publication. Keep the failed outbox write observable in logs.
            _logger.exception("sub-agent lifecycle event write failed parent=%s name=%s event=%s",
                              self.parent_thread_id, record.name, event)
            return
        if cursor.rowcount == 0:
            return
        self._notify_activity()
        _notify_member_event()

    async def _record_member_event(self, record: SubAgentRecord, event: str, *, detail: str = "") -> None:
        """Persist a member state change and publish it to the open session.

        The durable row is written by ``_write_member_event``; the publish pushes
        the member's own status onto the parent's live stream so the interface
        can show it while the turn is still open. Bounded by construction: one
        event per lifecycle transition, never per streamed child event.
        """
        self._write_member_event(record, event, detail=detail)
        await self._publish_member_status(record, event=event)

    async def _publish_member_status(self, record: SubAgentRecord, *, event: str) -> None:
        """Publish one member's durable status onto the parent's live stream.

        Driven by the member's own lifecycle (started / finished / failed /
        paused / closed / interrupted), not by the parent's tool-call row, so a
        member that finishes mid-turn reads as finished immediately instead of
        staying "running" until the turn ends or the periodic record poll runs.
        Best-effort: an absent or failing sink never affects the member.
        """
        sink = getattr(self.runner, "parent_event_sink", None)
        if sink is None:
            return
        from lamtools_core.event import CoreEvent

        # The record uses ``source_*`` names while the projection reads
        # ``parent_*``. Publish both so a status row can be nested under the
        # member's parent card instead of floating with no linkage.
        record_payload = record.to_dict()
        record_payload.update({
            "agent": record.name,
            "parent_call_id": record.source_call_id,
            "parent_run_id": record.source_run_id,
            "parent_turn_id": record.source_turn_id,
        })

        try:
            await sink.emit(CoreEvent(
                name="runtime.sub_agent_status",
                category="message",
                payload={"event": event, "sub_agent": record_payload},
                event_id=hashlib.sha256(
                    f"member-status:{self.parent_thread_id}:{record.name}:{record.status}:"
                    f"{record.started_at}:{record.completed_at}:{record.source_turn_id}".encode()
                ).hexdigest()[:32],
                session_id=self.parent_thread_id,
                run_id=str(record.source_run_id or ""),
                turn_id=str(record.source_turn_id or ""),
                tags=["sub_agent", "status"],
            ))
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("sub-agent status publication failed parent=%s name=%s event=%s",
                              self.parent_thread_id, record.name, event)
            return

    async def drain_member_events(self) -> list[dict[str, Any]]:
        """Deliver (once) every pending member state-change event."""
        async with self._lock:
            with self._connection() as db:
                rows = db.execute(
                    "SELECT id,payload,created_at FROM sub_agent_events WHERE parent_thread_id=? AND delivered_at IS NULL ORDER BY created_at,id",
                    (self.parent_thread_id,),
                ).fetchall()
                now = time.time()
                db.executemany(
                    "UPDATE sub_agent_events SET delivered_at=? WHERE id=?",
                    [(now, row["id"]) for row in rows],
                )
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict):
                events.append(payload)
        return events

    async def has_active_members(self) -> bool:
        """True while any member has queued work or a run in flight."""
        async with self._lock:
            if self._pending_prompts:
                return True
            if any(not task.done() for task in self._tasks.values()):
                return True
            return any(not task.done() for task in self._inline_tasks.values())

    def note_member_wait_turn(self, turn_id: object) -> None:
        """Record the turn whose members-running fact is currently published.

        Called by the kernel loop when it publishes the fact at a turn terminal,
        so the supervisor can retract it for that same turn once the last member
        it named finishes.
        """
        self._member_wait_turn_id = str(turn_id or "")

    def _no_members_remain(self, *, exclude: str = "") -> bool:
        """True when nothing is queued and no member other than ``exclude`` runs.

        ``exclude`` is the member whose own drive loop is finishing: its task is
        still alive while it emits this check, so it must not count itself.
        """
        if self._pending_prompts:
            return False
        if any(not task.done() for name, task in self._inline_tasks.items() if name != exclude):
            return False
        return all(task.done() for name, task in self._tasks.items() if name != exclude)

    async def report_members_drained(self) -> bool:
        """Retract the members-running fact once nothing is left to run.

        Publishes ``runtime.sub_agent_report`` (``waiting_on_members`` false) to
        the parent thread for the turn recorded by ``note_member_wait_turn``, so
        an ended turn stops advertising members that have since finished. The
        recorded turn is consumed, so one drain publishes one retraction.
        """
        turn_id = self._member_wait_turn_id
        if not turn_id:
            return False
        sink = getattr(self.runner, "parent_event_sink", None)
        if sink is None:
            return False
        from lamtools_core.event import CoreEvent

        try:
            await sink.emit(CoreEvent(
                name="runtime.sub_agent_report",
                category="message",
                payload={"waiting_on_members": False, "members": []},
                session_id=self.parent_thread_id,
                turn_id=turn_id,
                tags=["sub_agent", "report"],
            ))
        except BaseException:
            return False
        self._member_wait_turn_id = ""
        return True

    async def _maybe_report_members_drained(self, *, exclude: str = "") -> None:
        """Retract the published fact when the last of its members just ended."""
        if not self._member_wait_turn_id or not self._no_members_remain(exclude=exclude):
            return
        try:
            await self.report_members_drained()
        except BaseException:
            return

    async def active_member_status(self) -> list[dict[str, Any]]:
        """Snapshot of members still running (for lease-timeout reporting).

        One query for every running member: this runs at the end of a turn that
        still has members, so it must not cost one connection per member.
        """
        async with self._lock:
            names = [name for name, task in self._tasks.items() if not task.done()]
        if not names:
            return []
        placeholders = ",".join("?" for _ in names)
        try:
            with self._connection() as db:
                rows = db.execute(
                    f"SELECT payload FROM sub_agents WHERE parent_thread_id=? AND name IN ({placeholders})",
                    (self.parent_thread_id, *names),
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        now = time.time()
        out: list[dict[str, Any]] = []
        for row in rows:
            record = SubAgentRecord(**json.loads(row["payload"]))
            out.append(
                {
                    "name": record.name,
                    "type": record.type,
                    "status": record.status,
                    "running_ms": int((now - (record.started_at or now)) * 1000),
                    "summary": (record.summary or "")[:200],
                }
            )
        out.sort(key=lambda item: item["name"])
        return out

    async def sync_agent_runs(self) -> int:
        """Rebuild this parent's agent_runs projection from durable records.

        Startup recovery calls this after the sqlite registry is settled, so a
        projection lost while the process was down is restored from the same
        authority the supervisor uses.
        """
        store = self._agent_run_store
        if store is None:
            return 0
        live_names: set[str] = set()
        for payload in await self.list():
            name = str(payload.get("name") or "")
            record = self._load(name)
            if record is None:
                continue
            live_names.add(name)
            await store.upsert_agent_run(
                _agent_run_from_record(self.parent_thread_id, record)
            )
        # A record that no longer exists was deleted while the projection could
        # not be written. Keep the row (transcript identity) but hide it.
        for run in await store.list_agent_runs(parent_thread_id=self.parent_thread_id):
            if run.name and run.name not in live_names and run.status != "deleted":
                run.status = "deleted"
                await store.upsert_agent_run(run)
        return len(live_names)

    async def wait_for_activity(self, timeout: float) -> str:
        """Wait for the next member state change.

        Returns ``"activity"`` when something changed (or undelivered mail is
        already waiting) and ``"timeout"`` when the lease expired first.
        """
        self._activity.clear()
        if self._pending_mail_count() > 0:
            return "activity"
        try:
            await asyncio.wait_for(self._activity.wait(), timeout=max(float(timeout), 0.0))
            return "activity"
        except (TimeoutError, asyncio.TimeoutError):
            return "timeout"

    async def shutdown(self) -> None:
        self._closed = True
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        closer = getattr(self._owned_runner, "close", None)
        if callable(closer):
            await closer()
        self._owned_runner = None
        async with self._lock:
            for name in list(self._tasks):
                record = self._load(name)
                if record and record.status == "running":
                    record.status = "interrupted"
                    record.completed_at = time.time()
                    self._save(record)
                    await self._record_member_event(
                        record, "member_interrupted", detail="进程关闭时该成员仍在运行"
                    )
            self._tasks.clear()
        if self._agent_run_tasks:
            await asyncio.gather(*list(self._agent_run_tasks), return_exceptions=True)
        key = (str(self.database_path.parent.resolve()), self.parent_thread_id)
        if _SUPERVISORS.get(key) is self:
            _SUPERVISORS.pop(key, None)

    def _required(self, name: str) -> SubAgentRecord:
        record = self._load(name)
        if record is None:
            raise ValueError(f"sub-agent not found: {name}")
        return record

    def _load(self, name: str) -> SubAgentRecord | None:
        with self._connection() as db:
            row = db.execute("SELECT payload FROM sub_agents WHERE parent_thread_id=? AND name=?", (self.parent_thread_id, name)).fetchone()
        return SubAgentRecord(**json.loads(row["payload"])) if row else None

    def _save(self, record: SubAgentRecord) -> None:
        if not record.execution_token:
            record.execution_token = uuid.uuid4().hex
        with self._connection() as db:
            db.execute(
                "INSERT INTO sub_agents(parent_thread_id,name,payload) VALUES(?,?,?) ON CONFLICT(parent_thread_id,name) DO UPDATE SET payload=excluded.payload",
                (self.parent_thread_id, record.name, json.dumps(record.to_dict(), ensure_ascii=False)),
            )
        self._mirror_agent_run(record)

    def _save_if_current(self, record: SubAgentRecord, token: str) -> bool:
        # user:“修 问题严重的话 就重新设计”+(在同一数据库写入中校验执行凭据，其他连接提交的终止同样优先)。
        with self._connection() as db:
            changed = db.execute(
                "UPDATE sub_agents SET payload=? WHERE parent_thread_id=? AND name=? "
                "AND COALESCE(json_extract(payload, '$.execution_token'), '')=? "
                "AND json_extract(payload, '$.status') NOT IN ('terminated','closed','deleted')",
                (json.dumps(record.to_dict(), ensure_ascii=False), self.parent_thread_id, record.name, token),
            ).rowcount
        if changed:
            self._mirror_agent_run(record)
        return bool(changed)

    def _mirror_agent_run(self, record: SubAgentRecord) -> None:
        """Project one durable record into the turn-control read model.

        The mirror is best-effort and never blocks a member transition: a
        failed projection is repaired by ``reconcile_sub_agent_state`` at the
        next startup or watchdog pass. Keeping it off the sqlite commit path
        also means a core.db lock can never freeze sub-agent lifecycle work.
        """
        store = self._agent_run_store
        if store is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        run = _agent_run_from_record(self.parent_thread_id, record)
        task = loop.create_task(
            store.upsert_agent_run(run), name=f"agent-run:{run.agent_run_id}"
        )
        self._agent_run_tasks.add(task)

        def _finished(done: asyncio.Task[Any]) -> None:
            self._agent_run_tasks.discard(done)
            if done.cancelled():
                return
            exc = done.exception()
            if exc is not None:
                # The projection is repaired by sync_agent_runs; never let a
                # mirror failure surface as an unretrieved task exception.
                _logger.debug(
                    "[sub-agent] agent_run mirror failed name=%s: %s",
                    record.name,
                    exc,
                )

        task.add_done_callback(_finished)

    def _mail(self, name: str, direction: str, body: str, *, message_key: str) -> bool:
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        with self._connection() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO sub_agent_mailbox(id,parent_thread_id,name,direction,body,digest,message_key,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex,
                    self.parent_thread_id,
                    name,
                    direction,
                    body,
                    digest,
                    message_key,
                    time.time(),
                ),
            )
            return cursor.rowcount > 0


_SUPERVISORS: dict[tuple[str, str], SubAgentSupervisor] = {}


def _remember_supervisor(supervisor: "SubAgentSupervisor") -> None:
    """Adopt a supervisor as this process's owner of one parent session.

    The durable sub-agent rows stay the authority; this index only answers
    "who in this process can drive them", so a restart-recovered supervisor is
    reachable by ``find_sub_agent_supervisor`` instead of being invisible.
    """
    key = (str(supervisor.database_path.parent.resolve()), supervisor.parent_thread_id)
    # user:“修 问题严重的话 就重新设计”+(对账对象没有执行权，不能取代仍持有任务的所有者)。
    if not any(callable(getattr(supervisor.runner, attr, None)) for attr in ("run", "resume_interrupted")):
        return
    incumbent = _SUPERVISORS.get(key)
    if incumbent is not None and incumbent is not supervisor:
        return
    if key not in _SUPERVISORS and len(_SUPERVISORS) >= SUB_AGENT_MAX_SUPERVISORS:
        # Same bound as ``get_sub_agent_supervisor``: startup reconciliation
        # visits every parent, and an unbounded index would keep one runner per
        # session alive for the whole process. Only an idle entry is dropped.
        for candidate_key, candidate in list(_SUPERVISORS.items()):
            if candidate.has_active_work():
                continue
            _SUPERVISORS.pop(candidate_key, None)
            break
    _SUPERVISORS[key] = supervisor


def find_sub_agent_supervisor(parent_thread_id: object, *, data_dir: Path | str | None = None) -> SubAgentSupervisor | None:
    """Return the live supervisor for one parent session, if this process owns it.

    Used by the kernel loop to drain member events at the end of a turn without
    needing to know the supervisor's data directory.
    """
    thread_id = str(parent_thread_id or "")
    if not thread_id:
        return None
    if data_dir is not None:
        return _SUPERVISORS.get((str(Path(data_dir).resolve()), thread_id))
    for (_, supervisor_thread_id), supervisor in _SUPERVISORS.items():
        if supervisor_thread_id == thread_id:
            return supervisor
    return None


async def get_sub_agent_supervisor(
    *,
    parent_thread_id: str,
    runner: Any,
    data_dir: str | Path,
    update_existing_runner: bool = True,
) -> SubAgentSupervisor:
    # user:“修 问题严重的话 就重新设计”+(执行所有者的所有入口都拒绝纯投影对象)。
    if not any(callable(getattr(runner, attr, None)) for attr in ("run", "resume_interrupted")):
        raise ValueError("Sub-agent execution owner is not configured")
    key = (str(Path(data_dir).resolve()), str(parent_thread_id))
    supervisor = _SUPERVISORS.get(key)
    if supervisor is None:
        if len(_SUPERVISORS) >= SUB_AGENT_MAX_SUPERVISORS:
            # Bound the resident set: every supervisor owns a runner and an
            # independent MCP registry, so a long-lived process that visits
            # many sessions would otherwise accumulate them forever.
            for candidate_key, candidate in list(_SUPERVISORS.items()):
                if candidate_key == key or candidate.has_active_work():
                    continue
                _SUPERVISORS.pop(candidate_key, None)
                try:
                    await candidate.shutdown()
                except BaseException:
                    _logger.exception("[sub-agent] failed to shut down an idle supervisor")
                break
        supervisor = SubAgentSupervisor(
            parent_thread_id=parent_thread_id, runner=runner,
            database_path=Path(data_dir) / "sub_agents.sqlite3",
        )
        _SUPERVISORS[key] = supervisor
        await supervisor.recover()
    elif update_existing_runner:
        supervisor.update_runner(runner)
    return supervisor


def register_sub_agent_lifecycle_operations(
    catalog: Any,
    *,
    runner_factory: Any,
    data_dir: str | Path,
) -> None:
    """Mount the GUI/CLI-neutral lifecycle surface on an operation catalog."""

    from lamtools_core.app.operation_catalog import OperationResult

    async def supervisor_for(request: Any) -> SubAgentSupervisor:
        thread_id = str(
            request.payload.get("thread_id") or request.payload.get("threadId") or ""
        ).strip()
        if not thread_id:
            raise ValueError("thread_id is required")
        runner = runner_factory()
        if inspect.isawaitable(runner):
            runner = await runner
        runner.session_prefix = thread_id
        # user:“修 问题严重的话 就重新设计”+(冷启动运行器继承所属会话的工作目录与权限，不使用通用工厂默认值)。
        state_store = getattr(runner, "state_store", None)
        state = await state_store.get(thread_id) if state_store is not None else None
        runtime_snapshot = dict(getattr(state, "metadata", {}).get("runtime_snapshot") or {})
        runtime_snapshot.update(dict(request.payload.get("runtime_snapshot") or {}))
        for attr in ("approval_policy", "permission_preset", "active_tier", "tier_tools", "allow_access_outside_workdir"):
            if attr in runtime_snapshot:
                setattr(runner, attr, runtime_snapshot[attr])
        work_root = request.payload.get("work_root") or getattr(state, "metadata", {}).get("work_root")
        if work_root:
            runner.work_root = Path(work_root)
        runner.runtime_snapshot = runtime_snapshot or getattr(runner, "runtime_snapshot", None)
        return await get_sub_agent_supervisor(
            parent_thread_id=thread_id,
            runner=runner,
            data_dir=data_dir,
            # Lifecycle RPC runners are generic fallbacks.  An existing
            # supervisor may already hold the actual parent turn's approval,
            # event, and guidance context; do not replace it here.
            update_existing_runner=False,
        )

    async def lifecycle(request: Any) -> Any:
        try:
            supervisor = await supervisor_for(request)
            payload = request.payload
            metadata = request.metadata if isinstance(request.metadata, dict) else {}
            source_ids = {
                "call_id": str(payload.get("call_id") or metadata.get("call_id") or ""),
                "run_id": str(
                    payload.get("parent_run_id")
                    or payload.get("run_id")
                    or metadata.get("parent_run_id")
                    or metadata.get("run_id")
                    or ""
                ),
                "turn_id": str(
                    payload.get("parent_turn_id")
                    or payload.get("turn_id")
                    or metadata.get("parent_turn_id")
                    or metadata.get("turn_id")
                    or ""
                ),
                "message_id": str(metadata.get("parent_message_id") or ""),
                "part_id": str(metadata.get("parent_part_id") or ""),
            }
            if request.name == "sub_agent.list":
                return OperationResult(request.name, payload={"items": await supervisor.list()})
            if request.name == "sub_agent.create":
                result = await supervisor.create_operation(
                    type=payload.get("type"),
                    name=payload.get("name"),
                    model=payload.get("model"),
                    reasoning_level=payload.get("reasoning_level"),
                    source_ids=source_ids,
                )
                return OperationResult(request.name, payload=result.to_dict())
            if request.name == "sub_agent.close":
                result = await supervisor.close_operation(
                    type=payload.get("type"),
                    name=payload.get("name"),
                    model=payload.get("model"),
                    reasoning_level=payload.get("reasoning_level"),
                    source_ids=source_ids,
                )
                return OperationResult(request.name, payload=result.to_dict())
            if request.name == "sub_agent.delete":
                return OperationResult(
                    request.name,
                    payload=await supervisor.delete_operation(name=payload.get("name")),
                )
            if request.name == "sub_agent.interrupt":
                # Stop for the members themselves: the parent turn may already
                # be terminal, so this never touches the parent runtime. A
                # per-member Stop keeps its documented "can be continued"
                # meaning; only a session terminate writes the final state.
                victims = await supervisor.interrupt_active()
                return OperationResult(request.name, payload={
                    "items": victims,
                    "lifecycle_action": "members_interrupted",
                })
            if request.name == "sub_agent.terminate":
                victims = await supervisor.interrupt_active(include_paused=True, final_status="terminated")
                return OperationResult(request.name, payload={"items": victims, "lifecycle_action": "members_terminated"})
            if request.name == "sub_agent.pause":
                # Per-member Stop has the same meaning as the session Stop: the
                # member is parked and can be continued, not killed. The kill
                # entry point stays ``sub_agent.interrupt``.
                parked = await supervisor.pause_active(control_guard=metadata.get("control_guard"))
                return OperationResult(request.name, payload={
                    "items": parked,
                    "lifecycle_action": "members_suspended",
                })
            if request.name == "sub_agent.resume":
                # One Resume press covers both stoppings: members interrupted by
                # a terminate or a crash, and members a pause parked.
                resumed = [] if payload.get("suspended_only") else await supervisor.resume_interrupted()
                resumed += await supervisor.resume_suspended()
                return OperationResult(request.name, payload={
                    "items": resumed,
                    "lifecycle_action": "members_resumed",
                })
            accepted = await supervisor.message(
                type=payload.get("type"),
                name=payload.get("name"),
                prompt=payload.get("prompt"),
                source_ids=source_ids,
            )
            return OperationResult(request.name, payload=accepted)
        except ValueError as exc:
            return OperationResult(request.name, status="error", payload={"error": str(exc)})

    for operation_name in (
        "sub_agent.list",
        "sub_agent.terminate",
        "sub_agent.create",
        "sub_agent.close",
        "sub_agent.delete",
        "sub_agent.message",
        "sub_agent.interrupt",
        "sub_agent.pause",
        "sub_agent.resume",
    ):
        if not catalog.has(operation_name):
            catalog.register(operation_name, lifecycle)


async def shutdown_sub_agent_supervisors() -> None:
    supervisors = list(_SUPERVISORS.values())
    _SUPERVISORS.clear()
    await asyncio.gather(*(item.shutdown() for item in supervisors), return_exceptions=True)


async def shutdown_parent_sub_agents(parent_thread_id: str) -> None:
    matches = [key for key in _SUPERVISORS if key[1] == str(parent_thread_id)]
    supervisors = [_SUPERVISORS.pop(key) for key in matches]
    await asyncio.gather(*(item.shutdown() for item in supervisors), return_exceptions=True)


def drain_parent_mailbox(
    database_path: str | Path,
    parent_thread_id: str,
    *,
    mark_delivered: bool = True,
) -> list[dict[str, Any]]:
    path = Path(database_path)
    if not path.is_file():
        return []
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        try:
            rows = db.execute(
                "SELECT id,name,body,created_at FROM sub_agent_mailbox WHERE parent_thread_id=? AND direction='child_to_parent' AND delivered_at IS NULL ORDER BY created_at,id",
                (str(parent_thread_id),),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        if mark_delivered:
            now = time.time()
            db.executemany(
                "UPDATE sub_agent_mailbox SET delivered_at=? WHERE id=?",
                [(now, row["id"]) for row in rows],
            )
    return [dict(row) for row in rows]


def acknowledge_parent_mailbox(
    database_path: str | Path,
    parent_thread_id: str,
    message_ids: list[str],
) -> None:
    """Mark only messages actually handed to a started parent run."""
    ids = [str(item) for item in message_ids if str(item)]
    path = Path(database_path)
    if not ids or not path.is_file():
        return
    placeholders = ",".join("?" for _ in ids)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            f"UPDATE sub_agent_mailbox SET delivered_at=? "
            f"WHERE parent_thread_id=? AND direction='child_to_parent' "
            f"AND delivered_at IS NULL AND id IN ({placeholders})",
            (time.time(), str(parent_thread_id), *ids),
        )


def acknowledge_parent_guidance(database_path: str | Path, parent_thread_id: str, guidance_ids: list[str]) -> None:
    """Translate injected guidance IDs to mailbox receipts after the parent checkpoint."""
    path = Path(database_path)
    ids = set(guidance_ids)
    if not ids or not path.is_file():
        return
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute(
            "SELECT id,name,message_key FROM sub_agent_mailbox WHERE parent_thread_id=? "
            "AND direction='child_to_parent' AND delivered_at IS NULL", (parent_thread_id,),
        ).fetchall()
    acknowledge_parent_mailbox(path, parent_thread_id, [
        message_id for message_id, name, key in rows
        if f"sub-agent:{parent_thread_id}:{name}:{key}" in ids
    ])


# ── Waking an idle parent: durable member lifecycle events ──────────────────
#
# `sub_agent_events` already carries the member lifecycle facts and their
# delivery state. The kernel drains them while a parent turn is alive; when the
# turn has already ended there is nobody to drain them, so the watchdog in
# `app/memory_resume_supervisor.py` uses these helpers to find the threads that
# need waking and to claim the rows it delivers (dedupe is `delivered_at`).
#
# Only completion and failure wake a session on their own. A paused member is a
# human boundary (a question or approval is waiting for a person), and closing
# one is a user action. An interruption is reported alongside a completion or
# failure, but never starts a parent turn by itself.
MEMBER_WAKE_EVENTS = ("member_finished", "member_failed")
# When a completion/failure causes a turn, also report recover/shutdown
# interruptions from the same pending batch. An interruption alone does not
# restart a parent session; it remains durable until a suitable report occurs.
MEMBER_WAKE_REPORT_EVENTS = (*MEMBER_WAKE_EVENTS, "member_interrupted")


def member_event_payload(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("payload")
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raw = item.get("payload_json")
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def member_event_triggers_wake(payload: dict[str, Any]) -> bool:
    return str(payload.get("event") or "") in MEMBER_WAKE_EVENTS


def member_event_is_reportable(payload: dict[str, Any]) -> bool:
    return str(payload.get("event") or "") in MEMBER_WAKE_REPORT_EVENTS


def format_member_event(payload: dict[str, Any]) -> str:
    """One human line per member state change, shared by every consumer."""
    event = str(payload.get("event") or "member_update")
    if event == "members_still_running":
        members = payload.get("members") or []
        detail = "；".join(
            "{name}（{status}，已运行 {secs:.0f} 秒）".format(
                name=str(member.get("name") or "?"),
                status=str(member.get("status") or "running"),
                secs=float(member.get("running_ms") or 0) / 1000.0,
            )
            for member in members
            if isinstance(member, dict)
        )
        suffix = "（本次等待已到租约上限）" if payload.get("lease_timed_out") else ""
        return (
            f"- 成员仍在运行{suffix}：{detail or '未知'}。"
            "你可以继续等下一个事件，也可以先推进不依赖他们的工作。"
        )
    name = str(payload.get("name") or "(未署名成员)")
    elapsed = payload.get("elapsed_ms")
    elapsed_text = (
        f"，用时 {float(elapsed) / 1000.0:.0f} 秒"
        if isinstance(elapsed, (int, float)) and elapsed
        else ""
    )
    label = {
        "member_finished": "已完成",
        "member_paused": "已暂停（在等确认或补充信息）",
        "member_failed": "已失败",
        "member_closed": "已关闭",
        "member_interrupted": "已被中断",
    }.get(event, str(payload.get("status") or event))
    summary = str(payload.get("summary") or "").strip()
    detail = str(payload.get("detail") or "").strip()
    tail = f"：{summary}" if summary else ""
    if detail and detail != summary:
        tail += f"（原因：{detail}）"
    return f"- {name} {label}{elapsed_text}{tail}"


def list_threads_with_pending_member_wakes(
    database_path: str | Path,
    *,
    events: tuple[str, ...] = MEMBER_WAKE_EVENTS,
) -> list[str]:
    """Parent threads with an undelivered event that justifies a wake."""
    path = Path(database_path)
    if not path.is_file() or not events:
        return []
    clauses = " OR ".join("event_key LIKE ?" for _ in events)
    params = [f"{name}:%" for name in events]
    try:
        with sqlite3.connect(path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                f"SELECT DISTINCT parent_thread_id FROM sub_agent_events "
                f"WHERE delivered_at IS NULL AND ({clauses})",
                params,
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [str(row["parent_thread_id"]) for row in rows if row["parent_thread_id"]]


def peek_member_events(
    database_path: str | Path,
    parent_thread_id: str,
) -> list[dict[str, Any]]:
    """Every undelivered member event for one thread, without claiming it."""
    path = Path(database_path)
    if not path.is_file():
        return []
    try:
        with sqlite3.connect(path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT id,payload,event_key FROM sub_agent_events "
                "WHERE parent_thread_id=? AND delivered_at IS NULL ORDER BY created_at,id",
                (str(parent_thread_id),),
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        {
            "id": str(row["id"]),
            "event_key": str(row["event_key"]),
            "payload": member_event_payload({"payload": row["payload"]}),
        }
        for row in rows
    ]


def mark_member_events_delivered(database_path: str | Path, ids: list[str]) -> None:
    """Claim rows already handed to a started turn.

    Claiming only after the turn started is what keeps the wake path from
    losing an event when a start is refused: nothing is marked and the row is
    retried on the next tick. The `delivered_at IS NULL` predicate is the
    cross-path dedupe, so the kernel can never deliver a row this claimed.
    """
    clean = [str(item) for item in ids if str(item)]
    path = Path(database_path)
    if not clean or not path.is_file():
        return
    placeholders = ",".join("?" for _ in clean)
    try:
        with sqlite3.connect(path) as db:
            db.execute(
                f"UPDATE sub_agent_events SET delivered_at=? "
                f"WHERE delivered_at IS NULL AND id IN ({placeholders})",
                (time.time(), *clean),
            )
    except sqlite3.OperationalError:
        return


def member_wake_prompt(events: list[dict[str, Any]]) -> str:
    """One short system line per reportable member event. No coaching.

    The event itself is the input; the model is not told what to do with it, and
    every line is built from the stored event's name, state, and recorded detail.
    Interruption reasons survive process recovery and shutdown as report text.
    """
    lines: list[str] = []
    for item in events:
        if not isinstance(item, dict):
            continue
        payload = member_event_payload(item)
        name = str(payload.get("name") or "子代理")
        event = str(payload.get("event") or "")
        if event == "member_finished":
            line = f"子代理 {name} 已完成"
        elif event == "member_failed":
            line = f"子代理 {name} 已失败"
        elif event == "member_interrupted":
            line = f"子代理 {name} 已中断"
            detail = str(payload.get("detail") or "").strip()
            summary = str(payload.get("summary") or "").strip()
            suffixes: list[str] = []
            if detail:
                suffixes.append(f"原因：{detail}")
            if summary and summary != detail:
                suffixes.append(f"已保存摘要：{summary}")
            lines.append(f"{line}，{'；'.join(suffixes)}。" if suffixes else f"{line}。")
            continue
        else:
            continue
        summary = str(payload.get("summary") or "").strip()
        lines.append(f"{line}：{summary}" if summary else f"{line}。")
    return "\n".join(lines)


def current_child_identity() -> tuple[SubAgentSupervisor, str, str] | None:
    return _child_identity.get()


@contextmanager
def bound_child_identity(
    supervisor: SubAgentSupervisor,
    child_type: str,
    name: str,
):
    """Bind child-only tools while resuming a persisted child run."""
    identity_token = _child_identity.set((supervisor, child_type, name))
    invocation_id = uuid.uuid4().hex
    supervisor._provider_messages_by_invocation[invocation_id] = set()
    invocation_token = _child_invocation_id.set(invocation_id)
    try:
        yield
    finally:
        _child_invocation_id.reset(invocation_token)
        _child_identity.reset(identity_token)
        supervisor._provider_messages_by_invocation.pop(invocation_id, None)


# 成员事件落库后唤醒 member-wake watchdog 的回调。回合内不再消费成员事件，
# 续跑完全靠唤醒路径，所以事件一落库就立刻唤醒（由 watchdog 去抖合并），
# 而不是等下一次轮询。
_MEMBER_EVENT_NOTIFIER: Callable[[], None] | None = None


def set_member_event_notifier(notifier: Callable[[], None] | None) -> None:
    global _MEMBER_EVENT_NOTIFIER
    _MEMBER_EVENT_NOTIFIER = notifier


def _notify_member_event() -> None:
    notifier = _MEMBER_EVENT_NOTIFIER
    if notifier is None:
        return
    try:
        notifier()
    except Exception:  # noqa: BLE001 - a wake hint must never break the member
        pass


__all__ = [
    "MEMBER_WAKE_EVENTS",
    "MEMBER_WAKE_REPORT_EVENTS",
    "SUB_AGENT_TYPES", "SubAgentOperationResult", "SubAgentRecord", "SubAgentSupervisor", "acknowledge_parent_mailbox", "bound_child_identity", "current_child_identity", "drain_parent_mailbox",
    "format_member_event", "get_sub_agent_supervisor", "list_threads_with_pending_member_wakes",
    "mark_member_events_delivered", "member_event_is_reportable", "member_event_payload", "member_event_triggers_wake",
    "member_wake_prompt", "peek_member_events", "register_sub_agent_lifecycle_operations",
    "resolve_model_id", "set_member_event_notifier",
    "shutdown_parent_sub_agents", "shutdown_sub_agent_supervisors",
    "validate_name", "validate_reasoning", "validate_type",
]
