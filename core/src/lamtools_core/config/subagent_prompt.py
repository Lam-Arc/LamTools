"""Sub-agent delegation guide prompt.

Loads a natural-language markdown guide that teaches the running (parent)
agent how and when to use the ``sub_agent`` tool, and injects it into the
system prompt. The guide is plain markdown (no frontmatter).

Resolution is a first-existing-wins fallback chain (same shape as the
loadtools/access_tools loaders):

  1. Project:  ``{work_root}/.lam/config/subagent/guide.md``
  2. Global:    ``~/.lam/config/subagent/guide.md``
  3. Built-in:  :data:`DEFAULT_SUBAGENT_GUIDE` (module constant)

Members inherit this loader automatically because it lives in
``lamtools_core.config``. The user can author a custom guide as a plain
markdown file in either the project or the global location.
"""

from __future__ import annotations

import json
from pathlib import Path

GUIDE_FILENAME = "guide.md"
SETTINGS_FILENAME = "settings.json"
SUBAGENT_DIR = "subagent"

#: Built-in default guide used when no project/global file exists. Authored as
#: plain natural-language markdown; replaces the former hard-coded delegation
#: line in the base agent system prompt. This is delegation *strategy* only —
#: per-parameter usage (model/mode/agent) lives in the sub_agent tool schema so
#: the model learns it from the tool definition, not the system prompt.
DEFAULT_SUBAGENT_GUIDE = """\
## Sub-agent 委派指南
互不依赖的任务应委派 sub-agent 并行执行。委派时其 prompt 至少明确：工作范围、任务目标、输出格式。任务应自包含、边界清晰，避免与主 agent 职责重叠。"""

#: Default sub-agent settings. ``default_multimodal_model`` is the model_id or
#: display_name used in the capability prompt to tell text models which multimodal
#: model to delegate to. Empty string means "not configured" (fallback to
#: hard-coded examples).
DEFAULT_SUBAGENT_SETTINGS: dict[str, object] = {"default_multimodal_model": ""}


def subagent_guide_dirs(work_root: str | Path | None) -> list[Path]:
    """Return candidate directories, project scope first then global."""
    dirs: list[Path] = []
    if work_root:
        dirs.append(Path(work_root).resolve() / ".lam" / "config" / SUBAGENT_DIR)
    dirs.append(Path.home() / ".lam" / "config" / SUBAGENT_DIR)
    return dirs


def resolve_subagent_guide_path(work_root: str | Path | None = None) -> Path | None:
    """Return the first existing guide file path, or ``None`` when none exists."""
    for directory in subagent_guide_dirs(work_root):
        path = directory / GUIDE_FILENAME
        if path.is_file():
            return path
    return None


def load_subagent_guide(work_root: str | Path | None = None) -> str:
    """Load the sub-agent guide text.

    Returns the first existing project/global file content, otherwise the
    built-in :data:`DEFAULT_SUBAGENT_GUIDE`.
    """
    path = resolve_subagent_guide_path(work_root)
    if path is not None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        if text.strip():
            return text
    return DEFAULT_SUBAGENT_GUIDE


def guide_path_for_scope(scope: str, work_root: str | Path | None) -> Path:
    """Return the writable guide path for ``scope`` ("project" or "global")."""
    if scope == "project" and work_root:
        return Path(work_root).resolve() / ".lam" / "config" / SUBAGENT_DIR / GUIDE_FILENAME
    return Path.home() / ".lam" / "config" / SUBAGENT_DIR / GUIDE_FILENAME


def write_subagent_guide(content: str, *, scope: str, work_root: str | Path | None) -> Path:
    """Persist ``content`` to the guide file for ``scope`` and return its path."""
    path = guide_path_for_scope(scope, work_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Sub-agent settings (JSON key-value, e.g. default_multimodal_model)
# ---------------------------------------------------------------------------

def resolve_subagent_settings_path(work_root: str | Path | None = None) -> Path | None:
    """Return the first existing settings file path, or ``None``."""
    for directory in subagent_guide_dirs(work_root):
        path = directory / SETTINGS_FILENAME
        if path.is_file():
            return path
    return None


def load_subagent_settings(work_root: str | Path | None = None) -> dict[str, object]:
    """Load sub-agent settings (project > global > defaults).

    Returns a dict with at least ``default_multimodal_model``.
    """
    path = resolve_subagent_settings_path(work_root)
    if path is not None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**DEFAULT_SUBAGENT_SETTINGS, **data}
        except (OSError, json.JSONDecodeError):
            pass
    return dict(DEFAULT_SUBAGENT_SETTINGS)


def settings_path_for_scope(scope: str, work_root: str | Path | None) -> Path:
    """Return the writable settings path for ``scope`` ("project" or "global")."""
    if scope == "project" and work_root:
        return Path(work_root).resolve() / ".lam" / "config" / SUBAGENT_DIR / SETTINGS_FILENAME
    return Path.home() / ".lam" / "config" / SUBAGENT_DIR / SETTINGS_FILENAME


def write_subagent_settings(updates: dict[str, object], *, scope: str, work_root: str | Path | None) -> Path:
    """Merge ``updates`` into the settings file for ``scope`` and return its path."""
    path = settings_path_for_scope(scope, work_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, object] = dict(DEFAULT_SUBAGENT_SETTINGS)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                existing.update(data)
        except (OSError, json.JSONDecodeError):
            pass
    existing.update(updates)
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


__all__ = [
    "DEFAULT_SUBAGENT_GUIDE",
    "DEFAULT_SUBAGENT_SETTINGS",
    "GUIDE_FILENAME",
    "SETTINGS_FILENAME",
    "SUBAGENT_DIR",
    "guide_path_for_scope",
    "load_subagent_guide",
    "load_subagent_settings",
    "resolve_subagent_guide_path",
    "resolve_subagent_settings_path",
    "settings_path_for_scope",
    "subagent_guide_dirs",
    "write_subagent_guide",
    "write_subagent_settings",
]
