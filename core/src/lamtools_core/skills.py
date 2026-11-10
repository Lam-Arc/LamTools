from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Callable


def _utc_stamp() -> str:
    """UTC ISO 8601 timestamp the UI can hand straight to ``new Date()``."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    location: Path | None
    content: str
    allow_implicit_invocation: bool = True
    modes: tuple[str, ...] = ()
    # user:“每一个地方 sunday 都有等价或者近似接口”+(保留静态技能默认策略，内存技能分别控制模型和用户调用且不伪造路径)。
    model_invocable: bool = True
    user_invocable: bool = True
    plugin: str = ""


class SkillRegistry:
    """Discovers local SKILL.md files and loads their prompt content on demand."""

    def __init__(
        self,
        *,
        explicit_roots: Iterable[str | Path] = (),
        max_content_chars: int = 30_000,
        sample_files: int = 10,
        root_modes: dict[str | Path, Iterable[str]] | None = None,
        runtime_skills: Callable[[], Iterable[Skill]] | None = None,
    ) -> None:
        self._explicit_roots = tuple(Path(item).resolve() for item in explicit_roots)
        self._max_content_chars = max_content_chars
        self._sample_files = sample_files
        self._runtime_skills = runtime_skills
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
        # user:“宿主能力补齐和接口完善与文档更新”+(磁盘缓存保持原优先级，动态贡献每次读取当前状态，停用后旧注册表不能继续命中缓存)。
        static = self._filesystem_available(work_root)
        if self._runtime_skills is None:
            return static
        skills = {skill.name: skill for skill in static}
        for skill in self._runtime_skills():
            skills.setdefault(skill.name, skill)
        return sorted(skills.values(), key=lambda skill: skill.name)

    def _filesystem_available(self, work_root: str | Path | None) -> list[Skill]:
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

    @staticmethod
    def _prompt_description(value: str, *, limit: int = 180) -> str:
        """Return a compact trigger hint; full instructions stay behind load_skill."""
        text = " ".join(value.split())
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

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
        if self._runtime_skills is None and state_store is None and active_mode is None and self._cached_index is not None:
            return self._cached_index
        skills = [
            skill
            for skill in self.available(work_root)
            if skill.allow_implicit_invocation
            and getattr(skill, "model_invocable", True)
            and self._visible(skill, active_mode)
            and (state_store is None or state_store.is_enabled(skill.name))
        ]
        if not skills:
            return ""
        lines = [
            "Available skills:",
            "Use load_skill only when the task matches a trigger below; full instructions load on demand.",
        ]
        for skill in skills:
            lines.append(f"- {skill.name}: {self._prompt_description(skill.description)}")
        result = "\n".join(lines)
        if self._runtime_skills is None and state_store is None and active_mode is None:
            self._cached_index = result
        return result

    def load_prompt_content(self, work_root: str | Path | None, name: str, *, active_mode: str | None = None) -> str:
        skill = self.get(work_root, name, active_mode=active_mode)
        if not skill:
            available = ", ".join(item.name for item in self.available(work_root) if self._visible(item, active_mode))
            return f'Skill "{name}" not found. Available skills: {available or "none"}'

        if skill.location is None:
            content = skill.content.strip()
            if len(content) > self._max_content_chars:
                content = content[:self._max_content_chars] + "\n\n[Skill content truncated.]"
            return f'<skill_content name="{skill.name}">\n# Skill: {skill.name}\n\n{content}\n</skill_content>'
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
            # BOM 会让 frontmatter 的正则失配，name/description 双双丢失
            # （2026-09-25 审计 P3）。
            raw = path.read_text(encoding="utf-8-sig")
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
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            # 与信任账本同理：损坏的状态文件不该让技能索引抛错
            # （2026-09-25 审计 P3）。
            logging.getLogger(__name__).warning("unreadable skill state: %s", self.path, exc_info=True)
            return {"skills": {}}
        return data if isinstance(data, dict) else {"skills": {}}

    def _save(self, data: dict[str, Any]) -> None:
        from lamtools_core.config.root import atomic_write_text

        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=2) + chr(10))

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

    # ── 分组管理 ──────────────────────────────────────────────────────────
    # user:“skill 界面也做成瀑布流，并分组管理”+(分组与启用状态同账本存储：
    # 有序去重的分组名列表 + 每个技能一个 group 字段，未分组即空串。)

    @staticmethod
    def _clean_groups(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        result: list[str] = []
        for item in raw:
            name = str(item).strip()
            if name and name not in result:
                result.append(name)
        return result

    def snapshot(self) -> tuple[list[str], dict[str, Any]]:
        """一次读盘同时拿到分组表与技能状态（skill.list 逐技能读盘是 N+1）。"""
        data = self._load()
        skills = data.get("skills", {})
        return self._clean_groups(data.get("groups", [])), skills if isinstance(skills, dict) else {}

    def groups(self) -> list[str]:
        return self._clean_groups(self._load().get("groups", []))

    def set_groups(self, groups: list[str]) -> None:
        data = self._load()
        data["groups"] = self._clean_groups(groups)
        self._save(data)

    def group_of(self, name: str) -> str:
        skills = self._load().get("skills", {})
        if not isinstance(skills, dict):
            return ""
        entry = skills.get(name, {})
        if isinstance(entry, dict):
            return str(entry.get("group") or "")
        return ""

    def set_group(self, name: str, group: str) -> None:
        group = str(group).strip()
        # 只读一次账本：分组校验与技能写入必须基于同一份快照，避免并发下
        # 用另一份 groups 覆盖别人刚写入的状态。
        data = self._load()
        if group and group not in self._clean_groups(data.get("groups", [])):
            raise ValueError(f"unknown skill group '{group}'")
        skills = data.get("skills", {})
        if not isinstance(skills, dict):
            skills = {}
            data["skills"] = skills
        if not group:
            # 移出分组：技能本来就没有分组记录时不必落盘。
            entry = skills.get(name)
            if not isinstance(entry, dict) or not entry.get("group"):
                return
        entry = skills.setdefault(name, {})
        if not isinstance(entry, dict):
            entry = {}
            skills[name] = entry
        if group:
            entry["group"] = group
        else:
            entry.pop("group", None)
        self._save(data)

    def rename_group(self, old: str, new: str) -> None:
        old = str(old).strip()
        new = str(new).strip()
        if not new:
            raise ValueError("group name is required")
        data = self._load()
        groups = self._clean_groups(data.get("groups", []))
        if old not in groups:
            raise ValueError(f"unknown skill group '{old}'")
        if new != old and new in groups:
            raise ValueError(f"skill group '{new}' already exists")
        data["groups"] = [new if item == old else item for item in groups]
        skills = data.get("skills", {})
        if isinstance(skills, dict):
            for entry in skills.values():
                if isinstance(entry, dict) and entry.get("group") == old:
                    entry["group"] = new
        self._save(data)

    def delete_group(self, name: str) -> None:
        data = self._load()
        groups = self._clean_groups(data.get("groups", []))
        # 不存在的分组要报错：静默成功会让前端显示“已删除”，实际什么都没发生。
        if name not in groups:
            raise ValueError(f"unknown skill group '{name}'")
        data["groups"] = [item for item in groups if item != name]
        skills = data.get("skills", {})
        if isinstance(skills, dict):
            for entry in skills.values():
                if isinstance(entry, dict) and entry.get("group") == name:
                    entry.pop("group", None)
        self._save(data)


class SkillUsageStore:
    """Per-skill invocation ledger shared by load_skill and slash commands.

    user:“我希望能够在插件界面中看见 skill 的调用统计”+(用量与启停／分组账本
    分开存：技能被删除或状态文件被重写都不该抹掉历史用量)。
    """

    # 记录条数上限：技能总数通常几十个，避免删过大量技能后账本无限增长。
    MAX_RECORDS = 500

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _load(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return {"version": 1, "skills": {}}
        try:
            data = json.loads(raw)
        except ValueError:
            logging.getLogger(__name__).warning("unreadable skill usage: %s", self.path, exc_info=True)
            return {"version": 1, "skills": {}}
        return data if isinstance(data, dict) else {"version": 1, "skills": {}}

    def _save(self, data: dict[str, Any]) -> None:
        from lamtools_core.config.root import atomic_write_text

        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=2) + chr(10))

    @staticmethod
    def empty_entry() -> dict[str, Any]:
        return {"count": 0, "model_count": 0, "user_count": 0, "first_used_at": "", "last_used_at": ""}

    def record(self, name: str, *, source: str = "model", at: str | None = None) -> dict[str, Any]:
        """Increment one skill's counters; returns the updated entry."""
        target = str(name).strip()
        if not target:
            return {}
        stamp = at or _utc_stamp()
        data = self._load()
        skills = data.setdefault("skills", {})
        if not isinstance(skills, dict):
            skills = {}
            data["skills"] = skills
        raw_entry = skills.get(target)
        entry = dict(raw_entry) if isinstance(raw_entry, dict) else {}
        entry["count"] = int(entry.get("count") or 0) + 1
        # 两个来源计数都保持存在，界面与 CLI 不必处理缺字段。
        entry.setdefault("model_count", 0)
        entry.setdefault("user_count", 0)
        if source == "user":
            entry["user_count"] = int(entry.get("user_count") or 0) + 1
        else:
            entry["model_count"] = int(entry.get("model_count") or 0) + 1
        entry.setdefault("first_used_at", stamp)
        entry["last_used_at"] = stamp
        skills[target] = entry
        if len(skills) > self.MAX_RECORDS:
            ordered = sorted(
                skills.items(),
                key=lambda item: str(item[1].get("last_used_at") or "") if isinstance(item[1], dict) else "",
                reverse=True,
            )
            data["skills"] = dict(ordered[: self.MAX_RECORDS])
        self._save(data)
        return entry

    def snapshot(self) -> dict[str, dict[str, Any]]:
        skills = self._load().get("skills", {})
        if not isinstance(skills, dict):
            return {}
        return {str(name): dict(entry) for name, entry in skills.items() if isinstance(entry, dict)}

    def stats_for(self, names: Iterable[str]) -> dict[str, dict[str, Any]]:
        """Return one entry per requested name, zero-filled when never used."""
        ledger = self.snapshot()
        return {str(name): ledger.get(str(name)) or self.empty_entry() for name in names}

    def summary(self) -> dict[str, Any]:
        total = 0
        used = 0
        last = ""
        for entry in self.snapshot().values():
            count = int(entry.get("count") or 0)
            total += count
            if count > 0:
                used += 1
            stamp = str(entry.get("last_used_at") or "")
            if stamp > last:
                last = stamp
        return {"total_calls": total, "skills_used": used, "last_used_at": last}

    def reset(self, name: str | None = None) -> None:
        data = self._load()
        skills = data.get("skills", {})
        if not isinstance(skills, dict):
            return
        if name is None:
            skills.clear()
        else:
            skills.pop(str(name).strip(), None)
        self._save(data)


def derive_skill_usage_store(skill_state_store: Any) -> SkillUsageStore | None:
    """Derive the usage ledger path from the enable/disable ledger path."""
    path = getattr(skill_state_store, "path", None)
    if not path:
        return None
    return SkillUsageStore(Path(path).with_name("skill_usage.json"))


__all__ = ["Skill", "SkillRegistry", "SkillStateStore", "SkillUsageStore", "derive_skill_usage_store"]
