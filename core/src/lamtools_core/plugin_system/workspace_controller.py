"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(当前工作区重命名复用原项目CAS和插件作用域)。"""
import asyncio
import copy
import math
from pathlib import Path

from lamtools_core.async_tasks import finish_on_cancel
from .workspace_registry_access import PluginWorkspaceRegistryAPI


class WorkspaceControllerError(RuntimeError):
    def __init__(self, code, message, *, may_have_changed=False):
        self.code, self.may_have_changed = code, may_have_changed
        super().__init__(message)


class PluginWorkspaceController:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._root = Path(context.work_root).resolve()
        self._catalog = context.resolved_operation_catalog()
        self._registry = PluginWorkspaceRegistryAPI(context, scope)

    def _check(self):
        self._scope.check_open()
        if (self._context._registration_scope is not self._scope or Path(self._context.work_root).resolve() != self._root
                or self._context.resolved_operation_catalog() is not self._catalog):
            raise WorkspaceControllerError("workspace/host-changed", "Workspace binding changed")

    def _check_operation(self, name, binding):
        self._check()
        # user:“复用原宿主权威”+(只使用原注册身份，替换或撤回不得发布旧结果)。
        if binding is None or self._catalog.binding_token(name) is not binding or not self._catalog.has(name):
            raise WorkspaceControllerError("workspace/host-changed", "Original workspace operation changed")

    async def create(self, path):
        if type(path) is not str or not path or len(path) > 4096 or "\x00" in path:
            raise ValueError("Use a bounded absolute workspace path")
        try:
            path.encode("utf-8")
            candidate = Path(path)
            if not candidate.is_absolute():
                raise ValueError("Use an absolute workspace path")
            candidate = candidate.resolve()
        except (UnicodeError, OSError, RuntimeError):
            raise ValueError("Use a valid absolute workspace path") from None
        if candidate != self._root:
            raise WorkspaceControllerError("workspace/not-found", "Workspace is outside this project")
        self._scope.acquire()
        try:
            self._check()
            if not candidate.is_dir():
                raise WorkspaceControllerError("workspace/invalid-path", "Workspace directory is unavailable")
            existing = await self._registry.resolve_by_path(str(candidate))
            self._check()
            # user:“逐项核对固定上游源码及手册”+(准入等待后重新验证目录仍存在，不主动重建缺失路径)。
            if not candidate.is_dir():
                raise WorkspaceControllerError("workspace/invalid-path", "Workspace directory is unavailable")
            if existing is not None:
                return {"project": existing, "created": False}
            if self._catalog is None or not self._catalog.has("project.create"):
                raise WorkspaceControllerError("workspace/unavailable", "Original project creation is unavailable")
            binding = self._catalog.binding_token("project.create")
            async def write():
                # user:“复用原宿主权威”+(派发前确认仍是原项目操作，使用原事务创建与判定)。
                self._check()
                if binding is None or self._catalog.binding_token("project.create") is not binding or not self._catalog.has("project.create"):
                    raise WorkspaceControllerError("workspace/host-changed", "Original project creation changed")
                if not candidate.is_dir():
                    raise WorkspaceControllerError("workspace/invalid-path", "Workspace directory is unavailable")
                return await self._catalog.execute("project.create", {"work_root": str(candidate)},
                    metadata={"source": "plugin-sdk", "plugin": self._scope.owner})
            try:
                result = await finish_on_cancel(write(), name="workspace-create")
                self._check()
                if self._catalog.binding_token("project.create") is not binding or not self._catalog.has("project.create"):
                    raise ValueError("Original project creation changed")
                if result.status != "ok" or type(result.payload) is not dict:
                    raise ValueError("Original project creation failed")
                project, created = result.payload.get("project"), result.payload.get("created")
                if (type(project) is not dict or type(project.get("id")) is not str or type(created) is not bool
                        or type(project.get("work_root")) is not str or Path(project["work_root"]).resolve() != self._root):
                    raise ValueError("Original project result invalid")
                confirmed = await self._registry.resolve_by_path(str(candidate))
                self._check()
                if confirmed is None or confirmed.get("id") != project["id"] or self._catalog.binding_token("project.create") is not binding:
                    raise ValueError("Workspace binding changed")
                return {"project": confirmed, "created": created}
            except asyncio.CancelledError:
                raise
            except Exception:
                raise WorkspaceControllerError("workspace/write-uncertain", "Project creation may have changed; inspect current state", may_have_changed=True) from None
        finally:
            self._scope.release()

    async def follow(self, *, interval=0.1):
        if type(interval) not in {int, float} or not math.isfinite(interval) or not 0.01 <= interval <= 2:
            raise ValueError("Polling interval must be between 0.01 and 2 seconds")
        first, previous = True, None
        while True:
            self._check()
            # user:“第二阶段结束后 就继续开展第三阶段”+(按消费节奏读取原当前项目，变化时发布完整快照)。
            project = await self._registry.resolve_by_path(str(self._root))
            self._check()
            if first or project != previous:
                previous = copy.deepcopy(project)
                yield {"kind": "baseline" if first else "snapshot", "project": project}
                first = False
            await asyncio.sleep(interval)

    async def create_session(self, project_id, *, title="New Session"):
        if type(project_id) is not str or not project_id.strip() or len(project_id) > 128:
            raise ValueError("Use a bounded project id")
        if type(title) is not str or len(title) > 256 or "\x00" in title:
            raise ValueError("Use a bounded session title")
        try:
            title.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Use a valid session title") from None
        self._scope.acquire()
        try:
            self._check()
            if await self._registry.get(project_id) is None:
                raise WorkspaceControllerError("workspace/not-found", "Workspace is unavailable in this project")
            self._check()
            if self._catalog is None or not self._catalog.has("project.sessions.create"):
                raise WorkspaceControllerError("workspace/unavailable", "Original session creation is unavailable")
            if not self._catalog.has("project.sessions.get"):
                raise WorkspaceControllerError("workspace/unavailable", "Original session lookup is unavailable")
            binding = self._catalog.binding_token("project.sessions.create")
            read_binding = self._catalog.binding_token("project.sessions.get")
            try:
                # user:“复用原宿主权威”+(在原项目事务内创建会话，派发后取消等待结算)。
                async def write():
                    self._check_operation("project.sessions.create", binding)
                    self._check_operation("project.sessions.get", read_binding)
                    return await self._catalog.execute("project.sessions.create", {"project_id": project_id, "title": title},
                        metadata={"source": "plugin-sdk", "plugin": self._scope.owner})
                result = await finish_on_cancel(write(), name="workspace-session-create")
                self._check_operation("project.sessions.create", binding)
                if result.status != "ok" or type(result.payload) is not dict:
                    raise ValueError("Original creation did not return a session")
                session = result.payload.get("session")
                if (type(session) is not dict or type(session.get("id")) is not str
                        or type(session.get("metadata")) is not dict
                        or Path(session["metadata"].get("work_root", "")).resolve() != self._root
                        or await self._registry.get(project_id) is None):
                    raise ValueError("Session binding changed")
                self._check_operation("project.sessions.create", binding)
                # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(复核真实会话仍归属当前项目且可见，撤回或后续变化不发布旧快照)。
                self._check_operation("project.sessions.get", read_binding)
                lookup = await self._catalog.execute("project.sessions.get", {"project_id": project_id, "session_id": session["id"]},
                    metadata={"source": "plugin-sdk", "plugin": self._scope.owner})
                self._check_operation("project.sessions.create", binding)
                self._check_operation("project.sessions.get", read_binding)
                if lookup.status != "ok" or type(lookup.payload) is not dict or lookup.payload.get("session") != session:
                    raise ValueError("Session changed after creation")
                return dict(session)
            except asyncio.CancelledError:
                raise
            except Exception:
                raise WorkspaceControllerError("workspace/write-uncertain", "Session creation may have changed; inspect current state", may_have_changed=True) from None
        finally:
            self._scope.release()

    async def rename(self, project_id, name, *, expected_revision):
        if type(project_id) is not str or not project_id.strip() or len(project_id) > 128:
            raise ValueError("Use a bounded project id")
        if type(name) is not str or not name.strip() or len(name) > 256 or "\x00" in name:
            raise ValueError("Use a bounded nonblank workspace name")
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("Use a positive project revision")
        self._scope.acquire()
        try:
            self._check()
            if await self._registry.get(project_id) is None:
                raise WorkspaceControllerError("workspace/not-found", "Workspace is unavailable in this project")
            self._check()
            if self._catalog is None or not self._catalog.has("project.update"):
                raise WorkspaceControllerError("workspace/unavailable", "Original project operation is unavailable")
            binding = self._catalog.binding_token("project.update")
            try:
                # user:“复用原宿主权威”+(已派发项目CAS写入在重复取消时结算，不另造持久权威)。
                async def write():
                    self._check_operation("project.update", binding)
                    return await self._catalog.execute("project.update", {"project_id": project_id, "name": name, "expected_revision": expected_revision},
                        metadata={"source": "plugin-sdk", "plugin": self._scope.owner})
                result = await finish_on_cancel(write(), name="workspace-rename")
                self._check_operation("project.update", binding)
            except asyncio.CancelledError:
                raise
            except Exception:
                raise WorkspaceControllerError("workspace/write-failed", "Original project write failed", may_have_changed=True) from None
            if result.status != "ok":
                error = result.payload.get("error", "") if type(result.payload) is dict else ""
                code = "workspace/conflict" if str(error).startswith("REVISION_CONFLICT:") else "workspace/rejected"
                # user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(除原CAS冲突外，未分类的派发后错误不能假定没有提交)。
                raise WorkspaceControllerError(code, "Original project write was rejected", may_have_changed=code != "workspace/conflict")
            try:
                self._check()
                project = result.payload.get("project")
                if (type(project) is not dict or project.get("id") != project_id
                        or Path(project.get("work_root", "")).resolve() != self._root):
                    raise ValueError("Unexpected project result")
                # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(提交后复核原项目记录，避免发布已删除或被后续写入覆盖的旧结果)。
                current = await self._registry.get(project_id)
                self._check_operation("project.update", binding)
                if current is None or current != project:
                    raise ValueError("Project changed after write")
                return dict(current)
            except (RuntimeError, ValueError, TypeError, OSError):
                raise WorkspaceControllerError("workspace/host-changed", "Project write completed but binding changed", may_have_changed=True) from None
        finally:
            self._scope.release()

    async def pin_session(self, session_id):
        return await self._change_pin(session_id, pin=True)

    async def unpin_session(self, session_id):
        return await self._change_pin(session_id, pin=False)

    async def insert_session_before(self, session_id, before_session_id=None):
        if type(session_id) is not str or not session_id or len(session_id) > 128 or "\x00" in session_id:
            raise ValueError("Use a bounded session id")
        if before_session_id is not None and (
            type(before_session_id) is not str or not before_session_id
            or len(before_session_id) > 128 or "\x00" in before_session_id
        ):
            raise ValueError("Use a bounded before_session_id")
        for value in (session_id, before_session_id):
            if value is not None:
                try:
                    value.encode("utf-8")
                except UnicodeEncodeError:
                    raise ValueError("Use valid session ids") from None
        mutation, read = "project.sessions.insert_before", "project.sessions.list"
        self._scope.acquire()
        try:
            self._check()
            project = await self._registry.resolve_by_path(str(self._root))
            self._check()
            if project is None:
                raise WorkspaceControllerError("workspace/not-found", "Workspace is unavailable in this project")
            project_id = project.get("id")
            if type(project_id) is not str or not project_id:
                raise WorkspaceControllerError("workspace/invalid-result", "Original project identity is invalid")
            if self._catalog is None or any(not self._catalog.has(name) for name in (mutation, read)):
                raise WorkspaceControllerError("workspace/unavailable", "Original project session ordering is unavailable")
            mutation_binding = self._catalog.binding_token(mutation)
            read_binding = self._catalog.binding_token(read)
            try:
                async def write():
                    self._check_operation(mutation, mutation_binding)
                    payload = {"project_id": project_id, "session_id": session_id}
                    if before_session_id is not None:
                        payload["before_session_id"] = before_session_id
                    return await self._catalog.execute(
                        mutation, payload,
                        metadata={"source": "plugin-sdk", "plugin": self._scope.owner},
                    )
                result = await finish_on_cancel(write(), name="workspace-session-order")
                self._check_operation(mutation, mutation_binding)
            except asyncio.CancelledError:
                raise
            except Exception:
                raise WorkspaceControllerError(
                    "workspace/write-uncertain", "Session order may have changed; inspect current order", may_have_changed=True
                ) from None
            if result.status != "ok" or type(result.payload) is not dict:
                error = result.payload if type(result.payload) is dict else {}
                code = error.get("code")
                if code not in {"workspace/move-invalid", "workspace/not-found"}:
                    code = "workspace/rejected"
                raise WorkspaceControllerError(code, "Original session order operation was rejected")

            # user:“真实请求、错误、作用域、取消/流和清理”+(写后重读原项目会话顺序，并拒绝发布过时结果)。
            from .session_controller import _cancel_owned_read

            async def read_current():
                self._check_operation(read, read_binding)
                current = await self._catalog.execute(
                    read, {"project_id": project_id},
                    metadata={"source": "plugin-sdk", "plugin": self._scope.owner},
                )
                self._check_operation(read, read_binding)
                self._check_operation(mutation, mutation_binding)
                if current.status != "ok" or type(current.payload) is not dict:
                    raise ValueError("Original session order is unavailable")
                sessions = current.payload.get("sessions")
                if type(sessions) is not list or any(type(row) is not dict or type(row.get("id")) is not str for row in sessions):
                    raise ValueError("Original session order is invalid")
                ids = [row["id"] for row in sessions]
                if session_id not in ids:
                    raise ValueError("Moved session is no longer visible")
                if before_session_id is None:
                    if ids[-1] != session_id:
                        raise ValueError("Moved session is no longer last")
                elif before_session_id != session_id and ids.index(session_id) + 1 != ids.index(before_session_id):
                    raise ValueError("Session anchor ordering changed")
                if await self._registry.get(project_id) is None:
                    raise ValueError("Workspace changed after session ordering")
                self._check_operation(mutation, mutation_binding)
                self._check_operation(read, read_binding)
                return ids

            try:
                session_ids = await _cancel_owned_read(read_current(), name="workspace-session-order-revalidation")
                return {"session_ids": session_ids}
            except asyncio.CancelledError:
                raise
            except Exception:
                raise WorkspaceControllerError(
                    "workspace/host-changed", "Session order changed after commit", may_have_changed=True
                ) from None
        finally:
            self._scope.release()

    async def _change_pin(self, session_id, *, pin):
        if type(session_id) is not str or not session_id or len(session_id) > 128 or "\x00" in session_id:
            raise ValueError("Use a bounded session id")
        try:
            session_id.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Use a valid session id") from None
        mutation = "project.sessions.pin" if pin else "project.sessions.unpin"
        read = "project.sessions.pinned"
        self._scope.acquire()
        try:
            self._check()
            project = await self._registry.resolve_by_path(str(self._root))
            self._check()
            if project is None:
                raise WorkspaceControllerError("workspace/not-found", "Workspace is unavailable in this project")
            project_id = project.get("id")
            if type(project_id) is not str or not project_id:
                raise WorkspaceControllerError("workspace/invalid-result", "Original project identity is invalid")
            if self._catalog is None or any(not self._catalog.has(name) for name in (mutation, read)):
                raise WorkspaceControllerError("workspace/unavailable", "Original project session pin store is unavailable")
            mutation_binding = self._catalog.binding_token(mutation)
            read_binding = self._catalog.binding_token(read)
            try:
                async def write():
                    self._check_operation(mutation, mutation_binding)
                    return await self._catalog.execute(mutation, {"project_id": project_id, "session_id": session_id},
                        metadata={"source": "plugin-sdk", "plugin": self._scope.owner})
                result = await finish_on_cancel(write(), name="workspace-session-pin" if pin else "workspace-session-unpin")
                self._check_operation(mutation, mutation_binding)
            except asyncio.CancelledError:
                raise
            except Exception:
                raise WorkspaceControllerError("workspace/write-uncertain", "Session pin state may have changed; inspect current state", may_have_changed=True) from None
            if result.status != "ok" or type(result.payload) is not dict:
                error = result.payload.get("error", "") if type(result.payload) is dict else ""
                if "Session not found" in str(error):
                    raise WorkspaceControllerError("session/not-found", "Session is unavailable in this project")
                raise WorkspaceControllerError("workspace/rejected", "Original session pin operation was rejected")
            # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(提交后重读原Core置顶集合，不能发布已失效项目或过时列表)。
            from .session_controller import _cancel_owned_read

            async def read_current():
                self._check_operation(read, read_binding)
                current = await self._catalog.execute(read, {"project_id": project_id},
                    metadata={"source": "plugin-sdk", "plugin": self._scope.owner})
                self._check_operation(read, read_binding)
                if current.status != "ok" or type(current.payload) is not dict:
                    raise ValueError("Original session pin state is unavailable")
                ids = current.payload.get("pinned_session_ids")
                if type(ids) is not list or any(type(value) is not str for value in ids):
                    raise ValueError("Original session pin state is invalid")
                if await self._registry.get(project_id) is None:
                    raise ValueError("Workspace changed after pin update")
                self._check_operation(mutation, mutation_binding)
                self._check_operation(read, read_binding)
                return list(ids)

            try:
                pinned_ids = await _cancel_owned_read(read_current(), name="workspace-session-pin-revalidation")
                if pin and session_id not in pinned_ids:
                    raise ValueError("Session pin did not persist")
                return {"pinned_session_ids": pinned_ids}
            except asyncio.CancelledError:
                raise
            except Exception:
                raise WorkspaceControllerError("workspace/host-changed", "Session pin state changed after commit", may_have_changed=True) from None
        finally:
            self._scope.release()
