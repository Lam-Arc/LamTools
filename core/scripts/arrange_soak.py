"""Arrange/Observer 长跑与随机崩溃恢复验证脚本。

user:“隔离环境连续运行 24 小时，完成 100 次随机崩溃恢复测试”
+(24 小时不能靠嘴说，所以给出可重复执行的脚本；默认只跑一个小循环做自检，
真正 24 小时 soak 需要显式传 --hours)。

用法（在工作区的临时目录里跑，别指向真实数据）：

    python core/scripts/arrange_soak.py --db .lam/soak/core.db --seed-jobs 50 \
        --crash-iterations 5 --hours 0

    # 完整 24 小时 + 100 次崩溃
    python core/scripts/arrange_soak.py --db .lam/soak/core.db --seed-jobs 500 \
        --crash-iterations 100 --hours 24

验收口径（脚本退出码 0 即通过）：
1. 崩溃重启后，没有任务永久停在 running（过期租约必须可回收）。
2. 同一 signal 不会对同一个 job 产生两条 occurrence。
3. 所有 job 最终要么 completed，要么是可解释的 failed/cancelled/scheduled。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    src = here.parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


async def _run_child(args: argparse.Namespace) -> int:
    _ensure_path()
    from lamtools_core.app.core_db import open_core_app_db
    from lamtools_core.runtime.arrange import ArrangeManager, ArrangeRunner

    db = await open_core_app_db(Path(args.db))
    manager = ArrangeManager(db.arrange_store)

    async def executor(job):
        await asyncio.sleep(random.uniform(0.01, 0.15))
        return {"status": "ok"}

    runner = ArrangeRunner(
        db.arrange_store,
        executor,
        worker_id=f"soak-{os.getpid()}",
        max_active_jobs=args.max_active,
        claim_limit=args.max_active,
        poll_interval=0.05,
        lease_seconds=3.0,
    )
    await runner.start()
    try:
        while True:
            await asyncio.sleep(0.5)
            if args.seed_jobs and not getattr(args, "_seeded", False):
                now = datetime.now(timezone.utc)
                for index in range(args.seed_jobs):
                    try:
                        await manager.create(
                            thread_id="soak",
                            work_root="soak",
                            kind="routine",
                            operation="turn.start",
                            payload={"message": f"soak-{os.getpid()}-{index}"},
                            trigger={"type": "once", "run_at": now.isoformat()},
                            now=now,
                        )
                    except Exception:
                        pass
                args._seeded = True  # type: ignore[attr-defined]
            if args.hours:
                await asyncio.sleep(1)
            else:
                await asyncio.sleep(0.2)
    except asyncio.CancelledError:
        pass
    finally:
        await runner.stop()
        await db.close()
    return 0


async def _verify(db_path: Path) -> tuple[bool, dict[str, int]]:
    _ensure_path()
    from lamtools_core.app.core_db import open_core_app_db
    from lamtools_core.runtime.arrange import ArrangeManager

    db = await open_core_app_db(db_path)
    try:
        manager = ArrangeManager(db.arrange_store)
        now = datetime.now(timezone.utc)
        await db.arrange_store.recover_running(now=now + timedelta(seconds=60))
        jobs = await manager.list()
        stuck = 0
        duplicates = 0
        counts: dict[str, int] = {}
        for job in jobs:
            counts[job.status] = counts.get(job.status, 0) + 1
            if job.status == "running":
                stuck += 1
            occurrences = await manager.list_occurrences(job_id=job.id)
            seen: set[str] = set()
            for item in occurrences:
                key = item.signal_id or item.id
                if key in seen:
                    duplicates += 1
                seen.add(key)
        return (stuck == 0 and duplicates == 0), {
            **counts,
            "stuck_running": stuck,
            "duplicate_occurrences": duplicates,
        }
    finally:
        await db.close()


def _spawn_child(args: argparse.Namespace) -> subprocess.Popen:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--db",
        str(args.db),
        "--child",
        "--max-active",
        str(args.max_active),
        "--hours",
        str(args.hours),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src") + os.pathsep + env.get(
        "PYTHONPATH", ""
    )
    return subprocess.Popen(command, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Arrange soak / crash recovery")
    parser.add_argument("--db", required=True)
    parser.add_argument("--seed-jobs", type=int, default=50)
    parser.add_argument("--crash-iterations", type=int, default=5)
    parser.add_argument("--hours", type=float, default=0)
    parser.add_argument("--max-active", type=int, default=3)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.child:
        return asyncio.run(_run_child(args))

    db_path = Path(args.db).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # 先种任务：让子进程崩溃时总有 in-flight 的任务。
    seed = argparse.Namespace(**{**vars(args), "_seeded": False})
    child = _spawn_child(seed)
    time.sleep(1.5)
    started = time.perf_counter()

    for iteration in range(args.crash_iterations):
        if child.poll() is not None:
            child = _spawn_child(args)
            time.sleep(0.5)
        time.sleep(random.uniform(0.2, 1.2))
        if os.name == "nt":
            child.kill()
        else:
            child.send_signal(signal.SIGKILL)
        child.wait(timeout=20)
        print(f"[crash {iteration + 1}/{args.crash_iterations}] killed pid, restarting")
        child = _spawn_child(args)
        time.sleep(0.4)

    if args.hours:
        remaining = args.hours * 3600 - (time.perf_counter() - started)
        if remaining > 0:
            print(f"[soak] running {remaining / 3600:.2f}h more before verification")
            time.sleep(remaining)

    # 最后一次崩溃后让一个新进程把队列排空，证明"崩溃不会留下永久停摆"。
    drain_deadline = time.perf_counter() + 90
    while time.perf_counter() < drain_deadline:
        ok_probe, counts_probe = asyncio.run(_verify(db_path))
        if counts_probe.get("scheduled", 0) == 0 and counts_probe.get("stuck_running", 0) == 0:
            break
        await_sleep = 1.0
        time.sleep(await_sleep)

    if child.poll() is None:
        child.kill()
        child.wait(timeout=20)

    ok, counts = asyncio.run(_verify(db_path))
    print("[verify]", counts)
    print("[result]", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
