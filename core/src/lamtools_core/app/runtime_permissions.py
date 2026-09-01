"""Runtime permission presets and immutable turn/queue snapshots.

The Composer only chooses a small, user-facing preset.  Core expands that
preset against the session's frozen base capability and keeps the expanded
values with the accepted turn or queue item.  This module is deliberately
independent from ``ApprovalGate`` so HTTP, CLI, session persistence, and
sub-agent setup all use the same normalization rules.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, Mapping


PermissionPreset = Literal["ask", "auto", "full_access"]
PermissionMode = Literal["read_only", "limited_edit", "full_edit"]
ApprovalPolicy = Literal["require", "auto_approve"]

PERMISSION_PRESETS: tuple[PermissionPreset, ...] = ("ask", "auto", "full_access")
PERMISSION_MODES: tuple[PermissionMode, ...] = ("read_only", "limited_edit", "full_edit")
APPROVAL_POLICIES: tuple[ApprovalPolicy, ...] = ("require", "auto_approve")

DEFAULT_BASE_TIER: PermissionMode = "full_edit"
DEFAULT_BASE_ALLOW_ACCESS_OUTSIDE_WORKDIR = False
DEFAULT_PERMISSION_PRESET: PermissionPreset = "ask"

RUNTIME_PERMISSION_KEYS: tuple[str, ...] = (
    "permission_preset",
    "active_tier",
    "tier_tools",
    "approval_policy",
    "allow_access_outside_workdir",
)


def _as_mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def is_permission_preset(value: object) -> bool:
    return value in PERMISSION_PRESETS


def normalize_permission_preset(value: object, *, default: PermissionPreset = DEFAULT_PERMISSION_PRESET) -> PermissionPreset:
    """Validate a user-facing preset.

    An explicitly supplied invalid preset is rejected by callers.  Missing or
    blank values may use the supplied safe default.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    normalized = str(value).strip()
    if normalized not in PERMISSION_PRESETS:
        raise ValueError(
            f"invalid permission_preset '{normalized}' (expected one of {', '.join(PERMISSION_PRESETS)})"
        )
    return normalized  # type: ignore[return-value]


def normalize_permission_mode(value: object, *, default: PermissionMode = DEFAULT_BASE_TIER) -> PermissionMode:
    if value in PERMISSION_MODES:
        return value  # type: ignore[return-value]
    return default


def normalize_approval_policy(value: object, *, default: ApprovalPolicy = "require") -> ApprovalPolicy:
    if value in APPROVAL_POLICIES:
        return value  # type: ignore[return-value]
    return default


def normalize_tier_tools(raw: object) -> dict[PermissionMode, set[str]]:
    """Copy a tier tool map into the set representation used by Core tools."""
    result: dict[PermissionMode, set[str]] = {
        "read_only": set(),
        "limited_edit": set(),
        "full_edit": set(),
    }
    if not isinstance(raw, Mapping):
        return result
    for tier in PERMISSION_MODES:
        values = raw.get(tier)
        if isinstance(values, (set, frozenset, list, tuple)):
            result[tier] = {
                str(item).strip()
                for item in values
                if isinstance(item, str) and str(item).strip()
            }
    return result


def serialize_tier_tools(raw: object) -> dict[str, list[str]]:
    """Return deterministic JSON-safe tier tools for event/state snapshots."""
    normalized = normalize_tier_tools(raw)
    return {tier: sorted(normalized[tier]) for tier in PERMISSION_MODES}


def read_global_runtime_controls(value: object) -> dict[str, Any]:
    """Read only the global defaults relevant to new sessions.

    ``core.runtimeControls`` historically stores ``permission_mode`` and
    ``allow_access_outside_workdir``.  ``permission_preset`` and
    ``approval_policy`` are accepted as optional forward-compatible fields;
    all three user-facing presets are valid global defaults, while an absent
    preset remains ``ask`` for new sessions.
    """
    raw = _as_mapping(value) or {}
    preset_value = raw.get("permission_preset")
    preset = preset_value if preset_value in PERMISSION_PRESETS else DEFAULT_PERMISSION_PRESET
    if preset_value is None:
        approval = normalize_approval_policy(raw.get("approval_policy"), default="require")
        if approval == "auto_approve":
            preset = "auto"
    raw_outside = raw.get(
        "allow_access_outside_workdir",
        raw.get("base_allow_access_outside_workdir"),
    )
    return {
        "base_tier": normalize_permission_mode(
            raw.get("permission_mode", raw.get("base_tier"))
        ),
        "base_allow_access_outside_workdir": (
            raw_outside
            if isinstance(raw_outside, bool)
            else DEFAULT_BASE_ALLOW_ACCESS_OUTSIDE_WORKDIR
        ),
        "permission_preset": preset,
    }


