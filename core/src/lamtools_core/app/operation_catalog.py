"""Operation catalog for shared CLI, GUI, and HTTP entry points."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OperationRequest:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OperationResult:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"
    metadata: dict[str, Any] = field(default_factory=dict)


OperationHandler = Callable[[OperationRequest], OperationResult | Awaitable[OperationResult]]
OperationAvailability = Callable[[], bool]


def normalize_operation_name(name: str, aliases: dict[str, str] | None = None) -> str:
    alias_map = aliases or {}
    normalized = alias_map.get(name, name.replace("/", "."))
    return alias_map.get(normalized, normalized)


class OperationCatalog:
    def __init__(self) -> None:
        self._handlers: dict[str, OperationHandler] = {}
        self._owners: dict[str, str] = {}
        self._availability: dict[str, OperationAvailability] = {}
        # G 组：插件 operations 注册失败明细（hard_block/导入失败/同名冲突），
        # catalog 构建方写入，供上层（RPC 面 / 调试）检查；缺省空列表。
        self.plugin_operation_errors: list[dict[str, Any]] = []

    def register(
        self,
        name: str,
        handler: OperationHandler,
        *,
        owner: str = "",
        availability: OperationAvailability | None = None,
    ) -> None:
        if not name:
            raise ValueError("operation name is required")
        if name in self._handlers:
            raise ValueError(f"operation '{name}' already registered")
        self._handlers[name] = handler
        if owner:
            self._owners[name] = str(owner)
        if availability is not None:
            self._availability[name] = availability

    def _is_available(self, name: str) -> bool:
        predicate = self._availability.get(name)
        if predicate is None:
            return True
        try:
            return bool(predicate())
        except Exception:
            return False

    def has(self, name: str) -> bool:
        return name in self._handlers and self._is_available(name)

    def list(self) -> list[str]:
        return sorted(name for name in self._handlers if self._is_available(name))

    def registered(self) -> list[str]:
        """Return every registered operation, including unavailable ones.

        Hosts that wrap a plugin catalog need to mount the complete stable
        surface once so a later plugin enable transition can make an
        operation available without rebuilding the host catalog. Callers
        that advertise or execute operations should continue to use list or
        has so unavailable entries remain hidden.
        """
        return sorted(self._handlers)

    def owner_of(self, name: str) -> str:
        return self._owners.get(name, "")

    async def execute(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> OperationResult:
        handler = self._handlers.get(name)
        if handler is None or not self._is_available(name):
            raise KeyError(f"operation '{name}' is not registered")
        request = OperationRequest(name=name, payload=dict(payload or {}), metadata=dict(metadata or {}))
        result = handler(request)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, OperationResult):
            raise TypeError(f"operation '{name}' must return OperationResult")
        return result


__all__ = [
    "normalize_operation_name",
    "OperationCatalog",
    "OperationHandler",
    "OperationAvailability",
    "OperationRequest",
    "OperationResult",
]
