"""user:“继续，无人值守模式，不要停下来”+(根代理控制复用原会话存储、接收、回执和循环权威，SDK只拥有受限控制句柄)。"""
import hashlib
import json
from pathlib import Path

from lamtools_core.async_tasks import finish_on_cancel
from lamtools_core.session import SessionRecord
from .session_data import identifier
from .durable_access import _json


class AgentAccessError(RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code, self.may_have_changed = code, may_have_changed
        super().__init__(message)


class PluginAgentsAPI:
    def __init__(self, context, scope):
        self._context, self._scope, self._root = context, scope, Path(context.work_root).resolve()
        self._sessions = context.service("sessions")
        self._store = self._sessions._context().host.session_store if self._sessions is not None else None
        self._prefix = "sdk-agent-" + hashlib.sha256(json.dumps([scope.owner, str(self._root)]).encode()).hexdigest()[:20] + "-"

    def _host(self):
        self._scope.check_open()
        if self._sessions is None or self._store is None:
            raise AgentAccessError("agent/unavailable", "Native desktop sessions and persistent store are required")
        if self._context.service("sessions") is not self._sessions:
            raise AgentAccessError("agent/host-changed", "Session host changed")
        live = self._sessions._context()
        if live.host.session_store is not self._store:
            raise AgentAccessError("agent/host-changed", "Session store changed")
        return live

    async def _record(self, session_id):
        self._host()
        session_id = identifier(session_id)
        if not session_id.startswith(self._prefix):
            raise AgentAccessError("agent/not-found", "Agent is outside this plugin/project namespace")
        record = await self._store.get_readonly(session_id)
        # user:“复用原宿主权威”+(记录读取后复核原宿主与启动代，失效记录不能用于挂接或后续控制)。
        self._host()
        if (record is None or record.metadata.get("sdk_agent_owner") != self._scope.owner
                or Path(record.metadata.get("work_root", "")).resolve() != self._root):
            raise AgentAccessError("agent/not-found", "Agent is unknown or unavailable in the original project")
        return record

    async def create(self, *, request_id, title=""):
        self._scope.acquire()
        attempted = False
        try:
            request_id = identifier(request_id)
            if type(title) is not str or len(title) > 256 or "\x00" in title:
                raise ValueError("Agent title must be bounded text")
            live = self._host()
            from .working_directory import directory_exists
            if not directory_exists(self._root, self._root):
                raise AgentAccessError("agent/missing-project", "The original project must exist before creating an agent")
            session_id = self._prefix + hashlib.sha256(request_id.encode("utf8")).hexdigest()[:32]
            async def create_once():
                nonlocal attempted
                self._host()
                record = await self._store.get_readonly(session_id)
                # user:“复用原宿主权威”+(读取等待期间失效时在写入前拒绝，不能先向旧存储创建孤立记录再报告交接失败)。
                self._host()
                if record is None:
                    try:
                        attempted = True
                        await self._store.create(SessionRecord(session_id, "core", title or "New Session", "idle",
                            metadata={"work_root": str(self._root), "sdk_agent_owner": self._scope.owner}))
                    except ValueError:
                        # A cooperating creator may have committed the same deterministic ID.
                        if await self._store.get_readonly(session_id) is None:
                            raise
                record = await self._record(session_id)
                state = await self._sessions.state(session_id)
                if state.last_event_seq == 0:
                    # Native record creation and event acceptance have separate durable commits.
                    # A crash between them is repaired on the same request_id before returning a handle.
                    attempted = True
                    await self._sessions._execute(live, session_id, "thread.start",
                        {"thread_id": session_id, "title": record.title, "expected_revision": 0})
                return PluginAgentHandle(self, session_id)
            return await finish_on_cancel(live.host.session_actors.run("plugin-agent:" + session_id, create_once), name="plugin-agent-create")
        except Exception:
            if attempted:
                raise AgentAccessError("agent/create-incomplete", "Creation may have committed; retry the same request_id to reconcile the native handoff", may_have_changed=True) from None
            raise
        finally:
            self._scope.release()

    async def attach(self, session_id):
        self._scope.acquire()
        try:
            await self._record(session_id)
            return PluginAgentHandle(self, session_id)
        finally:
            self._scope.release()


class PluginAgentHandle:
    def __init__(self, api, session_id):
        self._api, self.session_id, self._closed = api, session_id, False

    async def _call(self, method, **fields):
        api = self._api
        api._scope.acquire()
        try:
            if self._closed:
                raise AgentAccessError("agent/handle-closed", "This agent handle is disposed; attach a new handle to inspect history")
            await api._record(self.session_id)
            if method == "resume":
                request_id = identifier(fields["request_id"])
                message_id = "sdk-resume-" + hashlib.sha256(request_id.encode("utf8")).hexdigest()
                live = api._host()
                async with live.session_factory() as db:
                    receipt = await live.persistence.find_client_event(db, thread_id=self.session_id,
                        client_message_id=message_id, methods={"turn/started"})
                if receipt is not None:
                    return {"session_id": self.session_id, "deduplicated": True, "event": _json(receipt.to_dict())}
                state = await api._sessions.state(self.session_id)
                if state.running or not state.paused_turn_id:
                    raise AgentAccessError("agent/not-resumable", "Only a committed paused native turn can resume")
                result = await finish_on_cancel(api._sessions._execute(api._host(), self.session_id, "turn.resume",
                    {"thread_id": self.session_id, "turn_id": state.paused_turn_id,
                     "client_message_id": message_id,
                     "work_root": str(api._root), "include_snapshot": False}), name="plugin-agent-resume")
                return _json(result)
            work = getattr(api._sessions, method)(self.session_id, **fields)
            result = await finish_on_cancel(work, name="plugin-agent-control") if method == "cancel" else await work
            if method in {"state", "wait", "events"}:
                api._host()
            return result
        finally:
            api._scope.release()

    async def followup(self, *, request_id, text):
        return await self._call("prompt", request_id=request_id, text=text, mode="queue", work_root=str(self._api._root))

    async def steer(self, *, request_id, text):
        return await self._call("prompt", request_id=request_id, text=text, mode="steer", work_root=str(self._api._root))

    async def resume(self, *, request_id):
        return await self._call("resume", request_id=request_id)

    async def state(self):
        return await self._call("state")

    async def wait(self, *, timeout=30):
        return await self._call("wait", timeout=timeout)

    async def events(self, *, after_seq=0, limit=100, max_bytes=1048576):
        return await self._call("events", after_seq=after_seq, limit=limit, max_bytes=max_bytes)

    async def cancel(self):
        return await self._call("cancel")

    async def dispose(self):
        if self._closed:
            return
        try:
            await self.cancel()
        finally:
            self._closed = True
