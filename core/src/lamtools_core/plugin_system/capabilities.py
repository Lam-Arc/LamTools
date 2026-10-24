"""The six declarative capabilities of a plugin.

user:“技能，工具，钩子，mcp，斜杠命令，上下文片段”+这些都只靠清单和文件
声明，宿主读取后交给后面的装配阶段；一条坏声明只影响自己那颗插件。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lamtools_core.llm.profiles import strip_jsonc
from lamtools_core.skills import SkillRegistry

from .manifest import PluginManifest

VALID_TOOL_PERMISSIONS = ("auto_allow", "ask_user", "hard_block")
VALID_TOOL_VISIBILITY = ("always", "on_load")
HOOK_EVENTS = (
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "SessionStart",
    "Stop",
    "UserPromptSubmit",
    "PermissionRequest",
)
VALID_HOOK_HANDLERS = ("command", "http", "mcp", "prompt")


class CapabilityError(ValueError):
    """A capability declaration that cannot be read for one plugin."""

    def __init__(self, plugin: str, message: str) -> None:
        super().__init__(f"{plugin}: {message}")
        self.plugin = plugin
        self.message = message


@dataclass(frozen=True)
class PluginToolSpec:
    name: str
    handler: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    permission: str = "ask_user"
    visibility: str = "always"
    skill: str = ""
    timeout: float | None = None
    plugin: str = ""
    plugin_root: str = ""


@dataclass(frozen=True)
class PluginSkillSpec:
    name: str
    description: str
    location: Path
    plugin: str = ""
    root: Path | None = None


@dataclass(frozen=True)
class PluginHookSpec:
    event: str
    matcher: str
    handlers: tuple[dict[str, Any], ...]
    plugin: str = ""


@dataclass(frozen=True)
class PluginCommandSpec:
    name: str
    title: str = ""
    description: str = ""
    operation: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    effect: dict[str, Any] = field(default_factory=dict)
    plugin: str = ""


@dataclass(frozen=True)
class PluginContextSpec:
    file: Path
    order: int = 50
    plugin: str = ""


@dataclass(frozen=True)
class PluginCapabilities:
    plugin: str
    tools: list[PluginToolSpec] = field(default_factory=list)
    skills: list[PluginSkillSpec] = field(default_factory=list)
    hooks: list[PluginHookSpec] = field(default_factory=list)
    mcp_files: list[Path] = field(default_factory=list)
    commands: list[PluginCommandSpec] = field(default_factory=list)
    context: list[PluginContextSpec] = field(default_factory=list)


def _declared_paths(manifest: PluginManifest, key: str) -> list[Path]:
    raw = manifest.raw.get(key)
    values = raw if isinstance(raw, list) else [raw] if isinstance(raw, str) else []
    paths: list[Path] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if not text.startswith("./"):
            raise CapabilityError(manifest.name, f"{key} path must start with './': {text}")
        candidate = (manifest.root / text[2:]).resolve()
        if not candidate.is_relative_to(manifest.root):
            raise CapabilityError(
                manifest.name, f"{key} path is outside the plugin root: {text}"
            )
        paths.append(candidate)
    return paths


def _load_jsonc(manifest: PluginManifest, path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise CapabilityError(manifest.name, f"cannot read {path.name}: {exc}") from exc
    try:
        return json.loads(strip_jsonc(text))
    except json.JSONDecodeError as exc:
        raise CapabilityError(
            manifest.name, f"{path.name} is not valid JSON ({exc.msg})"
        ) from exc


def _read_tools(manifest: PluginManifest) -> list[PluginToolSpec]:
    tools: list[PluginToolSpec] = []
    seen: set[str] = set()
    for path in _declared_paths(manifest, "tools"):
        data = _load_jsonc(manifest, path)
        items = data.get("tools") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise CapabilityError(manifest.name, f"{path.name} must contain a 'tools' array")
        for index, raw in enumerate(items):
            if not isinstance(raw, dict):
                raise CapabilityError(manifest.name, f"{path.name} tool #{index} must be an object")
            name = str(raw.get("name") or "").strip()
            handler = str(raw.get("handler") or "").strip()
            if not name:
                raise CapabilityError(manifest.name, f"{path.name} tool #{index} is missing name")
            if not handler:
                raise CapabilityError(manifest.name, f"tool '{name}' is missing handler")
            if name in seen:
                raise CapabilityError(manifest.name, f"duplicate tool name '{name}'")
            seen.add(name)
            permission = str(raw.get("permission") or "ask_user").strip()
            if permission not in VALID_TOOL_PERMISSIONS:
                raise CapabilityError(
                    manifest.name,
                    f"tool '{name}' has invalid permission '{permission}'",
                )
            visibility = str(raw.get("visibility") or "always").strip()
            if visibility not in VALID_TOOL_VISIBILITY:
                raise CapabilityError(
                    manifest.name, f"tool '{name}' has invalid visibility '{visibility}'"
                )
            skill = str(raw.get("skill") or "").strip()
            if visibility == "on_load" and not skill:
                raise CapabilityError(
                    manifest.name, f"tool '{name}' is on_load but has no skill"
                )
            timeout_raw = raw.get("timeout")
            timeout: float | None = None
            if timeout_raw is not None:
                try:
                    timeout = float(timeout_raw)
                except (TypeError, ValueError):
                    raise CapabilityError(
                        manifest.name, f"tool '{name}' has invalid timeout"
                    ) from None
                if timeout <= 0:
                    raise CapabilityError(manifest.name, f"tool '{name}' timeout must be positive")
            tools.append(
                PluginToolSpec(
                    name=name,
                    handler=handler,
                    description=str(raw.get("description") or ""),
                    input_schema=(
                        raw.get("input_schema")
                        if isinstance(raw.get("input_schema"), dict)
                        else {}
                    ),
                    output_schema=(
                        raw.get("output_schema")
                        if isinstance(raw.get("output_schema"), dict)
                        else {}
                    ),
                    permission=permission,
                    visibility=visibility,
                    skill=skill,
                    timeout=timeout,
                    plugin=manifest.name,
                    plugin_root=str(manifest.root),
                )
            )
    return tools


def _skill_root(location: Path, roots: list[Path]) -> Path:
    for root in roots:
        if location.is_relative_to(root):
            return root
    return location.parent


def declared_skill_roots(manifest: PluginManifest) -> list[Path]:
    """user:“技能根也是资源根”+清单声明的 skills 目录无论有没有 SKILL.md
    都进装配：技能索引只认 SKILL.md，但 read_file 的可搜索路径要认根。
    """
    try:
        return [path for path in _declared_paths(manifest, "skills") if path.is_dir()]
    except CapabilityError:
        return []


def _read_skills(manifest: PluginManifest) -> list[PluginSkillSpec]:
    roots = [path for path in _declared_paths(manifest, "skills") if path.is_dir()]
    if not roots:
        return []
    registry = SkillRegistry(explicit_roots=roots)
    skills: list[PluginSkillSpec] = []
    seen: set[str] = set()
    for skill in registry.available(None):
        if skill.name in seen:
            raise CapabilityError(manifest.name, f"duplicate skill name '{skill.name}'")
        seen.add(skill.name)
        skills.append(
            PluginSkillSpec(
                name=skill.name,
                description=skill.description,
                location=skill.location,
                plugin=manifest.name,
                root=_skill_root(skill.location, roots),
            )
        )
    return skills


def _read_hooks(manifest: PluginManifest) -> list[PluginHookSpec]:
    hooks: list[PluginHookSpec] = []
    for path in _declared_paths(manifest, "hooks"):
        data = _load_jsonc(manifest, path)
        section = data.get("hooks") if isinstance(data, dict) else None
        if not isinstance(section, dict):
            raise CapabilityError(manifest.name, f"{path.name} must contain a 'hooks' object")
        for event, groups in section.items():
            if event not in HOOK_EVENTS:
                raise CapabilityError(manifest.name, f"unknown hook event '{event}'")
            if not isinstance(groups, list):
                raise CapabilityError(manifest.name, f"hook event '{event}' must be a list")
            for group in groups:
                if not isinstance(group, dict):
                    raise CapabilityError(manifest.name, f"hook event '{event}' group must be an object")
                matcher = str(group.get("matcher") or "*")
                handlers = group.get("hooks")
                if not isinstance(handlers, list):
                    raise CapabilityError(
                        manifest.name, f"hook event '{event}' group must contain a 'hooks' list"
                    )
                clean_handlers: list[dict[str, Any]] = []
                for handler in handlers:
                    if not isinstance(handler, dict):
                        raise CapabilityError(
                            manifest.name, f"hook event '{event}' handler must be an object"
                        )
                    handler_type = str(handler.get("type") or "command")
                    if handler_type not in VALID_HOOK_HANDLERS:
                        raise CapabilityError(
                            manifest.name,
                            f"hook event '{event}' has unsupported handler type '{handler_type}'",
                        )
                    clean_handlers.append(dict(handler))
                hooks.append(
                    PluginHookSpec(
                        event=event,
                        matcher=matcher,
                        handlers=tuple(clean_handlers),
                        plugin=manifest.name,
                    )
                )
    return hooks


def _read_mcp(manifest: PluginManifest) -> list[Path]:
    paths = _declared_paths(manifest, "mcp")
    for path in paths:
        data = _load_jsonc(manifest, path)
        if not isinstance(data, dict) or not isinstance(data.get("mcpServers"), dict):
            raise CapabilityError(manifest.name, f"{path.name} must contain an 'mcpServers' object")
    return paths


def _read_commands(manifest: PluginManifest) -> list[PluginCommandSpec]:
    raw = manifest.raw.get("commands")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CapabilityError(manifest.name, "commands must be an array")
    commands: list[PluginCommandSpec] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise CapabilityError(manifest.name, f"commands[{index}] must be an object")
        name = str(item.get("name") or "").strip().lstrip("/").lower()
        if not name or any(character.isspace() for character in name):
            raise CapabilityError(manifest.name, f"commands[{index}] name must be one token")
        if name in seen:
            raise CapabilityError(manifest.name, f"duplicate command name '{name}'")
        seen.add(name)
        operation = str(item.get("operation") or "").strip()
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        effect = item.get("effect") if isinstance(item.get("effect"), dict) else {}
        if not operation and not effect:
            raise CapabilityError(
                manifest.name, f"command '{name}' needs an operation or an effect"
            )
        commands.append(
            PluginCommandSpec(
                name=name,
                title=str(item.get("title") or name).strip() or name,
                description=str(item.get("description") or "").strip(),
                operation=operation,
                payload=dict(payload),
                effect=dict(effect),
                plugin=manifest.name,
            )
        )
    return commands


def _read_context(manifest: PluginManifest) -> list[PluginContextSpec]:
    raw = manifest.raw.get("context")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CapabilityError(manifest.name, "context must be an array")
    entries: list[PluginContextSpec] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise CapabilityError(manifest.name, f"context[{index}] must be an object")
        text = str(item.get("file") or "").strip()
        if not text:
            raise CapabilityError(manifest.name, f"context[{index}] is missing file")
        if not text.startswith("./"):
            raise CapabilityError(
                manifest.name, f"context[{index}] file must start with './': {text}"
            )
        candidate = (manifest.root / text[2:]).resolve()
        if not candidate.is_relative_to(manifest.root):
            raise CapabilityError(
                manifest.name, f"context[{index}] file is outside the plugin root: {text}"
            )
        order_raw = item.get("order", 50)
        if isinstance(order_raw, bool) or not isinstance(order_raw, int):
            raise CapabilityError(manifest.name, f"context[{index}] order must be an integer")
        entries.append(PluginContextSpec(file=candidate, order=order_raw, plugin=manifest.name))
    return entries


def read_capabilities(manifest: PluginManifest) -> PluginCapabilities:
    """Read every declared capability, raising on the first broken declaration."""
    return PluginCapabilities(
        plugin=manifest.name,
        tools=_read_tools(manifest),
        skills=_read_skills(manifest),
        hooks=_read_hooks(manifest),
        mcp_files=_read_mcp(manifest),
        commands=_read_commands(manifest),
        context=_read_context(manifest),
    )


@dataclass
class CapabilityAssembly:
    plugins: dict[str, PluginCapabilities] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    tools: list[PluginToolSpec] = field(default_factory=list)
    skills: list[PluginSkillSpec] = field(default_factory=list)
    skill_roots: list[Path] = field(default_factory=list)
    hooks: list[PluginHookSpec] = field(default_factory=list)
    mcp_files: list[Path] = field(default_factory=list)
    commands: list[PluginCommandSpec] = field(default_factory=list)
    context: list[PluginContextSpec] = field(default_factory=list)


def assemble_capabilities(manifests: list[PluginManifest]) -> CapabilityAssembly:
    """Flatten enabled plugins into one namespace with explicit conflicts."""
    assembly = CapabilityAssembly()
    seen_tools: dict[str, str] = {}
    seen_commands: dict[str, str] = {}
    seen_skills: dict[str, str] = {}
    for manifest in manifests:
        if not manifest.enabled:
            continue
        try:
            capabilities = read_capabilities(manifest)
        except CapabilityError as exc:
            assembly.errors.append({"plugin": manifest.name, "error": exc.message})
            continue
        assembly.plugins[manifest.name] = capabilities
        # 声明根全量进表（资源可达性），发现到的技能根必在其中。
        for root in declared_skill_roots(manifest):
            if root not in assembly.skill_roots:
                assembly.skill_roots.append(root)
        for tool in capabilities.tools:
            if tool.name in seen_tools:
                assembly.errors.append(
                    {
                        "plugin": manifest.name,
                        "error": f"tool '{tool.name}' conflicts with plugin '{seen_tools[tool.name]}'",
                    }
                )
                continue
            seen_tools[tool.name] = manifest.name
            assembly.tools.append(tool)
        for command in capabilities.commands:
            if command.name in seen_commands:
                assembly.errors.append(
                    {
                        "plugin": manifest.name,
                        "error": f"command '{command.name}' conflicts with plugin '{seen_commands[command.name]}'",
                    }
                )
                continue
            seen_commands[command.name] = manifest.name
            assembly.commands.append(command)
        for skill in capabilities.skills:
            if skill.name in seen_skills:
                assembly.errors.append(
                    {
                        "plugin": manifest.name,
                        "error": f"skill '{skill.name}' conflicts with plugin '{seen_skills[skill.name]}'",
                    }
                )
                continue
            seen_skills[skill.name] = manifest.name
            assembly.skills.append(skill)
        assembly.hooks.extend(capabilities.hooks)
        assembly.mcp_files.extend(capabilities.mcp_files)
        assembly.context.extend(capabilities.context)
    assembly.context.sort(key=lambda item: (item.order, item.file.name))
    return assembly


__all__ = [
    "HOOK_EVENTS",
    "VALID_HOOK_HANDLERS",
    "VALID_TOOL_PERMISSIONS",
    "VALID_TOOL_VISIBILITY",
    "CapabilityAssembly",
    "CapabilityError",
    "PluginCapabilities",
    "PluginCommandSpec",
    "PluginContextSpec",
    "PluginHookSpec",
    "PluginSkillSpec",
    "PluginToolSpec",
    "assemble_capabilities",
    "read_capabilities",
]
