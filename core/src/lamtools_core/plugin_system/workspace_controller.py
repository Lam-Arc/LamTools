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
            binding = self._catalog.binding_token("project.sessions.create")
            try:
                # user:“复用原宿主权威”+(在原项目事务内创建会话，派发后取消等待结算)。
                async def write():
                    self._check_operation("project.sessions.create", binding)
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
                return dict(project)
            except (RuntimeError, ValueError, TypeError, OSError):
                raise WorkspaceControllerError("workspace/host-changed", "Project write completed but binding changed", may_have_changed=True) from None
        finally:
            self._scope.release()
