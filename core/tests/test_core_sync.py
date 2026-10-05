from pathlib import Path

import pytest
from sqlalchemy import delete

from lamtools_core.app import AppEventInput, open_core_app_db
from lamtools_core.app.core_db import CoreSyncChange
from lamtools_core.app.operation_catalog import OperationCatalog
from lamtools_core.app.sync_store import SYNC_CURSOR_EXPIRED
from lamtools_core.app.live_operations import _character_page_snapshot, _history_turn_limit
from lamtools_core.checkpoint import register_checkpoint_operations
from lamtools_core.event import RunItemEvent


@pytest.mark.asyncio
async def test_sync_snapshot_and_project_delta_are_cursor_ordered(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        project, session, created = await db.project_store.create_with_initial_session(
            tmp_path / "workspace",
            name="Workspace",
        )
        assert created is True

        first = await db.sync_journal.sync(cursor=None)
        assert first["ok"] is True
        assert first["mode"] == "snapshot"
        assert first["cursor"] == first["snapshotVersion"]
        assert first["projects"][0]["id"] == project.id
        assert first["threads"][0]["id"] == session.id
        assert first["snapshots"] == []
        assert first["messages"] == []

        cursor = int(first["cursor"])
        renamed = await db.project_store.rename(project.id, "Renamed")
        assert renamed is not None

        delta = await db.sync_journal.sync(cursor=cursor)
        assert delta["ok"] is True
        assert delta["mode"] == "delta"
        assert delta["cursor"] > cursor
        assert delta["has_more"] is False
        assert [change["type"] for change in delta["changes"]] == ["project"]
        assert delta["changes"][0]["entity"]["name"] == "Renamed"
    finally:
        await db.close()


def test_thread_snapshot_pages_by_character_budget_and_excludes_artifact_bodies() -> None:
    snapshot = {
        "thread_id": "thread-1",
        "snapshot_seq": 9,
        "revision": 4,
        "artifacts": {"large": {"content": "x" * 50_000}},
        "core": {
            "thread_id": "thread-1",
            "snapshot_seq": 9,
            "revision": 4,
            "status": "completed",
            "seen_event_ids": [f"event-{index}" for index in range(1_000)],
            "artifacts": {"large": {"content": "x" * 50_000}},
            "items": {
                f"item-{index}": {
                    "item_id": f"item-{index}",
                    "turn_id": f"turn-{index}",
                    "seq": index,
                    "type": "message",
                    "content": str(index) * 700,
                }
                for index in range(1, 6)
            },
            "item_order": [f"item-{index}" for index in range(1, 6)],
            "turns": {
                f"turn-{index}": {
                    "turn_id": f"turn-{index}",
                    "status": "completed",
                    "items": [f"item-{index}"],
                }
                for index in range(1, 6)
            },
        },
    }

    latest = _character_page_snapshot(snapshot, before_item_id=None, before_seq=None, char_limit=1_500)
    latest_order = latest["core"]["item_order"]
    assert latest_order
    assert latest_order[-1] == "item-5"
    assert latest["history_page"]["has_more"] is True
    assert latest["core"]["artifacts"] == {}
    assert latest["artifacts"] == {}
    assert latest["core"]["seen_event_ids"] == []

    older = _character_page_snapshot(
        snapshot,
        before_item_id=latest["history_page"]["next_before_item_id"],
        before_seq=latest["history_page"]["next_before_seq"],
        char_limit=1_500,
    )
    assert older["core"]["item_order"]
    assert set(older["core"]["item_order"]).isdisjoint(latest_order)


def test_thread_history_defaults_to_ten_turns_per_page() -> None:
    assert _history_turn_limit({}) == 10
    assert _history_turn_limit({"turn_limit": 20}) == 20


def test_thread_snapshot_page_keeps_user_message_for_selected_assistant_turn() -> None:
    turn_id = "thread-1:turn:large"
    user_id = f"{turn_id}:user"
    snapshot = {
        "thread_id": "thread-1",
        "snapshot_seq": 20,
        "items": {
            user_id: {
                "item_id": user_id,
                "turn_id": turn_id,
                "seq": 1,
                "type": "userMessage",
                "content": [{"type": "text", "text": "Create the report"}],
            },
        },
        "item_order": [user_id],
        "turns": {
            turn_id: {
                "turn_id": turn_id,
                "status": "completed",
                "items": [user_id],
            },
        },
        "core": {
            "thread_id": "thread-1",
            "snapshot_seq": 20,
            "status": "completed",
            "items": {
                f"assistant-{index}": {
                    "item_id": f"assistant-{index}",
                    "turn_id": turn_id,
                    "seq": index + 1,
                    "type": "agentMessage",
                    "content": str(index) * 900,
                }
                for index in range(1, 6)
            },
            "item_order": [f"assistant-{index}" for index in range(1, 6)],
            "turns": {
                turn_id: {
                    "turn_id": turn_id,
                    "status": "completed",
                    "items": [f"assistant-{index}" for index in range(1, 6)],
                },
            },
        },
    }

    latest = _character_page_snapshot(
        snapshot,
        before_item_id=None,
        before_seq=None,
        char_limit=1_500,
    )

    assert latest["history_page"]["has_more"] is True
    assert latest["item_order"] == [user_id]
    assert latest["items"][user_id]["type"] == "userMessage"
    assert latest["turns"][turn_id]["items"] == [user_id]
    assert latest["core"]["item_order"] == ["assistant-5"]


def test_thread_snapshot_page_never_splits_a_turn() -> None:
    snapshot = {
        "thread_id": "thread-complete-turn",
        "snapshot_seq": 20,
        "items": {
            "user-1": {
                "item_id": "user-1",
                "turn_id": "turn-1",
                "seq": 1,
                "type": "userMessage",
                "content": [{"type": "text", "text": "first"}],
            },
            "user-2": {
                "item_id": "user-2",
                "turn_id": "turn-2",
                "seq": 10,
                "type": "userMessage",
                "content": [{"type": "text", "text": "second"}],
            },
        },
        "item_order": ["user-1", "user-2"],
        "turns": {
            "turn-1": {"turn_id": "turn-1", "status": "completed", "items": ["user-1"]},
            "turn-2": {"turn_id": "turn-2", "status": "completed", "items": ["user-2"]},
        },
        "core": {
            "thread_id": "thread-complete-turn",
            "snapshot_seq": 20,
            "status": "completed",
            "items": {
                **{
                    f"turn-1-item-{index}": {
                        "item_id": f"turn-1-item-{index}",
                        "turn_id": "turn-1",
                        "seq": index + 1,
                        "type": "reasoning" if index % 2 else "toolCall",
                        "content": "x" * 2_000,
                    }
                    for index in range(1, 6)
                },
                **{
                    f"turn-2-item-{index}": {
                        "item_id": f"turn-2-item-{index}",
                        "turn_id": "turn-2",
                        "seq": index + 10,
                        "type": "reasoning" if index % 2 else "toolCall",
                        "content": "y" * 2_000,
                    }
                    for index in range(1, 6)
                },
            },
            "item_order": [
                *[f"turn-1-item-{index}" for index in range(1, 6)],
                *[f"turn-2-item-{index}" for index in range(1, 6)],
            ],
            "turns": {
                "turn-1": {
                    "turn_id": "turn-1",
                    "status": "completed",
                    "items": [f"turn-1-item-{index}" for index in range(1, 6)],
                },
                "turn-2": {
                    "turn_id": "turn-2",
                    "status": "completed",
                    "items": [f"turn-2-item-{index}" for index in range(1, 6)],
                },
            },
        },
    }

    latest = _character_page_snapshot(
        snapshot,
        before_item_id=None,
        before_seq=None,
        char_limit=1_000,
        turn_limit=1,
    )
    assert latest["history_page"]["turn_count"] == 1
    assert latest["history_page"]["character_count"] > latest["history_page"]["char_limit"]
    assert latest["item_order"] == ["user-2"]
    assert latest["core"]["item_order"] == [f"turn-2-item-{index}" for index in range(1, 6)]
    assert latest["history_page"]["has_more"] is True

    older = _character_page_snapshot(
        snapshot,
        before_item_id=latest["history_page"]["next_before_item_id"],
        before_seq=latest["history_page"]["next_before_seq"],
        char_limit=1_000,
        turn_limit=1,
    )
    assert older["item_order"] == ["user-1"]
    assert older["core"]["item_order"] == [f"turn-1-item-{index}" for index in range(1, 6)]
    assert older["history_page"]["has_more"] is False


@pytest.mark.asyncio
async def test_project_mutations_publish_protocol_shaped_sync_changes_after_commit(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    published: list[dict] = []

    async def publish(item: dict) -> None:
        published.append(item)

    db.project_store.set_sync_publisher(publish)
    try:
        project, session, _ = await db.project_store.create_with_initial_session(tmp_path / "workspace")
        assert [item["method"] for item in published] == ["sync/change", "sync/change"]
        assert all(item["params"]["seq"] > 0 for item in published)
        assert {item["params"]["type"] for item in published} == {"project", "thread"}

        published.clear()
        await db.project_store.rename(project.id, "Renamed")
        assert published[0]["params"]["entity"]["name"] == "Renamed"

        published.clear()
        assert await db.project_store.delete(project.id) is True
        assert {item["params"]["operation"] for item in published} == {"delete"}
        assert session.id in {item["params"]["entity_id"] for item in published}
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_sync_project_delete_emits_project_and_thread_tombstones(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        project, session, created = await db.project_store.create_with_initial_session(tmp_path / "workspace")
        assert created is True
        before = await db.sync_journal.current_cursor()

        assert await db.project_store.delete(project.id) is True
        delta = await db.sync_journal.sync(cursor=before)
        assert delta["mode"] == "delta"
        changes = delta["changes"]
        assert {(change["type"], change["operation"], change["entity_id"]) for change in changes} == {
            ("project", "delete", project.id),
            ("thread", "delete", session.id),
        }
        assert all(change["entity"]["deleted"] is True for change in changes)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_sync_returns_cursor_expired_when_history_has_a_gap(tmp_path: Path) -> None:
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        async def append_changes(connection) -> None:
            db.sync_journal.append(
                connection,
                entity_type="project",
                operation="upsert",
                entity_id="p1",
                entity={"id": "p1"},
            )
            db.sync_journal.append(
                connection,
                entity_type="project",
                operation="upsert",
                entity_id="p2",
                entity={"id": "p2"},
            )
            await connection.flush()

        await db.persistence.write(append_changes)
        async with db.session_factory() as connection:
            await connection.execute(delete(CoreSyncChange).where(CoreSyncChange.seq == 1))
            await connection.commit()

        result = await db.sync_journal.sync(cursor=0)
        assert result["ok"] is False
        assert result["error"] == SYNC_CURSOR_EXPIRED
        assert result["oldest_cursor"] == 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_rollback_is_a_persisted_sync_boundary_that_requires_a_snapshot(tmp_path: Path) -> None:
    work_root = tmp_path / "workspace"
    work_root.mkdir()
    db = await open_core_app_db(tmp_path / "core.db")
    catalog = OperationCatalog()
    register_checkpoint_operations(
        catalog,
        session_factory=db.session_factory,
        default_work_root=work_root,
        app_event_store=db.event_store,
        thread_snapshot_store=db.snapshot_store,
    )

    async def append_turn(turn_id: str, text: str) -> None:
        async def write(connection) -> None:
            await db.persistence.append_batch(
                connection,
                app_events=[AppEventInput(
                    thread_id="rollback-sync",
                    turn_id=turn_id,
                    method="turn/accepted",
                    payload={"turn_id": turn_id, "input": text},
                )],
                run_item_events=[
                    RunItemEvent(
                        kind="message",
                        thread_id="rollback-sync",
                        turn_id=turn_id,
                        item_id=f"{turn_id}:user",
                        status="completed",
                        payload={"role": "user", "content": text},
                    ),
                    RunItemEvent(
                        kind="message",
                        thread_id="rollback-sync",
                        turn_id=turn_id,
                        item_id=f"{turn_id}:assistant",
                        status="completed",
                        payload={"role": "assistant", "content": f"reply {text}"},
                    ),
                    RunItemEvent(
                        kind="status",
                        thread_id="rollback-sync",
                        turn_id=turn_id,
                        item_id=f"{turn_id}:status",
                        status="completed",
                        payload={"status": "completed"},
                    ),
                ],
            )

        await db.persistence.write(write)

    try:
        await append_turn("turn-1", "one")
        await append_turn("turn-2", "two")
        before = await db.sync_journal.current_cursor()

        result = await catalog.execute("session.rollback", {
            "session_id": "rollback-sync",
            "turn_id": "turn-2",
        })

        assert result.status == "ok", result.payload
        assert result.payload["mode"] == "conversation_only"
        assert result.payload["rollback_event"]["method"] == "session/rollback"
        delta = await db.sync_journal.sync(cursor=before)
        assert delta["mode"] == "delta"
        assert len(delta["changes"]) == 1
        change = delta["changes"][0]
        assert change["type"] == "thread.event"
        assert change["snapshot_required"] is True
        assert change["entity"]["snapshot_required"] is True
        assert change["entity"]["event"]["method"] == "session/rollback"
        assert change["entity"]["event"]["payload"]["target_turn_id"] == "turn-2"
    finally:
        await db.close()
