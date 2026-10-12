"""Contract tests for checkpoint baselines and superseded-checkpoint pruning."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from lamtools_core.app.core_db import (
    CoreCheckpoint,
    CoreCheckpointV2,
    CoreCheckpointV2SessionHistory,
    CoreRuntimeSession,
    CoreThreadSnapshot,
    open_core_app_db,
)
from lamtools_core.checkpoint_maintenance import (
    capture_checkpoint_baseline,
    compare_checkpoint_baseline,
    prune_superseded_checkpoints,
)
from lamtools_core.maintenance import MaintenanceScopeError
from lamtools_core.runtime_owner import owner_token


async def _seed_checkpoints(
    db_path: Path,
    session_id: str,
    *,
    count: int = 3,
    history_size: int = 200,
) -> list[str]:
    """Seed ``count`` chained checkpoints for one session, oldest first."""
    db = await open_core_app_db(db_path)
    try:
        async with db.session_factory() as session:
            session.add(CoreThreadSnapshot(thread_id=session_id, snapshot_json={}))
            base = datetime(2026, 1, 1, 0, 0, 0)
            previous = ""
            ids: list[str] = []
            for index in range(count):
                checkpoint_id = f"{session_id}-ck-{index}"
                ids.append(checkpoint_id)
                session.add(
                    CoreCheckpoint(
                        id=checkpoint_id,
                        root_session_id=session_id,
                        session_id=session_id,
                        parent_checkpoint_id=previous,
                        actor_kind="main",
                        reason="before_user_prompt",
                        turn_id=f"turn-{index}",
                        work_root=str(db_path.parent),
                        manifest_hash="",
                        conversation_json={},
                        status="ready",
                        created_at=base + timedelta(minutes=index),
                    )
                )
                session.add(
                    CoreCheckpointV2(
                        id=checkpoint_id,
                        root_session_id=session_id,
                        session_id=session_id,
                        turn_id=f"turn-{index}",
                        actor_kind="main",
                        reason="before_user_prompt",
                        status="ready",
                        event_seq=10 * (index + 1),
                        history_seq=5 * (index + 1),
                        runtime_state_json={},
                    )
                )
                session.add(
                    CoreCheckpointV2SessionHistory(
                        checkpoint_id=checkpoint_id,
                        history_json=[{"role": "user", "content": "x" * history_size}],
                    )
                )
                previous = checkpoint_id
            await session.commit()
    finally:
        await db.close()
    return ids


async def test_baseline_capture_and_compare(tmp_path: Path) -> None:
    db_path = tmp_path / "core.db"
    ids = await _seed_checkpoints(db_path, "s-1", count=3, history_size=200)

    baseline = await capture_checkpoint_baseline(db_path)
    assert baseline.checkpoint_count == 3
    assert baseline.session_count == 1
    assert baseline.history_bytes > 0
    assert baseline.sessions[0]["session_id"] == "s-1"
    assert baseline.sessions[0]["checkpoint_count"] == 3
    assert baseline.content_digest

    same = await capture_checkpoint_baseline(db_path)
    diff = compare_checkpoint_baseline(baseline.to_dict(), same)
    assert diff["identical"] is True
    assert diff["checkpoints_added"] == []
    assert diff["checkpoints_removed"] == []

    report = await prune_superseded_checkpoints(db_path, apply=True, allow_non_dev=True)
    assert report.ok
    assert report.checkpoints_deleted == len(ids) - 1

    after = await capture_checkpoint_baseline(db_path)
    diff_after = compare_checkpoint_baseline(baseline.to_dict(), after)
    assert diff_after["identical"] is False
    assert sorted(diff_after["checkpoints_removed"]) == sorted(ids[:-1])
    assert diff_after["history_bytes_saved"] > 0
    assert after.checkpoint_count == 1


async def test_prune_keeps_newest_per_session_and_verifies(tmp_path: Path) -> None:
    db_path = tmp_path / "core.db"
    ids = await _seed_checkpoints(db_path, "s-1", count=3)

    preview = await prune_superseded_checkpoints(db_path, apply=False, allow_non_dev=True)
    assert preview.applied is False
    assert not preview.already_clean
    assert preview.sessions_total == 1
    assert preview.checkpoints_planned == 2
    assert preview.checkpoints_deleted == 0
    assert preview.bytes_before > 0

    # Dry run writes nothing.
    still = await capture_checkpoint_baseline(db_path)
    assert still.checkpoint_count == 3

    report = await prune_superseded_checkpoints(db_path, apply=True, allow_non_dev=True)
    assert report.backup is not None
    assert report.checkpoints_deleted == 2
    assert report.ok
    assert report.sessions[0].readable and report.sessions[0].verified
    assert "checkpoints_remaining=1" in report.sessions[0].detail

    db = await open_core_app_db(db_path)
    try:
        remaining = await db.runtime_state_store.get_history("s-1")
        assert remaining == []
    finally:
        await db.close()

    after = await capture_checkpoint_baseline(db_path)
    assert [item["checkpoint_id"] for item in after.checkpoints] == [ids[-1]]


async def test_prune_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "core.db"
    await _seed_checkpoints(db_path, "s-1", count=3)

    first = await prune_superseded_checkpoints(db_path, apply=True, allow_non_dev=True)
    assert first.checkpoints_deleted == 2

    second = await prune_superseded_checkpoints(db_path, apply=True, allow_non_dev=True)
    assert second.already_clean is True
    assert second.checkpoints_deleted == 0
    assert second.backup is None


async def test_prune_relinks_orphan_child(tmp_path: Path) -> None:
    db_path = tmp_path / "core.db"
    ids = await _seed_checkpoints(db_path, "s-1", count=3)
    report = await prune_superseded_checkpoints(db_path, apply=True, allow_non_dev=True)
    assert report.checkpoints_deleted == 2

    db = await open_core_app_db(db_path)
    try:
        from sqlalchemy import select

        async with db.session_factory() as session:
            kept = (await session.execute(select(CoreCheckpoint))).scalars().all()
        assert [str(item.id) for item in kept] == [ids[-1]]
        assert str(kept[0].parent_checkpoint_id) not in set(ids[:-1])
    finally:
        await db.close()


async def test_prune_skips_session_with_in_flight_turn(tmp_path: Path) -> None:
    db_path = tmp_path / "core.db"
    await _seed_checkpoints(db_path, "s-1", count=3)
    db = await open_core_app_db(db_path)
    try:
        async with db.session_factory() as session:
            session.add(
                CoreRuntimeSession(
                    thread_id="s-1",
                    runtime_state_json={
                        "session_id": "s-1",
                        "status": "running",
                        "metadata": {"runtime_owner": owner_token()},
                    },
                )
            )
            await session.commit()
    finally:
        await db.close()

    report = await prune_superseded_checkpoints(db_path, apply=True, allow_non_dev=True)
    assert report.sessions_skipped_in_flight == 1
    assert report.checkpoints_deleted == 0
    assert report.sessions[0].skipped_in_flight is True
    assert report.ok

    still = await capture_checkpoint_baseline(db_path)
    assert still.checkpoint_count == 3


async def test_prune_refuses_non_dev_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "core.db"
    await _seed_checkpoints(db_path, "s-1", count=2)
    with pytest.raises(MaintenanceScopeError):
        await prune_superseded_checkpoints(db_path, apply=True)
