"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(原项目读取限定当前插件项目并检查启动代)。"""
from pathlib import Path


class WorkspaceRegistryError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class PluginWorkspaceRegistryAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._root = Path(context.work_root).resolve()
        self._catalog = context.resolved_operation_catalog()

    def _check(self):
        self._scope.check_open()
        if (self._context._registration_scope is not self._scope
                or Path(self._context.work_root).resolve() != self._root
                or self._context.resolved_operation_catalog() is not self._catalog):
            raise WorkspaceRegistryError("workspace-registry/host-changed", "Workspace binding changed")

    async def get(self, project_id):
        if type(project_id) is not str or not project_id.strip() or len(project_id) > 128:
            raise ValueError("project_id must be a nonblank string of at most 128 characters")
        self._scope.acquire()
        try:
            self._check()
            if self._catalog is None or not self._catalog.has("project.get"):
                raise WorkspaceRegistryError("workspace-registry/unavailable", "Native project lookup is unavailable")
            binding = self._catalog.binding_token("project.get")
            result = await self._catalog.execute("project.get", {"project_id": project_id},
                metadata={"source": "plugin-sdk", "plugin": self._scope.owner})
            # user:“复用原宿主权威”+(等待后重新检查当前项目、原操作目录和启动代；其他项目不可见)。
            self._check()
            # user:“复用原宿主权威”+(原项目操作重注册后不发布旧查询结果)。
            if binding is None or self._catalog.binding_token("project.get") is not binding or not self._catalog.has("project.get"):
                raise WorkspaceRegistryError("workspace-registry/host-changed", "Native project lookup changed")
            if result.status != "ok":
                if result.status == "error" and result.payload == {"error": "Project not found"}:
                    return None
                raise WorkspaceRegistryError("workspace-registry/rejected", "Native project lookup failed")
            project = result.payload.get("project") if type(result.payload) is dict else None
            if type(project) is not dict or type(project.get("work_root")) is not str:
                raise WorkspaceRegistryError("workspace-registry/invalid-result", "Native project result is invalid")
            if Path(project["work_root"]).resolve() != self._root:
                return None
            return dict(project)
        finally:
            self._scope.release()

    async def resolve_by_path(self, path):
        if type(path) is not str or not path or len(path) > 4096 or "\x00" in path or not Path(path).is_absolute():
            raise ValueError("path must be a bounded absolute path")
        self._scope.acquire()
        try:
            self._check()
            if Path(path).resolve() != self._root:
                return None
            if self._catalog is None or not self._catalog.has("project.resolve"):
                raise WorkspaceRegistryError("workspace-registry/unavailable", "Native project lookup is unavailable")
            binding = self._catalog.binding_token("project.resolve")
            result = await self._catalog.execute("project.resolve", {"work_root": str(self._root)},
                metadata={"source": "plugin-sdk", "plugin": self._scope.owner})
            # user:“复用原宿主权威”+(等待原只读查询后再次检查根、目录和启动代)。
            self._check()
            # user:“复用原宿主权威”+(同名替换原目录解析器后拒绝旧结果)。
            if binding is None or self._catalog.binding_token("project.resolve") is not binding or not self._catalog.has("project.resolve"):
                raise WorkspaceRegistryError("workspace-registry/host-changed", "Native project lookup changed")
            if result.status != "ok" or type(result.payload) is not dict:
                raise WorkspaceRegistryError("workspace-registry/rejected", "Native project lookup failed")
            project = result.payload.get("project")
            if project is None:
                return None
            if type(project) is not dict or type(project.get("work_root")) is not str:
                raise WorkspaceRegistryError("workspace-registry/invalid-result", "Native project result is invalid")
            if Path(project["work_root"]).resolve() != self._root:
                raise WorkspaceRegistryError("workspace-registry/invalid-result", "Native project root changed")
            return dict(project)
        finally:
            self._scope.release()

    async def sessions(self, project_id, *, limit=50, cursor=None):
        return await self._sessions_page(project_id, limit=limit, cursor=cursor, binding=None)

    async def _sessions_page(self, project_id, *, limit, cursor, binding):
        self._scope.acquire()
        try:
            self._check()
            if await self.get(project_id) is None:
                raise WorkspaceRegistryError("workspace-registry/not-found", "Workspace is unavailable in this project")
            self._check()
            host = self._context.service("session_query")
            if host is None or not callable(getattr(host, "query", None)):
                raise WorkspaceRegistryError("workspace-registry/unavailable", "Native bounded session query is unavailable")
            # user:“复用原宿主权威”+(只用固定项目根过滤原可见会话扫描，游标绑定项目与插件代)。
            # user:“建立真实请求、错误、作用域、取消/流和清理验收”+(不同搜索词的分页游标不能互用)。
            owner = (self._scope.owner, self._scope.epoch, project_id) if binding is None else (self._scope.owner, self._scope.epoch, project_id, binding)
            result = await host.query(owner, limit=limit, cursor=cursor,
                                      title_contains="", project_root=str(self._root))
            self._check()
            if self._context.service("session_query") is not host:
                raise WorkspaceRegistryError("workspace-registry/host-changed", "Session query provider changed")
            if await self.get(project_id) is None:
                raise WorkspaceRegistryError("workspace-registry/not-found", "Workspace is unavailable in this project")
            self._check()
            if self._context.service("session_query") is not host:
                raise WorkspaceRegistryError("workspace-registry/host-changed", "Session query provider changed")
            return result
        finally:
            self._scope.release()
