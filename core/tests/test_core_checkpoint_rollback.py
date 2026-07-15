from __future__ import annotations

import importlib
import subprocess
from pathlib import Path
from typing import Any

import pytest

from lamtools_core.app import open_core_app_db
from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.event import CollectingEventSink
from lamtools_core.kernel import CoreLoopKernel
from lamtools_core.llm import LLMRequest, LLMResponse, LLMStreamEvent
from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState, RuntimeTurnInput
from lamtools_core.session import MessageRecord, SessionRecord
from lamtools_core.tool.sub_agent_runner import KernelSubAgentRunner


def _checkpoint_coordinator_type():
    module = importlib.import_module("lamtools_core.checkpoint")
    return module.CoreCheckpointCoordinator


def _git(work_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=work_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_mixed_workspace(work_root: Path) -> None:
    work_root.mkdir()
    _git(work_root, "init", "-q")
    _git(work_root, "config", "user.email", "checkpoint-test@example.test")
    _git(work_root, "config", "user.name", "Checkpoint Test")
    _write(work_root / ".gitignore", "ignored.txt\ncreated-ignored.txt\n")
    _write(work_root / "tracked.txt", "tracked-before\n")
    _write(work_root / "deleted.txt", "deleted-before\n")
    _write(work_root / "rename-old.txt", "rename-before\n")
    _git(work_root, "add", ".gitignore", "tracked.txt", "deleted.txt", "rename-old.txt")
    _git(work_root, "commit", "-q", "-m", "baseline")
    _write(work_root / "untracked.txt", "untracked-before\n")
    _write(work_root / "ignored.txt", "ignored-before\n")


def _mutate_workspace_after_checkpoint(work_root: Path) -> None:
    _write(work_root / "tracked.txt", "tracked-after\n")
    (work_root / "deleted.txt").unlink()
    (work_root / "rename-old.txt").rename(work_root / "rename-new.txt")
    _write(work_root / "untracked.txt", "untracked-after\n")
    _write(work_root / "created.txt", "created-after\n")
    _write(work_root / "ignored.txt", "ignored-after\n")
    _write(work_root / "created-ignored.txt", "created-ignored-after\n")


def _assert_workspace_before_turn(work_root: Path) -> None:
    assert (work_root / "tracked.txt").read_text(encoding="utf-8") == "tracked-before\n"
    assert (work_root / "deleted.txt").read_text(encoding="utf-8") == "deleted-before\n"
    assert (work_root / "rename-old.txt").read_text(encoding="utf-8") == "rename-before\n"
    assert not (work_root / "rename-new.txt").exists()
    assert (work_root / "untracked.txt").read_text(encoding="utf-8") == "untracked-before\n"
    assert not (work_root / "created.txt").exists()
    assert (work_root / "ignored.txt").read_text(encoding="utf-8") == "ignored-before\n"
    assert not (work_root / "created-ignored.txt").exists()


def _assert_workspace_after_turn(work_root: Path) -> None:
    assert (work_root / "tracked.txt").read_text(encoding="utf-8") == "tracked-after\n"
    assert not (work_root / "deleted.txt").exists()
    assert not (work_root / "rename-old.txt").exists()
    assert (work_root / "rename-new.txt").read_text(encoding="utf-8") == "rename-before\n"
    assert (work_root / "untracked.txt").read_text(encoding="utf-8") == "untracked-after\n"
    assert (work_root / "created.txt").read_text(encoding="utf-8") == "created-after\n"
    assert (work_root / "ignored.txt").read_text(encoding="utf-8") == "ignored-after\n"
    assert (work_root / "created-ignored.txt").read_text(encoding="utf-8") == "created-ignored-after\n"


@pytest.mark.asyncio
async def test_checkpoint_restores_conversation_and_all_workspace_file_classes_and_can_be_undone(
    tmp_path: Path,
) -> None:
    """One public checkpoint must own conversation and workspace rollback together."""
    work_root = tmp_path / "workspace"
    _init_mixed_workspace(work_root)
    db = await open_core_app_db(tmp_path / "core.db")
    sessions = CoreDbSessionStore(lambda: db)
    coordinator_type = _checkpoint_coordinator_type()
    coordinator = coordinator_type(
        work_root=work_root,
        session_factory=db.session_factory,
        write_coordinator=db.persistence.write_coordinator,
        storage_root=tmp_path / "checkpoint-data",
    )
    try:
        await sessions.create(SessionRecord(
            id="session-rollback",
            member_id="core",
            title="Rollback",
            status="idle",
            metadata={"work_root": str(work_root)},
        ))
        await sessions.add_message(MessageRecord(
            id="message-before",
            session_id="session-rollback",
            role="user",
            content="first turn",
        ))
        await db.runtime_state_store.save_checkpoint(
            RuntimeState(session_id="session-rollback", run_id="turn-1", status="completed"),
            [{"role": "user", "content": "first turn"}],
        )

        checkpoint = await coordinator.begin_turn(
            session_id="session-rollback",
            turn_id="turn-2",
            actor_kind="main",
        )

        _mutate_workspace_after_checkpoint(work_root)
        await sessions.add_message(MessageRecord(
            id="message-after",
            session_id="session-rollback",
            role="assistant",
            content="second turn",
        ))
        state = await db.runtime_state_store.get("session-rollback")
        assert state is not None
        state.run_id = "turn-2"
        await db.runtime_state_store.save_checkpoint(
            state,
            [
                {"role": "user", "content": "first turn"},
                {"role": "assistant", "content": "second turn"},
            ],
        )

        restored = await coordinator.restore(checkpoint.id)

        assert restored.status == "committed"
        assert [message.content for message in await sessions.list_messages("session-rollback")] == ["first turn"]
        assert await db.runtime_state_store.get_history("session-rollback") == [
            {"role": "user", "content": "first turn"}
        ]
        _assert_workspace_before_turn(work_root)

        undone = await coordinator.undo(restored.operation_id)

        assert undone.status == "committed"
        assert [message.content for message in await sessions.list_messages("session-rollback")] == [
            "first turn",
            "second turn",
        ]
        assert await db.runtime_state_store.get_history("session-rollback") == [
            {"role": "user", "content": "first turn"},
            {"role": "assistant", "content": "second turn"},
        ]
        _assert_workspace_after_turn(work_root)
    finally:
        await db.close()


class _RecordingCheckpointCoordinator:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def begin_turn(self, *, session_id: str, turn_id: str, actor_kind: str = "main") -> Any:
        self.calls.append({
            "session_id": session_id,
            "turn_id": turn_id,
            "actor_kind": actor_kind,
        })
        return type("Checkpoint", (), {"id": f"checkpoint-{len(self.calls)}"})()


class _CheckpointOrderingLLM:
    def __init__(self, checkpoints: _RecordingCheckpointCoordinator, expected_count: int) -> None:
        self.checkpoints = checkpoints
        self.expected_count = expected_count

    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise AssertionError("Core runtime should use streaming")

    async def stream(self, request: LLMRequest):
        assert len(self.checkpoints.calls) == self.expected_count
        yield LLMStreamEvent(kind="content_delta", content="done")
        yield LLMStreamEvent(kind="done")


@pytest.mark.asyncio
async def test_main_agent_creates_checkpoint_before_the_model_sees_each_turn(tmp_path: Path) -> None:
    checkpoints = _RecordingCheckpointCoordinator()
    kernel = CoreLoopKernel(
        kit=CoreBaseAgentKit(
            work_root=tmp_path,
            config=CoreBaseAgentConfig(model_id="fake-model", approval_policy="auto_approve"),
        ),
        llm_client=_CheckpointOrderingLLM(checkpoints, expected_count=1),
        state_store=InMemoryRuntimeStateStore(),
        event_sink=CollectingEventSink(),
        checkpoint_coordinator=checkpoints,
    )

    await kernel.run(RuntimeTurnInput(
        user_message="main task",
        run_id="main-run-1",
        turn_id="main-turn-1",
        metadata={"session_id": "main-session"},
    ))
    kernel.llm_client = _CheckpointOrderingLLM(checkpoints, expected_count=2)
    await kernel.run(RuntimeTurnInput(
        user_message="main follow-up",
        run_id="main-run-2",
        turn_id="main-turn-2",
        metadata={"session_id": "main-session"},
    ))

    assert checkpoints.calls == [
        {
            "session_id": "main-session",
            "turn_id": "main-turn-1",
            "actor_kind": "main",
        },
        {
            "session_id": "main-session",
            "turn_id": "main-turn-2",
            "actor_kind": "main",
        },
    ]


@pytest.mark.asyncio
async def test_two_sub_agents_each_create_a_checkpoint_before_their_model_turn(tmp_path: Path) -> None:
    checkpoints = _RecordingCheckpointCoordinator()
    first = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=_CheckpointOrderingLLM(checkpoints, expected_count=1),
        model_id="fake-model",
        session_prefix="parent-session",
        checkpoint_coordinator=checkpoints,
    )
    second = KernelSubAgentRunner(
        work_root=tmp_path,
        llm_client=_CheckpointOrderingLLM(checkpoints, expected_count=2),
        model_id="fake-model",
        session_prefix="parent-session",
        checkpoint_coordinator=checkpoints,
    )

    await first.run(task="design architecture", agent="architecture")
    await second.run(task="implement design", agent="implementation")

    assert [call["actor_kind"] for call in checkpoints.calls] == ["sub_agent", "sub_agent"]
    assert [call["session_id"] for call in checkpoints.calls] == [
        "parent-session:sub:architecture",
        "parent-session:sub:implementation",
    ]
    assert all(call["turn_id"] for call in checkpoints.calls)
