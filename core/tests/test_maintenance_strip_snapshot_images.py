"""Contract tests for the local-development snapshot-image maintenance pass."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text

from lamtools_core import maintenance
from lamtools_core.app.core_db import (
    CoreAppEvent,
    CoreSyncChange,
    CoreThreadSnapshot,
    CoreThreadSnapshotItem,
    open_core_app_db,
)
from lamtools_core.maintenance import (
    MaintenanceScopeError,
    backup_database_files,
    dev_data_dir,
    is_dev_data_dir,
    strip_snapshot_registry_images,
)

DATA_URL = "data:image/png;base64,LEGACY" + "B" * 256
BODY = "legacy file body " * 16
THREAD_ID = "fat-1"


def _legacy_state(thread_id: str, *, fat: bool = True) -> dict:
    metadata = {"path": "a.png", "size_bytes": 12}
    if fat:
        metadata["image_data_url"] = DATA_URL
    return {
        "thread_id": thread_id,
        "snapshot_seq": 3,
        "revision": 3,
        "status": "idle",
        "turns": {},
        "items": {},
        "item_order": [f"{thread_id}:item-1"],
        "requests": {},
        "artifacts": {},
        "core": {
            "thread_id": thread_id,
            "items": {},
            "item_order": [f"{thread_id}:item-1"],
            "artifacts": {
                "artifact-1": {
                    "artifact_id": "artifact-1",
                    "kind": "file_read",
                    "content": BODY,
                    "metadata": metadata,
                }
            },
        },
        "session": {"member_id": "core", "title": "Legacy", "metadata": {}},
    }


def _legacy_item(thread_id: str) -> dict:
    return {
        "item_id": f"{thread_id}:item-1",
        "kind": "tool_result",
        "artifacts": [
            {
                "artifact_id": "artifact-1",
                "kind": "file_read",
                "content": BODY,
                "metadata": {"image_data_url": DATA_URL, "path": "a.png"},
            }
        ],
    }


EVENT_ID = "evt-fat-1"
SYNC_CHANGE_ID = "sync-fat-1"


def _run_item_event(thread_id: str) -> dict:
    """A RunItemEvent dict with both the dead payload-metadata copy and the
    render copy on the top-level artifacts list."""
    return {
        "kind": "tool_result",
        "thread_id": thread_id,
        "event_id": EVENT_ID,
        "status": "completed",
        "payload": {
            "type": "dynamicToolCall",
            "tool_name": "read_file",
            "replace": True,
            "metadata": {"path": "a.png", "image_data_url": DATA_URL},
        },
        "artifacts": [
            {
                "artifact_id": "artifact-1",
                "kind": "file_read",
                "metadata": {"path": "a.png", "image_data_url": DATA_URL},
            }
        ],
        "created_at_ms": 1,
    }


def _envelope(thread_id: str) -> dict:
    return {
        "event_id": EVENT_ID,
        "thread_id": thread_id,
        "method": "core/runItem",
        "payload": _run_item_event(thread_id),
        "seq": 1,
        "event_type": "core/runItem",
        "entity_type": "thread.event",
        "entity_id": thread_id,
    }


def _legacy_item_with_payload_copy(thread_id: str) -> dict:
    item = _legacy_item(thread_id)
    item["payload"] = {
        "type": "dynamicToolCall",
        "tool_name": "read_file",
        "metadata": {"path": "a.png", "image_data_url": DATA_URL},
    }
    return item


async def _seed_full(tmp_path: Path, thread_id: str = THREAD_ID) -> Path:
    """Seed all four storage locations with a read-invisible image copy."""
    db_path = tmp_path / "core.db"
    db = await open_core_app_db(db_path)
    try:
        async with db.session_factory() as session:
            session.add(
                CoreThreadSnapshot(
                    thread_id=thread_id,
                    snapshot_seq=3,
                    revision=3,
                    snapshot_json=_legacy_state(thread_id),
                )
            )
            session.add(
                CoreThreadSnapshotItem(
                    thread_id=thread_id,
                    item_id=f"{thread_id}:item-1",
                    seq=1,
                    item_json=_legacy_item_with_payload_copy(thread_id),
                )
            )
            session.add(
                CoreAppEvent(
                    event_id=EVENT_ID,
                    thread_id=thread_id,
                    seq=1,
                    method="core/runItem",
                    payload_json=_run_item_event(thread_id),
                )
            )
            session.add(
                CoreSyncChange(
                    change_id=SYNC_CHANGE_ID,
                    workspace_id="ws",
                    entity_type="thread.event",
                    event_type="thread.event.upsert",
                    operation="upsert",
                    entity_id=thread_id,
                    thread_id=thread_id,
                    revision=1,
                    entity_json={"event": _envelope(thread_id)},
                )
            )
            await session.commit()
    finally:
        await db.close()
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return db_path


def _raw_json(db_path: Path, sql: str, params: tuple = ()) -> dict:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        row = connection.execute(sql, params).fetchone()
    assert row is not None
    return json.loads(row[0])


async def _seed(tmp_path: Path, thread_id: str = THREAD_ID, *, fat: bool = True) -> Path:
    db_path = tmp_path / "core.db"
    db = await open_core_app_db(db_path)
    try:
        async with db.session_factory() as session:
            session.add(
                CoreThreadSnapshot(
                    thread_id=thread_id,
                    snapshot_seq=3,
                    revision=3,
                    snapshot_json=_legacy_state(thread_id, fat=fat),
                )
            )
            if fat:
                session.add(
                    CoreThreadSnapshotItem(
                        thread_id=thread_id,
                        item_id=f"{thread_id}:item-1",
                        seq=1,
                        item_json=_legacy_item(thread_id),
                    )
                )
            await session.commit()
    finally:
        await db.close()
    # Fold the WAL back so a file-level backup of core.db holds the seeded rows.
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return db_path


def _raw_metadata_row(db_path: Path, thread_id: str = THREAD_ID) -> str:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT snapshot_json FROM core_thread_snapshots WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
    assert row is not None
    return row[0]


def _raw_item_rows(db_path: Path, thread_id: str = THREAD_ID) -> dict[str, str]:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT item_id, item_json FROM core_thread_snapshot_items WHERE thread_id = ? "
            "ORDER BY item_id",
            (thread_id,),
        ).fetchall()
    return {str(item_id): raw for item_id, raw in rows}


def _bookkeeping(db_path: Path, thread_id: str = THREAD_ID) -> tuple[int, str]:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT revision, updated_at FROM core_thread_snapshots WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
    assert row is not None
    return int(row[0]), str(row[1])


def test_scope_guard_only_allows_the_local_dev_data_dir(tmp_path: Path) -> None:
    assert is_dev_data_dir(dev_data_dir()) is True
    assert is_dev_data_dir(dev_data_dir() / "core.db") is False
    assert is_dev_data_dir(tmp_path / "data") is False
    # An installed (portable/green) data directory looks like this and must fail.
    installed = tmp_path / "setuptest" / "0.3.16" / ".lam" / "core" / "data"
    assert is_dev_data_dir(installed) is False


@pytest.mark.asyncio
async def test_scope_guard_refuses_before_creating_anything(tmp_path: Path) -> None:
    db_path = tmp_path / "installed" / "core.db"
    with pytest.raises(MaintenanceScopeError):
        await strip_snapshot_registry_images(db_path, apply=True)
    assert not db_path.exists()
    assert not db_path.parent.exists()


@pytest.mark.asyncio
async def test_dry_run_reports_the_plan_without_writing_or_backing_up(tmp_path: Path) -> None:
    db_path = await _seed(tmp_path)
    before = _raw_metadata_row(db_path)

    report = await strip_snapshot_registry_images(db_path, apply=False, allow_non_dev=True)

    assert report.applied is False
    assert report.ok is True
    assert report.sessions_changed == 1
    assert report.images_removed == 1
    assert report.backup is None
    assert report.metadata_bytes_before >= len(before.encode("utf-8"))
    assert report.metadata_bytes_after < report.metadata_bytes_before
    assert not (tmp_path / "backups").exists()
    # Nothing was written.
    assert _raw_metadata_row(db_path) == before


@pytest.mark.asyncio
async def test_apply_backs_up_then_strips_and_verifies(tmp_path: Path) -> None:
    db_path = await _seed(tmp_path)
    before = _raw_metadata_row(db_path)
    items_before = _raw_item_rows(db_path)
    revision_before, updated_before = _bookkeeping(db_path)

    report = await strip_snapshot_registry_images(db_path, apply=True, allow_non_dev=True)

    # A file-level backup exists, its manifest is honest, and the copy still
    # holds the pre-write row (proof it was taken before the migration).
    assert report.backup is not None
    backup_dir = Path(report.backup.directory)
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    copied_db = backup_dir / "core.db"
    assert copied_db.is_file()
    recorded = next(item for item in manifest["files"] if item["name"] == "core.db")
    assert recorded["sha256"] == hashlib.sha256(copied_db.read_bytes()).hexdigest()
    assert DATA_URL.encode("ascii") in copied_db.read_bytes()

    # The legacy registry image is gone; everything else in the row survives.
    after = _raw_metadata_row(db_path)
    after_state = json.loads(after)
    entry = after_state["core"]["artifacts"]["artifact-1"]
    assert "image_data_url" not in entry["metadata"]
    assert entry["metadata"]["path"] == "a.png"
    assert entry["metadata"]["size_bytes"] == 12
    assert entry["content"] == BODY
    assert len(after.encode("utf-8")) < len(before.encode("utf-8"))

    # Item rows and the row's bookkeeping columns are untouched.
    assert _raw_item_rows(db_path) == items_before
    assert _bookkeeping(db_path) == (revision_before, updated_before)

    # Verification is part of the report.
    assert report.ok is True
    assert report.sessions_changed == 1
    assert report.sessions_verified == report.sessions_total
    assert report.metadata_bytes_after == len(after.encode("utf-8"))
    assert report.item_rows_after == report.item_rows_before
    session = next(item for item in report.sessions if item.thread_id == THREAD_ID)
    assert session.readable is True and session.verified is True


@pytest.mark.asyncio
async def test_repeat_apply_is_a_noop_and_takes_no_second_backup(tmp_path: Path) -> None:
    db_path = await _seed(tmp_path)
    first = await strip_snapshot_registry_images(db_path, apply=True, allow_non_dev=True)
    assert first.sessions_changed == 1
    assert len(list((tmp_path / "backups").iterdir())) == 1

    second = await strip_snapshot_registry_images(db_path, apply=True, allow_non_dev=True)

    assert second.already_clean is True
    assert second.ok is True
    assert second.sessions_changed == 0
    assert second.images_removed == 0
    assert second.backup is None
    assert len(list((tmp_path / "backups").iterdir())) == 1


@pytest.mark.asyncio
async def test_already_clean_database_reports_noop_without_backup(tmp_path: Path) -> None:
    db_path = await _seed(tmp_path, fat=False)
    report = await strip_snapshot_registry_images(db_path, apply=True, allow_non_dev=True)
    assert report.already_clean is True
    assert report.sessions_changed == 0
    assert report.backup is None
    assert not (tmp_path / "backups").exists()


@pytest.mark.asyncio
async def test_verification_rejects_a_row_that_changed_beyond_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a persisted row diverges from the planned slim state, the pass must
    report a failure instead of claiming success."""
    db_path = await _seed(tmp_path)
    real_apply = maintenance._apply

    async def tampered_apply(db, entries):  # type: ignore[no-untyped-def]
        await real_apply(db, entries)
        # Simulate an unrelated write losing a field the plan kept.
        async with db.session_factory() as session:
            state = json.loads(_raw_metadata_row(db_path))
            state["core"]["artifacts"]["artifact-1"]["metadata"].pop("size_bytes")
            await session.execute(
                text("UPDATE core_thread_snapshots SET snapshot_json = :raw WHERE thread_id = :tid"),
                {"raw": json.dumps(state), "tid": THREAD_ID},
            )
            await session.commit()

    monkeypatch.setattr(maintenance, "_apply", tampered_apply)
    report = await strip_snapshot_registry_images(db_path, apply=True, allow_non_dev=True)

    assert report.ok is False
    assert report.error
    session = next(item for item in report.sessions if item.thread_id == THREAD_ID)
    assert session.verified is False


