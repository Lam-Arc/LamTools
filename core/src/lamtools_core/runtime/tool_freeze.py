"""Freeze the model-visible tool array for one compaction cycle.

user:“像工具数组这种在前面的东西，把它冻住，有变动也不追加，等待下一次
压缩或者新会话再重建”+工具数组在请求前部，变化会让整段前缀缓存失效；
同一压缩周期内固定发送第一次看到的数组，压缩/新会话/重启后再重建。
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import threading
from typing import Any

TOOL_FREEZE_MESSAGE = "当前工具组未更新，工具数组将会在压缩或新会话更新。"

_MAX_FROZEN_SESSIONS = 128
_LOCK = threading.Lock()
#: (session_id, epoch_id) -> frozen tool dicts. Process-local on purpose: a
#: restart drops it and the next request re-freezes the freshly built array.
_FROZEN: "OrderedDict[tuple[str, str], tuple[dict[str, Any], ...]]" = OrderedDict()


def tool_freeze_epoch(state: Any) -> str:
    """Use the movable-context epoch so compaction starts a fresh freeze."""
    metadata = getattr(state, "metadata", None)
    if isinstance(metadata, dict):
        movable = metadata.get("movable_system_context")
        if isinstance(movable, dict):
            epoch_id = str(movable.get("epoch_id") or "").strip()
            if epoch_id:
                return epoch_id
    return "static"


def tool_name(tool: Any) -> str:
    """Return the model-visible name from an OpenAI-style tool dict."""
    if not isinstance(tool, dict):
        return ""
    function = tool.get("function")
    if isinstance(function, dict):
        return str(function.get("name") or "")
    return str(tool.get("name") or "")


def freeze_tool_specs(
    session_id: str,
    epoch_id: str,
    current_tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return this cycle's frozen tools, storing them on first use."""
    key = (str(session_id or ""), str(epoch_id or ""))
    with _LOCK:
        frozen = _FROZEN.get(key)
        if frozen is None:
            frozen = tuple(deepcopy(current_tools))
            _FROZEN[key] = frozen
            while len(_FROZEN) > _MAX_FROZEN_SESSIONS:
                _FROZEN.popitem(last=False)
        else:
            _FROZEN.move_to_end(key)
        return [deepcopy(tool) for tool in frozen]


def frozen_tool_names(session_id: str, epoch_id: str) -> set[str] | None:
    """Names in the frozen array, or None when this cycle has not frozen yet."""
    key = (str(session_id or ""), str(epoch_id or ""))
    with _LOCK:
        frozen = _FROZEN.get(key)
        if frozen is None:
            return None
        return {name for tool in frozen if (name := tool_name(tool))}


def prune_frozen_tools(
    session_id: str,
    epoch_id: str,
    current_names: set[str],
) -> None:
    """Drop tools that disappeared from the current model-visible surface.

    Additions still wait for compaction (the freeze contract), but a removed
    tool must not stay advertised: the model would keep calling it and every
    call would be rejected as a stale tool-group error.
    """
    key = (str(session_id or ""), str(epoch_id or ""))
    with _LOCK:
        frozen = _FROZEN.get(key)
        if frozen is None:
            return
        kept = tuple(tool for tool in frozen if tool_name(tool) in current_names)
        if len(kept) != len(frozen):
            _FROZEN[key] = kept


def frozen_tool_block_message(
    name: str,
    *,
    frozen_names: set[str] | None,
    current_names: set[str],
) -> str | None:
    """Explain a call to a tool that exists now but is not in the frozen array."""
    if frozen_names is None:
        return None
    if name in frozen_names:
        return None
    if name in current_names:
        return f"{TOOL_FREEZE_MESSAGE}（工具：{name}）"
    return None


def reset_session_tool_freeze(session_id: str) -> None:
    """Drop one session's frozen arrays (compaction or new session)."""
    target = str(session_id or "")
    with _LOCK:
        for key in [key for key in _FROZEN if key[0] == target]:
            _FROZEN.pop(key, None)


def reset_tool_freeze_cache() -> None:
    """Drop all frozen arrays; tests and process restart use this."""
    with _LOCK:
        _FROZEN.clear()
