"""Python bridge to the native Rust database engine (`sunday_core_db`).

user:“加载/切换/多会话多 agent 同时读写”+(通过 ctypes CDLL 调用 Rust 原生引擎，每次数据库操作自动释放 Python GIL，绕开 SQLAlchemy/aiosqlite/greenlet 开销)。
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import os
import sys
from ctypes import POINTER, c_char_p, c_size_t, c_uint8, c_uint64, c_void_p
from pathlib import Path
import threading
from typing import Any
from weakref import WeakKeyDictionary

_logger = logging.getLogger("lamtools_core.db.rust")

_FACTORY_REGISTRY: WeakKeyDictionary[Any, "RustCoreDb"] = WeakKeyDictionary()
_PATH_LOCK = threading.Lock()
_PATH_REGISTRY: dict[str, tuple["RustCoreDb", int]] = {}
_PATH_EXTERNAL: dict[str, "RustCoreDb"] = {}


def _canonical_path_key(db_path: Path | str) -> str:
    try:
        return str(Path(db_path).resolve())
    except OSError:
        return str(db_path)


def _lib_filename() -> str:
    if sys.platform == "win32":
        return "sunday_core_db.dll"
    if sys.platform == "darwin":
        return "libsunday_core_db.dylib"
    return "libsunday_core_db.so"


def _candidate_library_paths() -> list[Path]:
    name = _lib_filename()
    candidates: list[Path] = []
    override = os.environ.get("LAMTOOLS_RUST_DB_PATH", "").strip()
    if override:
        candidates.append(Path(override))
    here = Path(__file__).resolve().parent
    # Packaged inside lamtools_core/app/ or _MEIPASS
    candidates.append(here / name)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / name)
        candidates.append(Path(meipass) / "lamtools_core" / "app" / name)
    # Source checkout: core/sunday-core/target/{release,debug}/<lib>
    for parent in here.parents:
        target_root = parent / "sunday-core" / "target"
        if target_root.is_dir():
            candidates.append(target_root / "release" / name)
            candidates.append(target_root / "debug" / name)
            break
    return candidates


def _load_native_library() -> ctypes.CDLL | None:
    if os.environ.get("LAMTOOLS_DISABLE_RUST_DB", "").strip() == "1":
        return None
    for path in _candidate_library_paths():
        if not path.is_file():
            continue
        try:
            lib = ctypes.CDLL(str(path))
            lib.sunday_core_db_open.argtypes = [c_char_p]
            lib.sunday_core_db_open.restype = c_uint64
            lib.sunday_core_db_close.argtypes = [c_uint64]
            lib.sunday_core_db_close.restype = None
            lib.sunday_core_db_call.argtypes = [
                c_uint64,
                c_char_p,
                POINTER(c_uint8),
                c_size_t,
                POINTER(c_size_t),
            ]
            lib.sunday_core_db_call.restype = c_void_p
            lib.sunday_core_db_free.argtypes = [c_void_p, c_size_t]
            lib.sunday_core_db_free.restype = None
            return lib
        except OSError:
            _logger.warning("[db:rust] failed to load native library at %s", path, exc_info=True)
    return None


class RustDbError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


_RUST_WRITE_OPS: frozenset[str] = frozenset(
    {
        "append_and_project_batch",
        "session_create",
        "session_update",
        "session_patch",
        "session_delete",
        "session_persist_legacy_metadata",
        "sync_run",
        "sync_prune",
        "sub_agent_init_db",
        "sub_agent_save",
        "sub_agent_save_if_current",
        "sub_agent_delete_member",
        "sub_agent_recover_mark_interrupted",
        "sub_agent_mail_insert",
        "sub_agent_mail_mark_delivered_by_key",
        "sub_agent_ack_guidance",
        "sub_agent_ack_parent_mailbox",
        "sub_agent_ack_parent_guidance",
        "sub_agent_write_event",
        "sub_agent_drain_member_events",
        "sub_agent_bump_wake_counts",
        "sub_agent_migrate_pending_member_events_to_wake",
        "sub_agent_auto_release_unanswered",
        "sub_agent_mark_member_events_delivered",
    }
)


class RustCoreDb:
    """Thread-safe handle to a native Rust `DbEngine`."""

    def __init__(self, db_path: Path | str, *, lib: ctypes.CDLL, handle: int) -> None:
        self.db_path = Path(db_path)
        self._lock_identity = f"sqlite:{_canonical_path_key(db_path)}".lower()
        self._lib = lib
        self._handle = int(handle)
        self._closed = False

    @classmethod
    def try_open(cls, db_path: Path | str) -> "RustCoreDb | None":
        lib = _load_native_library()
        if lib is None:
            return None
        resolved = str(Path(db_path).resolve())
        handle = int(lib.sunday_core_db_open(resolved.encode("utf-8")))
        if handle <= 0:
            _logger.warning("[db:rust] sunday_core_db_open failed for %s", resolved)
            return None
        _logger.info("[db:rust] native engine opened for %s (handle=%d)", resolved, handle)
        return cls(db_path, lib=lib, handle=handle)

    @property
    def is_active(self) -> bool:
        return not self._closed and self._handle > 0

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        handle = self._handle
        self._handle = 0
        if handle > 0:
            self._lib.sunday_core_db_close(handle)

    def call_sync(self, op: str, payload: dict[str, Any] | None = None) -> Any:
        if not self.is_active:
            raise RustDbError("closed", "RustCoreDb handle is closed")
        req_bytes = (
            json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            if payload
            else b"{}"
        )
        req_buf = (c_uint8 * len(req_bytes)).from_buffer_copy(req_bytes)
        out_len = c_size_t(0)
        ptr = self._lib.sunday_core_db_call(
            self._handle,
            op.encode("utf-8"),
            req_buf,
            len(req_bytes),
            ctypes.byref(out_len),
        )
        if not ptr:
            raise RustDbError("null", f"null response for {op}")
        try:
            raw = ctypes.string_at(ptr, int(out_len.value))
        finally:
            self._lib.sunday_core_db_free(ptr, out_len)
        parsed = json.loads(raw.decode("utf-8"))
        if not parsed.get("ok"):
            raise RustDbError(
                str(parsed.get("error") or "db"),
                str(parsed.get("message") or f"Rust DB error on {op}"),
            )
        return parsed.get("data")

    async def call(self, op: str, payload: dict[str, Any] | None = None) -> Any:
        # user:“规划并实现”+(Rust 写操作共用 Python SQLiteWriteCoordinator 写锁，避免双锁撞车引发 5 秒 busy_timeout 与 database is locked)
        if op in _RUST_WRITE_OPS:
            from .sqlite_write import async_write_lock_for_identity

            async with async_write_lock_for_identity(self._lock_identity):
                return await asyncio.to_thread(self.call_sync, op, payload)
        return await asyncio.to_thread(self.call_sync, op, payload)

    def stats(self) -> dict[str, int]:
        return dict(self.call_sync("stats"))

    def invalidate_thread(self, thread_id: str | None = None) -> None:
        if self.is_active:
            self.call_sync(
                "invalidate_thread",
                {"thread_id": thread_id} if thread_id is not None else {},
            )


def register_rust_db(session_factory: Any, rust_db: RustCoreDb | None) -> None:
    if session_factory is None:
        return
    if rust_db is None:
        old = _FACTORY_REGISTRY.pop(session_factory, None)
        if old is not None:
            key = _canonical_path_key(old.db_path)
            with _PATH_LOCK:
                if _PATH_EXTERNAL.get(key) is old:
                    _PATH_EXTERNAL.pop(key, None)
    else:
        _FACTORY_REGISTRY[session_factory] = rust_db
        key = _canonical_path_key(rust_db.db_path)
        with _PATH_LOCK:
            _PATH_EXTERNAL[key] = rust_db


def get_rust_db(session_factory: Any) -> RustCoreDb | None:
    if session_factory is None:
        return None
    rust_db = _FACTORY_REGISTRY.get(session_factory)
    if rust_db is not None and rust_db.is_active:
        return rust_db
    return None


def borrow_rust_db_for_path(db_path: Path | str) -> RustCoreDb | None:
    """Return an active shared `RustCoreDb` already open for ``db_path``, if any."""
    if os.environ.get("LAMTOOLS_DISABLE_RUST_DB", "").strip() == "1":
        return None
    key = _canonical_path_key(db_path)
    with _PATH_LOCK:
        ext = _PATH_EXTERNAL.get(key)
        if ext is not None and ext.is_active:
            return ext
        entry = _PATH_REGISTRY.get(key)
        if entry is not None and entry[0].is_active:
            return entry[0]
    return None


def acquire_rust_db_for_path(db_path: Path | str) -> tuple[RustCoreDb | None, bool]:
    """Acquire a shared or ref-counted `RustCoreDb` for ``db_path``.

    user:“开始”+(若核心库已打开同一路径则直接复用同一个 Rust 引擎，否则按路径引用计数打开，关闭时自动释放句柄)。
    Returns ``(rust_db, owns_ref)`` where ``owns_ref`` tells ``release_rust_db_for_path``
    whether to decrement the ref-count on close.
    """
    if os.environ.get("LAMTOOLS_DISABLE_RUST_DB", "").strip() == "1":
        return None, False
    key = _canonical_path_key(db_path)
    with _PATH_LOCK:
        ext = _PATH_EXTERNAL.get(key)
        if ext is not None and ext.is_active:
            return ext, False
        entry = _PATH_REGISTRY.get(key)
        if entry is not None and entry[0].is_active:
            engine, count = entry
            _PATH_REGISTRY[key] = (engine, count + 1)
            return engine, True
    opened = RustCoreDb.try_open(db_path)
    if opened is None:
        return None, False
    with _PATH_LOCK:
        ext = _PATH_EXTERNAL.get(key)
        if ext is not None and ext.is_active:
            opened.close()
            return ext, False
        entry = _PATH_REGISTRY.get(key)
        if entry is not None and entry[0].is_active:
            opened.close()
            engine, count = entry
            _PATH_REGISTRY[key] = (engine, count + 1)
            return engine, True
        _PATH_REGISTRY[key] = (opened, 1)
        return opened, True


def release_rust_db_for_path(db_path: Path | str) -> None:
    key = _canonical_path_key(db_path)
    to_close: RustCoreDb | None = None
    with _PATH_LOCK:
        entry = _PATH_REGISTRY.get(key)
        if entry is None:
            return
        engine, count = entry
        if count <= 1:
            _PATH_REGISTRY.pop(key, None)
            to_close = engine
        else:
            _PATH_REGISTRY[key] = (engine, count - 1)
    if to_close is not None:
        to_close.close()
