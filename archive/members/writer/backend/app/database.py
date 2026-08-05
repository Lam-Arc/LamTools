from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from weakref import WeakValueDictionary

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from lamtools_core.app.sqlite_write import (
    SQLiteWriteCoordinator,
    configure_sqlite_engine,
    database_identity,
)

from .config import SHARED_CONFIG_TABLES, SHARED_SETTING_NAMESPACES, SHARED_SETTING_PREFIXES, settings

T = TypeVar("T")
WriterWriteAction = Callable[[AsyncSession], Awaitable[T]]


def create_writer_engine(
    database_url: str,
    *,
    debug: bool = False,
    poolclass: type | None = None,
) -> AsyncEngine:
    options: dict[str, Any] = {"echo": debug}
    if poolclass is not None:
        options["poolclass"] = poolclass
    engine = create_async_engine(database_url, **options)
    if engine.url.get_backend_name().startswith("sqlite"):
        configure_sqlite_engine(engine)
    return engine


engine = create_writer_engine(settings.database_url, debug=settings.debug)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

_WRITER_WRITE_COORDINATORS: WeakValueDictionary[str, SQLiteWriteCoordinator] = WeakValueDictionary()


def writer_write_coordinator(session_factory: Any = async_session) -> SQLiteWriteCoordinator:
    identity = database_identity(session_factory)
    coordinator = _WRITER_WRITE_COORDINATORS.get(identity)
    if coordinator is None:
        coordinator = SQLiteWriteCoordinator(session_factory, identity=identity)
        _WRITER_WRITE_COORDINATORS[identity] = coordinator
    return coordinator


async def writer_write(
    action: WriterWriteAction[T],
    *,
    session_factory: Any = async_session,
) -> T:
    return await writer_write_coordinator(session_factory).run(action)


def get_writer_write():
    return writer_write


async def execute_writer_write(
    db: AsyncSession,
    action: WriterWriteAction[T],
    write_transaction: Any = None,
) -> T:
    if callable(write_transaction):
        return await write_transaction(action)
    result = await action(db)
    await db.commit()
    return result


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    # Import all models before create_all so SQLAlchemy metadata is complete.
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name().startswith("sqlite"):
            await _migrate_sqlite_schema(conn)


