"""Session-scoped composer input parameter group.

user:“架构调整，输入框的信息作为‘输入参数组’按会话持久化保存包括模式权限模型思考以及输入信息”
+(每个会话记住自己的模式、权限、模型与思考档位；回合运行中改模式/权限/思考要在下一步生效，
模型仍按回合生效。这里只负责这组参数的规范化、读写与叠加，不持有任何运行时状态。)

The block lives at the top level of session metadata instead of inside
``runtime_preferences``: the latter is deliberately limited to the permission
dimension by ``merge_session_runtime_preferences``, which would drop any extra
nested key on the next PATCH.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from lamtools_core.llm.reasoning import normalize_reasoning_level

from .runtime_permissions import (
    normalize_permission_preset,
    session_runtime_preferences,
    with_session_runtime_preferences,
)

COMPOSER_STATE_KEY = "composer_state"

COMPOSER_ACTIVE_MODES: tuple[str, ...] = ("consider", "execute")
DEFAULT_COMPOSER_ACTIVE_MODE = "execute"

# Keys a live run may apply at its next step.  ``model_id`` is intentionally
# absent: the product keeps the model bound to the current turn.
LIVE_COMPOSER_KEYS: tuple[str, ...] = (
    "active_mode",
    "reasoning_level",
    "shallow_thinking_enabled",
    "permission_preset",
)


def normalize_composer_active_mode(value: object, fallback: str = DEFAULT_COMPOSER_ACTIVE_MODE) -> str:
    mode = str(value or "").strip()
    if mode in COMPOSER_ACTIVE_MODES:
        return mode
    fallback_mode = str(fallback or "").strip()
    return fallback_mode if fallback_mode in COMPOSER_ACTIVE_MODES else DEFAULT_COMPOSER_ACTIVE_MODE


def _first_present(*values: object) -> object | None:
    for value in values:
        if value is not None:
            return value
    return None


def normalize_composer_state(
    value: object,
    *,
    fallback: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a fully populated, validated composer parameter group."""
    raw = value if isinstance(value, Mapping) else {}
    base = fallback if isinstance(fallback, Mapping) else {}

    active_mode = normalize_composer_active_mode(
        _first_present(raw.get("active_mode"), raw.get("activeMode"), base.get("active_mode")),
        normalize_composer_active_mode(base.get("active_mode")),
    )
    model_id = str(
        _first_present(raw.get("model_id"), raw.get("modelId"), base.get("model_id")) or ""
    ).strip()
    reasoning_level = normalize_reasoning_level(
        _first_present(
            raw.get("reasoning_level"),
            raw.get("reasoningLevel"),
            base.get("reasoning_level"),
        ),
        normalize_reasoning_level(base.get("reasoning_level"), "off"),
    )
    raw_shallow = _first_present(
        raw.get("shallow_thinking_enabled"),
        raw.get("shallowThinkingEnabled"),
        base.get("shallow_thinking_enabled"),
    )
    shallow = raw_shallow if isinstance(raw_shallow, bool) else False

    raw_preset = _first_present(
        raw.get("permission_preset"),
        raw.get("permissionPreset"),
        base.get("permission_preset"),
    )
    try:
        permission_preset = normalize_permission_preset(
            raw_preset if raw_preset is not None else base.get("permission_preset")
        )
    except ValueError:
        permission_preset = normalize_permission_preset(None)

    return {
        "active_mode": active_mode,
        "model_id": model_id,
        "reasoning_level": reasoning_level,
        "shallow_thinking_enabled": shallow,
        "permission_preset": permission_preset,
    }


def composer_state_from_metadata(metadata: object) -> dict[str, Any]:
    """Read the group, falling back to the legacy keys each field used before."""
    raw_metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
    preferences = session_runtime_preferences(raw_metadata)
    fallback = {
        "model_id": raw_metadata.get("model_id"),
        "permission_preset": preferences.get("permission_preset"),
    }
    return normalize_composer_state(raw_metadata.get(COMPOSER_STATE_KEY), fallback=fallback)


