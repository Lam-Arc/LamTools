"""user:“宿主能力补齐和接口完善与文档更新”+(提供绑定启动代和目录的有限只读文件访问，不伪装完整 DSH 文件系统)。"""
from __future__ import annotations

import os
import stat
import codecs
import hashlib
import re
import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from lamtools_core.tool.workspace import validate_workspace_path
from lamtools_core.tool.workspace_files import atomic_write_bytes
from .file_lock import locked_file, FileLockBusy


class FilesystemError(ValueError):
    def __init__(self, code: str, message: str, *, may_have_changed: bool = False):
        self.code = code
        self.may_have_changed = may_have_changed
        super().__init__(message)


@dataclass(frozen=True)
class FileInfo:
    name: str
    kind: str
    size: int
    modified_ns: int


@dataclass(frozen=True)
class DirectoryListing:
    entries: tuple[FileInfo, ...]
    truncated: bool


@dataclass(frozen=True)
class FileObservation:
    path: Path
    exists: bool
    revision: str | None
    size: int


@dataclass(frozen=True)
class FileWriteResult:
    path: Path
    revision: str
    bytes_written: int
    written: bool
    replacements: int = 0


def _is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _info(name, info):
    kind = ("link" if _is_link(info) else "file" if stat.S_ISREG(info.st_mode)
            else "directory" if stat.S_ISDIR(info.st_mode) else "other")
    return FileInfo(name, kind, info.st_size, info.st_mtime_ns)


def _error(error):
    code = ("fs/not-found" if isinstance(error, FileNotFoundError) else
            "fs/not-directory" if isinstance(error, NotADirectoryError) else
            "fs/permission-denied" if isinstance(error, PermissionError) else "fs/io-error")
    return FilesystemError(code, "Filesystem operation failed")


