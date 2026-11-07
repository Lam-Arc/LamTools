"""启动时回收失效所有权。

user:“服务器重启后，应能够识别已死亡的执行进程，安全释放旧任务占用，使用户可以继续或
重试”“通过原子状态转移回收失效所有权”“绝不放宽旧 revision 写入限制”
+(这些用例直接验证行为：死进程占着的会话被转成终止态，活着的别的进程占着的一律不动，
终止态的重复回收是幂等的)。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lamtools_core.app.core_db import CoreRuntimeSession, open_core_app_db
from lamtools_core.runtime import RuntimeState
from lamtools_core.runtime_owner import OWNER_METADATA_KEY


async def _set_owner(db, session_id: str, token: dict) -> None:
    """Rewrite the persisted owner token without touching the status."""
    async with db.runtime_state_store.session_factory() as connection:
        row = await connection.get(CoreRuntimeSession, session_id)
        payload = dict(row.runtime_state_json or {})
        metadata = dict(payload.get("metadata") or {})
        metadata[OWNER_METADATA_KEY] = token
        payload["metadata"] = metadata
        row.runtime_state_json = payload
        await connection.commit()


async def _seed_running(db, session_id: str) -> None:
    state = RuntimeState(session_id=session_id)
    state.status = "running"
    await db.runtime_state_store.save_checkpoint(state, [])


@pytest.mark.asyncio
async def test_release_frees_a_session_whose_owner_died(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        await _seed_running(db, "thread-crashed")
        await _set_owner(
            db,
            "thread-crashed",
            {"pid": 999_999_999, "host": "testhost", "started_at": 0.0, "heartbeat_at": 0.0},
        )

        released = await db.runtime_state_store.release_orphaned_owners()

        assert released == 1
        after = await db.runtime_state_store.get("thread-crashed")
        assert after is not None
        assert after.status == "cancelled"
        assert after.metadata.get("cancellation_reason") == "owner_gone"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_release_leaves_a_session_owned_by_another_live_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """另一个进程还活着并且握着这个会话时，回收必须放手。"""
    from lamtools_core import runtime_owner

    monkeypatch.setattr(runtime_owner, "process_is_alive", lambda pid: True)
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        await _seed_running(db, "thread-elsewhere")
        await _set_owner(
            db,
            "thread-elsewhere",
            {
                "pid": os.getpid() + 1,
                "host": runtime_owner.socket.gethostname(),
                "started_at": 0.0,
                "heartbeat_at": 0.0,
            },
        )

        released = await db.runtime_state_store.release_orphaned_owners()

        assert released == 0
        after = await db.runtime_state_store.get("thread-elsewhere")
        assert after is not None
        assert after.status == "running"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_release_is_idempotent_and_skips_terminal_sessions(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        await _seed_running(db, "thread-crashed")
        await _set_owner(
            db,
            "thread-crashed",
            {"pid": 999_999_999, "host": "testhost", "started_at": 0.0, "heartbeat_at": 0.0},
        )
        done = RuntimeState(session_id="thread-done")
        done.status = "completed"
        await db.runtime_state_store.save_checkpoint(done, [])

        assert await db.runtime_state_store.release_orphaned_owners() == 1
        # 第二次已经没有活着的行了，不重复回收，也不碰终止态。
        assert await db.runtime_state_store.release_orphaned_owners() == 0
        finished = await db.runtime_state_store.get("thread-done")
        assert finished is not None and finished.status == "completed"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_release_does_not_loosen_the_stale_writer_guard(tmp_path: Path) -> None:
    """回收之后，同一进程里两个运行时交叉写仍然被拒绝。"""
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        await _seed_running(db, "thread-guard")
        await _set_owner(
            db,
            "thread-guard",
            {"pid": 999_999_999, "host": "testhost", "started_at": 0.0, "heartbeat_at": 0.0},
        )
        await db.runtime_state_store.release_orphaned_owners()

        first = await db.runtime_state_store.get("thread-guard")
        second = await db.runtime_state_store.get("thread-guard")
        assert first is not None and second is not None
        first.status = "running"
        await db.runtime_state_store.save(first)
        second.status = "waiting"
        from lamtools_core.runtime import RuntimeStateConflictError

        with pytest.raises(RuntimeStateConflictError):
            await db.runtime_state_store.save(second)
    finally:
        await db.close()

@pytest.mark.asyncio
async def test_release_keeps_a_session_parked_on_a_pending_approval(tmp_path: Path) -> None:
    """停在用户决定上的会话不是失效占用：审批要在重启后仍然可回答。"""
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        state = RuntimeState(session_id="thread-waiting")
        state.status = "waiting"
        state.metadata["pending_approval"] = {
            "request_id": "req-1",
            "tool_call": {"id": "call-1", "name": "write_file"},
        }
        await db.runtime_state_store.save_checkpoint(state, [])
        await _set_owner(
            db,
            "thread-waiting",
            {"pid": 999_999_999, "host": "testhost", "started_at": 0.0, "heartbeat_at": 0.0},
        )

        released = await db.runtime_state_store.release_orphaned_owners()

        assert released == 0
        after = await db.runtime_state_store.get("thread-waiting")
        assert after is not None
        assert after.status == "waiting"
        assert after.metadata.get("pending_approval"), "审批被回收清掉了"
    finally:
        await db.close()
