"""Tests for 设置 → 通用 → 内存中断自动续跑 (memory guard + auto resume)."""
from __future__ import annotations

import errno
from pathlib import Path
from typing import Any

import pytest

from lamtools_core.config.settings_store import set_setting
from lamtools_core.runtime import memory_guard as guard


class _State:
    """Minimal stand-in for RuntimeState: the guard only touches these fields."""

    def __init__(self, *, session_id: str = "thread-1", run_id: str = "turn-1", metadata: dict[str, Any] | None = None):
        self.session_id = session_id
        self.run_id = run_id
        self.metadata = dict(metadata or {})


@pytest.fixture()
def fake_available(monkeypatch: pytest.MonkeyPatch):
    """Drive the host reading instead of depending on the machine's real memory."""
    def _set(gb: float | None) -> None:
        monkeypatch.setattr(
            guard,
            "available_memory_bytes",
            lambda: None if gb is None else int(gb * (1024**3)),
        )
    _set(8.0)
    return _set


def test_defaults_to_on_with_four_gb(isolated_config_root: Path) -> None:
    """An unset namespace means「开着，阈值 4 GB」— the product asked for this
    behaviour, so the default has to be the enabled one."""
    assert guard.memory_resume_enabled() is True
    assert guard.resume_threshold_gb() == 4.0
    assert guard.resume_threshold_bytes() == 4 * 1024**3


def test_stored_preference_wins(isolated_config_root: Path) -> None:
    set_setting(guard.MEMORY_RESUME_NAMESPACE, {"enabled": False, "threshold_gb": 12})

    assert guard.memory_resume_enabled() is False
    assert guard.resume_threshold_gb() == 12.0


def test_merge_memory_resume_validates(isolated_config_root: Path) -> None:
    assert guard.merge_memory_resume({}, {"enabled": False})["enabled"] is False
    assert guard.merge_memory_resume({}, {}) == {"enabled": True, "threshold_gb": 4.0}
    assert guard.merge_memory_resume({}, {"threshold_gb": 6})["threshold_gb"] == 6.0
    # Rejected: wrong types and out-of-range values must not be persisted.
    assert guard.merge_memory_resume({}, {"enabled": "yes"}) is None
    assert guard.merge_memory_resume({}, {"threshold_gb": True}) is None
    assert guard.merge_memory_resume({}, {"threshold_gb": "8"}) is None
    assert guard.merge_memory_resume({}, {"threshold_gb": 0}) is None
    assert guard.merge_memory_resume({}, {"threshold_gb": 4096}) is None
    # Unknown keys are dropped rather than stored.
    assert guard.merge_memory_resume({}, {"unknown": 1}) == {"enabled": True, "threshold_gb": 4.0}


def test_corrupt_stored_threshold_falls_back(isolated_config_root: Path) -> None:
    set_setting(guard.MEMORY_RESUME_NAMESPACE, {"enabled": True, "threshold_gb": -3})

    assert guard.resume_threshold_gb() == guard.DEFAULT_THRESHOLD_GB


def test_resume_ready_compares_available_with_threshold(isolated_config_root: Path, fake_available) -> None:
    set_setting(guard.MEMORY_RESUME_NAMESPACE, {"enabled": True, "threshold_gb": 4})

    fake_available(3.9)
    assert guard.resume_ready() is False
    fake_available(4.0)
    assert guard.resume_ready() is True


def test_unreadable_memory_is_never_ready(isolated_config_root: Path, fake_available) -> None:
    """Not knowing must not be treated as "plenty of memory"."""
    fake_available(None)

    assert guard.available_memory_gb() is None
    assert guard.resume_ready() is False


def test_status_reports_the_reading(isolated_config_root: Path, fake_available) -> None:
    fake_available(6.5)

    status = guard.memory_resume_status()
    assert status["enabled"] is True
    assert status["threshold_gb"] == 4.0
    assert status["available_gb"] == 6.5
    assert status["ready"] is True


def test_is_memory_exhaustion_recognises_allocation_failures() -> None:
    assert guard.is_memory_exhaustion(MemoryError()) is True
    assert guard.is_memory_exhaustion(OSError(errno.ENOMEM, "Cannot allocate memory")) is True
    assert guard.is_memory_exhaustion(OSError(errno.ENOEXEC, "Exec format error")) is False
    assert guard.is_memory_exhaustion(ValueError("nope")) is False


