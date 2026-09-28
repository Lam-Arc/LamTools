from __future__ import annotations

import pytest

from lamtools_core.app.live_approval import normalize_approval_request


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"request_id": "request-1", "decision": "approve_once", "guidance": "continue"},
            {"request_id": "request-1", "thread_id": "", "decision": "approve", "guidance": "continue"},
        ),
        (
            {"thread_id": "thread-1", "action": "other_guidance", "response": "use git diff"},
            {"request_id": "request-1", "thread_id": "thread-1", "decision": "guide", "guidance": "use git diff"},
        ),
        (
            {"request_id": "request-1", "decision": "approve_for_session", "response": ""},
            {"request_id": "request-1", "thread_id": "", "decision": "approve", "guidance": ""},
        ),
    ],
)
async def test_normalize_approval_request_canonicalizes_legacy_and_current_payloads(payload, expected) -> None:
    async def resolve_pending_request(thread_id: str) -> str | None:
        assert thread_id == "thread-1"
        return "request-1"

    normalized = await normalize_approval_request(payload, resolve_pending_request=resolve_pending_request)

    assert normalized.to_dict() == expected


class _FakeSettingsOperations:
    """Minimal operations facade exposing only settings.get for policy resolution."""

    def __init__(self, value: dict | None) -> None:
        self._value = value if isinstance(value, dict) else {}

    def has(self, name: str) -> bool:
        return name == "settings.get"

    async def execute(self, name: str, payload: dict, metadata: dict | None = None) -> object:
        from lamtools_core.app.operation_catalog import OperationResult

        assert name == "settings.get"
        return OperationResult(name=name, status="ok", payload={"value": self._value})


class _FakePolicyContext:
    def __init__(self, value: dict | None) -> None:
        self.operations = _FakeSettingsOperations(value)


@pytest.mark.asyncio
async def test_resolve_turn_approval_policy_reads_allow_access_outside_workdir() -> None:
    from lamtools_core.app.live_operations import _resolve_turn_approval_policy

    resolved = await _resolve_turn_approval_policy(
        context=_FakePolicyContext(
            {"permission_mode": "full_edit", "allow_access_outside_workdir": True}
        ),
        params={},
    )

    assert resolved["allow_access_outside_workdir"] is True
    assert resolved["approval_policy"] == "require"


@pytest.mark.asyncio
async def test_resolve_turn_approval_policy_defaults_outside_workdir_false() -> None:
    from lamtools_core.app.live_operations import _resolve_turn_approval_policy

    resolved = await _resolve_turn_approval_policy(
        context=_FakePolicyContext({"permission_mode": "full_edit"}),
        params={},
    )

    assert resolved["allow_access_outside_workdir"] is False


def test_global_switch_opens_outside_access_for_frozen_session() -> None:
    """设置在会话创建后打开：旧会话不再逐次确认。"""
    from lamtools_core.app.runtime_permissions import resolve_session_permissions

    opened = resolve_session_permissions(
        preset="ask",
        base_tier="full_edit",
        base_allow_access_outside_workdir=False,
        global_controls={"permission_mode": "full_edit", "allow_access_outside_workdir": True},
    )
    closed = resolve_session_permissions(
        preset="ask",
        base_tier="full_edit",
        base_allow_access_outside_workdir=False,
        global_controls={"permission_mode": "full_edit"},
    )
    session_grant = resolve_session_permissions(
        preset="ask",
        base_tier="full_edit",
        base_allow_access_outside_workdir=True,
        global_controls={"permission_mode": "full_edit"},
    )

    assert opened.allow_access_outside_workdir is True
    assert closed.allow_access_outside_workdir is False
    assert session_grant.allow_access_outside_workdir is True


class _FakeSessionStore:
    def __init__(self, metadata: dict) -> None:
        self._metadata = metadata

    def get(self, session_id: str) -> object:
        session = type("Session", (), {})()
        session.id = session_id
        session.metadata = dict(self._metadata)
        return session


class _FakeHostContext:
    """Policy context backed by a session that froze ``false`` before the switch."""

    def __init__(self, *, settings: dict | None, session_metadata: dict) -> None:
        self.operations = _FakeSettingsOperations(settings)
        self.host = type("Host", (), {"session_store": _FakeSessionStore(session_metadata)})()


@pytest.mark.asyncio
async def test_resolve_turn_policy_applies_global_switch_to_existing_session() -> None:
    from lamtools_core.app.live_operations import _resolve_turn_approval_policy

    context = _FakeHostContext(
        settings={"permission_mode": "full_edit", "allow_access_outside_workdir": True},
        session_metadata={
            "work_root": "C:/workspace",
            "runtime_preferences": {
                "base_tier": "full_edit",
                "base_allow_access_outside_workdir": False,
                "permission_preset": "ask",
            },
        },
    )

    resolved = await _resolve_turn_approval_policy(context=context, params={"thread_id": "thread-1"})

    assert resolved["allow_access_outside_workdir"] is True


def test_full_access_preset_expands_to_full_edit_auto_approve_and_outside_access() -> None:
    from lamtools_core.app.runtime_permissions import resolve_permission_preset

    resolved = resolve_permission_preset(
        preset="full_access",
        base_tier="read_only",
        base_allow_access_outside_workdir=False,
        tier_tools={"read_only": {"read_file"}, "limited_edit": set(), "full_edit": set()},
    )

    assert resolved.active_tier == "full_edit"
    assert resolved.approval_policy == "auto_approve"
    assert resolved.allow_access_outside_workdir is True


def test_global_runtime_controls_preserve_full_access_default() -> None:
    from lamtools_core.app.runtime_permissions import read_global_runtime_controls

    controls = read_global_runtime_controls({"permission_preset": "full_access"})

    assert controls["permission_preset"] == "full_access"


def test_auto_preset_keeps_the_session_capability_tier() -> None:
    from lamtools_core.app.runtime_permissions import resolve_permission_preset

    resolved = resolve_permission_preset(
        preset="auto",
        base_tier="read_only",
        base_allow_access_outside_workdir=False,
        tier_tools={"read_only": {"read_file"}, "limited_edit": set(), "full_edit": set()},
    )

    assert resolved.active_tier == "read_only"
    assert resolved.approval_policy == "auto_approve"
    assert resolved.allow_access_outside_workdir is False
