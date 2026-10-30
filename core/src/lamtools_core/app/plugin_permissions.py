"""user:“每一个地方 sunday 都有等价或者近似接口”+(权限读侧复用既有预设规则和会话可见性，不生成授权或改变运行策略)。"""
from __future__ import annotations

from lamtools_core.plugin_system.permission_access import (
    PermissionAccessError, PermissionPresetInfo, PermissionCatalog, SessionPermissionView, PluginPermissionAPI,
)
from lamtools_core.plugin_system.sessions import SessionError
from lamtools_core.tool.operation_levels import AUTO_APPROVE_LEVELS
from . import runtime_permissions as rules


class PluginPermissionService:
    def __init__(self, sessions):
        self._sessions = sessions
        self._store = getattr(sessions._context().host, "session_store", None)

    def for_scope(self, scope):
        scope.check_open()
        return PluginPermissionAPI(self, scope)

    def _context(self):
        try:
            context = self._sessions._context()
        except SessionError as error:
            code = "closed" if error.code == "session/closed" else "host-changed"
            raise PermissionAccessError("permissions/" + code, "Permission host is unavailable; obtain a current host view") from None
        if getattr(context.host, "session_store", None) is not self._store:
            raise PermissionAccessError("permissions/host-changed", "Host session store changed; obtain a current host view")
        return context

    def catalog(self) -> PermissionCatalog:
        self._context()
        try:
            return PermissionCatalog(tuple(PermissionPresetInfo(name, AUTO_APPROVE_LEVELS[name]) for name in rules.PERMISSION_PRESETS),
                                     rules.load_global_runtime_controls()["permission_preset"])
        except Exception:
            raise PermissionAccessError("permissions/read-failed", "Permission catalog could not be read") from None

    async def read(self, session_id: str) -> SessionPermissionView:
        self._context()
        reader = getattr(self._store, "get_readonly", None)
        if not callable(reader):
            raise PermissionAccessError("permissions/unavailable", "Host provides no read-only session store")
        try:
            record = await reader(session_id)
            if record is None:
                raise PermissionAccessError("permissions/not-found", "Session is unknown or unavailable")
            preferences = rules.session_runtime_preferences(record.metadata)
            expanded = rules.resolve_permission_preset(preset=preferences["permission_preset"],
                base_tier=preferences["base_tier"], base_allow_access_outside_workdir=preferences["base_allow_access_outside_workdir"]).to_dict()
            return SessionPermissionView(session_id, preferences["permission_preset"], preferences["base_tier"],
                expanded["available_level"], expanded["auto_approve_level"], expanded["approval_policy"],
                expanded["allow_access_outside_workdir"], "runtime_preferences" in record.metadata)
        except PermissionAccessError:
            raise
        except Exception:
            raise PermissionAccessError("permissions/read-failed", "Session permission preferences could not be read") from None


__all__ = ["PluginPermissionService"]
