"""Per-plugin secret storage with OS-backed protection.

Plugins used to keep credentials in their own config files, which made every
plugin responsible for choosing a protection scheme.  This host service keeps
secrets outside the plugin folder and exposes only the calling plugin's own
namespace.

On Windows each value is protected with DPAPI (the current user's login
credentials).  Other platforms fall back to base64 plus owner-only file
permissions; that is obfuscation, not encryption, and the host logs the
limitation when it first writes a secret.
"""

from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import threading
import tempfile
import time
import errno
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if os.name == "nt":
    from ctypes import wintypes
else:  # pragma: no cover - the desktop host is Windows; keep imports portable
    wintypes = None  # type: ignore[assignment]

_logger = logging.getLogger(__name__)

_DPAPI_PREFIX = "dpapi:"
_B64_PREFIX = "b64:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class SecretStoreError(RuntimeError):
    def __init__(self, message: str, *, code: str = "credentials/store"):
        self.code = code
        super().__init__(message)


_transaction_lock = threading.RLock()


if wintypes is not None:
    class _DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]
else:  # pragma: no cover
    _DataBlob = None  # type: ignore[assignment,misc]


def _dpapi_protect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = _DataBlob(len(data), ctypes.cast(buffer, ctypes.c_void_p))
    blob_out = _DataBlob()
    if not crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = _DataBlob(len(data), ctypes.cast(buffer, ctypes.c_void_p))
    blob_out = _DataBlob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _encode(value: str) -> str:
    data = str(value).encode("utf-8")
    if os.name == "nt":
        return _DPAPI_PREFIX + base64.b64encode(_dpapi_protect(data)).decode("ascii")
    _logger.warning("plugin secrets use base64 + file permissions on this platform; DPAPI is Windows-only")
    return _B64_PREFIX + base64.b64encode(data).decode("ascii")


def _decode(encoded: str) -> str:
    encoded = str(encoded or "")
    if encoded.startswith(_DPAPI_PREFIX):
        return _dpapi_unprotect(base64.b64decode(encoded[len(_DPAPI_PREFIX):])).decode("utf-8")
    if encoded.startswith(_B64_PREFIX):
        return base64.b64decode(encoded[len(_B64_PREFIX):]).decode("utf-8")
    raise SecretStoreError("secret value has an unknown encoding")


