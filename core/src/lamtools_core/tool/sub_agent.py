from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
import re
from typing import Any


@dataclass(frozen=True)
class AgentWriteScope:
    paths: tuple[str, ...]


@dataclass(frozen=True)
class SubAgentDefinition:
    name: str
    description: str
    role: str
    developer_instructions: str
    tools: tuple[str, ...]
    model: str = ""
    aliases: tuple[str, ...] = ()
    source: str = "builtin"


SUB_AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def definition_map(definitions: tuple[SubAgentDefinition, ...]) -> dict[str, SubAgentDefinition]:
    result: dict[str, SubAgentDefinition] = {}
    for definition in definitions:
        result[definition.name] = definition
        for alias in definition.aliases:
            result[normalize_agent_key(alias)] = definition
    return result


def parse_sub_agent_definition(path: Path, source: str) -> SubAgentDefinition | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    frontmatter, body = split_frontmatter(text)
    data = parse_simple_frontmatter(frontmatter)
    name = str(data.get("name") or path.stem).strip()
    if not name:
        return None
    tools = frontmatter_list(data.get("tools"))
    aliases = tuple(frontmatter_list(data.get("aliases")))
    description = str(data.get("description") or "").strip()
    role = str(data.get("role") or name).strip()
    return SubAgentDefinition(
        name=normalize_agent_key(name),
        description=description or f"{name} subagent",
        role=role,
        developer_instructions=body.strip(),
        tools=tuple(normalize_tool_name(item) for item in tools if normalize_tool_name(item)),
        model=str(data.get("model") or "").strip(),
        aliases=tuple(normalize_agent_key(item) for item in aliases if normalize_agent_key(item)),
        source=source,
    )


def validate_project_sub_agent_name(name: str) -> str:
    normalized = normalize_agent_key(name)
    if not SUB_AGENT_NAME_PATTERN.fullmatch(normalized):
        raise ValueError("Agent name must use letters, numbers, '-' or '_'")
    return normalized


def project_sub_agent_definition_path(work_root: str | Path, name: str) -> Path:
    root = Path(work_root).resolve()
    safe_name = validate_project_sub_agent_name(name)
    return root / ".lamtools" / "agents" / f"{safe_name}.md"


def render_sub_agent_definition(definition: SubAgentDefinition) -> str:
    lines = [
        "---",
        f"name: {definition.name}",
        f"description: {yaml_scalar(definition.description)}",
        f"role: {yaml_scalar(definition.role)}",
        "tools:",
    ]
    for tool in definition.tools:
        lines.append(f"  - {tool}")
    if definition.model:
        lines.append(f"model: {yaml_scalar(definition.model)}")
    if definition.aliases:
        lines.append("aliases:")
        for alias in definition.aliases:
            lines.append(f"  - {alias}")
    lines.extend(["---", definition.developer_instructions.strip(), ""])
    return "\n".join(lines)


