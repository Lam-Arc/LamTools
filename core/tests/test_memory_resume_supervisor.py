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
        # Its own distinct origin so the interface can tell it from user input.
        assert params["origin"] == "memory_resume"

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


# ── Waking an idle session when a member finishes ───────────────────────────
#
# The kernel drains member events while a parent turn is alive. When the turn
# has ended, this watchdog starts a new turn in the same session so the main
# agent still learns a member finished or failed. It is the second thing that
# may start a turn nobody asked for, so the same refusals matter: a live turn,
# a user stop, a paused member, and a spent budget must all leave it alone.


def _seed_member_event(
    db_path: Path,
    event: str = "member_finished",
    name: str = "worker",
    *,
    detail: str = "",
) -> None:
    from lamtools_core.sub_agent_supervisor import SubAgentRecord, SubAgentSupervisor

    owner = SubAgentSupervisor(parent_thread_id="thread-1", runner=object(), database_path=db_path)
    record = SubAgentRecord(
        parent_thread_id="thread-1",
        type="execute",
        name=name,
        model_id="fake-model",
        reasoning_level="high",
        status="idle" if event == "member_finished" else event.removeprefix("member_"),
        summary=("done" if event == "member_finished" else "boom" if event == "member_failed" else ""),
        started_at=900.0,
        completed_at=1000.0,
        elapsed_ms=1000,
    )
    owner._write_member_event(record, event, detail=detail)


def _member_state(*, status: str = "completed") -> RuntimeState:
    return RuntimeState(session_id="thread-1", run_id="turn-user", status=status, metadata={})


async def _open_members(
    tmp_path: Path,
    *,
    registry: _FakeRegistry | None = None,
    state: RuntimeState | None = None,
    event: str = "member_finished",
):
    db = await open_core_app_db(tmp_path / "core.db")
    store = InMemoryRuntimeStateStore()
    await store.save(state if state is not None else _member_state())
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _seed_member_event(data_dir / "sub_agents.sqlite3", event=event)
    context = CoreLiveContext(
        operations=OperationCatalog(),
        session_factory=db.session_factory,
        persistence=db.persistence,
        runtime_state_store=store,
        runtime_task_registry=registry or _FakeRegistry(),
        hub=CoreAppEventHub(),
    )
    return db, context, store, data_dir


