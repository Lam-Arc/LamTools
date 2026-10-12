"""Host-memory guard: name memory-caused interruptions and resume after recovery.

Setting (设置 → 通用): ``settings.jsonc`` → ``core.memoryResume`` =
``{"enabled": bool, "threshold_gb": number}``.

When the machine runs out of memory mid-turn the backend cannot allocate, the
turn dies, and — worse — the failure itself may not be recordable.  This module
gives that failure a name (:data:`HOST_MEMORY_EXHAUSTED`), the user-facing text
that states the resume threshold, and the host reading the resume watchdog
polls (``available_memory_bytes``).

The threshold is measured against *available commit* — physical memory plus
what the page file can still back (Windows reports it as available virtual
memory).  A bare "free physical RAM" number would call a machine with a large
page file exhausted while it still has plenty of room to allocate.

Only Windows and Linux expose the reading; elsewhere the feature reports itself
unsupported instead of pretending it will resume.
"""

from __future__ import annotations

import errno
import logging
import sys
import time
from typing import Any

from lamtools_core.config.settings_store import get_setting

logger = logging.getLogger(__name__)

MEMORY_RESUME_NAMESPACE = "core.memoryResume"

#: Reason code carried on the terminal record of a memory-caused interruption.
HOST_MEMORY_EXHAUSTED = "host_memory_exhausted"

#: 连续自动续跑上限：连着这么多次都还是内存不足，就停下来交给人处理，
#: 免得"续跑 → 再中断"来回空转。
MEMORY_RESUME_MAX_ATTEMPTS = 3

#: Metadata key holding the armed resume. It is a ONE-SHOT token: the watchdog
#: deletes it before it starts the continuation, so nothing resumes twice.
MEMORY_RESUME_KEY = "memory_resume"

#: Metadata key recording that an interruption was already dealt with, so a
#: later start cannot arm the same interruption again.
MEMORY_RESUME_HANDLED_KEY = "memory_resume_handled_turn"

#: 默认阈值：可用内存（物理内存 + 页面文件）回到这个量以上才自动继续。
DEFAULT_THRESHOLD_GB = 4.0

#: 一台机器少于这个量就没有继续的意义，兼容住异常小的配置值。
MIN_THRESHOLD_GB = 0.5
MAX_THRESHOLD_GB = 1024.0


def platform_supported() -> bool:
    """True when this platform can report available memory."""
    return sys.platform in {"win32", "linux"}


def _windows_available_bytes() -> int | None:
    """Available commit (physical + page file) via ``GlobalMemoryStatusEx``."""
    try:
        import ctypes

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(status.ullAvailPageFile)
    except Exception:  # pragma: no cover - defensive: never break a run on this
        logger.warning("[memory] GlobalMemoryStatusEx failed", exc_info=True)
        return None


def _linux_available_bytes() -> int | None:
    """Available memory + free swap from ``/proc/meminfo``."""
    try:
        available_kb = 0
        swap_kb = 0
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                value = rest.strip().split(" ", 1)[0]
                if not value.isdigit():
                    continue
                if key == "MemAvailable":
                    available_kb = int(value)
                elif key == "SwapFree":
                    swap_kb = int(value)
        if not available_kb:
            return None
        return (available_kb + swap_kb) * 1024
    except Exception:  # pragma: no cover - defensive: never break a run on this
        logger.warning("[memory] /proc/meminfo unavailable", exc_info=True)
        return None


def available_memory_bytes() -> int | None:
    """Bytes the machine can still allocate (physical + page file), or ``None``."""
    if sys.platform == "win32":
        return _windows_available_bytes()
    if sys.platform == "linux":
        return _linux_available_bytes()
    return None


def available_memory_gb() -> float | None:
    raw = available_memory_bytes()
    return None if raw is None else round(raw / (1024**3), 2)


def memory_resume_enabled() -> bool:
    """「内存中断自动续跑」是否开启；未配置时默认开启。"""
    stored = get_setting(MEMORY_RESUME_NAMESPACE)
    if not isinstance(stored, dict):
        return True
    value = stored.get("enabled")
    return True if value is None else bool(value)


