"""user:“继续，无人值守模式，不要停下来”+(表和全局槽复用原SQLite KV的单记录事务/修订，不新增数据库或异步持久权威)。"""
import copy
import inspect
import logging
import re
from dataclasses import dataclass

from .storage_access import StorageError, _encode, _key

_logger = logging.getLogger(__name__)
_UNCHANGED = object()


@dataclass(frozen=True)
class DomainSnapshot:
    tables: dict
    global_value: object
    revision: int


class PluginStorageDomainAPI:
    def __init__(self, context, scope):
        self._context, self._scope = context, scope
        registry = context._service_registry
        if not hasattr(registry, "_storage_domain_observers"):
            registry._storage_domain_observers = {}
        self._observers = registry._storage_domain_observers

    def open(self, name, *, tables, version=1):
        self._scope.check_open()
        if type(name) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]{0,55}", name):
            raise ValueError("Use a lowercase domain name of at most 56 characters")
        if type(tables) is not list or len(tables) > 64 or any(type(table) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", table) for table in tables) or len(set(tables)) != len(tables):
            raise ValueError("Provide at most 64 distinct lowercase table names")
        unit = self._context.storage.open("domain-" + name, version=version)
        domain = StorageDomain(unit, name, tuple(sorted(tables)), self._scope, self._observers)
        try:
            domain.read()
        except BaseException:
            domain.close()
            raise
        self._scope.on_dispose(domain.close)
        return domain


class StorageDomain:
    def __init__(self, unit, name, tables, scope, observers):
        self._unit, self._name, self._tables, self._scope = unit, name, tables, scope
        self._observers, self._tokens = observers, set()
        self._identity = (scope.owner, name)

    def read(self):
        value = self._unit.get("snapshot")
        if not value.found:
            return DomainSnapshot({table: {} for table in self._tables}, None, value.revision)
        data = value.value
        if (type(data) is not dict or set(data) != {"tables", "global"} or type(data["tables"]) is not dict
                or set(data["tables"]) != set(self._tables) or any(type(rows) is not dict for rows in data["tables"].values())):
            raise StorageError("storage/domain-schema", "Stored domain table declaration differs or data is invalid")
        for rows in data["tables"].values():
            for key in rows:
                _key(key)
        return DomainSnapshot(copy.deepcopy(data["tables"]), copy.deepcopy(data["global"]), value.revision)

    def commit(self, changes, *, expected_revision, global_value=_UNCHANGED):
        current = self.read()
        if type(expected_revision) is not int or not 0 <= expected_revision <= 2**63 - 1:
            raise ValueError("Read a domain revision before committing")
        if expected_revision != current.revision:
            raise StorageError("storage/conflict", "Domain changed since the observed revision")
        if type(changes) is not list or len(changes) > 100:
            raise ValueError("A domain transaction accepts at most 100 changes")
        data = {"tables": current.tables, "global": current.global_value if global_value is _UNCHANGED else global_value}
        for change in changes:
            if type(change) is not dict or change.get("table") not in self._tables:
                raise ValueError("Change must name a declared table")
            key = _key(change.get("key"))
            if change.get("delete") is True and set(change) == {"table", "key", "delete"}:
                data["tables"][change["table"]].pop(key, None)
            elif set(change) == {"table", "key", "value"}:
                data["tables"][change["table"]][key] = change["value"]
            else:
                raise ValueError("Change must contain a value or delete=True")
        _encode(data)
        stored = self._unit.put("snapshot", data, expected_revision=expected_revision)
        # Notify only after the original transaction has acknowledged; observer failure cannot undo a commit.
        event = {"name": self._name, "revision": stored.revision}
        for token, registration in tuple(self._observers.get(self._identity, {}).items()):
            scope, callback = registration
            # user:“完成真实接口、参数/错误、作用域、取消/清理”+(前一个同步通知可能撤回后续观察者或关闭句柄，调用前复核原注册令牌，已提交数据仍保留)。
            if not scope.accepting or self._observers.get(self._identity, {}).get(token) is not registration:
                continue
            try:
                result = callback(dict(event))
                if inspect.isawaitable(result):
                    if inspect.iscoroutine(result):
                        result.close()
                    raise TypeError("Domain observers must be synchronous")
            except Exception:
                _logger.warning("A local storage-domain observer failed after committed revision %s", stored.revision)
        return DomainSnapshot(copy.deepcopy(stored.value["tables"]), copy.deepcopy(stored.value["global"]), stored.revision)

    def on_change(self, callback):
        self._unit._check()
        if not callable(callback):
            raise TypeError("Domain change observer must be callable")
        entries = self._observers.setdefault(self._identity, {})
        if len(entries) >= 64:
            raise ValueError("At most 64 local observers per plugin/domain")
        token = object()
        entries[token] = (self._scope, callback)
        self._tokens.add(token)
        def dispose():
            self._tokens.discard(token)
            current = self._observers.get(self._identity)
            if current is not None:
                current.pop(token, None)
                if not current:
                    self._observers.pop(self._identity, None)
        return dispose

    def close(self):
        entries = self._observers.get(self._identity)
        if entries is not None:
            for token in self._tokens:
                entries.pop(token, None)
            if not entries:
                self._observers.pop(self._identity, None)
        self._tokens.clear()
        self._unit.close()
