"""Tests for the directory-backed memory library (mem/library.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core import mem as memory


@pytest.fixture()
def project_work(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    return work


def test_project_and_global_roots_are_distinct(project_work, isolated_config_root):
    project_root = memory.memory_root(memory.SCOPE_PROJECT, project_work)
    global_root = memory.memory_root(memory.SCOPE_GLOBAL, None)

    assert project_root == project_work / ".lam" / "memory"
    assert global_root == isolated_config_root / "memory"
    assert project_root != global_root


def test_project_scope_requires_a_workspace():
    with pytest.raises(memory.MemoryPathError):
        memory.memory_root(memory.SCOPE_PROJECT, None)


@pytest.mark.parametrize(
    "relative",
    ["../escape.md", "notes/../../escape.md", "/etc/passwd", "C:/windows/hosts"],
)
def test_paths_cannot_escape_the_memory_root(project_work, relative):
    with pytest.raises(memory.MemoryPathError):
        memory.resolve_memory_path(memory.SCOPE_PROJECT, project_work, relative)


def test_generated_index_is_reserved(project_work):
    with pytest.raises(memory.MemoryReservedError):
        memory.resolve_memory_path(memory.SCOPE_PROJECT, project_work, memory.INDEX_FILENAME)


def test_index_name_is_reserved_at_any_depth(project_work):
    with pytest.raises(memory.MemoryReservedError):
        memory.write_memory(memory.SCOPE_PROJECT, project_work, "notes/INDEX.md", "x")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda work: memory.write_memory(memory.SCOPE_PROJECT, work, "", "x"),
        lambda work: memory.append_memory(memory.SCOPE_PROJECT, work, "", "x"),
        lambda work: memory.edit_memory(memory.SCOPE_PROJECT, work, "", "a", "b"),
        lambda work: memory.rename_memory(memory.SCOPE_PROJECT, work, "", "b.md"),
        lambda work: memory.rename_memory(memory.SCOPE_PROJECT, work, "a.md", ""),
    ],
)
def test_file_mutations_reject_an_empty_path(project_work, mutate):
    memory.write_memory(memory.SCOPE_PROJECT, project_work, "a.md", "a")

    with pytest.raises(memory.MemoryPathError):
        mutate(project_work)

    # The tier root must never be materialised as a file by a bad call.
    assert not (project_work / ".lam" / "memory").is_file()


def test_refresh_index_returns_the_rendered_text(project_work):
    memory.write_memory(memory.SCOPE_PROJECT, project_work, "a.md", "# A\n")

    text = memory.refresh_index(memory.SCOPE_PROJECT, project_work)
    on_disk = (
        memory.memory_root(memory.SCOPE_PROJECT, project_work) / memory.INDEX_FILENAME
    ).read_text(encoding="utf-8")

    assert "`a.md`" in text
    assert text == on_disk


def test_write_read_append_edit_roundtrip(project_work):
    memory.write_memory(memory.SCOPE_PROJECT, project_work, "notes/a.md", "# A\n")
    assert memory.read_memory(memory.SCOPE_PROJECT, project_work, "notes/a.md") == "# A\n"

    memory.append_memory(memory.SCOPE_PROJECT, project_work, "notes/a.md", "- item\n")
    assert memory.read_memory(memory.SCOPE_PROJECT, project_work, "notes/a.md") == "# A\n- item\n"

    memory.edit_memory(memory.SCOPE_PROJECT, project_work, "notes/a.md", "item", "entry")
    assert memory.read_memory(memory.SCOPE_PROJECT, project_work, "notes/a.md") == "# A\n- entry\n"


def test_edit_reports_ambiguous_and_missing_matches(project_work):
    memory.write_memory(memory.SCOPE_PROJECT, project_work, "dup.md", "x\nx\n")

    with pytest.raises(memory.MemoryConflictError):
        memory.edit_memory(memory.SCOPE_PROJECT, project_work, "dup.md", "x", "y")

    updated = memory.edit_memory(memory.SCOPE_PROJECT, project_work, "dup.md", "x", "y", occurrence=2)
    assert updated.path == "dup.md"
    assert memory.read_memory(memory.SCOPE_PROJECT, project_work, "dup.md") == "x\ny\n"

    with pytest.raises(memory.MemoryNotFoundError):
        memory.edit_memory(memory.SCOPE_PROJECT, project_work, "dup.md", "zzz", "y")


def test_delete_rename_and_mkdir(project_work):
    memory.make_directory(memory.SCOPE_PROJECT, project_work, "topics")
    memory.write_memory(memory.SCOPE_PROJECT, project_work, "topics/a.md", "a")
    memory.rename_memory(memory.SCOPE_PROJECT, project_work, "topics/a.md", "topics/b.md")

    assert memory.read_memory(memory.SCOPE_PROJECT, project_work, "topics/b.md") == "a"

    with pytest.raises(memory.MemoryConflictError):
        memory.rename_memory(memory.SCOPE_PROJECT, project_work, "topics/b.md", "topics/b.md")

    memory.delete_memory(memory.SCOPE_PROJECT, project_work, "topics")
    with pytest.raises(memory.MemoryNotFoundError):
        memory.list_entries(memory.SCOPE_PROJECT, project_work, path="topics")


def test_missing_file_operations_error(project_work):
    with pytest.raises(memory.MemoryNotFoundError):
        memory.read_memory(memory.SCOPE_PROJECT, project_work, "nope.md")
    with pytest.raises(memory.MemoryNotFoundError):
        memory.delete_memory(memory.SCOPE_PROJECT, project_work, "nope.md")


def test_listing_skips_the_generated_index(project_work):
    memory.write_memory(memory.SCOPE_PROJECT, project_work, "a.md", "# A\n")
    memory.refresh_index(memory.SCOPE_PROJECT, project_work)

    paths = [entry.path for entry in memory.list_entries(memory.SCOPE_PROJECT, project_work)]

    assert paths == ["a.md"]
    assert (memory.memory_root(memory.SCOPE_PROJECT, project_work) / memory.INDEX_FILENAME).is_file()


def test_listing_an_untouched_tier_is_empty(project_work):
    assert memory.list_entries(memory.SCOPE_PROJECT, project_work) == []


def test_index_summarises_files_and_reports_empty(project_work):
    empty = memory.render_index(memory.SCOPE_PROJECT, project_work)
    assert "暂无记忆" in empty

    memory.write_memory(memory.SCOPE_PROJECT, project_work, "notes/api.md", "# API 决策\n\nREST。\n")
    index = memory.render_index(memory.SCOPE_PROJECT, project_work)

    assert "API 决策" in index
    assert "`api.md`" in index
    assert "INDEX.md" not in index
    assert "scope=project" in index


def test_index_text_for_prompt_is_empty_until_something_is_stored(project_work):
    assert memory.index_text_for_prompt(memory.SCOPE_PROJECT, project_work) == ""

    memory.write_memory(memory.SCOPE_PROJECT, project_work, "a.md", "# A\n")

    text = memory.index_text_for_prompt(memory.SCOPE_PROJECT, project_work)
    assert "`a.md`" in text


def test_has_content_is_a_pure_probe_ignoring_the_generated_index(tmp_path):
    filled = tmp_path / "filled"
    memory.write_memory(memory.SCOPE_PROJECT, filled, "a.md", "# A\n")
    assert memory.has_content(memory.SCOPE_PROJECT, filled) is True

    # 只有自动生成的索引也算没记忆：索引是脚手架，不是记忆本身。
    index_only = tmp_path / "index-only"
    (index_only / ".lam" / "memory").mkdir(parents=True)
    memory.refresh_index(memory.SCOPE_PROJECT, index_only)
    assert (index_only / ".lam" / "memory" / "INDEX.md").is_file()
    assert memory.has_content(memory.SCOPE_PROJECT, index_only) is False

    # 空目录与不存在的根都算没记忆，且探测不创建任何东西。
    empty = tmp_path / "empty"
    empty.mkdir()
    assert memory.has_content(memory.SCOPE_PROJECT, empty) is False
    missing = tmp_path / "missing"
    assert memory.has_content(memory.SCOPE_PROJECT, missing) is False
    assert not missing.exists()
    assert not (empty / ".lam").exists()


def test_global_tier_uses_the_config_directory(isolated_config_root):
    memory.write_memory(memory.SCOPE_GLOBAL, None, "facts.md", "shared")

    assert (isolated_config_root / "memory" / "facts.md").read_text(encoding="utf-8") == "shared"


def test_scope_aliases_resolve_to_the_two_tiers():
    assert memory.normalize_scope("") == memory.SCOPE_PROJECT
    assert memory.normalize_scope("global") == memory.SCOPE_GLOBAL
    with pytest.raises(memory.MemoryPathError):
        memory.normalize_scope("nope")

def test_reveal_memory_creates_the_folder_and_opens_the_file_manager(project_work, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(
        "lamtools_core.attachment.files.open_with_default_app",
        lambda path: opened.append(str(path)),
    )

    returned = memory.reveal_memory(memory.SCOPE_PROJECT, project_work)

    expected = memory.memory_root(memory.SCOPE_PROJECT, project_work)
    assert returned == str(expected)
    assert expected.is_dir()
    assert opened == [str(expected)]


def test_reveal_memory_opens_the_global_tier(isolated_config_root, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(
        "lamtools_core.attachment.files.open_with_default_app",
        lambda path: opened.append(str(path)),
    )

    returned = memory.reveal_memory(memory.SCOPE_GLOBAL, None)

    assert returned == str(isolated_config_root / "memory")
    assert (isolated_config_root / "memory").is_dir()
    assert len(opened) == 1