def write_project_sub_agent_definition(work_root: str | Path, definition: SubAgentDefinition) -> SubAgentDefinition:
    safe_name = validate_project_sub_agent_name(definition.name)
    path = project_sub_agent_definition_path(work_root, safe_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = SubAgentDefinition(
        name=safe_name,
        description=definition.description.strip() or f"{safe_name} subagent",
        role=definition.role.strip() or safe_name,
        developer_instructions=definition.developer_instructions.strip(),
        tools=tuple(normalize_tool_name(tool) for tool in definition.tools if normalize_tool_name(tool)),
        model=definition.model.strip(),
        aliases=tuple(validate_project_sub_agent_name(alias) for alias in definition.aliases if alias.strip()),
        source="project",
    )
    path.write_text(render_sub_agent_definition(normalized), encoding="utf-8")
    return normalized


def delete_project_sub_agent_definition(work_root: str | Path, name: str) -> bool:
    path = project_sub_agent_definition_path(work_root, name)
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def yaml_scalar(value: str) -> str:
    clean = value.strip()
    if not clean:
        return '""'
    if re.search(r"[:#\[\]\{\},\n]", clean) or clean != clean.strip():
        return '"' + clean.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return clean


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    lines = text.splitlines()
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
    return "", text


def parse_simple_frontmatter(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key = ""
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) and current_key and line.strip().startswith("- "):
            current = data.setdefault(current_key, [])
            if isinstance(current, list):
                current.append(strip_yaml_scalar(line.strip()[2:]))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        stripped = value.strip()
        if stripped == "":
            data[current_key] = []
        elif stripped.startswith("[") and stripped.endswith("]"):
            data[current_key] = [
                strip_yaml_scalar(item) for item in stripped[1:-1].split(",") if item.strip()
            ]
        else:
            data[current_key] = strip_yaml_scalar(stripped)
    return data


def strip_yaml_scalar(value: str) -> str:
    clean = value.strip()
    if len(clean) >= 2 and clean[0] == clean[-1] and clean[0] in {"'", '"'}:
        return clean[1:-1]
    return clean


def frontmatter_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def normalize_agent_key(name: str) -> str:
    return str(name or "").strip().lower().replace(" ", "_")


def normalize_tool_name(name: str) -> str:
    return str(name or "").strip()


def is_write_capable(tools: tuple[str, ...] | list[str] | set[str] | frozenset[str]) -> bool:
    return bool({"write_file", "edit_file"} & set(tools))


def write_scope_error(
    *,
    agent_name: str,
    tools: tuple[str, ...] | list[str] | set[str] | frozenset[str],
    scope: AgentWriteScope | None,
) -> str:
    if not is_write_capable(tools):
        return ""
    if scope is None or not scope.paths:
        return (
            f"{agent_name} 是写入型子代理，启动前必须声明 write_scope，"
            "明确它允许修改或新建的文件/目录。"
        )
    return ""


def write_scope_from_options(options: dict[str, Any]) -> AgentWriteScope | None:
    raw = options.get("write_scope") or options.get("write_paths") or options.get("allowed_paths")
    paths: list[str] = []
    if isinstance(raw, str):
        paths = [raw]
    elif isinstance(raw, list):
        paths = [str(item) for item in raw]
    elif isinstance(raw, dict):
        for key in ("paths", "write_paths", "files", "directories", "create_paths"):
            value = raw.get(key)
            if isinstance(value, str):
                paths.append(value)
            elif isinstance(value, list):
                paths.extend(str(item) for item in value)
    normalized = tuple(item for item in (normalize_scope_path(path) for path in paths) if item)
    return AgentWriteScope(paths=normalized) if normalized else None


def normalize_scope_path(path: str) -> str:
    value = str(path or "").replace("\\", "/").strip().lstrip("/")
    while value.startswith("./"):
        value = value[2:]
    if not value or value.startswith("../") or "/../" in f"/{value}/":
        return ""
    return value.rstrip("/") + ("/" if value.endswith("/") else "")


def scope_allows_path(scope: AgentWriteScope | None, path: str) -> bool:
    if scope is None:
        return True
    target = normalize_scope_path(path)
    if not target:
        return False
    for pattern in scope.paths:
        base = pattern.rstrip("/")
        if any(char in pattern for char in "*?[]"):
            if fnmatch(target, pattern):
                return True
            if fnmatch(target, pattern.rstrip("/") + "/**"):
                return True
            continue
        if target == base or target.startswith(base.rstrip("/") + "/"):
            return True
    return False


def scopes_conflict(left: AgentWriteScope, right: AgentWriteScope) -> bool:
    for left_path in left.paths:
        for right_path in right.paths:
            if scope_paths_conflict(left_path, right_path):
                return True
    return False


def scope_paths_conflict(left: str, right: str) -> bool:
    if not left or not right:
        return True
    left_base = left.rstrip("/")
    right_base = right.rstrip("/")
    if any(char in left + right for char in "*?[]"):
        left_head = left_base.split("*", 1)[0].rstrip("/")
        right_head = right_base.split("*", 1)[0].rstrip("/")
        if not left_head or not right_head:
            return True
        return left_head == right_head or left_head.startswith(right_head + "/") or right_head.startswith(left_head + "/")
    return left_base == right_base or left_base.startswith(right_base + "/") or right_base.startswith(left_base + "/")