def load_global_runtime_controls() -> dict[str, Any]:
    """Load global defaults lazily, keeping this module usable in unit tests."""
    try:
        from lamtools_core.config.settings_store import get_setting

        return read_global_runtime_controls(get_setting("core.runtimeControls"))
    except Exception:  # noqa: BLE001 - a missing config must use safe defaults
        return read_global_runtime_controls(None)


def session_runtime_preferences(
    metadata: object,
    *,
    global_controls: object | None = None,
) -> dict[str, Any]:
    """Return canonical session preferences without mutating the input.

    The base tier and outside-workdir setting are copied at session creation;
    they are intentionally not re-read from global settings for an existing
    session.  Missing legacy metadata is lazily filled from the current
    global defaults by the caller.
    """
    raw_metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
    raw_preferences = raw_metadata.get("runtime_preferences")
    preferences = dict(raw_preferences) if isinstance(raw_preferences, Mapping) else {}
    # A missing preference block is the legacy/new-session path: it may be
    # initialized from global runtimeControls once.  Once the block exists,
    # even if it is partial because it came from an older version, its
    # missing fields must use stable safe defaults rather than the current
    # global settings.  Otherwise changing global defaults would silently
    # mutate an existing Session on its next read.
    if "runtime_preferences" in raw_metadata:
        defaults = {
            "base_tier": DEFAULT_BASE_TIER,
            "base_allow_access_outside_workdir": DEFAULT_BASE_ALLOW_ACCESS_OUTSIDE_WORKDIR,
            "permission_preset": DEFAULT_PERMISSION_PRESET,
        }
    else:
        defaults = read_global_runtime_controls(
            global_controls if global_controls is not None else load_global_runtime_controls()
        )
    base_tier = normalize_permission_mode(preferences.get("base_tier"), default=defaults["base_tier"])
    raw_outside = preferences.get("base_allow_access_outside_workdir")
    base_outside = raw_outside if isinstance(raw_outside, bool) else defaults["base_allow_access_outside_workdir"]
    try:
        preset = normalize_permission_preset(
            preferences.get("permission_preset"),
            default=defaults["permission_preset"],
        )
    except ValueError:
        preset = DEFAULT_PERMISSION_PRESET
    return {
        "base_tier": base_tier,
        "base_allow_access_outside_workdir": base_outside,
        "permission_preset": preset,
    }


def with_session_runtime_preferences(
    metadata: object,
    *,
    global_controls: object | None = None,
    permission_preset: object | None = None,
) -> dict[str, Any]:
    """Canonicalize metadata while preserving unrelated session metadata."""
    result = dict(metadata) if isinstance(metadata, Mapping) else {}
    preferences = session_runtime_preferences(result, global_controls=global_controls)
    if permission_preset is not None:
        preferences["permission_preset"] = normalize_permission_preset(permission_preset)
    result["runtime_preferences"] = preferences
    return result


def merge_session_runtime_preferences(
    existing_metadata: object,
    requested_metadata: object,
) -> dict[str, Any]:
    """Merge a session metadata PATCH without allowing base-tier escalation.

    The base capability is established when the session is created.  A later
    metadata update may change the Composer preset, but cannot smuggle a new
    ``base_tier`` or outside-workdir default into an existing session.
    """
    existing = dict(existing_metadata) if isinstance(existing_metadata, Mapping) else {}
    requested = dict(requested_metadata) if isinstance(requested_metadata, Mapping) else {}
    result = {**existing, **requested}
    existing_preferences = session_runtime_preferences(existing)
    requested_preferences = requested.get("runtime_preferences")
    requested_preset = (
        requested_preferences.get("permission_preset")
        if isinstance(requested_preferences, Mapping) and "permission_preset" in requested_preferences
        else existing_preferences["permission_preset"]
    )
    result["runtime_preferences"] = {
        "base_tier": existing_preferences["base_tier"],
        "base_allow_access_outside_workdir": existing_preferences[
            "base_allow_access_outside_workdir"
        ],
        "permission_preset": normalize_permission_preset(requested_preset),
    }
    return result


@dataclass(frozen=True)
class ResolvedRuntimePermissions:
    permission_preset: PermissionPreset
    active_tier: PermissionMode
    tier_tools: dict[PermissionMode, set[str]]
    approval_policy: ApprovalPolicy
    allow_access_outside_workdir: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "permission_preset": self.permission_preset,
            "active_tier": self.active_tier,
            "tier_tools": serialize_tier_tools(self.tier_tools),
            "approval_policy": self.approval_policy,
            "allow_access_outside_workdir": self.allow_access_outside_workdir,
        }


