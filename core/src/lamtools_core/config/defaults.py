"""Unified config directory defaults.

Every user-editable configuration file lives in ``.lam/core/config/`` (see
:func:`lamtools_core.config.root.core_config_dir`). :func:`ensure_default_config_files`
seeds that directory with a built-in default for each configurable file on
first run — the installer/desktop backend calls it at startup, so a fresh
install gets a visible, editable copy of every default immediately.

The function is idempotent: existing files are never overwritten, so user
edits survive every boot.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from lamtools_core.config.root import core_config_dir

_log = logging.getLogger(__name__)

#: Built-in default content for the files that have no bundled resource.
DEFAULT_AGENTS_MD = """\
# Global Agent Instructions

Instructions here apply to *every* project (project-level AGENTS.md is loaded
on top of this file). Edit freely — this is your machine-wide agent guidance.
"""

DEFAULT_LOAD_CONTEXT_JSONC = """\
// 全局上下文加载配置（load_context）
// addition: 追加加载的上下文文件（相对工作区根或绝对路径）
// except:   从默认上下文列表中排除的文件名（如 AGENTS.md / MEMORY.md）
// 工作区根目录的 load_context.jsonc 会叠加在本文件之上。
{
  "addition": [],
  "except": []
}
"""

DEFAULT_MEMORY_MD = """\
# Global Memory

跨项目长期记忆。此处内容会以 memory 优先级注入每个会话；工作区的 MEMORY.md
会叠加在它之后（优先级更高）。
"""

DEFAULT_HOOKS_JSON = '{"hooks": {}}\n'


def bundled_resources_dir() -> Path:
    """Directory of bundled default resources shipped with the app.

    Resolved relative to this file in dev; from ``_MEIPASS/config/resources``
    when frozen (PyInstaller) — the spec packs ``core/config/resources`` there.
    """
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return meipass / "config" / "resources"
    return Path(__file__).resolve().parent.parent.parent.parent / "config" / "resources"


def _copy_if_missing(target: Path, bundled_name: str) -> bool:
    """Copy a bundled resource into the config dir when both exist."""
    source = bundled_resources_dir() / bundled_name
    if not source.is_file():
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        _log.warning("Could not seed %s from bundled %s", target, bundled_name)
        return False
    return True


def _write_if_missing(target: Path, content: str) -> bool:
    """Write ``content`` into the config dir when the file does not exist yet."""
    if target.exists():
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError:
        _log.warning("Could not seed default config file %s", target)
        return False
    return True


def ensure_default_config_files() -> list[Path]:
    """Seed the unified config directory with default files (idempotent).

    Only files that do not exist yet are created; user edits are never
    overwritten. Returns the list of paths actually written (empty when the
    directory is already fully populated).
    """
    config_dir = core_config_dir()
    created: list[Path] = []
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        _log.warning("Could not create unified config directory %s", config_dir)
        return created

    # Tool policies — bundled resources are the canonical defaults.
    for bundled_name in ("loadtools.jsonc", "access_tools.jsonc"):
        target = config_dir / bundled_name
        if not target.exists() and _copy_if_missing(target, bundled_name):
            created.append(target)

    # Hooks — an empty hook set is the safe default.
    if _write_if_missing(config_dir / "hooks.json", DEFAULT_HOOKS_JSON):
        created.append(config_dir / "hooks.json")

    # Instruction / context / memory files.
    for name, content in (
        ("AGENTS.md", DEFAULT_AGENTS_MD),
        ("load_context.jsonc", DEFAULT_LOAD_CONTEXT_JSONC),
        ("memory.md", DEFAULT_MEMORY_MD),
    ):
        if _write_if_missing(config_dir / name, content):
            created.append(config_dir / name)

    # Sub-agent delegation guide + settings.
    from lamtools_core.config.subagent_prompt import (
        DEFAULT_SUBAGENT_GUIDE,
        DEFAULT_SUBAGENT_SETTINGS,
    )

    if _write_if_missing(config_dir / "subagent" / "guide.md", DEFAULT_SUBAGENT_GUIDE):
        created.append(config_dir / "subagent" / "guide.md")
    settings_target = config_dir / "subagent" / "settings.json"
    if _write_if_missing(settings_target, json.dumps(DEFAULT_SUBAGENT_SETTINGS, ensure_ascii=False, indent=2) + "\n"):
        created.append(settings_target)

    # Model definitions directory (bundled per-model jsonc files can land
    # here later; the directory itself must exist for discovery).
    models_dir = config_dir / "models"
    try:
        models_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        _log.warning("Could not create model definitions directory %s", models_dir)

    if created:
        _log.info("Seeded default config files into %s: %s", config_dir, [str(p) for p in created])
    return created


__all__ = [
    "bundled_resources_dir",
    "core_config_dir",
    "ensure_default_config_files",
]
