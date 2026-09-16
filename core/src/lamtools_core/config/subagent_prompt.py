"""Sub-agent delegation guide prompt.

Loads a natural-language markdown guide that teaches the running (parent)
agent how and when to use the ``sub_agent`` tool, and injects it into the
system prompt. The guide is plain markdown (no frontmatter).

Resolution is a first-existing-wins fallback chain (same shape as the
loadtools/access_tools loaders):

  1. Project:  ``{work_root}/.lam/config/subagent/guide.md``
  2. Global:    ``{core_config_dir}/subagent/guide.md`` (``~/.lam/core/config`` by default; beside the app when ``LAMTOOLS_HOME`` is set)
  3. Legacy:    ``{lam_home}/config/subagent/guide.md`` (read fallback for pre-unification installs)
  4. Built-in:  :data:`DEFAULT_SUBAGENT_GUIDE` (module constant)

Members inherit this loader automatically because it lives in
``lamtools_core.config``. The user can author a custom guide as a plain
markdown file in either the project or the global location.
"""

from __future__ import annotations

import json
from pathlib import Path

from lamtools_core.config.root import core_config_dir, legacy_user_config_dir

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
DELEGATION_STRATEGY_KEY = "delegation_strategy"
DELEGATION_STRATEGIES = ("forbidden", "low", "medium", "high")
DEFAULT_DELEGATION_STRATEGY = "medium"
DEFAULT_SUBAGENT_SETTINGS: dict[str, object] = {
    "default_multimodal_model": "",
    DELEGATION_STRATEGY_KEY: DEFAULT_DELEGATION_STRATEGY,
}

ROLE_ASSIGNMENTS_KEY = "role_assignments"
ROLE_ASSIGNMENT_TYPES = ("consider", "execute")
ROLE_ASSIGNMENT_REASONING_LEVELS = ("off", "light", "medium", "high", "xhigh", "max")
_REASONING_LEVEL_INDEX = {
    level: index for index, level in enumerate(ROLE_ASSIGNMENT_REASONING_LEVELS)
}


def subagent_guide_dirs(work_root: str | Path | None) -> list[Path]:
    """Return candidate directories, project scope first then global."""
    dirs: list[Path] = []
    if work_root:
        dirs.append(Path(work_root).resolve() / ".lam" / "config" / SUBAGENT_DIR)
    # Unified config directory first; legacy {lam_home}/config keeps working
    # as a read-only fallback for pre-unification installs.
    dirs.append(core_config_dir() / SUBAGENT_DIR)
    legacy = legacy_user_config_dir() / SUBAGENT_DIR
    if legacy != core_config_dir() / SUBAGENT_DIR:
        dirs.append(legacy)
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
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if text.strip():
            return text
    return DEFAULT_SUBAGENT_GUIDE


def guide_path_for_scope(scope: str, work_root: str | Path | None) -> Path:
    """Return the writable guide path for ``scope`` ("project" or "global")."""
    if scope == "project" and work_root:
        return Path(work_root).resolve() / ".lam" / "config" / SUBAGENT_DIR / GUIDE_FILENAME
    return core_config_dir() / SUBAGENT_DIR / GUIDE_FILENAME


