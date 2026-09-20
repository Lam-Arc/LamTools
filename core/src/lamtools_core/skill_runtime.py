from __future__ import annotations

from dataclasses import dataclass
import sys
from pathlib import Path
from typing import Iterable

from lamtools_core.config.root import core_skills_root, lam_home
from lamtools_core.skills import SkillRegistry


@dataclass(frozen=True)
class SkillRuntime:
    """One assembled view of the skill sources available to an Agent runtime."""

    roots: tuple[Path, ...]
    registry: SkillRegistry


def builtin_core_skill_roots() -> tuple[Path, ...]:
    """Return the packaged or source-tree directory containing built-in skills."""
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            return (Path(bundle_root) / "resources" / "skills",)

    module_root = Path(__file__).resolve().parent
    packaged_root = module_root / "resources" / "skills"
    if packaged_root.is_dir():
        return (packaged_root,)

    source_root = module_root.parents[1] / "skills"
    return (source_root,) if source_root.is_dir() else ()


def assemble_skill_roots(
    *,
    plugin_skill_roots: Iterable[str | Path] = (),
    builtin_skill_roots: Iterable[str | Path] = (),
) -> tuple[Path, ...]:
    """Assemble non-workspace roots in user, plugin, built-in precedence order.

    Workspace skills are resolved first by :class:`SkillRegistry` because the
    workspace is supplied per lookup rather than being a process-global root.
    """
    candidates: list[str | Path] = [
        core_skills_root(),
        lam_home() / "skills",
        *plugin_skill_roots,
        *builtin_skill_roots,
        *builtin_core_skill_roots(),
    ]
    seen: set[Path] = set()
    roots: list[Path] = []
    for candidate in candidates:
        root = Path(candidate).resolve()
        if root in seen:
            continue
        seen.add(root)
        roots.append(root)
    return tuple(roots)


def create_skill_runtime(
    *,
    plugin_skill_roots: Iterable[str | Path] = (),
    builtin_skill_roots: Iterable[str | Path] = (),
    max_content_chars: int = 30_000,
    sample_files: int = 10,
    plugin_skill_modes: dict[str | Path, Iterable[str]] | None = None,
) -> SkillRuntime:
    """Create the authoritative registry used by every Core Agent entrypoint."""
    roots = assemble_skill_roots(
        plugin_skill_roots=plugin_skill_roots,
        builtin_skill_roots=builtin_skill_roots,
    )
    return SkillRuntime(
        roots=roots,
        registry=SkillRegistry(
            explicit_roots=roots,
            max_content_chars=max_content_chars,
            sample_files=sample_files,
            root_modes=plugin_skill_modes,
        ),
    )


__all__ = [
    "SkillRuntime",
    "assemble_skill_roots",
    "builtin_core_skill_roots",
    "create_skill_runtime",
]
