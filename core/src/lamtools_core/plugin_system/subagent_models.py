"""user:“每一个地方 sunday 都有等价或者近似接口”+(插件/父会话模型政策沿用原会话CAS；目录不是授权)。"""
from copy import deepcopy

from lamtools_core.async_tasks import finish_on_cancel
from .session_data import SessionDataError, identifier


class SubagentModelError(SessionDataError):
    pass


_KEY = "plugin_subagent_models_v1"
_IDENTITY = ("id", "model_id", "provider_id", "provider")


def _identity(model):
    return {key: getattr(model, key) for key in _IDENTITY}


def _error(code, message):
    return SubagentModelError("subagent-model/" + code, message)


class PluginSubagentModelsAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        self._host = context.require_service("session_data")
        self._root = context.work_root

    def _check_binding(self):
        # user:“复用原宿主权威”+(读取前后使用同一会话宿主与启动代检查，不能向已替换宿主继续派发策略操作)。
        self._scope.check_open()
        if self._context.service("session_data") is not self._host:
            raise _error("host-changed", "Session data host changed")

    async def _read(self, parent):
        self._check_binding()
        identifier(parent)
        if ":sub:" in parent:
            raise _error("invalid-parent", "Choose a visible root parent session")
        _, record, revision = await self._host._read(parent, self._root)
        self._check_binding()
        policies = record.metadata.get(_KEY, {})
        if type(policies) is not dict:
            raise _error("invalid-policy", "Stored policy namespace is invalid")
        policy = policies.get(self._scope.owner)
        if policy is not None and (type(policy) is not dict or set(policy) != {"allowed", "default"}
                or type(policy["allowed"]) is not list or len(policy["allowed"]) > 32
                or any(type(row) is not dict or set(row) != set(_IDENTITY)
                       or any(type(row[key]) is not str for key in _IDENTITY) for row in policy["allowed"])
                or (policy["default"] is not None and policy["default"] not in [row["id"] for row in policy["allowed"]])):
            raise _error("invalid-policy", "Stored model policy is invalid")
        return record, revision, policy

    @staticmethod
    def _public(revision, policy):
        return {"revision": revision, "configured": policy is not None,
                "allowed": deepcopy(policy["allowed"]) if policy is not None else [],
                "default": policy["default"] if policy is not None else None}

    async def read(self, parent):
        self._scope.acquire()
        try:
            _, revision, policy = await self._read(parent)
            return self._public(revision, policy)
        finally:
            self._scope.release()

    def _route(self, ref):
        models = self._context.models
        selected = models.resolve(ref)
        # user:“审查当前代码，然后继续”+(原监督器最终保存wire ID；多提供方同wire不能静默丢失路由身份)。
        rows = models.list()
        if any(row.id != selected.id and (row.model_id in {selected.id, selected.model_id}
                                         or row.id == selected.model_id) for row in rows):
            raise _error("ambiguous-route", "Native child routing cannot uniquely retain this provider route")
        return selected

    async def set(self, parent, *, allowed, default=None, expected_revision):
        self._scope.acquire()
        try:
            if (type(allowed) is not list or len(allowed) > 32
                    or type(expected_revision) is not int or not 0 <= expected_revision <= 2**63 - 1):
                raise _error("invalid-policy", "Use at most 32 routes and a current integer session revision")
            record, revision, _ = await self._read(parent)
            if revision != expected_revision:
                raise _error("conflict", "Parent changed; read again")
            routes = [_identity(self._route(identifier(ref))) for ref in allowed]
            ids = [row["id"] for row in routes]
            if len(ids) != len(set(ids)):
                raise _error("invalid-policy", "Allowed routes must be distinct")
            chosen = None if default is None else self._route(identifier(default)).id
            if chosen is not None and chosen not in ids:
                raise _error("denied", "Default must belong to the explicit allowlist")
            policy = {"allowed": routes, "default": chosen}
            metadata = deepcopy(record.metadata)
            metadata.setdefault(_KEY, {})[self._scope.owner] = policy
            from lamtools_core.app.persistence_host import RevisionConflictError
            try:
                saved = await finish_on_cancel(self._host._store.patch(parent, metadata=metadata, expected_revision=revision),
                                               name="plugin-subagent-model-policy")
            except RevisionConflictError:
                raise _error("conflict", "Parent changed during policy update") from None
            if saved is None:
                raise _error("conflict", "Parent became unavailable during policy update")
            return self._public(revision + 1, policy)
        finally:
            self._scope.release()

    async def select(self, parent, ref=None, *, _legacy=False):
        self._scope.acquire()
        try:
            _, _, policy = await self._read(parent)
            if policy is None:
                if _legacy and ref is not None:
                    return {"id": identifier(ref)}
                raise _error("not-configured", "Configure a parent policy before using selection or a default")
            ref = policy["default"] if ref is None else identifier(ref)
            if ref is None or not policy["allowed"]:
                raise _error("denied", "No allowed default route")
            selected = self._route(ref)
            pinned = next((row for row in policy["allowed"] if row["id"] == selected.id), None)
            if pinned is None:
                raise _error("denied", "Model is outside this plugin parent allowlist")
            if pinned != _identity(selected):
                raise _error("retargeted", "Configured route identity changed; explicitly save a new policy")
            usable = self._context.models.select("background", ref=selected.id).model
            if _identity(usable) != pinned:
                raise _error("retargeted", "Model route changed during provider preflight")
            return usable.to_dict()
        finally:
            self._scope.release()
