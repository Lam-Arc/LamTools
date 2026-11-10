"""user:“第二阶段结束后 就继续开展第三阶段”+(会话只读复用原可见性和项目身份)。"""
import asyncio
import math
from pathlib import Path

from lamtools_core.async_tasks import finish_on_cancel

from .sessions import SESSIONS


class SessionControllerError(RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code, self.may_have_changed = code, may_have_changed
        super().__init__(message)


class PluginSessionController:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._root = Path(context.work_root).resolve()
        self._directories = context.require_service("working_directory")
        self._sessions = context.bind_service(SESSIONS)

    def _check(self):
        self._scope.check_open()
        if (self._context._registration_scope is not self._scope
                or Path(self._context.work_root).resolve() != self._root
                or self._context.service("working_directory") is not self._directories
                or getattr(self._directories, "_sessions", None) is not self._sessions.get()):
            raise SessionControllerError("session-controller/host-changed", "Session binding changed")

    async def _admit(self, session_id):
        self._check()
        state = await self._directories.for_scope(self._scope).get(session_id)
        self._check()
        if Path(state.project_root).resolve() != self._root:
            raise SessionControllerError("session-controller/not-found", "Session is unavailable in this project")
        return state

    async def _read(self, method, session_id, **kwargs):
        self._scope.acquire()
        try:
            # user:“复用原宿主权威”+(只读前后均重新检查原会话可见性和项目，失效不发布旧结果)。
            await self._admit(session_id)
            result = await self._sessions.call(method, session_id, **kwargs)
            await self._admit(session_id)
            # user:“完成真实接口、参数/错误、作用域、取消/清理”+(等待后不能发布被替换的会话提供方结果)。
            self._sessions.get()
            return result
        finally:
            self._scope.release()

    async def state(self, session_id):
        return await self._read("state", session_id)

    async def events(self, session_id, *, after_seq=0, limit=100, max_bytes=1048576):
        return await self._read("events", session_id, after_seq=after_seq, limit=limit, max_bytes=max_bytes)

    async def wait(self, session_id, *, timeout=30):
        return await self._read("wait", session_id, timeout=timeout)

    async def follow(self, session_id, *, after_seq=0, limit=100, max_bytes=1048576, interval=0.1):
        if type(interval) not in {int, float} or not math.isfinite(interval) or not 0.01 <= interval <= 2:
            raise ValueError("Polling interval must be between 0.01 and 2 seconds")
        cursor = after_seq
        while True:
            # user:“复用原宿主权威”+(按原持久事件游标逐页读取，发布每条前重新检查会话和项目)。
            page = await self.events(session_id, after_seq=cursor, limit=limit, max_bytes=max_bytes)
            for event in page.events:
                await self._admit(session_id)
                self._sessions.get()
                cursor = event["seq"]
                yield event
            if not page.has_more:
                await asyncio.sleep(interval)

    async def _write(self, method, session_id, **kwargs):
        self._scope.acquire()
        try:
            directory = await self._admit(session_id)
            if method == "prompt":
                # user:“复用原宿主权威”+(消息投递采用原会话执行目录快照，缺失时不派发)。
                if not directory.exists:
                    raise SessionControllerError("session-controller/directory-unavailable", "Session execution directory is unavailable")
                kwargs["work_root"] = directory.path
            try:
                # user:“复用原宿主权威”+(写入已派发后等待原操作结算，取消不假定回滚)。
                result = await finish_on_cancel(self._sessions.call(method, session_id, **kwargs), name="scoped-session-" + method)
                await self._admit(session_id)
                self._sessions.get()
                return result
            except asyncio.CancelledError:
                raise
            except Exception:
                raise SessionControllerError("session-controller/write-uncertain", "Session operation may have changed; inspect current state", may_have_changed=True) from None
        finally:
            self._scope.release()

    async def prompt(self, session_id, *, request_id, text, mode="queue"):
        return await self._write("prompt", session_id, request_id=request_id, text=text, mode=mode)

    async def update_queue(self, session_id, queue_item_id, *, text=None, delete=False):
        return await self._write("update_queue", session_id, queue_item_id=queue_item_id, text=text, delete=delete)

    async def cancel(self, session_id, *, turn_id=None):
        return await self._write("cancel", session_id, turn_id=turn_id)

    async def fork(self, session_id, *, checkpoint_id=None, turn_id=None, new_session_id=None, title=""):
        self._scope.acquire()
        try:
            await self._admit(session_id)
            # user:“复用原宿主权威”+(仅用原检查点/回合边界分叉，原操作负责真实提交与取消结算)。
            result = await self._context.checkpoints.fork(session_id, checkpoint_id=checkpoint_id,
                turn_id=turn_id, new_session_id=new_session_id, title=title)
            try:
                await self._admit(session_id)
                await self._admit(result["session_id"])
                self._sessions.get()
            except asyncio.CancelledError:
                raise
            except Exception:
                raise SessionControllerError("session-controller/write-uncertain", "Fork may have been created; inspect current state", may_have_changed=True) from None
            return result
        finally:
            self._scope.release()
