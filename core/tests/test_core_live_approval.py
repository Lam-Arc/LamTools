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
    assert resolved["approval_policy"] == "auto_approve"


@pytest.mark.asyncio
async def test_resolve_turn_approval_policy_defaults_outside_workdir_false() -> None:
    from lamtools_core.app.live_operations import _resolve_turn_approval_policy

    resolved = await _resolve_turn_approval_policy(
        context=_FakePolicyContext({"permission_mode": "full_edit"}),
        params={},
    )

    assert resolved["allow_access_outside_workdir"] is False
