"""user:“接口完善”+(配置读改写使用稳定旁路文件锁，独立进程合作串行，等待次数有明确上限)。"""

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import threading
import time

_thread_lock = threading.RLock()


class FileLockBusy(OSError):
    pass


@contextmanager
def locked_file(path: Path):
    with _thread_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as stream:
            stream.seek(0, 2)
            if not stream.tell():
                stream.write(b"0")
                stream.flush()
            for attempt in range(41):
                stream.seek(0)
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK, errno.EBUSY}:
                        raise
                    if attempt == 40:
                        raise FileLockBusy("File transaction lock is busy") from None
                    time.sleep(0.05)
            try:
                yield
            finally:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass  # File close releases the advisory lock.
