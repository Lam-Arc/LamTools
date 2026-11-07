"""强杀注入：只杀宿主、不连带杀树，验证"父死子亡"是否真的成立。

user:“修复 kill_injection.py 卡死问题；给每一步设置独立超时；记录每轮阶段、PID、
耗时、退出码；单轮失败不能拖死整个测试批次，超时必须算失败”

与旧版的区别：
1. 每个阶段（启动 / 等子进程 / 强杀 / 回收 / 检查）都有独立超时，任何一步超时
   只算这一轮失败，批次继续。
2. 每轮记录阶段耗时、宿主 pid、退出码，输出到 JSONL 原始日志。
3. **防假通过**：必须先观测到 Observer 子进程和它起的孙进程都真实存在，这一轮
   才算“有效注入”；无效轮次单独计数，不计入验收。
4. 进程树完整性：同时检查子进程和孙进程，不只看直接子进程。

用法：
    python core/scripts/kill_injection.py --iterations 10
    python core/scripts/kill_injection.py --iterations 1000 --delay-mode sweep
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import traceback

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _ensure_path() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))


# ---------------------------------------------------------------------------
# 进程存活 / 强杀工具
# ---------------------------------------------------------------------------


def _pid_alive(pid: int, *, timeout: float = 10.0) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                timeout=timeout,
                check=False,
                creationflags=CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            return True  # 查不到就当还活着，宁可多查一轮
        text = (result.stdout or b"").decode("utf-8", errors="ignore")
        if not text.strip():
            text = (result.stdout or b"").decode("mbcs", errors="ignore")
        return str(pid) in text
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_host(host: subprocess.Popen, *, timeout: float = 10.0) -> str:
    """强杀宿主，返回这一阶段的结果标记。

    只用 /F 不带 /T：/T 会连带杀树，等于替被测代码兜底、掩盖孤儿。
    每一步都有超时，绝不阻塞批次。
    """
    if host.poll() is not None:
        return "already-exited"
    try:
        subprocess.run(
            ["taskkill", "/PID", str(host.pid), "/F"],
            capture_output=True,
            timeout=timeout,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
        return "taskkill"
    except subprocess.TimeoutExpired:
        try:
            host.kill()
        except OSError:
            pass
        return "taskkill-timeout-fallback-kill"
    except OSError:
        try:
            host.kill()
        except OSError:
            pass
        return "taskkill-oserror-fallback-kill"


def _reap(host: subprocess.Popen, *, timeout: float = 10.0) -> int | None:
    try:
        return host.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            host.kill()
        except OSError:
            pass
        try:
            return host.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return None


# ---------------------------------------------------------------------------
# 观察器脚本：子进程 + 孙进程，各自写出 pid 标记
# ---------------------------------------------------------------------------

OBSERVER_SCRIPT = """
import os
import subprocess
import sys
import time
from pathlib import Path

mark = Path(__MARK_DIR__)
mark.mkdir(parents=True, exist_ok=True)
(mark / ("child-" + str(os.getpid()))).write_text(str(os.getpid()), encoding="utf-8")

# 观察器自己再起一个孙进程：验证进程树清理，而不只是直接子进程。
grand_code = (
    "import os,sys,time;"
    "from pathlib import Path;"
    "m=Path(sys.argv[1]);"
    "(m/('grand-'+str(os.getpid()))).write_text(str(os.getpid()), encoding='utf-8');"
    "time.sleep(900)"
)
try:
    subprocess.Popen([sys.executable, "-c", grand_code, str(mark)])
except Exception:
    pass

while True:
    time.sleep(0.2)
