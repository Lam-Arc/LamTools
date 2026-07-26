from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    location: Path
    content: str


class SkillRegistry:
    """Discovers local SKILL.md files and loads their prompt content on demand."""

    def __init__(
        self,
        *,
        explicit_roots: Iterable[str | Path] = (),
        max_content_chars: int = 30_000,
        sample_files: int = 10,
    ) -> None:
        self._explicit_roots = tuple(Path(item).resolve() for item in explicit_roots)
        self._max_content_chars = max_content_chars
        self._sample_files = sample_files
        # Caching: avoid repeated filesystem scans on every prompt_index call.
        # signature() yields a hashable tuple of (path, mtime_ns, size) per file;
        # we compare signatures to detect changes and invalidate accordingly.
        self._cached_signature: tuple[tuple[str, int, int], ...] | None = None
        self._cached_skills: list[Skill] | None = None
        self._cached_index: str | None = None

    def available(self, work_root: str | Path | None) -> list[Skill]:
        sig = self.signature(work_root)
        if self._cached_signature == sig and self._cached_skills is not None:
            return self._cached_skills
        skills: dict[str, Skill] = {}
        for path in self._candidate_skill_files(work_root):
            skill = self._read_skill(path)
            if skill and skill.name not in skills:
                skills[skill.name] = skill
        result = sorted(skills.values(), key=lambda item: item.name)
        self._cached_signature = sig
        self._cached_skills = result
        self._cached_index = None  # invalidate prompt_index cache
        return result

    def get(self, work_root: str | Path | None, name: str) -> Skill | None:
        target = name.strip()
        if not target:
            return None
        for skill in self.available(work_root):
            if skill.name == target:
                return skill
        return None

    def prompt_index(self, work_root: str | Path | None) -> str:
        if self._cached_index is not None:
            return self._cached_index
        skills = self.available(work_root)
        if not skills:
            return ""
        lines = [
            "Available skills:",
            "Use load_skill only when the current task matches a skill description.",
            "<available_skills>",
        ]
        for skill in skills:
            lines.extend(
                [
                    "  <skill>",
                    f"    <name>{skill.name}</name>",
                    f"    <description>{skill.description}</description>",
                    f"    <location>{skill.location}</location>",
                    "  </skill>",
                ]
            )
        lines.append("</available_skills>")
        result = "\n".join(lines)
        self._cached_index = result
        return result

    def load_prompt_content(self, work_root: str | Path | None, name: str) -> str:
        skill = self.get(work_root, name)
        if not skill:
            available = ", ".join(item.name for item in self.available(work_root))
            return f'Skill "{name}" not found. Available skills: {available or "none"}'

        base = skill.location.parent
        files = self._sample_related_files(base)
        content = skill.content.strip()
        if len(content) > self._max_content_chars:
            content = (
                content[: self._max_content_chars]
                + "\n\n[Skill content truncated. Read files under the base directory for exact details.]"
            )

        file_block = "\n".join(f"<file>{item}</file>" for item in files)
        return "\n".join(
            [
                f'<skill_content name="{skill.name}">',
                f"# Skill: {skill.name}",
                "",
                content,
                "",
                f"Base directory for this skill: {base}",
                "Relative paths in this skill are relative to this base directory.",
                "Note: file list is sampled.",
                "",
                "<skill_files>",
                file_block,
                "</skill_files>",
                "</skill_content>",
            ]
        )

    def signature(self, work_root: str | Path | None) -> tuple[tuple[str, int, int], ...]:
        paths: list[tuple[str, int, int]] = []
        for path in self._candidate_skill_files(work_root):
            try:
                stat = path.stat()
            except OSError:
                continue
            paths.append((str(path), stat.st_mtime_ns, stat.st_size))
        return tuple(paths)

    def _candidate_skill_files(self, work_root: str | Path | None) -> list[Path]:
        roots: list[Path] = []
        if work_root:
            root = Path(work_root).resolve()
            roots.extend(
                [
                    root / ".codex",
                    root / ".agents",
                    root / ".claude",
                ]
            )

        home = Path.home()
        roots.extend([home / ".codex", home / ".agents", home / ".claude"])
        roots.extend(self._explicit_roots)

        seen: set[Path] = set()
        results: list[Path] = []

        def _add_if_skill(path: Path) -> None:
            resolved = path.resolve()
            if resolved not in seen and resolved.is_file():
                seen.add(resolved)
                results.append(resolved)

        if work_root:
            wroot = Path(work_root).resolve()
            # Non-recursive scan for SKILL.md at workspace root only
            for p in wroot.glob("SKILL.md"):
                _add_if_skill(p)
            for p in wroot.glob(".opencode/skills/**/SKILL.md"):
                _add_if_skill(p)

        for root in roots:
            if not root.is_dir():
                continue
            patterns = ["skills/**/SKILL.md"]
            if root.name.startswith("."):
                patterns.extend(["SKILL.md", "**/SKILL.md", "skill/**/SKILL.md", ".opencode/skills/**/SKILL.md"])
            for pattern in patterns:
                for path in root.glob(pattern):
                    _add_if_skill(path)
        return results

    def _read_skill(self, path: Path) -> Skill | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        meta, content = self._split_frontmatter(raw)
        name = meta.get("name") or path.parent.name
        description = meta.get("description", "").strip()
        if not description:
            first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
            description = first_line[:200] if first_line else "Specialized workflow."
        return Skill(
            name=name.strip(),
            description=description,
            location=path,
            content=content,
        )

    @staticmethod
    def _split_frontmatter(raw: str) -> tuple[dict[str, str], str]:
        if not raw.startswith("---"):
            return {}, raw
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.DOTALL)
        if not match:
            return {}, raw
        meta: dict[str, str] = {}
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"').strip("'")
        return meta, match.group(2)

    def _sample_related_files(self, base: Path) -> list[Path]:
        files: list[Path] = []
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.name == "SKILL.md":
                continue
            files.append(path)
            if len(files) >= self._sample_files:
                break
        return files


__all__ = ["Skill", "SkillRegistry"]
