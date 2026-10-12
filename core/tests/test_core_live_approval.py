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


def test_end_reason_names_the_approved_tool_outcome_not_the_approval_layer() -> None:
    """A failure caused by the approved tool must not be labelled as an
    approval-layer failure: the machine-readable reason must say what actually
    happened."""
    from lamtools_core.app.approval_resolution import _failure_decision
    from lamtools_core.event import CoreEvent

    def tool_event(status: str) -> CoreEvent:
        return CoreEvent(
            name="runtime.tool.finished",
            category="tool",
            payload={"status": status},
            session_id="t",
            run_id="r",
        )

    assert _failure_decision("tool_execution", tool_event("blocked")) == "approved_tool_blocked"
    assert _failure_decision("tool_execution", tool_event("error")) == "approved_tool_error"
    # A missing tool event still names the fact rather than the layer.
    assert _failure_decision("tool_execution", None) == "approved_tool_failed"
    # Everything else is still an approval-resolution failure.
    assert _failure_decision("approval_resolution", tool_event("blocked")) == "approval_resolution_failed"


@pytest.mark.asyncio
async def test_finalize_failure_records_the_tool_outcome_in_the_terminal_event() -> None:
    from lamtools_core.app.approval_resolution import ApprovalResolutionLifecycle
    from lamtools_core.event import CoreEvent
    from lamtools_core.runtime import InMemoryRuntimeStateStore, RuntimeState

    store = InMemoryRuntimeStateStore()
    state = RuntimeState(
        session_id="thread-tool-failure",
        run_id="run-tool-failure",
        status="waiting",
        loop_state="wait",
        metadata={
            "pending_approval": {
                "request_id": "call-edit",
                "status": "executing",
                "tool_call": {"id": "call-edit", "name": "edit_file", "arguments": {}},
            }
        },
    )
    await store.save(state)

    persisted: list[list[object]] = []

    async def persist_run_items(items: list[object]) -> dict | None:
        persisted.append(list(items))
        return None

    lifecycle = ApprovalResolutionLifecycle(
        operation_name="approval.respond",
        thread_id="thread-tool-failure",
        state=state,
        state_store=store,
        request_id="call-edit",
        tool_call={"id": "call-edit", "name": "edit_file"},
        decision="approve",
        guidance="",
        persist_run_items=persist_run_items,
        run_items_from_events=lambda events: list(events),
        snapshot_from_events=lambda events: {},
    )
    assert await lifecycle.persist_decision() is None

    tool_event = CoreEvent(
        name="runtime.tool.finished",
        category="tool",
        payload={"tool_name": "edit_file", "call_id": "call-edit", "status": "blocked", "error": "refused"},
        session_id="thread-tool-failure",
        run_id="run-tool-failure",
        tags=["tool"],
    )
    result = await lifecycle.finalize_failure(
        "refused",
        tool_event=tool_event,
        failure_origin="tool_execution",
    )

    assert result.status == "error"
    failure_events = [
        item for item in persisted[-1] if getattr(item, "name", "") == "runtime.failed"
    ]
    assert failure_events, persisted[-1]
    assert failure_events[-1].payload["decision"] == "approved_tool_blocked"
