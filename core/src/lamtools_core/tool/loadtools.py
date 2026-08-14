"""Load-tools configuration: mode-based tool set management.

Controls which tools are advertised to the model (LLM request ``tools`` array)
and injects the active mode into the system prompt so the agent knows its
current constraints.

Separate from ``access_tools.jsonc`` which controls approval gating at
execution time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from lamtools_core.llm.profiles import strip_jsonc

type ModeName = str


@dataclass
class LoadToolMode:
    """A named tool-set mode."""

    description: str = ""
    tools: list[str] = field(default_factory=list)

    @property
    def tool_set(self) -> set[str]:
        return {t for t in self.tools if t.strip()}

    @property
    def is_full_access(self) -> bool:
        """Empty tools list means all tools are allowed."""
        return len(self.tool_set) == 0


LoadTools = dict[ModeName, LoadToolMode]


def load_loadtools(path: Path | str) -> LoadTools:
    """Load a ``loadtools.jsonc`` file and return a mode-name → LoadToolMode map.

    Returns an empty dict when the file is missing, unreadable, or invalid.
    Comment lines are stripped so files with a human-readable header (see
    :func:`serialize_loadtools`) parse cleanly. Uses the shared
    string-context-aware stripper so ``//`` inside quoted values (URLs)
    survives (audit 09 S3).
    """
    result: LoadTools = {}
    try:
        # utf-8-sig: a BOM must not silently void the whole file (audit 09 S3).
        raw = Path(path).read_text(encoding="utf-8-sig")
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return result
    try:
        data = json.loads(strip_jsonc(raw))
    except json.JSONDecodeError:
        return result
    if not isinstance(data, dict):
        return result
    modes = data.get("modes")
    if not isinstance(modes, dict):
        return result
    for name, entry in modes.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(entry, dict):
            continue
        description = str(entry.get("description") or "").strip()
        tools_raw = entry.get("tools")
        tools: list[str] = []
        if isinstance(tools_raw, list):
            tools = [str(t) for t in tools_raw if isinstance(t, str) and str(t).strip()]
        result[name.strip()] = LoadToolMode(description=description, tools=tools)
    return result


def mode_tool_set(
    load_tools: LoadTools,
    active_mode: str | None,
) -> set[str] | None:
    """Return the tool-name set for *active_mode*, or None when unfiltered.

    Returns:
        ``set[str]`` – the whitelist of tool names.
        ``None`` – mode not recognised or full-access mode → no filtering needed.
    """
    if not active_mode:
        return None
    mode = load_tools.get(active_mode)
    if mode is None:
        return None
    if mode.is_full_access:
        return None
    return mode.tool_set


def mode_prompt_line(
    load_tools: LoadTools,
    active_mode: str | None,
) -> str:
    """Build a system-prompt line describing the current mode (or empty string)."""
    if not active_mode:
        return ""
    mode = load_tools.get(active_mode)
    if mode is None:
        return ""
    desc = mode.description or active_mode
    return f"当前模式: {active_mode} — {desc}"


def mode_names(load_tools: LoadTools) -> list[str]:
    """Return the list of available mode names."""
    return list(load_tools.keys())


def serialize_loadtools(load_tools: LoadTools) -> str:
    """Serialize a LoadTools map to the ``loadtools.jsonc`` file format.

    The output is plain JSON (a JSONC superset) so the file stays
    human-editable; a leading comment documents the "empty list = all tools"
    semantics for the reader.
    """
    body = {
        "modes": {
            name: {
                "description": mode.description,
                "tools": list(mode.tools),
            }
            for name, mode in load_tools.items()
        }
    }
    header = (
        "// loadtools.jsonc — 模式工具集配置\n"
        "// 每个模式是一个工具白名单：tools 为空数组表示该模式可使用全部工具（不限制）。\n"
    )
    return header + json.dumps(body, ensure_ascii=False, indent=2) + "\n"


def default_load_tools() -> LoadTools:
    """Return a built-in default (consider + execute) suitable for Core."""
    return LoadTools({
        "consider": LoadToolMode(
            description="思索模式：仅使用只读工具进行分析和调研，不修改任何文件",
            tools=[
                "read_file", "list_dir", "search_files", "search_content",
                "web_search", "web_fetch", "git_status", "git_diff",
                "load_skill", "sub_agent",
            ],
        ),
        "execute": LoadToolMode(
            description="执行模式：可使用全部工具进行完整的代码操作",
            tools=[],
        ),
        "workflow": LoadToolMode(
            description="工作流模式：操作工作流图与查阅资料，不直接改项目文件",
            tools=[
                "read_file", "list_dir", "search_files", "search_content",
                "web_fetch", "load_skill", "sub_agent",
                "goal", "arrange",
                "workflow_graph", "workflow_add_node", "workflow_connect",
                "workflow_delete_node", "workflow_update_node",
            ],
        ),
    })


__all__ = [
    "LoadToolMode",
    "LoadTools",
    "ModeName",
    "default_load_tools",
    "load_loadtools",
    "mode_names",
    "mode_prompt_line",
    "mode_tool_set",
    "serialize_loadtools",
]
