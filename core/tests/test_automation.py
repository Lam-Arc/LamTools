"""Tests for 设置 → 通用 → 提问自动继续 (unattended ask auto-continue).

The preference only ever covers the model's ``question`` cards; permission
approvals are a safety boundary and are never in scope.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.config.automation import (
    ASK_AUTO_CONTINUE_NAMESPACE,
    ASK_AUTO_CONTINUE_TIMEOUT_MINUTES,
    ask_auto_continue_enabled,
    ask_auto_continue_status,
    merge_ask_auto_continue,
)
from lamtools_core.config.settings_store import set_setting


def test_defaults_to_off(isolated_config_root: Path) -> None:
    assert ask_auto_continue_enabled() is False
    assert ask_auto_continue_status() == {
        "enabled": False,
        "timeout_minutes": ASK_AUTO_CONTINUE_TIMEOUT_MINUTES,
        "applies_to": "question",
    }


def test_merge_validates_the_flag(isolated_config_root: Path) -> None:
    assert merge_ask_auto_continue({}, {"enabled": True}) == {"enabled": True}
    assert merge_ask_auto_continue({"enabled": True}, {}) == {"enabled": True}
    assert merge_ask_auto_continue({}, {"enabled": 1}) is None
    # Unknown keys are dropped rather than persisted.
    assert merge_ask_auto_continue({}, {"applies_to": "approval"}) == {"enabled": False}


@pytest.mark.asyncio
async def test_settings_rpc_round_trip_and_validation(isolated_config_root: Path) -> None:
    from lamtools_core.config.operations import build_config_operation_catalog

    catalog = build_config_operation_catalog()

    saved = await catalog.execute(
        "settings.update", {"namespace": ASK_AUTO_CONTINUE_NAMESPACE, "value": {"enabled": True}}, metadata={}
    )
    assert saved.status == "ok"
    assert ask_auto_continue_enabled() is True

    fetched = await catalog.execute("settings.get", {"namespace": ASK_AUTO_CONTINUE_NAMESPACE}, metadata={})
    assert fetched.payload["value"] == {"enabled": True}

    rejected = await catalog.execute(
        "settings.update", {"namespace": ASK_AUTO_CONTINUE_NAMESPACE, "value": {"enabled": "yes"}}, metadata={}
    )
    assert rejected.status == "error"
    # A rejected write must not clear the stored preference.
    assert ask_auto_continue_enabled() is True

    turned_off = await catalog.execute(
        "settings.update", {"namespace": ASK_AUTO_CONTINUE_NAMESPACE, "value": {"enabled": False}}, metadata={}
    )
    assert turned_off.status == "ok"
    assert ask_auto_continue_enabled() is False


def test_setting_round_trips_through_settings_jsonc(isolated_config_root: Path) -> None:
    set_setting(ASK_AUTO_CONTINUE_NAMESPACE, {"enabled": True})
    assert (isolated_config_root / "settings.jsonc").is_file()
    assert ask_auto_continue_enabled() is True