async def _migrate_sqlite_schema(conn) -> None:
    """Apply additive SQLite migrations for existing local databases.

    LamWriter uses SQLite in local desktop mode and currently does not have a
    full migration runner. `create_all()` creates missing tables but does not
    add columns to existing tables, so API/model expansion must be handled here
    to keep upgraded user databases usable.
    """
    table_columns: dict[str, set[str]] = {}

    async def columns(table: str) -> set[str]:
        if table not in table_columns:
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            table_columns[table] = {row[1] for row in result.fetchall()}
        return table_columns[table]

    async def add_column(table: str, name: str, definition: str) -> None:
        existing = await columns(table)
        if name not in existing:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
            existing.add(name)

    async def table_exists(table: str) -> bool:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
            {"name": table},
        )
        return result.first() is not None

    async def create_table(table: str, ddl: str) -> None:
        if not await table_exists(table):
            await conn.execute(text(ddl))

    await add_column("writer_sessions", "project_id", "VARCHAR(36)")
    await add_column("writer_sessions", "loop_position", "VARCHAR(50) DEFAULT 'execute'")
    await add_column("writer_sessions", "task_complexity", "VARCHAR(50) DEFAULT 'simple'")
    await add_column("writer_sessions", "planning_depth", "VARCHAR(50)")
    await add_column("writer_sessions", "turn_count", "INTEGER DEFAULT 0")
    await add_column("writer_sessions", "error_count", "INTEGER DEFAULT 0")
    await add_column("writer_sessions", "transcript_revision", "INTEGER DEFAULT 0")
    await add_column("writer_sessions", "todos", "JSON")
    await add_column("writer_sessions", "open_loops", "JSON")
    await add_column("writer_sessions", "context_summary", "TEXT")
    await add_column("writer_sessions", "task_plan", "JSON")
    await add_column("writer_sessions", "runtime_state", "JSON")
    await add_column("writer_sessions", "metadata", "JSON")

    await add_column("writer_messages", "turn_data", "JSON")
    await add_column("writer_messages", "metadata", "JSON")

    await add_column("writer_messages", "run_id", "VARCHAR(36)")
    await add_column("writer_messages", "parts", "JSON")

    await create_table(
        "writer_transcript_turns",
        """
        CREATE TABLE writer_transcript_turns (
            id VARCHAR(36) PRIMARY KEY,
            session_id VARCHAR(36) NOT NULL,
            sequence INTEGER NOT NULL,
            user_text TEXT DEFAULT '',
            user_message_id VARCHAR(36),
            status_cache VARCHAR(50),
            final_reply_block_id VARCHAR(36),
            started_at DATETIME,
            last_state_changed_at DATETIME,
            terminal_at DATETIME,
            terminal_reason VARCHAR(100),
            error TEXT,
            metadata JSON
        )
        """,
    )
    await create_table(
        "writer_transcript_model_calls",
        """
        CREATE TABLE writer_transcript_model_calls (
            id VARCHAR(64) PRIMARY KEY,
            turn_id VARCHAR(36) NOT NULL,
            sequence INTEGER NOT NULL,
            provider VARCHAR(100),
            model VARCHAR(255),
            status VARCHAR(50) DEFAULT 'running',
            started_at DATETIME,
            completed_at DATETIME,
            input_tokens INTEGER,
            output_tokens INTEGER,
            error TEXT,
            metadata JSON
        )
        """,
    )
    await create_table(
        "writer_transcript_blocks",
        """
        CREATE TABLE writer_transcript_blocks (
            id VARCHAR(128) PRIMARY KEY,
            turn_id VARCHAR(36) NOT NULL,
            model_call_id VARCHAR(64),
            parent_block_id VARCHAR(128),
            producer_id VARCHAR(64),
            sequence INTEGER NOT NULL,
            event_sequence INTEGER NOT NULL,
            type VARCHAR(50) NOT NULL,
            status VARCHAR(50) DEFAULT 'running',
            content TEXT,
            request_kind VARCHAR(50),
            response_json JSON,
            tool_name VARCHAR(100),
            tool_call_id VARCHAR(128),
            tool_args_json JSON,
            tool_result_preview TEXT,
            error TEXT,
            started_at DATETIME,
            updated_at DATETIME,
            completed_at DATETIME,
            duration_ms INTEGER,
            metadata JSON
        )
        """,
    )
    await create_table(
        "writer_active_producers",
        """
        CREATE TABLE writer_active_producers (
            id VARCHAR(64) PRIMARY KEY,
            turn_id VARCHAR(36) NOT NULL,
            model_call_id VARCHAR(64),
            parent_block_id VARCHAR(128),
            kind VARCHAR(50) DEFAULT 'runtime',
            started_at DATETIME,
            heartbeat_at DATETIME,
            closed_at DATETIME,
            close_reason VARCHAR(50),
            recoverable BOOLEAN DEFAULT 0
        )
        """,
    )
    await create_table(
        "writer_transcript_artifacts",
        """
        CREATE TABLE writer_transcript_artifacts (
            id VARCHAR(36) PRIMARY KEY,
            turn_id VARCHAR(36) NOT NULL,
            block_id VARCHAR(128) NOT NULL,
            file_name VARCHAR(255) DEFAULT '',
            file_path VARCHAR(2048) DEFAULT '',
            file_type VARCHAR(50) DEFAULT 'file',
            mime_type VARCHAR(255),
            size_bytes INTEGER,
            content_hash VARCHAR(128),
            created_at DATETIME,
            metadata JSON
        )
        """,
    )
    await create_table(
        "writer_app_events",
        """
        CREATE TABLE writer_app_events (
            event_id VARCHAR(64) PRIMARY KEY,
            thread_id VARCHAR(36) NOT NULL,
            seq INTEGER NOT NULL,
            turn_id VARCHAR(64),
            item_id VARCHAR(128),
            parent_item_id VARCHAR(128),
            client_message_id VARCHAR(64),
            method VARCHAR(100) NOT NULL,
            payload_json JSON NOT NULL,
            created_at DATETIME NOT NULL,
            persisted_at DATETIME NOT NULL,
            CONSTRAINT uq_writer_app_events_thread_seq UNIQUE (thread_id, seq)
        )
        """,
    )
    await create_table(
        "writer_thread_snapshots",
        """
        CREATE TABLE writer_thread_snapshots (
            thread_id VARCHAR(36) PRIMARY KEY,
            snapshot_seq INTEGER NOT NULL DEFAULT 0,
            snapshot_json JSON NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """,
    )
    await create_table(
        "writer_artifacts",
        """
        CREATE TABLE writer_artifacts (
            artifact_id VARCHAR(64) PRIMARY KEY,
            thread_id VARCHAR(36) NOT NULL,
            turn_id VARCHAR(64),
            item_id VARCHAR(128),
            kind VARCHAR(50) NOT NULL,
            name VARCHAR(255) NOT NULL DEFAULT '',
            path VARCHAR(2048) NOT NULL DEFAULT '',
            mime_type VARCHAR(255),
            size_bytes INTEGER,
            content_hash VARCHAR(128),
            metadata JSON,
            created_at DATETIME NOT NULL
        )
        """,
    )

    transcript_indexes = [
        "CREATE INDEX IF NOT EXISTS idx_writer_sessions_transcript_revision ON writer_sessions(transcript_revision)",
        "CREATE INDEX IF NOT EXISTS idx_writer_transcript_turns_session_sequence ON writer_transcript_turns(session_id, sequence)",
        "CREATE INDEX IF NOT EXISTS idx_writer_transcript_blocks_turn_sequence ON writer_transcript_blocks(turn_id, sequence)",
        "CREATE INDEX IF NOT EXISTS idx_writer_transcript_blocks_call_sequence ON writer_transcript_blocks(model_call_id, sequence)",
        "CREATE INDEX IF NOT EXISTS idx_writer_transcript_blocks_parent_sequence ON writer_transcript_blocks(parent_block_id, sequence)",
        "CREATE INDEX IF NOT EXISTS idx_writer_active_producers_turn_closed ON writer_active_producers(turn_id, closed_at)",
        "CREATE INDEX IF NOT EXISTS idx_writer_transcript_artifacts_turn ON writer_transcript_artifacts(turn_id)",
        "CREATE INDEX IF NOT EXISTS idx_writer_transcript_artifacts_block ON writer_transcript_artifacts(block_id)",
        "CREATE INDEX IF NOT EXISTS idx_writer_app_events_thread_seq ON writer_app_events(thread_id, seq)",
        "CREATE INDEX IF NOT EXISTS idx_writer_app_events_thread_turn_seq ON writer_app_events(thread_id, turn_id, seq)",
        "CREATE INDEX IF NOT EXISTS idx_writer_app_events_thread_item_seq ON writer_app_events(thread_id, item_id, seq)",
        "CREATE INDEX IF NOT EXISTS idx_writer_app_events_client_message ON writer_app_events(client_message_id)",
        "CREATE INDEX IF NOT EXISTS idx_writer_artifacts_thread_item ON writer_artifacts(thread_id, item_id)",
    ]
    for statement in transcript_indexes:
        await conn.execute(text(statement))

    for table in SHARED_CONFIG_TABLES:
        await conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
    if await table_exists("app_settings"):
        for namespace in SHARED_SETTING_NAMESPACES:
            await conn.execute(
                text("DELETE FROM app_settings WHERE namespace = :namespace"),
                {"namespace": namespace},
            )
        for prefix in SHARED_SETTING_PREFIXES:
            await conn.execute(
                text("DELETE FROM app_settings WHERE namespace LIKE :prefix"),
                {"prefix": f"{prefix}%"},
            )
