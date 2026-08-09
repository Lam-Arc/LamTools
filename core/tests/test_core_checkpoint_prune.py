from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from lamtools_core.app import open_core_app_db
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.checkpoint import (
    MAX_CHECKPOINTS_PER_SESSION,
    CoreCheckpointCoordinator,
)
from lamtools_core.runtime import RuntimeState
from lamtools_core.session import SessionRecord


async def _make_coordinator(core_db: Path, work_root: Path):
    db = await open_core_app_db(core_db)
    sessions = CoreDbSessionStore(lambda: db)
    if await sessions.get("prune-session") is None:
        await sessions.create(SessionRecord(
            id="prune-session",
            member_id="core",
            title="prune-session",
            status="idle",
            metadata={"work_root": str(work_root)},
        ))
    await db.runtime_state_store.save(RuntimeState(
        session_id="prune-session",
        run_id="",
        status="idle",
    ))
    coordinator = CoreCheckpointCoordinator(
        work_root=work_root,
        session_factory=db.session_factory,
        write_coordinator=db.persistence.write_coordinator,
    )
    return db, coordinator


async def _save_chain(coordinator, count: int, *, parent: str | None = None) -> list[str]:
    """Create ``count`` checkpoints, returning their ids in creation order."""
    ids: list[str] = []
    for index in range(count):
        ref = await coordinator.save(
            session_id="prune-session",
            turn_id=f"prune-turn-{index + 1}",
            parent_checkpoint_id=parent,
        )
        ids.append(ref.id)
    return ids


async def _graph_ids(coordinator) -> list[str]:
    graph = await coordinator.graph("prune-session")
    return [node.id for node in graph.nodes]


