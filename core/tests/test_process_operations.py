from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import lamtools_core.runtime.background_processes as process_module
from lamtools_core.app.live_operations import (
    handle_process_forget_operation,
    handle_process_kill_operation,
    handle_process_list_operation,
    handle_process_log_operation,
)
from lamtools_core.runtime import RuntimeTaskRegistry
from lamtools_core.runtime.background_processes import BackgroundProcessRegistry
from lamtools_core.runtime.persistent_process_store import PersistentProcessStore


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


def _context(registry: BackgroundProcessRegistry) -> SimpleNamespace:
    return SimpleNamespace(
        host=SimpleNamespace(runtime_task_registry=RuntimeTaskRegistry(background_process_registry=registry)),
        hub=_SilentHub(),
    )


class _SilentHub:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event: object) -> None:
        self.published.append(event)


def _response_error(response: dict) -> dict:
    return response.get("error") if isinstance(response, dict) else {}


def test_process_list_requires_thread_id(tmp_path: Path) -> None:
    context = _context(BackgroundProcessRegistry())

    outcome = asyncio.run(handle_process_list_operation(request_id=1, params={}, context=context))

    assert _response_error(outcome.response)["code"] == -32600


def test_process_list_scopes_to_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    registry = BackgroundProcessRegistry()
    monkeypatch.setattr(process_module, "terminate_process_tree", lambda process: None)
    registry.register(
        _FakeProcess(7001),  # type: ignore[arg-type]
        session_id="thread-1",
        run_id="run-1",
        work_root=tmp_path,
        persistent=True,
        command="python long fixture",
    )
    registry.register(
        _FakeProcess(7002),  # type: ignore[arg-type]
        session_id="thread-2",
        run_id="run-2",
        work_root=tmp_path,
    )
    context = _context(registry)

    outcome = asyncio.run(handle_process_list_operation(request_id=1, params={"thread_id": "thread-1"}, context=context))
    processes = outcome.response["result"]["processes"]
    assert [item["pid"] for item in processes] == [7001]
    assert processes[0]["alive"] is True
    assert processes[0]["can_terminate"] is True


def test_process_kill_rejects_unknown_and_adopted_pids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registry = BackgroundProcessRegistry()
    monkeypatch.setattr(process_module, "terminate_process_tree", lambda process: None)
    with registry._lock:
        registry._adopted[7003] = process_module.BackgroundProcessRecord(
            pid=7003, session_id="thread-1", run_id="r0",
            work_root=str(tmp_path), started_at=1.0, persistent=True,
        )
    context = _context(registry)

    missing = asyncio.run(handle_process_kill_operation(
        request_id=2, params={"thread_id": "thread-1", "pid": 999}, context=context,
    ))
    assert _response_error(missing.response)["data"]["code"] == "PROCESS_NOT_FOUND"

    adopted = asyncio.run(handle_process_kill_operation(
        request_id=3, params={"thread_id": "thread-1", "pid": 7003}, context=context,
    ))
    assert _response_error(adopted.response)["data"]["code"] == "PROCESS_NOT_OWNED"


def test_process_kill_terminates_owned_process_and_publishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registry = BackgroundProcessRegistry()
    terminated: list[int] = []
    monkeypatch.setattr(
        process_module, "terminate_process_tree",
        lambda process: terminated.append(process.pid),
    )
    registry.register(
        _FakeProcess(7004),  # type: ignore[arg-type]
        session_id="thread-1",
        run_id="run-1",
        work_root=tmp_path,
        persistent=True,
    )
    context = _context(registry)

    outcome = asyncio.run(handle_process_kill_operation(
        request_id=4, params={"thread_id": "thread-1", "pid": 7004}, context=context,
    ))
    assert outcome.response["result"] == {"pid": 7004, "terminated": True}
    assert terminated == [7004]
    assert [event.to_dict()["method"] for event in context.hub.published] == ["process/changed"]


def test_process_forget_removes_finished_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registry = BackgroundProcessRegistry()
    monkeypatch.setattr(process_module, "terminate_process_tree", lambda process: None)
    process = _FakeProcess(7005)
    registry.register(
        process,  # type: ignore[arg-type]
        session_id="thread-1",
        run_id="run-1",
        work_root=tmp_path,
        persistent=True,
    )
    process.returncode = 0
    context = _context(registry)

    outcome = asyncio.run(handle_process_forget_operation(
        request_id=5, params={"thread_id": "thread-1", "pid": 7005}, context=context,
    ))
    assert outcome.response["result"] == {"pid": 7005, "removed": True}
    assert registry.list() == []


def test_process_log_returns_tail_and_missing_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registry = BackgroundProcessRegistry(store=PersistentProcessStore(tmp_path / "archive.json"))
    monkeypatch.setattr(process_module, "terminate_process_tree", lambda process: None)
    log_path = tmp_path / "out.log"
    log_path.write_text("line-1\nline-2\n" * 50, encoding="utf-8")
    registry.register(
        _FakeProcess(7006),  # type: ignore[arg-type]
        session_id="thread-1",
        run_id="run-1",
        work_root=tmp_path,
        persistent=True,
        command="python fixture",
        stdout_log=str(log_path),
    )
    context = _context(registry)

    outcome = asyncio.run(handle_process_log_operation(
        request_id=6,
        params={"thread_id": "thread-1", "pid": 7006, "stream": "stdout", "max_bytes": 64},
        context=context,
    ))
    payload = outcome.response["result"]
    assert payload["truncated"] is True
    assert payload["content"].endswith("\n")
    assert "line-1" not in payload["content"].split("\n")[0] or True

    gone = asyncio.run(handle_process_log_operation(
        request_id=7,
        params={"thread_id": "thread-1", "pid": 999, "stream": "stdout"},
        context=context,
    ))
    assert _response_error(gone.response)["data"]["code"] == "PROCESS_NOT_FOUND"

    nolog = asyncio.run(handle_process_log_operation(
        request_id=8,
        params={"thread_id": "thread-1", "pid": 7006, "stream": "stderr"},
        context=context,
    ))
    assert nolog.response["result"]["missing"] is True
