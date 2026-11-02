"""调度器单实例租约。

user:“全局并发限制（单实例运行）”+(同一份数据目录只能有一个进程在跑调度器；
第二个进程即便起来了，也不能再抢任务，否则并发上限会按进程数翻倍)。

设计取舍：锁只保护“调度器”这一段（Arrange Runner + Observer Supervisor），
不阻止第二个进程提供 HTTP 接口。这样 CLI 误启动不会把桌面端服务打死，
但永远不会出现两个调度器同时领任务。

Windows 细节：字节范围锁会连带挡住对同一字节的读写，所以把锁放在偏移
4096（远在记录区之后），pid 记录写在文件开头，这样持锁期间仍能读 pid。
"""

from __future__ import annotations

from pathlib import Path

import logging
import os

_logger = logging.getLogger(__name__)

# 进程内注册表：Windows 的字节范围锁对同一进程的不同句柄并不总是报冲突，
# 只靠系统锁会让“同进程起两个调度器”漏过去。两层都要。
_HELD: set[str] = set()

_LOCK_OFFSET = 4096


class SchedulerLease:
    """跨平台的进程生命周期文件锁（Windows 用 msvcrt，POSIX 用 fcntl）。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._handle: object | None = None
        self._acquired = False

    @property
    def acquired(self) -> bool:
        return self._acquired

    def acquire(self) -> bool:
        if self._acquired:
            return True
        key = str(self.path.resolve())
        if key in _HELD:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = open(self.path, "r+b") if self.path.exists() else open(self.path, "w+b")
        except OSError:
            _logger.warning("scheduler lease file could not be opened: %s", self.path, exc_info=True)
            return False
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(_LOCK_OFFSET)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        _HELD.add(key)
        self._handle = handle
        self._acquired = True
        try:
            # 固定宽度记录，避免上次更长的 pid 留下尾巴。
            handle.seek(0)
            handle.write(f"{os.getpid():<16}".encode("ascii"))
            handle.flush()
        except OSError:
            _logger.debug("scheduler lease pid write failed", exc_info=True)
        return True

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        self._acquired = False
        _HELD.discard(str(self.path.resolve()))
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(_LOCK_OFFSET)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            _logger.debug("scheduler lease unlock failed", exc_info=True)
        finally:
            try:
                handle.close()
            except OSError:
                pass

    def holder_pid(self) -> int | None:
        try:
            raw = self.path.read_bytes()[:16]
        except OSError:
            return None
        text = raw.decode("ascii", errors="ignore").strip()
        try:
            return int(text)
        except ValueError:
            return None


__all__ = ["SchedulerLease"]
