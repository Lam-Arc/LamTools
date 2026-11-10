"""UIA 无障碍树：常驻 PowerShell 助手进程，带超时重启。

为什么不是纯 Python：UIA 是 COM 接口，ctypes 手搓 vtable 容易在 64 位指针和
VARIANT 上出错；PowerShell 直接调用 .NET 的 UIAutomationClient，代码短且行为
确定。代价是跨进程，所以助手常驻，靠 stdin/stdout 的 JSON 行通信。

为什么必须有超时：某些窗口的某个元素会让 UIA 卡住几十秒（实测记事本的保存
对话框出现过 80 秒）。超时后杀掉助手重启，比让整个回合卡死强。

user:“查一下 computer use 功能怎么做”+(模型要能按元素名点击，而不是靠猜像素
坐标；树为空时上层自动退回视觉路线)。
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HELPER_PATH = Path(__file__).with_name("uia_helper.ps1")
_START_TIMEOUT = 20.0
_DEFAULT_TIMEOUT = 8.0
# 助手崩溃后的冷却，避免每一步都重启一个注定失败的进程。
_RESTART_COOLDOWN = 3.0


class UiaError(RuntimeError):
    """UIA 助手不可用或返回错误。"""


class UiaHelper:
    """线程安全的常驻 UIA 助手。整个进程共用一个实例。"""

    def __init__(self, helper_path: Path | None = None) -> None:
        self._path = helper_path or _HELPER_PATH
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._last_failure = 0.0
        self._closed = False

    # -- 生命周期 ---------------------------------------------------------

    def _spawn(self) -> None:
        if not self._path.is_file():
            raise UiaError(f"uia helper script is missing: {self._path}")
        creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        self._proc = subprocess.Popen(
            [
                "powershell", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(self._path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        self._lines = queue.Queue()
        reader = threading.Thread(target=self._pump, args=(self._proc, self._lines), daemon=True)
        reader.start()
        self._reader = reader
        try:
            hello = self._next_line(_START_TIMEOUT)
        except UiaError:
            self._kill()
            raise
        if not hello or not hello.get("ok"):
            self._kill()
            raise UiaError(f"uia helper did not start: {hello}")

    @staticmethod
    def _pump(proc: subprocess.Popen[str], sink: queue.Queue[str | None]) -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                sink.put(line)
        except Exception:  # noqa: BLE001 - 读线程退出只影响本次调用
            pass
        finally:
            sink.put(None)

    def _kill(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=3)
        except Exception:
            pass

    def _next_line(self, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise UiaError(f"uia helper timed out after {timeout:.1f}s")
            try:
                raw = self._lines.get(timeout=remaining)
            except queue.Empty:
                raise UiaError(f"uia helper timed out after {timeout:.1f}s") from None
            if raw is None:
                raise UiaError("uia helper process exited")
            text = raw.strip()
            if not text:
                continue
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                # 助手偶尔会打印 .NET 的杂项输出，跳过而不是让整次调用失败。
                logger.debug("uia helper non-json line: %s", text[:200])
                continue

    def _ensure(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        if time.monotonic() - self._last_failure < _RESTART_COOLDOWN:
            raise UiaError("uia helper is restarting")
        try:
            self._spawn()
        except UiaError:
            self._last_failure = time.monotonic()
            raise
        except Exception as exc:  # noqa: BLE001 - 找不到 powershell 等启动失败同样进冷却
            self._last_failure = time.monotonic()
            raise UiaError(f"uia helper failed to start: {exc}") from exc

    # -- 调用 -------------------------------------------------------------

    def call(self, payload: dict[str, Any], *, timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
        if self._closed:
            raise UiaError("uia helper is closed")
        with self._lock:
            self._ensure()
            assert self._proc is not None and self._proc.stdin is not None
            try:
                self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self._proc.stdin.flush()
            except Exception as exc:
                self._kill()
                self._last_failure = time.monotonic()
                raise UiaError(f"uia helper write failed: {exc}") from exc
            try:
                response = self._next_line(timeout)
            except UiaError:
                # 卡住的 COM 调用杀不掉，只能整进程重启。
                self._kill()
                self._last_failure = time.monotonic()
                raise
            if not response.get("ok"):
                error = str(response.get("error") or "unknown uia error")
                raise UiaError(error)
            data = response.get("data")
            return data if isinstance(data, dict) else {}

    # -- 语义操作 ---------------------------------------------------------

    def tree(self, hwnd: int, *, max_nodes: int = 300, timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
        return self.call(
            {"op": "tree", "hwnd": int(hwnd), "max_nodes": int(max_nodes)},
            timeout=timeout,
        )

    def invoke(self, ref: str, *, timeout: float = 5.0) -> dict[str, Any]:
        return self.call({"op": "invoke", "ref": ref}, timeout=timeout)

    def focus(self, ref: str, *, timeout: float = 5.0) -> dict[str, Any]:
        return self.call({"op": "focus", "ref": ref}, timeout=timeout)

    def value(self, ref: str, *, timeout: float = 5.0) -> dict[str, Any]:
        return self.call({"op": "value", "ref": ref}, timeout=timeout)

    def window(self, hwnd: int, *, timeout: float = 5.0) -> dict[str, Any]:
        return self.call({"op": "window", "hwnd": int(hwnd)}, timeout=timeout)

    def ping(self, *, timeout: float = 3.0) -> dict[str, Any]:
        return self.call({"op": "ping"}, timeout=timeout)

    def close(self) -> None:
        self._closed = True
        with self._lock:
            proc = self._proc
            self._proc = None
            if proc is None:
                return
            try:
                if proc.stdin:
                    proc.stdin.write("exit\n")
                    proc.stdin.flush()
            except Exception:
                pass
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


_shared: UiaHelper | None = None
_shared_lock = threading.Lock()


def shared_helper() -> UiaHelper:
    """进程级单例。助手进程只保留一份，ref 才能在两步之间继续用。"""
    global _shared
    with _shared_lock:
        if _shared is None or _shared._closed:  # noqa: SLF001 - 同模块内的生命周期判断
            _shared = UiaHelper()
        return _shared


def shutdown_shared() -> None:
    global _shared
    with _shared_lock:
        helper = _shared
        _shared = None
    if helper is not None:
        helper.close()
