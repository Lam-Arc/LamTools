"""Run all Core test suites with bounded concurrency and visible failures."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock
from time import perf_counter
import traceback

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_LOCK = Lock()


@dataclass(frozen=True)
class Suite:
    name: str
    command: tuple[str, ...]
    cwd: Path


def core_suites(root: Path = ROOT) -> tuple[Suite, ...]:
    npm = "npm.cmd" if os.name == "nt" else "npm"
    return (
        Suite("core", (sys.executable, "-m", "pytest", "tests", "--durations=10"), root / "core"),
        Suite("core-ui", (npm, "run", "test:contract"), root / "core" / "ui"),
    )


def report(message: str) -> None:
    with OUTPUT_LOCK:
        print(message, flush=True)


def run_suite(suite: Suite, env: dict[str, str]) -> int:
    start = perf_counter()
    report(f"[{suite.name}] Starting")
    try:
        with subprocess.Popen(
            suite.command,
            cwd=suite.cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as process:
            assert process.stdout is not None
            for line in process.stdout:
                report(f"[{suite.name}] {line.rstrip()}")
            code = process.wait()
    except OSError as error:
        report(f"[{suite.name}] Could not start: {error}")
        code = 1
    status = "PASSED" if code == 0 else f"FAILED (exit {code})"
    report(f"[{suite.name}] {status} in {perf_counter() - start:.1f}s")
    return code


def run_suites(suites: tuple[Suite, ...], *, serial: bool = False) -> int:
    env = os.environ.copy()
    core_src = str(ROOT / "core" / "src")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (core_src, env.get("PYTHONPATH"))))
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    start = perf_counter()
    # Only independent suites overlap; preserve each framework's isolation,
    # discovery, assertions, and own worker settings.
    with ThreadPoolExecutor(max_workers=1 if serial else 2) as pool:
        futures = {pool.submit(run_suite, suite, env): suite for suite in suites}
        codes = []
        for future in as_completed(futures):
            try:
                codes.append(future.result())
            except Exception:
                report(f"[{futures[future].name}] RUNNER FAILED\n{traceback.format_exc()}")
                codes.append(1)
    success = all(code == 0 for code in codes)
    report(f"{'All tests passed' if success else 'TESTS FAILED'} in {perf_counter() - start:.1f}s.")
    return 0 if success else 1


def main() -> int:
    # Windows redirects Python output using the legacy console code page.
    # Vitest emits Unicode markers and failure excerpts; keep the parent
    # UTF-8 too, otherwise a reporting error can hide a suite's test results.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=("core", "all"), nargs="?", default="all")
    parser.add_argument("--serial", action="store_true", help="Run the same suites sequentially")
    args = parser.parse_args()
    return run_suites(core_suites(), serial=args.serial)


if __name__ == "__main__":
    raise SystemExit(main())
