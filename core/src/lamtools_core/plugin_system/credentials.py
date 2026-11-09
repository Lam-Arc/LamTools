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

    def describe_many(self, refs: list[str]) -> dict[str, CredentialInfo]:
        # user:“继续，自动值守，非必要不停歇，自己不断找下一步做”+(一次读取原所有者键快照，批量状态不读取凭据明文)。
        if type(refs) is not list or len(refs) > 64:
            raise CredentialError("credentials/invalid-ref", "Use at most 64 credential identifiers")
        names = [self._key(ref) for ref in refs]
        keys = set(self._call("keys")) if names else set()
        self._scope.check_open()
        return {key: CredentialInfo(key in keys, "plugin-store" if key in keys else None) for key in names}

    def resolve(self, key: str) -> ResolvedCredential | None:
        key = self._key(key)
        value = self._call("get", key)
        return ResolvedCredential(value) if value else None

    @staticmethod
    def _value(value):
        # user:“复用原宿主权威”+(控制器预检与原凭据写入使用同一值校验)。
        try:
            valid = isinstance(value, str) and bool(value.strip()) and len(value.encode("utf-8")) <= 64 * 1024
        except UnicodeError:
            valid = False
        if not valid:
            raise CredentialError("credentials/invalid-value", "Credential must be a nonblank string of at most 64 KiB; use unset to remove it")

    def set(self, key: str, value: str) -> None:
        key = self._key(key)
        self._value(value)
        self._call("set", key, value)

    def unset(self, key: str) -> None:
        self._call("delete", self._key(key))

    def compare_exchange(self, key: str, *, expected: str | None, value: str | None) -> bool:
        # user:“接口完善与文档更新”+(明确值条件更新沿原加密凭据与所有者范围，不提供任意回调或DSH record转换)。
        key = self._key(key)
        for item in (expected, value):
            try:
                valid = item is None or (isinstance(item, str) and bool(item.strip()) and len(item.encode("utf8")) <= 65536)
            except UnicodeError:
                valid = False
            if not valid:
                raise CredentialError("credentials/invalid-value", "Use None or a nonblank bounded credential value")
        return self._call("compare_exchange", key, expected, value)


__all__ = ["CredentialError", "CredentialInfo", "ResolvedCredential", "PluginCredentials"]
