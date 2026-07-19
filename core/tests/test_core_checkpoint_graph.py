from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lamtools_core.app import open_core_app_db
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.checkpoint import CoreCheckpointCoordinator
from lamtools_core.plugins.engine import HookEngine
from lamtools_core.plugins.models import HookDefinition, HookEvent, HookHandler
from lamtools_core.runtime import RuntimeState
from lamtools_core.session import SessionRecord
from lamtools_core.tool import ToolCall
from lamtools_core.tool.default_toolbox import build_core_toolbox


async def _runtime(
    db: Any,
    session_id: str,
    *,
    history: list[dict[str, str]],
    status: str = "completed",
) -> None:
    state = await db.runtime_state_store.get(session_id)
    if state is None:
        state = RuntimeState(session_id=session_id, status=status)
    state.status = status
    await db.runtime_state_store.save_checkpoint(state, history)


@pytest.mark.asyncio
async def test_restore_creates_a_new_graph_branch_without_deleting_later_nodes(tmp_path: Path) -> None:
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    (work_root / "state.txt").write_text("one", encoding="utf-8")
    db = await open_core_app_db(tmp_path / "core.db")
    coordinator = CoreCheckpointCoordinator(
        work_root=work_root,
        session_factory=db.session_factory,
        write_coordinator=db.persistence.write_coordinator,
        storage_root=tmp_path / "checkpoint-data",
    )
    try:
        await _runtime(db, "session-graph", history=[{"role": "user", "content": "one"}])
        first = await coordinator.save(
            session_id="session-graph",
            turn_id="turn-1",
            actor_kind="main",
            reason="manual",
            label="first",
        )

        (work_root / "state.txt").write_text("two", encoding="utf-8")
        await _runtime(db, "session-graph", history=[{"role": "user", "content": "two"}])
        second = await coordinator.save(
            session_id="session-graph",
            turn_id="turn-2",
            actor_kind="main",
            reason="manual",
            label="second",
        )

        restored = await coordinator.load(first.id)
        third = await coordinator.save(
            session_id="session-graph",
            turn_id="turn-3",
            actor_kind="main",
            reason="before_user_prompt",
            label="instruction checkpoint",
        )
        graph = await coordinator.graph("session-graph")
        nodes = {node.id: node for node in graph.nodes}

        assert nodes[second.id].parent_checkpoint_id == first.id
        assert nodes[restored.derived_checkpoint_id].parent_checkpoint_id == first.id
        assert nodes[restored.derived_checkpoint_id].edge_kind == "rollback"
        assert nodes[restored.derived_checkpoint_id].reason == "rollback_all"
        assert nodes[third.id].parent_checkpoint_id == restored.derived_checkpoint_id
        assert second.id in nodes
        assert graph.heads["session-graph"] == third.id
        assert (work_root / "state.txt").read_text(encoding="utf-8") == "one"
    finally:
        await db.close()


