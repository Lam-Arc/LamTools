"""The 主动记忆 (Memory) switch — one setting, two behaviours.

PRD 7.1: the switch gates ``memory.md`` automatic injection and the background
Dreaming pass; it never touches the stored files, the ``memory`` tool or any
manual read/edit surface.

The namespace lives in the shared ``settings.jsonc`` (``core.memory``) so the
desktop settings UI and the mobile client read the same value.  An absent
namespace means "on" — the feature is on by default and the file only records
a deliberate choice.
"""

from __future__ import annotations

from typing import Any

from lamtools_core.config.settings_store import get_setting, set_setting

MEMORY_NAMESPACE = "core.memory"


def memory_settings() -> dict[str, Any]:
    """The raw namespace value (empty when never written)."""
    value = get_setting(MEMORY_NAMESPACE)
    return dict(value) if isinstance(value, dict) else {}


def memory_enabled() -> bool:
    """Whether 主动记忆 is on (default: on)."""
    value = memory_settings().get("enabled")
    return True if value is None else bool(value)


def set_memory_enabled(enabled: bool) -> None:
    """Persist the switch; the next model request sees the new value."""
    set_setting(MEMORY_NAMESPACE, {"enabled": bool(enabled)})


__all__ = ["MEMORY_NAMESPACE", "memory_enabled", "memory_settings", "set_memory_enabled"]
