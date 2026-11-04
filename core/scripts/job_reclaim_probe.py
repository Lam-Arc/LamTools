"""Does a hard-killed host reclaim its children? Four job scenarios, measured.

The runtime relies on a kill-on-close job so that a crashed or /F killed host
does not leave observer processes behind. This probe measures that claim with
the shipped helper (``create_kill_on_close_job``) under two host placements and
two spawn strategies:

* nested    - the host runs inside the harness job (what a managed harness does)
* detached  - the host is created through WMI, so its parent is a service and
              it starts outside any job (what a normal user launch looks like)

* joblist   - atomic PROC_THREAD_ATTRIBUTE_JOB_LIST at creation
* assign    - AssignProcessToJobObject right after spawn

For every scenario it records whether the flag is really set, whether the child
is really inside the job, and whether the child is still alive after the host is
terminated. Surviving children are reported, then cleaned up.

    python core/scripts/job_reclaim_probe.py
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259
KILL_ON_JOB_CLOSE = 0x2000
SLEEP_SCRIPT = "import time; time.sleep(600)"

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.TerminateProcess.restype = wintypes.BOOL
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeProcess.restype = wintypes.BOOL
kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
kernel32.IsProcessInJob.restype = wintypes.BOOL
kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
kernel32.QueryInformationJobObject.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.LPVOID,
]
kernel32.QueryInformationJobObject.restype = wintypes.BOOL
kernel32.GetCurrentProcess.restype = wintypes.HANDLE


def _alive(pid: int) -> bool:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    code = wintypes.DWORD()
    ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    kernel32.CloseHandle(handle)
    return bool(ok) and code.value == STILL_ACTIVE


def _hard_kill(pid: int) -> bool:
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    ok = kernel32.TerminateProcess(handle, 1)
    kernel32.CloseHandle(handle)
    return bool(ok)


def _in_any_job() -> bool:
    member = wintypes.BOOL(False)
    kernel32.IsProcessInJob(kernel32.GetCurrentProcess(), None, ctypes.byref(member))
    return bool(member.value)


def _in_job(process_handle: int, job: int) -> bool:
    member = wintypes.BOOL(False)
    ok = kernel32.IsProcessInJob(
        wintypes.HANDLE(process_handle), wintypes.HANDLE(job), ctypes.byref(member)
    )
    return bool(ok) and bool(member.value)


def _limit_flags(job: int) -> int:
    buffer = ctypes.create_string_buffer(144)
    ok = kernel32.QueryInformationJobObject(
        wintypes.HANDLE(job), 9, ctypes.cast(buffer, wintypes.LPVOID), 144, None
    )
    return int.from_bytes(buffer.raw[16:20], "little") if ok else -1


def _host(mode: str, report_path: str) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from lamtools_core.runtime.win_job_spawn import (  # noqa: PLC0415
        create_kill_on_close_job,
        spawn_in_job,
    )

    job = create_kill_on_close_job()
    flags = _limit_flags(job)
    assign_ok = None
    if mode.startswith("joblist"):
        # The shipped runtime spawns with pipes, which makes CreateProcessW
        # inherit handles. Both shapes are measured so an inheritance leak
        # cannot hide behind the variant we did not run.
        child = spawn_in_job(
            [sys.executable, "-u", "-c", SLEEP_SCRIPT],
            cwd=os.getcwd(),
            env=dict(os.environ),
            pipes=mode.endswith("pipes"),
            creationflags=0,
            job_handle=job,
        )
        child_pid, child_handle = child.pid, child._handle
    else:
        process = subprocess.Popen([sys.executable, "-u", "-c", SLEEP_SCRIPT], close_fds=True)
        assign_ok = bool(
            kernel32.AssignProcessToJobObject(
                wintypes.HANDLE(job), wintypes.HANDLE(int(process._handle))
            )
        )
        child_pid, child_handle = process.pid, int(process._handle)

    report = {
        "mode": mode,
        "host_pid": os.getpid(),
        "host_in_job": _in_any_job(),
        "limit_flags": flags,
        "kill_on_close_set": bool(flags & KILL_ON_JOB_CLOSE),
        "assign_ok": assign_ok,
        "child_pid": child_pid,
        "child_in_job": _in_job(child_handle, job),
    }
    Path(report_path).write_text(json.dumps(report), encoding="utf-8")
    time.sleep(600)
    return 0


def _start_nested(mode: str, report: Path) -> int | None:
    host = subprocess.Popen(
        [sys.executable, "-u", __file__, "--host", mode, "--report", str(report)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _wait_for_report(report)
    return host.pid


def _start_detached(mode: str, report: Path) -> int | None:
    command = (
        f'"{sys.executable}" -u "{Path(__file__).resolve()}" '
        f'--host {mode} --report "{report}"'
    )
    script = (
        "$arg = @{CommandLine='" + command.replace("'", "''") + "'}; "
        "(Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments $arg).ProcessId"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    pid_text = (result.stdout or "").strip().splitlines()[-1:] or [""]
    try:
        pid = int(pid_text[0].strip())
    except ValueError:
        return None
    _wait_for_report(report)
    return pid


def _wait_for_report(report: Path) -> dict | None:
    deadline = time.time() + 40
    while time.time() < deadline:
        if report.exists():
            try:
                return json.loads(report.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                time.sleep(0.1)
                continue
        time.sleep(0.1)
    return None


def _run_scenario(*, mode: str, placement: str) -> dict:
    report_path = Path(tempfile.mkdtemp()) / "report.json"
    launcher = _start_nested if placement == "nested" else _start_detached
    host_pid = launcher(mode, report_path)
    payload = _wait_for_report(report_path) or {}
    result: dict = {"placement": placement, "mode": mode, **payload}
    if host_pid is None:
        result["error"] = "host never started"
        return result
    result["host_pid"] = host_pid
    if not payload:
        result["error"] = "host never reported"
        _hard_kill(host_pid)
        return result

    _hard_kill(host_pid)
    for _ in range(40):
        if not _alive(host_pid):
            break
        time.sleep(0.1)
    time.sleep(3.0)
    child_pid = int(payload.get("child_pid") or 0)
    result["child_alive_after_host_kill"] = bool(child_pid) and _alive(child_pid)
    if result["child_alive_after_host_kill"]:
        _hard_kill(child_pid)
    return result


def main() -> int:
    results = []
    for placement, mode in (
        ("nested", "joblist"),
        ("nested", "joblist-pipes"),
        ("nested", "assign"),
        ("detached", "joblist"),
        ("detached", "assign"),
    ):
        result = _run_scenario(mode=mode, placement=placement)
        results.append(result)
        verdict = "SURVIVED" if result.get("child_alive_after_host_kill") else "reclaimed"
        print(
            f"[{placement}/{mode}] host_in_job={result.get('host_in_job')} "
            f"child_in_job={result.get('child_in_job')} "
            f"kill_on_close={result.get('kill_on_close_set')} -> {verdict}"
            + (f" error={result['error']}" if result.get("error") else ""),
            flush=True,
        )
    print(json.dumps(results, indent=2), flush=True)
    leaked = [item for item in results if item.get("child_alive_after_host_kill")]
    print(f"[result] {len(leaked)} scenario(s) left a surviving child", flush=True)
    return 0


if __name__ == "__main__":
    if "--host" in sys.argv:
        index = sys.argv.index("--report") + 1
        raise SystemExit(_host(sys.argv[sys.argv.index("--host") + 1], sys.argv[index]))
    raise SystemExit(main())
