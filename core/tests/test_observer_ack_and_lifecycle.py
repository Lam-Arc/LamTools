"""Observer v2 ACK、生命周期持久化、SQL 层 execution 隔离的验收用例。

user:“Observer 可靠事件投递、ACK、去重与重放；Observer 正常退出与失败重启策略”
+(这里每条断言都对应一个可观察的故障场景，不允许用宽松断言换绿灯)。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.runtime.arrange import ArrangeManager, InMemoryArrangeStore
from lamtools_core.runtime.observer import (
    DESIRED_STOPPED_SUCCESSFULLY,
    InMemoryObserverLifecycleStore,
    ObserverSupervisor,
    prepare_observer,
)

NOW = datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)


async def _wait_until(predicate, *, timeout: float = 10.0, label: str = "condition") -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"{label} was not met before timeout")
        await asyncio.sleep(0.02)


# ---------------------------------------------------------------------------
# 1. v2 ACK：宿主提交后才回 ACK，观察器收到 ACK 才推进游标
# ---------------------------------------------------------------------------

_V2_OBSERVER = """
import json
import os
import sys
import threading
import time
from pathlib import Path

state = Path(os.environ["LAMTOOLS_OBSERVER_STATE_DIR"])
state.mkdir(parents=True, exist_ok=True)
cursor = state / "cursor.txt"
feed = Path(os.environ["LAMTOOLS_OBSERVER_WORK_ROOT"]) / "feed.json"

acked = set()
if cursor.exists():
    acked = {item for item in cursor.read_text(encoding="utf-8").split() if item}
events = [str(item) for item in json.loads(feed.read_text(encoding="utf-8"))]


def read_acks():
    for line in sys.stdin:
        try:
            frame = json.loads(line)
        except Exception:
            continue
        if frame.get("type") != "ack":
            continue
        acked.add(str(frame.get("event_id") or ""))
        cursor.write_text(chr(10).join(sorted(a for a in acked if a)), encoding="utf-8")


threading.Thread(target=read_acks, daemon=True).start()

# 没有收到 ACK 就一直重发：这正是 v2 的契约，宿主按 event_id 去重。
while True:
    for event_id in events:
        if event_id in acked:
            continue
        print(json.dumps({
            "protocol": "lamtools.signal.v2",
            "event_id": event_id,
            "event_type": "content.published",
            "occurred_at": "2026-07-18T09:00:00Z",
        }, ensure_ascii=False), flush=True)
    time.sleep(0.1)
