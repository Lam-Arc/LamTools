"""Load the optional Workflow package without requiring installer inclusion.

Existing operation/tool/CLI declarations use this canonical package name.
The package is supplied by the installed plugin, not the frozen Core runtime.
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys

_PACKAGE = "lamtools_core.plugins.bundled.workflow"
_ROOT = Path(__file__).resolve().parent


def create_plugin(context):
    existing = sys.modules.get(_PACKAGE)
    if existing is None:
        try:
            existing = importlib.import_module(_PACKAGE)
        except ModuleNotFoundError as exc:
            if exc.name != _PACKAGE:
                raise
            spec = importlib.util.spec_from_file_location(
                _PACKAGE, _ROOT / "__init__.py",
                submodule_search_locations=[str(_ROOT)],
            )
            if spec is None or spec.loader is None:
                raise ImportError("Workflow package loader unavailable")
            existing = importlib.util.module_from_spec(spec)
            sys.modules[_PACKAGE] = existing
            try:
                spec.loader.exec_module(existing)
            except BaseException:
                sys.modules.pop(_PACKAGE, None)
                raise
    backend = importlib.import_module(f"{_PACKAGE}.backend")
    return backend.create_plugin(context)
