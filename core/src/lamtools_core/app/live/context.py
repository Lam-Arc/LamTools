"""Shared live-operation context, host dispatch and result contracts."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from lamtools_core.runtime import RuntimeStateStore, default_runtime_task_registry
from ..event_store import AppEventEnvelope, SqlAlchemyAppEventStore
from ..live_approval import normalize_approval_request
from ..live_hub import CoreAppEventHub, hub as default_hub
from ..live_member import DefaultCoreLiveMemberHooks
from ..live_protocol import INVALID_REQUEST, rpc_error, rpc_result
from ..operation_catalog import OperationCatalog, OperationHandler, OperationRequest, OperationResult
from ..operation_groups import CORE_WORKBENCH_OPERATION_NAMES
from ..persistence_host import AppPersistenceHost, RevisionConflictError
from ..session_actor import SessionActorBusyError, SessionActorRegistry
from ..snapshot_store import SqlAlchemyThreadSnapshotStore
from ..turn_acceptance import TURN_ACCEPTED_METHODS


class SessionBusyError(RuntimeError):
    """A live operation cannot start because its session is already busy."""

    def __init__(
        self,
        *,
        reason: str,
        message: str = "session is busy",
        active_run_id: str = "",
    ) -> None:
        self.reason = str(reason or "active_operation_exists")
        self.active_run_id = str(active_run_id or "")
        super().__init__(message)

    @property
    def data(self) -> dict[str, str]:
        payload = {
            "code": "SESSION_BUSY",
            "reason": self.reason,
        }
        if self.active_run_id:
            payload["active_run_id"] = self.active_run_id
        return payload


@dataclass
class CoreLiveOperationHost:
    """Owns reusable live-operation dependencies and catalog handlers."""

    session_factory: Callable[[], Any]
    persistence: AppPersistenceHost
    hub: CoreAppEventHub = field(default_factory=lambda: default_hub)
    runtime_task_registry: Any = field(default_factory=default_runtime_task_registry)
    runtime_state_store: RuntimeStateStore | None = None
    product_operation_executors: dict[str, Any] = field(default_factory=dict)
    operation_executors: dict[str, Any] = field(default_factory=dict)
    member_hooks: Any = field(default_factory=DefaultCoreLiveMemberHooks)
    # Optional LLM client + model id used for side-channel tasks such as
    # auto-generating a session title from the first user message. May be None
    # when the host is constructed without a model provider (e.g. tests).
    llm_client: Any = None
    default_model_id: str = ""
    # Optional session store used to persist auto-generated titles. When None,
    # title generation still runs but the result is only broadcast, not stored.
    session_store: Any = None
    # user:“在正常的目标终止之后，还会多发这条消息出去”+(续跑前核对目标的当前状态)。
    goal_manager: Any = None
    # Global journal used by Local-First mobile clients. It is optional so the
    # operation host remains usable in focused unit tests.
    sync_journal: Any = None
    # Shared by every live connection created for this host.  The registry
    # serializes only short state mutations; it never owns the long-running
    # Agent task, which continues through RuntimeTaskRegistry.
    session_actors: SessionActorRegistry = field(default_factory=SessionActorRegistry)
    # user:“失败回合结束后会话仍被判为‘有活跃回合’”+(保留终态写入失败的修复意图，下次发消息先收尾)。
    pending_terminal_failures: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)
    _handlers: dict[str, OperationHandler] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        product_executors = {**self.operation_executors, **self.product_operation_executors}
        forbidden = sorted(set(product_executors).intersection(CORE_WORKBENCH_OPERATION_NAMES))
        if forbidden:
            raise ValueError(f"base live operation executors cannot be overridden: {', '.join(forbidden)}")
        self.product_operation_executors = product_executors
        self.persistence.bind_session_factory(self.session_factory)
        names = {*CORE_WORKBENCH_OPERATION_NAMES, *self.product_operation_executors}
        self._handlers = {name: self._build_catalog_handler(name) for name in names}

    @property
    def event_store(self) -> SqlAlchemyAppEventStore:
        return self.persistence.event_store

    @property
    def snapshot_store(self) -> SqlAlchemyThreadSnapshotStore:
        return self.persistence.snapshot_store

    def operation_handlers(self) -> dict[str, OperationHandler]:
        return dict(self._handlers)

    async def execute(
        self,
        name: str,
        *,
        request_id: int | str | None,
        params: dict[str, Any],
        context: "CoreLiveContext",
    ) -> "CoreLiveOperationOutcome":
        from .dispatch import _CORE_LIVE_OPERATION_EXECUTORS
        from .params import _serialized_actor_key, _thread_id_from_params
        if name == "approval.respond":
            try:
                params = (await normalize_approval_request(params)).to_dict()
            except ValueError as exc:
                return CoreLiveOperationOutcome(
                    response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
                )

        async def invoke() -> CoreLiveOperationOutcome:
            handler = _CORE_LIVE_OPERATION_EXECUTORS.get(name)
            if handler is not None:
                return await handler(request_id=request_id, params=params, context=context)
            handler = self.product_operation_executors.get(name)
            if handler is not None:
                return await handler(request_id=request_id, params=params, context=context)
            if not context.operations.has(name):
                raise KeyError(f"Unsupported core live operation: {name}")
            result = await context.operations.execute(name, params, metadata={"source": "core_live"})
            payload = dict(result.payload or {})
            if result.status != "ok":
                return CoreLiveOperationOutcome(
                    response=rpc_error(
                        request_id,
                        code=INVALID_REQUEST,
                        message=str(payload.get("error") or result.status),
                        data=payload,
                    )
                )
            return CoreLiveOperationOutcome(response=rpc_result(request_id, payload))

        try:
            actor_key = _serialized_actor_key(name, params)
            if actor_key:
                if name == "turn.start":
                    # 会话已有活跃回合时，答案不会随等待改变（回合结束前一直活跃），
                    # 而排队在 session actor / 写协调器后面会先等数秒再回 busy（实测
                    # 1.6s / 13.1s / 26.5s）。注册表里的 run 认领就是排他依据，所以在
                    # 进入串行化之前先短路：SESSION_BUSY 立即可答。排他性不变——若注册
                    # 表没有认领，仍旧走原来的 actor + 写内判定（含 client_message_id
                    # 去重）。带同一 client_message_id 的重试先做索引回执查询，
                    # 已接受的提交返回原回执；其他请求仍立即 SESSION_BUSY。
                    active_run_id = self.runtime_task_registry.active_run_id(
                        _thread_id_from_params(params)
                    )
                    if active_run_id:
                        client_id = str(params.get("client_message_id") or params.get("clientMessageId") or "")
                        if client_id:
                            async with context.session_factory() as db:
                                accepted = await context.persistence.find_client_event(
                                    db, thread_id=_thread_id_from_params(params),
                                    client_message_id=client_id, methods=TURN_ACCEPTED_METHODS,
                                )
                            if accepted is not None:
                                return CoreLiveOperationOutcome(response=rpc_result(
                                    request_id, {"events": [accepted.to_dict()]},
                                ))
                            # user:“turn.start 返回‘忙’，但那一轮实际上已经在后台跑起来”+(认领先于提交，同一请求重试必须等接收事务结束后再判定)。
                            return await self.session_actors.run(actor_key, invoke)
                        return CoreLiveOperationOutcome(
                            response=rpc_error(
                                request_id,
                                code=INVALID_REQUEST,
                                message="session has an active turn",
                                data={
                                    "code": "SESSION_BUSY",
                                    "reason": "active_turn_exists",
                                    "active_run_id": active_run_id,
                                },
                            )
                        )
                # Ordinary composer commands are short state mutations. Do
                # not queue a second request behind one that may be waiting
                # on an external command; report the conflict immediately.
                if name == "command.execute":
                    return await self.session_actors.try_run(actor_key, invoke)
                return await self.session_actors.run(actor_key, invoke)
            return await invoke()
        except SessionActorBusyError:
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message="session has an active operation",
                    data={
                        "code": "SESSION_BUSY",
                        "reason": "active_operation_exists",
                    },
                )
            )
        except RevisionConflictError as exc:
            return CoreLiveOperationOutcome(
                response=rpc_error(
                    request_id,
                    code=INVALID_REQUEST,
                    message="Revision conflict; refresh the session and retry explicitly",
                    data=exc.data,
                )
            )

    def _build_catalog_handler(self, name: str) -> OperationHandler:
        from .params import _thread_id_from_params
        async def handle(request: OperationRequest) -> OperationResult:
            connection = request.metadata.get("connection")
            rpc_request = request.metadata.get("rpc_request")
            params = dict(request.payload)
            if not _thread_id_from_params(params) and connection is not None:
                thread_id = getattr(connection, "thread_id", None)
                if thread_id:
                    params["thread_id"] = thread_id
            if connection is not None:
                thread_id = _thread_id_from_params(params)
                switch_subscription = getattr(connection, "switch_thread_subscription", None)
                if thread_id and callable(switch_subscription):
                    switch_subscription(thread_id)
            request_id = getattr(rpc_request, "id", None)
            context = getattr(connection, "context", None)
            if not isinstance(context, CoreLiveContext):
                raise TypeError("core live connection context is required")
            outcome = await self.execute(name, request_id=request_id, params=params, context=context)
            await connection.send_operation_outcome(outcome, publish_events=False)
            return OperationResult(name=request.name, metadata={"live_response_sent": True})

        return handle


@dataclass(frozen=True)
class CoreLiveContext:
    operations: OperationCatalog
    session_factory: Callable[[], Any] | None = None
    event_store: SqlAlchemyAppEventStore | None = None
    snapshot_store: SqlAlchemyThreadSnapshotStore | None = None
    hub: CoreAppEventHub = field(default_factory=lambda: default_hub)
    persistence: AppPersistenceHost | None = None
    runtime_task_registry: Any = field(default_factory=default_runtime_task_registry)
    runtime_state_store: RuntimeStateStore | None = None
    session_actors: SessionActorRegistry = field(default_factory=SessionActorRegistry)
    host: CoreLiveOperationHost | None = None
    _job_waiters: dict[str, list[asyncio.Future[Any]]] = field(
        default_factory=dict, repr=False
    )
    _job_outcomes: dict[str, dict[str, Any]] = field(
        default_factory=dict, repr=False
    )

    def __post_init__(self) -> None:
        if self.host is not None:
            object.__setattr__(self, "session_factory", self.host.session_factory)
            object.__setattr__(self, "persistence", self.host.persistence)
            object.__setattr__(self, "event_store", self.host.event_store)
            object.__setattr__(self, "snapshot_store", self.host.snapshot_store)
            object.__setattr__(self, "hub", self.host.hub)
            object.__setattr__(self, "runtime_task_registry", self.host.runtime_task_registry)
            object.__setattr__(self, "runtime_state_store", self.host.runtime_state_store)
            object.__setattr__(
                self,
                "session_actors",
                getattr(self.host, "session_actors", self.session_actors),
            )
            return
        persistence = self.persistence
        if persistence is None:
            if self.event_store is None or self.snapshot_store is None:
                raise ValueError("event_store and snapshot_store are required when persistence is not provided")
            persistence = AppPersistenceHost(self.event_store, self.snapshot_store)
        if self.session_factory is None:
            raise ValueError("session_factory is required when host is not provided")
        object.__setattr__(self, "persistence", persistence)
        object.__setattr__(self, "event_store", persistence.event_store)
        object.__setattr__(self, "snapshot_store", persistence.snapshot_store)
        object.__setattr__(
            self,
            "host",
            CoreLiveOperationHost(
                session_factory=self.session_factory,
                persistence=persistence,
                hub=self.hub,
                runtime_task_registry=self.runtime_task_registry,
                runtime_state_store=self.runtime_state_store,
                session_actors=self.session_actors,
            ),
        )

    @property
    def turn_store(self) -> Any:
        """Lazy read-model store for turns, runs, interactions and jobs."""
        cached = getattr(self, "_turn_store_cache", None)
        if cached is not None:
            return cached
        from lamtools_core.turn.store import TurnStore

        store = TurnStore(self.session_factory, self.persistence.write_coordinator)
        object.__setattr__(self, "_turn_store_cache", store)
        return store

    @property
    def turn_worker(self) -> Any:
        """Durable continuation worker bound to this live context."""
        from .continuations import _execute_continuation_job
        cached = getattr(self, "_turn_worker_cache", None)
        if cached is not None:
            return cached
        from lamtools_core.turn.worker import TurnWorker

        worker = TurnWorker(
            self.turn_store,
            lambda job: _execute_continuation_job(context=self, job=job),
            # Continuations converge inside the operation (success or a
            # persisted failure), so an exception is not retried blindly: a
            # replayed kernel could execute tools twice. A crash instead leaves
            # the job leased and startup recovery reclaims it.
            max_attempts=1,
            retry_delay_ms=0,
            poll_seconds=0.1,
        )
        object.__setattr__(self, "_turn_worker_cache", worker)
        return worker


@dataclass
class CoreLiveOperationOutcome:
    response: dict[str, Any]
    notify_events: list[AppEventEnvelope] = field(default_factory=list)
    publish_events: list[AppEventEnvelope] = field(default_factory=list)
    runtime_start: dict[str, Any] | None = None
