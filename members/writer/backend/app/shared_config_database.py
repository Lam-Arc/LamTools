from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lamtools_core.config.shared_database import init_shared_config_schema

from app.config import SHARED_SETTING_NAMESPACES, SHARED_SETTING_PREFIXES, _legacy_appdata_dir, settings


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def shared_config_db_path() -> Path:
    raw = os.environ.get("LAMTOOLS_LLM_CONFIG_DB") or ""
    if raw.strip():
        return Path(raw).expanduser()
    return _repo_root() / "data" / "lamtools.db"


def shared_config_database_url() -> str:
    path = shared_config_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{path}"


shared_config_engine = create_async_engine(
    shared_config_database_url(),
    echo=settings.debug,
)
shared_config_session = async_sessionmaker(
    shared_config_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_shared_config_db():
    async with shared_config_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_shared_config_db() -> None:
    await init_shared_config_schema(shared_config_engine)
    migrate_legacy_shared_config(shared_config_db_path())


def migrate_legacy_shared_config(
    shared_db_path_value: Path | str,
    legacy_db_path: Path | str | None = None,
) -> bool:
    shared_path = Path(shared_db_path_value)
    legacy_path = Path(legacy_db_path) if legacy_db_path is not None else _legacy_appdata_dir() / "lamwriter.db"
    if not legacy_path.exists():
        return False
    try:
        if shared_path.resolve() == legacy_path.resolve():
            return False
    except OSError:
        return False

    shared_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(legacy_path) as legacy_conn, sqlite3.connect(shared_path) as shared_conn:
        if _table_count(shared_conn, "llm_providers") > 0:
            return False
        copied = False
        copied = _copy_table_rows(legacy_conn, shared_conn, "llm_providers") or copied
        copied = _copy_table_rows(legacy_conn, shared_conn, "llm_models") or copied
        copied = _copy_shared_setting_rows(legacy_conn, shared_conn) or copied
        shared_conn.commit()
        return copied


def _copy_table_rows(source: sqlite3.Connection, target: sqlite3.Connection, table: str) -> bool:
    source_columns = _table_columns(source, table)
    target_columns = _table_columns(target, table)
    columns = [column for column in target_columns if column in source_columns]
    if not columns:
        return False
    rows = source.execute(
        f"SELECT {_column_list(columns)} FROM {_quote_identifier(table)}"
    ).fetchall()
    return _insert_rows(target, table, columns, rows)


def _copy_shared_setting_rows(source: sqlite3.Connection, target: sqlite3.Connection) -> bool:
    table = "app_settings"
    source_columns = _table_columns(source, table)
    target_columns = _table_columns(target, table)
    columns = [column for column in target_columns if column in source_columns]
    if "namespace" not in columns:
        return False
    namespace_index = columns.index("namespace")
    rows = [
        row
        for row in source.execute(f"SELECT {_column_list(columns)} FROM app_settings").fetchall()
        if _is_shared_setting_namespace(str(row[namespace_index] or ""))
    ]
    return _insert_rows(target, table, columns, rows)


def _insert_rows(
    target: sqlite3.Connection,
    table: str,
    columns: list[str],
    rows: list[tuple[Any, ...]],
) -> bool:
    if not rows:
        return False
    before = target.total_changes
    placeholders = ", ".join("?" for _ in columns)
    target.executemany(
        f"INSERT OR IGNORE INTO {_quote_identifier(table)} ({_column_list(columns)}) VALUES ({placeholders})",
        rows,
    )
    return target.total_changes > before


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    if not _sqlite_table_exists(conn, table):
        return 0
    row = conn.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}").fetchone()
    return int(row[0] or 0) if row is not None else 0


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if not _sqlite_table_exists(conn, table):
        return []
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({_quote_identifier(table)})").fetchall()]


def _sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _is_shared_setting_namespace(namespace: str) -> bool:
    if namespace in SHARED_SETTING_NAMESPACES:
        return True
    return namespace.startswith(SHARED_SETTING_PREFIXES)


def _column_list(columns: list[str]) -> str:
    return ", ".join(_quote_identifier(column) for column in columns)


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


__all__ = [
    "get_shared_config_db",
    "init_shared_config_db",
    "migrate_legacy_shared_config",
    "shared_config_db_path",
    "shared_config_database_url",
    "shared_config_engine",
    "shared_config_session",
]
