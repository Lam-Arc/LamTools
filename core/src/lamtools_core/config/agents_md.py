"""Global AGENTS.md instruction file.

A user-level instruction file that applies to *every* project, stored at
``{lam_home}/config/AGENTS.md`` (``~/.lam/config/AGENTS.md`` by default, or
beside the app when ``LAMTOOLS_HOME`` is set for green/portable mode).
Unlike the project-level ``{work_root}/AGENTS.md`` (which is loaded by
:class:`ProjectContextLoader` from the work root), the global file is injected
*additively* — the global AGENTS.md is loaded first, then the project AGENTS.md,
so both layers contribute to the system prompt.

The project-level read/write primitives live in ``app/project_store.py`` and
operate on ``{work_root}/AGENTS.md``; this module covers only the global tier.
"""

from __future__ import annotations

from pathlib import Path

from lamtools_core.config.root import lam_home

#: Filename for the global instruction file.
AGENTS_MD_FILENAME = "AGENTS.md"


def global_config_dir() -> Path:
    """Sub-directory under the LamTools home that holds the global AGENTS.md."""
    return lam_home() / "config"


def global_agents_md_path() -> Path:
    """Return the path to the global ``~/.lam/config/AGENTS.md`` file."""
    return global_config_dir() / AGENTS_MD_FILENAME


def read_global_agents_md() -> dict[str, object]:
    """Read the global AGENTS.md.

    Returns ``{"content": str, "exists": bool}`` — ``content`` is empty when the
    file does not exist.
    """
    path = global_agents_md_path()
    if not path.is_file():
        return {"content": "", "exists": False}
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        content = path.read_text(encoding="utf-8", errors="replace")
    return {"content": content, "exists": True}


def write_global_agents_md(content: str) -> dict[str, object]:
    """Persist ``content`` to the global AGENTS.md, creating dirs as needed."""
    path = global_agents_md_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"content": content, "exists": True}
