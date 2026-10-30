"""user:“宿主能力补齐和接口完善与文档更新”+(权限预设和会话设置只读返回，不把设置快照当作批准凭证)。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


class PermissionAccessError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class PermissionPresetInfo:
    name: str
    auto_approve_level: int


@dataclass(frozen=True)
class PermissionCatalog:
    options: tuple[PermissionPresetInfo, ...]
    default_preset: str


@dataclass(frozen=True)
class SessionPermissionView:
    session_id: str
    preset: str
    base_tier: str
    base_available_level: int
    preset_auto_approve_level: int
    approval_policy: str
    allow_access_outside_workdir: bool
    preferences_stored: bool
    basis: Literal["session-preferences"] = "session-preferences"


class PluginPermissionAPI:
    def __init__(self, host, scope):
        self._host, self._scope = host, scope

    def catalog(self) -> PermissionCatalog:
        self._scope.check_open()
        return self._host.catalog()

    async def read(self, session_id: str) -> SessionPermissionView:
        self._scope.acquire()
        try:
            if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 256:
                raise PermissionAccessError("permissions/invalid-session", "session_id must be a nonblank string of at most 256 characters")
            return await self._host.read(session_id.strip())
        finally:
            self._scope.release()


__all__ = ["PermissionAccessError", "PermissionPresetInfo", "PermissionCatalog", "SessionPermissionView", "PluginPermissionAPI"]
