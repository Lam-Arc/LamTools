"""Cross-process ownership of a session's runtime state.

The CLI, the live host and the desktop app can all point at the same SQLite
database, and nothing below SQLite serializes them.  A second writer that
silently adopts a session another process is actively running would interleave
two runtimes into one state row, which is what produced the "revision conflict
mid-run" failure on 2026-09-27.

Each run therefore records an *owner token* (pid, host, heartbeat) in the
session's runtime metadata.  Readers use it to tell "another process is running
this session right now" from "the process that owned it died", so a crashed run
can be adopted while a live one is refused.
"""

from __future__ import annotations

import os
import socket
import time
from typing import Any, Mapping

#: Metadata key holding the owner token of the run that last wrote the state.
OWNER_METADATA_KEY = "runtime_owner"

#: Run states that mean "a turn is in flight".  Anything else is terminal.
LIVE_RUN_STATES = frozenset({"running", "waiting", "interrupting"})

#: Fallback staleness window, used when the owner's pid cannot be checked
#: (owner on another host, or a token without a pid).  Generous on purpose: a
#: single model round with max reasoning can take many minutes, and adopting a
#: *live* slow writer is the failure this guard exists to prevent.
DEFAULT_OWNER_STALE_SECONDS = 30 * 60.0


def owner_token(*, pid: int | None = None, host: str | None = None) -> dict[str, Any]:
    """Build the ownership token for the current process."""
    now = time.time()
    return {
        "pid": int(os.getpid() if pid is None else pid),
        "host": str(socket.gethostname() if host is None else host),
        "started_at": now,
        "heartbeat_at": now,
    }


def read_owner(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the recorded owner token, or ``{}`` when there is none."""
    if not isinstance(metadata, Mapping):
        return {}
    raw = metadata.get(OWNER_METADATA_KEY)
    return dict(raw) if isinstance(raw, Mapping) else {}


def is_own_token(owner: Mapping[str, Any] | None) -> bool:
    """Whether the token belongs to this process on this host."""
    if not isinstance(owner, Mapping) or not owner:
        return False
    try:
        pid = int(owner.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    return pid == os.getpid() and str(owner.get("host") or "") == socket.gethostname()


def refresh_owner(metadata: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """Stamp ``metadata`` with this process as owner and return the token."""
    stamp = time.time() if now is None else now
    existing = read_owner(metadata)
    token = {
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "started_at": float(existing.get("started_at") or stamp),
        "heartbeat_at": stamp,
    }
    metadata[OWNER_METADATA_KEY] = token
    return token


def process_is_alive(pid: int) -> bool | None:
    """Whether *pid* is running on this host; ``None`` when unknowable."""
    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - platform specific
        # Never os.kill on Windows: signal 0 is not a liveness probe there, it
        # terminates the target process.
        import ctypes

        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(
            SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
        if not handle:
            return False
        try:
            WAIT_TIMEOUT = 0x00000102
            return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def owner_is_live(
    owner: Mapping[str, Any] | None,
    *,
    now: float | None = None,
    stale_after: float = DEFAULT_OWNER_STALE_SECONDS,
) -> bool:
    """Whether the owner of a state row is still running.

    A local pid is authoritative.  A token from another host (or without a
    usable pid) falls back to heartbeat age, so a network-shared database
    degrades to "assume live until the heartbeat is old" instead of accepting a
    concurrent writer.
    """
    if not isinstance(owner, Mapping) or not owner:
        return False
    stamp = time.time() if now is None else now
    host = str(owner.get("host") or "")
    if host and host != socket.gethostname():
        try:
            heartbeat = float(owner.get("heartbeat_at") or owner.get("started_at") or 0)
        except (TypeError, ValueError):
            return True
        return (stamp - heartbeat) <= stale_after
    try:
        pid = int(owner.get("pid") or 0)
    except (TypeError, ValueError):
        return True
    alive = process_is_alive(pid)
    if alive is None:
        return True
    return bool(alive)


def state_row_is_live(
    state_payload: Mapping[str, Any] | None,
    *,
    now: float | None = None,
    stale_after: float = DEFAULT_OWNER_STALE_SECONDS,
) -> bool:
    """Whether a persisted runtime-state payload belongs to a live run.

    ``state_payload`` is the row's decoded JSON (``runtime_state_json``).
    Terminal rows are never live, even if their token mentions a starting pid.
    """
    if not isinstance(state_payload, Mapping):
        return False
    if str(state_payload.get("status") or "") not in LIVE_RUN_STATES:
        return False
    metadata = state_payload.get("metadata")
    return owner_is_live(read_owner(metadata), now=now, stale_after=stale_after)


__all__ = [
    "DEFAULT_OWNER_STALE_SECONDS",
    "LIVE_RUN_STATES",
    "OWNER_METADATA_KEY",
    "is_own_token",
    "owner_is_live",
    "owner_token",
    "process_is_alive",
    "read_owner",
    "refresh_owner",
    "state_row_is_live",
]