def _limit(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise FilesystemError("fs/invalid-limit", f"Limit must be an integer between 1 and {maximum}")


class PluginFilesystemAPI:
    """Synchronous trusted-plugin convenience API, not an OS security boundary.

    Path checks reject observed links/reparse points but are not race-proof
    against concurrent hostile filesystem changes. No snapshot or deadline.
    """
    def __init__(self, root, scope, data_dir=None):
        self._root = Path(root).resolve()
        self._scope = scope
        self._lock_root = Path(data_dir).resolve() / "filesystem-locks" if data_dir is not None else None
        self._watches = set()
        self._watch_cleanup = False

    async def _close_watches(self):
        watches = tuple(self._watches)
        for watch in watches:
            watch._stop.set()
        for watch in watches:
            await watch.aclose()

    def _watch_snapshot(self, path):
        target = self._path(path, allow_missing_final=True)
        try:
            try:
                info = target.stat()
            except FileNotFoundError:
                return None
            header = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            if not stat.S_ISDIR(info.st_mode):
                if not stat.S_ISREG(info.st_mode):
                    raise FilesystemError("fs/not-file", "Only regular files and directories can be watched")
                return header
            entries = []
            with os.scandir(target) as iterator:
                for entry in iterator:
                    if len(entries) >= 1000:
                        raise FilesystemError("fs/watch-limit", "Directory watch exceeds 1000 direct entries")
                    item = entry.stat(follow_symlinks=False)
                    entries.append((entry.name, item.st_mode, item.st_size, item.st_mtime_ns))
            return header, tuple(sorted(entries))
        except OSError as error:
            raise _error(error) from None

    async def watch(self, path, callback, *, interval=0.5):
        # user:“继续，把 2 阶段都做完”+(监听显式采用元数据轮询近似，先检查路径与容量，再注册真实后台任务和停用清理)。
        self._scope.check_open()
        if not callable(callback) or type(interval) not in {int, float} or not math.isfinite(interval) or not 0.01 <= interval <= 60:
            raise FilesystemError("fs/invalid-watch", "Watch needs a callable and interval within [0.01, 60] seconds")
        if len(self._watches) >= 64:
            raise FilesystemError("fs/watch-limit", "At most 64 active watches per view")
        target = self._path(path, allow_missing_final=True)
        snapshot = self._watch_snapshot(target)
        if not self._watch_cleanup:
            self._scope.on_dispose(self._close_watches)
            self._watch_cleanup = True
        from .file_watch import FileWatch
        handle = FileWatch(self, target, callback, interval, snapshot)
        self._watches.add(handle)
        return handle

    @property
    def root(self) -> Path:
        self._scope.check_open()
        return self._root

    def resolve(self, path) -> Path:
        # user:“继续，把 2 阶段都做完”+(本地文件目标采用重新校验的 Path，不伪装 DSH opaque target 或远程挂载)。
        return self._path(path, allow_missing_final=True)

    def process_path(self, target) -> str:
        return str(self.resolve(target))

    def file_url(self, target) -> str:
        return self.resolve(target).as_uri()

    def contains(self, parent, child) -> bool:
        boundary = self.resolve(parent)
        try:
            self.resolve(child).relative_to(boundary)
            return True
        except ValueError:
            return False

    def process_path_from_host_path(self, host_path) -> str | None:
        self._scope.check_open()
        try:
            absolute = Path(host_path)
        except (TypeError, ValueError):
            raise FilesystemError("fs/invalid-path", "Host mapping requires an absolute path") from None
        if not absolute.is_absolute():
            raise FilesystemError("fs/invalid-path", "Host mapping requires an absolute path")
        try:
            return self.process_path(absolute)
        except FilesystemError as error:
            if error.code in {"fs/invalid-path", "fs/not-found", "fs/link-not-supported"}:
                return None
            raise

    def _path(self, path, *, allow_final_link=False, allow_missing_final=False):
        self._scope.check_open()
        try:
            value = os.fspath(path)
            if not isinstance(value, str) or not value or "\x00" in value:
                raise ValueError
            candidate = Path(value)
            components = candidate.parts[1:] if candidate.anchor else candidate.parts
            if ".." in candidate.parts or any(":" in part for part in components):
                raise ValueError
            lexical = self._root / candidate
            relative = lexical.relative_to(self._root)
            # user:“每一个地方 sunday 都有等价或者近似接口”+(复用工作目录路径规则，但此只读子集显式拒绝越界和已观察到的重解析点)。
            cursor = self._root
            for part in ("", *relative.parts):
                cursor = cursor / part
                try:
                    info = cursor.lstat()
                except FileNotFoundError:
                    if allow_missing_final and relative.parts and cursor == lexical:
                        return validate_workspace_path(lexical, self._root, allow_outside=False)
                    raise
                if _is_link(info):
                    # user:“宿主能力补齐和接口完善与文档更新”+(lstat 仅允许检查最后一个链接本身，根目录和中间链接仍不能穿过)。
                    if allow_final_link and relative.parts and cursor == lexical:
                        return lexical
                    raise FilesystemError("fs/link-not-supported", "Links and reparse points are unsupported")
            return validate_workspace_path(lexical, self._root, allow_outside=False)
        except FilesystemError:
            raise
        except (ValueError, TypeError):
            raise FilesystemError("fs/invalid-path", "Path must stay inside the pinned work root; parent traversal and streams are unsupported") from None
        except OSError as error:
            raise _error(error) from None

    @staticmethod
    def _revision(payload):
        return "sha256:" + hashlib.sha256(payload).hexdigest() if payload is not None else None

    def _snapshot_bytes(self, path):
        target = self._path(path, allow_missing_final=True)
        try:
            try:
                info = target.lstat()
            except FileNotFoundError:
                return target, None
            if _is_link(info):
                raise FilesystemError("fs/link-not-supported", "Links and reparse points are unsupported")
            if not stat.S_ISREG(info.st_mode):
                raise FilesystemError("fs/not-file", "Only regular files can be read")
            with target.open("rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise FilesystemError("fs/not-file", "Only regular files can be read")
                payload = stream.read(1_048_577)
            if len(payload) > 1_048_576:
                raise FilesystemError("fs/too-large", "Whole-file observation and mutation are limited to 1 MiB")
            return target, payload
        except OSError as error:
            raise _error(error) from None

    def observe(self, path) -> FileObservation:
        target, payload = self._snapshot_bytes(path)
        return FileObservation(target, payload is not None, self._revision(payload), len(payload) if payload is not None else 0)

    @staticmethod
    def _text_bytes(content):
        if type(content) is not str or "\x00" in content:
            raise FilesystemError("fs/not-text", "Content must be UTF-8 text without NUL")
        try:
            payload = content.encode("utf-8")
        except UnicodeError:
            raise FilesystemError("fs/not-text", "Content must be UTF-8 text without NUL") from None
        if len(payload) > 1_048_576:
            raise FilesystemError("fs/too-large", "Text mutation is limited to 1 MiB")
        return payload

    def _mutate(self, path, expected_revision, transform):
        # user:“继续，把 2 阶段都做完”+(文件修改复用原子发布工具，合作调用共用路径锁，必须明确修订号，失败不伪装未写入)。
        self._scope.check_open()
        if expected_revision is not None and (type(expected_revision) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_revision)):
            raise FilesystemError("fs/invalid-revision", "Use observe().revision; None only permits creation when absent")
        if self._lock_root is None:
            raise FilesystemError("fs/unavailable", "Host data directory is required for coordinated mutations")
        target = self._path(path, allow_missing_final=True)
        identity = os.path.normcase(str(target))
        lock = self._lock_root / (hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".lock")
        published = False
        try:
            with locked_file(lock):
                target, old = self._snapshot_bytes(target)
                if self._revision(old) != expected_revision:
                    raise FilesystemError("fs/conflict", "File changed or the absent-file condition no longer holds")
                if old is not None:
                    try:
                        previous = old.decode("utf-8")
                        if "\x00" in previous:
                            raise UnicodeError
                    except UnicodeError:
                        raise FilesystemError("fs/not-text", "Existing file must be UTF-8 text without NUL") from None
                else:
                    previous = None
                content, replacements = transform(previous)
                payload = self._text_bytes(content)
                written = payload != old
                if written:
                    try:
                        atomic_write_bytes(target, payload)
                        published = True
                    except Exception:
                        raise FilesystemError("fs/write-failed", "Publication failed or acknowledgement is uncertain; observe the file before retrying", may_have_changed=True) from None
                return FileWriteResult(target, self._revision(payload), len(payload) if written else 0, written, replacements)
        except FileLockBusy:
            raise FilesystemError("fs/busy", "File transaction lock is busy") from None
        except OSError as error:
            if published:
                raise FilesystemError("fs/write-failed", "Publication completed but transaction cleanup failed; observe before retrying", may_have_changed=True) from None
            raise _error(error) from None

    def write_text(self, path, content: str, *, expected_revision: str | None) -> FileWriteResult:
        self._scope.check_open()
        self._text_bytes(content)
        return self._mutate(path, expected_revision, lambda previous: (content, 0))

    def edit_text(self, path, search: str, replacement: str, *, expected_revision: str,
                  replace_all: bool = False) -> FileWriteResult:
        self._scope.check_open()
        self._text_bytes(search)
        self._text_bytes(replacement)
        if not search or type(replace_all) is not bool or expected_revision is None:
            raise FilesystemError("fs/invalid-edit", "Edit requires nonempty literal search, a revision and boolean replace_all")
        def edit(previous):
            if previous is None:
                raise FilesystemError("fs/not-found", "Edit target does not exist")
            count = previous.count(search)
            if not count:
                raise FilesystemError("fs/no-match", "Literal search has no match")
            if count > 1 and not replace_all:
                raise FilesystemError("fs/ambiguous-edit", "Literal search has multiple matches; explicitly select replace_all")
            return previous.replace(search, replacement), count
        return self._mutate(path, expected_revision, edit)

    def stat(self, path=".") -> FileInfo:
        target = self._path(path)
        try:
            return _info(target.name, target.stat())
        except OSError as error:
            raise _error(error) from None

    def lstat(self, path=".") -> FileInfo:
        target = self._path(path, allow_final_link=True)
        try:
            return _info(target.name, target.lstat())
        except OSError as error:
            raise _error(error) from None

    def read_byte_range(self, path, *, offset: int, length: int) -> bytes:
        # user:“写好清单，逐项打勾完成，不要出错”+(范围读取按窗口限制字节，不加载整个文件或前缀；仍保持目录和启动代边界)。
        self._scope.check_open()
        if (type(offset) is not int or type(length) is not int
                or not 0 <= offset <= 2**63 - 1 or not 0 <= length <= 1_048_576
                or offset + length > 2**63 - 1):
            raise FilesystemError("fs/invalid-range", "offset and length must be non-negative integers; length is at most 1 MiB and the end must fit a signed 64-bit offset")
        target = self._path(path)
        try:
            if not stat.S_ISREG(target.stat().st_mode):
                raise FilesystemError("fs/not-file", "Only regular files can be read")
            with target.open("rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise FilesystemError("fs/not-file", "Only regular files can be read")
                if length == 0 or offset >= info.st_size:
                    return b""
                stream.seek(offset)
                return stream.read(length)
        except OSError as error:
            raise _error(error) from None

    def read_bytes(self, path, *, max_bytes: int) -> bytes:
        self._scope.check_open()
        _limit(max_bytes, 1_048_576)
        target = self._path(path)
        try:
            if not stat.S_ISREG(target.stat().st_mode):
                raise FilesystemError("fs/not-file", "Only regular files can be read")
            with target.open("rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise FilesystemError("fs/not-file", "Only regular files can be read")
                payload = stream.read(max_bytes + 1)
            if len(payload) > max_bytes:
                raise FilesystemError("fs/too-large", "File exceeds max_bytes")
            return payload
        except OSError as error:
            raise _error(error) from None

    def read_text(self, path, *, max_bytes: int) -> str:
        payload = self.read_bytes(path, max_bytes=max_bytes)
        try:
            text = payload.decode("utf-8")
            if "\x00" in text:
                raise UnicodeError
            return text
        except UnicodeError:
            raise FilesystemError("fs/not-text", "File must be UTF-8 text without NUL") from None

    def stream_text(self, path, *, max_bytes: int, chunk_bytes: int = 8192) -> Iterator[str]:
        # user:“继续，列好清单 逐项打勾”+(流式文本有总量限制，解码跨块保留状态，yield 前关闭句柄，未耗尽不代表完整验证)。
        self._scope.check_open()
        _limit(max_bytes, 64 * 1024 * 1024)
        _limit(chunk_bytes, 65536)
        original = self._path(path)
        try:
            baseline = original.stat()
        except OSError as error:
            raise _error(error) from None
        if not stat.S_ISREG(baseline.st_mode):
            raise FilesystemError("fs/not-file", "Only regular files can be read")
        if baseline.st_size > max_bytes:
            raise FilesystemError("fs/too-large", "File exceeds max_bytes")

        def signature(info):
            # user:“写好清单，逐项打勾完成，不要出错”+(Windows 路径 stat 和 fstat 的 ctime 语义可能不同；比较身份、长度与修改时间，避免正常文件被误判)。
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

        expected = signature(baseline)
        def changed():
            return FilesystemError("fs/changed", "File changed during streaming; discard partial content and restart explicitly")

        def checked_path():
            target = self._path(original)
            try:
                if signature(target.stat()) != expected:
                    raise changed()
            except OSError as error:
                raise _error(error) from None
            return target

        def chunks():
            decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
            offset = 0
            while offset < baseline.st_size:
                self._scope.check_open()
                target = checked_path()
                size = min(chunk_bytes, baseline.st_size - offset)
                try:
                    with target.open("rb") as stream:
                        if signature(os.fstat(stream.fileno())) != expected:
                            raise changed()
                        stream.seek(offset)
                        raw = stream.read(size)
                        if len(raw) != size or signature(os.fstat(stream.fileno())) != expected:
                            raise changed()
                except OSError as error:
                    raise _error(error) from None
                offset += len(raw)
                try:
                    text = decoder.decode(raw)
                    if "\x00" in text:
                        raise UnicodeError
                except UnicodeError:
                    raise FilesystemError("fs/not-text", "File must be UTF-8 text without NUL") from None
                if text:
                    yield text
            self._scope.check_open()
            checked_path()
            try:
                tail = decoder.decode(b"", final=True)
            except UnicodeError:
                raise FilesystemError("fs/not-text", "File must be UTF-8 text without NUL") from None
            if tail:
                yield tail
        return chunks()

    def list_dir(self, path=".", *, limit: int = 100) -> DirectoryListing:
        self._scope.check_open()
        _limit(limit, 1000)
        target = self._path(path)
        entries = []
        try:
            with os.scandir(target) as iterator:
                for entry in iterator:
                    if len(entries) == limit:
                        return DirectoryListing(tuple(entries), True)
                    entries.append(_info(entry.name, entry.stat(follow_symlinks=False)))
            return DirectoryListing(tuple(entries), False)
        except OSError as error:
            raise _error(error) from None


__all__ = ["PluginFilesystemAPI", "FilesystemError", "FileInfo", "DirectoryListing", "FileObservation", "FileWriteResult"]
