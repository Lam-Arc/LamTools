"""Tests for the global context tiers (project_context.py)."""

from __future__ import annotations

from lamtools_core.app.project_context import ProjectContextLoader
from lamtools_core.config.defaults import DEFAULT_AGENTS_MD


def test_global_agents_md_is_injected_before_project_files(tmp_path, isolated_config_root):
    isolated_config_root.mkdir(parents=True)
    (isolated_config_root / "AGENTS.md").write_text(
        "# Global instructions\nwork everywhere", encoding="utf-8"
    )
    work = tmp_path / "work"
    work.mkdir()
    (work / "AGENTS.md").write_text("# Project instructions\n", encoding="utf-8")

    parts = ProjectContextLoader().to_prompt_parts(work)

    names = [p.key for p in parts]
    assert "project_global_agents" in names
    assert names.index("project_global_agents") < names.index("project_agents")
    content = {p.key: p.content for p in parts}
    assert "work everywhere" in str(content["project_global_agents"])


def test_memory_index_is_injected_per_tier(tmp_path, isolated_config_root):
    global_memory = isolated_config_root / "memory"
    (global_memory / "topics").mkdir(parents=True)
    (global_memory / "topics" / "api.md").write_text(
        "# API 决策\n\nREST over GraphQL.\n", encoding="utf-8"
    )
    work = tmp_path / "work"
    project_memory = work / ".lam" / "memory"
    project_memory.mkdir(parents=True)
    (project_memory / "prefs.md").write_text("# 偏好\n中文用 UTF-8\n", encoding="utf-8")

    parts = ProjectContextLoader().to_prompt_parts(work)

    names = [p.key for p in parts]
    assert "project_global_memory" in names
    assert "project_memory" in names
    assert names.index("project_global_memory") < names.index("project_memory")
    content = {p.key: p.content for p in parts}
    assert "api.md" in str(content["project_global_memory"])
    assert "prefs.md" in str(content["project_memory"])
    # The generated index lands next to the tree it describes.
    assert (global_memory / "INDEX.md").is_file()
    assert (project_memory / "INDEX.md").is_file()


def test_empty_memory_tiers_are_not_injected(tmp_path, isolated_config_root):
    isolated_config_root.mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()

    parts = ProjectContextLoader().to_prompt_parts(work)

    keys = {part.key for part in parts}
    assert "project_global_memory" not in keys
    assert "project_memory" not in keys


def test_seeded_global_templates_are_not_injected(tmp_path, isolated_config_root):
    isolated_config_root.mkdir(parents=True)
    (isolated_config_root / "AGENTS.md").write_text(DEFAULT_AGENTS_MD, encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    (work / "AGENTS.md").write_text("project rules", encoding="utf-8")

    parts = ProjectContextLoader().to_prompt_parts(work)
    keys = {part.key for part in parts}

    assert "project_global_agents" not in keys
    assert "project_agents" in keys


def test_global_load_context_merges_with_workspace_load_context(tmp_path, isolated_config_root):
    isolated_config_root.mkdir(parents=True)
    (isolated_config_root / "load_context.jsonc").write_text(
        '{"addition": [{"name": "GLOBAL_EXTRA.md", "priority": 30}]}', encoding="utf-8"
    )
    work = tmp_path / "work"
    work.mkdir()
    (work / "load_context.jsonc").write_text(
        '{"addition": [{"name": "LOCAL_EXTRA.md", "priority": 40}], "except": ["CONTEXT.md"]}',
        encoding="utf-8",
    )
    (work / "GLOBAL_EXTRA.md").write_text("global extra", encoding="utf-8")
    (work / "LOCAL_EXTRA.md").write_text("local extra", encoding="utf-8")
    (work / "CONTEXT.md").write_text("excluded", encoding="utf-8")
    (work / "AGENTS.md").write_text("agents", encoding="utf-8")

    parts = ProjectContextLoader().to_prompt_parts(work)

    keys = {p.key for p in parts}
    # Both addition files are loaded; the workspace except applies globally.
    assert "project_global_extra" in keys
    assert "project_local_extra" in keys
    assert "project_context" not in keys
    assert "project_agents" in keys
    # Priority order: base AGENTS.md (10) < GLOBAL_EXTRA (30) < LOCAL_EXTRA (40).
    order = [p.key for p in parts]
    assert order.index("project_agents") < order.index("project_global_extra") < order.index("project_local_extra")


def test_workspace_load_context_without_global_is_unchanged(tmp_path, isolated_config_root):
    work = tmp_path / "work"
    work.mkdir()
    (work / "load_context.jsonc").write_text(
        '{"addition": [{"name": "ONLY_LOCAL.md", "priority": 25}]}', encoding="utf-8"
    )
    (work / "ONLY_LOCAL.md").write_text("local only", encoding="utf-8")

    parts = ProjectContextLoader().to_prompt_parts(work)

    assert "project_only_local" in {p.key for p in parts}