def test_exhaustion_message_states_the_threshold(isolated_config_root: Path) -> None:
    set_setting(guard.MEMORY_RESUME_NAMESPACE, {"enabled": True, "threshold_gb": 6.5})

    message = guard.memory_exhausted_message()
    assert "内存不足" in message
    assert "6.5 GB" in message
    assert "自动继续" in message


def test_exhaustion_message_does_not_promise_when_off(isolated_config_root: Path) -> None:
    set_setting(guard.MEMORY_RESUME_NAMESPACE, {"enabled": False})

    message = guard.memory_exhausted_message()
    # It must not claim a resume will happen; it points at the switch instead.
    assert "会自动继续" not in message
    assert "内存中断自动续跑" in message
    assert "设置" in message


def test_interruption_arms_a_resume_and_counts_the_streak(isolated_config_root: Path) -> None:
    state = _State(metadata={"original_user_message": "make a PV"})

    message = guard.note_memory_interruption(state)

    assert state.metadata["failure_code"] == guard.HOST_MEMORY_EXHAUSTED
    assert state.metadata["failure_message"] == message
    assert guard.memory_resume_attempts(state) == 1
    pending = guard.pending_memory_resume(state)
    assert pending is not None
    assert pending["thread_id"] == "thread-1"
    assert pending["turn_id"] == "turn-1"
    assert pending["original_message"] == "make a PV"
    assert pending["threshold_gb"] == 4.0
    # A further interruption in the same chain counts up.
    guard.note_memory_interruption(state)
    assert guard.memory_resume_attempts(state) == 2


def test_resume_budget_stops_after_the_cap(isolated_config_root: Path) -> None:
    state = _State()
    for _ in range(guard.MEMORY_RESUME_MAX_ATTEMPTS):
        guard.note_memory_interruption(state)

    # The third interruption still gets a resume (3 resumes are allowed)…
    assert guard.memory_resume_budget_exhausted(state) is False
    assert guard.memory_resume_resumes_spent(state) == 2
    assert "自动继续" in guard.memory_exhausted_message_for(state)

    # …the fourth does not, and says so instead of promising a resume.
    guard.note_memory_interruption(state)
    assert guard.memory_resume_budget_exhausted(state) is True
    assert guard.memory_resume_resumes_spent(state) == 3
    message = guard.memory_exhausted_message_for(state)
    assert "不再自动继续" in message
    assert "3 次" in message


def test_streak_resets_when_the_chain_breaks(isolated_config_root: Path) -> None:
    state = _State()
    guard.note_memory_interruption(state)
    guard.note_memory_interruption(state)

    guard.clear_memory_resume_streak(state)

    assert guard.memory_resume_attempts(state) == 0
    # A fresh interruption after a clean turn starts the budget over.
    guard.note_memory_interruption(state)
    assert guard.memory_resume_attempts(state) == 1


def test_clear_pending_resume_disarms(isolated_config_root: Path) -> None:
    state = _State()
    guard.note_memory_interruption(state)

    guard.clear_pending_memory_resume(state)

    assert guard.pending_memory_resume(state) is None
    # The streak survives disarming: it counts interruptions, not armed markers.
    assert guard.memory_resume_attempts(state) == 1


def test_ensure_pending_resume_arms_only_memory_states(isolated_config_root: Path) -> None:
    memory_state = _State(metadata={"failure_code": guard.HOST_MEMORY_EXHAUSTED})
    other_state = _State(metadata={"failure_code": "model_retry_exhausted"})

    assert guard.ensure_pending_memory_resume(memory_state) is True
    assert guard.pending_memory_resume(memory_state) is not None
    # Idempotent: an already armed state is left alone.
    assert guard.ensure_pending_memory_resume(memory_state) is False
    assert guard.ensure_pending_memory_resume(other_state) is False


def test_state_is_memory_exhaustion_reads_the_explicit_code(isolated_config_root: Path) -> None:
    assert guard.state_is_memory_exhaustion(_State(metadata={"failure_code": guard.HOST_MEMORY_EXHAUSTED})) is True
    assert guard.state_is_memory_exhaustion(_State(metadata={"failure_code": "model_retry_exhausted"})) is False
    assert guard.state_is_memory_exhaustion(_State(metadata={})) is False


