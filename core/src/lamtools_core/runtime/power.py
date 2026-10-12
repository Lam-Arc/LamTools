"""Keep the machine awake while Sunday runs.

Setting (设置 → 通用): ``settings.jsonc`` → ``core.keepAwake`` = ``{"enabled": bool}``.

Sleep kills long turns — a multi-minute image/video pipeline or a long tool
run simply stops when Windows suspends.  The state is applied to the process
that owns the event loop (``SetThreadExecutionState``'s ``ES_CONTINUOUS``
request is tied to the calling thread, so a short-lived worker thread would
drop it the moment it exits) and re-applied whenever the setting changes.

Only Windows exposes this switch; elsewhere the setting is reported as
unsupported instead of pretending it took effect.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from lamtools_core.config.settings_store import get_setting

logger = logging.getLogger(__name__)

KEEP_AWAKE_NAMESPACE = "core.keepAwake"

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001

_applied = False


def platform_supported() -> bool:
    """True when this platform has a working keep-awake switch."""
    return sys.platform == "win32"


def _set_execution_state(flags: int) -> int | None:
    """Call ``SetThreadExecutionState``; ``None`` when the platform lacks it."""
    if not platform_supported():
        return None
    try:
        import ctypes

        return int(ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags)))
    except Exception:  # pragma: no cover - defensive: never break startup on this
        logger.warning("[power] SetThreadExecutionState failed", exc_info=True)
        return 0


def keep_awake_enabled() -> bool:
    stored = get_setting(KEEP_AWAKE_NAMESPACE)
    return bool(isinstance(stored, dict) and stored.get("enabled"))


def merge_keep_awake(current: Any, incoming: dict[str, Any]) -> dict[str, Any] | None:
    """Merge a ``core.keepAwake`` update; ``None`` rejects an invalid value."""
    merged = {**(current if isinstance(current, dict) else {})}
    for key, raw in incoming.items():
        if key != "enabled":
            # Unknown keys are dropped rather than persisted.
            continue
        if not isinstance(raw, bool):
            return None
        merged[key] = raw
    merged.setdefault("enabled", False)
    return merged


def apply_keep_awake(enabled: bool | None = None) -> bool:
    """Apply the stored (or given) state; returns True while the machine is held awake.

    A failure is not fatal: the app keeps running and the settings page still
    shows the stored preference.
    """
    global _applied
    wanted = keep_awake_enabled() if enabled is None else bool(enabled)
    flags = _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED if wanted else _ES_CONTINUOUS
    result = _set_execution_state(flags)
    if result is None:
        _applied = False
        if wanted:
            logger.info("[power] keep-awake is not supported on %s; setting stored but inactive", sys.platform)
        return _applied
    if wanted and result == 0:
        logger.warning("[power] keep-awake request was refused by the OS")
        _applied = False
        return _applied
    _applied = wanted
    return _applied


def is_applied() -> bool:
    """True when the machine is currently being held awake by this process."""
    return _applied


def keep_awake_status() -> dict[str, Any]:
    return {
        "enabled": keep_awake_enabled(),
        "applied": is_applied(),
        "supported": platform_supported(),
    }


__all__ = [
    "KEEP_AWAKE_NAMESPACE",
    "apply_keep_awake",
    "is_applied",
    "keep_awake_enabled",
    "keep_awake_status",
    "merge_keep_awake",
    "platform_supported",
]
