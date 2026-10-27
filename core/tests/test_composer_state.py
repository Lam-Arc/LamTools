"""Session-scoped composer input parameter group.

user:“架构调整，输入框的信息作为‘输入参数组’按会话持久化保存包括模式权限模型思考以及输入信息”
+(先写验收测试：参数组规范化、会话落库、运行中回合收到下一步补丁、恢复时只取显式保存的值)。
"""
from __future__ import annotations

import pytest

from lamtools_core.app.composer_state import (
    composer_state_from_metadata,
    composer_state_patch,
    inherit_composer_params,
    live_composer_patch,
    normalize_composer_state,
    overlay_composer_controls,
    with_composer_state,
)
from lamtools_core.app.live.composer import handle_session_composer_set_operation
from lamtools_core.session import build_session_record


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_normalize_composer_state_fills_defaults_and_rejects_unknown_levels():
    state = normalize_composer_state(
        {
            "active_mode": "bogus",
            "model_id": "  model-a  ",
            "reasoning_level": "xh",
            "shallow_thinking_enabled": True,
        }
    )

    assert state == {
        "active_mode": "execute",
        "model_id": "model-a",
        "reasoning_level": "xhigh",
        "shallow_thinking_enabled": True,
        "permission_preset": "ask",
    }


def test_with_composer_state_mirrors_legacy_keys_and_permission_authority():
    metadata = with_composer_state(
        {"runtime_preferences": {"base_tier": "full_edit", "permission_preset": "ask"}},
        {
            "active_mode": "consider",
            "model_id": "model-b",
            "reasoning_level": "medium",
            "permission_preset": "auto",
        },
    )

    assert metadata["composer_state"]["active_mode"] == "consider"
    assert metadata["model_id"] == "model-b"
    # Permission remains authoritative in runtime_preferences.
    assert metadata["runtime_preferences"]["permission_preset"] == "auto"
    assert metadata["runtime_preferences"]["base_tier"] == "full_edit"


def test_composer_state_patch_only_changes_provided_fields():
    metadata = {
        "composer_state": {
            "active_mode": "execute",
            "model_id": "model-a",
            "reasoning_level": "max",
            "shallow_thinking_enabled": True,
            "permission_preset": "full_access",
        }
    }

    patched = composer_state_patch(metadata, active_mode="consider")

    assert patched == {
        "active_mode": "consider",
        "model_id": "model-a",
        "reasoning_level": "max",
        "shallow_thinking_enabled": True,
        "permission_preset": "full_access",
    }


def test_live_composer_patch_excludes_the_model():
    patch = live_composer_patch(
        {
            "active_mode": "consider",
            "model_id": "model-b",
            "reasoning_level": "high",
            "shallow_thinking_enabled": False,
            "permission_preset": "auto",
        }
    )

    assert "model_id" not in patch
    assert patch == {
        "active_mode": "consider",
        "reasoning_level": "high",
        "shallow_thinking_enabled": False,
        "permission_preset": "auto",
    }


def test_overlay_composer_controls_does_not_invent_defaults_for_legacy_sessions():
    parked = {"active_mode": "study:study", "reasoning_level": "max", "model_id": "parked"}

    # No composer_state block: a study/plugin/legacy session keeps its parked
    # values instead of being turned into the product default "execute".
    assert overlay_composer_controls(parked, {"model_id": "legacy"}) == parked

    overlaid = overlay_composer_controls(
        parked,
        {
            "composer_state": {
                "active_mode": "consider",
                "reasoning_level": "light",
            }
        },
    )
    assert overlaid["active_mode"] == "consider"
    assert overlaid["reasoning_level"] == "light"
    # Model stays parked unless explicitly requested.
    assert overlaid["model_id"] == "parked"


def test_inherit_composer_params_keeps_explicit_caller_values():
    metadata = {
        "composer_state": {
            "active_mode": "consider",
            "model_id": "session-model",
            "reasoning_level": "light",
            "shallow_thinking_enabled": True,
        }
    }

    merged = inherit_composer_params(
        {"model_id": "explicit-model", "reasoning_level": "max"},
        metadata,
    )

    assert merged["model_id"] == "explicit-model"
    assert merged["reasoning_level"] == "max"
    assert merged["active_mode"] == "consider"
    assert merged["shallow_thinking_enabled"] is True


# ---------------------------------------------------------------------------
# session.composer.set
# ---------------------------------------------------------------------------


class _SessionStore:
    def __init__(self, record):
        self.record = record
        self.patches = []

    async def get(self, session_id):
        return self.record if session_id == self.record.id else None

    async def patch(self, session_id, *, metadata=None, **_kwargs):
        assert session_id == self.record.id
        self.patches.append(metadata)
        self.record.metadata = dict(metadata or {})
        return self.record


class _Registry:
    def __init__(self, run_id: str = "run-1"):
        self.run_id = run_id
        self.updates: list[tuple[str, dict, str]] = []

    def active_run_id(self, thread_id: str):
        return self.run_id

    def update_settings(self, thread_id, patch, *, run_id=""):
        self.updates.append((thread_id, dict(patch), run_id))
        return True


class _Hub:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


class _Host:
    def __init__(self):
        self.session_store = None
        self.runtime_task_registry = None
        self.runtime_state_store = None


class _Context:
    def __init__(self):
        self.host = _Host()
        self.hub = _Hub()
        self.operations = None


def _context() -> _Context:
    return _Context()


