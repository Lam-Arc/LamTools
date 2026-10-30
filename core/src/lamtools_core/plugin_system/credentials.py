"""user:“宿主能力补齐和接口完善与文档更新”+(新凭据门面绑定插件启动代，元数据查询与明确读取值分离，保留原凭据格式)。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

from .secrets import SecretStoreError


class CredentialError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class CredentialInfo:
    configured: bool
    source: str | None
    writable: bool = True

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class ResolvedCredential:
    value: str = field(repr=False)
    source: str = "plugin-store"


class PluginCredentials:
    def __init__(self, store, scope):
        self._store, self._scope, self._owner = store, scope, scope.owner

    def _key(self, key):
        self._scope.check_open()
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", key):
            raise CredentialError("credentials/invalid-ref", "Credential name must be a POSIX-style identifier of at most 128 characters")
        return key

    def _call(self, method, *args):
        try:
            return getattr(self._store, method)(self._owner, *args)
        except SecretStoreError as error:
            # user:“接口完善”+(默认异常堆栈也不能重新带出底层凭据载荷)。
            raise CredentialError(error.code, "Credential store operation failed") from None

    def describe(self, key: str) -> CredentialInfo:
        key = self._key(key)
        configured = key in self._call("keys")
        return CredentialInfo(configured, "plugin-store" if configured else None)

    def resolve(self, key: str) -> ResolvedCredential | None:
        key = self._key(key)
        value = self._call("get", key)
        return ResolvedCredential(value) if value else None

    def set(self, key: str, value: str) -> None:
        key = self._key(key)
        try:
            valid = isinstance(value, str) and bool(value.strip()) and len(value.encode("utf-8")) <= 64 * 1024
        except UnicodeError:
            valid = False
        if not valid:
            raise CredentialError("credentials/invalid-value", "Credential must be a nonblank string of at most 64 KiB; use unset to remove it")
        self._call("set", key, value)

    def unset(self, key: str) -> None:
        self._call("delete", self._key(key))


__all__ = ["CredentialError", "CredentialInfo", "ResolvedCredential", "PluginCredentials"]
