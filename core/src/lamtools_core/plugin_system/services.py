"""Owned service publications and effects, driven by the existing lifecycle.

user:“宿主能力补齐和接口完善与文档更新”+(以插件启动为注册事务，成功后公开，失败/停用撤回，旧句柄不能进入新代际)。
"""

from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


class ServiceError(RuntimeError):
    def __init__(self, code: str, name: str, message: str) -> None:
        self.code, self.service = code, name
        super().__init__(f"{code}: {name}: {message}")


@dataclass(frozen=True)
class ServiceKey(Generic[T]):
    name: str
    version: int = 1
    protocol: type[T] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", self.name):
            raise ValueError("service name must be a non-empty dotted name")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("service version must be a positive integer")

    def validate(self, value: T) -> None:
        if value is None:
            raise TypeError(f"service '{self.name}' cannot be None")
        if self.protocol is not None and not isinstance(value, self.protocol):
            raise TypeError(f"service '{self.name}' does not implement its protocol")


def service_key(key: ServiceKey[T] | str) -> ServiceKey[T]:
    if isinstance(key, str):
        return ServiceKey(key)
    if not isinstance(key, ServiceKey):
        raise TypeError("service key must be a name or ServiceKey")
    return key


@dataclass(eq=False)
class ServiceRegistration(Generic[T]):
    scope: RegistrationScope
    key: ServiceKey[T]
    value: T
    live: bool = True

    def __call__(self) -> None:
        """Withdraw this exact registration; old disposers cannot delete new ones."""
        if not self.live:
            return
        self.live = False
        registry = self.scope.registry
        if registry.records.get(self.key.name) is self:
            registry.records.pop(self.key.name)
            if registry.values.get(self.key.name) is self.value:
                registry.values.pop(self.key.name)
        if self.scope.entries.get(self.key.name) is self:
            self.scope.entries.pop(self.key.name)


class HostServiceRegistry:
    """Metadata for owned entries in the existing service map, not a new host."""
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values
        self.records: dict[str, ServiceRegistration] = {}

    def record(self, name: str) -> ServiceRegistration | None:
        registration = self.records.get(name)
        if registration is not None and self.values.get(name) is registration.value:
            return registration
        return None


class ServiceRef(Generic[T]):
    """Pins both provider and requester epochs; call() owns an in-flight lease.

    get() checks validity but returns a trusted Python object. A caller that
    retains that raw object bypasses future checks; use call() for draining.
    """
    def __init__(self, key: ServiceKey[T], resolver: Callable[[], tuple[Any, Any]],
                 requester: RegistrationScope | None) -> None:
        self.key, self._resolver, self._requester = key, resolver, requester
        self._value, self._token = resolver()
        self._provider = self._token.scope if isinstance(self._token, ServiceRegistration) else None
        version = self._token.key.version if isinstance(self._token, ServiceRegistration) else 1
        if key.version != version:
            raise ServiceError("service/version", key.name, f"requested version {key.version}, available {version}")
        key.validate(self._value)

    def get(self) -> T:
        if self._requester is not None and not self._requester.accepting:
            raise ServiceError("service/requester-stopped", self.key.name, "requester epoch is revoked")
        value, token = self._resolver()
        if value is not self._value or token is not self._token:
            raise ServiceError("service/stale", self.key.name, "provider was replaced or withdrawn")
        return value

    async def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        value = self.get()
        if not isinstance(method, str) or method.startswith("_"):
            raise ValueError("service method must be a public name")
        callback = getattr(value, method, None)
        if not callable(callback):
            raise ServiceError("service/method", self.key.name, f"method '{method}' is unavailable")
        scopes = list(dict.fromkeys(s for s in (self._provider, self._requester) if s is not None))
        acquired: list[RegistrationScope] = []
        try:
            for scope in scopes:
                scope.acquire()
                acquired.append(scope)
            result = callback(*args, **kwargs)
            return await result if inspect.isawaitable(result) else result
        finally:
            for scope in reversed(acquired):
                scope.release()


