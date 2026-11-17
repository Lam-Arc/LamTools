"""A meta-path finder that replaces modules and patches single functions.

user:“甚至是说去禁用我们的某一段函数，然后自己提供一个函数上去”+函数补丁必须
在模块执行完成、调用方绑定名字之前应用，否则 ``from module import f`` 会拿到
旧引用；这里用导入时的补丁加载器解决。
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


class OverrideTable(dict[str, Path]):
    """Whole-module replacements plus per-function patches.

    The table itself is the module mapping, so existing callers that treat the
    loader result as a dict keep working; ``patches`` is carried alongside.
    """

    def __init__(
        self,
        modules: dict[str, Path] | None = None,
        patches: dict[str, dict[str, Path]] | None = None,
    ) -> None:
        super().__init__(modules or {})
        self.patches = {
            key: dict(value) for key, value in (patches or {}).items()
        }

    @property
    def modules(self) -> "OverrideTable":
        return self

    def is_empty(self) -> bool:
        return not self and not self.patches


class OverrideLoader(importlib.abc.Loader):
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType | None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        source = self.path.read_text(encoding="utf-8-sig")
        code = compile(source, str(self.path), "exec")
        exec(code, module.__dict__)


def _load_patch_function(path: Path, name: str, original: Any) -> Any:
    source = path.read_text(encoding="utf-8-sig")
    code = compile(source, str(path), "exec")
    namespace: dict[str, Any] = {
        "__name__": f"_lamtools_patch_{path.stem}",
        "__file__": str(path),
        "__package__": "",
        "original": original,
    }
    exec(code, namespace)
    patched = namespace.get(name)
    if patched is None:
        patched = namespace.get("override")
    if not callable(patched):
        raise ImportError(
            f"function patch {path} must define '{name}' or 'override'"
        )
    return patched


class PatchLoader(importlib.abc.Loader):
    """Run the original loader, then replace the named attributes."""

    def __init__(self, original: importlib.abc.Loader, patches: dict[str, Path]) -> None:
        self.original = original
        self.patches = dict(patches)

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType | None:
        create = getattr(self.original, "create_module", None)
        return create(spec) if callable(create) else None

    def exec_module(self, module: ModuleType) -> None:
        self.original.exec_module(module)
        for name, path in self.patches.items():
            original = getattr(module, name, None)
            setattr(module, name, _load_patch_function(path, name, original))


class OverrideFinder(importlib.abc.MetaPathFinder):
    """Resolve replacements, and post-process patched modules."""

    def __init__(self, table: OverrideTable | dict[str, Path]) -> None:
        if isinstance(table, OverrideTable):
            self.table = table
        else:
            self.table = OverrideTable(modules=dict(table))

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> importlib.machinery.ModuleSpec | None:
        replacement = self.table.modules.get(fullname)
        if replacement is not None:
            return importlib.util.spec_from_file_location(
                fullname,
                replacement,
                loader=OverrideLoader(replacement),
            )
        patches = self.table.patches.get(fullname)
        if not patches:
            return None
        original = importlib.machinery.PathFinder.find_spec(fullname, path)
        if original is None or original.loader is None:
            return None
        loader = PatchLoader(original.loader, patches)
        spec = importlib.util.spec_from_loader(
            fullname,
            loader,
            origin=original.origin,
            is_package=original.submodule_search_locations is not None,
        )
        if spec is not None and original.submodule_search_locations is not None:
            spec.submodule_search_locations = list(original.submodule_search_locations)
        return spec


def install_overrides(table: OverrideTable | dict[str, Path]) -> OverrideFinder:
    """Insert the finder at the front so it wins over the normal path finders."""
    finder = OverrideFinder(table)
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
    "OverrideTable",
    "PatchLoader",
    "install_overrides",
    "remove_overrides",
]
