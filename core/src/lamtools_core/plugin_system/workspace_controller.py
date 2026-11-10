"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(当前工作区重命名复用原项目CAS和插件作用域)。"""
import asyncio
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
            try:
                # user:“复用原宿主权威”+(已派发项目CAS写入在重复取消时结算，不另造持久权威)。
                result = await finish_on_cancel(self._catalog.execute("project.update",
                    {"project_id": project_id, "name": name, "expected_revision": expected_revision},
                    metadata={"source": "plugin-sdk", "plugin": self._scope.owner}), name="workspace-rename")
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
