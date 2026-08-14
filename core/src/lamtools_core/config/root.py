"""Unified config root — resolves .lam/core/ directory near the executable.

Check order:
  1. LAMTOOLS_CORE_CONFIG_ROOT  environment variable
  2. {exe_dir}/.lam/core/        (LamCore.exe / python executable directory)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def lam_home() -> Path:
    """Return the LamTools user-home directory.

    Green/portable mode: when ``LAMTOOLS_HOME`` is set (the desktop shell sets
    it to the app directory's ``.lam/``), every user-level file lives beside
    the app so nothing is written outside the install root. Otherwise fall
    back to ``~/.lam`` for CLI/dev usage.
    """
    env = os.environ.get("LAMTOOLS_HOME")
    if env:
        return Path(env)
    return Path.home() / ".lam"


def core_config_root() -> Path:
    """Return the .lam/core/ directory for user-facing config files."""
    env = os.environ.get("LAMTOOLS_CORE_CONFIG_ROOT")
    if env:
        return Path(env)

    # Green/portable mode: unified under the app-side .lam/.
    lam = os.environ.get("LAMTOOLS_HOME")
    if lam:
        return (Path(lam) / "core").resolve()

    exe_dir = _exe_dir()
    return (exe_dir / ".lam" / "core").resolve()


def core_config_file(name: str) -> Path:
    """Return path to a config file inside .lam/core/config/."""
    return core_config_root() / "config" / name


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path`` atomically (tmp file + rename).

    A crash mid-write must never leave a truncated config file that the next
    read silently treats as empty and then overwrites wholesale — the
    settings-loss chain from audit 09 S3. Callers with no existing file get
    plain creation; the tmp is written next to the target so ``os.replace``
    stays on the same volume.
    """
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def core_config_dir() -> Path:
    """Return the unified user config directory: .lam/core/config/.

    Every user-editable configuration file (loadtools.jsonc,
    access_tools.jsonc, hooks.json, AGENTS.md, load_context.jsonc,
    memory.md, subagent/, models/) lives under this single directory so
    installs and migrations have exactly one place to seed defaults.
    """
    return core_config_root() / "config"


def legacy_user_config_dir() -> Path:
    """Return the legacy user config directory: {lam_home}/config.

    Kept as a read-only fallback for configurations that historically lived
    there (global AGENTS.md, models/, subagent/) before the unified
    .lam/core/config/ directory existed. New writes always go to
    :func:`core_config_dir`.
    """
    return lam_home() / "config"


def core_skills_root() -> Path:
    """Return .lam/core/skills/ for user-installed skills."""
    return core_config_root() / "skills"


def core_plugins_root() -> Path:
    """Return .lam/core/plugins/ for user-installed plugins."""
    return core_config_root() / "plugins"


def default_projects_root() -> Path:
    """Return the lam_projects/ directory for default project workspaces.

    Check order:
      1. LAMTOOLS_PROJECTS_ROOT  environment variable
      2. {repo_root}/lam_projects/  (dev mode: repository root)
      3. {exe_dir}/lam_projects/    (packaged mode: beside the .exe)
    """
    env = os.environ.get("LAMTOOLS_PROJECTS_ROOT")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return (_exe_dir() / "lam_projects").resolve()
    # Dev mode: place lam_projects at the repository root (parent of core/).
    return (_exe_dir().parent / "lam_projects").resolve()


def ensure_projects_root() -> Path:
    """Return lam_projects/, creating it (and parents) if missing."""
    root = default_projects_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


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
