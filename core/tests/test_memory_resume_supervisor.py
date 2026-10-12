"""Tests for the「内存恢复后自动续跑」watchdog decisions.

The watchdog is the only thing that may start a turn nobody asked for, so its
refusals matter as much as its action: memory below the threshold, a spent
budget, and a thread the user is already using must all leave things alone.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lamtools_core.app import OperationCatalog, open_core_app_db
from lamtools_core.app import memory_resume_supervisor as supervisor
from lamtools_core.app.live_hub import CoreAppEventHub
from lamtools_core.app.live_operations import CoreLiveContext
from lamtools_core.config.settings_store import set_setting
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState
from lamtools_core.runtime import memory_guard as guard


class _FakeRegistry:
    def __init__(self, running: set[str] | None = None) -> None:
        self.running = set(running or ())

    def is_running(self, thread_id: str, *, run_id: str | None = None) -> bool:
        del run_id
        return thread_id in self.running


def _armed_state(*, attempts: int = 1, original_message: str = "make a PV", armed: bool = True) -> RuntimeState:
    metadata: dict[str, Any] = {
        "failure_code": guard.HOST_MEMORY_EXHAUSTED,
        "failure_message": "本机内存不足，本轮已中断。",
        "original_user_message": original_message,
        "memory_resume_attempts": attempts,
    }
    if armed:
        metadata[supervisor.MEMORY_RESUME_METADATA_KEY] = {
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "original_message": original_message,
            "threshold_gb": 4.0,
            "attempts": attempts,
            "created_at": 0.0,
        }
    return RuntimeState(session_id="thread-1", run_id="turn-1", status="failed", metadata=metadata)


async def _open(tmp_path: Path, *, registry: _FakeRegistry | None = None, state: RuntimeState | None = None):
    """A live context backed by a real (temp) app DB plus a seeded state."""
    db = await open_core_app_db(tmp_path / "core.db")
    store = InMemoryRuntimeStateStore()
    await store.save(state if state is not None else _armed_state())
    context = CoreLiveContext(
        operations=OperationCatalog(),
        session_factory=db.session_factory,
        persistence=db.persistence,
        runtime_state_store=store,
        runtime_task_registry=registry or _FakeRegistry(),
        hub=CoreAppEventHub(),
    )
    return db, context, store


@pytest.fixture()
def allow_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor, "memory_resume_enabled", lambda: True)
    monkeypatch.setattr(supervisor, "resume_ready", lambda: True)
    monkeypatch.setattr(supervisor, "available_memory_gb", lambda: 9.0)


@pytest.fixture()
def recorded_starts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    starts: list[dict[str, Any]] = []

    async def _fake_start(*, request_id: Any, params: dict[str, Any], context: Any):
        del request_id, context
        starts.append(params)

        class _Outcome:
            response: dict[str, Any] = {"result": {}}

        return _Outcome()

    monkeypatch.setattr(supervisor, "handle_turn_start_operation", _fake_start)
    return starts


@pytest.mark.asyncio
async def test_no_resume_while_memory_is_below_the_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_starts: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(supervisor, "memory_resume_enabled", lambda: True)
    monkeypatch.setattr(supervisor, "resume_ready", lambda: False)
    db, context, store = await _open(tmp_path)
    try:
        assert await supervisor.MemoryResumeSupervisor(context=context).tick() == 0
        assert recorded_starts == []
        # Still armed: it must keep waiting, not give up.
        assert guard.pending_memory_resume(await store.get("thread-1")) is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_resumes_the_same_session_once_memory_recovers(
    tmp_path: Path, allow_memory: None, recorded_starts: list[dict[str, Any]]
) -> None:
    db, context, store = await _open(tmp_path)
    try:
        runner = supervisor.MemoryResumeSupervisor(context=context)
        assert await runner.tick() == 1

        assert len(recorded_starts) == 1
        params = recorded_starts[0]
        assert params["thread_id"] == "thread-1"
        text = params["input"][0]["text"]
        assert "自动继续" in text
        assert "make a PV" in text

        # Disarmed before starting: a later tick must not continue it twice.
        assert guard.pending_memory_resume(await store.get("thread-1")) is None
        assert await runner.tick() == 0
        assert len(recorded_starts) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_spent_budget_disarms_without_starting(
    tmp_path: Path, allow_memory: None, recorded_starts: list[dict[str, Any]]
) -> None:
    db, context, store = await _open(
        tmp_path, state=_armed_state(attempts=guard.MEMORY_RESUME_MAX_ATTEMPTS + 1)
    )
    try:
        assert await supervisor.MemoryResumeSupervisor(context=context).tick() == 0
        assert recorded_starts == []
        # Disarmed: leaving the marker behind would make every later sweep retry
        # a resume the user was already told would not happen.
        assert guard.pending_memory_resume(await store.get("thread-1")) is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_leaves_a_thread_the_user_is_using_alone(
    tmp_path: Path, allow_memory: None, recorded_starts: list[dict[str, Any]]
) -> None:
    db, context, store = await _open(tmp_path, registry=_FakeRegistry({"thread-1"}))
    try:
        assert await supervisor.MemoryResumeSupervisor(context=context).tick() == 0
        assert recorded_starts == []
        # The user's own turn wins; the kernel disarms the marker when it starts.
        assert guard.pending_memory_resume(await store.get("thread-1")) is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_a_refused_start_re_arms_for_the_next_tick(
    tmp_path: Path, allow_memory: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    starts: list[dict[str, Any]] = []

    async def _refusing_start(*, request_id: Any, params: dict[str, Any], context: Any):
        del request_id, context
        starts.append(params)

        class _Outcome:
            response = {"id": None, "error": {"code": -32600, "message": "session has an active turn"}}

        return _Outcome()

    monkeypatch.setattr(supervisor, "handle_turn_start_operation", _refusing_start)
    db, context, store = await _open(tmp_path)
    try:
        assert await supervisor.MemoryResumeSupervisor(context=context).tick() == 0
        assert len(starts) == 1
        assert guard.pending_memory_resume(await store.get("thread-1")) is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_disabled_switch_does_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_starts: list[dict[str, Any]]
) -> None:
    set_setting(guard.MEMORY_RESUME_NAMESPACE, {"enabled": False})
    monkeypatch.setattr(supervisor, "resume_ready", lambda: True)
    db, context, store = await _open(tmp_path)
    try:
        assert await supervisor.MemoryResumeSupervisor(context=context).tick() == 0
        assert recorded_starts == []
        # Nothing is consumed while the switch is off, so turning it back on
        # still continues the interrupted turn.
        assert guard.pending_memory_resume(await store.get("thread-1")) is not None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_unarmed_thread_is_ignored(
    tmp_path: Path, allow_memory: None, recorded_starts: list[dict[str, Any]]
) -> None:
    db, context, store = await _open(tmp_path, state=_armed_state(armed=False))
    try:
        assert await supervisor.MemoryResumeSupervisor(context=context).tick() == 0
        assert recorded_starts == []
    finally:
        await db.close()


def test_continuation_prompt_is_explicit_about_why() -> None:
    prompt = supervisor.memory_resume_continuation_prompt(
        original_message="make a PV", resumes_spent=1
    )

    assert "内存不足" in prompt
    assert "不要重做" in prompt
    assert "make a PV" in prompt
    assert "第 2 次继续" in prompt


@pytest.mark.asyncio
async def test_start_arms_nothing_by_itself(
    tmp_path: Path, allow_memory: None, recorded_starts: list[dict[str, Any]]
) -> None:
    # A state recorded as memory-interrupted but never armed (an older build,
    # or a session already continued by hand). Starting the app must NOT turn
    # that into a new turn on its own — that was the bug: it re-armed on every
    # start, so the same session got continued again and again.
    other = RuntimeState(
        session_id="thread-1",
        run_id="turn-1",
        status="failed",
        metadata={"failure_code": guard.HOST_MEMORY_EXHAUSTED, "failure_turn_id": "turn-old"},
    )
    db, context, store = await _open(tmp_path, state=other)
    try:
        runner = supervisor.MemoryResumeSupervisor(context=context)
        await runner.start()
        try:
            assert recorded_starts == []
            assert guard.pending_memory_resume(await store.get("thread-1")) is None
        finally:
            await runner.stop()
    finally:
        await db.close()
