"""user:“该重建就重建”+(每个插件独立模块空间，更新不复用旧模块或字节码)。"""
from __future__ import annotations
import hashlib
import importlib
import importlib.abc
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def namespace(root: Path) -> str:
    return "_lamtools_extension_" + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:20]


class _Source(importlib.abc.Loader):
    def __init__(self, path):
        self.path = path

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(compile(self.path.read_text(encoding="utf-8-sig"), str(self.path), "exec"), module.__dict__)


class _Finder(importlib.abc.MetaPathFinder):
    roots: dict[str, Path] = {}

    def find_spec(self, fullname, path=None, target=None):
        prefix, _, relative = fullname.partition(".")
        root = self.roots.get(prefix)
        if root is None or not relative:
            return None
        file = root.joinpath(*relative.split("."))
        package = file / "__init__.py"
        candidate = package if package.is_file() else file.with_suffix(".py")
        if not candidate.is_file() or not candidate.resolve().is_relative_to(root):
            return None
        return importlib.util.spec_from_file_location(fullname, candidate, loader=_Source(candidate),
            submodule_search_locations=[str(file)] if candidate == package else None)


_finder = _Finder()


def load_module(root: Path, module: str):
    if module.startswith("lamtools_core."):
        return importlib.import_module(module)
    if any(not part.isidentifier() for part in module.split(".")):
        raise ImportError(f"invalid plugin module: {module}")
    root = root.resolve()
    prefix = namespace(root)
    if _finder not in sys.meta_path:
        sys.meta_path.insert(0, _finder)
    _finder.roots[prefix] = root
    if prefix not in sys.modules:
        package = ModuleType(prefix)
        package.__path__ = [str(root)]
        package.__package__ = prefix
        sys.modules[prefix] = package
    return importlib.import_module(f"{prefix}.{module}")


def load_entry(root: Path, entry: Path):
    relative = entry.relative_to(root).with_suffix("")
    parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
    return load_module(root, ".".join(parts))


def invalidate_modules(root: Path) -> None:
    prefix = namespace(root)
    for name in list(sys.modules):
        if name == prefix or name.startswith(prefix + "."):
            sys.modules.pop(name, None)
    _finder.roots.pop(prefix, None)
    importlib.invalidate_caches()