def resume_threshold_gb() -> float:
    """Stored resume threshold in GB; falls back to the default."""
    stored = get_setting(MEMORY_RESUME_NAMESPACE)
    if not isinstance(stored, dict):
        return DEFAULT_THRESHOLD_GB
    raw = stored.get("threshold_gb")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return DEFAULT_THRESHOLD_GB
    value = float(raw)
    if not MIN_THRESHOLD_GB <= value <= MAX_THRESHOLD_GB:
        return DEFAULT_THRESHOLD_GB
    return value


def resume_threshold_bytes() -> int:
    return int(resume_threshold_gb() * (1024**3))


def merge_memory_resume(current: Any, incoming: dict[str, Any]) -> dict[str, Any] | None:
    """Merge a ``core.memoryResume`` update; ``None`` rejects an invalid value."""
    merged = {**(current if isinstance(current, dict) else {})}
    for key, raw in incoming.items():
        if key == "enabled":
            if not isinstance(raw, bool):
                return None
            merged[key] = raw
            continue
        if key == "threshold_gb":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                return None
            value = float(raw)
            if not MIN_THRESHOLD_GB <= value <= MAX_THRESHOLD_GB:
                return None
            merged[key] = value
            continue
        # Unknown keys are dropped rather than persisted.
    merged.setdefault("enabled", True)
    merged.setdefault("threshold_gb", DEFAULT_THRESHOLD_GB)
    return merged


def resume_ready() -> bool:
    """Whether available memory has reached the threshold yet."""
    available = available_memory_bytes()
    if available is None:
        return False
    return available >= resume_threshold_bytes()


def is_memory_exhaustion(exc: BaseException) -> bool:
    """Whether an exception looks like the host refusing to allocate.

    ``MemoryError`` covers a normal failed allocation; the ``OSError`` variants
    cover Windows refusing to grow the page file / Linux hitting the commit
    limit, which surface as allocation errors too.
    """
    if isinstance(exc, MemoryError):
        return True
    if isinstance(exc, OSError):
        # 12 = ENOMEM on every platform Python reports; 1455 =
        # ERROR_COMMITMENT_LIMIT, which is what Windows answers when the commit
        # limit (RAM + page file) is reached.
        if getattr(exc, "errno", None) == errno.ENOMEM:
            return True
        if getattr(exc, "winerror", None) == 1455:
            return True
    return False


def failure_code_for(exc: BaseException) -> str:
    """Machine-readable interruption code for a terminal failure."""
    return HOST_MEMORY_EXHAUSTED if is_memory_exhaustion(exc) else ""


def _looks_like_memory_error(text: str) -> bool:
    value = (text or "").strip().lower()
    if not value:
        return False
    return value in {"memoryerror", "out of memory", "cannot allocate memory"} or "memoryerror" in value


def state_is_memory_exhaustion(state: Any) -> bool:
    """Whether a runtime state records a memory-caused interruption.

    Beyond the explicit :data:`HOST_MEMORY_EXHAUSTED` code this also accepts the
    evidence builds before that code existed left behind: the failure the
    approval-resolution fallback kept was the bare exception name, and a bare
    ``MemoryError`` is the host refusing to allocate.
    """
    metadata = _metadata(state)
    if str(metadata.get("failure_code") or "") == HOST_MEMORY_EXHAUSTED:
        return True
    resolution = metadata.get("approval_resolution")
    if isinstance(resolution, dict) and _looks_like_memory_error(str(resolution.get("error") or "")):
        return True
    return False


def memory_exhausted_message() -> str:
    """User-facing interruption text, stating when the turn resumes."""
    if not memory_resume_enabled():
        return (
            "本机内存不足，本轮已中断。可用内存（物理内存 + 页面文件）恢复后，"
            "可在 设置 → 通用 打开「内存中断自动续跑」再继续。"
        )
    threshold = resume_threshold_gb()
    shown = f"{threshold:g}"
    if not platform_supported():
        return f"本机内存不足，本轮已中断（当前平台不支持自动续跑，可用内存需大于 {shown} GB）。"
    return (
        f"本机内存不足，本轮已中断。可用内存（物理内存 + 页面文件）大于 "
        f"{shown} GB 时 Sunday 会自动继续。"
    )


def memory_resume_started_message() -> str:
    """Opening line of the continuation turn."""
    return "上一轮因本机内存不足中断，现已自动继续。"


