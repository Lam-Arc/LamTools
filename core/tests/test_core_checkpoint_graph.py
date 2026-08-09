from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lamtools_core.app import open_core_app_db
from lamtools_core.app.core_db import CoreThreadSnapshot
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.event_store import AppEventInput
from lamtools_core.checkpoint import CoreCheckpointCoordinator
from lamtools_core.event import RunItemEvent
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
async def test_restore_creates_a_new_branch_and_prunes_the_abandoned_future(tmp_path: Path) -> None:
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

        # simulate a tool write: back the file up before modifying it (lazy capture)
        await coordinator.backup_file(session_id="session-graph", path=work_root / "state.txt")
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

        undo = nodes.get(restored.undo_checkpoint_id)
        derived = nodes.get(restored.derived_checkpoint_id)
        assert undo is not None and undo.parent_checkpoint_id == first.id
        assert derived is not None and derived.edge_kind == "rollback"
        assert derived.reason == "rollback_all"
        assert derived.parent_checkpoint_id == undo.id
        assert nodes[third.id].parent_checkpoint_id == derived.id
        # Rolling back to `first` abandons the old future (`second`) — it is
        # pruned from the main line and can no longer be revisited.
        assert second.id not in nodes
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
async def test_restore_applies_only_the_requested_scope(
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
        # simulate a tool write: back the file up before modifying it (lazy capture)
        await coordinator.backup_file(session_id="session-scope", path=state_file)
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
        undo = next(node for node in graph.nodes if node.id == restored.undo_checkpoint_id)
        assert derived.reason == f"rollback_{scope}"
        assert derived.parent_checkpoint_id == undo.id
        assert undo.parent_checkpoint_id == checkpoint.id
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
        # simulate a tool write: back the file up before modifying it (lazy capture)
        await coordinator.backup_file(session_id="session-active", path=state_file)
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

        # simulate a tool write: back the file up before modifying it (lazy capture)
        await coordinator.backup_file(session_id=child_id, path=work_root / "state.txt")
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


@pytest.mark.asyncio
async def test_fork_with_events_remaps_item_keys_and_regenerates_event_ids(tmp_path: Path) -> None:
    """Regression: forking a checkpoint that captured an event stream used to
    (1) crash on the global event_id primary key and (2) leave the forked
    projection's item dict keys pointing at the source session, so the
    frontend dropped every pre-fork message (new messages appeared at the
    top of the thread). Both must now be fixed."""
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
        await _runtime(db, "session-source", history=[{"role": "user", "content": "hello"}])
        async with db.session_factory() as session:
            await db.event_store.append(session, AppEventInput(
                thread_id="session-source", method="thread/started", payload={"status": "idle"},
            ))
            await db.event_store.append(session, AppEventInput(
                thread_id="session-source", method="turn/accepted",
                payload={"turn_id": "turn-0", "input": "hello"}, turn_id="turn-0",
            ))
            await db.event_store.append_run_item_event(session, RunItemEvent(
                kind="message", thread_id="session-source", event_id="evt-user",
                turn_id="turn-0", item_id="session-source:turn:turn-0:user",
                status="completed", payload={"role": "user", "content": "hello"},
            ))
            await db.event_store.append_run_item_event(session, RunItemEvent(
                kind="message", thread_id="session-source", event_id="evt-assistant",
                turn_id="turn-0", item_id="session-source:turn:turn-0:assistant",
                status="running", payload={"role": "assistant", "content": "ok"},
            ))
            events = await db.event_store.list_thread(session, thread_id="session-source")
            await db.snapshot_store.apply_many(session, events)
            await session.commit()

        # Checkpoint at the boundary BEFORE turn-1: the captured event stream
        # (turn-0's messages) is what a fork must replay into the new session.
        source = await coordinator.save(
            session_id="session-source",
            turn_id="turn-1",
            actor_kind="main",
            reason="manual",
        )
        forked = await coordinator.fork(source.id, new_session_id="session-forked")
        assert forked.session_id == "session-forked"

        # 1) Forked events must not collide with the source events' global ids.
        async with db.session_factory() as session:
            source_events = await db.event_store.list_thread(session, thread_id="session-source")
            forked_events = await db.event_store.list_thread(session, thread_id="session-forked")
            row = await session.get(CoreThreadSnapshot, "session-forked")
        assert len(forked_events) == len(source_events)
        assert {e.event_id for e in forked_events}.isdisjoint({e.event_id for e in source_events})
        assert all(
            str(e.item_id or "").startswith("session-forked:")
            for e in forked_events
            if e.item_id
        )

        # 2) Projection item dict keys must be remapped to the fork session and
        #    stay consistent with item_order so the frontend can join them.
        assert row is not None
        core = row.snapshot_json["core"]
        assert all(str(key).startswith("session-forked:") for key in core["items"])
        assert all(iid in core["items"] for iid in core["item_order"])
        assert all(
            str(item.get("item_id", "")).startswith("session-forked:")
            for item in core["items"].values()
        )
        assert len(core["items"]) == 2
    finally:
        await db.close()
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def save(self, **kwargs: str) -> Any:
        self.calls.append(dict(kwargs))
        return type("Checkpoint", (), {"id": "hook-checkpoint"})()


@pytest.mark.asyncio
@pytest.mark.skip(reason="checkpoint hooks were removed from HookEngine; checkpointing is now an operation-catalog concern")
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
            command="checkpoint save --reason high_risk_command",
        ),
    )
    engine = HookEngine([hook])

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
    from lamtools_core.app.operation_catalog import OperationCatalog, OperationResult

    catalog = OperationCatalog()
    from lamtools_core.checkpoint import register_checkpoint_operations

    register_checkpoint_operations(
        catalog,
        session_factory=db.session_factory,
        data_dir=tmp_path / "core-data",
        default_work_root=work_root,
    )

    async def op(name: str, payload: dict[str, Any]) -> OperationResult:
        return await catalog.execute(name, payload)

    try:
        await _runtime(db, "session-tools", history=[{"role": "user", "content": "before"}])
        names = set(catalog.list())
        assert {"session.checkpoints.create", "session.checkpoints.list", "session.checkpoints.graph", "session.checkpoints.restore"} <= names

        saved = await op("session.checkpoints.create", {
            "session_id": "session-tools",
            "label": "manual",
        })
        assert saved.status == "ok", saved.error
        child_saved = await op("session.checkpoints.create", {
            "session_id": "session-tools:sub:worker",
            "label": "child",
        })
        assert child_saved.status == "ok", child_saved.error
        state_file.write_text("after", encoding="utf-8")
        await _runtime(db, "session-tools", history=[{"role": "user", "content": "after"}])
        graph = await op("session.checkpoints.graph", {"session_id": "session-tools"})
        loaded = await op("session.checkpoints.restore", {
            "session_id": "session-tools",
            "checkpoint_id": child_saved.payload["checkpoint"]["id"],
        })

        assert graph.status == "ok"
        graph_payload = graph.payload
        assert graph_payload["heads"]["session-tools"] == saved.payload["checkpoint"]["id"]
        assert graph_payload["heads"]["session-tools:sub:worker"] == child_saved.payload["checkpoint"]["id"]
        assert loaded.status == "ok"
        assert loaded.payload.get("scope") in {"workspace", "all", "conversation"}
        assert loaded.payload.get("derived_checkpoint_id")
        # Lazy capture: the file was edited without backup_file(), so the
        # workspace is intentionally NOT rolled back (only tool-backed edits are).
        assert state_file.read_text(encoding="utf-8") == "after"
        assert await db.runtime_state_store.get_history("session-tools") == [
            {"role": "user", "content": "after"}
        ]
    finally:
        await db.close()
