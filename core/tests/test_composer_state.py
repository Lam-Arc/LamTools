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
        "active_mode": "work",
        "model_id": "model-a",
        "reasoning_level": "xhigh",
        "shallow_thinking_enabled": True,
        "permission_preset": "ask",
    }


def test_with_composer_state_mirrors_legacy_keys_and_permission_authority():
    metadata = with_composer_state(
        {"runtime_preferences": {"base_tier": "full_edit", "permission_preset": "ask"}},
        {
            "active_mode": "chat",
            "model_id": "model-b",
            "reasoning_level": "medium",
            "permission_preset": "auto",
        },
    )

    assert metadata["composer_state"]["active_mode"] == "chat"
    assert metadata["model_id"] == "model-b"
    # Permission remains authoritative in runtime_preferences.
    assert metadata["runtime_preferences"]["permission_preset"] == "auto"
    assert metadata["runtime_preferences"]["base_tier"] == "full_edit"


def test_composer_state_patch_only_changes_provided_fields():
    metadata = {
        "composer_state": {
            "active_mode": "work",
            "model_id": "model-a",
            "reasoning_level": "max",
            "shallow_thinking_enabled": True,
            "permission_preset": "full_access",
        }
    }

    patched = composer_state_patch(metadata, active_mode="chat")

    assert patched == {
        "active_mode": "chat",
        "model_id": "model-a",
        "reasoning_level": "max",
        "shallow_thinking_enabled": True,
        "permission_preset": "full_access",
    }


def test_live_composer_patch_excludes_the_model_and_the_mode():
    # user:“新建会话时选择好，就不可变动了”+(运行中的回合也收不到模式变更：下一步
    # 补丁里只有思考档位、浅思考与权限；模式与模型都按会话/回合固定。)
    patch = live_composer_patch(
        {
            "active_mode": "chat",
            "model_id": "model-b",
            "reasoning_level": "high",
            "shallow_thinking_enabled": False,
            "permission_preset": "auto",
        }
    )

    assert "model_id" not in patch
    assert "active_mode" not in patch
    assert patch == {
        "reasoning_level": "high",
        "shallow_thinking_enabled": False,
        "permission_preset": "auto",
    }


def test_overlay_composer_controls_does_not_invent_defaults_for_legacy_sessions():
    parked = {"active_mode": "study:study", "reasoning_level": "max", "model_id": "parked"}

    # No composer_state block: a study/plugin/legacy session keeps its parked
    # values instead of being turned into the product default "work".
    assert overlay_composer_controls(parked, {"model_id": "legacy"}) == parked

    overlaid = overlay_composer_controls(
        parked,
        {
            "composer_state": {
                "active_mode": "chat",
                "reasoning_level": "light",
            }
        },
    )
    assert overlaid["active_mode"] == "chat"
    assert overlaid["reasoning_level"] == "light"
    # Model stays parked unless explicitly requested.
    assert overlaid["model_id"] == "parked"


def test_inherit_composer_params_keeps_explicit_caller_values():
    metadata = {
        "composer_state": {
            "active_mode": "chat",
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
    assert merged["active_mode"] == "chat"
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
            "model_id": "model-b",
            "reasoning_level": "high",
            "shallow_thinking_enabled": True,
            "permission_preset": "auto",
        },
        context=context,
    )

    # 这组参数不写模式，所以返回的组里也没有 active_mode（会话仍是「还没定模式」）。
    assert outcome.response["result"]["composer_state"] == {
        "model_id": "model-b",
        "reasoning_level": "high",
        "shallow_thinking_enabled": True,
        "permission_preset": "auto",
    }
    assert outcome.response["result"]["applied_to_run"] is True
    assert record.metadata["composer_state"]["model_id"] == "model-b"
    assert record.metadata["model_id"] == "model-b"
    assert record.metadata["runtime_preferences"]["permission_preset"] == "auto"
    # 运行中的回合只收到可热改的键，模式不在其中。
    assert registry.updates == [
        (
            record.id,
            {
                "reasoning_level": "high",
                "shallow_thinking_enabled": True,
                "permission_preset": "auto",
            },
            "run-1",
        )
    ]


