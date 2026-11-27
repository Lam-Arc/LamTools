"""Cache stability of the memory injection.

PRD 4.2 asks that injected cognition stays stable so prompt caches are not
invalidated.  This suite proves that at the request boundary, not by reasoning:

* the leading system prompt is byte-identical before and after a memory change;
* the change appears once, as a tail notice, and only once;
* the next turn keeps the same frozen prefix (the epoch rides the snapshot);
* a re-seed (what compaction does) is the only point where the prefix changes;
* nothing in the injected text is volatile, so an unchanged library renders
  identically on every load;
* Dreaming writing the same content again is a no-op, so it cannot cause churn;
* turning the switch off is reported as a deletion at the tail, not a rewrite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import lamtools_core.app.base_agent as base_agent
from lamtools_core import mem as memory
from lamtools_core.app.base_agent import CoreBaseAgentKit
from lamtools_core.app.project_context import ProjectContextLoader
from lamtools_core.mem import dreaming
from lamtools_core.mem import settings as memory_settings
from lamtools_core.prompt import PromptContext
from lamtools_core.prompt.movable import (
    MOVABLE_CONTEXT_METADATA_KEY,
    is_movable_context_notice,
)
from lamtools_core.runtime import RuntimeState


class _Toolbox:
    load_tools = None

    def tool_specs(self):
        return []

    def model_tools(self, active_mode=None):
        return []

    def skill_index(self):
        return ""


def _kit(monkeypatch, work_root: Path) -> CoreBaseAgentKit:
    # Keep the real project-context loader: the memory blocks must come from the
    # actual files on disk, not from a stub.
    monkeypatch.setattr(
        base_agent,
        "command_shell_prompt",
        lambda: "[Command Shell]\nCurrent shell: Git Bash.",
    )
    monkeypatch.setattr(base_agent, "mode_prompt_line", lambda *_: "")
    kit = CoreBaseAgentKit(
        work_root=work_root,
        config=None,
        toolbox=_Toolbox(),  # type: ignore[arg-type]
        verification_policy=None,
    )
    monkeypatch.setattr(kit, "_cached_subagent_guide", lambda: "")
    monkeypatch.setattr(kit, "_cached_subagent_roles", lambda: "")
    monkeypatch.setattr(kit, "_cached_subagent_strategy", lambda: "")
    return kit


def _state(work_root: Path, *, epoch: dict | None = None, session: str = "s1") -> RuntimeState:
    metadata = {"work_root": str(work_root)}
    if epoch is not None:
        metadata[MOVABLE_CONTEXT_METADATA_KEY] = epoch
    return RuntimeState(session_id=session, metadata=metadata)


def _notices(request) -> list:
    return [message for message in request.messages if is_movable_context_notice(message)]


@pytest.fixture()
def project_work(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    return work


@pytest.mark.asyncio
async def test_memory_change_never_rewrites_the_frozen_prefix(monkeypatch, project_work):
    memory.write_core_document(
        memory.SCOPE_PROJECT, project_work, "# 项目认知\n用户偏好方案先行。\n"
    )
    kit = _kit(monkeypatch, project_work)
    state = _state(project_work)

    first = await kit.build_model_request(state, PromptContext(session_id="s1"))
    prefix = str(first.messages[0].content)
    assert "用户偏好方案先行。" in prefix
    assert _notices(first) == []

    # The user (or the memory tool) edits the document mid-epoch.
    memory.write_core_document(
        memory.SCOPE_PROJECT,
        project_work,
        "# 项目认知\n用户偏好方案先行。\n新增的长期约束：先写验收测试。\n",
    )
    second = await kit.build_model_request(state, PromptContext(session_id="s1"))

    # The cached prefix must be byte-identical; only the tail changes.
    assert str(second.messages[0].content) == prefix
    assert "新增的长期约束" not in str(second.messages[0].content)

    notices = _notices(second)
    assert len(notices) == 1
    assert second.messages[-1] is notices[0], "the notice must be the request tail"
    assert "新增的长期约束" in str(notices[0].content)


@pytest.mark.asyncio
async def test_a_change_is_announced_exactly_once(monkeypatch, project_work):
    memory.write_core_document(memory.SCOPE_PROJECT, project_work, "# 认知\n第一版。\n")
    kit = _kit(monkeypatch, project_work)
    state = _state(project_work)
    await kit.build_model_request(state, PromptContext(session_id="s1"))

    memory.write_core_document(memory.SCOPE_PROJECT, project_work, "# 认知\n第二版。\n")
    second = await kit.build_model_request(state, PromptContext(session_id="s1"))
    assert len(_notices(second)) == 1

    # Nothing changed since: the next request must not repeat the notice.
    third = await kit.build_model_request(state, PromptContext(session_id="s1"))
    assert _notices(third) == []
    assert str(third.messages[0].content) == str(second.messages[0].content)


@pytest.mark.asyncio
async def test_next_turn_keeps_the_same_frozen_prefix(monkeypatch, project_work):
    memory.write_core_document(memory.SCOPE_PROJECT, project_work, "# 认知\n原始内容。\n")
    kit = _kit(monkeypatch, project_work)
    first_turn = _state(project_work)
    request = await kit.build_model_request(first_turn, PromptContext(session_id="s1"))
    prefix = str(request.messages[0].content)

    # A new turn restores the previous snapshot, including the frozen epoch.
    epoch = first_turn.metadata[MOVABLE_CONTEXT_METADATA_KEY]
    memory.write_core_document(
        memory.SCOPE_PROJECT, project_work, "# 认知\n原始内容。\n下一轮才加上的内容。\n"
    )
    second_turn = _state(project_work, epoch=epoch)
    next_request = await kit.build_model_request(second_turn, PromptContext(session_id="s1"))

    assert str(next_request.messages[0].content) == prefix
    assert "下一轮才加上的内容" not in str(next_request.messages[0].content)
    assert "下一轮才加上的内容" in str(_notices(next_request)[0].content)


@pytest.mark.asyncio
async def test_compaction_reseed_is_the_only_prefix_change(monkeypatch, project_work):
    memory.write_core_document(memory.SCOPE_PROJECT, project_work, "# 认知\n旧内容。\n")
    kit = _kit(monkeypatch, project_work)
    state = _state(project_work)
    request = await kit.build_model_request(state, PromptContext(session_id="s1"))
    old_prefix = str(request.messages[0].content)

    memory.write_core_document(
        memory.SCOPE_PROJECT, project_work, "# 认知\n旧内容。\n压缩后应出现的内容。\n"
    )
    # What a successful compaction does: re-seed from the latest blocks.
    kit.rebuild_movable_system_context(state)
    reseeded = await kit.build_model_request(state, PromptContext(session_id="s1"))

    new_prefix = str(reseeded.messages[0].content)
    assert new_prefix != old_prefix
    assert "压缩后应出现的内容" in new_prefix
    assert _notices(reseeded) == [], "a fresh epoch has no diffs to report"


def test_unchanged_memory_renders_identically(project_work):
    memory.write_core_document(memory.SCOPE_PROJECT, project_work, "# 认知\n稳定内容。\n")
    memory.write_memory(
        memory.SCOPE_PROJECT, project_work, "notes/stack.md", "when touching the stack, read this"
    )

    first = [(item.name, item.content) for item in ProjectContextLoader().load(project_work)]
    second = [(item.name, item.content) for item in ProjectContextLoader().load(project_work)]

    assert first == second
    core = dict(first)["PROJECT_MEMORY_CORE.md"]
    # No timestamps or counters leak into the injected cognition.
    assert core.count("稳定内容。") == 1
    assert "20" not in core.split("memory.md")[0][-5:]


def test_dreaming_with_identical_content_is_a_no_op(project_work):
    memory.write_core_document(memory.SCOPE_PROJECT, project_work, "# 认知\n手写内容。\n")
    output = {
        "project": {
            "core": """# 认知
