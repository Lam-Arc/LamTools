from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from lamtools_core.skills import SkillRegistry

CommandAction = Literal["insert_token", "run_action", "expand_on_send"]
CommandSource = Literal["core", "member"]


def default_core_resource_roots() -> list[Path]:
    return [Path(__file__).resolve().parents[2]]


@dataclass(frozen=True)
class ComposerCommandDefinition:
    name: str
    title: str
    description: str
    icon: str
    action: CommandAction
    source: CommandSource
    accepts_args: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
            "action": self.action,
            "source": self.source,
            "accepts_args": self.accepts_args,
        }


@dataclass(frozen=True)
class PreparedComposerInput:
    visible_items: list[dict[str, Any]]
    runtime_items: list[dict[str, Any]]
    visible_text: str
    runtime_text: str


def load_command_catalog(
    *, core_roots: list[Path], member_roots: list[Path]
) -> list[ComposerCommandDefinition]:
    disabled = load_disabled_core_commands(member_roots)
    all_core_commands = _load_definitions(core_roots, source="core")
    core_names = {item.name for item in all_core_commands}
    core_commands = [item for item in all_core_commands if item.name not in disabled]
    member_commands = [
        item
        for item in _load_definitions(member_roots, source="member")
        if item.name not in core_names
    ]
    return [*core_commands, *member_commands]


def build_composer_command_catalog(
    *,
    core_roots: list[Path],
    member_roots: list[Path],
    work_root: str | Path | None = None,
    skill_registry: SkillRegistry | None = None,
) -> list[ComposerCommandDefinition]:
    """Return one Core-owned catalog for built-ins, member declarations, and skills."""
    commands = load_command_catalog(core_roots=core_roots, member_roots=member_roots)
    registry = skill_registry or SkillRegistry(explicit_roots=[*member_roots, *core_roots])
    reserved_names = {item.name for item in _load_definitions(core_roots, source="core")}
    reserved_names.update(item.name for item in commands)
    reserved_names.update(load_disabled_core_commands(member_roots))
    skill_commands: list[ComposerCommandDefinition] = []
    for skill in registry.available(work_root):
        name = normalize_command_name(skill.name)
        if not name or name in reserved_names:
            continue
        reserved_names.add(name)
        skill_commands.append(
            ComposerCommandDefinition(
                name=name,
                title=skill.name.strip().lstrip("/") or name,
                description=skill.description,
                icon="sparkles",
                action="insert_token",
                source="core",
            )
        )
    return [*commands, *skill_commands]


def prepare_composer_input(
    *,
    work_root: str | Path | None,
    input_items: list[dict[str, Any]],
    skill_registry: SkillRegistry | None = None,
) -> PreparedComposerInput:
    """Prepare visible and runtime input while preserving attachment items."""
    registry = skill_registry or SkillRegistry()
    visible_items: list[dict[str, Any]] = []
    runtime_items: list[dict[str, Any]] = []
    visible_parts: list[str] = []
    runtime_parts: list[str] = []

    for item in input_items:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "skill":
            requested_name = str(item.get("name") or "").strip()
            if not requested_name:
                raise ValueError("skill name is required")
            skill = _resolve_skill(registry, work_root, requested_name)
            if skill is None:
                available = ", ".join(item.name for item in registry.available(work_root))
                raise ValueError(f'Skill "{requested_name}" not found. Available skills: {available or "none"}')
            source_text = str(item.get("source_text") or f"/{requested_name}")
            content = registry.load_prompt_content(work_root, skill.name)
            visible_items.append({"type": "text", "text": source_text})
            runtime_items.append({"type": "text", "text": content})
            visible_parts.append(source_text)
            runtime_parts.append(content)
            continue
        visible_items.append(item)
        runtime_items.append(item)
        if item.get("type") == "text":
            text = str(item.get("text") or "")
            visible_parts.append(text)
            runtime_parts.append(text)

    return PreparedComposerInput(
        visible_items=visible_items,
        runtime_items=runtime_items,
        visible_text="".join(visible_parts).strip(),
        runtime_text="".join(runtime_parts).strip(),
    )


def normalize_command_name(value: object) -> str:
    return _normalize_name(value)


def _resolve_skill(
    registry: SkillRegistry,
    work_root: str | Path | None,
    requested_name: str,
):
    direct = registry.get(work_root, requested_name)
    if direct is not None:
        return direct
    normalized = normalize_command_name(requested_name)
    return next(
        (item for item in registry.available(work_root) if normalize_command_name(item.name) == normalized),
        None,
    )


def load_disabled_core_commands(member_roots: list[Path]) -> set[str]:
    disabled: set[str] = set()
    for root in member_roots:
        config = root / "command" / "config.json"
        if not config.is_file():
            continue
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        raw = data.get("disabled_core_commands") if isinstance(data, dict) else None
        if isinstance(raw, list):
            for item in raw:
                name = _normalize_name(item)
                if name:
                    disabled.add(name)
    return disabled


def _load_definitions(
    roots: list[Path], *, source: CommandSource
) -> list[ComposerCommandDefinition]:
    seen: set[str] = set()
    commands: list[ComposerCommandDefinition] = []
    for root in roots:
        command_dir = root / "command"
        if not command_dir.is_dir():
            continue
        for path in sorted(command_dir.glob("*.json")):
            if path.name == "config.json":
                continue
            command = _read_definition(path, source=source)
            if command is None or command.name in seen:
                continue
            seen.add(command.name)
            commands.append(command)
    return commands


def _read_definition(
    path: Path, *, source: CommandSource
) -> ComposerCommandDefinition | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    name = _normalize_name(data.get("name"))
    if not name:
        return None
    action = str(data.get("action") or "run_action")
    if action not in {"insert_token", "run_action", "expand_on_send"}:
        return None
    return ComposerCommandDefinition(
        name=name,
        title=str(data.get("title") or name),
        description=str(data.get("description") or ""),
        icon=str(data.get("icon") or "/"),
        action=cast(CommandAction, action),
        source=source,
        accepts_args=bool(data.get("accepts_args") or False),
    )


def _normalize_name(value: object) -> str:
    raw = str(value or "").strip().lstrip("/")
    return " ".join(raw.split()).lower()
