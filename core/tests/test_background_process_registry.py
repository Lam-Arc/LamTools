from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import lamtools_core.runtime.background_processes as process_module
import lamtools_core.tool.command_tools as command_tools_module
import lamtools_core.tool.command_runner as command_runner_module
from lamtools_core.runtime import RuntimeTaskRegistry
from lamtools_core.runtime.background_processes import (
    BackgroundProcessRecord,
    BackgroundProcessRegistry,
    persistent_process_prompt,
)
from lamtools_core.tool import ToolCall
from lamtools_core.tool.command import CommandExecution
from lamtools_core.tool.command_tools import CommandToolHandlers
from lamtools_core.tool.command_runner import _run_background_subprocess


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


def test_registry_cleans_only_owned_processes_for_matching_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = BackgroundProcessRegistry()
    first = _FakeProcess(101)
    second = _FakeProcess(202)
    unrelated = _FakeProcess(303)
    terminated: list[int] = []
    monkeypatch.setattr(
        process_module,
        "terminate_process_tree",
        lambda process: terminated.append(process.pid),
    )

    registry.register(first, session_id="s1", run_id="r1", work_root=tmp_path)  # type: ignore[arg-type]
    registry.register(second, session_id="s1", run_id="r2", work_root=tmp_path)  # type: ignore[arg-type]
    # This process exists in the OS model but was never started/registered by Core.
    assert unrelated.pid not in {record.pid for record in registry.list()}

    assert registry.cleanup_run("s1", "r1") == [101]
    assert terminated == [101]
    assert [record.pid for record in registry.list()] == [202]


def test_parent_session_cleanup_includes_registered_sub_agent_processes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = BackgroundProcessRegistry()
    parent = _FakeProcess(111)
    child = _FakeProcess(222)
    other = _FakeProcess(333)
    terminated: list[int] = []
    monkeypatch.setattr(
        process_module,
        "terminate_process_tree",
        lambda process: terminated.append(process.pid),
    )
    registry.register(parent, session_id="parent", run_id="root-run", work_root=tmp_path)  # type: ignore[arg-type]
    registry.register(child, session_id="parent:sub:worker", run_id="child-run", work_root=tmp_path)  # type: ignore[arg-type]
    registry.register(other, session_id="other", run_id="other-run", work_root=tmp_path)  # type: ignore[arg-type]

    assert registry.cleanup_session("parent") == [111, 222]
    assert terminated == [111, 222]
    assert [record.pid for record in registry.list()] == [333]


@pytest.mark.asyncio
async def test_runtime_task_completion_cleans_registered_processes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process_registry = BackgroundProcessRegistry()
    runtime_registry = RuntimeTaskRegistry(background_process_registry=process_registry)
    process = _FakeProcess(444)
    terminated: list[int] = []
    monkeypatch.setattr(
        process_module,
        "terminate_process_tree",
        lambda owned: terminated.append(owned.pid),
    )
    process_registry.register(
        process,  # type: ignore[arg-type]
        session_id="thread-1",
        run_id="turn-1",
        work_root=tmp_path,
    )

    task = asyncio.create_task(asyncio.sleep(0))
    assert runtime_registry.register("thread-1", task, run_id="turn-1") is True
    await task
    await asyncio.sleep(0)

    assert terminated == [444]
    assert process_registry.list() == []


@pytest.mark.asyncio
async def test_runtime_status_poll_cannot_skip_completed_task_process_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process_registry = BackgroundProcessRegistry()
    runtime_registry = RuntimeTaskRegistry(background_process_registry=process_registry)
    process = _FakeProcess(445)
    terminated: list[int] = []
    monkeypatch.setattr(
        process_module,
        "terminate_process_tree",
        lambda owned: terminated.append(owned.pid),
    )
    process_registry.register(
        process,  # type: ignore[arg-type]
        session_id="thread-polled",
        run_id="turn-polled",
        work_root=tmp_path,
    )
    release = asyncio.Event()
    task = asyncio.create_task(release.wait())
    assert runtime_registry.register("thread-polled", task, run_id="turn-polled") is True

    release.set()
    await asyncio.sleep(0)
    assert task.done()
    assert runtime_registry.active_run_id("thread-polled") is None
    await asyncio.sleep(0)

    assert terminated == [445]
    assert process_registry.list() == []


