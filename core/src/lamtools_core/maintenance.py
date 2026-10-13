"""One-shot maintenance commands for the local Core development database.

Read-invisible inline image copies are stripped in one pass, across every
storage location that historically wrote them:

* ``core_thread_snapshots.snapshot_json`` artifact-registry copies
  (``snapshot_store.slim_registry_inline_images``), and
* the ``payload.metadata.image_data_url`` copy on
  ``core_thread_snapshot_items.item_json``, ``core_app_events.payload_json``
  and ``core_sync_changes.entity_json``.

All four are copies no reader ever observes: the loader strips them from every
assembled state (``snapshot_store._strip_inline_image_copies``), new writes
already stop producing them (``runtime_projection._metadata_without_inline_image``),
and the UI renders images from the artifact body
(``artifact.metadata.image_data_url``), never from the payload metadata. The
render copy on ``item.artifacts`` and the inline bytes inside model history are
deliberately kept.

This module runs the same strip over every session in one pass, with a
file-level backup first and a per-session readability/integrity check
afterwards. Verification compares the real snapshot reader's assembled output
before and after the pass; because the loader already dropped these keys, the
loaded state must be byte-identical.

Scope is enforced here, not left to the caller: only the repository's local
development data directory (``<repo>/data``) may be targeted. A green/portable
or per-user installed database is refused even when its path is passed
explicitly. Tests opt out with ``allow_non_dev=True``; the CLI never does.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from .app.core_db import open_core_app_db
from .app.snapshot_store import slim_registry_inline_images

__all__ = [
    "BackupFile",
    "BackupRecord",
    "ConcurrentModificationError",
    "MaintenanceScopeError",
    "SessionStripResult",
    "StripReport",
    "backup_database_files",
    "dev_data_dir",
    "dev_db_path",
    "is_dev_data_dir",
    "strip_snapshot_registry_images",
]


class MaintenanceScopeError(RuntimeError):
    """A maintenance operation was pointed outside the local dev data directory."""


class ConcurrentModificationError(RuntimeError):
    """A session metadata row changed between planning and applying the strip."""


def repo_root() -> Path:
    # maintenance.py → lamtools_core → src → core → repository root.
    return Path(__file__).resolve().parents[3]


def dev_data_dir() -> Path:
    """The repository's local development data directory (``<repo>/data``)."""
    return repo_root() / "data"


def dev_db_path() -> Path:
    return dev_data_dir() / "core.db"


