"""user:“第二阶段结束后 就继续开展第三阶段”+(会话只读复用原可见性和项目身份)。"""
import asyncio
import copy
import hashlib
import math
from pathlib import Path

from lamtools_core.async_tasks import finish_on_cancel

from .sessions import SESSIONS


class SessionControllerError(RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code, self.may_have_changed = code, may_have_changed
        super().__init__(message)


async def _cancel_owned_read(work, *, name):
    task = asyncio.create_task(work, name=name)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        task.cancel()
        async def join_read():
            await asyncio.gather(task, return_exceptions=True)
        # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(重复取消等待原只读调用和准入清理后释放租约)。
        await finish_on_cancel(join_read(), name=name + "-cleanup")
        raise


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
        async def read_owned():
            self._scope.acquire()
            try:
                # user:“复用原宿主权威”+(只读前后均重新检查原会话可见性和项目，失效不发布旧结果)。
                await self._admit(session_id)
                result = await self._sessions.call(method, session_id, **kwargs)
                await self._admit(session_id)
                self._sessions.get()
                return result
            finally:
                self._scope.release()
        return await _cancel_owned_read(read_owned(), name="scoped-session-read-" + method)

    async def state(self, session_id):
        return await self._read("state", session_id)

    async def observe_state(self, session_id, *, interval=0.1):
        if type(interval) not in {int, float} or not math.isfinite(interval) or not 0.01 <= interval <= 2:
            raise ValueError("Polling interval must be between 0.01 and 2 seconds")
        previous = None
        while True:
            # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(只按消费节奏读取原可见会话状态，变化时发布完整快照)。
            current = await self.state(session_id)
            if current != previous:
                previous = current
                yield current
            await asyncio.sleep(interval)

    async def observe_projections(self, session_id, *, interval=0.1):
        if type(interval) not in {int, float} or not math.isfinite(interval) or not 0.01 <= interval <= 2:
            raise ValueError("Polling interval must be between 0.01 and 2 seconds")
        source = self._context.require_service("session_data")
        projection = self._context.session_projections
        previous = None
        async def read_projection():
            # user:“复用原宿主权威”+(复用原投影读取及会话准入，不能发布被替换提供方的旧结果)。
            self._check()
            if self._context.service("session_data") is not source:
                raise SessionControllerError("session-controller/host-changed", "Projection provider changed")
            await self._admit(session_id)
            current = await projection.get(session_id)
            self._check()
            if self._context.service("session_data") is not source:
                raise SessionControllerError("session-controller/host-changed", "Projection provider changed")
            return current
        while True:
            current = await _cancel_owned_read(read_projection(), name="scoped-session-projection-read")
            if current != previous:
                previous = copy.deepcopy(current)
                yield current
            await asyncio.sleep(interval)

    async def events(self, session_id, *, after_seq=0, limit=100, max_bytes=1048576):
        return await self._read("events", session_id, after_seq=after_seq, limit=limit, max_bytes=max_bytes)

    async def observe_events(self, session_id, *, interval=0.1):
        if type(interval) not in {int, float} or not math.isfinite(interval) or not 0.01 <= interval <= 2:
            raise ValueError("Polling interval must be between 0.01 and 2 seconds")
        # user:“复用原宿主权威”+(先准入可见会话并记录原持久事件末尾，再只观察后续事件)。
        current = await self.state(session_id)
        stream = self.follow(session_id, after_seq=current.last_event_seq, interval=interval)
        try:
            yield {"kind": "ready", "after_seq": current.last_event_seq}
            while True:
                pull = asyncio.create_task(anext(stream))
                try:
                    event = await asyncio.shield(pull)
                except StopAsyncIteration:
                    break
                except asyncio.CancelledError:
                    pull.cancel()
                    async def join_pull():
                        await asyncio.gather(pull, return_exceptions=True)
                    # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(重复取消仍等待原事件读取退出和清理)。
                    await finish_on_cancel(join_pull(), name="session-observe-event-pull-close")
                    raise
                yield {"kind": "event", "event": event}
        finally:
            await finish_on_cancel(stream.aclose(), name="session-observe-event-close")

    async def wait(self, session_id, *, timeout=30):
        return await self._read("wait", session_id, timeout=timeout)

    async def wait_with_output(self, session_id, *, timeout=30, after_seq=0, max_messages=10):
        if type(after_seq) is not int or not 0 <= after_seq <= 2**63 - 1:
            raise ValueError("after_seq must be a non-negative event sequence")
        if type(max_messages) is not int or not 1 <= max_messages <= 20:
            raise ValueError("max_messages must be between 1 and 20")
        async def read_output():
            result = await self.wait(session_id, timeout=timeout)
            through = result.state.last_event_seq
            if after_seq > through:
                raise ValueError("after_seq exceeds the stopping event sequence")
            cursor, scanned, matches = after_seq, 0, {}
            # user:“复用原宿主权威”+(仅提取停止位置之前原持久事件中完成的助手文本，限制扫描和返回量)。
            while cursor < through and scanned < 2000:
                before = cursor
                page = await self.events(session_id, after_seq=cursor, limit=min(100, 2000 - scanned))
                if not page.events:
                    break
                for event in page.events:
                    seq = event.get("seq")
                    if type(seq) is not int or seq <= cursor or seq > through:
                        break
                    cursor, scanned = seq, scanned + 1
                    outer = event.get("payload")
                    inner = outer.get("payload") if type(outer) is dict else None
                    if (event.get("method") == "core/runItem" and type(outer) is dict
                            and outer.get("kind") == "message" and outer.get("status") == "completed"
                            and type(inner) is dict and inner.get("type") == "agentMessage"
                            and type(inner.get("content")) is str):
                        text = inner["content"]
                        item_id = event.get("item_id")
                        key = ("item", item_id) if type(item_id) is str and item_id else ("event", seq)
                        # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(同一原消息的后续完成事件替换旧版本)。
                        matches.pop(key, None)
                        matches[key] = {"seq": seq, "text": text[:4096], "text_truncated": len(text) > 4096}
                # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(提供方未推进游标时停止并明确不完整)。
                if cursor == before or cursor >= through or not page.has_more:
                    break
            await self._admit(session_id)
            self._sessions.get()
            complete = cursor >= through
            return {"reason": result.reason, "state": result.state, "messages": list(reversed(list(matches.values())[-max_messages:])),
                    "truncated": len(matches) > max_messages or not complete,
                    "scan_complete": complete, "next_after_seq": None if complete else cursor}
        return await _cancel_owned_read(read_output(), name="scoped-session-wait-output")

    async def search_project(self, project_id, query, *, scan_limit=10, cursor=None):
        # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(项目扫描及历史读取均需等待取消清理)。
        return await _cancel_owned_read(self._search_project(project_id, query, scan_limit=scan_limit, cursor=cursor),
                                        name="scoped-project-history-search")

    async def _search_project(self, project_id, query, *, scan_limit, cursor):
        if type(query) is not str or not query.strip() or len(query) > 256:
            raise ValueError("Use a nonempty query of at most 256 characters")
        try:
            query.encode("utf-8")
        except UnicodeError:
            raise ValueError("Use valid Unicode text") from None
        if type(scan_limit) is not int or not 1 <= scan_limit <= 20:
            raise ValueError("scan_limit must be between 1 and 20")
        self._scope.acquire()
        try:
            host = self._sessions.get()._context().host
            store = getattr(host, "runtime_state_store", None)
            if not callable(getattr(store, "read_history_page", None)):
                raise SessionControllerError("session-controller/unavailable", "Native history search is unavailable")
            registry = self._context.workspace_registry
            # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(复用原有界游标并绑定搜索词，不将词明文放入游标)。
            binding = ("history-search", hashlib.sha256(query.encode("utf-8")).digest())
            page = await registry._sessions_page(project_id, limit=scan_limit, cursor=cursor, binding=binding)
            items = []
            for row in page.items:
                # user:“复用原宿主权威”+(每个当前项目会话只返回原历史的一条用户或助手命中)。
                result = await self.search_archive(row.session_id, query, limit=1)
                if result["matches"]:
                    items.append({"session_id": row.session_id, "match": result["matches"][0]})
            if await registry.get(project_id) is None:
                raise SessionControllerError("session-controller/not-found", "Project is unavailable")
            # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(项目复核等待结束后再检查每条命中的会话范围)。
            for item in items:
                await self._admit(item["session_id"])
            # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(跨会话汇总不能混用被替换的原历史提供方)。
            current = self._sessions.get()._context().host
            if current is not host or getattr(current, "runtime_state_store", None) is not store:
                raise SessionControllerError("session-controller/host-changed", "History provider changed")
            return {"items": items, "next_cursor": page.next_cursor, "has_more": page.has_more}
        finally:
            self._scope.release()

    async def search_archive(self, session_id, query, *, limit=10, after_seq=0):
        # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(搜索取消时等待原历史读取和作用域清理)。
        return await _cancel_owned_read(self._search_archive(session_id, query, limit=limit, after_seq=after_seq),
                                        name="scoped-session-history-search")

    async def _search_archive(self, session_id, query, *, limit, after_seq):
        from lamtools_core.tool.context_history import HistoryAccess, _search

        if type(query) is not str or not query.strip() or len(query) > 256:
            raise ValueError("Use a nonempty query of at most 256 characters")
        try:
            query.encode("utf-8")
        except UnicodeError:
            raise ValueError("Use valid Unicode text") from None
        self._scope.acquire()
        try:
            await self._admit(session_id)
            host = self._sessions.get()._context().host
            store = getattr(host, "runtime_state_store", None)
            if not callable(getattr(store, "read_history_page", None)):
                raise SessionControllerError("session-controller/unavailable", "Native history search is unavailable")
            controller = self

            class ScopedHistory(HistoryAccess):
                async def page(self, cursor, page_limit):
                    rows = await super().page(cursor, page_limit)
                    # user:“第二阶段结束后 就继续开展第三阶段”+(每页后复核原会话和历史提供方，只搜索用户及助手文本)。
                    await controller._admit(session_id)
                    current = controller._sessions.get()._context().host
                    if current is not host or getattr(current, "runtime_state_store", None) is not store:
                        raise SessionControllerError("session-controller/host-changed", "History provider changed")
                    return [{key: value for key, value in row.items() if key != "tool_calls"}
                            if row.get("role") in {"user", "assistant"}
                            else {"role": "excluded", "metadata": row.get("metadata", {})} for row in rows]

            result = await _search(ScopedHistory(store, session_id, []),
                                   {"query": query, "limit": limit, "after_seq": after_seq})
            await self._admit(session_id)
            current = self._sessions.get()._context().host
            if current is not host or getattr(current, "runtime_state_store", None) is not store:
                raise SessionControllerError("session-controller/host-changed", "History provider changed")
            return result
        finally:
            self._scope.release()

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
            # user:“我不是很早之前就决策说要把它取消掉 删掉了吗”+(分叉只按回合边界，
            # 检查点入口已移除；原操作负责真实提交与取消结算)。
            if checkpoint_id:
                raise SessionControllerError("session-controller/invalid-boundary", "Checkpoints are no longer supported; pass turn_id")
            result = await self._context.checkpoints.fork(session_id, turn_id=turn_id,
                new_session_id=new_session_id, title=title)
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
