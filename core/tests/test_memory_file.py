"""Tests for MEMORY.md parsing and rewriting."""

from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.mem import MemoryEntry
from lamtools_core.mem.memory_file import (
    merge_into_memory_md,
    parse_memory_md,
    write_memory_md,
)


SAMPLE_MEMORY_MD = """\
# Memory

> 由 LamTools dreaming 自动维护。

## Preferences
- [2026-08-04] 用户偏好 PowerShell 中文用 UTF-8 — source: session#a
- 这是我手动写的偏好

## Facts
- [2026-08-04] 数据库在 data/core.db — source: session#b

## Todo
- [ ] 接 FTS5 — source: session#b

## Deprecated
- ~~向量检索~~（LIKE 足够） — source: session#a
"""


@pytest.fixture
def memory_file(tmp_path: Path) -> Path:
    p = tmp_path / "MEMORY.md"
    p.write_text(SAMPLE_MEMORY_MD, encoding="utf-8")
    return p


class TestParseMemoryMd:
    def test_parse_nonexistent_returns_empty(self, tmp_path: Path):
        snap = parse_memory_md(tmp_path / "nope.md")
        assert snap.entries == []

    def test_parse_all_sections(self, memory_file: Path):
        snap = parse_memory_md(memory_file)
        sections = {e.section for e in snap.entries}
        assert sections == {"preferences", "facts", "todo", "deprecated"}

    def test_parse_machine_entry(self, memory_file: Path):
        snap = parse_memory_md(memory_file)
        pref = [e for e in snap.entries if e.section == "preferences" and e.source == "session#a"]
        assert len(pref) == 1
        assert pref[0].content == "用户偏好 PowerShell 中文用 UTF-8"
        assert pref[0].date == "2026-08-04"
        assert not pref[0].is_human

    def test_parse_human_entry(self, memory_file: Path):
        snap = parse_memory_md(memory_file)
        human = [e for e in snap.entries if e.is_human]
        assert len(human) == 1
        assert human[0].content == "这是我手动写的偏好"
        assert human[0].source == ""

    def test_parse_todo_open(self, memory_file: Path):
        snap = parse_memory_md(memory_file)
        todo = [e for e in snap.entries if e.section == "todo"]
        assert len(todo) == 1
        assert todo[0].is_todo_open
        assert todo[0].content == "接 FTS5"

    def test_parse_deprecated(self, memory_file: Path):
        snap = parse_memory_md(memory_file)
        dep = [e for e in snap.entries if e.section == "deprecated"]
        assert len(dep) == 1
        assert dep[0].is_deprecated
        assert dep[0].content == "向量检索"
        assert dep[0].note == "LIKE 足够"


class TestWriteMemoryMd:
    def test_round_trip_preserves_entries(self, memory_file: Path):
        snap = parse_memory_md(memory_file)
        write_memory_md(memory_file, snap)
        snap2 = parse_memory_md(memory_file)
        assert len(snap2.entries) == len(snap.entries)
        # Contents preserved
        contents = {e.content for e in snap2.entries}
        assert "用户偏好 PowerShell 中文用 UTF-8" in contents
        assert "这是我手动写的偏好" in contents

    def test_write_creates_header(self, tmp_path: Path):
        p = tmp_path / "MEMORY.md"
        write_memory_md(p, parse_memory_md(p))  # empty snapshot
        text = p.read_text(encoding="utf-8")
        assert "# Memory" in text
        assert "dreaming" in text.lower()


class TestMergeIntoMemoryMd:
    def test_merge_new_entry(self, memory_file: Path):
        result = merge_into_memory_md(
            memory_file,
            [MemoryEntry(id="m3", kind="decision", content="短期记忆不注入 prompt", source="session#c", confidence=0.8)],
            today="2026-08-05",
        )
        assert result["added"] == 1
        snap = parse_memory_md(memory_file)
        decisions = [e for e in snap.entries if e.section == "decisions"]
        assert len(decisions) == 1
        assert decisions[0].content == "短期记忆不注入 prompt"
        assert decisions[0].source == "session#c"
        assert decisions[0].date == "2026-08-05"

    def test_merge_updates_existing(self, memory_file: Path):
        result = merge_into_memory_md(
            memory_file,
            [MemoryEntry(id="m1", kind="fact", content="数据库在 data/core.db（14张表）", source="session#b", confidence=0.9)],
            today="2026-08-05",
        )
        assert result["updated"] == 1
        snap = parse_memory_md(memory_file)
        facts = [e for e in snap.entries if e.section == "facts"]
        assert len(facts) == 1
        assert facts[0].content == "数据库在 data/core.db（14张表）"
        assert facts[0].date == "2026-08-05"

    def test_merge_preserves_human_entries(self, memory_file: Path):
        merge_into_memory_md(
            memory_file,
            [MemoryEntry(id="m1", kind="fact", content="new fact", source="session#x", confidence=0.9)],
        )
        snap = parse_memory_md(memory_file)
        human = [e for e in snap.entries if e.is_human]
        assert len(human) == 1
        assert human[0].content == "这是我手动写的偏好"

    def test_merge_same_source_different_kinds(self, memory_file: Path):
        """session#b appears in both facts and todo — updating one must not clobber the other."""
        result = merge_into_memory_md(
            memory_file,
            [
                MemoryEntry(id="m1", kind="fact", content="数据库在 data/core.db（更新）", source="session#b", confidence=0.9),
            ],
            today="2026-08-05",
        )
        assert result["updated"] == 1
        snap = parse_memory_md(memory_file)
        todos = [e for e in snap.entries if e.section == "todo"]
        assert len(todos) == 1
        assert todos[0].content == "接 FTS5"  # untouched

    def test_merge_into_nonexistent_file(self, tmp_path: Path):
        p = tmp_path / "MEMORY.md"
        result = merge_into_memory_md(
            p,
            [MemoryEntry(id="m1", kind="fact", content="first fact", source="session#a", confidence=0.9)],
        )
        assert result["added"] == 1
        assert p.exists()
        snap = parse_memory_md(p)
        assert len(snap.entries) == 1
