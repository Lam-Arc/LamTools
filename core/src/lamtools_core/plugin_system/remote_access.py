"""user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(仅列当前插件实际受管Remote方法，不伪造Peer权限决策)。"""
import copy

from .capabilities import CapabilityError
from .management_access import HostOperationError
from .operation_bridge import read_operations
from .plugin_http import read_http_routes, resource_guarded_operation
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
        bindings = {}
        for (namespace, method), (path, _, encoding) in methods.items():
            route = routes[path]
            spec = specs.get(route.operation)
            row = next(item for item in manifest.raw["http"]["remote"]
                       if item["namespace"] == namespace and item["method"] == method)
            resource = row.get("resource")
            # user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(不发布同操作资源门禁必然拒绝的别名)。
            if resource_guarded_operation(manifest, route.operation,
                                          admitted=("remote", resource) if resource is not None else None):
                continue
            # user:“复用原宿主权威”+(只列原目录已挂载、同插件所有且无需交互审批的明确方法；资源授权仍由处理器负责)。
            if spec is not None and spec.permission == "auto_allow" and self._catalog.owner_of(route.operation) == "plugin:" + self._scope.owner and self._catalog.has(route.operation):
                bindings[route.operation] = self._catalog.binding_token(route.operation)
                result.append({"namespace": namespace, "method": method, "result_encoding": encoding})
        self._check()
        current = self._host.get(self._scope.owner)
        # user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(读取期间声明被撤回时不发布旧方法清单)。
        if current is None or current.raw != declaration:
            raise HostOperationError("host/changed", "Remote declaration changed during read")
        # user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(外部操作文件的审批变化也必须撤回旧清单)。
        try:
            if {spec.name: spec for spec in read_operations(current)} != specs:
                raise HostOperationError("host/changed", "Remote operations changed during read")
        except (ValueError, TypeError, CapabilityError, UnicodeError, RecursionError):
            raise HostOperationError("host/changed", "Remote operations changed during read") from None
        self._check()
        # user:“第三阶段先做Remote/网关的后端访问控制与明确方法名单”+(最终读取期间同名操作重注册不能发布旧名单)。
        if any(token is None or self._catalog.binding_token(name) is not token
               or not self._catalog.has(name) or self._catalog.owner_of(name) != "plugin:" + self._scope.owner
               for name, token in bindings.items()):
            raise HostOperationError("host/changed", "Remote operation binding changed during read")
        return {"methods": sorted(result, key=lambda row: (row["namespace"], row["method"]))}