@pytest.mark.asyncio
async def test_command_handler_passes_runtime_ownership_to_background_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = BackgroundProcessRegistry()
    captured: dict[str, object] = {}

    async def fake_background(argv, **kwargs):
        captured.update(kwargs)
        return CommandExecution(exit_code=0, background=True, metadata={"pid": 987})

    monkeypatch.setattr(command_tools_module.sys, "platform", "linux")
    monkeypatch.setattr(command_tools_module, "_run_background_subprocess", fake_background)
    handlers = CommandToolHandlers(
        work_root=tmp_path,
        command_timeout=10,
        loaded_skill_roots=set(),
        background_process_registry=registry,
    )

    result = await handlers.run_command(
        ToolCall(
            id="call-1",
            name="run_command",
            arguments={"command": "echo ready", "background": True},
            metadata={"_runtime_session_id": "session-1", "_runtime_run_id": "run-1"},
        )
    )

    assert result.status == "ok"
    assert captured["process_registry"] is registry
    assert captured["session_id"] == "session-1"
    assert captured["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_background_runner_registers_real_process_and_registry_terminates_it(
    tmp_path: Path,
) -> None:
    registry = BackgroundProcessRegistry()
    execution = await _run_background_subprocess(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        command="python sleep fixture",
        process_registry=registry,
        session_id="session-real",
        run_id="run-real",
    )
    try:
        assert execution.exit_code == 0
        [record] = registry.list(session_id="session-real", run_id="run-real")
        assert record.pid == execution.metadata["pid"]
    finally:
        terminated = registry.cleanup_run("session-real", "run-real")

    assert terminated == [execution.metadata["pid"]]
    assert registry.list() == []


@pytest.mark.asyncio
async def test_cancelling_background_start_cannot_register_process_after_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = BackgroundProcessRegistry()
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    process = _FakeProcess(555)
    terminated: list[int] = []
    monkeypatch.setattr(
        process_module,
        "terminate_process_tree",
        lambda owned: terminated.append(owned.pid),
    )

    def delayed_start(*_args, cancel_event=None, **kwargs):
        started.set()
        try:
            release.wait(timeout=2)
            # Emulate the narrow race where cancellation arrives after the
            # blocking runner's final check but immediately before ownership
            # registration.
            kwargs["process_registry"].register(
                process,  # type: ignore[arg-type]
                session_id=kwargs["session_id"],
                run_id=kwargs["run_id"],
                work_root=kwargs["cwd"],
            )
            return CommandExecution(exit_code=0, background=True, metadata={"pid": process.pid})
        finally:
            finished.set()

    monkeypatch.setattr(command_runner_module, "_run_background_subprocess_blocking", delayed_start)
    task = asyncio.create_task(_run_background_subprocess(
        [sys.executable, "-c", "pass"],
        cwd=tmp_path,
        command="delayed background fixture",
        process_registry=registry,
        session_id="thread-1:sub:qa",
        run_id="child-run",
    ))
    assert await asyncio.to_thread(started.wait, 1)

    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await asyncio.to_thread(finished.wait, 1)

    assert registry.list() == []
    assert terminated == [555]


@pytest.mark.asyncio
async def test_persistent_process_survives_turn_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process_registry = BackgroundProcessRegistry()
    runtime_registry = RuntimeTaskRegistry(background_process_registry=process_registry)
    process = _FakeProcess(777)
    terminated: list[int] = []
    monkeypatch.setattr(
        process_module,
        "terminate_process_tree",
        lambda owned: terminated.append(owned.pid),
    )
    process_registry.register(
        process,  # type: ignore[arg-type]
        session_id="thread-1",
        run_id="turn-1",
        work_root=tmp_path,
        persistent=True,
        command="python -m http.server 8123",
    )

    task = asyncio.create_task(asyncio.sleep(0))
    assert runtime_registry.register("thread-1", task, run_id="turn-1") is True
    await task
    await asyncio.sleep(0)

    assert terminated == []
    assert [record.pid for record in process_registry.list()] == [777]
    [status] = process_registry.list_status(session_id="thread-1")
    assert status.alive is True
    assert status.owned is True
    assert status.record.persistent is True


def test_persistent_process_survives_stop_and_session_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = BackgroundProcessRegistry()
    persistent = _FakeProcess(811)
    ordinary = _FakeProcess(812)
    terminated: list[int] = []
    monkeypatch.setattr(
        process_module,
        "terminate_process_tree",
        lambda owned: terminated.append(owned.pid),
    )
    registry.register(persistent, session_id="s1", run_id="r1", work_root=tmp_path, persistent=True)  # type: ignore[arg-type]
    registry.register(ordinary, session_id="s1", run_id="r2", work_root=tmp_path)  # type: ignore[arg-type]

    # Stopping the run (cleanup_run) and finishing the session (cleanup_session)
    # must spare the persistent record while ordinary records still die.
    assert registry.cleanup_run("s1", "r1") == []
    assert registry.cleanup_session("s1") == [812]
    assert [record.pid for record in registry.list()] == [811]
    assert terminated == [812]

    # Deleting the session (force cleanup) also ends the persistent process.
    assert registry.cleanup_session("s1", force=True) == [811]
    assert terminated == [812, 811]
    assert registry.list() == []


def test_persistent_record_stays_listed_after_natural_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = BackgroundProcessRegistry()
    persistent = _FakeProcess(821)
    ordinary = _FakeProcess(822)
    registry.register(persistent, session_id="s1", run_id="r1", work_root=tmp_path, persistent=True)  # type: ignore[arg-type]
    registry.register(ordinary, session_id="s1", run_id="r2", work_root=tmp_path)  # type: ignore[arg-type]
    persistent.returncode = 0
    ordinary.returncode = 0

    assert [record.pid for record in registry.list()] == [821]
    [status] = registry.list_status(session_id="s1")
    assert status.alive is False
    assert status.owned is True