@pytest.mark.asyncio
async def test_session_composer_set_never_changes_the_mode():
    # user:“发送第一条消息时，定下该会话模式；新建会话时选择好，就不可变动了”
    # +(输入框这组参数不碰模式：请求里带了模式也不落库，会话里的模式保持不变。)
    record = build_session_record(
        session_id="thread-composer-fixed-mode",
        member_id="core",
        title="Composer",
        status="idle",
        metadata={
            "composer_state": {
                "active_mode": "work",
                "model_id": "model-a",
                "reasoning_level": "max",
                "shallow_thinking_enabled": False,
                "permission_preset": "ask",
            }
        },
    )
    store = _SessionStore(record)
    context = _context()
    context.host.session_store = store

    outcome = await handle_session_composer_set_operation(
        request_id=1,
        params={"thread_id": record.id, "active_mode": "chat"},
        context=context,
    )

    assert "error" not in outcome.response
    assert record.metadata["composer_state"]["active_mode"] == "work"


@pytest.mark.asyncio
async def test_session_composer_set_does_not_write_a_mode_by_itself():
    # 空会话里动输入框的其它参数，不会把模式提前写进会话；模式留给第一条消息定。
    record = build_session_record(
        session_id="thread-composer-fresh",
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
        params={"thread_id": record.id, "active_mode": "auto"},
        context=context,
    )

    assert "error" not in outcome.response
    assert "active_mode" not in record.metadata["composer_state"]
    assert composer_state_from_metadata(record.metadata)["active_mode"] == "work"
    assert "active_mode" not in registry.updates[0][1]


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
                "active_mode": "work",
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
        params={"thread_id": record.id, "reasoning_level": "light"},
        context=context,
    )

    assert record.metadata["composer_state"] == {
        "active_mode": "work",
        "model_id": "model-a",
        "reasoning_level": "light",
        "shallow_thinking_enabled": True,
        "permission_preset": "full_access",
    }
    assert composer_state_from_metadata(record.metadata)["model_id"] == "model-a"


def test_kit_apply_runtime_settings_keeps_the_model_and_the_mode(tmp_path):
    from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
    from lamtools_core.runtime import RuntimeState

    class _Toolbox:
        active_mode = "work"

    kit = CoreBaseAgentKit(
        work_root=tmp_path,
        config=CoreBaseAgentConfig(
            model_id="model-current",
            active_mode="work",
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
            "active_mode": "chat",
            "reasoning_level": "light",
            "shallow_thinking_enabled": True,
            "permission_preset": "auto",
            # The product keeps the model bound to the current turn.
            "model_id": "model-next-turn",
        },
    )

    assert changed == {
        "reasoning_level",
        "shallow_thinking_enabled",
        "permission_preset",
    }
    # user:“新建会话时选择好，就不可变动了”+(模式不属于本轮可改的设置，保持原样。)
    assert kit.config.active_mode == "work"
    assert kit.toolbox.active_mode == "work"
    assert kit.config.reasoning_level == "light"
    assert kit.config.model_id == "model-current"
    assert state.metadata["shallow_thinking_enabled"] is True
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

def test_hidden_auto_mode_is_still_accepted_by_the_backend():
    """user:“后端/内核里 auto 的处理逻辑保留（旧会话、旧存档、旧 API 调用仍能跑通）”
    “不需要改后端，只加一条断言说明兼容”+(界面从下个版本起只给聊天/工作，但后端这一层
    不改：auto 仍然读得出来、存得回去，superagent 这个旧名也照旧归一到 auto，
    旧会话与旧 API 调用不会因为界面隐藏了入口而报错。)
    """
    assert normalize_composer_state({"active_mode": "auto"})["active_mode"] == "auto"
    assert normalize_composer_state({"active_mode": "superagent"})["active_mode"] == "auto"
    assert normalize_composer_state({"active_mode": "consider"})["active_mode"] == "chat"
    assert normalize_composer_state({"active_mode": "execute"})["active_mode"] == "work"
