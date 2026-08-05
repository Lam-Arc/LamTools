from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from lamtools_core.config.agents_md import global_agents_md_path
from lamtools_core.prompt import PromptPart, PromptPartKind


DEFAULT_PROJECT_CONTEXT_FILES: list[tuple[str, int, PromptPartKind]] = [
    ("AGENTS.md", 10, "system"),
    ("CLAUDE.md", 10, "system"),
    ("CONTEXT.md", 10, "system"),
    ("MEMORY.md", 20, "memory"),
]

_CONTEXT_CONFIG_FILE = "load_context.jsonc"


@dataclass
class ContextConfig:
    addition: list[dict[str, object]] = field(default_factory=list)
    except_files: list[str] = field(default_factory=list)

    @staticmethod
    def from_file(path: Path) -> ContextConfig | None:
        if not path.is_file():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        data = _parse_jsonc(text)
        if not isinstance(data, dict):
            return None
        addition: list[dict[str, object]] = []
        raw_addition = data.get("addition")
        if isinstance(raw_addition, list):
            for item in raw_addition:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    addition.append(item)
        except_files: list[str] = []
        raw_except = data.get("except")
        if isinstance(raw_except, list):
            for item in raw_except:
                if isinstance(item, str):
                    except_files.append(item)
        return ContextConfig(addition=addition, except_files=except_files)


@dataclass
class ProjectContextFile:
    name: str
    path: Path
    content: str
    priority: int
    kind: PromptPartKind

    def to_prompt_part(self) -> PromptPart:
        return PromptPart(
            key=f"project_{self.name.lower().rstrip('.md').replace('.', '_')}",
            kind=self.kind,
            content=f"Instructions from: {self.path}\n{self.content.strip()}",
            priority=self.priority,
        )


class ProjectContextLoader:
    def __init__(
        self,
        file_specs: list[tuple[str, int, PromptPartKind]] | None = None,
        max_chars_per_file: int = 20000,
    ):
        self._base_specs = file_specs if file_specs is not None else DEFAULT_PROJECT_CONTEXT_FILES
        self._max_chars_per_file = max_chars_per_file

    def _resolve_specs(
        self, work_root: Path
    ) -> list[tuple[str, int, PromptPartKind]]:
        config = ContextConfig.from_file(work_root / _CONTEXT_CONFIG_FILE)
        if config is None:
            return self._base_specs

        specs = list(self._base_specs)
        for item in config.addition:
            name = str(item["name"])
            priority = int(item.get("priority", 50))
            kind = _coerce_kind(str(item.get("kind", "system")))
            specs.append((name, priority, kind))

        except_set = set(config.except_files)
        specs = [s for s in specs if s[0] not in except_set]
        specs.sort(key=lambda s: s[1])
        return specs

    def load(self, work_root: str | Path | None) -> list[ProjectContextFile]:
        results: list[ProjectContextFile] = []
        # Global AGENTS.md is injected additively *before* project context files
        # so both layers contribute to the system prompt (global first, then
        # project-specific). It uses a distinct key to avoid colliding with the
        # project-level AGENTS.md prompt part.
        global_path = global_agents_md_path()
        if global_path.is_file():
            content = self._read(global_path, self._max_chars_per_file)
            if content:
                results.append(
                    ProjectContextFile(
                        name="GLOBAL_AGENTS.md",
                        path=global_path,
                        content=content,
                        priority=5,
                        kind="system",
                    )
                )
        if not work_root:
            return results
        root = Path(work_root).resolve()
        if not root.exists():
            return results
        specs = self._resolve_specs(root)
        for name, priority, kind in specs:
            path = root / name
            if not path.is_file():
                continue
            content = self._read(path, self._max_chars_per_file)
            if content:
                results.append(
                    ProjectContextFile(
                        name=name,
                        path=path,
                        content=content,
                        priority=priority,
                        kind=kind,
                    )
                )
        return results

    def to_prompt_parts(self, work_root: str | Path | None) -> list[PromptPart]:
        return [f.to_prompt_part() for f in self.load(work_root)]

    @staticmethod
    def _read(path: Path, max_chars: int) -> str:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        if len(content) <= max_chars:
            return content
        return (
            content[:max_chars]
            + "\n\n[Instruction file truncated. Read the file directly if exact later sections matter.]"
        )


_VALID_KINDS: set[str] = set(PromptPartKind.__args__)  # type: ignore[attr-defined]


def _coerce_kind(raw: str) -> PromptPartKind:
    if raw in _VALID_KINDS:
        return raw  # type: ignore[return-value]
    return "system"


_JSONC_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)


def _parse_jsonc(text: str) -> object:
    stripped = _JSONC_RE.sub("", text)
    return json.loads(stripped)