- 用户偏好方案先行
""",
            "memories": [],
        }
    }

    first = dreaming.apply_dream_output(work_root=project_work, output=output)
    after_first = memory.read_core_document(memory.SCOPE_PROJECT, project_work)
    versions_after_first = memory.list_core_versions(memory.SCOPE_PROJECT, project_work)

    second = dreaming.apply_dream_output(work_root=project_work, output=output)
    after_second = memory.read_core_document(memory.SCOPE_PROJECT, project_work)

    assert any(item["path"] == memory.CORE_FILENAME for item in first)
    # Same content again writes nothing, so the injected block cannot churn and
    # no extra version is recorded.
    assert not any(item["path"] == memory.CORE_FILENAME for item in second)
    assert after_second == after_first
    assert (
        len(memory.list_core_versions(memory.SCOPE_PROJECT, project_work))
        == len(versions_after_first)
    )


@pytest.mark.asyncio
async def test_switch_off_rebuilds_the_prefix_so_it_takes_effect(monkeypatch, project_work):
    # Cache protection must never make the switch cosmetic: flipping it rebuilds
    # the leading prompt once, so the cognition is really gone (or back).
    memory.write_core_document(
        memory.SCOPE_PROJECT,
        project_work,
        """# 认知
不应再注入。
""",
    )
    kit = _kit(monkeypatch, project_work)
    state = _state(project_work)
    request = await kit.build_model_request(state, PromptContext(session_id="s1"))
    assert "不应再注入。" in str(request.messages[0].content)

    memory_settings.set_memory_enabled(False)
    try:
        disabled = await kit.build_model_request(state, PromptContext(session_id="s1"))
        assert "不应再注入。" not in str(disabled.messages[0].content)
        assert _notices(disabled) == [], "a rebuild is the update; no tail diff is needed"

        memory_settings.set_memory_enabled(True)
        reopened = await kit.build_model_request(state, PromptContext(session_id="s1"))
        assert "不应再注入。" in str(reopened.messages[0].content)
    finally:
        memory_settings.set_memory_enabled(True)
