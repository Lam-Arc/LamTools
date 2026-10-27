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
    pass


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
        self.root = Path(root)
        self.path = self.root / "secrets.json"
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {"version": 1, "plugins": {}}
        self._load()

    def view(self, plugin: str) -> "PluginSecrets":
        return PluginSecrets(self, plugin)

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception as exc:  # noqa: BLE001 - a corrupt store must be explicit on write
            _logger.warning("plugin secret store is unreadable: %s", exc)
            return
        if isinstance(raw, dict) and isinstance(raw.get("plugins"), dict):
            self._data = {"version": 1, "plugins": dict(raw["plugins"])}

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, self.path)

    def _plugin_bucket(self, plugin: str) -> dict[str, Any]:
        plugins = self._data.setdefault("plugins", {})
        bucket = plugins.get(str(plugin))
        if not isinstance(bucket, dict):
            bucket = {}
            plugins[str(plugin)] = bucket
        return bucket

    def get(self, plugin: str, key: str, default: str = "") -> str:
        with self._lock:
            entry = self._plugin_bucket(plugin).get(str(key))
            if not isinstance(entry, dict) or not entry.get("value"):
                return default
            try:
                return _decode(str(entry["value"]))
            except Exception as exc:  # noqa: BLE001
                raise SecretStoreError(f"cannot decrypt secret '{key}' for plugin '{plugin}': {exc}") from exc

    def set(self, plugin: str, key: str, value: str) -> None:
        key = str(key or "").strip()
        if not key:
            raise ValueError("secret key must not be empty")
        with self._lock:
            if not str(value):
                self._plugin_bucket(plugin).pop(key, None)
                self._save()
                return
            self._plugin_bucket(plugin)[key] = {
                "value": _encode(str(value)),
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            }
            self._save()

    def delete(self, plugin: str, key: str) -> None:
        with self._lock:
            if self._plugin_bucket(plugin).pop(str(key), None) is not None:
                self._save()

    def keys(self, plugin: str) -> list[str]:
        with self._lock:
            return sorted(self._plugin_bucket(plugin).keys())

    def clear(self, plugin: str) -> None:
        with self._lock:
            if self._data.get("plugins", {}).pop(str(plugin), None) is not None:
                self._save()


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
