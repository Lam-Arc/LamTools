"""One-shot compaction of the Core sync journal.

user:“在这一次的更新中，自动把之前的数据库进行一遍去重和缩小”+(同步日志是追加式
的：每次运行时状态保存都会写一条完整的 ``runtime.upsert`` 快照，每个事件也会写一条
``thread.event``。长期使用后，同一会话的旧状态快照越积越多，单条快照又很大，数据库
会膨胀到几十 GB，连带把启动修补拖慢。)

The journal is append-only by design, but the runtime snapshots are *state*, not
history: a client that has not caught up only needs the newest row for an
entity. Compaction therefore keeps, per runtime entity, only the newest
``keep_per_entity`` rows, preserves every non-runtime change, rebuilds the
table in one sequential pass, and (optionally) VACUUMs the file.

It also creates the ``(thread_id, revision)`` covering index used by the
startup thread-revision repair, so that repair becomes an index lookup instead
of a per-thread table scan.

The operation is offline: the desktop must be closed. ``apply=False`` only
reports what would happen.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

#: 启动修补使用的覆盖索引；压缩时一次性建好，之后每次启动都只查索引。
THREAD_REVISION_INDEX = "idx_core_events_thread_revision"

#: 写入侧按 (entity_type, entity_id) 覆盖旧运行时快照所需的索引。
#: 新库由 create_all 建；旧库只能在这里补，否则写入侧会退回追加式增长。
SYNC_ENTITY_INDEX = "idx_core_sync_changes_entity"

#: 重建期间使用的临时表名，不能和正式表冲突。
_COMPACT_TABLE = "core_sync_changes__compact"
_KEEP_TABLE = "_core_sync_keep_runtime"


@dataclass
class SyncCompactionReport:
    db_path: str
    applied: bool = False
    vacuumed: bool = False
    index_created: bool = False
    entity_index_created: bool = False
    backup_path: str = ""
    before_bytes: int = 0
    after_bytes: int = 0
    max_seq_before: int = 0
    max_seq_after: int = 0
    total_changes_before: int = 0
    total_changes_after: int = 0
    runtime_changes_before: int = 0
    runtime_entities: int = 0
    runtime_changes_after: int = 0
    other_changes: int = 0
    deleted_changes: int = 0
    duration_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)
    error: str = ""
    ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["before_mb"] = round(self.before_bytes / 1048576, 1)
        payload["after_mb"] = round(self.after_bytes / 1048576, 1)
        payload["saved_mb"] = round((self.before_bytes - self.after_bytes) / 1048576, 1)
        return payload


class SyncCompactionError(RuntimeError):
    """Compaction refused or failed; nothing beyond the reported step was kept."""


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db_path), timeout=10, isolation_level=None)
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def _dbfile_bytes(connection: sqlite3.Connection) -> int:
    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0] or 0)
    page_count = int(connection.execute("PRAGMA page_count").fetchone()[0] or 0)
    return page_size * page_count


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _sync_table_ddl(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='core_sync_changes'"
    ).fetchone()
    if row is None or not row[0]:
        raise SyncCompactionError("core_sync_changes 不存在，无法压缩")
    return str(row[0])


def _explicit_index_sql(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='index' AND tbl_name='core_sync_changes' AND sql IS NOT NULL"
    ).fetchall()
    return [str(row[0]) for row in rows if row[0]]


def _backup_path(db_path: Path, backup_dir: Path | None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = backup_dir or (db_path.parent / "backups")
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{db_path.name}.pre-compact-{stamp}"


def _backup_database(db_path: Path, backup_dir: Path | None) -> Path:
    target = _backup_path(db_path, backup_dir)
    _log.info("[compact] backing up %s -> %s", db_path, target)
    shutil.copy2(db_path, target)
    for suffix in ("-wal", "-shm"):
        sidecar = db_path.with_name(db_path.name + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, target.with_name(target.name + suffix))
    return target


def _checkpoint(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    except sqlite3.DatabaseError as error:  # another reader/writer is present
        raise SyncCompactionError(
            f"数据库仍被占用，无法压缩：{error}。请先完全退出 Sunday。"
        ) from error


def _replace_table_name(ddl: str, name: str) -> str:
    pattern = re.compile(
        r"^(\s*CREATE\s+TABLE\s+)(?:\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*)",
        re.IGNORECASE,
    )
    replaced, count = pattern.subn(rf'\1"{name}"', ddl, count=1)
    if count != 1:
        raise SyncCompactionError("无法从建表语句中定位表名")
    return replaced


def _journal_stats(connection: sqlite3.Connection) -> dict[str, int]:
    """One scan that yields the row counts and the cursor high-water mark."""
    row = connection.execute(
        "SELECT COUNT(*), "
        "COALESCE(SUM(CASE WHEN entity_type='runtime' THEN 1 ELSE 0 END), 0), "
        "COUNT(DISTINCT CASE WHEN entity_type='runtime' THEN entity_id END), "
        "COALESCE(MAX(seq), 0) "
        "FROM core_sync_changes"
    ).fetchone()
    return {
        "total": int(row[0] or 0),
        "runtime": int(row[1] or 0),
        "entities": int(row[2] or 0),
        "max_seq": int(row[3] or 0),
    }


def _ensure_revision_index(connection: sqlite3.Connection) -> bool:
    existing = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (THREAD_REVISION_INDEX,)
    ).fetchone()
    if existing is not None:
        return False
    _log.info("[compact] creating covering index %s (one-time)", THREAD_REVISION_INDEX)
    connection.execute(
        f"CREATE INDEX IF NOT EXISTS {THREAD_REVISION_INDEX} "
        "ON core_app_events(thread_id, revision)"
    )
    return True


def _ensure_sync_entity_index(connection: sqlite3.Connection) -> bool:
    existing = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (SYNC_ENTITY_INDEX,)
    ).fetchone()
    if existing is not None:
        return False
    _log.info("[compact] creating entity index %s (one-time)", SYNC_ENTITY_INDEX)
    connection.execute(
        f"CREATE INDEX IF NOT EXISTS {SYNC_ENTITY_INDEX} "
        "ON core_sync_changes(entity_type, entity_id, seq)"
    )
    return True


def _vacuum(connection: sqlite3.Connection) -> None:
    _log.info("[compact] VACUUM started")
    connection.execute("VACUUM")
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    _log.info("[compact] VACUUM finished")


def compact_sync_journal(
    db_path: str | Path,
    *,
    apply: bool = False,
    keep_per_entity: int = 1,
    vacuum: bool = True,
    backup: bool = True,
    backup_dir: str | Path | None = None,
) -> SyncCompactionReport:
    """Drop superseded runtime snapshots and reclaim the space.

    ``apply=False`` performs the read-only planning queries and stops.
    """
    path = Path(db_path)
    if not path.is_file():
        raise SyncCompactionError(f"数据库不存在：{path}")
    keep = max(1, int(keep_per_entity or 1))
    started = time.perf_counter()
    report = SyncCompactionReport(db_path=str(path))

    connection = _connect(path)
    try:
        report.before_bytes = _dbfile_bytes(connection)
        tables = _table_names(connection)
        if "core_sync_changes" not in tables:
            raise SyncCompactionError("core_sync_changes 不存在，无法压缩")
        if "core_app_events" not in tables:
            raise SyncCompactionError("core_app_events 不存在，无法压缩")

        before = _journal_stats(connection)
        report.max_seq_before = before["max_seq"]
        report.total_changes_before = before["total"]
        report.runtime_changes_before = before["runtime"]
        report.runtime_entities = before["entities"]
        report.other_changes = before["total"] - before["runtime"]

        if not apply:
            report.notes.append("dry-run：仅统计，未修改数据库")
            report.duration_seconds = time.perf_counter() - started
            return report

        _checkpoint(connection)

        if backup:
            connection.close()
            report.backup_path = str(_backup_database(path, backup_dir))
            connection = _connect(path)

        _rebuild_journal(connection, keep_per_entity=keep)
        report.index_created = _ensure_revision_index(connection)
        report.entity_index_created = _ensure_sync_entity_index(connection)

        after = _journal_stats(connection)
        report.max_seq_after = after["max_seq"]
        report.total_changes_after = after["total"]
        report.runtime_changes_after = after["runtime"]
        report.deleted_changes = report.total_changes_before - report.total_changes_after
        report.applied = True

        if report.max_seq_after != report.max_seq_before:
            raise SyncCompactionError(
                "压缩后游标回退：最新 seq 发生变化，已保留备份"
            )

        if vacuum:
            free = shutil.disk_usage(path.parent).free
            needed = max(report.before_bytes // 4, 512 * 1024 * 1024)
            if free < needed:
                report.notes.append(
                    f"磁盘剩余 {free // 1048576}MB，低于 VACUUM 需要的 {needed // 1048576}MB，跳过缩容"
                )
            else:
                _vacuum(connection)
                report.vacuumed = True

        report.after_bytes = _dbfile_bytes(connection)
        report.duration_seconds = time.perf_counter() - started
        return report
    finally:
        try:
            connection.close()
        except Exception:  # noqa: BLE001 - closing must never mask the real error
            pass


def _rebuild_journal(connection: sqlite3.Connection, *, keep_per_entity: int) -> None:
    ddl = _sync_table_ddl(connection)
    index_sql = _explicit_index_sql(connection)
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(f'DROP TABLE IF EXISTS "{_COMPACT_TABLE}"')
        connection.execute(f'DROP TABLE IF EXISTS temp."{_KEEP_TABLE}"')
        connection.execute(f'CREATE TEMP TABLE "{_KEEP_TABLE}" (seq INTEGER PRIMARY KEY)')
        connection.execute(
            f'INSERT INTO "{_KEEP_TABLE}"(seq) '
            "SELECT seq FROM ("
            "  SELECT seq, ROW_NUMBER() OVER ("
            "    PARTITION BY entity_id ORDER BY seq DESC"
            "  ) AS row_number FROM core_sync_changes WHERE entity_type='runtime'"
            ") WHERE row_number <= ?",
            (keep_per_entity,),
        )
        connection.execute(_replace_table_name(ddl, _COMPACT_TABLE))
        connection.execute(
            f'INSERT INTO "{_COMPACT_TABLE}" '
            "SELECT * FROM core_sync_changes "
            "WHERE entity_type <> 'runtime' "
            f'OR seq IN (SELECT seq FROM "{_KEEP_TABLE}")'
        )
        connection.execute("DROP TABLE core_sync_changes")
        connection.execute(f'ALTER TABLE "{_COMPACT_TABLE}" RENAME TO core_sync_changes')
        for statement in index_sql:
            connection.execute(statement)
        connection.execute(f'DROP TABLE IF EXISTS temp."{_KEEP_TABLE}"')
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def write_report(report: SyncCompactionReport, path: str | Path | None) -> None:
    payload = report.to_dict()
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _log.info("[compact] %s", text)
