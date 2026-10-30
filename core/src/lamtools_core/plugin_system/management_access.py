"""user:“继续，把 2 阶段都做完”+(管理门面沿用原操作目录、启停事务及运行档解析，不创建第二个宿主权威)。"""
from .durable_access import _json


class HostOperationError(RuntimeError):
    def __init__(self, code, message, *, status="error", details=None):
        self.code, self.status, self.details = code, status, details or {}
        super().__init__(message)


class PluginManagementAPI:
    def __init__(self, context, scope, domain):
        self._context, self._scope, self._domain = context, scope, domain
        self._catalog = context.resolved_operation_catalog()

    async def _call(self, action, **payload):
        self._scope.acquire()
        try:
            catalog = self._context.resolved_operation_catalog()
            if catalog is not self._catalog:
                raise HostOperationError("host/changed", "Operation catalog changed")
            name = self._domain + "." + action
            if catalog is None or not catalog.has(name):
                raise HostOperationError("host/unavailable", "Required management operation is unavailable")
            try:
                result = await catalog.execute(name, _json(payload), metadata={"source": "plugin-sdk", "plugin": self._scope.owner})
            except Exception:
                raise HostOperationError("host/operation-failed", "Native management operation failed") from None
            body = _json(result.payload)
            if result.status != "ok":
                raise HostOperationError("host/operation-rejected", "Native operation was rejected or requires confirmation", status=result.status, details=body)
            return body
        finally:
            self._scope.release()

    async def list(self):
        return await self._call("list")

    async def resolve(self, name):
        if self._domain != "profile":
            raise HostOperationError("host/invalid-action", "resolve is a profile read operation")
        return await self._call("resolve", name=self._name(name))

    def _name(self, name):
        if type(name) is not str or not name.strip() or len(name) > 256:
            raise HostOperationError("host/invalid-name", "Use a bounded nonblank name")
        return name.strip()

    async def _manage(self, action, name):
        self._scope.check_open()
        if self._domain != "plugin.system":
            raise HostOperationError("host/invalid-action", "Profile interface is read-only")
        name = self._name(name)
        if name == self._scope.owner and action in {"disable", "reload"}:
            raise HostOperationError("host/self-management", "A plugin cannot stop or reload itself from its active call")
        return await self._call(action, name=name)

    async def enable(self, name):
        return await self._manage("enable", name)

    async def disable(self, name):
        return await self._manage("disable", name)

    async def reload(self, name):
        return await self._manage("reload", name)
