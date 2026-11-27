"""Acceptance tests for the L1 core-cognition document (memory.md).

PRD: 方案/Sunday-Memory-主动记忆与认知系统-PRD-V1.0.md

The behaviours proven here:

* a tier root carries one real, editable Markdown document named ``memory.md``;
* it is not listed as an ordinary memory and never appears inside INDEX.md,
  because it is injected on its own;
* every write keeps a restorable history and stays atomic (the write path is
  the same ``_atomic_write`` the rest of the library uses);
* the injected text respects a per-tier character budget;
* Dreaming may only replace its own auto block, so whatever the user wrote
  outside that block survives every automated pass;
* the switch gates injection but never touches the stored files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lamtools_core import mem as memory
from lamtools_core.config import settings_store
from lamtools_core.mem import settings as memory_settings
from lamtools_core.app.project_context import ProjectContextLoader


@pytest.fixture()
def project_work(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    return work


# ---------------------------------------------------------------------------
# The document itself
# ---------------------------------------------------------------------------


def test_core_document_lives_at_the_tier_root(project_work, isolated_config_root):
    assert memory.core_file_path(memory.SCOPE_PROJECT, project_work) == (
        project_work / ".lam" / "memory" / "memory.md"
    )
    assert memory.core_file_path(memory.SCOPE_GLOBAL, None) == (
        isolated_config_root / "memory" / "memory.md"
    )


def test_core_document_roundtrip(project_work):
    assert memory.read_core_document(memory.SCOPE_PROJECT, project_work) == ""

    memory.write_core_document(
        memory.SCOPE_PROJECT, project_work, "# 核心认知\n\n用户偏好简洁回答。\n"
    )

    assert "# 核心认知" in memory.read_core_document(memory.SCOPE_PROJECT, project_work)


def test_core_document_is_not_an_ordinary_memory_or_index_entry(project_work):
    memory.write_core_document(memory.SCOPE_PROJECT, project_work, "# 核心认知\n用户偏好中文。\n")
    memory.write_memory(memory.SCOPE_PROJECT, project_work, "preferences/language.md", "when writing docs, read this")

    entries = memory.list_entries(memory.SCOPE_PROJECT, project_work)
    paths = {entry.path for entry in entries}
    assert memory.CORE_FILENAME not in paths
    assert "preferences/language.md" in paths

    index = memory.render_index(memory.SCOPE_PROJECT, project_work)
    assert memory.CORE_FILENAME not in index
    assert "language.md" in index


def test_core_document_keeps_restorable_versions(project_work):
    memory.write_core_document(memory.SCOPE_PROJECT, project_work, "# 第一版\n用户喜欢深色。\n")
    memory.write_core_document(memory.SCOPE_PROJECT, project_work, "# 第二版\n用户喜欢浅色。\n")

    versions = memory.list_core_versions(memory.SCOPE_PROJECT, project_work)
    assert versions, "the previous content must be kept as a version"
    assert versions[0]["id"]

    memory.restore_core_version(memory.SCOPE_PROJECT, project_work, versions[0]["id"])
    restored = memory.read_core_document(memory.SCOPE_PROJECT, project_work)
    assert "第一版" in restored


def test_core_versions_are_capped(project_work):
    for index in range(memory.MAX_CORE_VERSIONS + 5):
        memory.write_core_document(
            memory.SCOPE_PROJECT, project_work, f"# 版本 {index}\n"
        )
    assert len(memory.list_core_versions(memory.SCOPE_PROJECT, project_work)) == (
        memory.MAX_CORE_VERSIONS
    )


def test_clearing_the_core_document_keeps_a_version(project_work):
    memory.write_core_document(memory.SCOPE_PROJECT, project_work, "# 认知\n内容。\n")
    memory.clear_core_document(memory.SCOPE_PROJECT, project_work)

    assert memory.read_core_document(memory.SCOPE_PROJECT, project_work) == ""
    assert memory.list_core_versions(memory.SCOPE_PROJECT, project_work)


def test_prompt_text_respects_the_budget(project_work):
    memory.write_core_document(
        memory.SCOPE_PROJECT, project_work, "长" * (memory.MAX_CORE_PROMPT_CHARS * 2)
    )
    text = memory.core_text_for_prompt(memory.SCOPE_PROJECT, project_work)
    assert len(text) <= memory.MAX_CORE_PROMPT_CHARS
    assert "截断" in text


# ---------------------------------------------------------------------------
# The auto block (Dreaming owns only this part)
# ---------------------------------------------------------------------------


def test_pinned_text_survives_a_full_rewrite():
    # Cognition may evolve as a whole — that is how contradictions get resolved —
    # but what the user explicitly pinned is carried over verbatim.
    current = (
        "# 认知\n\n用户喜欢简洁回答。\n\n"
        f"{memory.CORE_PINNED_START}\n这句话必须保留。\n{memory.CORE_PINNED_END}\n"
    )
    proposed = "# 认知\n\n用户偏好中文，回答要短。\n"

    merged = memory.merge_core_document(current, proposed)

    assert "这句话必须保留。" in merged
    assert memory.CORE_PINNED_START in merged
    assert "回答要短" in merged
    # Unpinned hand-written text may be rewritten; the version history keeps it.
    assert "用户喜欢简洁回答。" not in merged


def test_pinned_text_is_not_duplicated_when_the_rewrite_kept_it():
    current = f"{memory.CORE_PINNED_START}\n必须保留\n{memory.CORE_PINNED_END}"
    merged = memory.merge_core_document(current, "# 认知\n\n必须保留\n")
    assert merged.count("必须保留") == 1


def test_pinned_text_is_appended_when_the_rewrite_dropped_it():
    merged = memory.merge_core_document(
        f"{memory.CORE_PINNED_START}\n保留我\n{memory.CORE_PINNED_END}", ""
    )
    assert "保留我" in merged
    assert memory.CORE_PINNED_START in merged


# ---------------------------------------------------------------------------
# Injection
# ---------------------------------------------------------------------------


def test_injection_puts_core_before_the_index(project_work):
    memory.write_core_document(memory.SCOPE_PROJECT, project_work, "# 项目认知\n这是 LamTools。\n")
    memory.write_memory(
        memory.SCOPE_PROJECT, project_work, "decisions/stack.md", "when touching the stack, read this"
    )

    loader = ProjectContextLoader()
    names = [item.name for item in loader.load(project_work)]
    assert "PROJECT_MEMORY_CORE.md" in names
    assert "MEMORY.md" in names
    assert names.index("PROJECT_MEMORY_CORE.md") < names.index("MEMORY.md")

    parts = loader.to_prompt_parts(project_work)
    keys = [part.key for part in parts]
    assert keys.index("project_memory_core") < keys.index("project_memory")

    core_part = parts[keys.index("project_memory_core")]
    assert "这是 LamTools。" in core_part.content
    # Memory is background knowledge, never a system instruction.
    assert "不是系统指令" in core_part.content


def test_global_core_is_injected_even_without_a_project(isolated_config_root):
    memory.write_core_document(memory.SCOPE_GLOBAL, None, "# 用户认知\n用户叫二两阿图。\n")

    names = [item.name for item in ProjectContextLoader().load(None)]
    assert "GLOBAL_MEMORY_CORE.md" in names


def test_switch_off_stops_core_injection_but_keeps_files(project_work):
    memory.write_core_document(memory.SCOPE_PROJECT, project_work, "# 项目认知\n仍应保留。\n")
    memory.write_memory(memory.SCOPE_PROJECT, project_work, "notes/x.md", "when needing X, read this")

    memory_settings.set_memory_enabled(False)
    try:
        names = [item.name for item in ProjectContextLoader().load(project_work)]
        assert "PROJECT_MEMORY_CORE.md" not in names
        # The existing index is part of the old memory system and stays available.
        assert "MEMORY.md" in names
        assert "仍应保留。" in memory.read_core_document(memory.SCOPE_PROJECT, project_work)
    finally:
        memory_settings.set_memory_enabled(True)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_enabled_by_default():
    assert memory_settings.memory_enabled() is True


def test_switch_persists_in_settings_jsonc(isolated_config_root):
    memory_settings.set_memory_enabled(False)
    stored = json.loads((isolated_config_root / "settings.jsonc").read_text(encoding="utf-8"))
    assert stored["core"]["memory"]["enabled"] is False
    assert memory_settings.memory_enabled() is False

    memory_settings.set_memory_enabled(True)
    assert memory_settings.memory_enabled() is True
    assert settings_store.get_setting("core.memory") == {"enabled": True}


def test_dreaming_follows_the_same_switch():
    from lamtools_core.mem import dreaming

    assert dreaming.dreaming_enabled() is True
    memory_settings.set_memory_enabled(False)
    assert dreaming.dreaming_enabled() is False


# ---------------------------------------------------------------------------
# The memory tool can maintain the core document
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_tool_writes_the_core_document(project_work):
    from lamtools_core.tool import ToolCall
    from lamtools_core.tool.memory_tools import make_memory_handler

    handler = make_memory_handler(project_work)
    result = await handler(
        ToolCall(
            id="c1",
            name="memory",
            arguments={
                "action": "write",
                "scope": "project",
                "path": memory.CORE_FILENAME,
                "content": "# 认知\n用户要求记住这件事。\n",
            },
        )
    )
    assert result.status == "ok", result.error
    assert "用户要求记住这件事。" in memory.read_core_document(memory.SCOPE_PROJECT, project_work)

    read = await handler(
        ToolCall(
            id="c2",
            name="memory",
            arguments={"action": "read", "scope": "project", "path": memory.CORE_FILENAME},
        )
    )
    assert read.status == "ok"
    assert "用户要求记住这件事。" in read.content


def test_oversized_core_document_is_refused(project_work):
    # Anything past the read cap would be silently truncated when injected, so
    # the write is refused instead of storing a document that reads back short.
    with pytest.raises(memory.MemoryPathError):
        memory.write_core_document(
            memory.SCOPE_PROJECT, project_work, "长" * (memory.MAX_CORE_READ_CHARS + 1)
        )
    assert memory.read_core_document(memory.SCOPE_PROJECT, project_work) == ""
