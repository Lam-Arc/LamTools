"""user:“继续”+(子代理沿用原监督器/邮箱，插件只能通过门面操作自己的持久成员，不新建执行所有者)。"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from lamtools_core.async_tasks import finish_on_cancel
from .durable_access import _json
from .sessions import SessionError


class SubagentAccessError(RuntimeError):
    def __init__(self, code, message, *, details=None, may_have_changed=False):
        self.code, self.details, self.may_have_changed = code, details or {}, may_have_changed
        super().__init__(message)


def _identifier(value):
    if type(value) is not str or not value.strip() or len(value) > 256 or "\x00" in value:
        raise SubagentAccessError("subagent/invalid-id", "Use a bounded nonempty identifier")
    return value


_PUBLIC = frozenset({"parent_thread_id", "type", "model_id", "reasoning_level", "status", "summary",
                     "sub_session_id", "started_at", "completed_at", "elapsed_ms", "lifecycle_action",
                     "accepted", "deduplicated", "message_id", "delivery_mode", "execution_directory"})


class PluginSubagentAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._root = Path(context.work_root).resolve()
        self._catalog, self._sessions = context.resolved_operation_catalog(), context.service("sessions")
        self._store = None
        self._prefix = "p_" + hashlib.sha256(json.dumps([scope.owner, str(self._root)]).encode()).hexdigest()[:24] + "_"

    def _name(self, name):
        if type(name) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name):
            raise SubagentAccessError("subagent/invalid-name", "Use a lowercase member name of at most32 letters/digits/underscores")
        return self._prefix + name

    def _public(self, row):
        name = row.get("name") if isinstance(row, dict) else None
        if type(name) is not str or not name.startswith(self._prefix):
            raise SubagentAccessError("subagent/foreign-member", "Native response is outside this plugin namespace", may_have_changed=True)
        return {key: value for key, value in row.items() if key in _PUBLIC} | {"name": name[len(self._prefix):], "native_name": name}

    async def _call(self, action, parent, **fields):
        self._scope.acquire()
        mutation = action != "list"
        try:
            parent = _identifier(parent)
            if ":sub:" in parent:
                raise SubagentAccessError("subagent/invalid-parent", "This facade controls members of a root session only")
            if self._catalog is not self._context.resolved_operation_catalog() or self._sessions is not self._context.service("sessions"):
                raise SubagentAccessError("subagent/host-changed", "Subagent host changed")
            operation = "sub_agent." + action
            if self._catalog is None or not self._catalog.has(operation) or self._sessions is None:
                raise SubagentAccessError("subagent/unavailable", "Required native subagent operation is unavailable")
            host = self._sessions._context().host
            store = getattr(host, "session_store", None)
            if self._store is None:
                self._store = store
            if store is not self._store:
                raise SubagentAccessError("subagent/host-changed", "Parent session store changed")
            read = getattr(store, "get_readonly", None)
            if not callable(read):
                raise SubagentAccessError("subagent/unavailable", "Host has no read-only parent visibility check")
            try:
                record = await read(parent)
            except Exception:
                raise SubagentAccessError("subagent/read-failed", "Parent visibility read failed") from None
            if record is None:
                raise SubagentAccessError("subagent/not-found", "Parent session is unknown or unavailable")
            root = record.metadata.get("work_root")
            if type(root) is not str or Path(root).resolve() != self._root:
                raise SubagentAccessError("subagent/project-mismatch", "Parent belongs to another project")
            self._scope.check_open()
            work = self._catalog.execute(operation, {"thread_id": parent, "work_root": str(self._root), **fields},
                metadata={"source": "plugin-sdk", "plugin": self._scope.owner})
            try:
                result = await finish_on_cancel(work, name="plugin-subagent-operation") if mutation else await work
            except Exception:
                raise SubagentAccessError("subagent/operation-failed", "Native subagent operation failed; inspect member state before retrying", may_have_changed=mutation) from None
            if result.status != "ok":
                try:
                    details = _json(result.payload)
                except Exception:
                    raise SubagentAccessError("subagent/invalid-result", "Native rejection is not bounded JSON", may_have_changed=mutation) from None
                raise SubagentAccessError("subagent/rejected", "Native supervisor rejected the request", details=details, may_have_changed=mutation)
            try:
                if action == "list":
                    rows = result.payload["items"]
                    if type(rows) is not list or any(type(row) is not dict or type(row.get("name")) is not str for row in rows):
                        raise ValueError("Invalid native member list")
                    body = {"items": [self._public(row) for row in rows if isinstance(row, dict)
                                      and type(row.get("name")) is str and row["name"].startswith(self._prefix)]}
                else:
                    body = self._public(result.payload)
                return _json(body)
            except SubagentAccessError:
                raise
            except Exception:
                raise SubagentAccessError("subagent/invalid-result", "Native member result is not supported bounded JSON", may_have_changed=mutation) from None
        except SessionError as error:
            raise SubagentAccessError("subagent/closed" if error.code == "session/closed" else "subagent/host-changed", "Session host is unavailable") from None
        finally:
            self._scope.release()

    async def list(self, parent_session_id):
        return await self._call("list", parent_session_id)

    async def get(self, parent_session_id, name):
        encoded = self._name(name)
        rows = (await self.list(parent_session_id))["items"]
        row = next((row for row in rows if row["native_name"] == encoded), None)
        if row is None:
            raise SubagentAccessError("subagent/not-found", "No member in this plugin namespace")
        return row

    async def create(self, parent_session_id, name, *, kind, model, reasoning_level):
        # user:“给我把 2 阶段做完，前端除外”+(创建时捕获父会话持久执行目录，已有成员由原监督器保留原目录)。
        directory = await self._context.working_directory.get(parent_session_id)
        if not directory.exists:
            raise SubagentAccessError("subagent/missing-directory", "Parent execution directory is unavailable")
        return await self._call("create", parent_session_id, name=self._name(name), type=_identifier(kind),
                                model=_identifier(model), reasoning_level=_identifier(reasoning_level), execution_directory=directory.path)

    async def message(self, parent_session_id, name, *, request_id, text):
        self._scope.check_open()
        request_id = _identifier(request_id)
        try:
            if type(text) is not str or not text.strip() or "\x00" in text or len(text.encode("utf-8")) > 65536:
                raise ValueError
        except (ValueError, UnicodeError):
            raise SubagentAccessError("subagent/invalid-message", "Message must be nonempty UTF-8 text up to64KiB") from None
        row = await self.get(parent_session_id, name)
        call_id = "plugin_" + hashlib.sha256(json.dumps([self._prefix, parent_session_id, name, request_id]).encode()).hexdigest()
        return await self._call("message", parent_session_id, name=row["native_name"], type=row["type"], prompt=text, call_id=call_id)

    async def close(self, parent_session_id, name):
        self._scope.check_open()
        row = await self.get(parent_session_id, name)
        from lamtools_core.sub_agent_supervisor import current_child_identity
        identity = current_child_identity()
        if identity is not None and identity[0].parent_thread_id == parent_session_id and identity[2] == row["native_name"]:
            raise SubagentAccessError("subagent/self-close", "A member cannot join its own running task")
        return await self._call("close", parent_session_id, name=row["native_name"], type=row["type"],
                                model=row["model_id"], reasoning_level=row["reasoning_level"])

    async def interrupt(self, parent_session_id, name):
        # user:“继续”+(只中断当前插件自己的一个成员，不调用父会话的整组停止)。
        self._scope.check_open()
        row = await self.get(parent_session_id, name)
        from lamtools_core.sub_agent_supervisor import current_child_identity
        identity = current_child_identity()
        if identity is not None and identity[0].parent_thread_id == parent_session_id and identity[2] == row["native_name"]:
            raise SubagentAccessError("subagent/self-interrupt", "A member cannot interrupt and join itself")
        return await self._call("interrupt_member", parent_session_id, name=row["native_name"])

    async def resume(self, parent_session_id, name):
        # user:“继续”+(恢复仅针对已中断成员，实际的历史和运行身份继续由原监督器验证)。
        self._scope.check_open()
        row = await self.get(parent_session_id, name)
        return await self._call("resume_member", parent_session_id, name=row["native_name"])
