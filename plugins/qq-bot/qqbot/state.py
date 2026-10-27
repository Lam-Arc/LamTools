"""Process-local handle to the running QQ bot backend.

Operation handlers and native tools are loaded as separate modules by the
host; they share the backend instance through this small module instead of
importing the backend loader.
"""

from __future__ import annotations

from typing import Any

_RUNTIME: Any | None = None


def set_runtime(runtime: Any | None) -> None:
    global _RUNTIME
    _RUNTIME = runtime


def get_runtime() -> Any | None:
    return _RUNTIME


__all__ = ["set_runtime", "get_runtime"]