def resolve_permission_preset(
    *,
    preset: object,
    base_tier: object,
    base_allow_access_outside_workdir: object,
    tier_tools: object = None,
) -> ResolvedRuntimePermissions:
    """Expand a Composer preset against the session's base capability."""
    normalized_preset = normalize_permission_preset(preset)
    normalized_base = normalize_permission_mode(base_tier)
    base_outside = (
        base_allow_access_outside_workdir
        if isinstance(base_allow_access_outside_workdir, bool)
        else DEFAULT_BASE_ALLOW_ACCESS_OUTSIDE_WORKDIR
    )
    if normalized_preset == "full_access":
        active_tier: PermissionMode = "full_edit"
        outside = True
        approval: ApprovalPolicy = "auto_approve"
    else:
        active_tier = normalized_base
        outside = bool(base_outside)
        approval = "auto_approve" if normalized_preset == "auto" else "require"
    return ResolvedRuntimePermissions(
        permission_preset=normalized_preset,
        active_tier=active_tier,
        tier_tools=normalize_tier_tools(tier_tools),
        approval_policy=approval,
        allow_access_outside_workdir=outside,
    )


def runtime_snapshot(
    *,
    permissions: ResolvedRuntimePermissions,
    active_mode: str | None = None,
    model_id: str | None = None,
    reasoning_level: str | None = None,
    thinking_enabled: bool | None = None,
    thinking_budget: int | None = None,
    reasoning_effort: str | None = None,
    shallow_thinking_enabled: bool | None = None,
    context_window_tokens: int | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    compact_trigger_tokens: int | None = None,
    compact_limit_tokens: int | None = None,
) -> dict[str, Any]:
    """Build the complete JSON-safe snapshot accepted by a turn or queue."""
    result = permissions.to_dict()
    optional = {
        "active_mode": active_mode,
        "model_id": model_id,
        "reasoning_level": reasoning_level,
        "thinking_enabled": thinking_enabled,
        "thinking_budget": thinking_budget,
        "reasoning_effort": reasoning_effort,
        "shallow_thinking_enabled": shallow_thinking_enabled,
        "context_window_tokens": context_window_tokens,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "compact_trigger_tokens": compact_trigger_tokens,
        "compact_limit_tokens": compact_limit_tokens,
    }
    result.update({key: value for key, value in optional.items() if value is not None})
    return deepcopy(result)


def permissions_from_snapshot(raw: object) -> ResolvedRuntimePermissions | None:
    """Parse a persisted snapshot; return ``None`` when it is absent/invalid."""
    if not isinstance(raw, Mapping):
        return None
    try:
        raw_preset = raw.get("permission_preset")
        # Snapshots written before the preset field used the expanded
        # approval_policy directly.  Preserve that frozen decision when a
        # queue item/paused turn is resumed; never reinterpret it from the
        # current Composer or global settings.
        if raw_preset is None or (isinstance(raw_preset, str) and not raw_preset.strip()):
            raw_preset = (
                "auto"
                if normalize_approval_policy(raw.get("approval_policy")) == "auto_approve"
                else "ask"
            )
        return resolve_permission_preset(
            preset=raw_preset,
            base_tier=raw.get("active_tier"),
            base_allow_access_outside_workdir=raw.get("allow_access_outside_workdir"),
            tier_tools=raw.get("tier_tools"),
        )
    except ValueError:
        return None


__all__ = [
    "APPROVAL_POLICIES",
    "DEFAULT_BASE_ALLOW_ACCESS_OUTSIDE_WORKDIR",
    "DEFAULT_BASE_TIER",
    "DEFAULT_PERMISSION_PRESET",
    "PERMISSION_MODES",
    "PERMISSION_PRESETS",
    "ApprovalPolicy",
    "PermissionMode",
    "PermissionPreset",
    "ResolvedRuntimePermissions",
    "normalize_approval_policy",
    "normalize_permission_mode",
    "normalize_permission_preset",
    "normalize_tier_tools",
    "permissions_from_snapshot",
    "read_global_runtime_controls",
    "runtime_snapshot",
    "serialize_tier_tools",
    "session_runtime_preferences",
    "with_session_runtime_preferences",
    "merge_session_runtime_preferences",
    "load_global_runtime_controls",
    "resolve_permission_preset",
]
