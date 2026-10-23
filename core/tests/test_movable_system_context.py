from __future__ import annotations

import copy

import pytest

import lamtools_core.app.base_agent as base_agent
from lamtools_core.app.base_agent import CoreBaseAgentConfig, CoreBaseAgentKit
from lamtools_core.llm import TAIL_SYSTEM_MESSAGE_MARKER, ChatMessage
from lamtools_core.prompt import PromptContext, PromptPart
from lamtools_core.prompt.movable import (
    MOVABLE_CONTEXT_METADATA_KEY,
    is_movable_context_notice,
)
from lamtools_core.runtime import RuntimeState


class _MovableToolbox:
    load_tools = None

    def __init__(self) -> None:
        self.skill = ""
        self.tools: list[dict] = []

    def tool_specs(self):
        return []

    def model_tools(self, active_mode=None):
        return list(self.tools)

    def skill_index(self):
        return self.skill


def _agents_part(text: str) -> PromptPart:
    return PromptPart(
        key="project_agents",
        kind="system",
        content=f"Instructions from: AGENTS.md\n{text}",
        metadata={"source_name": "AGENTS.md"},
    )


def _make_kit(monkeypatch, tmp_path, *, parts, config=None):
    monkeypatch.setattr(
        base_agent,
        "command_shell_prompt",
        lambda: "[Command Shell]\nCurrent shell: Git Bash.",
    )
    monkeypatch.setattr(base_agent, "mode_prompt_line", lambda *_: "")
    kit = CoreBaseAgentKit(
        work_root=tmp_path,
        config=config or CoreBaseAgentConfig(instructions="BASE INSTRUCTIONS"),
        toolbox=_MovableToolbox(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(kit, "_cached_subagent_guide", lambda: "")
    monkeypatch.setattr(kit, "_cached_subagent_roles", lambda: "")
    monkeypatch.setattr(kit, "_cached_subagent_strategy", lambda: "")
    monkeypatch.setattr(kit, "_build_project_context_parts", lambda: list(parts))
    return kit


def _state(tmp_path, *, turn_id: str = "turn-1") -> RuntimeState:
    return RuntimeState(
        session_id="session-1",
        metadata={"work_root": str(tmp_path), "turn_id": turn_id},
    )


@pytest.mark.asyncio
async def test_malformed_epoch_state_reseeds_instead_of_crashing(monkeypatch, tmp_path):
    kit = _make_kit(monkeypatch, tmp_path, parts=[_agents_part("VERSION A")])
    state = _state(tmp_path)
    state.metadata[MOVABLE_CONTEXT_METADATA_KEY] = {
        "version": 1,
        "system_prompt": "OLD PROMPT",
        "reported": {},
        "block_labels": ["not", "a", "mapping"],
    }

    request = await kit.build_model_request(state, PromptContext(session_id="session-1"))

    assert str(request.messages[0].content) != "OLD PROMPT"
    assert "VERSION A" in str(request.messages[0].content)
    assert request.metadata.get("_movable_context_seeded") is True
    epoch = state.metadata[MOVABLE_CONTEXT_METADATA_KEY]
    assert epoch["system_prompt"] == request.messages[0].content


def test_rebuild_handles_none_metadata(monkeypatch, tmp_path):
    kit = _make_kit(monkeypatch, tmp_path, parts=[_agents_part("VERSION A")])
    state = RuntimeState(session_id="session-1", metadata=None)

    kit.rebuild_movable_system_context(state)

    assert state.metadata[MOVABLE_CONTEXT_METADATA_KEY]["system_prompt"]


@pytest.mark.asyncio
async def test_unchanged_blocks_keep_the_leading_prompt_byte_identical(monkeypatch, tmp_path):
    parts = [_agents_part("VERSION A")]
    kit = _make_kit(monkeypatch, tmp_path, parts=parts)
    state = _state(tmp_path)

    first = await kit.build_model_request(state, PromptContext(session_id="session-1"))
    frozen = str(first.messages[0].content)
    assert "VERSION A" in frozen
    assert first.metadata.get("_movable_context_seeded") is True
    epoch = state.metadata[MOVABLE_CONTEXT_METADATA_KEY]
    assert epoch["system_prompt"] == frozen

    second = await kit.build_model_request(state, PromptContext(session_id="session-1"))
    assert str(second.messages[0].content) == frozen
    assert second.metadata.get("_movable_context_notices") is None
    assert second.metadata.get("_movable_context_seeded") is None


@pytest.mark.asyncio
async def test_changed_block_appends_new_content_once_without_touching_the_front(
    monkeypatch, tmp_path
):
    parts = [_agents_part("VERSION A")]
    kit = _make_kit(monkeypatch, tmp_path, parts=parts)
    state = _state(tmp_path)

    first = await kit.build_model_request(state, PromptContext(session_id="session-1"))
    frozen = str(first.messages[0].content)

    parts[0] = _agents_part("VERSION B")
    second = await kit.build_model_request(state, PromptContext(session_id="session-1"))
    assert str(second.messages[0].content) == frozen

    notices = [
        message for message in second.messages if is_movable_context_notice(message)
    ]
    assert len(notices) == 1
    notice = notices[0]
    assert 'System message "AGENTS.md" are changed, now:' in str(notice.content)
    assert "VERSION B" in str(notice.content)
    assert "VERSION A" not in str(notice.content)
    assert notice.metadata.get(TAIL_SYSTEM_MESSAGE_MARKER) is True
    assert second.metadata["_movable_context_notices"] == [notice]

    # The kernel writes the notice into durable history. A later step must not
    # emit it a second time.
    third = await kit.build_model_request(
        state,
        PromptContext(session_id="session-1", history=[notice]),
    )
    assert str(third.messages[0].content) == frozen
    assert third.metadata.get("_movable_context_notices") is None
    assert [m for m in third.messages if is_movable_context_notice(m)] == [notice]


@pytest.mark.asyncio
async def test_deleted_and_restored_blocks_are_reported_as_changed_or_deleted(
    monkeypatch, tmp_path
):
    parts = [_agents_part("VERSION A")]
    kit = _make_kit(monkeypatch, tmp_path, parts=parts)
    state = _state(tmp_path)

    first = await kit.build_model_request(state, PromptContext(session_id="session-1"))
    frozen = str(first.messages[0].content)

    parts[0] = _agents_part("VERSION B")
    changed = await kit.build_model_request(state, PromptContext(session_id="session-1"))
    changed_notice = changed.metadata["_movable_context_notices"][0]

    parts.clear()
    deleted = await kit.build_model_request(
        state,
        PromptContext(session_id="session-1", history=[changed_notice]),
    )
    assert str(deleted.messages[0].content) == frozen
    deleted_notice = deleted.metadata["_movable_context_notices"][0]
    assert 'System message "AGENTS.md" are deleted' in str(deleted_notice.content)
    assert "the copy in the leading system prompt no longer applies" in str(
        deleted_notice.content
    )

    parts.append(_agents_part("VERSION A"))
    restored = await kit.build_model_request(
        state,
        PromptContext(
            session_id="session-1",
            history=[changed_notice, deleted_notice],
        ),
    )
    assert str(restored.messages[0].content) == frozen
    restored_notice = restored.metadata["_movable_context_notices"][0]
    assert 'System message "AGENTS.md" are changed, now:' in str(
        restored_notice.content
    )
    assert "VERSION A" in str(restored_notice.content)


@pytest.mark.asyncio
async def test_restart_continues_the_persisted_frozen_epoch(monkeypatch, tmp_path):
    parts = [_agents_part("VERSION A")]
    kit = _make_kit(monkeypatch, tmp_path, parts=parts)
    state = _state(tmp_path)
    first = await kit.build_model_request(state, PromptContext(session_id="session-1"))
    frozen = str(first.messages[0].content)

    # A restart is a new kit with the durable state loaded from the store.
    parts[0] = _agents_part("VERSION B")
    restarted_kit = _make_kit(monkeypatch, tmp_path, parts=parts)
    restarted_state = RuntimeState(
        session_id="session-1",
        metadata=copy.deepcopy(state.metadata),
    )
    request = await restarted_kit.build_model_request(
        restarted_state,
        PromptContext(session_id="session-1"),
    )

    assert str(request.messages[0].content) == frozen
    notices = request.metadata["_movable_context_notices"]
    assert 'System message "AGENTS.md" are changed, now:' in str(notices[0].content)
    assert "VERSION B" in str(notices[0].content)


@pytest.mark.asyncio
async def test_compaction_rebuilds_the_epoch_from_the_latest_blocks(monkeypatch, tmp_path):
    parts = [_agents_part("VERSION A")]
    kit = _make_kit(monkeypatch, tmp_path, parts=parts)
    state = _state(tmp_path)
    first = await kit.build_model_request(state, PromptContext(session_id="session-1"))
    old_frozen = str(first.messages[0].content)

    parts[0] = _agents_part("VERSION B")
    kit.rebuild_movable_system_context(state)
    epoch = state.metadata[MOVABLE_CONTEXT_METADATA_KEY]
    assert "VERSION B" in epoch["system_prompt"]
    assert "VERSION A" not in epoch["system_prompt"]
    assert epoch["system_prompt"] != old_frozen

    request = await kit.build_model_request(state, PromptContext(session_id="session-1"))
    assert str(request.messages[0].content) == epoch["system_prompt"]
    assert request.metadata.get("_movable_context_notices") is None


@pytest.mark.asyncio
async def test_notice_is_appended_after_runtime_context_and_is_the_last_message(
    monkeypatch, tmp_path
):
    parts = [_agents_part("VERSION A")]
    kit = _make_kit(
        monkeypatch,
        tmp_path,
        parts=parts,
        config=CoreBaseAgentConfig(
            instructions="BASE INSTRUCTIONS",
            request_local_late_context="late child context",
        ),
    )
    state = _state(tmp_path)
    state.metadata["active_plan"] = {
        "plan_summary": "goal",
        "plan_steps": [{"id": "1", "description": "do it", "status": "running"}],
    }
    await kit.build_model_request(state, PromptContext(session_id="session-1"))

    wake = ChatMessage(
        role="system",
        content="member wake",
        metadata={
            "origin": "member_wake",
            "turn_id": "turn-1",
            TAIL_SYSTEM_MESSAGE_MARKER: True,
        },
    )
    parts[0] = _agents_part("VERSION B")
    request = await kit.build_model_request(
        state,
        PromptContext(session_id="session-1", history=[wake]),
    )

    assert request.messages[-1].metadata["key"] == "movable_context_notice"
    assert is_movable_context_notice(request.messages[-1])
    assert request.messages[-2] is wake
    assert request.messages[-3].content == "late child context"


@pytest.mark.asyncio
async def test_runtime_note_appends_only_changed_fields(monkeypatch, tmp_path):
    kit = _make_kit(monkeypatch, tmp_path, parts=[])
    state = _state(tmp_path)
    state.metadata["active_plan"] = {
        "plan_summary": "Goal A",
        "plan_files": ["a.txt"],
        "plan_steps": [
            {"id": "step-1", "status": "pending", "description": "Draft"},
        ],
    }

    first = await kit.build_model_request(state, PromptContext(session_id="session-1"))
    first_note = first.metadata["_runtime_context_delta"][0]
    assert "[Current plan]" in str(first_note.content)
    assert "Goal: Goal A" in str(first_note.content)
    assert "step-1 · pending · Draft" in str(first_note.content)

    state.metadata["active_plan"]["plan_steps"][0]["status"] = "completed"
    second = await kit.build_model_request(
        state,
        PromptContext(session_id="session-1", history=[first_note]),
    )
    second_note = second.metadata["_runtime_context_delta"][0]
    assert "[Runtime context update]" in str(second_note.content)
    assert "[Current plan]" not in str(second_note.content)
    assert "Goal: Goal A" not in str(second_note.content)
    assert "- Plan step step-1: completed · Draft" in str(second_note.content)

    third = await kit.build_model_request(
        state,
        PromptContext(session_id="session-1", history=[first_note, second_note]),
    )
    assert third.metadata.get("_runtime_context_delta") is None


@pytest.mark.asyncio
async def test_runtime_process_changes_are_appended_without_repeating_the_snapshot(
    monkeypatch, tmp_path
):
    kit = _make_kit(monkeypatch, tmp_path, parts=[])
    state = _state(tmp_path)
    running = {"123": "npm run dev"}
    monkeypatch.setattr(
        base_agent, "persistent_process_snapshot", lambda *_: dict(running)
    )

    first = await kit.build_model_request(state, PromptContext(session_id="session-1"))
    first_note = first.metadata["_runtime_context_delta"][0]
    assert "[Persistent Background Processes]" in str(first_note.content)
    assert "- pid 123 | running | npm run dev" in str(first_note.content)

    running.clear()
    second = await kit.build_model_request(
        state,
        PromptContext(session_id="session-1", history=[first_note]),
    )
    second_note = second.metadata["_runtime_context_delta"][0]
    assert str(second_note.content).startswith("[Runtime context update]")
    assert "- Process 123: exited" in str(second_note.content)
    assert "[Persistent Background Processes]" not in str(second_note.content)
