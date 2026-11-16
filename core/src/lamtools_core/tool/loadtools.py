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

# user:“将现有的consider，excute迭代为 super Agent、chat、work”+(旧名字不再是一等模式，
# 读旧配置时映射到新名字；用户自己写的工具清单原样带过去，只改名不改内容)。
LEGACY_MODE_NAMES: dict[str, str] = {"consider": "chat", "execute": "work", "superagent": "auto"}


def load_loadtools(path: Path | str) -> LoadTools:
    """Load ``loadtools.jsonc`` and return the three canonical modes.

    A missing or unreadable file still yields chat / work / auto, so a new
    session can always pick a mode.
    """
    return _with_default_modes(_parse_loadtools(path))


def _parse_loadtools(path: Path | str) -> LoadTools:
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


def _with_default_modes(loaded: LoadTools) -> LoadTools:
    """Rename legacy modes and fill in any mode the file does not define.

    user:“新建会话时选择好，就不可变动了”+(三种模式必须始终存在，否则新建会话选不出
    模式；旧配置里只有 consider/execute 时也要能开起来)。
    """
    merged: LoadTools = {}
    # 同一个文件里新旧名字都写了时，以新名字为准。
    for name, mode in loaded.items():
        if name not in LEGACY_MODE_NAMES:
            merged.setdefault(name, mode)
    for name, mode in loaded.items():
        if name in LEGACY_MODE_NAMES:
            merged.setdefault(LEGACY_MODE_NAMES[name], mode)
    for name, mode in default_load_tools().items():
        merged.setdefault(name, mode)
    return merged


def mode_tool_set(
    load_tools: LoadTools,
    active_mode: str | None,
) -> set[str] | None:
    """Return the tool-name set for *active_mode*, or None when unfiltered.

    Returns:
        ``set[str]`` – the whitelist of tool names.
        ``None`` – mode not recognised or full-access mode → no filtering needed.
    """
    # The mode whitelist is the single source of what the model may see, so a
    # planning mode must not advertise tools it can never run.  ``run_command``
    # stays in the consider list on purpose: it is one tool whose per-command
    # level decides whether a specific command is allowed, which is why the
    # former "never filter by name in consider" shortcut was wrong — it also
    # advertised every write tool.
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
    return f"Current mode: {active_mode} — {desc}"


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


_READ_ONLY_TOOLS: list[str] = [
    "read_file", "list_dir", "search_files", "search_content",
    "web_search", "web_fetch", "git_status", "git_diff",
    "load_skill", "memory", "message",
    # user:“ok，那就这么做”+(分析模式也可查阅当前会话的历史原文)。
    "search_context", "recall_context",
]


def default_load_tools() -> LoadTools:
    """Return the built-in modes: chat, work, auto.

    user:“我觉得它应该是一种运行模式，将现有的consider，excute迭代为 super Agent、
    chat、work”+(三种模式的区别是这条会话自己留下多少活：聊天一点不干，工作全干，
    Super Agent 只留对话、判断和派工，活交给带独立工作区的子代理)。
    """
    return LoadTools({
        "chat": LoadToolMode(
            description="聊天模式：只用只读工具讨论、调研、分析，不改动任何文件",
            tools=[*_READ_ONLY_TOOLS, "run_command"],
        ),
        "work": LoadToolMode(
            description="工作模式：使用全部工具，在这一轮里把事做完",
            tools=[],
        ),
        "auto": LoadToolMode(
            description=(
                "智能模式（auto）：你只对话、判断和派工，不自己改文件也不跑命令。"
                "把目标交给带独立工作区的子代理，等它汇报后再回复用户"
            ),
            tools=[*_READ_ONLY_TOOLS, "question", "sub_agent", "sub_agent_message"],
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