@pytest.mark.asyncio
async def test_session_composer_set_persists_and_signals_the_active_run():
    record = build_session_record(
        session_id="thread-composer",
        member_id="core",
        title="Composer",
        status="idle",
        metadata={},
    )
    store = _SessionStore(record)
    registry = _Registry()
    context = _context()
    context.host.session_store = store
    context.host.runtime_task_registry = registry

    outcome = await handle_session_composer_set_operation(
        request_id=1,
        params={
            "thread_id": record.id,
            "active_mode": "consider",
            "model_id": "model-b",
            "reasoning_level": "high",
            "shallow_thinking_enabled": True,
            "permission_preset": "auto",
        },
        context=context,
    )

    assert outcome.response["result"]["composer_state"] == {
        "active_mode": "consider",
        "model_id": "model-b",
        "reasoning_level": "high",
        "shallow_thinking_enabled": True,
        "permission_preset": "auto",
    }
    assert outcome.response["result"]["applied_to_run"] is True
    assert record.metadata["composer_state"]["model_id"] == "model-b"
    assert record.metadata["model_id"] == "model-b"
    assert record.metadata["runtime_preferences"]["permission_preset"] == "auto"
    assert registry.updates == [
        (
            record.id,
            {
                "active_mode": "consider",
                "reasoning_level": "high",
                "shallow_thinking_enabled": True,
                "permission_preset": "auto",
            },
            "run-1",
        )
    ]


@pytest.mark.asyncio
async def test_session_composer_set_can_skip_the_running_turn():
    record = build_session_record(
        session_id="thread-composer-idle",
        member_id="core",
        title="Composer",
        status="idle",
        metadata={},
    )
    store = _SessionStore(record)
    registry = _Registry()
    context = _context()
    context.host.session_store = store
    context.host.runtime_task_registry = registry

    outcome = await handle_session_composer_set_operation(
        request_id=1,
        params={
            "thread_id": record.id,
            "reasoning_level": "medium",
            "apply_to_running": False,
        },
        context=context,
    )

    assert outcome.response["result"]["applied_to_run"] is False
    assert registry.updates == []
    assert record.metadata["composer_state"]["reasoning_level"] == "medium"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"active_mode": "bogus"},
        {"reasoning_level": "ultra-max"},
        {"shallow_thinking_enabled": "yes"},
        {"permission_preset": "sometimes"},
    ],
)
async def test_session_composer_set_rejects_invalid_values(params):
    record = build_session_record(
        session_id="thread-composer-invalid",
        member_id="core",
        title="Composer",
        status="idle",
        metadata={},
    )
    store = _SessionStore(record)
    context = _context()
    context.host.session_store = store

    outcome = await handle_session_composer_set_operation(
        request_id=1,
        params={"thread_id": record.id, **params},
        context=context,
    )

    assert "error" in outcome.response
    assert store.patches == []


@pytest.mark.asyncio
async def test_session_composer_set_partial_update_preserves_other_fields():
    record = build_session_record(
        session_id="thread-composer-partial",
        member_id="core",
        title="Composer",
        status="idle",
        metadata={
            "composer_state": {
                "active_mode": "execute",
                "model_id": "model-a",
                "reasoning_level": "max",
                "shallow_thinking_enabled": True,
                "permission_preset": "full_access",
            }
        },
    )
    store = _SessionStore(record)
    context = _context()
    context.host.session_store = store

    await handle_session_composer_set_operation(
        request_id=1,
        params={"thread_id": record.id, "active_mode": "consider"},
        context=context,
    )

    assert record.metadata["composer_state"] == {
        "active_mode": "consider",
        "model_id": "model-a",
        "reasoning_level": "max",
        "shallow_thinking_enabled": True,
        "permission_preset": "full_access",
    }
    assert composer_state_from_metadata(record.metadata)["model_id"] == "model-a"


def test_kit_apply_runtime_settings_updates_config_but_keeps_the_model(tmp_path):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.runtime import RuntimeState

    class _Toolbox:
        active_mode = "execute"

    kit = CoreBaseAgentKit(
        work_root=tmp_path,
        config=CoreBaseAgentConfig(
            model_id="model-current",
            active_mode="execute",
            reasoning_level="max",
        ),
        toolbox=_Toolbox(),
    )
    state = RuntimeState(
        session_id="session-settings",
        metadata={"runtime_snapshot": {"permission_preset": "ask", "model_id": "model-current"}},
    )

    changed = kit.apply_runtime_settings(
        state,
        {
            "active_mode": "consider",
            "reasoning_level": "light",
            "shallow_thinking_enabled": True,
            "permission_preset": "auto",
            # The product keeps the model bound to the current turn.
            "model_id": "model-next-turn",
        },
    )

    assert changed == {
        "active_mode",
        "reasoning_level",
        "shallow_thinking_enabled",
        "permission_preset",
    }
    assert kit.config.active_mode == "consider"
    assert kit.config.reasoning_level == "light"
    assert kit.config.model_id == "model-current"
    assert kit.toolbox.active_mode == "consider"
    assert state.metadata["shallow_thinking_enabled"] is True
    assert state.metadata["runtime_snapshot"]["active_mode"] == "consider"
    assert state.metadata["runtime_snapshot"]["reasoning_level"] == "light"
    assert state.metadata["runtime_snapshot"]["permission_preset"] == "auto"
    assert state.metadata["runtime_snapshot"]["model_id"] == "model-current"


def test_session_composer_operation_is_registered_for_live_dispatch():
    from lamtools_core.app.live.dispatch import _CORE_LIVE_OPERATION_EXECUTORS
    from lamtools_core.app.operation_groups import CORE_WORKBENCH_OPERATION_NAMES

    assert (
        _CORE_LIVE_OPERATION_EXECUTORS["session.composer.set"]
        is handle_session_composer_set_operation
    )
    assert "session.composer.set" in CORE_WORKBENCH_OPERATION_NAMES
