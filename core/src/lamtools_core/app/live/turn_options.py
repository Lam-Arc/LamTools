"""Frozen runtime options, permissions and resource configuration."""
from __future__ import annotations

# user:“拆分后依旧很大”+(按业务职责分组，保留兼容入口，避免大文件再次集中。)

import inspect
import sys
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any
from lamtools_core.tool.approval import TierTools, load_access_tools
from lamtools_core.tool.loadtools import LoadTools, default_load_tools, load_loadtools
from ..runtime_permissions import (
    load_global_runtime_controls,
    normalize_permission_mode,
    normalize_permission_preset,
    permissions_from_snapshot,
    resolve_session_permissions,
    runtime_snapshot as build_runtime_snapshot,
    session_runtime_preferences,
    with_session_runtime_preferences,
)
from .context import CoreLiveContext


async def _latest_persisted_active_mode(*, context: "CoreLiveContext", thread_id: str) -> str | None:
    """Return the newest non-empty active mode persisted for this thread."""
    session_factory = getattr(context, "session_factory", None)
    persistence = getattr(context, "persistence", None)
    load_metadata = getattr(persistence, "load_metadata", None)
    if not thread_id or not callable(session_factory) or not callable(load_metadata):
        return None
    try:
        async with session_factory() as db:
            snapshot = await load_metadata(db, thread_id)
    except Exception:
        # Mode inheritance is best-effort; an unavailable snapshot must not
        # prevent an automatic continuation from starting.
        return None
    if not isinstance(snapshot, Mapping):
        return None

    # Turn acceptance stores the authoritative runtime snapshot in `turns`.
    # Older snapshots may expose only the core projection, so use it only when
    # the canonical turn map is unavailable.
    raw_turns = snapshot.get("turns")
    core = snapshot.get("core")
    core_turns = core.get("turns") if isinstance(core, Mapping) else None
    if not isinstance(raw_turns, Mapping):
        raw_turns = core_turns
    if not isinstance(raw_turns, Mapping):
        return None

    def turn_sequence(turn: Mapping[str, Any]) -> int:
        try:
            return int(turn.get("last_seq") or turn.get("seq") or 0)
        except (TypeError, ValueError):
            return 0

    ordered_turns = sorted(
        (turn for turn in raw_turns.values() if isinstance(turn, Mapping)),
        key=turn_sequence,
        reverse=True,
    )
    for turn in ordered_turns:
        runtime_snapshot = turn.get("runtime_snapshot")
        if not isinstance(runtime_snapshot, Mapping):
            continue
        active_mode = runtime_snapshot.get("active_mode")
        if isinstance(active_mode, str) and active_mode.strip():
            return active_mode.strip()
    return None


