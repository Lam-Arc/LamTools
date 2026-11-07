"""user:“第二阶段结束后 就继续开展第三阶段”+(变化流复用原FileWatch轮询；有界合并通知，不等待消费者拉取才释放资源)。"""
import asyncio
import hashlib

from lamtools_core.async_tasks import finish_on_cancel
from .filesystem_access import FilesystemError, PluginFilesystemAPI
from .workspace_files import WorkspaceFileError

MAX_STREAMS = 32
MAX_ROOTS = 32


class _WatchFilesystem(PluginFilesystemAPI):
    def __init__(self, api, root):
        super().__init__(root, api._scope, api._context.data_dir)
        self._check_binding = api._check

    def _watch_snapshot(self, path):
        self._check_binding()
        return super()._watch_snapshot(path)


async def open_changes(api, fs, path, interval):
    scope = api._scope
    state = getattr(scope, "_workspace_file_changes", None)
    if state is None:
        state = {"streams": set(), "roots": {}}
        scope._workspace_file_changes = state
        async def close_all():
            results = await asyncio.gather(*(stream.aclose() for stream in tuple(state["streams"])), return_exceptions=True)
            failures = [result for result in results if isinstance(result, Exception)]
            if failures:
                raise ExceptionGroup("Session file change cleanup failed", failures)
            state["roots"].clear()
        scope.on_dispose(close_all)
    if len(state["streams"]) >= MAX_STREAMS:
        raise WorkspaceFileError("workspace-file/watch-limit", "Too many active session file streams")
    key = (str(fs.root), id(api._host), str(api._context.data_dir))
    watched = state["roots"].get(key)
    if watched is None:
        if len(state["roots"]) >= MAX_ROOTS:
            raise WorkspaceFileError("workspace-file/watch-limit", "Too many distinct watch roots in this startup")
        watched = _WatchFilesystem(api, fs.root)
    stream = WorkspaceFileChanges(api, watched, str(watched.resolve(path)), state)
    stream._watch = await watched.watch(path, stream._changed, interval=interval)
    state["roots"][key] = watched
    state["streams"].add(stream)
    stream._watch._task.add_done_callback(stream._finished)
    return stream


class WorkspaceFileChanges:
    def __init__(self, api, fs, path, state):
        self._api, self._fs, self._path, self._state = api, fs, path, state
        self._watch, self._close_task = None, None
        self._available = asyncio.Event()
        self._latest, self._error = None, None
        self._ready, self._closed, self._closing, self._reading = True, False, False, False

    def _changed(self, event):
        self._api._check()
        try:
            info = self._fs.stat(self._path)
            version = f"stat:{info.size}:{info.modified_ns}"
            if info.kind == "directory":
                version = "watch:" + hashlib.sha256(repr(self._watch._snapshot).encode("utf8")).hexdigest()
            change = {"absolute_path": self._path, "version": version, "bytes": info.size}
        except FilesystemError as error:
            if error.code != "fs/not-found":
                raise
            change = {"absolute_path": self._path, "absent": True}
        # user:“完成真实接口、参数/错误、作用域、取消/清理”+(只保留最新失效通知，慢消费者不能累积无界队列；ready单独持有保证先发)。
        self._latest = {"kind": "change", "change": change}
        self._available.set()

    def _finished(self, task):
        if not self._closing:
            self._error = self._watch._error
            if task.cancelled():
                self._error = FilesystemError("fs/watch-failed", "Original watcher was cancelled")
            elif task.exception() is not None:
                self._error = FilesystemError("fs/watch-failed", "Original watcher failed")
        self._closed = True
        self._state["streams"].discard(self)
        self._available.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._reading:
            raise WorkspaceFileError("workspace-file/concurrent-read", "Use one consumer per file change stream")
        self._reading = True
        try:
            self._api._check()
            if self._ready and not self._closed:
                self._ready = False
                return {"kind": "ready"}
            while not self._closed and self._latest is None:
                await self._available.wait()
                self._available.clear()
            self._api._check()
            if self._closed:
                if self._error is not None:
                    error, self._error = self._error, None
                    raise error
                raise StopAsyncIteration
            result, self._latest = self._latest, None
            self._available.clear()
            return result
        except StopAsyncIteration:
            raise
        except BaseException:
            await self.aclose()
            raise
        finally:
            self._reading = False

    async def aclose(self):
        self._closing, self._closed, self._latest = True, True, None
        self._available.set()
        if self._close_task is None:
            async def close():
                try:
                    if self._watch is not None:
                        await self._watch.aclose()
                finally:
                    self._state["streams"].discard(self)
            self._close_task = asyncio.create_task(close(), name="workspace-file-changes-close")
        # user:“完成真实接口、参数/错误、作用域、取消/清理”+(关闭不依赖消费方pull，重复取消调用者仍等待原watch真实退出)。
        async def join():
            await asyncio.shield(self._close_task)
        await finish_on_cancel(join(), name="workspace-file-changes-join")
