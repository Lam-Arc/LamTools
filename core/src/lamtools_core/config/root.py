"""Unified config root — resolves .lam/core/ directory near the executable.

Check order:
  1. LAMTOOLS_CORE_CONFIG_ROOT  environment variable
  2. {exe_dir}/.lam/core/        (LamCore.exe / python executable directory)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def core_config_root() -> Path:
    """Return the .lam/core/ directory for user-facing config files."""
    env = os.environ.get("LAMTOOLS_CORE_CONFIG_ROOT")
    if env:
        return Path(env)

    exe_dir = _exe_dir()
    return (exe_dir / ".lam" / "core").resolve()


def core_config_file(name: str) -> Path:
    """Return path to a config file inside .lam/core/config/."""
    return core_config_root() / "config" / name


def core_skills_root() -> Path:
    """Return .lam/core/skills/ for user-installed skills."""
    return core_config_root() / "skills"


def core_plugins_root() -> Path:
    """Return .lam/core/plugins/ for user-installed plugins."""
    return core_config_root() / "plugins"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _exe_dir() -> Path:
    """Directory containing the running executable (Python or PyInstaller)."""
    if getattr(sys, "frozen", False):
        # PyInstaller: sys.executable is the .exe path
        return Path(sys.executable).resolve().parent
    # Dev mode: use the project root (3 levels up from this file)
    # config/root.py → src/lamtools_core → core/ → repo root
    return Path(__file__).resolve().parent.parent.parent.parent