async def _resolve_turn_approval_policy(*, context: "CoreLiveContext", params: dict[str, Any]) -> dict[str, Any]:
    """Resolve approval policy, tier configuration, and loadtools mode for a turn.

    Returns dict with keys: approval_policy, active_tier, tier_tools, active_mode, load_tools
    """
    explicit = params.get("approval_policy") or params.get("approvalPolicy")
    thread_id = str(
        params.get("thread_id")
        or params.get("threadId")
        or params.get("session_id")
        or params.get("sessionId")
        or ""
    ).strip()
    active_mode = params.get("active_mode")
    if isinstance(active_mode, str) and active_mode.strip():
        active_mode = active_mode.strip()
    else:
        active_mode = None
    automatic_origin = str(params.get("origin") or params.get("turn_origin") or "").strip()
    if active_mode is None and automatic_origin:
        active_mode = await _latest_persisted_active_mode(context=context, thread_id=thread_id)
    load_tools = _load_load_tools(context)
    global_controls: dict[str, Any] = load_global_runtime_controls()
    global_value: dict[str, Any] = {}
    if context.operations.has("settings.get"):
        try:
            result = await context.operations.execute(
                "settings.get",
                {"namespace": "core.runtimeControls"},
                metadata={"source": "core_live"},
            )
            value = result.payload.get("value") if result.status == "ok" and isinstance(result.payload, dict) else None
            if isinstance(value, dict):
                global_value = dict(value)
                global_controls = {
                    **global_controls,
                    **{
                        "base_tier": normalize_permission_mode(
                            value.get("permission_mode"),
                            default=global_controls["base_tier"],
                        ),
                        "base_allow_access_outside_workdir": (
                            value.get("allow_access_outside_workdir")
                            if isinstance(value.get("allow_access_outside_workdir"), bool)
                            else global_controls["base_allow_access_outside_workdir"]
                        ),
                        "permission_preset": (
                            value.get("permission_preset")
                            if value.get("permission_preset") in {"ask", "auto", "full_access"}
                            else global_controls["permission_preset"]
                        ),
                    },
                }
        except Exception:
            global_value = {}

    session_metadata: dict[str, Any] = {}
    session_store = getattr(getattr(context, "host", None), "session_store", None)
    if thread_id and session_store is not None:
        try:
            session = session_store.get(thread_id)
            if inspect.isawaitable(session):
                session = await session
            raw_metadata = getattr(session, "metadata", None)
            if isinstance(raw_metadata, dict):
                session_metadata = dict(raw_metadata)
                if "runtime_preferences" not in session_metadata:
                    canonical = with_session_runtime_preferences(
                        session_metadata,
                        global_controls=global_value or global_controls,
                    )
                    patch = getattr(session_store, "patch", None)
                    if callable(patch):
                        patched = patch(thread_id, metadata=canonical)
                        if inspect.isawaitable(patched):
                            await patched
                    session_metadata = canonical
        except Exception:
            session_metadata = {}

    preferences = session_runtime_preferences(
        session_metadata,
        global_controls=global_value or global_controls,
    )
    # New clients submit only the preset.  Legacy callers may still provide
    # the expanded fields; those are accepted only when no new preset exists.
    raw_preset = params.get("permission_preset")
    legacy_active_tier = params.get("active_tier")
    legacy_outside = params.get("allow_access_outside_workdir")
    if raw_preset is not None:
        preset = normalize_permission_preset(raw_preset)
        base_tier = preferences["base_tier"]
        base_outside = preferences["base_allow_access_outside_workdir"]
    elif explicit is not None or legacy_active_tier is not None or isinstance(legacy_outside, bool):
        policy = "auto_approve" if explicit == "auto_approve" else "require"
        preset = "auto" if policy == "auto_approve" else "ask"
        base_tier = normalize_permission_mode(legacy_active_tier, default=preferences["base_tier"])
        base_outside = legacy_outside if isinstance(legacy_outside, bool) else preferences[
            "base_allow_access_outside_workdir"
        ]
    else:
        preset = preferences["permission_preset"]
        base_tier = preferences["base_tier"]
        base_outside = preferences["base_allow_access_outside_workdir"]

    tier_tools = _load_tier_tools(context)
    # user:“工具组可以用consider模式（只读）”+(辅助会话由服务端固定模式，客户端或全局完全访问不能扩大能力)。
    auxiliary = session_metadata.get("ui_surface") == "auxiliary"
    if auxiliary:
        preset, base_tier, active_mode = "ask", "read_only", "consider"
    permissions = resolve_session_permissions(
        preset=preset,
        base_tier=base_tier,
        base_allow_access_outside_workdir=base_outside,
        tier_tools=tier_tools,
        global_controls=global_value or global_controls,
    )
    snapshot = build_runtime_snapshot(permissions=permissions, active_mode=active_mode)
    if auxiliary:
        snapshot.update(auxiliary_read_only=True, auxiliary_parent_session_id=str(session_metadata.get("parent_session_id") or ""))
    return {
        **permissions.to_dict(),
        "work_root": str(session_metadata.get("work_root") or ""),
        "tier_tools": permissions.tier_tools,
        "active_mode": active_mode,
        "runtime_snapshot": snapshot,
        # The caller also needs the session's composer group so a client that
        # omits the parameters still inherits the session's own values.
        "session_metadata": session_metadata,
    }


def _runtime_snapshot_with_turn_options(
    permission_snapshot: dict[str, Any],
    *,
    params: dict[str, Any],
    active_mode: str | None,
) -> dict[str, Any]:
    """Add model/thinking options to an already-resolved permission snapshot."""
    result = dict(permission_snapshot)
    result["active_mode"] = active_mode
    scalar_keys = (
        "model_id",
        "reasoning_level",
        "thinking_enabled",
        "thinking_budget",
        "reasoning_effort",
        "shallow_thinking_enabled",
        "context_window_tokens",
        "max_tokens",
        "temperature",
        "compact_trigger_tokens",
        "compact_limit_tokens",
        "instructions",
        "request_local_late_context",
        "goal_id",
        "auxiliary_additional_information",
    )
    for key in scalar_keys:
        value = params.get(key)
        if value is not None and not (isinstance(value, str) and not value.strip()):
            result[key] = value

    return deepcopy(result)