def write_subagent_guide(content: str, *, scope: str, work_root: str | Path | None) -> Path:
    """Persist ``content`` to the guide file for ``scope`` and return its path."""
    path = guide_path_for_scope(scope, work_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    from lamtools_core.config.root import atomic_write_text

    atomic_write_text(path, content)
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


def _read_settings_file(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(data) if isinstance(data, dict) else {}


def _global_settings_path() -> Path | None:
    """Return the configured global settings path, including legacy fallback."""
    for directory in subagent_guide_dirs(None):
        path = directory / SETTINGS_FILENAME
        if path.is_file():
            return path
    return None


def load_local_subagent_settings(
    scope: str,
    work_root: str | Path | None = None,
) -> dict[str, object]:
    """Load only one writable scope without injecting defaults.

    Missing keys stay missing so a project file that only changes another
    setting cannot accidentally shadow global role assignments with a
    synthesized empty list.
    """
    if scope not in ("project", "global"):
        raise ValueError("scope must be 'project' or 'global'")
    if scope == "project":
        if not work_root:
            return {}
        path = settings_path_for_scope(scope, work_root)
    else:
        path = settings_path_for_scope(scope, work_root)
    return _read_settings_file(path)


def _role_assignment_key(task_type: object) -> str:
    return str(task_type or "").strip().casefold()


def normalize_delegation_strategy(value: object) -> str:
    """Validate one persisted sub-agent delegation strategy."""
    if not isinstance(value, str):
        raise ValueError("delegation_strategy must be a string")
    strategy = value.strip().lower()
    if strategy not in DELEGATION_STRATEGIES:
        allowed = ", ".join(DELEGATION_STRATEGIES)
        raise ValueError(f"delegation_strategy must be one of: {allowed}")
    return strategy


def load_effective_delegation_strategy(
    work_root: str | Path | None = None,
) -> str:
    """Resolve global baseline plus an explicit project override.

    Missing and invalid hand-edited values degrade safely to the inherited
    value, with ``medium`` as the legacy/built-in fallback.
    """
    strategy = load_global_delegation_strategy()
    project_settings = load_local_subagent_settings("project", work_root)
    if DELEGATION_STRATEGY_KEY in project_settings:
        try:
            strategy = normalize_delegation_strategy(
                project_settings[DELEGATION_STRATEGY_KEY]
            )
        except ValueError:
            pass
    return strategy


def load_global_delegation_strategy() -> str:
    """Return the global strategy or the built-in ``medium`` fallback."""
    global_path = _global_settings_path()
    global_settings = _read_settings_file(global_path) if global_path else {}
    if DELEGATION_STRATEGY_KEY not in global_settings:
        return DEFAULT_DELEGATION_STRATEGY
    try:
        return normalize_delegation_strategy(
            global_settings[DELEGATION_STRATEGY_KEY]
        )
    except ValueError:
        return DEFAULT_DELEGATION_STRATEGY


_DELEGATION_STRATEGY_PROMPTS = {
    "forbidden": "当前子代理委派策略：禁止委派子代理。",
    "low": "当前子代理委派策略：仅在大范围调查、探索时委派子代理。",
    "medium": "当前子代理委派策略：保持当前默认委派策略。",
    "high": (
        "当前子代理委派策略：必须先制定计划并由用户确认；确认后立即生成高中心化 "
        "Checklist，尽可能由多个子代理并行推进，主 Agent 统一负责决策指挥、任务分配、"
        "依赖协调、冲突调解、结果整合与最终验收。"
    ),
}


def render_delegation_strategy_prompt(work_root: str | Path | None = None) -> str:
    """Render the effective strategy as stable leading-system discipline."""
    strategy = load_effective_delegation_strategy(work_root)
    return (
        "## Sub-agent 委派策略\n"
        "本策略优先于通用委派指南与角色建议。\n"
        + _DELEGATION_STRATEGY_PROMPTS[strategy]
    )


def normalize_reasoning_level(value: object) -> str:
    """Normalize one role-assignment reasoning level or raise ``ValueError``."""
    if not isinstance(value, str):
        raise ValueError("reasoning level must be a string")
    level = value.strip().lower()
    if level == "xh":
        level = "xhigh"
    if level not in _REASONING_LEVEL_INDEX:
        allowed = ", ".join(ROLE_ASSIGNMENT_REASONING_LEVELS)
        raise ValueError(f"reasoning level must be one of: {allowed}")
    return level


def normalize_role_assignment(value: object) -> dict[str, str]:
    """Validate and normalize one persisted role-assignment rule."""
    if not isinstance(value, dict):
        raise ValueError("each role assignment must be an object")
    expected = {"task_type", "type", "model", "reasoning_min", "reasoning_max"}
    unknown = set(value) - expected
    missing = expected - set(value)
    if unknown:
        raise ValueError(f"unknown role assignment fields: {', '.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"missing role assignment fields: {', '.join(sorted(missing))}")

    raw_task_type = value.get("task_type")
    if not isinstance(raw_task_type, str):
        raise ValueError("task_type must be a string")
    task_type = raw_task_type.strip()
    if not task_type:
        raise ValueError("task_type must not be empty")
    raw_type = value.get("type")
    if not isinstance(raw_type, str):
        raise ValueError("type must be a string")
    assignment_type = raw_type.strip().lower()
    if assignment_type not in ROLE_ASSIGNMENT_TYPES:
        raise ValueError("type must be 'consider' or 'execute'")
    raw_model = value.get("model")
    if not isinstance(raw_model, str):
        raise ValueError("model must be a string")
    model = raw_model.strip()
    if not model:
        raise ValueError("model must be an exact non-empty model_id")
    reasoning_min = normalize_reasoning_level(value.get("reasoning_min"))
    reasoning_max = normalize_reasoning_level(value.get("reasoning_max"))
    if _REASONING_LEVEL_INDEX[reasoning_min] > _REASONING_LEVEL_INDEX[reasoning_max]:
        raise ValueError("reasoning_min must not be greater than reasoning_max")
    return {
        "task_type": task_type,
        "type": assignment_type,
        "model": model,
        "reasoning_min": reasoning_min,
        "reasoning_max": reasoning_max,
    }


def normalize_role_assignments(value: object) -> list[dict[str, str]]:
    """Validate a rule list, rejecting duplicate normalized task types."""
    if not isinstance(value, list):
        raise ValueError("role_assignments must be an array")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        normalized = normalize_role_assignment(item)
        key = _role_assignment_key(normalized["task_type"])
        if key in seen:
            raise ValueError(f"duplicate task_type: {normalized['task_type']}")
        seen.add(key)
        result.append(normalized)
    return result


def merge_role_assignments(
    global_rules: object,
    project_rules: object,
) -> list[dict[str, str]]:
    """Merge project rules over the global baseline by trimmed casefold task type."""
    baseline = normalize_role_assignments(global_rules)
    overrides = normalize_role_assignments(project_rules)
    merged = [dict(rule) for rule in baseline]
    positions = {
        _role_assignment_key(rule["task_type"]): index
        for index, rule in enumerate(merged)
    }
    for rule in overrides:
        key = _role_assignment_key(rule["task_type"])
        if key in positions:
            merged[positions[key]] = dict(rule)
        else:
            positions[key] = len(merged)
            merged.append(dict(rule))
    return merged


def load_effective_role_assignments(
    work_root: str | Path | None = None,
) -> list[dict[str, str]]:
    """Return global rules with project rules overriding the same task type."""
    global_path = _global_settings_path()
    global_settings = _read_settings_file(global_path) if global_path else {}
    project_settings = load_local_subagent_settings("project", work_root)
    global_rules = global_settings.get(ROLE_ASSIGNMENTS_KEY, [])
    project_rules = project_settings.get(ROLE_ASSIGNMENTS_KEY, [])
    try:
        return merge_role_assignments(global_rules, project_rules)
    except ValueError:
        # Settings edited manually should not prevent Core from starting. Each
        # invalid scope degrades independently while RPC/CLI writes stay strict.
        try:
            global_normalized = normalize_role_assignments(global_rules)
        except ValueError:
            global_normalized = []
        try:
            project_normalized = normalize_role_assignments(project_rules)
        except ValueError:
            project_normalized = []
        return merge_role_assignments(global_normalized, project_normalized)


def load_subagent_settings(work_root: str | Path | None = None) -> dict[str, object]:
    """Load effective sub-agent settings (global baseline + project override).

    Returns a dict with at least ``default_multimodal_model``.
    """
    global_path = _global_settings_path()
    global_settings = _read_settings_file(global_path) if global_path else {}
    project_settings = load_local_subagent_settings("project", work_root)
    settings = {**DEFAULT_SUBAGENT_SETTINGS, **global_settings, **project_settings}
    settings[ROLE_ASSIGNMENTS_KEY] = load_effective_role_assignments(work_root)
    settings[DELEGATION_STRATEGY_KEY] = load_effective_delegation_strategy(work_root)
    return settings


def render_role_assignments_prompt(work_root: str | Path | None = None) -> str:
    """Render effective role assignments as a stable system-prompt section."""
    rules = load_effective_role_assignments(work_root)
    if not rules:
        return ""
    lines = [
        "## Sub-agent 角色分配",
        "匹配任务类型时，优先使用对应的类型、模型与思考强度范围；未匹配时按实际任务选择。",
    ]
    for rule in rules:
        lines.append(
            "- 任务类型：{task_type}；类型：{type}；建议模型：{model}；"
            "建议思考强度：{reasoning_min}–{reasoning_max}".format(**rule)
        )
    return "\n".join(lines)


def resolve_default_multimodal_model(work_root: str | Path | None = None) -> str | None:
    """Resolve the model to delegate multimodal work to.

    Returns the user-configured ``default_multimodal_model`` (settings) when
    set; otherwise the first model in the store whose jsonc declares
    ``capability: "multimodal"`` (ModelStore ``list_sync`` model_id order).
    ``None`` when neither exists — callers should then omit a concrete model.
    """
    configured = str(
        load_subagent_settings(work_root).get("default_multimodal_model") or ""
    ).strip()
    if configured:
        return configured
    from lamtools_core.config.model_store import ModelStore

    for model in ModelStore().list_sync(work_root=work_root):
        if model.resolved_capability == "multimodal":
            return model.model_id
    return None


def settings_path_for_scope(scope: str, work_root: str | Path | None) -> Path:
    """Return the writable settings path for ``scope`` ("project" or "global")."""
    if scope == "project" and work_root:
        return Path(work_root).resolve() / ".lam" / "config" / SUBAGENT_DIR / SETTINGS_FILENAME
    return core_config_dir() / SUBAGENT_DIR / SETTINGS_FILENAME


def write_subagent_settings(updates: dict[str, object], *, scope: str, work_root: str | Path | None) -> Path:
    """Merge ``updates`` into the settings file for ``scope`` and return its path."""
    path = settings_path_for_scope(scope, work_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_settings_file(path)
    updates = dict(updates)
    if DELEGATION_STRATEGY_KEY in updates:
        if updates[DELEGATION_STRATEGY_KEY] is None:
            existing.pop(DELEGATION_STRATEGY_KEY, None)
            updates.pop(DELEGATION_STRATEGY_KEY)
        else:
            updates[DELEGATION_STRATEGY_KEY] = normalize_delegation_strategy(
                updates[DELEGATION_STRATEGY_KEY]
            )
    if ROLE_ASSIGNMENTS_KEY in updates:
        updates[ROLE_ASSIGNMENTS_KEY] = normalize_role_assignments(
            updates[ROLE_ASSIGNMENTS_KEY]
        )
    existing.update(updates)
    from lamtools_core.config.root import atomic_write_text

    atomic_write_text(path, json.dumps(existing, indent=2, ensure_ascii=False))
    return path


__all__ = [
    "DEFAULT_SUBAGENT_GUIDE",
    "DEFAULT_SUBAGENT_SETTINGS",
    "DEFAULT_DELEGATION_STRATEGY",
    "DELEGATION_STRATEGIES",
    "DELEGATION_STRATEGY_KEY",
    "GUIDE_FILENAME",
    "ROLE_ASSIGNMENTS_KEY",
    "ROLE_ASSIGNMENT_REASONING_LEVELS",
    "ROLE_ASSIGNMENT_TYPES",
    "SETTINGS_FILENAME",
    "SUBAGENT_DIR",
    "guide_path_for_scope",
    "load_effective_role_assignments",
    "load_effective_delegation_strategy",
    "load_global_delegation_strategy",
    "load_local_subagent_settings",
    "load_subagent_guide",
    "load_subagent_settings",
    "merge_role_assignments",
    "normalize_reasoning_level",
    "normalize_delegation_strategy",
    "normalize_role_assignment",
    "normalize_role_assignments",
    "render_role_assignments_prompt",
    "render_delegation_strategy_prompt",
    "resolve_default_multimodal_model",
    "resolve_subagent_guide_path",
    "resolve_subagent_settings_path",
    "settings_path_for_scope",
    "subagent_guide_dirs",
    "write_subagent_guide",
    "write_subagent_settings",
]
