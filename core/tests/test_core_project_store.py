from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.app import open_core_app_db


@pytest.mark.asyncio
async def test_create_makes_normalized_workspace_without_initializing_git(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    requested_root = tmp_path / "nested" / "workspace" / ".." / "workspace"
    try:
        project, created = await db.project_store.create(requested_root)

        assert created is True
        assert project.work_root == str(requested_root.resolve())
        assert project.name == "workspace"
        assert requested_root.resolve().is_dir()
        assert not (requested_root.resolve() / ".git").exists()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_create_same_normalized_workspace_keeps_original_project_name(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    root = tmp_path / "workspace"
    try:
        first, first_created = await db.project_store.create(root, name="First name")
        duplicate, duplicate_created = await db.project_store.create(root / ".", name="Second name")

        assert first_created is True
        assert duplicate_created is False
        assert duplicate.id == first.id
        assert duplicate.name == "First name"
        assert await db.project_store.list() == [first]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_project_record_can_be_renamed_listed_and_deleted_without_deleting_workspace(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    root = tmp_path / "workspace"
    try:
        project, _ = await db.project_store.create(root)

        renamed = await db.project_store.rename(project.id, "Renamed workspace")
        assert renamed is not None
        assert renamed.name == "Renamed workspace"
        assert await db.project_store.get(project.id) == renamed
        assert await db.project_store.list() == [renamed]

        assert await db.project_store.delete(project.id) is True
        assert await db.project_store.get(project.id) is None
        assert root.is_dir()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_agents_md_is_utf8_and_survives_project_record_deletion(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    root = tmp_path / "workspace"
    try:
        project, _ = await db.project_store.create(root)

        assert await db.project_store.read_agents_md(project.id) == {"content": "", "exists": False}

        content = "# 项目规则\n\n使用 UTF-8。\n"
        assert await db.project_store.write_agents_md(project.id, content) == {"content": content, "exists": True}
        assert await db.project_store.read_agents_md(project.id) == {"content": content, "exists": True}

        assert await db.project_store.delete(project.id) is True
        assert (root / "AGENTS.md").read_text(encoding="utf-8") == content
    finally:
        await db.close()
