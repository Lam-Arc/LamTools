"""Plugin-owned session visibility follows the live plugin enabled state."""

from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.app.core_db import open_core_app_db
from lamtools_core.app.core_session_store import CoreDbSessionStore
from lamtools_core.plugins.registry import PluginStateStore, bundled_plugins_dir
from lamtools_core.plugins.session_visibility import PluginSessionVisibility
from lamtools_core.session import MessageRecord, SessionRecord


@pytest.mark.asyncio
async def test_disabled_plugin_sessions_are_not_materialized_or_listed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LAMTOOLS_HOME", str(tmp_path / "home"))
    data_dir = tmp_path / "data"
    state_store = PluginStateStore(data_dir / "plugins.jsonc")
    visibility = PluginSessionVisibility(
        plugin_roots=[bundled_plugins_dir()],
        state_store=state_store,
    )
    db = await open_core_app_db(tmp_path / "core.db")
    sessions = CoreDbSessionStore(lambda: db, session_visible=visibility)
    db.project_store.set_session_visibility(visibility)
    project, _ = await db.project_store.create(tmp_path / "project")

    await sessions.create(
        SessionRecord(
            id="chat",
            member_id="core",
            title="Chat",
            status="idle",
            metadata={"work_root": project.work_root},
        )
    )
    await sessions.create(
        SessionRecord(
            id="wf_legacy",
            member_id="core",
            title="Legacy Workflow",
            status="idle",
            metadata={"work_root": project.work_root},
        )
    )
    await sessions.create(
        SessionRecord(
            id="workflow:demo",
            member_id="core",
            title="Workflow",
            status="idle",
            metadata={
                "work_root": project.work_root,
                "owner_plugin": "workflow",
                "resource_type": "workflow",
                "resource_id": "demo",
            },
        )
    )
    await sessions.add_message(
        MessageRecord(
            id="workflow-message",
            session_id="workflow:demo",
            role="assistant",
            content="workflow state",
        )
    )

    state_store.set_enabled("workflow", False)

    assert await sessions.get("workflow:demo") is None
    assert await sessions.get("wf_legacy") is None
    assert "workflow:demo" not in {session.id for session in await sessions.list()}
    assert await sessions.list_messages("workflow:demo") == []
    assert await sessions.patch("workflow:demo", title="must not write") is None
    assert await sessions.delete("workflow:demo") is False
    assert "workflow:demo" not in {
        session.id for session in await db.project_store.list_sessions(project.id)
    }

    state_store.set_enabled("workflow", True)

    assert (await sessions.get("workflow:demo")).title == "Workflow"
    assert (await sessions.get("wf_legacy")).title == "Legacy Workflow"
    assert [message.id for message in await sessions.list_messages("workflow:demo")] == [
        "workflow-message"
    ]
    assert "workflow:demo" in {
        session.id for session in await db.project_store.list_sessions(project.id)
    }
    await db.close()
