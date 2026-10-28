"""Small process-memory samples; no heap dumps or conversation contents."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
import time
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)


def process_memory_sample() -> dict[str, int] | None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        get_memory = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
        get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        get_memory.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not get_memory(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return None
        return {"rss_bytes": counters.WorkingSetSize, "peak_rss_bytes": counters.PeakWorkingSetSize,
                "private_bytes": counters.PrivateUsage, "peak_private_bytes": counters.PeakPagefileUsage}
    if sys.platform == "linux":
        values = {}
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(":")
            if key in {"VmRSS", "VmHWM", "VmData", "VmPeak"}:
                values[key] = int(value.split()[0]) * 1024
        return {"rss_bytes": values.get("VmRSS", 0), "peak_rss_bytes": values.get("VmHWM", 0),
                "data_bytes": values.get("VmData", 0), "peak_virtual_bytes": values.get("VmPeak", 0)}
    return None


class BackendMemoryDiagnostics:
    # user:“而且刚才为什么内存占用这么多，差不多 14g？”+(定期记录后端自身内存和任务类型，增长时提前留证，不保存任何会话内容)。
    def __init__(self) -> None:
        self._last_at: float | None = None
        self._last_bytes = 0

    def sample(self) -> None:
        try:
            memory = process_memory_sample()
            if memory is None:
                return
            now = time.monotonic()
            current = memory.get("private_bytes", memory["rss_bytes"])
            if self._last_at is not None and now - self._last_at < 60 and abs(current - self._last_bytes) < 256 * 1024**2:
                return
            self._last_at, self._last_bytes = now, current
            tasks = asyncio.all_tasks()
            kinds = Counter(getattr(task.get_coro(), "__qualname__", type(task.get_coro()).__name__) for task in tasks)
            sample = {**memory, "tasks": len(tasks), "threads": threading.active_count(),
                      "coroutines": kinds.most_common(12)}
            logger.log(logging.WARNING if current >= 2 * 1024**3 else logging.INFO,
                       "[backend-memory] %s", json.dumps(sample, separators=(",", ":")))
        except Exception:
            logger.debug("[backend-memory] sampling unavailable", exc_info=True)