def with_composer_state(
    metadata: object,
    state: object,
    *,
    global_controls: object | None = None,
) -> dict[str, Any]:
    """Merge the group into session metadata and keep legacy mirrors in sync.

    ``model_id`` stays at the top level because the auto-title path still reads
    it, and the permission preset stays authoritative in
    ``runtime_preferences`` so existing permission resolution keeps working.
    """
    result = dict(metadata) if isinstance(metadata, Mapping) else {}
    normalized = normalize_composer_state(state, fallback=composer_state_from_metadata(result))
    result[COMPOSER_STATE_KEY] = normalized
    if normalized["model_id"]:
        result["model_id"] = normalized["model_id"]
    else:
        result.pop("model_id", None)
    return with_session_runtime_preferences(
        result,
        global_controls=global_controls,
        permission_preset=normalized["permission_preset"],
    )


def composer_state_patch(
    metadata: object,
    *,
    active_mode: object = None,
    model_id: object = None,
    reasoning_level: object = None,
    shallow_thinking_enabled: object = None,
    permission_preset: object = None,
) -> dict[str, Any]:
    """Build the group for a partial update without losing untouched fields."""
    current = composer_state_from_metadata(metadata)
    return normalize_composer_state(
        {
            "active_mode": active_mode,
            "model_id": model_id,
            "reasoning_level": reasoning_level,
            "shallow_thinking_enabled": shallow_thinking_enabled,
            "permission_preset": permission_preset,
        },
        fallback=current,
    )


def live_composer_patch(state: object) -> dict[str, Any]:
    """Return only the keys a running turn may apply at its next step."""
    normalized = normalize_composer_state(state)
    return {key: deepcopy(normalized[key]) for key in LIVE_COMPOSER_KEYS}


def overlay_composer_controls(
    snapshot: object,
    metadata: object,
    *,
    include_model: bool = False,
) -> dict[str, Any]:
    """Overlay the session's group onto a turn runtime snapshot.

    Used by resume/approval continuations: mode, thinking level, and the
    shallow toggle follow the session's current values, while the model stays
    bound to the parked turn unless ``include_model`` is explicitly requested.

    Only fields that were explicitly stored in ``composer_state`` are applied.
    A legacy/plugin/auxiliary session without the block keeps whatever the
    parked turn or the plugin surface decided; inventing product defaults here
    would silently turn a study/plugin mode into ``execute``.
    """
    merged = dict(snapshot) if isinstance(snapshot, Mapping) else {}
    raw_metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
    raw_state = raw_metadata.get(COMPOSER_STATE_KEY)
    if not isinstance(raw_state, Mapping):
        return merged
    state = normalize_composer_state(raw_state)
    if "active_mode" in raw_state or "activeMode" in raw_state:
        merged["active_mode"] = state["active_mode"]
    if "reasoning_level" in raw_state or "reasoningLevel" in raw_state:
        merged["reasoning_level"] = state["reasoning_level"]
    if "shallow_thinking_enabled" in raw_state or "shallowThinkingEnabled" in raw_state:
        merged["shallow_thinking_enabled"] = state["shallow_thinking_enabled"]
    if include_model and state["model_id"]:
        merged["model_id"] = state["model_id"]
    return merged


def inherit_composer_params(
    params: object,
    metadata: object,
) -> dict[str, Any]:
    """Fill a turn's missing options from the session's stored group.

    Explicit caller values always win; this only covers clients and automatic
    turns that do not repeat the Composer parameters.  Permission is resolved
    separately from ``runtime_preferences`` and is deliberately not copied.
    """
    merged = dict(params) if isinstance(params, Mapping) else {}
    raw_metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
    raw_state = raw_metadata.get(COMPOSER_STATE_KEY)
    if not isinstance(raw_state, Mapping):
        return merged
    state = normalize_composer_state(raw_state)
    aliases = {
        "active_mode": ("active_mode", "activeMode"),
        "model_id": ("model_id", "modelId"),
        "reasoning_level": ("reasoning_level", "reasoningLevel"),
        "shallow_thinking_enabled": (
            "shallow_thinking_enabled",
            "shallowThinkingEnabled",
        ),
    }
    for key, names in aliases.items():
        if any(name in merged and merged[name] is not None for name in names):
            continue
        if key in raw_state or any(name in raw_state for name in names[1:]):
            merged[key] = deepcopy(state[key])
    return merged


__all__ = [
    "COMPOSER_ACTIVE_MODES",
    "COMPOSER_STATE_KEY",
    "DEFAULT_COMPOSER_ACTIVE_MODE",
    "LIVE_COMPOSER_KEYS",
    "composer_state_from_metadata",
    "composer_state_patch",
    "inherit_composer_params",
    "live_composer_patch",
    "normalize_composer_active_mode",
    "normalize_composer_state",
    "overlay_composer_controls",
    "with_composer_state",
]
