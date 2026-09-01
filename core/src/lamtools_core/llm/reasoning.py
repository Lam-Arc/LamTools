"""Provider-neutral reasoning level semantics.

The Composer and runtime use four product levels.  Provider-specific names
and payload shapes belong to adapter profiles, not to this module.
"""

from __future__ import annotations

from typing import Literal

ReasoningLevel = Literal["off", "light", "high", "max"]
REASONING_LEVELS: tuple[ReasoningLevel, ...] = ("off", "light", "high", "max")

# Values written by older Core versions.  They remain accepted at the
# boundary so a persisted session or an older CLI client can be resumed.
_LEGACY_REASONING_LEVELS: dict[str, ReasoningLevel] = {
    "none": "off",
    "disabled": "off",
    "light": "light",
    "low": "light",
    "minimal": "light",
    "medium": "high",
    "high": "high",
    "max": "max",
    "ultra": "max",
}


def normalize_reasoning_level(
    value: object,
    fallback: ReasoningLevel = "off",
) -> ReasoningLevel:
    """Return one of the four canonical product levels.

    Unknown values deliberately fall back instead of being copied into an
    outbound provider request.  This keeps a malformed UI/storage value from
    becoming an undocumented vendor parameter.
    """

    normalized = str(value or "").strip().lower()
    return _LEGACY_REASONING_LEVELS.get(normalized, fallback)


def reasoning_level_from_legacy(
    *,
    reasoning_level: object = None,
    thinking_enabled: object = None,
    reasoning_effort: object = None,
    fallback: ReasoningLevel = "off",
) -> ReasoningLevel:
    """Resolve the new level from new or legacy runtime fields."""

    if str(reasoning_level or "").strip():
        return normalize_reasoning_level(reasoning_level, fallback)
    if isinstance(thinking_enabled, bool):
        if not thinking_enabled:
            return "off"
        # A legacy boolean only expressed on/off.  ``high`` preserves the old
        # enabled-by-default behavior without inventing a vendor value.
        return "high"
    if str(reasoning_effort or "").strip():
        return normalize_reasoning_level(reasoning_effort, fallback)
    return fallback


__all__ = [
    "REASONING_LEVELS",
    "ReasoningLevel",
    "normalize_reasoning_level",
    "reasoning_level_from_legacy",
]