def memory_resume_exhausted_message(resumes: int) -> str:
    """Text for giving up after repeated resumes that ran out of memory again."""
    return (
        f"本机内存不足，本轮已中断；已连续自动继续 {resumes} 次仍未能完成，"
        "不再自动继续，请释放内存后手动继续。"
    )


def memory_resume_status() -> dict[str, Any]:
    return {
        "enabled": memory_resume_enabled(),
        "threshold_gb": resume_threshold_gb(),
        "supported": platform_supported(),
        "available_gb": available_memory_gb(),
        "ready": resume_ready(),
    }


# ── Interruption / pending-resume bookkeeping on a runtime state ─────────────
#
# Everything lives in the state's metadata so it survives a restart: a machine
# that kills the process mid-turn must still know, once it is back, that a turn
# was interrupted by memory and is waiting to continue.


def _metadata(state: Any) -> dict[str, Any]:
    metadata = getattr(state, "metadata", None)
    return metadata if isinstance(metadata, dict) else {}


def note_memory_interruption(state: Any) -> str:
    """Record a memory-caused interruption on ``state`` and arm the resume.

    Returns the user-facing explanation (what happened, when it resumes).

    The armed resume is a one-shot token for *this* interruption: the turn id
    that was interrupted is recorded alongside it, and a previous interruption's
    "already handled" mark is dropped. Without that, a session that was once
    interrupted would be continued again on every later start — the reason has
    to stay readable in the record, so the reason itself cannot be the token.
    """
    message = memory_exhausted_message()
    metadata = _metadata(state)
    turn_id = str(getattr(state, "run_id", "") or "")
    metadata["failure_code"] = HOST_MEMORY_EXHAUSTED
    metadata["failure_message"] = message
    metadata["failure_turn_id"] = turn_id
    metadata["failure_at"] = time.time()
    metadata.pop(MEMORY_RESUME_HANDLED_KEY, None)
    metadata["memory_resume_attempts"] = memory_resume_attempts(state) + 1
    metadata[MEMORY_RESUME_KEY] = {
        "thread_id": str(getattr(state, "session_id", "") or ""),
        "turn_id": turn_id,
        "original_message": str(metadata.get("original_user_message") or ""),
        "threshold_gb": resume_threshold_gb(),
        "attempts": int(metadata["memory_resume_attempts"]),
        "created_at": time.time(),
    }
    return message


def clear_failure_detail(state: Any) -> None:
    """Drop a recorded failure explanation.

    Called when a new turn starts and when a turn ends for a non-memory reason:
    a stale reason must never be inherited by a later, unrelated failure — it
    would mislabel it and could arm a resume nothing asked for.
    """
    metadata = _metadata(state)
    metadata.pop("failure_code", None)
    metadata.pop("failure_message", None)
    metadata.pop("failure_turn_id", None)
    metadata.pop("failure_at", None)


def mark_memory_resume_handled(state: Any, turn_id: str) -> None:
    """Remember that this interruption was already dealt with (one-shot token)."""
    handled = str(turn_id or "").strip()
    if not handled:
        return
    _metadata(state)[MEMORY_RESUME_HANDLED_KEY] = handled


def memory_resume_handled(state: Any) -> str:
    return str(_metadata(state).get(MEMORY_RESUME_HANDLED_KEY) or "")


def interruption_turn_id(state: Any) -> str:
    """The turn a recorded interruption belongs to.

    Falls back to the state's own run id for records written before the turn id
    was stored: back then nothing could have been resumed after it, so the
    current run *was* the interrupted one.
    """
    recorded = str(_metadata(state).get("failure_turn_id") or "").strip()
    return recorded or str(getattr(state, "run_id", "") or "")


def interruption_is_current(state: Any) -> bool:
    """Whether the recorded interruption is still this session's latest turn.

    A resume (or a turn the user sent by hand) moves the session on; from then
    on the interruption is history and must never be continued again.
    """
    recorded = interruption_turn_id(state)
    if not recorded:
        return False
    current = str(getattr(state, "run_id", "") or "")
    return bool(current) and recorded == current


def memory_resume_attempts(state: Any) -> int:
    """How many memory interruptions happened in a row for this thread."""
    raw = _metadata(state).get("memory_resume_attempts")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0
    return max(0, raw)


def clear_memory_resume_streak(state: Any) -> None:
    """The chain broke — this turn did not end in memory exhaustion."""
    _metadata(state).pop("memory_resume_attempts", None)