@pytest.mark.asyncio
async def test_backup_manifest_records_hashes(tmp_path: Path) -> None:
    db_path = await _seed(tmp_path)
    record = backup_database_files(db_path, timestamp="20260101T000000Z")
    manifest = json.loads((Path(record.directory) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_db"] == str(db_path)
    names = {entry["name"] for entry in manifest["files"]}
    assert "core.db" in names
    by_name = {entry["name"]: entry for entry in manifest["files"]}
    assert by_name["core.db"]["bytes"] > 0
    for entry in manifest["files"]:
        # SQLite sidecars (-shm in particular) may legitimately be empty.
        assert entry["bytes"] >= 0
        assert len(entry["sha256"]) == 64


@pytest.mark.asyncio
async def test_cli_refuses_a_non_dev_database(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    from lamtools_core.cli import cmd_maintenance_strip_snapshot_images

    class Args:
        core_db = str(tmp_path / "user" / "core.db")
        apply = True

    exit_code = await cmd_maintenance_strip_snapshot_images(Args())
    payload = json.loads(capsys.readouterr().out.strip())

    assert exit_code == 2
    assert payload["status"] == "refused"
    assert "development data directory" in payload["error"]
    assert not Path(Args.core_db).exists()


@pytest.mark.asyncio
async def test_payload_metadata_images_are_stripped_from_all_three_tables(tmp_path: Path) -> None:
    db_path = await _seed_full(tmp_path)

    report = await strip_snapshot_registry_images(db_path, apply=True, allow_non_dev=True)

    assert report.ok is True
    # One registry copy + one item payload copy + one event payload copy + one
    # sync-entity payload copy.
    assert report.images_removed == 4
    assert report.payload_images_removed == 3
    assert report.item_bytes_saved > 0
    assert report.event_bytes_saved > 0
    assert report.sync_bytes_saved > 0
    assert report.bytes_saved >= len(DATA_URL.encode("ascii")) * 4

    # Item payload metadata copy is gone; the render copy on artifacts survives.
    item = _raw_json(
        db_path,
        "SELECT item_json FROM core_thread_snapshot_items WHERE item_id = ?",
        (f"{THREAD_ID}:item-1",),
    )
    assert "image_data_url" not in item["payload"]["metadata"]
    assert item["payload"]["metadata"]["path"] == "a.png"
    assert item["artifacts"][0]["metadata"]["image_data_url"] == DATA_URL

    # Event payload metadata copy is gone; the event's own artifacts survive.
    event = _raw_json(
        db_path,
        "SELECT payload_json FROM core_app_events WHERE event_id = ?",
        (EVENT_ID,),
    )
    assert "image_data_url" not in event["payload"]["metadata"]
    assert event["artifacts"][0]["metadata"]["image_data_url"] == DATA_URL

    # Sync entity's nested event copy is slimmed the same way.
    sync = _raw_json(
        db_path,
        "SELECT entity_json FROM core_sync_changes WHERE change_id = ?",
        (SYNC_CHANGE_ID,),
    )
    inner = sync["event"]["payload"]
    assert "image_data_url" not in inner["payload"]["metadata"]
    assert inner["artifacts"][0]["metadata"]["image_data_url"] == DATA_URL

    # Every session verified, including the load-result comparison.
    assert report.sessions_verified == report.sessions_total
    session = next(item for item in report.sessions if item.thread_id == THREAD_ID)
    assert session.verified is True and session.readable is True


@pytest.mark.asyncio
async def test_payload_strip_is_idempotent_and_takes_no_second_backup(tmp_path: Path) -> None:
    db_path = await _seed_full(tmp_path)
    first = await strip_snapshot_registry_images(db_path, apply=True, allow_non_dev=True)
    assert first.sessions_changed == 1

    second = await strip_snapshot_registry_images(db_path, apply=True, allow_non_dev=True)

    assert second.already_clean is True
    assert second.ok is True
    assert second.payload_images_removed == 0
    assert second.bytes_saved == 0
    assert second.backup is None
    assert len(list((tmp_path / "backups").iterdir())) == 1


@pytest.mark.asyncio
async def test_load_result_is_identical_across_the_payload_strip(
    tmp_path: Path,
) -> None:
    """The real reader's assembled state must not change: the stripped keys were
    already dropped on load, so pre/post load digests are byte-identical."""
    db_path = await _seed_full(tmp_path)

    before_db = await open_core_app_db(db_path)
    try:
        async with before_db.session_factory() as session:
            before_state = await before_db.snapshot_store.load(session, THREAD_ID)
    finally:
        await before_db.close()

    report = await strip_snapshot_registry_images(db_path, apply=True, allow_non_dev=True)
    assert report.ok is True

    after_db = await open_core_app_db(db_path)
    try:
        async with after_db.session_factory() as session:
            after_state = await after_db.snapshot_store.load(session, THREAD_ID)
    finally:
        await after_db.close()

    assert json.dumps(before_state, sort_keys=True, default=str) == json.dumps(
        after_state, sort_keys=True, default=str
    )


@pytest.mark.asyncio
async def test_verification_rejects_a_changed_event_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent change to an event row must abort rather than silently
    rewrite a stale copy."""
    db_path = await _seed_full(tmp_path)
    real_apply = maintenance._apply

    async def tampered_apply(db, entries):  # type: ignore[no-untyped-def]
        await real_apply(db, entries)
        async with db.session_factory() as session:
            event = _raw_json(
                db_path,
                "SELECT payload_json FROM core_app_events WHERE event_id = ?",
                (EVENT_ID,),
            )
            event["payload"]["metadata"]["path"] = "mutated.png"
            await session.execute(
                text("UPDATE core_app_events SET payload_json = :raw WHERE event_id = :e"),
                {"raw": json.dumps(event), "e": EVENT_ID},
            )
            await session.commit()

    monkeypatch.setattr(maintenance, "_apply", tampered_apply)
    report = await strip_snapshot_registry_images(db_path, apply=True, allow_non_dev=True)

    assert report.ok is False
    assert report.error
    session = next(item for item in report.sessions if item.thread_id == THREAD_ID)
    assert session.verified is False



def test_backup_snapshots_a_live_write_connection_without_exclusive_access(
    tmp_path: Path,
) -> None:
    """The backup must work while another connection holds the DB open for writing.

    This is the running-app case: the app keeps the database open for writing, so
    its ``-wal``/``-shm`` sidecars stay locked. The previous filesystem copy
    could not read the ``-shm`` (Windows) and, when it "succeeded", mixed a
    ``core.db`` and a ``-wal`` captured at different instants into a torn file.
    The engine-level snapshot must need no exclusive access, be complete, and be
    a valid, independently queryable database.
    """
    db_path = tmp_path / "core.db"
    holder = sqlite3.connect(str(db_path))
    try:
        holder.execute("PRAGMA journal_mode=WAL")
        holder.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
        holder.execute("INSERT INTO items(name) VALUES ('kept')")
        holder.commit()
        # A write-capable connection stays open across the backup, so the source
        # lock state is exactly the one that broke the file copy.
        assert Path(str(db_path) + "-wal").exists()
        assert Path(str(db_path) + "-shm").exists()

        record = backup_database_files(
            db_path, backup_root=tmp_path / "backups", timestamp="20260101T000000Z"
        )
    finally:
        holder.close()

    backup_dir = Path(record.directory)
    # One self-contained database file; no sidecars were copied.
    assert {path.name for path in backup_dir.iterdir()} == {"core.db", "manifest.json"}
    snapshot = backup_dir / "core.db"
    assert snapshot.is_file() and snapshot.stat().st_size > 0

    check = sqlite3.connect(str(snapshot))
    try:
        assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert check.execute("SELECT name FROM items").fetchall() == [("kept",)]
    finally:
        check.close()


def test_backup_failure_aborts_and_removes_the_partial_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused backup must abort and leave nothing behind.

    The backup is taken before any write, so if it cannot be produced the whole
    operation must stop; and it must not leave the partial, unrestorable
    directory the old file copy left when it failed midway.
    """

    def boom(_db_path: Path, _snapshot: Path) -> None:
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr(maintenance, "_snapshot_database", boom)

    with pytest.raises(RuntimeError, match="snapshot failed"):
        backup_database_files(
            tmp_path / "core.db",
            backup_root=tmp_path / "backups",
            timestamp="20260101T000000Z",
        )

    assert list((tmp_path / "backups").iterdir()) == []
