from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any

from lamtools_core.runtime import RuntimeState

SUB_SESSION_METADATA_KEY = "_sub_sessions"
SUB_SESSION_RUNTIME_STATES_KEY = "_sub_session_runtime_states"


@dataclass(frozen=True)
class SubSessionRef:
    agent_name: str
    agent_index: str
    session_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "agent_name": self.agent_name,
            "agent_index": self.agent_index,
            "session_id": self.session_id,
        }


class SubSessionManager:
    def __init__(self, *, metadata_key: str = SUB_SESSION_METADATA_KEY) -> None:
        self._metadata_key = metadata_key

    def get_or_create(self, parent_state: RuntimeState, agent_name: str | None = None) -> SubSessionRef:
        registry = _registry(parent_state.metadata, self._metadata_key)
        normalized = normalize_sub_session_agent_name(agent_name)
        agents = registry.setdefault("agents", {})
        existing = agents.get(normalized)
        if isinstance(existing, dict):
            ref = _ref_from_dict(existing)
            if ref is not None:
                return ref

        next_index = _next_index(registry)
        ref = SubSessionRef(
            agent_name=normalized,
            agent_index=f"{next_index:03d}",
            session_id=f"{parent_state.session_id}:sub:{next_index:03d}:{normalized}",
        )
        agents[normalized] = ref.to_dict()
        registry["next_index"] = next_index + 1
        return ref


class SubSessionRuntimeStateStore:
    def __init__(self, parent_state: RuntimeState, *, metadata_key: str = SUB_SESSION_RUNTIME_STATES_KEY) -> None:
        self._parent_state = parent_state
        self._metadata_key = metadata_key

    async def get(self, session_id: str) -> RuntimeState | None:
        states = self._states()
        raw = states.get(session_id)
        if not isinstance(raw, dict):
            return None
        runtime_keys = {"session_id", "run_id", "status", "position", "loop_state", "turn_count", "metadata"}
        data = {key: value for key, value in raw.items() if key in runtime_keys}
        if not data.get("session_id"):
            return None
        return RuntimeState(**data)

    async def save(self, state: RuntimeState) -> None:
        self._states()[state.session_id] = state.to_dict()

    def _states(self) -> dict[str, Any]:
        raw = self._parent_state.metadata.get(self._metadata_key)
        if not isinstance(raw, dict):
            raw = {}
            self._parent_state.metadata[self._metadata_key] = raw
        return raw


def normalize_sub_session_agent_name(agent_name: str | None) -> str:
    value = str(agent_name or "").strip().lower().replace(" ", "_").replace("-", "_")
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "sub"


def filter_sub_agent_tools(
    tools: list[dict[str, Any]],
    *,
    sub_agent_tool_name: str = "sub_agent",
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for tool in tools:
        name = _tool_name(tool)
        if name == sub_agent_tool_name:
            continue
        filtered.append(deepcopy(tool))
    return filtered


def _registry(metadata: dict[str, Any], key: str) -> dict[str, Any]:
    raw = metadata.get(key)
    if not isinstance(raw, dict):
        raw = {}
        metadata[key] = raw
    agents = raw.get("agents")
    if not isinstance(agents, dict):
        raw["agents"] = {}
    if not isinstance(raw.get("next_index"), int) or int(raw.get("next_index") or 0) < 1:
        raw["next_index"] = 1
    return raw


def _next_index(registry: dict[str, Any]) -> int:
    try:
        value = int(registry.get("next_index") or 1)
    except (TypeError, ValueError):
        value = 1
    return max(value, 1)


def _ref_from_dict(value: dict[str, Any]) -> SubSessionRef | None:
    agent_name = str(value.get("agent_name") or "").strip()
    agent_index = str(value.get("agent_index") or "").strip()
    session_id = str(value.get("session_id") or "").strip()
    if not agent_name or not agent_index or not session_id:
        return None
    return SubSessionRef(agent_name=agent_name, agent_index=agent_index, session_id=session_id)


def _tool_name(tool: dict[str, Any]) -> str:
    function = tool.get("function")
    if isinstance(function, dict):
        return str(function.get("name") or "")
    return str(tool.get("name") or "")


__all__ = [
    "SUB_SESSION_METADATA_KEY",
    "SUB_SESSION_RUNTIME_STATES_KEY",
    "SubSessionManager",
    "SubSessionRuntimeStateStore",
    "SubSessionRef",
    "filter_sub_agent_tools",
    "normalize_sub_session_agent_name",
]