def pending_memory_resume(state: Any) -> dict[str, Any] | None:
    """The armed auto-resume descriptor, when there is one."""
    pending = _metadata(state).get(MEMORY_RESUME_KEY)
    return pending if isinstance(pending, dict) else None


def clear_pending_memory_resume(state: Any) -> None:
    _metadata(state).pop(MEMORY_RESUME_KEY, None)


def ensure_pending_memory_resume(state: Any) -> bool:
    """Arm the resume for a recorded memory interruption, at most once.

    Strict by construction — this is the only thing that may start a turn nobody
    asked for, so all of these must hold:

    * the record really is a memory interruption,
    * it is still the session's *latest* turn (nothing ran after it),
    * it has not already been handled,
    * the switch is on and no resume is already armed.

    The old form of this — "the session was once interrupted by memory" — armed
    again on every start, which would have continued the same session forever.
    """
    metadata = _metadata(state)
    if not state_is_memory_exhaustion(state):
        return False
    if not memory_resume_enabled():
        return False
    if not interruption_is_current(state):
        return False
    if memory_resume_handled(state) == interruption_turn_id(state):
        return False
    if isinstance(metadata.get(MEMORY_RESUME_KEY), dict):
        return False
    if not str(metadata.get("failure_code") or ""):
        metadata["failure_code"] = HOST_MEMORY_EXHAUSTED
    if not str(metadata.get("failure_message") or ""):
        metadata["failure_message"] = memory_exhausted_message_for(state)
    metadata[MEMORY_RESUME_KEY] = {
        "thread_id": str(getattr(state, "session_id", "") or ""),
        "turn_id": interruption_turn_id(state),
        "original_message": str(metadata.get("original_user_message") or ""),
        "threshold_gb": resume_threshold_gb(),
        "attempts": memory_resume_attempts(state),
        "created_at": time.time(),
    }
    return True


def memory_resume_budget_exhausted(state: Any) -> bool:
    """Whether too many resumes in a row already failed on memory.

    ``memory_resume_attempts`` counts consecutive memory interruptions, so the
    resumes already spent are one fewer; the budget is spent once the current
    interruption would be the ``MEMORY_RESUME_MAX_ATTEMPTS + 1``-th.
    """
    return memory_resume_attempts(state) > MEMORY_RESUME_MAX_ATTEMPTS


def memory_resume_resumes_spent(state: Any) -> int:
    """How many automatic resumes this chain already used."""
    return max(0, memory_resume_attempts(state) - 1)


def memory_exhausted_message_for(state: Any) -> str:
    """Explanation for a state whose interruption was memory exhaustion.

    Unlike :func:`memory_exhausted_message` this accounts for a spent resume
    budget, so the text a user reads never promises a resume that will not come.
    """
    if memory_resume_budget_exhausted(state):
        return memory_resume_exhausted_message(memory_resume_resumes_spent(state))
    return memory_exhausted_message()


__all__ = [
    "DEFAULT_THRESHOLD_GB",
    "HOST_MEMORY_EXHAUSTED",
    "MEMORY_RESUME_HANDLED_KEY",
    "MEMORY_RESUME_KEY",
    "MEMORY_RESUME_MAX_ATTEMPTS",
    "MEMORY_RESUME_NAMESPACE",
    "available_memory_bytes",
    "available_memory_gb",
    "clear_failure_detail",
    "clear_memory_resume_streak",
    "clear_pending_memory_resume",
    "ensure_pending_memory_resume",
    "failure_code_for",
    "interruption_is_current",
    "interruption_turn_id",
    "is_memory_exhaustion",
    "mark_memory_resume_handled",
    "memory_exhausted_message",
    "memory_exhausted_message_for",
    "memory_resume_attempts",
    "memory_resume_budget_exhausted",
    "memory_resume_enabled",
    "memory_resume_exhausted_message",
    "memory_resume_handled",
    "memory_resume_resumes_spent",
    "memory_resume_started_message",
    "memory_resume_status",
    "merge_memory_resume",
    "note_memory_interruption",
    "pending_memory_resume",
    "platform_supported",
    "resume_ready",
    "resume_threshold_bytes",
    "resume_threshold_gb",
    "state_is_memory_exhaustion",
]
