"""One-shot cleanup for an installed Constant core.db.

What it removes (all of it is redundant or re-derivable):

* inline base64 images inside ``core_history_entries.message_json`` — the
  message text keeps the absolute file path and gains ``metadata.image_ref``;
  the file itself is never touched, so the model can re-read it;
* superseded ``thread`` rows in ``core_sync_changes`` — only the newest change
  per session survives (the full-snapshot copy is what made single rows 13 MB);
* old ``thread.event`` rows — only the newest ``--keep-thread-events`` survive
  (clients with an older cursor rebuild from a snapshot by design);
* then ``VACUUM`` reclaims the file space.

Safety:

* dry-run by default; pass ``--apply`` to modify;
* a file-level backup is taken by default (``--no-backup`` to skip);
* the backend must be stopped — the script takes an exclusive write lock and
  refuses to run if the database is busy;
* every history row is rewritten only when an inline image block was actually
  found; rows without a recoverable path are left untouched and reported.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

DEFAULT_DB = Path(r"E:\setuptest\constant\.lam\core.db")
DEFAULT_BACKUP_DIR = Path(r"E:\setuptest\constant\.lam\backups")
PATH_RE = re.compile(r"图片文件:\s*(.+?)[（(]")
DATA_URL_RE = re.compile(r"^data:([^;,]+)[;,]?")


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"


def connect(db: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(db), timeout=30, isolation_level=None)
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def table_stats(connection: sqlite3.Connection) -> dict[str, int]:
    stats = {}
    stats["db_bytes"] = Path(connection.execute("PRAGMA database_list").fetchone()[2]).stat().st_size
    for name, sql in (
        ("history_image_rows", "SELECT count(*) FROM core_history_entries WHERE message_json LIKE '%data:image%'"),
        ("history_image_bytes", "SELECT coalesce(sum(length(message_json)),0) FROM core_history_entries WHERE message_json LIKE '%data:image%'"),
        ("sync_rows", "SELECT count(*) FROM core_sync_changes"),
        ("sync_bytes", "SELECT coalesce(sum(length(entity_json)),0) FROM core_sync_changes"),
        ("thread_rows", "SELECT count(*) FROM core_sync_changes WHERE entity_type='thread'"),
        ("thread_bytes", "SELECT coalesce(sum(length(entity_json)),0) FROM core_sync_changes WHERE entity_type='thread'"),
        ("thread_event_rows", "SELECT count(*) FROM core_sync_changes WHERE entity_type='thread.event'"),
        ("thread_event_bytes", "SELECT coalesce(sum(length(entity_json)),0) FROM core_sync_changes WHERE entity_type='thread.event'"),
    ):
        stats[name] = int(connection.execute(sql).fetchone()[0])
    return stats


def clean_message(raw: str) -> tuple[str, int, bool]:
    """Return (new_json, removed_blocks, has_recoverable_path)."""
    try:
        message = json.loads(raw)
    except (TypeError, ValueError):
        return raw, 0, False
    if not isinstance(message, dict):
        return raw, 0, False
    content = message.get("content")
    if not isinstance(content, list):
        return raw, 0, False

    text = "\n".join(
        str(block.get("text") or "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
    match = PATH_RE.search(text)
    path = match.group(1).strip() if match else ""
    mime = ""
    kept: list[dict] = []
    removed = 0
    for block in content:
        if isinstance(block, dict) and block.get("type") == "image_url":
            image = block.get("image_url")
            url = image.get("url") if isinstance(image, dict) else None
            if isinstance(url, str) and url.startswith("data:"):
                removed += 1
                mime_match = DATA_URL_RE.match(url)
                if mime_match and not mime:
                    mime = mime_match.group(1)
                continue
        kept.append(block)
    if not removed:
        return raw, 0, bool(path)
    message["content"] = kept
    metadata = message.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        message["metadata"] = metadata
    if path and "image_ref" not in metadata:
        metadata["image_ref"] = {"path": path, "mime": mime, "sha256": ""}
    return json.dumps(message, ensure_ascii=False, separators=(",", ":")), removed, bool(path)


def backup(db: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"core.db.before-cleanup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    log(f"备份数据库 -> {target}（{human(db.stat().st_size)}）")
    started = time.perf_counter()
    shutil.copy2(db, target)
    log(f"备份完成，用时 {time.perf_counter() - started:.0f}s")
    return target


def clean_history(connection: sqlite3.Connection, *, apply: bool) -> dict[str, int]:
    rows = connection.execute(
        "SELECT seq, message_json FROM core_history_entries WHERE message_json LIKE '%data:image%'"
    ).fetchall()
    log(f"历史：{len(rows)} 条含内联图片")
    updated = 0
    removed = 0
    skipped = 0
    before_bytes = sum(len(raw) for _, raw in rows)
    after_bytes = 0
    for index, (seq, raw) in enumerate(rows, 1):
        new_raw, removed_here, has_path = clean_message(raw)
        after_bytes += len(new_raw)
        if removed_here:
            if not has_path:
                skipped += 1
                log(f"  跳过 seq={seq}：找不到文件路径，保留原图")
                after_bytes += len(raw) - len(new_raw)
                continue
            removed += removed_here
            if apply:
                connection.execute(
                    "UPDATE core_history_entries SET message_json=? WHERE seq=?",
                    (new_raw, seq),
                )
            updated += 1
        if index % 100 == 0:
            log(f"  已处理 {index}/{len(rows)}")
    return {
        "rows": len(rows),
        "updated": updated,
        "removed_blocks": removed,
        "skipped": skipped,
        "before_bytes": before_bytes,
        "after_bytes": after_bytes,
    }


def prune_sync(connection: sqlite3.Connection, *, apply: bool, keep_events: int) -> dict[str, int]:
    thread_before = connection.execute(
        "SELECT count(*) FROM core_sync_changes WHERE entity_type='thread'"
    ).fetchone()[0]
    event_before = connection.execute(
        "SELECT count(*) FROM core_sync_changes WHERE entity_type='thread.event'"
    ).fetchone()[0]

    if apply:
        connection.execute(
            "DELETE FROM core_sync_changes WHERE entity_type='thread' AND seq NOT IN ("
            "SELECT max(seq) FROM core_sync_changes WHERE entity_type='thread' GROUP BY entity_id)"
        )
        cutoff = connection.execute(
            "SELECT seq FROM core_sync_changes WHERE entity_type='thread.event' "
            "ORDER BY seq DESC LIMIT 1 OFFSET ?",
            (max(0, keep_events - 1),),
        ).fetchone()
        if cutoff is not None:
            connection.execute(
                "DELETE FROM core_sync_changes WHERE entity_type='thread.event' AND seq < ?",
                (int(cutoff[0]),),
            )

    thread_after = connection.execute(
        "SELECT count(*) FROM core_sync_changes WHERE entity_type='thread'"
    ).fetchone()[0]
    event_after = connection.execute(
        "SELECT count(*) FROM core_sync_changes WHERE entity_type='thread.event'"
    ).fetchone()[0]
    return {
        "thread_before": thread_before,
        "thread_after": thread_after,
        "thread_deleted": thread_before - thread_after,
        "event_before": event_before,
        "event_after": event_after,
        "event_deleted": event_before - event_after,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true", help="真正修改数据库；默认只统计")
    parser.add_argument("--backup", dest="backup", action="store_true", default=True)
    parser.add_argument("--no-backup", dest="backup", action="store_false")
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--keep-thread-events", type=int, default=20_000)
    parser.add_argument("--vacuum", dest="vacuum", action="store_true", default=True)
    parser.add_argument("--no-vacuum", dest="vacuum", action="store_false")
    args = parser.parse_args()

    db = args.db
    if not db.is_file():
        log(f"数据库不存在：{db}")
        return 2
    log(f"数据库：{db}（{human(db.stat().st_size)}）")
    connection = connect(db)
    try:
        before = table_stats(connection)
        log(
            "清理前："
            f"历史含图 {before['history_image_rows']} 条 / {human(before['history_image_bytes'])}；"
            f"同步日志 {before['sync_rows']} 条 / {human(before['sync_bytes'])}"
            f"（thread {before['thread_rows']} 条 / {human(before['thread_bytes'])}，"
            f"thread.event {before['thread_event_rows']} 条 / {human(before['thread_event_bytes'])}）"
        )
        if not args.apply:
            log("dry-run：未修改。加 --apply 执行。")
            return 0

        if args.backup:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.close()
            backup(db, args.backup_dir)
            connection = connect(db)

        log("清理历史内联图片…")
        connection.execute("BEGIN IMMEDIATE")
        history = clean_history(connection, apply=True)
        connection.execute("COMMIT")
        log(
            f"历史完成：改写 {history['updated']} 条，移除 {history['removed_blocks']} 个图片块，"
            f"跳过 {history['skipped']} 条，"
            f"{human(history['before_bytes'])} -> {human(history['after_bytes'])}"
        )

        log("清理同步日志…")
        connection.execute("BEGIN IMMEDIATE")
        sync = prune_sync(connection, apply=True, keep_events=args.keep_thread_events)
        connection.execute("COMMIT")
        log(
            f"同步日志完成：thread {sync['thread_before']} -> {sync['thread_after']}，"
            f"thread.event {sync['event_before']} -> {sync['event_after']}"
        )

        if args.vacuum:
            log("VACUUM 回收空间（可能需要十几分钟）…")
            started = time.perf_counter()
            connection.execute("VACUUM")
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            log(f"VACUUM 完成，用时 {time.perf_counter() - started:.0f}s")

        after = table_stats(connection)
        log(f"清理后数据库：{human(after['db_bytes'])}（之前 {human(before['db_bytes'])}）")
        log(
            "清理后："
            f"历史含图 {after['history_image_rows']} 条；"
            f"同步日志 {after['sync_rows']} 条 / {human(after['sync_bytes'])}"
        )
        log("integrity_check…")
        result = connection.execute("PRAGMA integrity_check").fetchone()
        log(f"integrity_check = {result[0] if result else 'unknown'}")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
