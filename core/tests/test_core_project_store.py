from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.app import open_core_app_db
from lamtools_core.app.core_db import CoreAppEvent, CoreRuntimeSession
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.app.project_store import (
    ActiveProjectSessionsError,
    ensure_workspace_root,
    normalize_workspace_root,
    read_workspace_agents_md,
    write_workspace_agents_md,
)


def test_workspace_helpers_normalize_create_and_round_trip_utf8_agents(tmp_path: Path) -> None:
    root = tmp_path / "nested" / "workspace" / ".." / "workspace"

    assert normalize_workspace_root(root) == root.resolve()
    assert ensure_workspace_root(root) == root.resolve()
    assert root.resolve().is_dir()
    assert read_workspace_agents_md(root) == {"content": "", "exists": False}

    content = "# 项目规则\n\n请使用 UTF-8。\n"
    assert write_workspace_agents_md(root, content) == {"content": content, "exists": True}
    assert read_workspace_agents_md(root) == {"content": content, "exists": True}


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
        assert [session.metadata for session in await db.project_store.list_sessions(project.id)] == [
            {"project_id": project.id, "work_root": str(requested_root.resolve())}
        ]
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
async def test_public_delete_cleans_linked_session_records_without_deleting_workspace(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    root = tmp_path / "workspace"
    try:
        project, _ = await db.project_store.create(root)

        renamed = await db.project_store.rename(project.id, "Renamed workspace")
        assert renamed is not None
        assert renamed.name == "Renamed workspace"
        assert await db.project_store.get(project.id) == renamed
        assert await db.project_store.list() == [renamed]

        [session] = await db.project_store.list_sessions(project.id)

        async def add_related_records(connection) -> None:
            connection.add(
                CoreAppEvent(
                    event_id="public-delete-event",
                    thread_id=session.id,
                    seq=1,
                    method="thread/started",
                    payload_json={},
                )
            )
            connection.add(CoreRuntimeSession(thread_id=session.id))

        await db.persistence.write(add_related_records)

        assert await db.project_store.delete(project.id) is True
        assert await db.project_store.get(project.id) is None
        assert await db.project_store.list_sessions(project.id) == []
        async with db.session_factory() as connection:
            assert await connection.get(CoreAppEvent, "public-delete-event") is None
            assert await connection.get(CoreRuntimeSession, session.id) is None
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


@pytest.mark.asyncio
async def test_create_with_initial_session_returns_the_public_initial_session(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    root = tmp_path / "workspace"
    try:
        project, initial_session, created = await db.project_store.create_with_initial_session(root, name="Docs")

        assert created is True
        assert initial_session.metadata == {
            "project_id": project.id,
            "work_root": str(root.resolve()),
        }
        assert await db.project_store.list_sessions(project.id) == [initial_session]

    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "waiting", "interrupting"])
async def test_public_delete_rejects_active_linked_sessions(tmp_path: Path, status: str) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        project, _ = await db.project_store.create(tmp_path / "workspace")
        [session] = await db.project_store.list_sessions(project.id)
        await CoreDbSessionStore(lambda: db).patch(session.id, status=status)

        with pytest.raises(ActiveProjectSessionsError, match="active session"):
            await db.project_store.delete(project.id)
        assert await db.project_store.get(project.id) is not None
    finally:
        await db.close()