@pytest.mark.parametrize(
    ("scope", "expected_history", "expected_file"),
    [
        ("conversation", "before", "after"),
        ("workspace", "after", "before"),
        ("all", "before", "before"),
    ],
)
@pytest.mark.asyncio
async def test_restore_and_undo_apply_only_the_requested_scope(
    tmp_path: Path,
    scope: str,
    expected_history: str,
    expected_file: str,
) -> None:
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    state_file = work_root / "state.txt"
    state_file.write_text("before", encoding="utf-8")
    db = await open_core_app_db(tmp_path / "core.db")
    coordinator = CoreCheckpointCoordinator(
        work_root=work_root,
        session_factory=db.session_factory,
        write_coordinator=db.persistence.write_coordinator,
        storage_root=tmp_path / "checkpoint-data",
    )
    try:
        await _runtime(db, "session-scope", history=[{"role": "user", "content": "before"}])
        checkpoint = await coordinator.save(
            session_id="session-scope",
            turn_id="turn-before",
            reason="manual",
        )
        state_file.write_text("after", encoding="utf-8")
        await _runtime(db, "session-scope", history=[{"role": "user", "content": "after"}])

        restored = await coordinator.load(checkpoint.id, scope=scope)

        assert restored.scope == scope
        assert await db.runtime_state_store.get_history("session-scope") == [
            {"role": "user", "content": expected_history}
        ]
        assert state_file.read_text(encoding="utf-8") == expected_file
        assert restored.restored_paths == (() if scope == "conversation" else ("state.txt",))
        graph = await coordinator.graph("session-scope")
        derived = next(node for node in graph.nodes if node.id == restored.derived_checkpoint_id)
        assert derived.reason == f"rollback_{scope}"
        assert derived.parent_checkpoint_id == checkpoint.id

        undone = await coordinator.undo(restored.operation_id)

        assert undone.scope == scope
        assert await db.runtime_state_store.get_history("session-scope") == [
            {"role": "user", "content": "after"}
        ]
        assert state_file.read_text(encoding="utf-8") == "after"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_workspace_only_restore_is_allowed_during_an_active_turn(tmp_path: Path) -> None:
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    state_file = work_root / "state.txt"
    state_file.write_text("before", encoding="utf-8")
    db = await open_core_app_db(tmp_path / "core.db")
    coordinator = CoreCheckpointCoordinator(
        work_root=work_root,
        session_factory=db.session_factory,
        write_coordinator=db.persistence.write_coordinator,
        storage_root=tmp_path / "checkpoint-data",
    )
    try:
        await _runtime(db, "session-active", history=[{"role": "user", "content": "before"}])
        checkpoint = await coordinator.save(
            session_id="session-active",
            turn_id="turn-before",
            reason="manual",
        )
        state_file.write_text("after", encoding="utf-8")
        await _runtime(
            db,
            "session-active",
            history=[{"role": "user", "content": "active"}],
            status="running",
        )

        restored = await coordinator.load(checkpoint.id, scope="workspace")

        assert restored.scope == "workspace"
        assert state_file.read_text(encoding="utf-8") == "before"
        assert await db.runtime_state_store.get_history("session-active") == [
            {"role": "user", "content": "active"}
        ]
        with pytest.raises(ValueError, match="active"):
            await coordinator.load(checkpoint.id, scope="conversation")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_sub_agent_checkpoint_branches_from_main_and_restores_only_child_conversation(
    tmp_path: Path,
) -> None:
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    (work_root / "state.txt").write_text("before-child", encoding="utf-8")
    db = await open_core_app_db(tmp_path / "core.db")
    coordinator = CoreCheckpointCoordinator(
        work_root=work_root,
        session_factory=db.session_factory,
        write_coordinator=db.persistence.write_coordinator,
        storage_root=tmp_path / "checkpoint-data",
    )
    child_id = "session-parent:sub:implementation"
    try:
        await _runtime(db, "session-parent", history=[{"role": "user", "content": "main-before"}])
        main = await coordinator.save(
            session_id="session-parent",
            turn_id="main-turn",
            actor_kind="main",
            reason="before_user_prompt",
        )
        await _runtime(db, child_id, history=[{"role": "user", "content": "child-before"}])
        child = await coordinator.save(
            session_id=child_id,
            turn_id="child-turn",
            actor_kind="sub_agent",
            reason="before_user_prompt",
        )

        (work_root / "state.txt").write_text("after-child", encoding="utf-8")
        await _runtime(db, "session-parent", history=[{"role": "user", "content": "main-after"}])
        await _runtime(db, child_id, history=[{"role": "user", "content": "child-after"}])

        await coordinator.load(child.id)
        graph = await coordinator.graph(child_id)

        assert child.parent_checkpoint_id == main.id
        assert child.graph_id == main.graph_id
        assert await db.runtime_state_store.get_history(child_id) == [
            {"role": "user", "content": "child-before"}
        ]
        assert await db.runtime_state_store.get_history("session-parent") == [
            {"role": "user", "content": "main-after"}
        ]
        assert (work_root / "state.txt").read_text(encoding="utf-8") == "before-child"
        assert {node.session_id for node in graph.nodes} == {"session-parent", child_id}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_fork_creates_a_new_session_and_marks_the_graph_edge(tmp_path: Path) -> None:
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    db = await open_core_app_db(tmp_path / "core.db")
    sessions = CoreDbSessionStore(lambda: db)
    coordinator = CoreCheckpointCoordinator(
        work_root=work_root,
        session_factory=db.session_factory,
        write_coordinator=db.persistence.write_coordinator,
        storage_root=tmp_path / "checkpoint-data",
    )
    try:
        await sessions.create(SessionRecord(
            id="session-source",
            member_id="core",
            title="Source",
            status="idle",
            metadata={"work_root": str(work_root)},
        ))
        await _runtime(
            db,
            "session-source",
            history=[{"role": "user", "content": "source history"}],
        )
        source = await coordinator.save(
            session_id="session-source",
            turn_id="source-turn",
            actor_kind="main",
            reason="manual",
        )

        forked = await coordinator.fork(source.id, new_session_id="session-forked")
        graph = await coordinator.graph("session-forked")
        fork_session = await sessions.get("session-forked")

        assert forked.session_id == "session-forked"
        assert forked.parent_checkpoint_id == source.id
        assert forked.edge_kind == "session_fork"
        assert forked.label == "分叉到新会话"
        assert forked.graph_id == source.graph_id
        assert graph.heads["session-forked"] == forked.id
        assert await db.runtime_state_store.get_history("session-forked") == [
            {"role": "user", "content": "source history"}
        ]
        assert fork_session is not None
        assert fork_session.metadata["forked_from_session_id"] == "session-source"
        assert fork_session.metadata["forked_from_checkpoint_id"] == source.id
        with pytest.raises(ValueError, match="session family"):
            await coordinator.load(
                source.id,
                scope="workspace",
                requesting_session_id="session-forked",
            )
    finally:
        await db.close()


