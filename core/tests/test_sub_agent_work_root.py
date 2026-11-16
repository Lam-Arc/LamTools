"""sub_agent 的可选 work_root：不传就等于父会话目录，传了就是这只子代理自己的目录。

user:“派工复用 sub_agent 加一个可选 work_root。空的 work_root 完全保持现有行为”
+(派工时给子代理一份独立工作区，两只子代理不会改同一份文件；不传则与现在完全一致)。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.sub_agent_supervisor import SubAgentSupervisor
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import build_core_toolbox


@pytest.fixture(autouse=True)
def _accept_any_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """These cases are about directories, not model resolution."""
    monkeypatch.setattr(
        "lamtools_core.sub_agent_supervisor.resolve_model_id",
        lambda value, work_root=None: str(value),
    )


class _Runner:
    """Minimal execution owner: the supervisor only reads work_root here."""

    def __init__(self, work_root: Path) -> None:
        self.work_root = work_root
        self.session_prefix = "thread-parent"

    async def run(self, **_kwargs):
        raise AssertionError("this test never starts a turn")


def _supervisor(tmp_path: Path) -> SubAgentSupervisor:
    project = tmp_path / "project"
    project.mkdir()
    return SubAgentSupervisor(
        parent_thread_id="thread-parent",
        runner=_Runner(project),
        database_path=tmp_path / "data" / "sub_agents.sqlite3",
    )


@pytest.mark.asyncio
async def test_a_sub_agent_without_work_root_uses_the_project_directory(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)

    result = await supervisor.create_operation(
        type="execute", name="worker", model="m", reasoning_level="high"
    )

    assert result.record.execution_directory == ""
    assert supervisor.member_execution_directory("worker") == str((tmp_path / "project").resolve())


@pytest.mark.asyncio
async def test_a_sub_agent_with_work_root_is_confined_to_that_directory(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    child = tmp_path / "project" / ".worktrees" / "ticket-1"
    child.mkdir(parents=True)

    result = await supervisor.create_operation(
        type="execute",
        name="worker",
        model="m",
        reasoning_level="high",
        execution_directory=str(child),
    )

    assert result.record.execution_directory == str(child)
    assert supervisor.member_execution_directory("worker") == str(child)


class _FakeSupervisor:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_operation(self, **kwargs):
        self.calls.append(kwargs)

        class _Operation:
            def to_dict(self) -> dict:
                return {"ok": True}

        return _Operation()


@pytest.mark.asyncio
async def test_the_tool_creates_the_workspace_and_passes_it_as_the_execution_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeSupervisor()

    async def fake_supervisor(**_kwargs):
        return fake

    monkeypatch.setattr(
        "lamtools_core.sub_agent_supervisor.get_sub_agent_supervisor", fake_supervisor
    )
    runner = _Runner(tmp_path)
    toolbox = build_core_toolbox(work_root=tmp_path, sub_agent_runner=runner)

    result = await toolbox.execute(
        ToolCall(
            id="create-worker",
            name="sub_agent",
            arguments={
                "action": "create",
                "type": "execute",
                "name": "worker",
                "model": "m",
                "reasoning_level": "high",
                "work_root": "worktrees/ticket-1",
            },
        )
    )

    assert result.status == "ok", result.error
    child = (tmp_path / "worktrees" / "ticket-1").resolve()
    assert child.is_dir(), "宿主必须先把目录开出来"
    assert fake.calls[0]["execution_directory"] == str(child)


@pytest.mark.asyncio
async def test_the_tool_refuses_a_workspace_outside_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeSupervisor()

    async def fake_supervisor(**_kwargs):
        return fake

    monkeypatch.setattr(
        "lamtools_core.sub_agent_supervisor.get_sub_agent_supervisor", fake_supervisor
    )
    toolbox = build_core_toolbox(work_root=tmp_path, sub_agent_runner=_Runner(tmp_path))

    result = await toolbox.execute(
        ToolCall(
            id="create-escape",
            name="sub_agent",
            arguments={
                "action": "create",
                "type": "execute",
                "name": "worker",
                "model": "m",
                "reasoning_level": "high",
                "work_root": "../outside",
            },
        )
    )

    assert result.status == "failed"
    assert "inside the project" in (result.error or "")
    assert fake.calls == []