"""


def _write_v2_observer(work_root: Path) -> Path:
    script = work_root / "observer.py"
    script.write_text(_V2_OBSERVER.strip() + "\n", encoding="utf-8")
    return script


@pytest.mark.asyncio
async def test_v2_observer_advances_cursor_only_after_host_ack(tmp_path: Path) -> None:
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    _write_v2_observer(work_root)
    (work_root / "feed.json").write_text('["evt-a", "evt-b"]', encoding="utf-8")

    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root=str(work_root),
        kind="focus",
        operation="turn.start",
        payload={"message": "watch"},
        trigger={"type": "event", "event_type": "content.published"},
        observer=prepare_observer(
            {"entry": "observer.py", "protocol": "lamtools.signal.v2"}, work_root=work_root
        ),
    )

    supervisor = ObserverSupervisor(store, data_dir=tmp_path / "data", poll_interval=0.05)
    await supervisor.start()
    try:
        cursor = tmp_path / "data" / "observers" / job.id / "cursor.txt"
        await _wait_until(cursor.exists, label="ACK 之后写游标")
        acked = set(cursor.read_text(encoding="utf-8").split())
        status = supervisor.status(job.id)
    finally:
        await supervisor.stop()

    assert acked == {"evt-a", "evt-b"}
    assert status.get("acks_sent") == 2, status
    occurrences = await manager.list_occurrences(job_id=job.id)
    assert len(occurrences) == 2


@pytest.mark.asyncio
async def test_v2_observer_redelivery_after_missing_ack_is_deduplicated(tmp_path: Path) -> None:
    """ACK 丢失 → 观察器重发 → 宿主按 event_id 去重，不产生第二条 occurrence。"""
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    _write_v2_observer(work_root)
    (work_root / "feed.json").write_text('["evt-dup"]', encoding="utf-8")

    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root=str(work_root),
        kind="focus",
        operation="turn.start",
        payload={"message": "watch"},
        trigger={"type": "event", "event_type": "content.published"},
        observer=prepare_observer(
            {"entry": "observer.py", "protocol": "lamtools.signal.v2"}, work_root=work_root
        ),
    )

    supervisor = ObserverSupervisor(store, data_dir=tmp_path / "data", poll_interval=0.05)
    # 前两次 ACK 全部丢弃，模拟宿主写 ACK 失败 / 断线。
    async def _drop_ack(observer_job, event_id: str) -> None:
        supervisor._bump_ack(observer_job.id, sent=False)

    supervisor._send_ack = _drop_ack  # type: ignore[method-assign]
    await supervisor.start()
    try:
        await _wait_until(
            lambda: (supervisor.status(job.id).get("acks_dropped") or 0) >= 2,
            label="观察器重发",
        )
    finally:
        await supervisor.stop()

    occurrences = await manager.list_occurrences(job_id=job.id)
    assert len(occurrences) == 1, f"重复投递产生了 {len(occurrences)} 条 occurrence"


# ---------------------------------------------------------------------------
# 2. 生命周期持久化：正常退出是终态，跨进程重启仍生效，rearm 才能复活
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clean_exit_stays_stopped_across_supervisor_restart(tmp_path: Path) -> None:
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    runs_path = work_root / "runs.txt"
    script = work_root / "observer.py"
    script.write_text(
        "\n".join(
            [
                "import os, sys",
                "from pathlib import Path",
                "root = Path(os.environ['LAMTOOLS_OBSERVER_WORK_ROOT'])",
                "with open(root / 'runs.txt', 'a', encoding='utf-8') as handle:",
                "    handle.write('run\\n')",
                "sys.exit(0)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    store = InMemoryArrangeStore()
    manager = ArrangeManager(store)
    job = await manager.create(
        thread_id="thread-1",
        work_root=str(work_root),
        kind="focus",
        operation="turn.start",
        payload={"message": "watch"},
        trigger={"type": "event", "event_type": "content.published"},
        observer=prepare_observer(
            {"entry": "observer.py", "restart": "on-failure"}, work_root=work_root
        ),
    )
    lifecycle = InMemoryObserverLifecycleStore()

    first = ObserverSupervisor(
        store, data_dir=tmp_path / "data", poll_interval=0.05, lifecycle_store=lifecycle
    )
    await first.start()
    await _wait_until(lambda: runs_path.exists(), label="首次启动")
    await asyncio.sleep(0.6)
    await first.stop()
    saved = await lifecycle.get(job.id)
    assert saved is not None
    assert saved["desired_state"] == DESIRED_STOPPED_SUCCESSFULLY

    # 模拟 Sunday 进程重启：新的监督器 + 同一份持久生命周期。
    second = ObserverSupervisor(
        store, data_dir=tmp_path / "data", poll_interval=0.05, lifecycle_store=lifecycle
    )
    await second.start()
    await asyncio.sleep(0.8)
    await second.stop()

    launches = runs_path.read_text(encoding="utf-8").count("run")
    assert launches == 1, f"正常退出后又被拉起，累计启动 {launches} 次"

    third = ObserverSupervisor(
        store, data_dir=tmp_path / "data", poll_interval=0.05, lifecycle_store=lifecycle
    )
    await third.start()
    await third.rearm(job.id)
    await _wait_until(
        lambda: runs_path.read_text(encoding="utf-8").count("run") >= 2,
        label="rearm 之后重新拉起",
    )
    await third.stop()


# ---------------------------------------------------------------------------
# 3. SQL 层：execution 隔离 + 原子中断
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sql_claim_assigns_execution_id_and_fences_old_execution(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        manager = ArrangeManager(db.arrange_store)
        job = await manager.create(
            thread_id="thread-1",
            work_root="test-proj",
            kind="routine",
            operation="turn.start",
            payload={"message": "run"},
            trigger={"type": "once", "run_at": NOW.isoformat()},
            now=NOW,
        )
        first = (
            await db.arrange_store.claim_due(
                now=NOW, worker_id="worker-a", lease_seconds=5, limit=1
            )
        )[0]
        assert first.execution_id.startswith("exec_")

        second = (
            await db.arrange_store.claim_due(
                now=NOW.replace(microsecond=0), worker_id="worker-b", lease_seconds=5, limit=1
            )
        )
        assert second == []

        reclaimed = (
            await db.arrange_store.claim_due(
                now=NOW.replace(second=6),  # 租约过期
                worker_id="worker-b",
                lease_seconds=5,
                limit=1,
            )
        )
        assert reclaimed == []
        second = (
            await db.arrange_store.claim_due(
                now=NOW.replace(second=6), worker_id="worker-b", lease_seconds=5, limit=1
            )
        )[0]
        assert second.execution_id != first.execution_id

        with pytest.raises(RuntimeError, match="lease lost"):
            await db.arrange_store.complete_run(
                job_id=job.id,
                worker_id="worker-a",
                now=NOW.replace(second=6),
                fencing_token=first.fencing_token,
                execution_id=first.execution_id,
            )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_sql_atomic_interrupt_marks_paused_and_invalidates_execution(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        manager = ArrangeManager(db.arrange_store)
        job = await manager.create(
            thread_id="thread-1",
            work_root="test-proj",
            kind="routine",
            operation="turn.start",
            payload={"message": "run"},
            trigger={"type": "once", "run_at": NOW.isoformat()},
            now=NOW,
        )
        claimed = (
            await db.arrange_store.claim_due(
                now=NOW, worker_id="worker-a", lease_seconds=5, limit=1
            )
        )[0]
        paused = await manager.request_interrupt(job.id, "paused", now=NOW)
        assert paused.status == "paused"
        assert paused.execution_id == ""

        with pytest.raises(RuntimeError, match="lease lost"):
            await db.arrange_store.complete_run(
                job_id=job.id,
                worker_id="worker-a",
                now=NOW,
                fencing_token=claimed.fencing_token,
                execution_id=claimed.execution_id,
            )

        occurrences = await manager.list_occurrences(job_id=job.id)
        assert [item.status for item in occurrences] == ["pending"]

        resumed = await manager.update_status(job.id, "scheduled", now=NOW)
        assert resumed.status == "scheduled"
    finally:
        await db.close()
