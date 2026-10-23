"""Single-authority contracts for live permissions and status vocabulary."""

from __future__ import annotations

from pathlib import Path

from lamtools_core.app.runtime_permissions import overlay_runtime_permissions
from lamtools_core.tool.approval import ApprovalGate, PermissionResolver


def _gate(**overrides) -> ApprovalGate:
    values = {
        "work_root": Path.cwd(),
        "tool_permissions": {
            "read_file": "auto_allow",
            "write_file": "ask_user",
            "danger": "hard_block",
        },
    }
    values.update(overrides)
    return ApprovalGate(**values)


def test_permission_resolver_is_the_only_writer_of_live_gate_inputs():
    gate = _gate()
    resolver = PermissionResolver(gate)

    changed = resolver.apply_snapshot(
        {
            "approval_policy": "auto_approve",
            "active_tier": "read_only",
            "tier_tools": {
                "read_only": ["read_file"],
                "limited_edit": ["read_file", "write_file"],
                "not_a_tier": ["write_file"],
            },
            "allow_access_outside_workdir": True,
        }
    )

    assert changed is True
    assert gate.approval_policy == "auto_approve"
    assert gate.active_tier == "read_only"
    assert gate.tier_tools == {
        "read_only": {"read_file"},
        "limited_edit": {"read_file", "write_file"},
        "full_edit": set(),
    }
    assert gate.allow_access_outside_workdir is True
    # The capability boundary still beats the automatic preset.
    decision = resolver.resolve("write_file", {"path": "x.txt"})
    assert decision.blocked is True
    assert decision.requires_approval is False

    # Unknown values are ignored instead of silently resetting a valid input.
    assert resolver.apply_snapshot(
        {"approval_policy": "nonsense", "active_tier": "nonsense"}
    ) is False
    assert gate.approval_policy == "auto_approve"
    assert gate.active_tier == "read_only"


def test_overlay_runtime_permissions_refreshes_only_permission_keys():
    base = {
        "model_id": "keep-me",
        "approval_policy": "require",
        "active_tier": "full_edit",
        "extra": 1,
    }
    live = {
        "model_id": "do-not-copy",
        "approval_policy": "auto_approve",
        "active_tier": "read_only",
        "permission_preset": "auto",
        "tier_tools": {"read_only": ["read_file"]},
        "allow_access_outside_workdir": True,
    }

    merged = overlay_runtime_permissions(base, live)

    assert merged["model_id"] == "keep-me"
    assert merged["extra"] == 1
    assert merged["approval_policy"] == "auto_approve"
    assert merged["active_tier"] == "read_only"
    assert merged["permission_preset"] == "auto"
    assert merged["allow_access_outside_workdir"] is True
    assert "model_id" not in overlay_runtime_permissions({}, live)


def test_status_vocabulary_has_one_source():
    from lamtools_core.app.queue_state import ACTIVE_TURN_STATUSES
    from lamtools_core.event.runtime_projection import TERMINAL_STATUSES
    from lamtools_core.runtime_owner import LIVE_RUN_STATES
    from lamtools_core.snapshot import TERMINAL_STATUSES as SNAPSHOT_TERMINAL
    from lamtools_core.turn.model import (
        ACTIVE_TURN_STATUSES as TURN_ACTIVE_STATUSES,
        BUSY_TURN_STATUSES,
        LIVE_RUNTIME_STATUSES,
        TERMINAL_ITEM_STATUSES,
        TERMINAL_TURN_STATUSES,
    )

    assert LIVE_RUN_STATES is LIVE_RUNTIME_STATUSES
    assert TERMINAL_STATUSES is TERMINAL_ITEM_STATUSES
    assert SNAPSHOT_TERMINAL is TERMINAL_TURN_STATUSES
    assert ACTIVE_TURN_STATUSES == TURN_ACTIVE_STATUSES | {"interrupting"}
    # Legacy snapshot/runtime spellings remain recognized.
    assert "interrupting" in BUSY_TURN_STATUSES
    assert "paused" in BUSY_TURN_STATUSES
    assert "paused" not in ACTIVE_TURN_STATUSES
    assert "skipped" in TERMINAL_TURN_STATUSES