def test_state_is_memory_exhaustion_accepts_older_evidence(isolated_config_root: Path) -> None:
    """Builds before the code existed kept the bare exception name where the
    failure was recorded; that evidence must still name the interruption."""
    legacy = _State(metadata={"approval_resolution": {"phase": "terminal_persistence_failed", "error": "MemoryError"}})
    other = _State(metadata={"approval_resolution": {"phase": "terminal_persistence_failed", "error": "TimeoutError"}})

    assert guard.state_is_memory_exhaustion(legacy) is True
    assert guard.state_is_memory_exhaustion(other) is False


def test_ensure_pending_resume_stamps_a_legacy_state(isolated_config_root: Path) -> None:
    state = _State(metadata={"approval_resolution": {"error": "MemoryError"}})

    assert guard.ensure_pending_memory_resume(state) is True

    assert state.metadata["failure_code"] == guard.HOST_MEMORY_EXHAUSTED
    assert "内存不足" in state.metadata["failure_message"]
    assert guard.pending_memory_resume(state) is not None


def test_ensure_pending_resume_respects_the_switch(isolated_config_root: Path) -> None:
    set_setting(guard.MEMORY_RESUME_NAMESPACE, {"enabled": False})
    state = _State(metadata={"failure_code": guard.HOST_MEMORY_EXHAUSTED})

    assert guard.ensure_pending_memory_resume(state) is False


@pytest.mark.asyncio
async def test_settings_rpc_stores_and_validates_memory_resume(isolated_config_root: Path) -> None:
    from lamtools_core.config.operations import build_config_operation_catalog

    catalog = build_config_operation_catalog()

    stored = await catalog.execute(
        "settings.update",
        {"namespace": "core.memoryResume", "value": {"threshold_gb": 8}},
        metadata={},
    )
    assert stored.status == "ok"
    assert guard.resume_threshold_gb() == 8.0
    assert guard.memory_resume_enabled() is True

    rejected = await catalog.execute(
        "settings.update",
        {"namespace": "core.memoryResume", "value": {"threshold_gb": "lots"}},
        metadata={},
    )
    assert rejected.status == "error"
    # The rejected write must not change what is stored.
    assert guard.resume_threshold_gb() == 8.0


def test_resume_is_refused_once_the_session_moved_on(isolated_config_root: Path) -> None:
    """The interrupted turn must still be the session's latest turn. A later
    turn (an earlier resume, or one the user sent) makes it history."""
    state = _State(metadata={"failure_code": guard.HOST_MEMORY_EXHAUSTED, "failure_turn_id": "turn-old"})

    assert guard.interruption_is_current(state) is False
    assert guard.ensure_pending_memory_resume(state) is False
    assert guard.pending_memory_resume(state) is None

    # Same state, but the interruption IS the current turn → armed.
    state.metadata["failure_turn_id"] = state.run_id
    assert guard.ensure_pending_memory_resume(state) is True


def test_resume_is_refused_when_the_interruption_was_already_handled(isolated_config_root: Path) -> None:
    state = _State()
    guard.note_memory_interruption(state)
    guard.clear_pending_memory_resume(state)
    guard.mark_memory_resume_handled(state, state.run_id)

    # This is the case that used to loop: the reason stays readable forever, so
    # only an explicit token may trigger a continuation.
    assert guard.ensure_pending_memory_resume(state) is False

    # A fresh interruption clears the mark and may continue again.
    guard.note_memory_interruption(state)
    assert guard.pending_memory_resume(state) is not None
    assert guard.memory_resume_handled(state) == ""


def test_interruption_records_the_turn_it_belongs_to(isolated_config_root: Path) -> None:
    state = _State()

    guard.note_memory_interruption(state)

    assert state.metadata["failure_turn_id"] == state.run_id
    assert state.metadata["failure_at"] > 0
    assert guard.interruption_is_current(state) is True
    assert guard.pending_memory_resume(state)["turn_id"] == state.run_id


def test_clear_failure_detail_drops_the_explanation(isolated_config_root: Path) -> None:
    state = _State()
    guard.note_memory_interruption(state)

    guard.clear_failure_detail(state)

    assert state.metadata.get("failure_code") is None
    assert state.metadata.get("failure_message") is None
    assert state.metadata.get("failure_turn_id") is None
    # The armed resume is a separate decision; clearing the wording keeps it.
    assert guard.pending_memory_resume(state) is not None