class RegistrationScope:
    """One managed start's owned registrations, call leases and cleanup stack."""
    def __init__(self, registry: HostServiceRegistry, owner: str, epoch: int) -> None:
        self.registry, self.owner, self.epoch = registry, owner, epoch
        self.accepting = True
        self.published = False
        self.disposed = False
        self.entries: dict[str, ServiceRegistration] = {}
        self.dependencies: list[ServiceRef] = []
        self._cleanups: list[Callable] = []
        self._calls: dict[asyncio.Task, int] = {}
        self._idle = asyncio.Event()
        self._idle.set()
        self._dispose_task: asyncio.Task | None = None

    def check_open(self) -> None:
        if not self.accepting:
            raise ServiceError("service/scope-closed", self.owner, "registration epoch is revoked")

    def local(self, name: str) -> ServiceRegistration | None:
        return self.entries.get(name) if self.accepting else None

    def register(self, key: ServiceKey[T], value: T) -> ServiceRegistration[T]:
        self.check_open()
        key.validate(value)
        if key.name in self.entries or self.published and key.name in self.registry.values:
            raise ServiceError("service/conflict", key.name, "service name already registered")
        entry = ServiceRegistration(self, key, value)
        self.entries[key.name] = entry
        if self.published:
            self.registry.records[key.name] = entry
            self.registry.values[key.name] = value
        return entry

    def publish(self, reserved: set[str]) -> None:
        self.check_open()
        # There is no await between preflight and commit, so two concurrent
        # plugin starts cannot each publish half of a conflicting batch.
        for dependency in self.dependencies:
            dependency.get()
        for name in self.entries:
            if name in self.registry.values or name in reserved:
                raise ServiceError("service/conflict", name, "service name already registered or exported")
        for name, entry in self.entries.items():
            self.registry.records[name] = entry
            self.registry.values[name] = entry.value
        self.published = True

    def revoke(self) -> None:
        self.accepting = False
        for entry in list(self.entries.values()):
            entry()

    def on_dispose(self, callback: Callable) -> None:
        self.check_open()
        if not callable(callback):
            raise TypeError("disposer must be callable")
        self._cleanups.append(callback)

    def effect(self, setup: Callable[[], Callable]) -> None:
        self.check_open()
        cleanup = setup()
        if inspect.isawaitable(cleanup):
            if inspect.iscoroutine(cleanup):
                cleanup.close()
            raise TypeError("effect setup must be synchronous; use async start and on_dispose")
        self.on_dispose(cleanup)

    def acquire(self) -> None:
        self.check_open()
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("service calls require an asyncio task")
        self._calls[task] = self._calls.get(task, 0) + 1
        self._idle.clear()

    def release(self) -> None:
        task = asyncio.current_task()
        count = self._calls.get(task, 0)
        if count > 1:
            self._calls[task] = count - 1
        else:
            self._calls.pop(task, None)
        if not self._calls:
            self._idle.set()

    async def drain(self) -> None:
        self.check_can_drain()
        await self._idle.wait()

    def check_can_drain(self) -> None:
        if asyncio.current_task() in self._calls:
            raise ServiceError("service/self-stop", self.owner, "cannot stop a plugin from its own active service call")

    async def dispose(self) -> None:
        self.revoke()
        await self.drain()
        if self.disposed:
            return
        if self._dispose_task is None or self._dispose_task.done():
            self._dispose_task = asyncio.create_task(self._dispose(), name=f"plugin:{self.owner}:effects")
            self._dispose_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        # Cancellation belongs to the stop caller; cleanup remains owned and
        # the existing lifecycle deadline/retry path can rejoin this task.
        await asyncio.shield(self._dispose_task)

    async def _dispose(self) -> None:
        failures: list[Exception] = []
        retry: list[Callable] = []
        while self._cleanups:
            cleanup = self._cleanups.pop()
            try:
                result = cleanup()
                if inspect.isawaitable(result):
                    await result
            except (Exception, asyncio.CancelledError) as error:
                retry.append(cleanup)
                failures.append(RuntimeError("cleanup cancelled") if isinstance(error, asyncio.CancelledError) else error)
        self._cleanups = list(reversed(retry))
        if failures:
            raise ExceptionGroup("plugin effect cleanup failed", failures)
        self.disposed = True


__all__ = ["ServiceKey", "ServiceRef", "ServiceError"]
