"""user:“给我把 2 阶段做完，前端除外”+(目录选择提供本地browse后端，复用原路径规则，不调用系统对话框)。"""
import os
import re
from pathlib import Path

from .filesystem_access import PluginFilesystemAPI


class DirectoryPickerError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class PluginDirectoryPickerAPI:
    kind = "browse"

    def __init__(self, context, scope):
        self._scope = scope
        self._fs = PluginFilesystemAPI(context.work_root, scope, context.data_dir)

    def capability(self):
        self._scope.check_open()
        return self

    def _path(self, path):
        candidate = Path(path) if path is not None else self._fs.root
        if not candidate.is_absolute() or candidate.drive.startswith("\\"):
            raise ValueError("Use a fully qualified local path")
        if os.name == "nt":
            import ctypes
            if ctypes.windll.kernel32.GetDriveTypeW(str(candidate.anchor)) != 3:
                raise ValueError("Only fixed local drives are supported")
        target = self._fs.resolve(candidate)
        if not target.is_dir():
            raise ValueError("Parent must be an existing directory")
        return target

    def list(self, path=None, *, limit=100):
        self._scope.check_open()
        try:
            target = self._path(path)
            listing = self._fs.list_dir(target, limit=limit)
            ancestors = [self._fs.root]
            for part in target.relative_to(self._fs.root).parts:
                ancestors.append(ancestors[-1] / part)
            return {"path": str(target), "entries": [{"name": row.name, "path": str(target / row.name)}
                    for row in listing.entries if row.kind == "directory"], "truncated": listing.truncated,
                    "ancestors": [{"name": item.name, "path": str(item)} for item in ancestors]}
        except (OSError, ValueError, TypeError):
            raise DirectoryPickerError("directory-unreadable", "List a bounded directory within the fixed local project") from None

    def create_directory(self, path, name):
        self._scope.check_open()
        try:
            if (path is None or type(name) is not str or not name.strip() or len(name) > 255 or name[-1] in {".", " "}
                    or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name) or name in {".", ".."}
                    or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", name.split(".")[0])):
                raise ValueError("Use one ordinary directory name")
            parent = self._path(path)
            child = self._fs.resolve(parent / name)
            child.mkdir()
            return str(child)
        except FileExistsError:
            raise DirectoryPickerError("directory-exists", "Child directory already exists") from None
        except (OSError, ValueError, TypeError):
            raise DirectoryPickerError("directory-create-failed", "Create one child of an existing fixed local project directory") from None
