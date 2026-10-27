"""Live-operation parameter validation, actor keys and activity predicates."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

from typing import Any
from lamtools_core.composer_commands import normalize_command_name
from .context import CoreLiveContext


SERIALIZED_SESSION_OPERATIONS = frozenset({
    "thread.start",
    "turn.start",
    "turn.resume",
    "turn.pause",
    "turn.cancel",
    "turn.terminate",
    "turn.force_reset",
    "turn.steer",
    "approval.respond",
    "queue.create",
    "queue.update",
    "queue.delete",
    "queue.guide",
    "command.execute",
})


def _is_stoppable_turn(snapshot: dict[str, Any], turn_id: str) -> bool:
    """Whether a Stop-type request may target this turn.

    A paused turn is not executing, but it is exactly what a single click parks
    and what the long-press confirm has to terminate, so it is stoppable.
    """
    if _is_active_turn(snapshot, turn_id):
        return True
    core = snapshot.get("core")
    turns = core.get("turns") if isinstance(core, dict) else snapshot.get("turns")
    turn = turns.get(turn_id) if isinstance(turns, dict) else None
    return isinstance(turn, dict) and str(turn.get("status") or "") == "paused"


def _is_active_turn(snapshot: dict[str, Any], turn_id: str) -> bool:
    core = snapshot.get("core")
    turns = core.get("turns") if isinstance(core, dict) else snapshot.get("turns")
    turn = turns.get(turn_id) if isinstance(turns, dict) else None
    return isinstance(turn, dict) and str(turn.get("status") or "") in {"running", "waiting", "interrupting"}


def _thread_id_from_params(params: dict[str, Any]) -> str:
    return str(params.get("thread_id") or params.get("threadId") or params.get("session_id") or "").strip()


def _serialized_actor_key(name: str, params: dict[str, Any]) -> str:
    """Return the actor key for commands that mutate shared state.

    Reads and long-running runtime workers intentionally bypass this lock.
    Manual context compaction also bypasses it: it owns a RuntimeTaskRegistry
    slot so turn.cancel can acquire the session actor and cancel the real task.
    Project operations use their own key when no session id is available so a
    project mutation cannot race another live connection's project command.
    """

    normalized = str(name or "").strip()
    if normalized == "command.execute" and normalize_command_name(params.get("command")) == "compact":
        return ""
    if normalized not in SERIALIZED_SESSION_OPERATIONS and not (
        normalized.startswith("session.") or normalized.startswith("project.")
    ):
        return ""
    thread_id = _thread_id_from_params(params)
    if thread_id:
        return f"session:{thread_id}"
    project_id = str(params.get("project_id") or params.get("projectId") or "").strip()
    if project_id:
        return f"project:{project_id}"
    return ""


def _command_arguments(params: dict[str, Any]) -> str:
    value = params.get("arguments")
    if value is None:
        value = params.get("args")
    return str(value or "").strip()


def _command_kind(definition: dict[str, Any]) -> str:
    raw_kind = str(definition.get("kind") or "").strip().lower()
    if raw_kind in {"action", "skill"}:
        return raw_kind
    # Compatibility for command catalogs produced before the explicit kind
    # field was introduced.
    return "skill" if definition.get("action") in {"insert_token", "expand_on_send"} else "action"


def _expected_revision(params: dict[str, Any]) -> int | None:
    """Parse the optional CAS revision without treating zero as absent."""

    marker = object()
    value = params.get("expected_revision", marker)
    if value is marker:
        value = params.get("expectedRevision", marker)
    if value is marker or value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("expected_revision must be a non-negative integer")
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("expected_revision must be a non-negative integer") from exc
    if revision < 0:
        raise ValueError("expected_revision must be a non-negative integer")
    return revision


def _include_snapshot_param(params: dict[str, Any]) -> bool:
    """Mutation responses embed the full snapshot unless the caller opts out.

    The desktop UI opts out everywhere: the response's event list already
    carries the state change and the revision, so a 48MB snapshot parse per
    send/guide on large threads was pure latency (measured 0.6-1.6s round
    trips on a 509-item session). CLI/mobile callers keep the legacy default.
    """
    return params.get("include_snapshot") is not False


async def _load_snapshot_outside_write_lock(context: CoreLiveContext, thread_id: str) -> dict[str, Any]:
    """Assemble the full snapshot after the write transaction committed.

    Full assembly scans every item row; doing it inside the global SQLite
    write lock stalled concurrent sends/streaming for its whole duration.
    Reading after commit is monotonic for clients (revision only moves
    forward), so the tiny race window is harmless.
    """
    async with context.session_factory() as db:
        return await context.persistence.load(db, thread_id)
