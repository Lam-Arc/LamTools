"""A meta-path finder that serves plugin files for specific module names.

user:“允许插件去禁用我们的某一个文件，并且自己提供上去”+查找器只拦截覆盖
表里的名字，其余导入完全不受影响；覆盖必须发生在第一次导入之前。
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


class OverrideLoader(importlib.abc.Loader):
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType | None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        source = self.path.read_text(encoding="utf-8-sig")
        code = compile(source, str(self.path), "exec")
        exec(code, module.__dict__)


class OverrideFinder(importlib.abc.MetaPathFinder):
    """Resolve only the module names present in ``overrides``."""

    def __init__(self, overrides: dict[str, Path]) -> None:
        self.overrides = {str(name): Path(path) for name, path in overrides.items()}

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> importlib.machinery.ModuleSpec | None:
        override_path = self.overrides.get(fullname)
        if override_path is None:
            return None
        return importlib.util.spec_from_file_location(
            fullname,
            override_path,
            loader=OverrideLoader(override_path),
        )


def install_overrides(overrides: dict[str, Path]) -> OverrideFinder:
    """Insert the finder at the front so it wins over the normal path finders."""
    finder = OverrideFinder(overrides)
    sys.meta_path.insert(0, finder)
    return finder


def remove_overrides(finder: OverrideFinder) -> None:
    try:
        sys.meta_path.remove(finder)
    except ValueError:
        pass


__all__ = [
    "OverrideFinder",
    "OverrideLoader",
    "install_overrides",
    "remove_overrides",
]
