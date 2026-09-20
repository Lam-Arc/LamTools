from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    location: Path
    content: str
    allow_implicit_invocation: bool = True
    modes: tuple[str, ...] = ()


class SkillRegistry:
    """Discovers local SKILL.md files and loads their prompt content on demand."""

    def __init__(
        self,
        *,
        explicit_roots: Iterable[str | Path] = (),
        max_content_chars: int = 30_000,
        sample_files: int = 10,
        root_modes: dict[str | Path, Iterable[str]] | None = None,
    ) -> None:
        self._explicit_roots = tuple(Path(item).resolve() for item in explicit_roots)
        self._max_content_chars = max_content_chars
        self._sample_files = sample_files
        self._root_modes = {
            Path(root).resolve(): tuple(str(mode).strip() for mode in modes if str(mode).strip())
            for root, modes in (root_modes or {}).items()
        }
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

    @staticmethod
    def _visible(skill: Skill, active_mode: str | None) -> bool:
        return not skill.modes or (bool(active_mode) and active_mode in skill.modes)

    def get(self, work_root: str | Path | None, name: str, *, active_mode: str | None = None) -> Skill | None:
        target = name.strip()
        if not target:
            return None
        for skill in self.available(work_root):
            if skill.name == target and self._visible(skill, active_mode):
                return skill
        return None

    def prompt_index(
        self,
        work_root: str | Path | None,
        state_store: SkillStateStore | None = None,
        active_mode: str | None = None,
    ) -> str:
        if state_store is None and active_mode is None and self._cached_index is not None:
            return self._cached_index
        skills = [
            skill
            for skill in self.available(work_root)
            if skill.allow_implicit_invocation
            and self._visible(skill, active_mode)
            and (state_store is None or state_store.is_enabled(skill.name))
        ]
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
                    "  </skill>",
                ]
            )
        lines.append("</available_skills>")
        result = "\n".join(lines)
        if state_store is None and active_mode is None:
            self._cached_index = result
        return result

    def load_prompt_content(self, work_root: str | Path | None, name: str, *, active_mode: str | None = None) -> str:
        skill = self.get(work_root, name, active_mode=active_mode)
        if not skill:
            available = ", ".join(item.name for item in self.available(work_root) if self._visible(item, active_mode))
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
            for candidate in (path, path.parent / "agents" / "openai.yaml"):
                try:
                    stat = candidate.stat()
                except OSError:
                    continue
                paths.append((str(candidate), stat.st_mtime_ns, stat.st_size))
        return tuple(paths)

    def _candidate_skill_files(self, work_root: str | Path | None) -> list[Path]:
        seen: set[Path] = set()
        results: list[Path] = []

        def _add_if_skill(path: Path) -> None:
            resolved = path.resolve()
            if resolved not in seen and resolved.is_file():
                seen.add(resolved)
                results.append(resolved)

        # Workspace skills have the highest precedence.  The runtime assembler
        # orders all remaining sources as user, plugin, then built-in.
        if work_root:
            lam_dir = Path(work_root).resolve() / ".lam"
            if lam_dir.is_dir():
                for p in lam_dir.rglob("SKILL.md"):
                    _add_if_skill(p)

        # An explicit root may be either a skills directory or a resource root
        # containing a skills/ directory.  Preserve both supported forms.
        for root in self._explicit_roots:
            if root.is_dir():
                for p in root.glob("skills/*/SKILL.md"):
                    _add_if_skill(p)
                for p in root.glob("*/SKILL.md"):
                    _add_if_skill(p)

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
            description = first_line[:200] if first_line else "Specialized capability."
        modes: tuple[str, ...] = ()
        resolved = path.resolve()
        for root, scoped_modes in self._root_modes.items():
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            modes = scoped_modes
            break
        return Skill(
            name=name.strip(),
            description=description,
            location=path,
            content=content,
            allow_implicit_invocation=self._allow_implicit_invocation(path.parent),
            modes=modes,
        )

    @staticmethod
    def _allow_implicit_invocation(base: Path) -> bool:
        """Read the standard agents/openai.yaml invocation policy.

        The field is intentionally parsed without a YAML dependency because it
        is a single boolean policy value. Invalid or absent metadata preserves
        the standard default: implicit invocation is allowed.
        """

        path = base / "agents" / "openai.yaml"
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return True
        match = re.search(
            r"(?m)^\s*allow_implicit_invocation\s*:\s*(true|false)\s*(?:#.*)?$",
            raw,
            re.IGNORECASE,
        )
        return match is None or match.group(1).casefold() == "true"

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


class SkillStateStore:
    """Persistent enable/disable state for skills (mirrors PluginStateStore pattern)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"skills": {}}
        data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {"skills": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_enabled(self, name: str) -> bool:
        skills = self._load().get("skills", {})
        if not isinstance(skills, dict):
            return True
        raw = skills.get(name, {})
        return bool(raw.get("enabled", True)) if isinstance(raw, dict) else True

    def set_enabled(self, name: str, enabled: bool) -> None:
        data = self._load()
        skills = data.setdefault("skills", {})
        if not isinstance(skills, dict):
            skills = {}
            data["skills"] = skills
        entry = skills.setdefault(name, {})
        if not isinstance(entry, dict):
            entry = {}
            skills[name] = entry
        entry["enabled"] = bool(enabled)
        self._save(data)

    def remove(self, name: str) -> None:
        data = self._load()
        skills = data.get("skills", {})
        if not isinstance(skills, dict) or name not in skills:
            return
        skills.pop(name, None)
        self._save(data)


__all__ = ["Skill", "SkillRegistry", "SkillStateStore"]
