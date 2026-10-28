"""Process-local handles for the QQ bot plugin.

The host loads operations and tools as separate modules.  A multi-bot manager
owns the per-bot runtimes; the current inbound message/turn carries its runtime
through a contextvar so tools act on the bot that received the message.
"""

from __future__ import annotations

import contextvars
from typing import Any

_MANAGER: Any | None = None
_RUNTIME: Any | None = None
_CURRENT_RUNTIME: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "qqbot_current_runtime",
    default=None,
)


def set_manager(manager: Any | None) -> None:
    global _MANAGER
    _MANAGER = manager


def get_manager() -> Any | None:
    return _MANAGER


def set_runtime(runtime: Any | None) -> None:
    """Legacy single-runtime handle (kept for tests and old host paths)."""
    global _RUNTIME
    _RUNTIME = runtime


def get_runtime() -> Any | None:
    current = _CURRENT_RUNTIME.get()
    if current is not None:
        return current
    manager = _MANAGER
    if manager is not None:
        default = getattr(manager, "default_bot", None)
        if callable(default):
            runtime = default()
            if runtime is not None:
                return runtime
    return _RUNTIME


def set_current_runtime(runtime: Any | None) -> contextvars.Token:
    return _CURRENT_RUNTIME.set(runtime)


def reset_current_runtime(token: contextvars.Token) -> None:
    try:
        _CURRENT_RUNTIME.reset(token)
    except ValueError:
        pass


__all__ = [
    "set_manager",
    "get_manager",
    "set_runtime",
    "get_runtime",
    "set_current_runtime",
    "reset_current_runtime",
]
