"""Tests for 设置 → 通用 → 保持电脑运行 (keep-awake)."""
from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.config.settings_store import set_setting
from lamtools_core.runtime import power


@pytest.fixture()
def fake_execution_state(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Capture SetThreadExecutionState flags instead of touching the real machine."""
    calls: list[int] = []

    def _fake(flags: int) -> int:
        calls.append(flags)
        return 1

    monkeypatch.setattr(power, "_set_execution_state", _fake)
    monkeypatch.setattr(power, "platform_supported", lambda: True)
    monkeypatch.setattr(power, "_applied", False)
    return calls


def test_defaults_to_off(isolated_config_root: Path) -> None:
    assert power.keep_awake_enabled() is False
    assert power.is_applied() is False


def test_enabling_holds_the_machine_awake(isolated_config_root: Path, fake_execution_state: list[int]) -> None:
    set_setting(power.KEEP_AWAKE_NAMESPACE, {"enabled": True})

    assert power.apply_keep_awake() is True
    assert power.is_applied() is True
    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    assert fake_execution_state[-1] == 0x80000001


def test_disabling_releases_the_request(isolated_config_root: Path, fake_execution_state: list[int]) -> None:
    set_setting(power.KEEP_AWAKE_NAMESPACE, {"enabled": True})
    power.apply_keep_awake()

    set_setting(power.KEEP_AWAKE_NAMESPACE, {"enabled": False})
    assert power.apply_keep_awake() is False
    assert power.is_applied() is False
    # ES_CONTINUOUS alone clears the system-required request.
    assert fake_execution_state[-1] == 0x80000000


def test_unsupported_platform_reports_inactive(isolated_config_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(power, "platform_supported", lambda: False)
    monkeypatch.setattr(power, "_set_execution_state", lambda flags: None)
    monkeypatch.setattr(power, "_applied", False)
    set_setting(power.KEEP_AWAKE_NAMESPACE, {"enabled": True})

    assert power.apply_keep_awake() is False
    status = power.keep_awake_status()
    assert status == {"enabled": True, "applied": False, "supported": False}


def test_os_refusal_is_not_reported_as_applied(
    isolated_config_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(power, "platform_supported", lambda: True)
    monkeypatch.setattr(power, "_set_execution_state", lambda flags: 0)
    monkeypatch.setattr(power, "_applied", False)
    set_setting(power.KEEP_AWAKE_NAMESPACE, {"enabled": True})

    assert power.apply_keep_awake() is False


def test_merge_keep_awake_validates_the_flag(isolated_config_root: Path) -> None:
    assert power.merge_keep_awake({}, {"enabled": True}) == {"enabled": True}
    assert power.merge_keep_awake({"enabled": True}, {}) == {"enabled": True}
    assert power.merge_keep_awake({}, {"enabled": "yes"}) is None
    assert power.merge_keep_awake({}, {"unknown": 1}) == {"enabled": False}


@pytest.mark.asyncio
async def test_settings_rpc_applies_the_switch_immediately(
    isolated_config_root: Path, fake_execution_state: list[int]
) -> None:
    from lamtools_core.config.operations import build_config_operation_catalog

    catalog = build_config_operation_catalog()

    turned_on = await catalog.execute(
        "settings.update", {"namespace": "core.keepAwake", "value": {"enabled": True}}, metadata={}
    )
    assert turned_on.status == "ok"
    assert power.is_applied() is True

    rejected = await catalog.execute(
        "settings.update", {"namespace": "core.keepAwake", "value": {"enabled": "yes"}}, metadata={}
    )
    assert rejected.status == "error"
    # The rejected write must not flip the machine back off.
    assert power.keep_awake_enabled() is True
    assert power.is_applied() is True

    turned_off = await catalog.execute(
        "settings.update", {"namespace": "core.keepAwake", "value": {"enabled": False}}, metadata={}
    )
    assert turned_off.status == "ok"
    assert power.is_applied() is False