class _RecordingCheckpointCoordinator:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def save(self, **kwargs: str) -> Any:
        self.calls.append(dict(kwargs))
        return type("Checkpoint", (), {"id": "hook-checkpoint"})()


@pytest.mark.asyncio
async def test_checkpoint_hook_can_filter_high_risk_command_input() -> None:
    checkpoints = _RecordingCheckpointCoordinator()
    hook = HookDefinition(
        id="checkpoint-before-remove",
        event="PreToolUse",
        matcher="run_command",
        source="project",
        source_name="project",
        config_path=Path("hooks.json"),
        trusted=True,
        status="trusted",
        handler=HookHandler(
            type="checkpoint",
            reason="high_risk_command",
            label="高危命令前自动存档",
            input_pattern=r"(?i)\b(remove-item|rm|del)\b",
        ),
    )
    engine = HookEngine([hook], checkpoint_coordinator=checkpoints)

    harmless = await engine.run(HookEvent(
        event_name="PreToolUse",
        session_id="session-hook",
        run_id="run-hook",
        turn_id="turn-hook",
        tool_name="run_command",
        tool_input={"command": "Get-ChildItem"},
    ))
    dangerous = await engine.run(HookEvent(
        event_name="PreToolUse",
        session_id="session-hook",
        run_id="run-hook",
        turn_id="turn-hook",
        tool_name="run_command",
        tool_input={"command": "Remove-Item -LiteralPath temp.txt"},
    ))

    assert checkpoints.calls == [{
        "session_id": "session-hook",
        "turn_id": "turn-hook:hook:checkpoint-before-remove",
        "actor_kind": "hook",
        "reason": "high_risk_command",
        "label": "高危命令前自动存档",
        "edge_kind": "hook",
    }]
    assert harmless.audit_events[0]["status"] == "skipped_input_pattern"
    assert dangerous.audit_events[0]["checkpoint_id"] == "hook-checkpoint"


@pytest.mark.asyncio
async def test_checkpoint_tools_share_the_coordinator_for_save_load_and_graph(tmp_path: Path) -> None:
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    state_file = work_root / "state.txt"
    state_file.write_text("before", encoding="utf-8")
    db = await open_core_app_db(tmp_path / "core.db")
    coordinator = CoreCheckpointCoordinator(
        work_root=work_root,
        session_factory=db.session_factory,
        write_coordinator=db.persistence.write_coordinator,
        storage_root=tmp_path / "checkpoint-data",
    )
    toolbox = build_core_toolbox(
        work_root=work_root,
        approval_policy="auto_approve",
        checkpoint_coordinator=coordinator,
    )
    try:
        await _runtime(db, "session-tools", history=[{"role": "user", "content": "before"}])
        names = {spec.name for spec in toolbox.tool_specs()}
        assert {"checkpoint_save", "checkpoint_load", "checkpoint_graph"} <= names

        save_call = toolbox.prepare_call(ToolCall(
            id="save-1",
            name="checkpoint_save",
            arguments={"label": "manual"},
            metadata={"_runtime_session_id": "session-tools", "_runtime_run_id": "run-1"},
        ))
        saved = await toolbox.execute(save_call)
        assert saved.status == "ok", saved.error
        child_saved = await toolbox.execute(ToolCall(
            id="save-child-1",
            name="checkpoint_save",
            arguments={"session_id": "session-tools:sub:worker", "label": "child"},
            metadata={"_runtime_session_id": "session-tools", "_runtime_run_id": "run-1"},
        ))
        assert child_saved.status == "ok", child_saved.error
        state_file.write_text("after", encoding="utf-8")
        await _runtime(db, "session-tools", history=[{"role": "user", "content": "after"}])
        graph = await toolbox.execute(ToolCall(
            id="graph-1",
            name="checkpoint_graph",
            arguments={"session_id": "session-tools"},
            metadata={"_runtime_session_id": "session-tools"},
        ))
        loaded = await toolbox.execute(ToolCall(
            id="load-1",
            name="checkpoint_load",
            arguments={"checkpoint_id": child_saved.metadata["id"]},
            metadata={"_runtime_session_id": "session-tools"},
        ))

        assert graph.status == "ok"
        assert graph.metadata["heads"]["session-tools"] == saved.metadata["id"]
        assert graph.metadata["heads"]["session-tools:sub:worker"] == child_saved.metadata["id"]
        assert loaded.status == "ok"
        assert loaded.metadata["scope"] == "workspace"
        assert loaded.metadata["derived_checkpoint_id"]
        assert state_file.read_text(encoding="utf-8") == "before"
        assert await db.runtime_state_store.get_history("session-tools") == [
            {"role": "user", "content": "after"}
        ]
        load_spec = next(spec for spec in toolbox.tool_specs() if spec.name == "checkpoint_load")
        assert "scope" not in load_spec.input_schema["properties"]
    finally:
        await db.close()
