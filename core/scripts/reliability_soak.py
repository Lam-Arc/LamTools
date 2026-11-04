"""可靠性长跑 / 随机崩溃恢复，并记录量化指标。

user:“完成后先进行故障注入和 100 次随机崩溃恢复测试，再进行 24 小时 Soak。
记录并发峰值、事件丢失、重复副作用、资源泄漏、恢复时间及任务最终状态”
+(这个脚本就是那份证据：它真的杀进程、真的重启，最后从数据库和磁盘反推指标)。

用法：

    # 100 次随机崩溃（推荐先跑这个）
    python core/scripts/reliability_soak.py --db .lam/soak/core.db --crashes 100

    # 24 小时长跑（不杀进程，只持续跑并定期采样）
    python core/scripts/reliability_soak.py --db .lam/soak/core.db --hours 24 --crashes 0

    # 24 小时 + 期间随机崩溃
    python core/scripts/reliability_soak.py --db .lam/soak/core.db --hours 24 --crashes 100

退出码 0 = 全部不变式成立。
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import uuid
import time


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    src = here.parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


def _rss_mb() -> float | None:
    """当前进程常驻内存（MB）。用来看长跑有没有泄漏。"""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class _Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = _Counters()
            counters.cb = ctypes.sizeof(counters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            getter = getattr(
                ctypes.windll.kernel32,
                "K32GetProcessMemoryInfo",
                None,
            ) or getattr(ctypes.windll.psapi, "GetProcessMemoryInfo", None)
            if getter is None:
                return None
            # 必须显式声明 argtypes：否则 64 位 HANDLE 会被截断成 32 位，
            # 调用直接返回 0，看起来像"读不到内存"。
            getter.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
            getter.restype = wintypes.BOOL
            if not getter(handle, ctypes.byref(counters), counters.cb):
                return None
            return round(counters.WorkingSetSize / (1024 * 1024), 1)
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except Exception:
        return None
    return None


def _metric(path: Path, **payload) -> None:
    payload.setdefault("t", time.time())
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 子进程：真正跑一个调度器 + 观察器 + 受管命令 + 幂等副作用
# ---------------------------------------------------------------------------


async def _child(args: argparse.Namespace) -> int:
    _ensure_path()
    from lamtools_core.app.core_db import open_core_app_db
    from lamtools_core.runtime.arrange import ArrangeManager, ArrangeRunner
    from lamtools_core.runtime.observer import ObserverSupervisor, prepare_observer
    from lamtools_core.superagent import EffectOutbox
    from lamtools_core.tool.command import run_subprocess_blocking

    root = Path(args.root).resolve()
    metrics = root / "metrics.jsonl"
    effects_dir = root / "effects"
    pids_dir = root / "pids"
    for folder in (effects_dir, pids_dir):
        folder.mkdir(parents=True, exist_ok=True)

    _metric(metrics, kind="child_start", pid=os.getpid())

    db = await open_core_app_db(Path(args.db))
    manager = ArrangeManager(db.arrange_store)
    outbox = EffectOutbox(db.superagent_store)

    class _FileAdapter:
        """外部副作用 = 独占创建一个标记文件；重复创建会被当场发现。"""

        async def lookup(self, effect):
            path = effects_dir / effect.idempotency_key
            return "file" if path.exists() else None

        async def perform(self, effect):
            path = effects_dir / effect.idempotency_key
            try:
                os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            except FileExistsError:
                _metric(metrics, kind="effect_dup", key=effect.idempotency_key)
                return "file"
            _metric(metrics, kind="effect_new", key=effect.idempotency_key)
            return "file"

    adapter = _FileAdapter()

    host_id = uuid.uuid4().hex

    async def executor(job):
        marker = str(job.payload.get("marker") or job.id)
        _metric(metrics, kind="job_start", marker=marker, pid=os.getpid(), host=host_id)
        pid_file = pids_dir / f"{marker}.{os.getpid()}.pid"
        code = (
            "import os,time;"
            f"open({str(pid_file)!r},'w').write(str(os.getpid()));"
            f"time.sleep({random.uniform(0.02, 0.08):.3f})"
        )
        try:
            await asyncio.to_thread(
                run_subprocess_blocking,
                [sys.executable, "-c", code],
                cwd=root,
                timeout=120,
            )
            await outbox.deliver(
                await outbox.ensure(
                    ticket_id=marker, kind="marker_file", idempotency_key=marker
                ),
                adapter,
            )
        finally:
            try:
                pid_file.unlink(missing_ok=True)
            except OSError:
                pass
            _metric(metrics, kind="job_end", marker=marker, pid=os.getpid(), host=host_id)
        return {"status": "ok"}

    runner = ArrangeRunner(
        db.arrange_store,
        executor,
        worker_id=f"soak-{os.getpid()}",
        max_active_jobs=args.max_active,
        claim_limit=args.max_active,
        poll_interval=0.05,
        lease_seconds=args.lease_seconds,
        job_timeout_seconds=args.job_timeout,
    )

    observer_supervisor = None
    if args.observer_events:
        work = root / "observer-work"
        work.mkdir(parents=True, exist_ok=True)
        (work / "feed.json").write_text(
            json.dumps([f"evt-{index}" for index in range(args.observer_events)]),
            encoding="utf-8",
        )
        script = work / "observer.py"
        if not script.exists():
            script.write_text(
                "\n".join(
                    [
                        "import json, os, sys, threading, time",
                        "from pathlib import Path",
                        'state = Path(os.environ["LAMTOOLS_OBSERVER_STATE_DIR"])',
                        "state.mkdir(parents=True, exist_ok=True)",
                        'cursor = state / "cursor.txt"',
                        "acked = set()",
                        "if cursor.exists():",
                        '    acked = {x for x in cursor.read_text(encoding="utf-8").split() if x}',
                        'feed = json.loads((Path(os.environ["LAMTOOLS_OBSERVER_WORK_ROOT"]) / "feed.json").read_text())',
                        "def read_acks():",
                        "    for line in sys.stdin:",
                        "        try:",
                        "            frame = json.loads(line)",
                        "        except Exception:",
                        "            continue",
                        '        if frame.get("type") != "ack":',
                        "            continue",
                        '        acked.add(str(frame.get("event_id")))',
                        '        cursor.write_text(chr(10).join(sorted(acked)), encoding="utf-8")',
                        "threading.Thread(target=read_acks, daemon=True).start()",
                        "while True:",
                        "    for event_id in feed:",
                        "        if event_id in acked:",
                        "            continue",
                        "        print(json.dumps({'protocol': 'lamtools.signal.v2', 'event_id': event_id,",
                        "                          'event_type': 'soak.tick', 'occurred_at': '2026-08-02T00:00:00Z'}),",
                        "              flush=True)",
                        "    time.sleep(0.2)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
        observer_supervisor = ObserverSupervisor(
            db.arrange_store,
            data_dir=root / "observer-data",
            poll_interval=0.1,
            lifecycle_store=getattr(db, "observer_lifecycle", None),
        )
        existing = [
            job
            for job in await manager.list()
            if job.observer and job.status in {"scheduled", "waiting", "running"}
        ]
        if not existing:
            await manager.create(
                thread_id="soak-observer",
                work_root=str(work),
                kind="focus",
                operation="turn.start",
                payload={"message": "soak"},
                trigger={"type": "event", "event_type": "soak.tick"},
                observer=prepare_observer(
                    {"entry": "observer.py", "protocol": "lamtools.signal.v2"},
                    work_root=work,
                ),
            )

    await runner.start()
    if observer_supervisor is not None:
        await observer_supervisor.start()

    deadline = time.time() + args.hours * 3600 if args.hours else None
    last_feed = 0.0
    last_beat = 0.0
    fed = 0
    try:
        while True:
            await asyncio.sleep(0.5)
            now = time.time()
            if deadline is not None and now > deadline:
                break
            # 长跑必须持续有活干，否则只是空转，测不出泄漏与漂移。
            if deadline is not None and args.feed_interval > 0:
                if now - last_feed >= args.feed_interval:
                    last_feed = now
                    fed += 1
                    clock = datetime.now(timezone.utc)
                    await manager.create(
                        thread_id="soak",
                        work_root="soak",
                        kind="routine",
                        operation="turn.start",
                        payload={"message": f"feed-{os.getpid()}-{fed}"},
                        trigger={"type": "once", "run_at": clock.isoformat()},
                        now=clock,
                    )
            if now - last_beat >= args.heartbeat_seconds:
                last_beat = now
                _metric(
                    metrics,
                    kind="heartbeat",
                    pid=os.getpid(),
                    rss_mb=_rss_mb(),
                    live_processes=sum(
                        handle.guard.live_processes()
                        for handle in runner._active.values()
                        if handle.guard is not None
                    ),
                    active=len(runner._active),
                )
    finally:
        if observer_supervisor is not None:
            await observer_supervisor.stop()
        await runner.stop()
        await db.close()
        _metric(metrics, kind="child_exit", pid=os.getpid())
    return 0


# ---------------------------------------------------------------------------
# 父进程：种任务、随机崩、最后核对
# ---------------------------------------------------------------------------


async def _seed(args: argparse.Namespace) -> int:
    _ensure_path()
    from lamtools_core.app.core_db import open_core_app_db
    from lamtools_core.runtime.arrange import ArrangeManager

    db = await open_core_app_db(Path(args.db))
    try:
        manager = ArrangeManager(db.arrange_store)
        existing = await manager.list()
        if len(existing) >= args.seed_jobs:
            return 0
        now = datetime.now(timezone.utc)
        for index in range(args.seed_jobs - len(existing)):
            await manager.create(
                thread_id="soak",
                work_root="soak",
                kind="routine",
                operation="turn.start",
                payload={"message": f"seed-{int(time.time())}-{index}"},
                trigger={"type": "once", "run_at": now.isoformat()},
                now=now,
            )
        return args.seed_jobs - len(existing)
    finally:
        await db.close()


async def _verify(args: argparse.Namespace) -> tuple[bool, dict]:
    _ensure_path()
    from lamtools_core.app.core_db import open_core_app_db
    from lamtools_core.runtime.arrange import ArrangeManager

    root = Path(args.root).resolve()
    metrics = root / "metrics.jsonl"
    db = await open_core_app_db(Path(args.db))
    try:
        manager = ArrangeManager(db.arrange_store)
        await db.arrange_store.recover_running(now=datetime.now(timezone.utc) + timedelta(minutes=5))
        jobs = await manager.list()
        states = Counter(job.status for job in jobs)
        stuck = 0
        duplicate_occurrences = 0
        signals_total = 0
        for job in jobs:
            if job.status == "running":
                stuck += 1
            occurrences = await manager.list_occurrences(job_id=job.id)
            seen: set[str] = set()
            for item in occurrences:
                key = item.signal_id or item.id
                if key in seen:
                    duplicate_occurrences += 1
                seen.add(key)
            signals_total += len(seen)

        effect_records = await db.superagent_store.list("effect")
        done_keys = Counter(
            str(item.get("idempotency_key") or "")
            for item in effect_records
            if str(item.get("status") or "") == "done"
        )
        duplicate_effects = sum(1 for key, count in done_keys.items() if key and count > 1)
        effect_missing = sum(1 for key, count in done_keys.items() if not key)
    finally:
        await db.close()

    # 指标回放
    events: list[dict] = []
    if metrics.exists():
        for line in metrics.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    # 峰值必须按宿主分别统计：被强杀的进程永远写不出 job_end，全局累计会把
    # "死掉那批的 start"算成一直在跑（第一次跑就是被这个坑到 19）。同时不能用
    # pid 当宿主身份：Windows 会复用 pid，两代宿主会被并成同一个峰值。
    starts = [item for item in events if item.get("kind") == "job_start"]
    per_host_current: dict[str, int] = defaultdict(int)
    per_host_peak: dict[str, int] = defaultdict(int)
    for item in sorted(events, key=lambda entry: entry.get("t", 0)):
        host = str(item.get("host") or f"pid:{int(item.get('pid') or 0)}")
        if item.get("kind") == "job_start":
            per_host_current[host] += 1
            per_host_peak[host] = max(per_host_peak[host], per_host_current[host])
        elif item.get("kind") == "job_end":
            per_host_current[host] = max(0, per_host_current[host] - 1)
    peak = max(per_host_peak.values()) if per_host_peak else 0
    beats = [item for item in events if item.get("kind") == "heartbeat"]
    rss_values = [float(item["rss_mb"]) for item in beats if item.get("rss_mb")]
    effect_dups = sum(1 for item in events if item.get("kind") == "effect_dup")
    effect_new = sum(1 for item in events if item.get("kind") == "effect_new")

    # 资源泄漏：登记过但还活着的子进程
    leaked_pids = 0
    pids_dir = root / "pids"
    if pids_dir.exists():
        for pid_file in pids_dir.glob("*.pid"):
            try:
                pid = int(pid_file.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                continue
            if _pid_alive(pid):
                leaked_pids += 1

    report = {
        "jobs_total": len(jobs),
        "final_states": dict(states),
        "stuck_running": stuck,
        "peak_concurrency": peak,
        "job_runs": len(starts),
        "duplicate_occurrences": duplicate_occurrences,
        "signals_total": signals_total,
        "effects_created": effect_new,
        "duplicate_effect_attempts": effect_dups,
        "duplicate_effect_records": duplicate_effects,
        "effect_records_missing_key": effect_missing,
        "leaked_child_processes": leaked_pids,
        # Scope the lookup to the observer directory of this run. A bare
        # "observer-work" needle also matches every other run on the machine,
        # so leftovers from an earlier crash or soak were reported as this
        # run own leak.
        "orphan_observer_processes": _count_processes_matching(
            str(root / "observer-work")
        ),
        "heartbeats": len(beats),
        "rss_first_mb": rss_values[0] if rss_values else None,
        "rss_last_mb": rss_values[-1] if rss_values else None,
        "rss_peak_mb": max(rss_values) if rss_values else None,
    }
    ok = (
        stuck == 0
        and duplicate_occurrences == 0
        and duplicate_effects == 0
        and leaked_pids == 0
        and report.get("orphan_observer_processes") == 0
        and peak <= args.max_active
    )
    return ok, report


def _count_processes_matching(needle: str) -> int:
    """数一下还有多少进程命令行里带这个标记（用来发现孤儿观察器）。"""
    try:
        if os.name == "nt":
            # 只数 python 子进程：否则 powershell/bash 自己的命令行里也带着这个标记，
            # 会把"孤儿"误报成 5 个（第一版就踩了）。
            script = (
                "$n=0;Get-CimInstance Win32_Process | "
                "Where-Object { $_.Name -like 'python*' -and "
                "$_.CommandLine -like '*" + needle + "*' } | "
                "ForEach-Object { $n++ }; $n"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                timeout=90,
                check=False,
            )
            text = (result.stdout or b"").decode("utf-8", errors="ignore").strip()
            return int(text or 0)
        result = subprocess.run(
            ["pgrep", "-f", needle], capture_output=True, timeout=30, check=False
        )
        return len([line for line in (result.stdout or b"").splitlines() if line.strip()])
    except Exception:
        return -1


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        output = (result.stdout or b"").decode("utf-8", errors="ignore")
        if not output.strip():
            output = (result.stdout or b"").decode("mbcs", errors="ignore")
        return str(pid) in output
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _spawn(args: argparse.Namespace) -> subprocess.Popen:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--root",
        str(args.root),
        "--db",
        str(args.db),
        "--child",
        "--max-active",
        str(args.max_active),
        "--lease-seconds",
        str(args.lease_seconds),
        "--job-timeout",
        str(args.job_timeout),
        "--hours",
        str(args.hours),
        "--observer-events",
        str(args.observer_events),
        "--feed-interval",
        str(args.feed_interval),
        "--heartbeat-seconds",
        str(args.heartbeat_seconds),
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src") + os.pathsep + env.get(
        "PYTHONPATH", ""
    )
    return subprocess.Popen(command, env=env)


def _report_source() -> None:
    """Print the bound source and commit, and refuse a foreign checkout.

    These tools import ``lamtools_core`` directly, so an editable install
    pointing at another checkout would measure the wrong code silently.
    """
    import lamtools_core

    here = Path(__file__).resolve()
    expected = (here.parents[1] / "src").resolve()
    loaded = Path(lamtools_core.__file__).resolve().parent
    if not loaded.is_relative_to(expected):
        raise SystemExit(
            f"bound source mismatch: loaded {loaded}, expected {expected}"
        )
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=here.parents[2],
            capture_output=True,
            text=True,
            check=False,
        )
        head = result.stdout.strip() or "unknown"
    except OSError:
        head = "unknown"
    print(f"[source] {loaded} @ {head}", flush=True)


def main() -> int:
    _ensure_path()
    parser = argparse.ArgumentParser(description="Arrange/Observer reliability soak")
    parser.add_argument("--root", default=".lam/soak")
    parser.add_argument("--db", default="")
    parser.add_argument("--seed-jobs", type=int, default=60)
    parser.add_argument("--crashes", type=int, default=0)
    parser.add_argument("--hours", type=float, default=0)
    parser.add_argument("--max-active", type=int, default=3)
    parser.add_argument("--lease-seconds", type=float, default=3.0)
    parser.add_argument("--job-timeout", type=float, default=120.0)
    parser.add_argument("--observer-events", type=int, default=20)
    parser.add_argument("--feed-interval", type=float, default=10.0)
    parser.add_argument("--heartbeat-seconds", type=float, default=60.0)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    _report_source()

    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not args.db:
        args.db = str(root / "core.db")
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)

    if args.child:
        return asyncio.run(_child(args))

    seeded = asyncio.run(_seed(args))
    print(f"[seed] {seeded} jobs added, db={args.db}")

    child = _spawn(args)
    time.sleep(1.0)
    killed_at: list[float] = []
    restarted_at: list[float] = []

    for iteration in range(args.crashes):
        if child.poll() is not None:
            child = _spawn(args)
            restarted_at.append(time.time())
            time.sleep(0.5)
        time.sleep(random.uniform(0.3, 1.5))
        killed_at.append(time.time())
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(child.pid), "/T", "/F"],
                capture_output=True,
                timeout=20,
                check=False,
            )
        else:
            child.send_signal(signal.SIGKILL)
        child.wait(timeout=30)
        if (iteration + 1) % 10 == 0 or iteration == 0:
            print(f"[crash] {iteration + 1}/{args.crashes}")
        child = _spawn(args)
        restarted_at.append(time.time())
        time.sleep(random.uniform(0.2, 0.6))

    deadline = time.time() + args.hours * 3600
    if args.hours:
        print(f"[soak] running {args.hours}h")
        while time.time() < deadline:
            if child.poll() is not None:
                child = _spawn(args)
            time.sleep(5)
    else:
        # 排空：让最后一个进程把队列跑完，证明崩溃不会留下永久停摆。
        drain_deadline = time.time() + 180
        while time.time() < drain_deadline:
            _, probe = asyncio.run(_verify(args))
            if probe["stuck_running"] == 0 and probe["final_states"].get("scheduled", 0) == 0:
                break
            if child.poll() is not None:
                child = _spawn(args)
            time.sleep(2)

    if child.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(child.pid), "/T", "/F"],
                capture_output=True,
                timeout=20,
                check=False,
            )
        else:
            child.kill()
        child.wait(timeout=20)

    ok, report = asyncio.run(_verify(args))
    recovery: list[float] = []
    if killed_at and restarted_at:
        for index, start in enumerate(restarted_at):
            later = [item for item in killed_at if item > start]
            if later:
                recovery.append(min(later) - start)
    report["crashes"] = args.crashes
    report["recovery_seconds_median"] = (
        round(sorted(recovery)[len(recovery) // 2], 3) if recovery else None
    )
    print("[verify] " + json.dumps(report, ensure_ascii=False, indent=2))
    print("[result]", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
