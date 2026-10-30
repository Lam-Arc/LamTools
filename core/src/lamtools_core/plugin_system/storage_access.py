"""user:“宿主能力补齐和接口完善与文档更新”+(插件 JSON 状态保存在原稳定数据目录，SQLite 负责原子提交与冲突检查，不另建生命周期)。"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .manifest import _validate_name
from .services import RegistrationScope

MAX_VALUE_BYTES = 1024 * 1024


class StorageError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class StoredValue:
    found: bool
    value: Any
    revision: int


@dataclass(frozen=True)
class StoredKey:
    key: str
    revision: int


@dataclass(frozen=True)
class StorageKeyPage:
    entries: tuple[StoredKey, ...]
    next_after: str | None


def _key(value, *, empty=False):
    try:
        valid = isinstance(value, str) and (empty or bool(value)) and "\x00" not in value and len(value.encode("utf-8")) <= 512
    except UnicodeError:
        valid = False
    if not valid:
        raise StorageError("storage/invalid-key", "Keys must be non-empty UTF-8 strings of at most 512 bytes")
    return value


def _encode(value):
    def validate(item):
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError("JSON object keys must be strings")
            for child in item.values():
                validate(child)
        elif type(item) is list:
            for child in item:
                validate(child)
        elif item is not None and (type(item) not in {str, int, float, bool} or type(item) is float and not math.isfinite(item)):
            raise ValueError("Not a JSON value")
    try:
        validate(value)
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_VALUE_BYTES:
            raise ValueError("Value exceeds byte limit")
        return encoded
    except (ValueError, TypeError, RecursionError) as error:
        raise StorageError("storage/invalid-value", "Value must be finite JSON of at most 1 MiB") from error


class PluginStorageAPI:
    def __init__(self, host, scope):
        self._host, self._scope = host, scope

    def open(self, name: str, *, version: int = 1):
        self._scope.check_open()
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
            raise StorageError("storage/invalid-unit", "Unit name must match [a-z][a-z0-9_-]{0,63}")
        if type(version) is not int or not 1 <= version <= 2**31 - 1:
            raise StorageError("storage/invalid-version", "Version must be a positive 32-bit integer")
        unit = StorageUnit(self._host, self._scope, name, version)
        unit._run("open")
        return unit


class StorageUnit:
    def __init__(self, host, scope: RegistrationScope, name, version):
        self._host, self._scope = host, scope
        self._name, self._version = name, version
        self._closed, self._uncertain = False, False

    def _check(self):
        self._scope.check_open()
        if self._closed:
            raise StorageError("storage/closed", "Storage handle is closed")
        if self._uncertain:
            raise StorageError("storage/unknown-state", "Reopen storage and reconcile the last write before continuing")

    def close(self):
        self._closed = True

    def get(self, key: str) -> StoredValue:
        self._check()
        return self._run("get", key=_key(key))

    def put(self, key: str, value: Any, *, expected_revision: int | None = None) -> StoredValue:
        self._check()
        return self._run("put", key=_key(key), encoded=_encode(value), expected=self._expected(expected_revision))

    def delete(self, key: str, *, expected_revision: int | None = None) -> StoredValue:
        self._check()
        return self._run("delete", key=_key(key), expected=self._expected(expected_revision))

    def keys(self, *, prefix: str = "", after: str | None = None, limit: int = 100) -> StorageKeyPage:
        self._check()
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise StorageError("storage/invalid-limit", "Key page limit must be between 1 and 1000")
        return self._run("keys", prefix=_key(prefix, empty=True), after=None if after is None else _key(after), limit=limit)

    @staticmethod
    def _expected(value):
        if value is not None and (type(value) is not int or not 0 <= value <= 2**63 - 1):
            raise StorageError("storage/invalid-revision", "Expected revision must be a non-negative 64-bit integer")
        return value

    def _run(self, action, **options):
        self._check()
        connection = None
        writing = action in {"open", "put", "delete"}
        try:
            path = self._host.path(self._scope.owner)
            if action == "open":
                path.parent.mkdir(parents=True, exist_ok=True)
            elif not path.is_file():
                raise StorageError("storage/missing-medium", "Storage file is missing; reopen explicitly")
            connection = sqlite3.connect(path.as_uri() + ("?mode=rwc" if action == "open" else "?mode=rw"),
                                         uri=True, timeout=2, isolation_level=None)
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE" if writing else "BEGIN")
            format_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if format_version == 0 and action == "open":
                if connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone():
                    raise StorageError("storage/format-version", "Unknown storage file format")
                connection.execute("CREATE TABLE units (name TEXT PRIMARY KEY, version INTEGER NOT NULL CHECK (version>=1))")
                connection.execute("CREATE TABLE records (unit TEXT NOT NULL REFERENCES units(name), key TEXT NOT NULL, value TEXT, revision INTEGER NOT NULL CHECK (revision>=1), present INTEGER NOT NULL CHECK (present IN (0,1)), PRIMARY KEY (unit,key))")
                connection.execute("PRAGMA user_version=1")
            elif format_version != 1:
                raise StorageError("storage/format-version", "Unsupported storage file version")
            row = connection.execute("SELECT version FROM units WHERE name=?", (self._name,)).fetchone()
            if row is None:
                if action != "open":
                    raise StorageError("storage/missing-unit", "Storage unit no longer exists")
                connection.execute("INSERT INTO units (name,version) VALUES (?,?)", (self._name, self._version))
            elif row[0] != self._version:
                raise StorageError("storage/version-mismatch", "Stored unit version differs from requested version")
            result = self._apply(connection, action, options)
            try:
                connection.commit()
            except Exception as error:
                if writing:
                    self._uncertain = True
                    raise StorageError("storage/unknown-state", "Write acknowledgement failed; reopen and reconcile storage") from error
                raise
            return result
        except StorageError:
            raise
        except (sqlite3.Error, OSError) as error:
            code = "storage/busy" if (getattr(error, "sqlite_errorcode", 0) & 255) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} else "storage/io"
            raise StorageError(code, "Unable to access plugin storage") from error
        finally:
            if connection is not None:
                try:
                    if connection.in_transaction:
                        connection.rollback()
                except sqlite3.Error:
                    pass  # Preserve the original storage/commit diagnosis.
                finally:
                    connection.close()

    def _apply(self, connection, action, options):
        if action == "open":
            return None
        if action == "keys":
            rows = connection.execute("SELECT key,revision FROM records WHERE unit=? AND present=1 AND substr(key,1,length(?))=? AND (? IS NULL OR key>?) ORDER BY key COLLATE BINARY LIMIT ?",
                (self._name, options["prefix"], options["prefix"], options["after"], options["after"], options["limit"] + 1)).fetchall()
            entries = tuple(StoredKey(*row) for row in rows[:options["limit"]])
            return StorageKeyPage(entries, entries[-1].key if len(rows) > options["limit"] else None)
        key = options["key"]
        row = connection.execute("SELECT value,revision,present FROM records WHERE unit=? AND key=?", (self._name, key)).fetchone()
        revision = row[1] if row else 0
        found = bool(row and row[2])
        if action == "get":
            try:
                value = json.loads(row[0]) if found else None
                if found:
                    _encode(value)
            except (ValueError, TypeError, StorageError) as error:
                raise StorageError("storage/invalid-record", "Stored value is not valid supported JSON") from error
            return StoredValue(found, value, revision)
        expected = options.get("expected")
        if expected is not None and expected != revision:
            raise StorageError("storage/conflict", "Record changed since the expected revision")
        if action == "delete" and not found:
            return StoredValue(False, None, revision)
        if revision >= 2**63 - 1:
            raise StorageError("storage/revision-exhausted", "Record revision limit reached")
        revision += 1
        encoded = options["encoded"] if action == "put" else None
        connection.execute("INSERT INTO records (unit,key,value,revision,present) VALUES (?,?,?,?,?) ON CONFLICT(unit,key) DO UPDATE SET value=excluded.value,revision=excluded.revision,present=excluded.present",
                           (self._name, key, encoded, revision, int(action == "put")))
        return StoredValue(action == "put", json.loads(encoded) if encoded is not None else None, revision)


class PluginStorageHost:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, owner):
        owner = _validate_name(owner, self.root)
        folder = self.root / owner
        path = folder / "host-kv.sqlite3"
        if folder.resolve() != folder or path.is_symlink() or not path.resolve().is_relative_to(folder):
            raise StorageError("storage/path", "Plugin storage directory cannot redirect to another location")
        return path

    def for_scope(self, scope):
        scope.check_open()
        return PluginStorageAPI(self, scope)


def ensure_plugin_storage(context, *, root):
    host = context.service("plugin_storage")
    if host is None:
        host = PluginStorageHost(root)
        context.set_service("plugin_storage", host)
    elif host.root != Path(root).resolve():
        raise StorageError("storage/host-changed", "Existing storage host cannot be retargeted")
    return host