"""


def _write_observer(work: Path, mark_dir: Path) -> Path:
    script = work / "observer.py"
    mark_dir.mkdir(parents=True, exist_ok=True)
    script.write_text(
        OBSERVER_SCRIPT.replace("__MARK_DIR__", repr(str(mark_dir))), encoding="utf-8"
    )
    return script


async def _host(args: argparse.Namespace) -> int:
    _ensure_path()
    from lamtools_core.app.core_db import open_core_app_db
    from lamtools_core.runtime.arrange import ArrangeManager
    from lamtools_core.runtime.observer import ObserverSupervisor, prepare_observer

    root = Path(args.root).resolve()
    work = root / "observer-work"
    work.mkdir(parents=True, exist_ok=True)
    _write_observer(work, root / "marks")

    db = await open_core_app_db(Path(args.db))
    manager = ArrangeManager(db.arrange_store)
    jobs = await manager.list()
    if not jobs:
        await manager.create(
            thread_id="kill",
            work_root=str(work),
            kind="focus",
            operation="turn.start",
            payload={"message": "kill"},
            trigger={"type": "event", "event_type": "kill.tick"},
            observer=prepare_observer({"entry": "observer.py"}, work_root=work),
        )
    supervisor = ObserverSupervisor(
        db.arrange_store,
        data_dir=root / "observer-data",
        poll_interval=0.05,
    )
    await supervisor.start()
    try:
        while True:
            await asyncio.sleep(0.2)
    finally:
        await supervisor.stop()
        await db.close()


# ---------------------------------------------------------------------------
# 批次驱动
# ---------------------------------------------------------------------------


def _marks(root: Path) -> dict[str, int]:
    marks = root / "marks"
    result: dict[str, int] = {}
    if not marks.exists():
        return result
    for path in marks.glob("*"):
        try:
            result[path.stem] = int(path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            continue
    return result


def _drop_marks(root: Path) -> None:
    marks = root / "marks"
    if not marks.exists():
        return
    for path in marks.glob("*"):
        try:
            path.unlink()
        except OSError:
            pass


def _spawn_host(args: argparse.Namespace) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src") + os.pathsep + env.get(
        "PYTHONPATH", ""
    )
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--root",
        str(args.root),
        "--db",
        str(args.db),
        "--host",
    ]
    return subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )


def _wait_for_tree(
    args: argparse.Namespace, host: subprocess.Popen, root: Path
) -> tuple[bool, dict[str, float], str]:
    """等到 Observer 子进程和孙进程都真实存在。

    user:“每轮必须确认 Observer、子进程和孙进程已真实启动”+(否则这一轮
    "0 孤儿"毫无意义——前两版注入器就是这样空转通过的)。
    """
    deadline = time.perf_counter() + args.startup_timeout
    started = time.perf_counter()
    while time.perf_counter() < deadline:
        if host.poll() is not None:
            return False, {"wait_tree": time.perf_counter() - started}, "host-exited-early"
        marks = _marks(root)
        if any(name.startswith("child-") for name in marks) and any(
            name.startswith("grand-") for name in marks
        ):
            return True, {"wait_tree": time.perf_counter() - started}, "ready"
        time.sleep(0.02)
    return False, {"wait_tree": time.perf_counter() - started}, "startup-timeout"


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
    parser = argparse.ArgumentParser(description="Hard-kill injection for observer orphans")
    parser.add_argument("--root", default=".lam/killinject")
    parser.add_argument("--db", default="")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    parser.add_argument("--stage-timeout", type=float, default=10.0)
    parser.add_argument("--settle", type=float, default=0.4)
    parser.add_argument("--delay-mode", choices=["sweep", "random", "none"], default="sweep")
    parser.add_argument("--max-delay", type=float, default=0.30)
    parser.add_argument("--host", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    _report_source()

    root = Path(args.root).resolve()
    (root / "marks").mkdir(parents=True, exist_ok=True)
    if not args.db:
        args.db = str(root / "core.db")
    if args.host:
        return asyncio.run(_host(args))

    log_path = root / "iterations.jsonl"
    log_path.write_text("", encoding="utf-8")

    stats = {
        "iterations": args.iterations,
        "valid": 0,
        "invalid": 0,
        "timeouts": 0,
        "host_errors": 0,
        "orphans": 0,
        "orphan_children": 0,
        "orphan_grandchildren": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    batch_started = time.perf_counter()

    for iteration in range(args.iterations):
        record: dict[str, object] = {"iteration": iteration + 1}
        stage: dict[str, float] = {}
        t_stage = time.perf_counter()

        def mark_stage(name: str) -> None:
            nonlocal t_stage
            now = time.perf_counter()
            stage[name] = round(now - t_stage, 3)
            t_stage = now

        host: subprocess.Popen | None = None
        try:
            _drop_marks(root)
            host = _spawn_host(args)
            record["host_pid"] = host.pid
            mark_stage("spawn")

            ready, wait_stage, reason = _wait_for_tree(args, host, root)
            stage.update(wait_stage)
            mark_stage("wait_tree_finish")
            record["tree_ready"] = ready
            record["reason"] = reason
            if not ready:
                # 无效轮次：不能让"没起起来"冒充"0 孤儿"。
                stats["invalid"] += 1
                if reason == "startup-timeout":
                    stats["timeouts"] += 1
                else:
                    stats["host_errors"] += 1
                _kill_host(host, timeout=args.stage_timeout)
                record["host_exit"] = _reap(host, timeout=args.stage_timeout)
                mark_stage("cleanup")
                record["elapsed"] = round(time.perf_counter() - t_stage, 3)
                record["stage"] = stage
                _append(log_path, record)
                continue

            stats["valid"] += 1

            # 在"树已就绪"的不同阶段强杀：0ms、以及按偏移扫描到 max-delay。
            if args.delay_mode == "sweep":
                delay = 0.0 if iteration % 3 == 0 else (iteration * 0.01) % args.max_delay
            elif args.delay_mode == "random":
                delay = random.uniform(0, args.max_delay)
            else:
                delay = 0.0
            record["kill_delay"] = round(delay, 3)
            if delay:
                time.sleep(delay)
            mark_stage("delay")

            record["kill_method"] = _kill_host(host, timeout=args.stage_timeout)
            mark_stage("kill")
            record["host_exit"] = _reap(host, timeout=args.stage_timeout)
            if record["host_exit"] is None:
                stats["timeouts"] += 1
            mark_stage("reap")

            time.sleep(args.settle)
            mark_stage("settle")

            marks = _marks(root)
            survivors = {name: pid for name, pid in marks.items() if _pid_alive(pid)}
            children = [name for name in survivors if name.startswith("child-")]
            grandchildren = [name for name in survivors if name.startswith("grand-")]
            record["marks"] = len(marks)
            record["orphans"] = len(survivors)
            record["orphan_children"] = len(children)
            record["orphan_grandchildren"] = len(grandchildren)
            record["orphan_sample"] = list(survivors.values())[:5]
            mark_stage("check")

            if survivors:
                stats["orphans"] += len(survivors)
                stats["orphan_children"] += len(children)
                stats["orphan_grandchildren"] += len(grandchildren)
                for pid in survivors.values():
                    try:
                        subprocess.run(
                            ["taskkill", "/PID", str(pid), "/T", "/F"],
                            capture_output=True,
                            timeout=args.stage_timeout,
                            check=False,
                            creationflags=CREATE_NO_WINDOW,
                        )
                    except (subprocess.TimeoutExpired, OSError):
                        pass
        except Exception as exc:  # noqa: BLE001 — 单轮异常不能拖死批次
            stats["host_errors"] += 1
            record["error"] = f"{type(exc).__name__}: {exc}"
            record["traceback"] = traceback.format_exc(limit=3)
        finally:
            if host is not None and host.poll() is None:
                _kill_host(host, timeout=args.stage_timeout)
                _reap(host, timeout=args.stage_timeout)
            record.setdefault("stage", stage)
            record["elapsed"] = round(sum(stage.values()), 3)
            _append(log_path, record)

        if (iteration + 1) % 10 == 0 or iteration == 0:
            elapsed = time.perf_counter() - batch_started
            print(
                f"[progress] {iteration + 1}/{args.iterations} "
                f"valid={stats['valid']} invalid={stats['invalid']} "
                f"orphans={stats['orphans']} timeouts={stats['timeouts']} "
                f"elapsed={elapsed:.0f}s",
                flush=True,
            )

    stats["elapsed_seconds"] = round(time.perf_counter() - batch_started, 1)
    stats["finished_at"] = datetime.now(timezone.utc).isoformat()
    stats["kill_method"] = "taskkill /F (host only, no /T)"
    stats["log"] = str(log_path)
    (root / "kill_injection_report.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[report] " + json.dumps(stats, ensure_ascii=False), flush=True)
    ok = stats["orphans"] == 0 and stats["valid"] == args.iterations and stats["timeouts"] == 0
    print("[result]", "PASS" if ok else "FAIL", flush=True)
    return 0 if ok else 1


def _append(path: Path, record: dict[str, object]) -> None:
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
