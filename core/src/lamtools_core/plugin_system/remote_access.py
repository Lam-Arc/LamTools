"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(仅列当前插件实际受管Remote方法，不伪造Peer权限决策)。"""
import copy

from .capabilities import CapabilityError
from .management_access import HostOperationError
from .operation_bridge import read_operations
from .plugin_http import read_http_routes
from .remote_gateway import read_remote_methods


class PluginRemoteAccess:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._catalog = context.resolved_operation_catalog()
        self._host = getattr(self._catalog, "plugin_system_host", None)

    def _check(self):
        self._scope.check_open()
        if (self._context._registration_scope is not self._scope
                or self._context.resolved_operation_catalog() is not self._catalog
                or getattr(self._catalog, "plugin_system_host", None) is not self._host):
            raise HostOperationError("host/changed", "Original Remote host binding changed")
        if self._host is None or self._catalog is None:
            raise HostOperationError("host/unavailable", "Original Remote host is unavailable")
        if not self._host.available(self._scope.owner):
            raise HostOperationError("host/unavailable", "Plugin is unavailable")

    def declared_methods(self):
        self._check()
        manifest = self._host.get(self._scope.owner)
        if manifest is None:
            raise HostOperationError("host/unavailable", "Plugin is unavailable")
        declaration = copy.deepcopy(manifest.raw)
        try:
            methods = read_remote_methods(manifest)
            routes = {route.path: route for route in read_http_routes(manifest) if route.method == "POST"}
            specs = {spec.name: spec for spec in read_operations(manifest)}
        except (ValueError, TypeError, CapabilityError, UnicodeError, RecursionError):
            raise HostOperationError("host/invalid-declaration", "Remote declaration is invalid") from None
        result = []
        for (namespace, method), (path, _, encoding) in methods.items():
            route = routes[path]
            spec = specs.get(route.operation)
            # user:“复用原宿主权威”+(只列原目录已挂载、同插件所有且无需交互审批的明确方法；资源授权仍由处理器负责)。
            if spec is not None and spec.permission == "auto_allow" and self._catalog.owner_of(route.operation) == "plugin:" + self._scope.owner and self._catalog.has(route.operation):
                result.append({"namespace": namespace, "method": method, "result_encoding": encoding})
        self._check()
        current = self._host.get(self._scope.owner)
        # user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(读取期间声明被撤回时不发布旧方法清单)。
        if current is None or current.raw != declaration:
            raise HostOperationError("host/changed", "Remote declaration changed during read")
        return {"methods": sorted(result, key=lambda row: (row["namespace"], row["method"]))}