def is_dev_data_dir(path: Path | str) -> bool:
    """True when ``path`` is the repository's local development data directory."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    return resolved == dev_data_dir().resolve()


# --------------------------------------------------------------------------- #
# Backup
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BackupFile:
    name: str
    bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "bytes": self.bytes, "sha256": self.sha256}


@dataclass(frozen=True)
class BackupRecord:
    directory: str
    files: tuple[BackupFile, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "directory": self.directory,
            "files": [item.to_dict() for item in self.files],
        }


# The backup is an engine-level snapshot, not a filesystem copy. SQLite keeps a
# live database in several sibling files (``-wal``/``-shm``) locked by whoever
# has it open, so a plain file copy of a running database is both impossible
# (the ``-shm`` mapping cannot be read from another process on Windows) and,
# when it "succeeds", a torn snapshot of a database whose sidecar was captured
# at a different instant. ``VACUUM INTO`` reads through the engine and writes a
# fresh, self-contained database file instead — complete, restorable, consistent,
# and requiring no exclusive access.


def _sha256_file(path: Path, *, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_database(db_path: Path, snapshot: Path) -> None:
    """Write a complete, consistent snapshot of ``db_path`` to ``snapshot``.

    ``VACUUM INTO`` takes an ordinary read snapshot of the source and writes a
    fresh database file; it never reads or writes the source's ``-wal``/``-shm``
    sidecars directly and never takes the source's write lock, so the source may
    be open for writing by another process (the running app) at the same time.
    The source itself is never modified.
    """
    if snapshot.exists():
        snapshot.unlink()
    connection = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        connection.execute("VACUUM INTO ?", (str(snapshot),))
    finally:
        connection.close()


def backup_database_files(
    db_path: Path | str,
    *,
    backup_root: Path | str | None = None,
    timestamp: str | None = None,
    label: str = "strip-snapshot-images",
    purpose: str = "file-level backup taken before the migration",
) -> BackupRecord:
    """Take a complete, restorable snapshot of the database into a new dir.

    The snapshot is written before any row is modified, so a failed or refused
    migration always leaves a restorable copy next to the data. It is produced
    by the database engine (``VACUUM INTO``), not by copying files, so it needs
    no exclusive access and can be taken while the running app holds the database
    open for writing — the normal case, which the previous file-copy approach
    could not handle and which produced a torn copy on a live database.

    Each run gets its own timestamped directory, so repeated runs never overwrite
    an earlier backup. If the snapshot cannot be taken the run aborts and the
    partially written directory is removed, so a refused backup never leaves an
    unrestorable artifact behind. ``label`` names the run (its own subdirectory)
    and ``purpose`` is recorded in the manifest, so several maintenance passes
    share this helper without sharing a directory.
    """
    db_path = Path(db_path)
    root = Path(backup_root) if backup_root is not None else db_path.parent / "backups"
    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = root / f"{label}-{stamp}"
    suffix = 1
    while target.exists():
        suffix += 1
        target = root / f"{label}-{stamp}-{suffix}"
    target.mkdir(parents=True)

    try:
        snapshot = target / db_path.name
        _snapshot_database(db_path, snapshot)
        files = (
            BackupFile(
                name=db_path.name,
                bytes=snapshot.stat().st_size,
                sha256=_sha256_file(snapshot),
            ),
        )
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_db": str(db_path),
            "purpose": purpose,
            "method": "vacuum-into",
            "files": [item.to_dict() for item in files],
        }
        (target / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return BackupRecord(directory=str(target), files=files)
    except BaseException:
        # Never leave a partial, unrestorable directory behind: a refused backup
        # must consume no space and must not confuse a later restore.
        shutil.rmtree(target, ignore_errors=True)
        raise


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


@dataclass
class SessionStripResult:
    thread_id: str
    changed: bool
    images_removed: int
    metadata_bytes_before: int
    metadata_bytes_after: int
    item_rows: int
    readable: bool
    verified: bool
    payload_images_removed: int = 0
    item_bytes_before: int = 0
    item_bytes_after: int = 0
    event_bytes_before: int = 0
    event_bytes_after: int = 0
    sync_bytes_before: int = 0
    sync_bytes_after: int = 0
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "changed": self.changed,
            "images_removed": self.images_removed,
            "payload_images_removed": self.payload_images_removed,
            "metadata_bytes_before": self.metadata_bytes_before,
            "metadata_bytes_after": self.metadata_bytes_after,
            "item_bytes_before": self.item_bytes_before,
            "item_bytes_after": self.item_bytes_after,
            "event_bytes_before": self.event_bytes_before,
            "event_bytes_after": self.event_bytes_after,
            "sync_bytes_before": self.sync_bytes_before,
            "sync_bytes_after": self.sync_bytes_after,
            "item_rows": self.item_rows,
            "readable": self.readable,
            "verified": self.verified,
            "detail": self.detail,
        }


@dataclass
class StripReport:
    db_path: str
    data_dir: str
    applied: bool
    already_clean: bool
    backup: BackupRecord | None = None
    sessions_total: int = 0
    sessions_changed: int = 0
    sessions_verified: int = 0
    images_removed: int = 0
    payload_images_removed: int = 0
    metadata_bytes_before: int = 0
    metadata_bytes_after: int = 0
    item_bytes_before: int = 0
    item_bytes_after: int = 0
    event_bytes_before: int = 0
    event_bytes_after: int = 0
    sync_bytes_before: int = 0
    sync_bytes_after: int = 0
    item_rows_before: int = 0
    item_rows_after: int = 0
    db_file_bytes_before: int = 0
    db_file_bytes_after: int = 0
    sessions: list[SessionStripResult] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        if self.error:
            return False
        if not self.applied or self.already_clean:
            return True
        return all(
            item.readable and item.verified for item in self.sessions if item.changed
        )

    @property
    def bytes_saved(self) -> int:
        return max(
            0,
            (self.metadata_bytes_before + self.item_bytes_before
             + self.event_bytes_before + self.sync_bytes_before)
            - (self.metadata_bytes_after + self.item_bytes_after
               + self.event_bytes_after + self.sync_bytes_after),
        )

    @property
    def metadata_bytes_saved(self) -> int:
        return self.metadata_bytes_before - self.metadata_bytes_after

    @property
    def item_bytes_saved(self) -> int:
        return self.item_bytes_before - self.item_bytes_after

    @property
    def event_bytes_saved(self) -> int:
        return self.event_bytes_before - self.event_bytes_after

    @property
    def sync_bytes_saved(self) -> int:
        return self.sync_bytes_before - self.sync_bytes_after

    def to_dict(self) -> dict[str, Any]:
        return {
            "db_path": self.db_path,
            "data_dir": self.data_dir,
            "applied": self.applied,
            "already_clean": self.already_clean,
            "backup": self.backup.to_dict() if self.backup else None,
            "sessions_total": self.sessions_total,
            "sessions_changed": self.sessions_changed,
            "sessions_verified": self.sessions_verified,
            "images_removed": self.images_removed,
            "payload_images_removed": self.payload_images_removed,
            "metadata_bytes_before": self.metadata_bytes_before,
            "metadata_bytes_after": self.metadata_bytes_after,
            "metadata_bytes_saved": self.metadata_bytes_before - self.metadata_bytes_after,
            "item_bytes_before": self.item_bytes_before,
            "item_bytes_after": self.item_bytes_after,
            "item_bytes_saved": self.item_bytes_before - self.item_bytes_after,
            "event_bytes_before": self.event_bytes_before,
            "event_bytes_after": self.event_bytes_after,
            "event_bytes_saved": self.event_bytes_before - self.event_bytes_after,
            "sync_bytes_before": self.sync_bytes_before,
            "sync_bytes_after": self.sync_bytes_after,
            "sync_bytes_saved": self.sync_bytes_before - self.sync_bytes_after,
            "bytes_saved": self.bytes_saved,
            "item_rows_before": self.item_rows_before,
            "item_rows_after": self.item_rows_after,
            "db_file_bytes_before": self.db_file_bytes_before,
            "db_file_bytes_after": self.db_file_bytes_after,
            "ok": self.ok,
            "error": self.error,
            "sessions": [item.to_dict() for item in self.sessions],
        }


# --------------------------------------------------------------------------- #
# Plan / apply / verify
# --------------------------------------------------------------------------- #

_INLINE_IMAGE_METADATA_KEY = "image_data_url"


def _raw_json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _text_bytes(value: str) -> int:
    return len(value.encode("utf-8"))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _count_registry_inline_images(state: Any) -> int:
    """How many ``image_data_url`` keys the registry copies of ``state`` hold."""
    if not isinstance(state, dict):
        return 0
    total = 0
    registries: list[Any] = [state.get("artifacts")]
    core = state.get("core")
    if isinstance(core, dict):
        registries.append(core.get("artifacts"))
    for registry in registries:
        if not isinstance(registry, dict):
            continue
        for artifact in registry.values():
            metadata = artifact.get("metadata") if isinstance(artifact, dict) else None
            if isinstance(metadata, dict) and _INLINE_IMAGE_METADATA_KEY in metadata:
                total += 1
    return total


def _strip_metadata_inline_image(metadata: Any) -> Any:
    """Return ``metadata`` without ``image_data_url``, else the same object."""
    if isinstance(metadata, dict) and _INLINE_IMAGE_METADATA_KEY in metadata:
        return {
            key: value
            for key, value in metadata.items()
            if key != _INLINE_IMAGE_METADATA_KEY
        }
    return metadata


def _slim_item_payload_image(item: Any) -> tuple[Any, int]:
    """Drop ``item_json['payload']['metadata']['image_data_url']``.

    Returns ``(slimmed_item, removed)``; the original object is returned when
    nothing is removed so untouched rows stay byte-identical.
    """
    if not isinstance(item, dict):
        return item, 0
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return item, 0
    stripped = _strip_metadata_inline_image(payload.get("metadata"))
    if stripped is payload.get("metadata"):
        return item, 0
    slim_payload = dict(payload)
    slim_payload["metadata"] = stripped
    slim = dict(item)
    slim["payload"] = slim_payload
    return slim, 1


def _slim_run_item_payload_image(run_item: Any) -> tuple[Any, int]:
    """Drop ``run_item['payload']['metadata']['image_data_url']``."""
    return _slim_item_payload_image(run_item)


def _slim_event_payload_json(payload_json: Any) -> tuple[Any, int]:
    """``core_app_events.payload_json`` is a RunItemEvent dict."""
    return _slim_run_item_payload_image(payload_json)


def _slim_sync_entity_json(entity: Any) -> tuple[Any, int]:
    """``entity_json = {'event': envelope}``; ``envelope['payload']`` is a
    RunItemEvent dict, so the payload-metadata copy lives two levels down."""
    if not isinstance(entity, dict):
        return entity, 0
    envelope = entity.get("event")
    if not isinstance(envelope, dict):
        return entity, 0
    slim_run, removed = _slim_run_item_payload_image(envelope.get("payload"))
    if not removed:
        return entity, 0
    slim_envelope = dict(envelope)
    slim_envelope["payload"] = slim_run
    slim = dict(entity)
    slim["event"] = slim_envelope
    return slim, 1


@dataclass
class _RowSlim:
    """One planned row rewrite (item / event / sync change)."""

    table: str  # "items" | "events" | "sync"
    key: tuple[Any, ...]
    before_digest: str
    before_bytes: int
    after_bytes: int
    images_removed: int
    slim: Any

    @property
    def saved_bytes(self) -> int:
        return self.before_bytes - self.after_bytes


@dataclass
class _PlanEntry:
    thread_id: str
    digest: str
    before_bytes: int
    images_removed: int
    item_ids: frozenset[str]
    item_rows: int
    item_bytes: int
    event_bytes: int = 0
    sync_bytes: int = 0
    slimmed: dict[str, Any] | None = None
    item_slims: list[_RowSlim] = field(default_factory=list)
    event_slims: list[_RowSlim] = field(default_factory=list)
    sync_slims: list[_RowSlim] = field(default_factory=list)
    load_digest_before: str = ""

    @property
    def changed(self) -> bool:
        return bool(
            self.slimmed is not None
            or self.item_slims
            or self.event_slims
            or self.sync_slims
        )

    @property
    def row_slims(self) -> tuple[_RowSlim, ...]:
        return (*self.item_slims, *self.event_slims, *self.sync_slims)

    @property
    def payload_images_removed(self) -> int:
        return sum(row.images_removed for row in self.row_slims)


def _empty_bucket() -> dict[str, Any]:
    return {
        "snapshot": None,
        "item_ids": [],
        "item_rows": 0,
        "item_bytes": 0,
        "item_slims": [],
        "event_bytes": 0,
        "event_slims": [],
        "sync_bytes": 0,
        "sync_slims": [],
    }


def _row_slim(table: str, key: tuple[Any, ...], raw_text: str, slim: Any) -> _RowSlim:
    slim_text = json.dumps(slim)
    return _RowSlim(
        table=table,
        key=key,
        before_digest=_digest(raw_text),
        before_bytes=_text_bytes(raw_text),
        after_bytes=_text_bytes(slim_text),
        images_removed=1,
        slim=slim,
    )


async def _plan(db: Any) -> list[_PlanEntry]:
    """Read every storage row and compute its read-invisible slim replacement.

    Rows are streamed one at a time: the sync journal alone holds hundreds of
    megabytes of JSON, and materializing every row before stripping would need
    a multiple of that in transient Python objects.
    """
    buckets: dict[str, dict[str, Any]] = {}

    def bucket(thread_id: str) -> dict[str, Any]:
        return buckets.setdefault(thread_id, _empty_bucket())

    async with db.session_factory() as session:
        stream = await session.stream(
            text("SELECT thread_id, snapshot_json FROM core_thread_snapshots")
        )
        async for row in stream:
            thread_id = str(row[0])
            raw_text = _raw_json_text(row[1])
            try:
                state = json.loads(raw_text)
            except (TypeError, ValueError) as exc:  # pragma: no cover — corrupt DB
                raise RuntimeError(
                    f"session metadata row '{thread_id}' is not valid JSON: {exc}"
                ) from exc
            if not isinstance(state, dict):
                raise RuntimeError(
                    f"session metadata row '{thread_id}' is not a JSON object"
                )
            images = _count_registry_inline_images(state)
            bucket(thread_id)["snapshot"] = {
                "digest": _digest(raw_text),
                "before_bytes": _text_bytes(raw_text),
                "images": images,
                "slimmed": slim_registry_inline_images(state) if images else None,
            }
        await stream.close()

    async with db.session_factory() as session:
        stream = await session.stream(
            text(
                "SELECT thread_id, item_id, item_json FROM core_thread_snapshot_items"
            )
        )
        async for row in stream:
            thread_id = str(row[0])
            item_id = str(row[1])
            raw_text = _raw_json_text(row[2])
            entry = bucket(thread_id)
            entry["item_ids"].append(item_id)
            entry["item_rows"] += 1
            entry["item_bytes"] += _text_bytes(raw_text)
            if _INLINE_IMAGE_METADATA_KEY not in raw_text:
                continue
            slim, removed = _slim_item_payload_image(json.loads(raw_text))
            if removed:
                entry["item_slims"].append(
                    _row_slim("items", (thread_id, item_id), raw_text, slim)
                )
        await stream.close()

    async with db.session_factory() as session:
        stream = await session.stream(
            text("SELECT event_id, thread_id, payload_json FROM core_app_events")
        )
        async for row in stream:
            event_id = str(row[0])
            thread_id = str(row[1])
            raw_text = _raw_json_text(row[2])
            entry = bucket(thread_id)
            entry["event_bytes"] += _text_bytes(raw_text)
            if _INLINE_IMAGE_METADATA_KEY not in raw_text:
                continue
            slim, removed = _slim_event_payload_json(json.loads(raw_text))
            if removed:
                entry["event_slims"].append(
                    _row_slim("events", (event_id,), raw_text, slim)
                )
        await stream.close()

    async with db.session_factory() as session:
        stream = await session.stream(
            text("SELECT seq, thread_id, entity_json FROM core_sync_changes")
        )
        async for row in stream:
            seq = int(row[0])
            thread_id = str(row[1] or "")
            raw_text = _raw_json_text(row[2])
            entry = bucket(thread_id)
            entry["sync_bytes"] += _text_bytes(raw_text)
            if _INLINE_IMAGE_METADATA_KEY not in raw_text:
                continue
            slim, removed = _slim_sync_entity_json(json.loads(raw_text))
            if removed:
                entry["sync_slims"].append(
                    _row_slim("sync", (seq,), raw_text, slim)
                )
        await stream.close()

    entries: list[_PlanEntry] = []
    for thread_id, data in buckets.items():
        snapshot = data["snapshot"]
        entries.append(
            _PlanEntry(
                thread_id=thread_id,
                digest=str(snapshot["digest"]) if snapshot else "",
                before_bytes=int(snapshot["before_bytes"]) if snapshot else 0,
                images_removed=int(snapshot["images"]) if snapshot else 0,
                item_ids=frozenset(data["item_ids"]),
                item_rows=int(data["item_rows"]),
                item_bytes=int(data["item_bytes"]),
                event_bytes=int(data["event_bytes"]),
                sync_bytes=int(data["sync_bytes"]),
                slimmed=snapshot["slimmed"] if snapshot else None,
                item_slims=list(data["item_slims"]),
                event_slims=list(data["event_slims"]),
                sync_slims=list(data["sync_slims"]),
            )
        )

    # Capture the real reader's assembled output for every session that the
    # pass will touch, so verification can prove the load result is unchanged.
    async with db.session_factory() as session:
        for entry in entries:
            if not entry.changed or not entry.digest:
                continue
            state = await db.snapshot_store.load(session, entry.thread_id)
            entry.load_digest_before = _digest(
                json.dumps(state, sort_keys=True, default=str)
            )
    return entries


async def _select_row_json(session: Any, row: _RowSlim) -> Any:
    if row.table == "items":
        return (
            await session.execute(
                text(
                    "SELECT item_json FROM core_thread_snapshot_items "
                    "WHERE thread_id = :thread_id AND item_id = :item_id"
                ),
                {"thread_id": row.key[0], "item_id": row.key[1]},
            )
        ).scalar()
    if row.table == "events":
        return (
            await session.execute(
                text("SELECT payload_json FROM core_app_events WHERE event_id = :event_id"),
                {"event_id": row.key[0]},
            )
        ).scalar()
    if row.table == "sync":
        return (
            await session.execute(
                text("SELECT entity_json FROM core_sync_changes WHERE seq = :seq"),
                {"seq": row.key[0]},
            )
        ).scalar()
    return None


async def _apply(db: Any, entries: list[_PlanEntry]) -> None:
    """Rewrite the planned rows in one write transaction.

    Compare-and-swap guards against a concurrent app write between planning and
    applying: a changed digest aborts the whole transaction, so no row is ever
    rolled back to a stale copy. Only the stripped key is removed — every other
    column and JSON field stays byte-identical.
    """
    changed = [entry for entry in entries if entry.changed]

    async def action(session: Any) -> None:
        # Fail fast before any write if anything changed under us.
        for entry in changed:
            rows = entry.row_slims
            if entry.slimmed is not None:
                current = (
                    await session.execute(
                        text(
                            "SELECT snapshot_json FROM core_thread_snapshots "
                            "WHERE thread_id = :thread_id"
                        ),
                        {"thread_id": entry.thread_id},
                    )
                ).scalar()
                if current is None:
                    raise ConcurrentModificationError(
                        f"session metadata row '{entry.thread_id}' disappeared before the strip"
                    )
                if _digest(_raw_json_text(current)) != entry.digest:
                    raise ConcurrentModificationError(
                        f"session metadata row '{entry.thread_id}' changed during the strip; "
                        "stop the app and rerun"
                    )
            for row in rows:
                current = await _select_row_json(session, row)
                if current is None:
                    raise ConcurrentModificationError(
                        f"{row.table} row {row.key!r} disappeared before the strip"
                    )
                if _digest(_raw_json_text(current)) != row.before_digest:
                    raise ConcurrentModificationError(
                        f"{row.table} row {row.key!r} changed during the strip; "
                        "stop the app and rerun"
                    )

        for entry in changed:
            if entry.slimmed is not None:
                await session.execute(
                    text(
                        "UPDATE core_thread_snapshots SET snapshot_json = :raw "
                        "WHERE thread_id = :thread_id"
                    ),
                    {
                        # Mirrors the SQLAlchemy JSON serializer the app writes
                        # with (json.dumps defaults), so the rewritten row is in
                        # the same canonical form as any other snapshot write.
                        "raw": json.dumps(entry.slimmed),
                        "thread_id": entry.thread_id,
                    },
                )
            for row in entry.item_slims:
                await session.execute(
                    text(
                        "UPDATE core_thread_snapshot_items SET item_json = :raw "
                        "WHERE thread_id = :thread_id AND item_id = :item_id"
                    ),
                    {
                        "raw": json.dumps(row.slim),
                        "thread_id": row.key[0],
                        "item_id": row.key[1],
                    },
                )
            for row in entry.event_slims:
                await session.execute(
                    text(
                        "UPDATE core_app_events SET payload_json = :raw "
                        "WHERE event_id = :event_id"
                    ),
                    {"raw": json.dumps(row.slim), "event_id": row.key[0]},
                )
            for row in entry.sync_slims:
                await session.execute(
                    text(
                        "UPDATE core_sync_changes SET entity_json = :raw "
                        "WHERE seq = :seq"
                    ),
                    {"raw": json.dumps(row.slim), "seq": row.key[0]},
                )

    await db.persistence.write(action)


async def _verify(db: Any, report: StripReport, entries: list[_PlanEntry]) -> None:
    """Per-session readability and integrity check after the strip.

    For a changed session: every rewritten row must equal exactly the planned
    slim state (nothing but the dead image key removed), the untouched rows must
    still be present, and the real snapshot reader must assemble a byte-identical
    state (its load result is compared against the pre-strip digest, because the
    loader already dropped these keys).
    """
    by_id = {entry.thread_id: entry for entry in entries}
    async with db.session_factory() as session:
        for result in report.sessions:
            entry = by_id[result.thread_id]
            if not entry.changed:
                result.verified = True
                continue
            # Snapshot registry copy.
            if entry.slimmed is not None:
                current = (
                    await session.execute(
                        text(
                            "SELECT snapshot_json FROM core_thread_snapshots "
                            "WHERE thread_id = :thread_id"
                        ),
                        {"thread_id": result.thread_id},
                    )
                ).scalar()
                if current is None:
                    result.verified = False
                    result.readable = False
                    result.detail = "session metadata row disappeared during the strip"
                    continue
                after_text = _raw_json_text(current)
                result.metadata_bytes_after = _text_bytes(after_text)
                if json.loads(after_text) != entry.slimmed:
                    result.verified = False
                    result.detail = "persisted row differs from the planned slimmed state"
                    continue
            # Rewritten item / event / sync rows.
            row_failure = ""
            for row in entry.row_slims:
                current = await _select_row_json(session, row)
                if current is None:
                    row_failure = f"{row.table} row {row.key!r} disappeared during the strip"
                    break
                if json.loads(_raw_json_text(current)) != row.slim:
                    row_failure = f"{row.table} row {row.key!r} differs from the planned slim state"
                    break
            if row_failure:
                result.verified = False
                result.detail = row_failure
                continue
            # Item table membership and byte accounting must match the plan.
            item_rows = (
                await session.execute(
                    text(
                        "SELECT item_id, length(CAST(item_json AS BLOB)) "
                        "FROM core_thread_snapshot_items WHERE thread_id = :thread_id"
                    ),
                    {"thread_id": result.thread_id},
                )
            ).all()
            if {str(row[0]) for row in item_rows} != set(entry.item_ids):
                result.verified = False
                result.detail = "item rows changed during the strip"
                continue
            result.verified = True

    report.sessions_verified = sum(1 for item in report.sessions if item.verified)

    # Readability through the real reader, on its own connection. The loaded
    # state is compared against the pre-strip digest: because the loader strips
    # the same dead keys, the assembled conversation must be unchanged.
    for result in report.sessions:
        entry = by_id[result.thread_id]
        if not entry.changed:
            result.readable = True
            continue
        if not entry.digest:
            result.readable = True
            continue
        try:
            async with db.session_factory() as session:
                state = await db.snapshot_store.load(session, result.thread_id)
            digest = _digest(json.dumps(state, sort_keys=True, default=str))
            if digest != entry.load_digest_before:
                result.readable = False
                result.detail = (
                    "loaded snapshot changed beyond the stripped dead keys"
                )
                continue
            assembled = (state.get("core") or {}).get("items") or {}
            if set(assembled) != set(entry.item_ids):
                result.readable = False
                result.detail = (
                    "snapshot assembly item set differs from the item table"
                )
                continue
            result.readable = True
        except Exception as exc:  # noqa: BLE001 — a broken session must be reported, not hidden
            result.readable = False
            result.detail = f"snapshot load failed: {exc}"

    for item in report.sessions:
        result = item
        if result.changed and not (result.readable and result.verified):
            report.error = report.error or f"session '{result.thread_id}' failed verification"


def _planned_after_bytes(before: int, rows: list[_RowSlim]) -> int:
    return before - sum(row.saved_bytes for row in rows)


async def strip_snapshot_registry_images(
    db_path: Path | str,
    *,
    apply: bool = False,
    backup_root: Path | str | None = None,
    allow_non_dev: bool = False,
) -> StripReport:
    """Strip read-invisible inline image copies from every storage location.

    ``apply=False`` (the default) is a dry run: nothing is backed up, written or
    verified beyond the plan. ``apply=True`` backs the database files up first,
    rewrites the affected rows in one transaction, then verifies each session.
    Repeated runs are idempotent: a second pass finds nothing to strip, takes no
    backup and reports ``already_clean``.
    """
    db_path = Path(db_path)
    if not allow_non_dev and not is_dev_data_dir(db_path.parent):
        raise MaintenanceScopeError(
            "maintenance runs only against the local development data directory "
            f"({dev_data_dir()}); refusing '{db_path.parent}'. Installed user data "
            "directories are never touched."
        )

    report = StripReport(
        db_path=str(db_path),
        data_dir=str(db_path.parent),
        applied=bool(apply),
        already_clean=False,
        db_file_bytes_before=db_path.stat().st_size if db_path.is_file() else 0,
    )
    db = await open_core_app_db(db_path)
    try:
        entries = await _plan(db)
        report.sessions_total = len(entries)
        report.item_rows_before = sum(entry.item_rows for entry in entries)
        report.item_rows_after = report.item_rows_before
        report.metadata_bytes_before = sum(entry.before_bytes for entry in entries)
        report.item_bytes_before = sum(entry.item_bytes for entry in entries)
        report.event_bytes_before = sum(entry.event_bytes for entry in entries)
        report.sync_bytes_before = sum(entry.sync_bytes for entry in entries)
        report.sessions = [
            SessionStripResult(
                thread_id=entry.thread_id,
                changed=entry.changed,
                images_removed=entry.images_removed + entry.payload_images_removed,
                metadata_bytes_before=entry.before_bytes,
                metadata_bytes_after=entry.before_bytes,
                item_rows=entry.item_rows,
                readable=True,
                verified=not entry.changed,
                payload_images_removed=entry.payload_images_removed,
                item_bytes_before=entry.item_bytes,
                item_bytes_after=entry.item_bytes,
                event_bytes_before=entry.event_bytes,
                event_bytes_after=entry.event_bytes,
                sync_bytes_before=entry.sync_bytes,
                sync_bytes_after=entry.sync_bytes,
            )
            for entry in entries
        ]
        changed = [entry for entry in entries if entry.changed]
        report.sessions_changed = len(changed)
        report.payload_images_removed = sum(
            entry.payload_images_removed for entry in entries
        )
        report.images_removed = sum(
            entry.images_removed + entry.payload_images_removed for entry in entries
        )

        def fill_planned_after() -> None:
            for entry, result in zip(entries, report.sessions):
                if entry.slimmed is not None:
                    result.metadata_bytes_after = _text_bytes(json.dumps(entry.slimmed))
                result.item_bytes_after = _planned_after_bytes(
                    entry.item_bytes, entry.item_slims
                )
                result.event_bytes_after = _planned_after_bytes(
                    result.event_bytes_before, entry.event_slims
                )
                result.sync_bytes_after = _planned_after_bytes(
                    result.sync_bytes_before, entry.sync_slims
                )
            report.metadata_bytes_after = sum(item.metadata_bytes_after for item in report.sessions)
            report.item_bytes_after = sum(item.item_bytes_after for item in report.sessions)
            report.event_bytes_after = sum(item.event_bytes_after for item in report.sessions)
            report.sync_bytes_after = sum(item.sync_bytes_after for item in report.sessions)

        if not changed:
            report.already_clean = True
            report.sessions_verified = len(entries)
            report.metadata_bytes_after = report.metadata_bytes_before
            report.item_bytes_after = report.item_bytes_before
            report.event_bytes_after = report.event_bytes_before
            report.sync_bytes_after = report.sync_bytes_before
            report.db_file_bytes_after = report.db_file_bytes_before
            return report

        if not apply:
            fill_planned_after()
            report.sessions_verified = sum(1 for item in report.sessions if item.verified)
            report.db_file_bytes_after = report.db_file_bytes_before
            return report

        report.backup = backup_database_files(db_path, backup_root=backup_root)
        await _apply(db, entries)
        fill_planned_after()
        await _verify(db, report, entries)
        # Verification re-reads the real rows; fold the confirmed per-session
        # sizes back into the report totals.
        report.metadata_bytes_after = sum(item.metadata_bytes_after for item in report.sessions)
        report.item_bytes_after = sum(item.item_bytes_after for item in report.sessions)
        report.event_bytes_after = sum(item.event_bytes_after for item in report.sessions)
        report.sync_bytes_after = sum(item.sync_bytes_after for item in report.sessions)
        # Fold the write back out of the WAL so the reported file size reflects
        # the migration instead of a temporarily inflated journal. Best effort:
        # a reader holding the WAL only postpones this.
        try:
            async with db.session_factory() as session:
                await session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        except Exception:  # noqa: BLE001 — informational only
            pass
        report.db_file_bytes_after = db_path.stat().st_size if db_path.is_file() else 0
        return report
    finally:
        await db.close()
