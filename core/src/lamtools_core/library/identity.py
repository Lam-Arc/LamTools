"""文件身份：把「同一份文件」与「它现在叫什么、在哪」分开。

user:“用户移动或重命名文件后，应尽可能自动保持原有资产信息关联；对于无法
确认身份的文件，应提示重新关联，而不是直接丢失元数据或错误关联到其他文件”
+(路径只是当前位置。Windows 上优先取卷序列号 + 文件 ID，移动与重命名都不会
改变；取不到时才退回路径指纹，并如实标成弱身份)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import ctypes
import hashlib
import os
from pathlib import Path

# Win32：只读属性即可取身份，不读文件内容，也不改变文件状态。
_FILE_READ_ATTRIBUTES = 0x0080
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", ctypes.c_uint32),
        ("ftCreationTime", ctypes.c_uint64),
        ("ftLastAccessTime", ctypes.c_uint64),
        ("ftLastWriteTime", ctypes.c_uint64),
        ("dwVolumeSerialNumber", ctypes.c_uint32),
        ("nFileSizeHigh", ctypes.c_uint32),
        ("nFileSizeLow", ctypes.c_uint32),
        ("nNumberOfLinks", ctypes.c_uint32),
        ("nFileIndexHigh", ctypes.c_uint32),
        ("nFileIndexLow", ctypes.c_uint32),
    ]


@dataclass(frozen=True, slots=True)
class FileIdentity:
    """一份文件此刻的身份与元信息。"""

    identity_key: str
    identity_kind: str
    volume_serial: str
    file_id: str
    path: str
    path_key: str
    name: str
    extension: str
    size: int
    mtime_ns: int
    is_dir: bool

    @property
    def weak(self) -> bool:
        return self.identity_kind != "fileid"

    def to_asset_fields(self) -> dict[str, object]:
        return {
            "identity_key": self.identity_key,
            "identity_kind": self.identity_kind,
            "volume_serial": self.volume_serial,
            "file_id": self.file_id,
            "path": self.path,
            "path_key": self.path_key,
            "name": self.name,
            "extension": self.extension,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "is_dir": self.is_dir,
        }


def normalize_path(path: str | os.PathLike[str]) -> str:
    """转成绝对路径并去掉末尾分隔符；不解析大小写，也不要求文件存在。"""
    raw = os.fspath(path).strip().strip('"')
    if not raw:
        raise ValueError("empty path")
    expanded = os.path.expandvars(os.path.expanduser(raw))
    normalized = os.path.abspath(expanded).rstrip("\\/")
    # 资源管理器与文件对话框给的是长路径，但环境变量/临时目录可能带 8.3
    # 短名（ADMINI~1）；统一成长名，否则同一个文件会得到两个不同的查表键。
    if os.name == "nt":
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = ctypes.windll.kernel32.GetLongPathNameW(normalized, buffer, 32768)  # type: ignore[attr-defined]
            if length:
                normalized = buffer.value.rstrip("\\/")
        except (AttributeError, OSError):
            pass
    return normalized


def path_key(path: str) -> str:
    """用于查表的规范化路径：大小写不敏感，统一分隔符。"""
    return os.path.normcase(os.path.normpath(normalize_path(path))).replace("/", "\\")


def _weak_identity(path: str, normalized: str) -> tuple[str, str, str]:
    digest = hashlib.sha1(path_key(path).encode("utf-8", "surrogatepass")).hexdigest()
    return f"path:{digest}", "", ""


def _win32_identity(path: str) -> tuple[str, str, str] | None:
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except AttributeError:
        return None
    kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.GetFileInformationByHandle.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    kernel32.GetFileInformationByHandle.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    handle = kernel32.CreateFileW(
        path,
        _FILE_READ_ATTRIBUTES,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if not handle or handle == _INVALID_HANDLE_VALUE:
        return None
    try:
        info = _ByHandleFileInformation()
        if not kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
            return None
        volume = f"{info.dwVolumeSerialNumber:08x}"
        file_id = f"{info.nFileIndexHigh:08x}{info.nFileIndexLow:08x}"
        if not file_id.strip("0"):
            # 某些文件系统（或部分网络盘）不提供稳定的文件索引。
            return None
        return f"{volume}:{file_id}", volume, file_id
    finally:
        kernel32.CloseHandle(handle)


def identity_for(path: str | os.PathLike[str]) -> FileIdentity:
    """读取一份文件的身份与当前元信息。

    文件不存在时抛 ``FileNotFoundError``；无权访问时抛 ``PermissionError``。
    身份取不到不算失败：退回路径指纹，由上层如实标为弱身份。
    """
    normalized = normalize_path(path)
    stat = os.stat(normalized)
    is_dir = os.path.isdir(normalized)
    resolved = _win32_identity(normalized)
    if resolved is not None:
        key, volume, file_id = resolved
        kind = "fileid"
    else:
        key, volume, file_id = _weak_identity(normalized, normalized)
        kind = "path"
    name = Path(normalized).name
    extension = "" if is_dir else Path(normalized).suffix.lstrip(".").lower()
    return FileIdentity(
        identity_key=key,
        identity_kind=kind,
        volume_serial=volume,
        file_id=file_id,
        path=normalized,
        path_key=path_key(normalized),
        name=name,
        extension=extension,
        size=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
        is_dir=is_dir,
    )


def identity_from_record(path: str, *, volume_serial: str, file_id: str) -> str:
    """由库里已有的字段拼回身份键（用于迁移/测试）。"""
    if volume_serial and file_id:
        return f"{volume_serial}:{file_id}"
    return _weak_identity(path, normalize_path(path))[0]


def find_identity_candidate(identity: FileIdentity, candidate_paths: list[str]) -> str | None:
    """在候选路径里找出与目标身份相同的那一个；找不到返回 None。

    user:“不能直接丢失元数据或错误关联到其他文件”+(同名文件很多，
    逐个核对卷序列号与文件 ID；弱身份只按原路径比对，绝不猜)。
    """
    for candidate in candidate_paths:
        try:
            other = identity_for(candidate)
        except OSError:
            continue
        if other.identity_key == identity.identity_key:
            return other.path
    return None


def now_stamp() -> datetime:
    return datetime.now()