class PluginSecretStore:
    """Host-owned, per-plugin secret store."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.path = self.root / "secrets.json"
        # user:“宿主能力补齐和接口完善与文档更新”+(磁盘是唯一状态权威；实例不缓存凭据副本，坏文件只在实际操作时明确拒绝)。
        self._lock = _transaction_lock

    def view(self, plugin: str) -> "PluginSecrets":
        return PluginSecrets(self, plugin)

    def for_scope(self, scope):
        from .credentials import PluginCredentials
        scope.check_open()
        return PluginCredentials(self, scope)

    @contextmanager
    def _locked(self):
        # user:“接口完善”+(同一文件的读—改—替换由线程和进程锁串行化，不让旧实例覆盖其他实例新写入的凭据)。
        with self._lock:
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                stream = (self.root / "secrets.lock").open("a+b")
            except OSError as error:
                raise SecretStoreError("Cannot access credential store", code="credentials/io") from None
            with stream:
                try:
                    stream.seek(0, 2)
                    if not stream.tell():
                        stream.write(b"0")
                        stream.flush()
                    for attempt in range(41):
                        stream.seek(0)
                        try:
                            if os.name == "nt":
                                import msvcrt
                                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                            else:
                                import fcntl
                                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                            break
                        except OSError as error:
                            if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK, errno.EBUSY}:
                                raise
                            if attempt == 40:
                                raise SecretStoreError("Credential store is busy", code="credentials/busy") from None
                            time.sleep(0.05)
                except SecretStoreError:
                    raise
                except OSError as error:
                    raise SecretStoreError("Cannot lock credential store", code="credentials/io") from None
                try:
                    yield
                finally:
                    try:
                        stream.seek(0)
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        # Closing the file releases the lock; do not turn an
                        # acknowledged save into an apparent rejected mutation.
                        _logger.warning("Credential lock release failed; closing lock file")

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 1, "plugins": {}}
        except OSError as error:
            raise SecretStoreError("Cannot read credential store", code="credentials/io") from None
        except ValueError as error:
            raise SecretStoreError("Credential store is malformed", code="credentials/corrupt") from None
        if not isinstance(raw, dict) or not isinstance(raw.get("plugins"), dict):
            raise SecretStoreError("Credential store is malformed", code="credentials/corrupt")
        if type(raw.get("version")) is not int or raw["version"] != 1:
            raise SecretStoreError("Unsupported credential store version", code="credentials/version")
        for plugin, bucket in raw["plugins"].items():
            if not plugin or not isinstance(bucket, dict):
                raise SecretStoreError("Credential namespace is malformed", code="credentials/corrupt")
            for key, entry in bucket.items():
                if (not key or not isinstance(entry, dict) or not isinstance(entry.get("value"), str)
                        or not entry["value"].startswith((_DPAPI_PREFIX, _B64_PREFIX))):
                    raise SecretStoreError("Credential entry is malformed", code="credentials/corrupt")
        return raw

    def _save(self, data) -> None:
        temporary = None
        try:
            fd, name = tempfile.mkstemp(dir=self.root, prefix=".secrets-", suffix=".tmp")
            temporary = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as error:
            raise SecretStoreError("Cannot persist credential store", code="credentials/io") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    _logger.warning("Credential temporary-file cleanup failed")

    def _plugin_bucket(self, data, plugin: str) -> dict[str, Any]:
        plugins = data["plugins"]
        bucket = plugins.get(str(plugin))
        if not isinstance(bucket, dict):
            bucket = {}
            plugins[str(plugin)] = bucket
        return bucket

    def get(self, plugin: str, key: str, default: str = "") -> str:
        with self._locked():
            entry = self._load()["plugins"].get(str(plugin), {}).get(str(key))
            if not isinstance(entry, dict) or not entry.get("value"):
                return default
            try:
                return _decode(str(entry["value"]))
            except Exception as error:
                raise SecretStoreError("Cannot decrypt credential", code="credentials/decrypt") from None

    def set(self, plugin: str, key: str, value: str) -> None:
        key = str(key or "").strip()
        if not key:
            raise ValueError("secret key must not be empty")
        with self._locked():
            data = self._load()
            if not str(value):
                if data["plugins"].get(str(plugin), {}).pop(key, None) is not None:
                    self._save(data)
                return
            try:
                encoded = _encode(str(value))
            except Exception as error:
                raise SecretStoreError("Cannot protect credential", code="credentials/protect") from None
            self._plugin_bucket(data, plugin)[key] = {
                "value": encoded,
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
            self._save(data)

    def delete(self, plugin: str, key: str) -> None:
        with self._locked():
            data = self._load()
            if data["plugins"].get(str(plugin), {}).pop(str(key), None) is not None:
                self._save(data)

    def keys(self, plugin: str) -> list[str]:
        with self._locked():
            return sorted(self._load()["plugins"].get(str(plugin), {}).keys())

    def clear(self, plugin: str) -> None:
        with self._locked():
            data = self._load()
            if data["plugins"].pop(str(plugin), None) is not None:
                self._save(data)


class PluginSecrets:
    """The view a single plugin receives as ``context.service("secrets")``."""

    def __init__(self, store: PluginSecretStore, plugin: str) -> None:
        self._store = store
        self.plugin = plugin

    def get(self, key: str, default: str = "") -> str:
        return self._store.get(self.plugin, key, default)

    def set(self, key: str, value: str) -> None:
        self._store.set(self.plugin, key, value)

    def delete(self, key: str) -> None:
        self._store.delete(self.plugin, key)

    def keys(self) -> list[str]:
        return self._store.keys(self.plugin)

    def has(self, key: str) -> bool:
        return str(key) in self._store.keys(self.plugin)

    def clear(self) -> None:
        self._store.clear(self.plugin)


__all__ = ["PluginSecretStore", "PluginSecrets", "SecretStoreError"]
