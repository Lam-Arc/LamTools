from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

import pytest

import lamtools_core.runtime.background_processes as process_module
import lamtools_core.tool.command_tools as command_tools_module
import lamtools_core.tool.command_runner as command_runner_module
from lamtools_core.runtime import RuntimeTaskRegistry
from lamtools_core.runtime.background_processes import BackgroundProcessRegistry
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
