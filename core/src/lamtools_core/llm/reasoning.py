"""Provider-neutral reasoning level semantics.

The Composer and runtime use six product levels. Provider-specific names and
payload shapes belong to adapter profiles, not to this module. Keeping the
normalization here means persisted sessions, CLI callers, and tool arguments
all converge on the same canonical values before a model request is built.
"""

from __future__ import annotations

from typing import Literal

ReasoningLevel = Literal["off", "light", "medium", "high", "xhigh", "max"]
REASONING_LEVELS: tuple[ReasoningLevel, ...] = (
    "off",
    "light",
    "medium",
    "high",
    "xhigh",
    "max",
)

# Values written by older Core versions.  They remain accepted at the
# boundary so a persisted session or an older CLI client can be resumed.
_LEGACY_REASONING_LEVELS: dict[str, ReasoningLevel] = {
    "none": "off",
    "disabled": "off",
    "off": "off",
    "light": "light",
    "low": "light",
    "minimal": "light",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "xh": "xhigh",
    "max": "max",
    "ultra": "max",
}


def normalize_reasoning_level(
    value: object,
    fallback: ReasoningLevel = "off",
) -> ReasoningLevel:
    """Return one of the six canonical product levels.

    Unknown values deliberately fall back instead of being copied into an
    outbound provider request.  This keeps a malformed UI/storage value from
    becoming an undocumented vendor parameter.
    """

    normalized = str(value or "").strip().lower()
    fallback_value = _LEGACY_REASONING_LEVELS.get(
        str(fallback or "").strip().lower(),
        "off",
    )
    return _LEGACY_REASONING_LEVELS.get(normalized, fallback_value)


def coerce_reasoning_level(value: object) -> ReasoningLevel | None:
    """Return the canonical level for a known name, or ``None`` when unknown.

    ``normalize_reasoning_level`` deliberately falls back on unknown input;
    callers that must *reject* an unknown level (a model declaring its own
    reasoning ladder) need that distinction, so it is exposed here instead of
    being duplicated at each call site.
    """

    return _LEGACY_REASONING_LEVELS.get(str(value or "").strip().lower())


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
    return normalize_reasoning_level(fallback, "off")


__all__ = [
    "REASONING_LEVELS",
    "ReasoningLevel",
    "coerce_reasoning_level",
    "normalize_reasoning_level",
    "reasoning_level_from_legacy",
]
