"""量化验收：并发上限与调度延迟（真实测量，不是估算）。

user:“1000 个待执行任务，配置并发为 3，实际峰值并发不得超过 3”
“空闲执行槽下，本地入库任务调度延迟 p95 目标不超过 2 秒”
+(这两条必须在真实 SQLite + 真实 Runner 上跑出来，数字写进报告)。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import statistics
import time

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.runtime.arrange import ArrangeManager, ArrangeRunner, _TERMINAL_STATUSES


async def _seed(manager: ArrangeManager, count: int, *, now: datetime) -> None:
    for index in range(count):
        await manager.create(
            thread_id="thread-1",
            work_root="test-proj",
            kind="routine",
            operation="turn.start",
            payload={"message": f"job-{index}"},
            trigger={"type": "once", "run_at": now.isoformat()},
            now=now,
        )


@pytest.mark.asyncio
async def test_1000_jobs_with_capacity_three_never_exceeds_peak(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        manager = ArrangeManager(db.arrange_store)
        now = datetime.now(timezone.utc)
        await _seed(manager, 1000, now=now)

        lock = asyncio.Lock()
        stats = {"current": 0, "peak": 0, "runs": 0}

        async def executor(_job):
            async with lock:
                stats["current"] += 1
                stats["peak"] = max(stats["peak"], stats["current"])
                stats["runs"] += 1
            await asyncio.sleep(0.001)
            async with lock:
                stats["current"] -= 1
            return {"status": "ok"}

        runner = ArrangeRunner(
            db.arrange_store,
            executor,
            max_active_jobs=3,
            claim_limit=25,
            poll_interval=0.01,
            lease_seconds=30,
        )
        await runner.start()
        try:
            deadline = asyncio.get_running_loop().time() + 120
            while stats["runs"] < 1000:
                if asyncio.get_running_loop().time() > deadline:
                    break
                await asyncio.sleep(0.05)
            # user:“1000 个待执行任务，配置并发为 3，实际峰值并发不得超过 3”+(runner.stop()
            # 会取消仍在跑的任务，所以必须等最后一个任务把终态写进库再停；否则断言测到的
            # 是用例自己的收尾竞态，而不是调度器少算了任务)
            while asyncio.get_running_loop().time() < deadline:
                jobs = await manager.list()
                if all(job.status in _TERMINAL_STATUSES for job in jobs):
                    break
                await asyncio.sleep(0.05)
        finally:
            await runner.stop()

        jobs = await manager.list()
        completed = sum(1 for job in jobs if job.status == "completed")
    finally:
        await db.close()

    assert stats["peak"] <= 3, f"峰值并发 {stats['peak']} 超过 3"
    assert stats["peak"] >= 2, "用例没有真正制造并发，断言无效"
    assert stats["runs"] == 1000, f"只执行了 {stats['runs']} 个任务"
    assert completed == 1000, f"只有 {completed} 个任务最终 completed"


@pytest.mark.asyncio
async def test_idle_slot_dispatch_latency_p95_under_two_seconds(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        manager = ArrangeManager(db.arrange_store)
        started: list[float] = []
        dispatched: list[float] = []
        inserted_at: dict[str, float] = {}
        done = asyncio.Event()

        async def executor(job):
            dispatched.append(time.perf_counter())
            await asyncio.sleep(0)
            return {"status": "ok"}

        runner = ArrangeRunner(
            db.arrange_store, executor, max_active_jobs=3, claim_limit=3, poll_interval=0.05
        )
        await runner.start()
        samples: list[float] = []
        try:
            for index in range(30):
                now = datetime.now(timezone.utc)
                job = await manager.create(
                    thread_id="thread-1",
                    work_root="test-proj",
                    kind="routine",
                    operation="turn.start",
                    payload={"message": f"latency-{index}"},
                    trigger={"type": "once", "run_at": now.isoformat()},
                    now=now,
                )
                inserted_at[job.id] = time.perf_counter()
                runner.wake()
                before = len(dispatched)
                deadline = time.perf_counter() + 10
                while len(dispatched) == before and time.perf_counter() < deadline:
                    await asyncio.sleep(0.005)
                samples.append(dispatched[-1] - inserted_at[job.id])
        finally:
            await runner.stop()
    finally:
        await db.close()

    p95 = statistics.quantiles(samples, n=20)[-1] if len(samples) >= 2 else samples[0]
    median = statistics.median(samples)
    print(f"dispatch latency p50={median*1000:.1f}ms p95={p95*1000:.1f}ms n={len(samples)}")
    assert p95 <= 2.0, f"调度延迟 p95 {p95:.3f}s 超过 2s"
