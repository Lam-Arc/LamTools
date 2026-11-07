"""user:“审查当前代码，然后继续”+(类型、检查、预设和缓存视图共享原注册表/数据库，不增加另一份业务权威)。"""
import copy
import json
from collections import OrderedDict
from dataclasses import asdict

from .content_access import _bounded
from .services import ServiceError, ServiceKey


class PluginTypesAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope

    def register(self, key, value):
        self._scope.check_open()
        if not isinstance(key, ServiceKey):
            raise TypeError("Type registrations require a public ServiceKey and optional runtime-checkable protocol")
        return self._context.register_service(key, value)

    def require(self, key):
        self._scope.check_open()
        return self._context.bind_service(key)

    def get(self, key):
        try:
            return self.require(key)
        except ServiceError as error:
            if error.code != "service/unavailable":
                raise
            return None


class PluginInspectorAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope

    @staticmethod
    def _descriptor(kind, row):
        if kind == "operations" and isinstance(row, str):
            return {"name": row}
        keys = {"name", "owner"} if kind == "operations" else {"name", "available", "scope", "owner", "version", "epoch"}
        return {key: value for key, value in row.items() if key in keys}

    def snapshot(self, *, limit=1000):
        self._scope.check_open()
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Inspection limit must be 1–1000")
        source = self._context.describe_host()
        # Return registry descriptors only; no raw service objects, retained references or execution endpoint.
        services = [self._descriptor("services", row) for row in source["services"][:limit]]
        operations = [self._descriptor("operations", row) for row in source["operations"][:limit]]
        return _bounded({"services": services, "operations": operations,
                         "truncated": len(source["services"]) > limit or len(source["operations"]) > limit}, 1048576)

    def query(self, kind, name):
        self._scope.check_open()
        if type(kind) is not str or kind not in {"services", "operations"} or type(name) is not str or len(name) > 256:
            raise ValueError("Query a service or operation by its bounded exact name")
        # user:“完成真实接口、参数/错误、作用域、取消/清理”+(精确查询读取原目录而非截断快照，命中后仍只公开同一白名单描述，绝不返回服务值或执行操作)。
        for row in self._context.describe_host()[kind]:
            if (row if isinstance(row, str) else row.get("name")) == name:
                return _bounded(self._descriptor(kind, row), 1048576)
        return None


class PluginPresetAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope

    async def _call(self, method, *args, **kwargs):
        self._scope.acquire()
        try:
            reference = self._context.bind_service("agent_presets")
            result = await reference.call(method, *args, **kwargs)
            # user:“完成真实接口、参数/错误、作用域、取消/清理”+(只读预设发布前复核请求启动代和同一提供方，不改变通用服务调用的已执行副作用语义)。
            self._scope.check_open()
            reference.get()
            if method == "list":
                if len(result) > 1000:
                    raise ValueError("Preset catalog exceeds 1000 records")
                value = [asdict(item) for item in result]
            else:
                value = asdict(result)
            return json.loads(json.dumps(_bounded(value, 1048576), ensure_ascii=False, allow_nan=False))
        finally:
            self._scope.release()

    async def list(self):
        return await self._call("list")

    async def resolve(self, preset_id=None):
        return await self._call("resolve", preset_id)

    async def compose(self, preset_id=None, *, mode="", allowed_tools=None, model="", prompt=""):
        return await self._call("compose", preset_id, mode=mode, allowed_tools=allowed_tools, model=model, prompt=prompt)


class PluginProjectionCacheAPI:
    def __init__(self, context, scope):
        self._context, self._scope, self._entries = context, scope, OrderedDict()
        scope.on_dispose(self._entries.clear)

    async def get(self, session_id):
        self._scope.acquire()
        try:
            current = await self._context.session_projections.get(session_id)
            # Revalidate at the original authority each time, including runtime fields outside metadata revision.
            previous = self._entries.get(session_id)
            if previous != current:
                self._entries[session_id] = copy.deepcopy(current)
            self._entries.move_to_end(session_id)
            while len(self._entries) > 128:
                self._entries.popitem(last=False)
            return copy.deepcopy(self._entries[session_id])
        finally:
            self._scope.release()

    def invalidate(self, session_id=None):
        self._scope.check_open()
        if session_id is None:
            count = len(self._entries)
            self._entries.clear()
            return count
        from .session_data import identifier
        return int(self._entries.pop(identifier(session_id), None) is not None)
