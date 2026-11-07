"""The polled sub_agent.list RPC must not pay setup cost on every poll.

During the 2026-10-30 incident the UI polled `sub_agent.list` every ~220 ms
(108 calls in five minutes were logged). Each call used to build a fresh runner
(config discovery, plugin assembly, skill runtime, global permission load) and
read the core database once, only to discover a supervisor this process already
owned — work that then competed with every other database user for the same
small connection pool.

These tests pin the fix: once a supervisor exists for a thread, the lifecycle
RPCs reuse it without rebuilding the runner or opening another core-DB session.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from lamtools_core import sub_agent_supervisor as supervisor_module


class _FakeStateStore:
    def __init__(self) -> None:
        self.get_calls = 0

    async def get(self, session_id: str) -> Any:
        self.get_calls += 1
        return None


class _FakeRunner:
    """Only the surface the supervisor and lifecycle RPCs touch."""

    def __init__(self) -> None:
        self.state_store = _FakeStateStore()
        self.work_root = Path(".")
        self.session_prefix = ""
        self.runtime_snapshot: dict[str, Any] = {}
        self.approval_policy = "require"
        self.permission_preset = "ask"
        self.active_tier = ""
        self.tier_tools: dict[str, Any] = {}
        self.allow_access_outside_workdir = False

    async def run(self, **_kwargs: Any) -> Any:  # pragma: no cover - not executed here
        raise AssertionError("sub_agent.list must not run a member")

    async def resume_interrupted(self, **_kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("sub_agent.list must not run a member")


class _Catalog:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def register(self, name: str, handler: Any) -> None:
        self.handlers[name] = handler

    def has(self, name: str) -> bool:
        return name in self.handlers


class _Request:
    def __init__(self, name: str, payload: dict[str, Any]) -> None:
        self.name = name
        self.payload = payload
        self.metadata: dict[str, Any] = {}


@pytest.fixture(autouse=True)
def _clean_supervisors() -> Any:
    supervisor_module._SUPERVISORS.clear()
    yield
    supervisor_module._SUPERVISORS.clear()


@pytest.mark.asyncio
async def test_repeated_list_reuses_supervisor_without_rebuilding_the_runner(
    tmp_path: Path,
) -> None:
    catalog = _Catalog()
    built: list[_FakeRunner] = []

    def factory() -> _FakeRunner:
        runner = _FakeRunner()
        built.append(runner)
        return runner

    supervisor_module.register_sub_agent_lifecycle_operations(
        catalog,
        runner_factory=factory,
        data_dir=tmp_path,
    )
    handler = catalog.handlers["sub_agent.list"]
    assert handler is not None

    first = await handler(_Request("sub_agent.list", {"thread_id": "thread-1"}))
    second = await handler(_Request("sub_agent.list", {"thread_id": "thread-1"}))
    third = await handler(_Request("sub_agent.list", {"thread_id": "thread-1"}))

    assert len(built) == 1, "a poll must not rebuild the runner while a supervisor lives"
    assert built[0].state_store.get_calls == 1, "a poll must not read core.db again"
    assert first.payload == {"items": []}
    assert second.payload == {"items": []}
    assert third.payload == {"items": []}


@pytest.mark.asyncio
async def test_list_returns_records_and_keeps_serving_them(tmp_path: Path) -> None:
    catalog = _Catalog()
    built: list[_FakeRunner] = []

    def factory() -> _FakeRunner:
        runner = _FakeRunner()
        built.append(runner)
        return runner

    supervisor_module.register_sub_agent_lifecycle_operations(
        catalog,
        runner_factory=factory,
        data_dir=tmp_path,
    )
    handler = catalog.handlers["sub_agent.list"]

    await handler(_Request("sub_agent.list", {"thread_id": "thread-2"}))
    supervisor = supervisor_module.find_sub_agent_supervisor("thread-2", data_dir=tmp_path)
    assert supervisor is not None
    supervisor._save(
        supervisor_module.SubAgentRecord(
            parent_thread_id="thread-2",
            type="consider",
            name="helper",
            model_id="fake-model",
            reasoning_level="medium",
            status="enabled",
        )
    )

    listed = await handler(_Request("sub_agent.list", {"thread_id": "thread-2"}))
    names = [item["name"] for item in listed.payload["items"]]
    assert names == ["helper"]
    assert len(built) == 1
    assert built[0].state_store.get_calls == 1


@pytest.mark.asyncio
async def test_concurrent_cold_start_builds_one_supervisor(tmp_path: Path) -> None:
    """冷会话的第一批并发轮询只能建一个监督器（否则每条都付一次装配与一次库读）。"""
    catalog = _Catalog()
    built: list[_FakeRunner] = []

    def factory() -> _FakeRunner:
        runner = _FakeRunner()
        built.append(runner)
        return runner

    supervisor_module.register_sub_agent_lifecycle_operations(
        catalog,
        runner_factory=factory,
        data_dir=tmp_path,
    )
    handler = catalog.handlers["sub_agent.list"]

    await asyncio.gather(
        *[handler(_Request("sub_agent.list", {"thread_id": "cold"})) for _ in range(6)]
    )

    assert len(built) == 1
    assert built[0].state_store.get_calls == 1
    assert supervisor_module.find_sub_agent_supervisor("cold", data_dir=tmp_path) is not None


@pytest.mark.asyncio
async def test_different_threads_get_their_own_supervisor(tmp_path: Path) -> None:
    catalog = _Catalog()
    built: list[_FakeRunner] = []

    def factory() -> _FakeRunner:
        runner = _FakeRunner()
        built.append(runner)
        return runner

    supervisor_module.register_sub_agent_lifecycle_operations(
        catalog,
        runner_factory=factory,
        data_dir=tmp_path,
    )
    handler = catalog.handlers["sub_agent.list"]

    await asyncio.gather(
        handler(_Request("sub_agent.list", {"thread_id": "thread-a"})),
        handler(_Request("sub_agent.list", {"thread_id": "thread-b"})),
    )
    await handler(_Request("sub_agent.list", {"thread_id": "thread-a"}))
    await handler(_Request("sub_agent.list", {"thread_id": "thread-b"}))

    assert len(built) == 2
    assert supervisor_module.find_sub_agent_supervisor("thread-a", data_dir=tmp_path) is not None
    assert supervisor_module.find_sub_agent_supervisor("thread-b", data_dir=tmp_path) is not None