@pytest.mark.asyncio
async def test_prune_keeps_only_recent_mainline_nodes(tmp_path: Path) -> None:
    core_db = tmp_path / "core.db"
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    db, coordinator = await _make_coordinator(core_db, work_root)
    try:
        ids = await _save_chain(coordinator, MAX_CHECKPOINTS_PER_SESSION + 2)
        graph_ids = await _graph_ids(coordinator)

        # Oldest two are pruned; the most recent six remain in order.
        assert ids[0] not in graph_ids
        assert ids[1] not in graph_ids
        assert graph_ids == ids[2:]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_prune_relinks_child_of_pruned_node(tmp_path: Path) -> None:
    core_db = tmp_path / "core.db"
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    db, coordinator = await _make_coordinator(core_db, work_root)
    try:
        ids = await _save_chain(coordinator, MAX_CHECKPOINTS_PER_SESSION + 2)
        graph = await coordinator.graph("prune-session")
        nodes = {node.id: node for node in graph.nodes}

        # ids[2] (first survivor) had parent ids[1] which was pruned —
        # it must be re-linked to the nearest surviving ancestor ("" = root).
        assert nodes[ids[2]].parent_checkpoint_id == ""
        # The rest of the chain stays intact.
        for older, newer in zip(ids[3:], ids[4:]):
            assert nodes[newer].parent_checkpoint_id == older
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_rollback_then_continue_branches_and_prunes_old_future(tmp_path: Path) -> None:
    """Rolling back to an old node then continuing creates a branch: the
    pre-rollback future (everything after the rollback point) is pruned —
    you cannot go back past the branch point once a newer turn exists."""
    core_db = tmp_path / "core.db"
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    db, coordinator = await _make_coordinator(core_db, work_root)
    try:
        ids = await _save_chain(coordinator, MAX_CHECKPOINTS_PER_SESSION + 2)
        # Roll back to ids[2] (still within the kept window).
        result = await coordinator.load(ids[2], scope="conversation")
        assert result.status == "committed"
        undo_id = result.undo_checkpoint_id
        derived_id = result.derived_checkpoint_id

        # A new instruction after the rollback continues from the derived node.
        new_id = (await coordinator.save(
            session_id="prune-session",
            turn_id="prune-after-rollback",
        )).id

        graph = await coordinator.graph("prune-session")
        nodes = {node.id: node for node in graph.nodes}
        graph_ids = [node.id for node in graph.nodes]

        # Old future (ids[3..7]) is gone; the branch line survives.
        assert [ids[3], ids[4], ids[5], ids[6], ids[7]] == [i for i in ids[3:] if i not in graph_ids]
        assert graph_ids == [ids[2], undo_id, derived_id, new_id]
        assert nodes[undo_id].parent_checkpoint_id == ids[2]
        assert nodes[derived_id].parent_checkpoint_id == undo_id
        assert nodes[new_id].parent_checkpoint_id == derived_id
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_branch_from_recent_node_keeps_six_mainline_nodes(tmp_path: Path) -> None:
    """Branching from a recent node keeps the 6 newest main-line nodes; the
    abandoned future (nodes after the branch point) is pruned."""
    core_db = tmp_path / "core.db"
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    db, coordinator = await _make_coordinator(core_db, work_root)
    try:
        ids = await _save_chain(coordinator, MAX_CHECKPOINTS_PER_SESSION + 4)
        # Branch off the newest-but-one node.
        branch_id = (await coordinator.save(
            session_id="prune-session",
            turn_id="prune-branch-recent",
            parent_checkpoint_id=ids[-2],
        )).id

        graph = await coordinator.graph("prune-session")
        graph_ids = [node.id for node in graph.nodes]

        # The abandoned future (ids[-1]) is pruned; the main line keeps the
        # branch point plus the 5 newest ancestors (6 nodes total).
        assert ids[-1] not in graph_ids
        assert graph_ids == [*ids[-(MAX_CHECKPOINTS_PER_SESSION):-1], branch_id]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_rollback_bookkeeping_never_consumes_the_turn_window(tmp_path: Path) -> None:
    """The 6-turn window counts conversation turns only. Each rollback adds
    two bookkeeping nodes (undo/derived) that must not push turns out of the
    window — otherwise repeated rollbacks would silently reduce the pool of
    rollback targets below 6."""
    core_db = tmp_path / "core.db"
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    db, coordinator = await _make_coordinator(core_db, work_root)
    try:
        ids = await _save_chain(coordinator, MAX_CHECKPOINTS_PER_SESSION)  # t1..t6
        # Roll back twice: t1..t4..t6 become the abandoned future; the
        # remaining line is t1 -> t2 (target) with 2× undo/derived bookkeeping.
        first = await coordinator.load(ids[2], scope="conversation")  # to t3
        assert first.status == "committed"
        second = await coordinator.load(ids[1], scope="conversation")  # to t2
        assert second.status == "committed"

        # Continue with three new turns. With node-counting retention the two
        # bookkeeping pairs would already have consumed the 6-node window and
        # t1 would be pruned; with turn-counting it must survive.
        for index in range(3):
            await coordinator.save(
                session_id="prune-session",
                turn_id=f"after-rollback-{index}",
            )

        graph = await coordinator.graph("prune-session")
        nodes = {node.id: node for node in graph.nodes}
        turns = [n for n in graph.nodes if n.actor_kind == "main"]
        assert ids[0] in nodes  # t1 still inside the window
        assert ids[1] in nodes  # last rollback target stays too
        assert len(turns) == 5  # t1, t2 + 3 new turns

        # Fill the window: 6 new turns total → exactly the 6 newest turns
        # remain; t1/t2 and the bookkeeping below them are pruned.
        for index in range(3, MAX_CHECKPOINTS_PER_SESSION):
            await coordinator.save(
                session_id="prune-session",
                turn_id=f"after-rollback-{index}",
            )
        graph = await coordinator.graph("prune-session")
        turns = [n for n in graph.nodes if n.actor_kind == "main"]
        assert len(turns) == MAX_CHECKPOINTS_PER_SESSION
        assert ids[0] not in {n.id for n in graph.nodes}
        assert ids[1] not in {n.id for n in graph.nodes}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_manual_rpc_checkpoints_do_not_consume_the_turn_window(tmp_path: Path) -> None:
    """Manual (actor_kind != main) checkpoints are bookkeeping: they never
    count toward the 6-turn window and are pruned once the window passes
    them."""
    core_db = tmp_path / "core.db"
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    db, coordinator = await _make_coordinator(core_db, work_root)
    try:
        ids = await _save_chain(coordinator, MAX_CHECKPOINTS_PER_SESSION)
        # A manual tool checkpoint between turns.
        manual = (await coordinator.save(
            session_id="prune-session",
            turn_id="manual-1",
            actor_kind="tool",
            reason="manual",
        )).id
        # Two more turns — the manual node is above the window start, so it
        # survives until the window slides past it.
        extra = await _save_chain(coordinator, 1)
        graph = await coordinator.graph("prune-session")
        assert manual in {n.id for n in graph.nodes}
        assert len([n for n in graph.nodes if n.actor_kind == "main"]) == MAX_CHECKPOINTS_PER_SESSION

        # A sixth new turn slides the window: the manual node (bookkeeping)
        # and the oldest turn are pruned together.
        await _save_chain(coordinator, MAX_CHECKPOINTS_PER_SESSION - 1)
        graph = await coordinator.graph("prune-session")
        turns = [n for n in graph.nodes if n.actor_kind == "main"]
        assert len(turns) == MAX_CHECKPOINTS_PER_SESSION
        assert manual not in {n.id for n in graph.nodes}
        assert extra[0] in {n.id for n in graph.nodes}
    finally:
        await db.close()