def test_kill_and_forget_respect_session_ownership(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = BackgroundProcessRegistry()
    owned = _FakeProcess(831)
    terminated: list[int] = []
    monkeypatch.setattr(
        process_module,
        "terminate_process_tree",
        lambda owned_process: terminated.append(owned_process.pid),
    )
    registry.register(owned, session_id="s1", run_id="r1", work_root=tmp_path, persistent=True)  # type: ignore[arg-type]

    assert registry.kill("s2", 831) == "not_found"
    assert registry.kill("s1", 999) == "not_found"
    assert registry.kill("s1", 831) == "terminated"
    assert terminated == [831]
    assert registry.list() == []

    adopted = BackgroundProcessRecord(
        pid=832, session_id="s1", run_id="r0", work_root=str(tmp_path),
        started_at=0.0, persistent=True,
    )
    with registry._lock:
        registry._adopted[832] = adopted
    assert registry.kill("s1", 832) == "not_owned"
    assert terminated == [831]
    assert registry.forget("s1", 832) is True
    assert registry.list() == []


def test_forget_refuses_live_owned_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = BackgroundProcessRegistry()
    owned = _FakeProcess(841)
    terminated: list[int] = []
    monkeypatch.setattr(
        process_module,
        "terminate_process_tree",
        lambda owned_process: terminated.append(owned_process.pid),
    )
    registry.register(owned, session_id="s1", run_id="r1", work_root=tmp_path, persistent=True)  # type: ignore[arg-type]

    assert registry.forget("s1", 841) is False
    assert terminated == []
    assert [record.pid for record in registry.list()] == [841]
    owned.returncode = 0
    assert registry.forget("s1", 841) is True
    assert registry.list() == []


def test_persistent_archive_round_trip_and_adoption(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from lamtools_core.runtime.persistent_process_store import PersistentProcessStore

    store_path = tmp_path / "background-processes.json"
    store = PersistentProcessStore(store_path)
    live = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    terminated: list[int] = []
    monkeypatch.setattr(
        process_module,
        "terminate_process_tree",
        lambda owned: terminated.append(owned.pid),
    )
    try:
        # Crash simulation: an archive left by a previous backend run adopts
        # into a fresh registry as display-only records.
        previous = BackgroundProcessRecord(
            pid=live.pid, session_id="s1", run_id="r0", work_root=str(tmp_path),
            started_at=1.0, persistent=True, command="python long-lived fixture",
        )
        store.save([previous.to_archive()])
        adopted_registry = BackgroundProcessRegistry(store=store)
        [status] = adopted_registry.list_status(session_id="s1")
        assert status.owned is False
        assert status.alive is True
        assert status.record.command == "python long-lived fixture"
        assert adopted_registry.kill("s1", live.pid) == "not_owned"
        assert terminated == []

        # Shutdown kills owned persistent processes and clears their archive;
        # adopted records stay archived so the next start can still see them.
        assert adopted_registry.shutdown() == []
        assert [int(item["pid"]) for item in store.load()] == [live.pid]

        # Owned persistent lifecycle: registration archives, shutdown clears.
        owned_store = PersistentProcessStore(tmp_path / "owned.json")
        owned_registry = BackgroundProcessRegistry(store=owned_store)
        record = owned_registry.register(
            live,
            session_id="s1",
            run_id="r1",
            work_root=tmp_path,
            persistent=True,
            command="python long-lived fixture",
        )
        assert [int(item["pid"]) for item in owned_store.load()] == [record.pid]
        assert owned_registry.shutdown() == [record.pid]
        assert terminated == [record.pid]
        assert owned_registry.list() == []
        assert owned_store.load() == []
    finally:
        live.kill()
        live.wait(timeout=5)


def test_persistent_prompt_lists_running_session_processes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = BackgroundProcessRegistry()
    assert persistent_process_prompt(registry, "s1") == ""

    process = _FakeProcess(851)
    terminated: list[int] = []
    monkeypatch.setattr(
        process_module,
        "terminate_process_tree",
        lambda owned: terminated.append(owned.pid),
    )
    registry.register(
        process,  # type: ignore[arg-type]
        session_id="s1",
        run_id="r1",
        work_root=tmp_path,
        persistent=True,
        command="python -m http.server 8123",
    )
    prompt = persistent_process_prompt(registry, "s1")
    assert "[Persistent Background Processes]" in prompt
    assert "pid 851" in prompt
    assert "python -m http.server 8123" in prompt
    assert persistent_process_prompt(registry, "other-session") == ""

    process.returncode = 0
    assert persistent_process_prompt(registry, "s1") == ""
    registry.cleanup_session("s1", force=True)