def _queue_runtime_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    """Return the queue item's persisted runtime snapshot.

    New queue records always contain the canonical snapshot written by
    ``queue/create``.  Older records may not have one; their compatibility
    fallback is deliberately conservative. Dispatch overlays the current
    session permission fields before starting the queued turn.
    """
    raw = item.get("runtime_snapshot") if isinstance(item, dict) else None
    if isinstance(raw, dict):
        permissions = permissions_from_snapshot(raw)
        if permissions is not None:
            snapshot = build_runtime_snapshot(
                permissions=permissions,
                active_mode=(
                    str(raw.get("active_mode") or "").strip()
                    if raw.get("active_mode") is not None
                    else None
                ),
            )
            for key in (
                "model_id",
                "reasoning_level",
                "thinking_enabled",
                "thinking_budget",
                "reasoning_effort",
                "shallow_thinking_enabled",
                "context_window_tokens",
                "max_tokens",
                "temperature",
                "compact_trigger_tokens",
                "compact_limit_tokens",
                "instructions",
                "request_local_late_context",
                "auxiliary_read_only",
                "auxiliary_parent_session_id",
                "auxiliary_additional_information",
            ):
                if key in raw and raw[key] is not None:
                    snapshot[key] = deepcopy(raw[key])
            return snapshot
    return {
        "permission_preset": "ask",
        "active_tier": None,
        "tier_tools": None,
        "approval_policy": "require",
        "allow_access_outside_workdir": False,
    }


async def _resolve_imagegen_config(*, context: "CoreLiveContext") -> dict[str, Any]:
    """Resolve generate_image runtime config from the core.imagegen settings namespace.

    Independent of the approval-policy resolution so explicit per-turn
    approval overrides (e.g. CLI --auto-approve) still apply imagegen settings.
    Missing/invalid settings → disabled (the tool is hidden from the model).
    """
    default: dict[str, Any] = {"enabled": False, "api_url": "", "api_key": "", "model": ""}
    if not context.operations.has("settings.get"):
        return default
    try:
        result = await context.operations.execute(
            "settings.get",
            {"namespace": "core.imagegen"},
            metadata={"source": "core_live"},
        )
    except Exception:
        return default
    if result.status != "ok":
        return default
    value = result.payload.get("value") if isinstance(result.payload, dict) else None
    if not isinstance(value, dict):
        return default
    return {
        "enabled": bool(value.get("enabled")),
        "api_url": str(value.get("api_url") or "").strip(),
        "api_key": str(value.get("api_key") or "").strip(),
        "model": str(value.get("model") or "").strip(),
    }


def _bundled_config_resources_dir() -> Path:
    """Directory of bundled tool-config resources (access_tools.jsonc, ...).

    Resolved relative to this file in dev; from ``_MEIPASS/config/resources``
    when frozen (PyInstaller).
    """
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return meipass / "config" / "resources"
    return Path(__file__).resolve().parent.parent.parent.parent.parent / "config" / "resources"


def _load_tier_tools(context: "CoreLiveContext") -> TierTools | None:
    """Load access_tools.jsonc — prefer .lam/core/config/, then bundled."""
    from lamtools_core.config.root import core_config_file

    candidates: list[Path] = [core_config_file("access_tools.jsonc")]
    candidates.append(_bundled_config_resources_dir() / "access_tools.jsonc")
    for candidate in candidates:
        try:
            if candidate.exists():
                return load_access_tools(candidate)
        except (OSError, ValueError):
            continue
    return None


def _load_load_tools(context: "CoreLiveContext") -> LoadTools:
    """Load loadtools.jsonc — prefer .lam/core/config/, fallback to Core default."""
    from lamtools_core.config.root import core_config_file

    # Unified config directory (user-modifiable after packaging)
    candidate = core_config_file("loadtools.jsonc")
    try:
        if candidate.exists():
            member_tools = load_loadtools(candidate)
            if member_tools:
                return member_tools
    except (OSError, ValueError):
        pass
    # Fallback to Core built-in default
    return default_load_tools()
