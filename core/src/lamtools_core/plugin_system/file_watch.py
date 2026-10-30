"""user:“继续，把 2 阶段都做完”+(以明确的有限轮询近似监听，真实发出变化，所有后台任务随启动代关闭)。"""
import asyncio
import inspect
from dataclasses import dataclass

from .filesystem_access import FilesystemError


@dataclass(frozen=True)
class FileWatchEvent:
    path: str
    kind: str


@dataclass(frozen=True)
class FileWatchResult:
    reason: str
    changes: int


class FileWatch:
    def __init__(self, api, path, callback, interval, snapshot):
        self._api, self._path, self._callback, self._interval = api, path, callback, interval
        self._snapshot, self._stop = snapshot, asyncio.Event()
        self._error, self._changes = None, 0
        self._task = asyncio.create_task(self._run(), name="plugin-file-watch")

    async def _run(self):
        try:
            while self._api._scope.accepting:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                    break
                except TimeoutError:
                    pass
                if not self._api._scope.accepting:
                    break
                current = self._api._watch_snapshot(self._path)
                if current != self._snapshot:
                    kind = "created" if self._snapshot is None else "deleted" if current is None else "changed"
                    self._snapshot = current
                    self._changes += 1
                    self._api._scope.acquire()
                    try:
                        async with asyncio.timeout(5):
                            response = self._callback(FileWatchEvent(str(self._path), kind))
                            if inspect.isawaitable(response):
                                await response
                    except Exception:
                        raise FilesystemError("fs/watch-callback-failed", "Watch callback failed or exceeded its deadline") from None
                    finally:
                        self._api._scope.release()
        except FilesystemError as error:
            self._error = error
        except Exception:
            self._error = FilesystemError("fs/watch-failed", "File watch failed")
        finally:
            self._api._watches.discard(self)
        return FileWatchResult("error" if self._error else "closed", self._changes)

    async def wait(self):
        self._api._scope.check_open()
        result = await asyncio.shield(self._task)
        if self._error is not None:
            raise self._error
        return result

    async def aclose(self):
        self._stop.set()
        caller = asyncio.current_task()
        if caller is self._task:
            return
        cancelling = caller.cancelling()
        while not self._task.done():
            try:
                await asyncio.shield(self._task)
            except asyncio.CancelledError:
                continue
        self._task.result()
        if caller.cancelling() > cancelling:
            raise asyncio.CancelledError

    async def __aenter__(self):
        self._api._scope.check_open()
        return self

    async def __aexit__(self, *args):
        await self.aclose()