@pytest.mark.asyncio
async def test_member_finish_wakes_an_idle_session(
    tmp_path: Path, recorded_starts: list[dict[str, Any]]
) -> None:
    db, context, store, data_dir = await _open_members(tmp_path)
    try:
        runner = supervisor.MemoryResumeSupervisor(context=context, sub_agent_data_dir=data_dir)
        assert await runner.tick() == 1
        assert len(recorded_starts) == 1
        params = recorded_starts[0]
        assert params["thread_id"] == "thread-1"
        assert params["client_message_id"].startswith("thread-1:member-wake:")
        assert params["origin"] == "member_wake"
        text = params["input"][0]["text"]
        assert "worker" in text and "已完成" in text
        # Claimed on delivery: a second tick must not deliver it again.
        assert await runner.tick() == 0
        assert len(recorded_starts) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_member_failure_also_wakes(
    tmp_path: Path, recorded_starts: list[dict[str, Any]]
) -> None:
    db, context, store, data_dir = await _open_members(tmp_path, event="member_failed")
    try:
        runner = supervisor.MemoryResumeSupervisor(context=context, sub_agent_data_dir=data_dir)
        assert await runner.tick() == 1
        assert "已失败" in recorded_starts[0]["input"][0]["text"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_paused_member_never_wakes(
    tmp_path: Path, recorded_starts: list[dict[str, Any]]
) -> None:
    db, context, store, data_dir = await _open_members(tmp_path, event="member_paused")
    try:
        runner = supervisor.MemoryResumeSupervisor(context=context, sub_agent_data_dir=data_dir)
        assert await runner.tick() == 0
        assert recorded_starts == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_interruption_alone_does_not_restart_the_parent(
    tmp_path: Path, recorded_starts: list[dict[str, Any]]
) -> None:
    from lamtools_core.sub_agent_supervisor import peek_member_events

    db, context, store, data_dir = await _open_members(tmp_path, event="member_interrupted")
    try:
        runner = supervisor.MemoryResumeSupervisor(context=context, sub_agent_data_dir=data_dir)
        assert await runner.tick() == 0
        assert recorded_starts == []
        # An interruption remains durable until a suitable turn can report it.
        pending = peek_member_events(data_dir / "sub_agents.sqlite3", "thread-1")
        assert len(pending) == 1
        assert pending[0]["payload"]["event"] == "member_interrupted"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_user_cancelled_session_is_not_woken(
    tmp_path: Path, recorded_starts: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    from lamtools_core.sub_agent_supervisor import peek_member_events

    caplog.set_level("INFO", logger=supervisor.__name__)
    db, context, store, data_dir = await _open_members(
        tmp_path, state=_member_state(status="cancelled")
    )
    try:
        runner = supervisor.MemoryResumeSupervisor(context=context, sub_agent_data_dir=data_dir)
        assert await runner.tick() == 0
        assert await runner.tick() == 0
        assert recorded_starts == []
        # User cancellation is the stop boundary: keep the event pending for a
        # later user-owned turn, and explain the safe skip in the watchdog log.
        pending = peek_member_events(data_dir / "sub_agents.sqlite3", "thread-1")
        assert len(pending) == 1
        assert pending[0]["payload"]["event"] == "member_finished"
        assert "safely skipping user-cancelled" in caplog.text
        assert "remain unclaimed for a later user-owned turn" in caplog.text
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_live_turn_wins_over_the_wake(
    tmp_path: Path, recorded_starts: list[dict[str, Any]]
) -> None:
    db, context, store, data_dir = await _open_members(
        tmp_path, registry=_FakeRegistry({"thread-1"})
    )
    try:
        runner = supervisor.MemoryResumeSupervisor(context=context, sub_agent_data_dir=data_dir)
        assert await runner.tick() == 0
        assert recorded_starts == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_member_wake_is_bounded_and_a_user_turn_resets_it(
    tmp_path: Path, recorded_starts: list[dict[str, Any]]
) -> None:
    from lamtools_core.runtime import member_wake as wake

    state = _member_state()
    wake.note_member_wake(state)
    for _ in range(wake.MEMBER_WAKE_MAX_CONSECUTIVE - 1):
        wake.note_member_wake(state)
    db, context, store, data_dir = await _open_members(tmp_path, state=state)
    try:
        runner = supervisor.MemoryResumeSupervisor(context=context, sub_agent_data_dir=data_dir)
        # Budget spent: no wake, and the pending row stays for the next user turn.
        assert await runner.tick() == 0
        assert recorded_starts == []
        # A user turn clears the streak (the kernel calls this at turn start).
        wake.clear_member_wake_streak(state)
        assert await runner.tick() == 1
    finally:
        await db.close()


def test_member_wake_autostart_flag_is_one_shot() -> None:
    """The kernel must not reset the streak its own wake is counting.

    The watchdog marks the state before starting its turn; the kernel consumes
    that mark once and skips the streak reset for that turn only, so a user turn
    still clears it (see runtime/member_wake.py).
    """
    from lamtools_core.runtime import member_wake as wake

    state = RuntimeState(session_id="thread-1", run_id="run-1", status="running", metadata={})
    wake.mark_member_wake_autostart(state)
    assert wake.consume_member_wake_autostart(state) is True
    assert wake.consume_member_wake_autostart(state) is False
    wake.note_member_wake(state)
    wake.note_member_wake(state)
    assert wake.member_wake_streak(state) == 2
    assert wake.member_wake_exhausted(state) is False
    wake.clear_member_wake_streak(state)
    assert wake.member_wake_streak(state) == 0


@pytest.mark.asyncio
async def test_two_member_completions_are_delivered_in_one_wake_turn(
    tmp_path: Path, recorded_starts: list[dict[str, Any]]
) -> None:
    """Completions close together coalesce into ONE turn, both still visible."""
    db, context, store, data_dir = await _open_members(tmp_path, event="member_finished")
    try:
        _seed_member_event(data_dir / "sub_agents.sqlite3", event="member_finished", name="beta")
        runner = supervisor.MemoryResumeSupervisor(context=context, sub_agent_data_dir=data_dir)
        assert await runner.tick() == 1
        assert len(recorded_starts) == 1
        text = recorded_starts[0]["input"][0]["text"]
        assert "worker" in text and "beta" in text
        # Both delivered in one turn; a second tick starts nothing.
        assert await runner.tick() == 0
        assert len(recorded_starts) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_wake_reports_interruption_reason_and_claims_only_reported_events(
    tmp_path: Path, recorded_starts: list[dict[str, Any]]
) -> None:
    from lamtools_core.sub_agent_supervisor import peek_member_events

    db, context, store, data_dir = await _open_members(tmp_path)
    database = data_dir / "sub_agents.sqlite3"
    _seed_member_event(
        database,
        event="member_interrupted",
        name="interrupted_worker",
        detail="进程重启时该成员仍在运行",
    )
    _seed_member_event(database, event="member_paused", name="approval_worker")
    try:
        runner = supervisor.MemoryResumeSupervisor(context=context, sub_agent_data_dir=data_dir)
        assert await runner.tick() == 1
        text = recorded_starts[0]["input"][0]["text"]
        assert "worker 已完成" in text
        assert "interrupted_worker 已中断" in text
        assert "原因：进程重启时该成员仍在运行" in text
        assert "approval_worker" not in text

        # Only delivered facts are claimed. Human-gated work is still pending.
        pending = peek_member_events(database, "thread-1")
        assert [(item["payload"]["event"], item["payload"]["name"]) for item in pending] == [
            ("member_paused", "approval_worker"),
        ]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_member_completion_waits_for_a_live_turn_then_becomes_its_own_turn(
    tmp_path: Path, recorded_starts: list[dict[str, Any]]
) -> None:
    """While a turn runs the result waits; once it releases, a NEW turn carries it."""
    registry = _FakeRegistry({"thread-1"})
    db, context, store, data_dir = await _open_members(tmp_path, registry=registry)
    try:
        runner = supervisor.MemoryResumeSupervisor(context=context, sub_agent_data_dir=data_dir)
        assert await runner.tick() == 0
        assert recorded_starts == []
        registry.running.clear()
        assert await runner.tick() == 1
        assert len(recorded_starts) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_member_event_notify_is_debounced(tmp_path: Path) -> None:
    """A burst of completions schedules one wake, not one per completion."""
    db, context, store, data_dir = await _open_members(tmp_path)
    try:
        runner = supervisor.MemoryResumeSupervisor(context=context, sub_agent_data_dir=data_dir)
        runner.notify_member_event()
        handle = runner._coalesce_handle
        assert handle is not None
        runner.notify_member_event()
        assert runner._coalesce_handle is handle
        runner._fire_coalesced()
        assert runner._wake.is_set()
    finally:
        await db.close()
