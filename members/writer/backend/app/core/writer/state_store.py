from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import Base, _migrate_sqlite_schema, create_writer_engine, writer_write_coordinator
from .schemas import (
    WriterSessionState,
    WriterPhase,
    WriterInteractionMode,
    WriterLoopPosition,
    TaskComplexity,
    PlanningDepth,
    TaskPlan,
    DelegationStatus,
)
from app.models.session import WriterSession

logger = logging.getLogger(__name__)


class WriterStateStore:
    """DB-backed state store using SQLAlchemy.

    Replaces the old in-memory + JSON file persistence.
    The runtime still holds WriterSessionState (Pydantic) in memory for fast access,
    but all persistence goes through the DB.
    """

    def __init__(self, db_factory=None, *, write_coordinator=None):
        """Initialize with an async session factory.

        Args:
            db_factory: Callable that returns an AsyncSession context manager,
                        or a data directory path for a local SQLite state DB.
                        If None, use the app-wide DB session factory.
        """
        self._engine = None
        self._initialized = False
        if isinstance(db_factory, (str, Path)):
            data_dir = Path(db_factory)
            data_dir.mkdir(parents=True, exist_ok=True)
            db_url = f"sqlite+aiosqlite:///{data_dir / 'lamwriter.db'}"
            self._engine = create_writer_engine(db_url, debug=False, poolclass=NullPool)
            self._db_factory = async_sessionmaker(
                self._engine, class_=AsyncSession, expire_on_commit=False
            )
        else:
            if db_factory is None:
                from app.database import async_session

                self._db_factory = async_session
                self._initialized = True
            else:
                self._db_factory = db_factory
        self._write_coordinator = write_coordinator or writer_write_coordinator(self._db_factory)
        self._cache: dict[str, WriterSessionState] = {}

    async def get(self, session_id: str, db: AsyncSession | None = None) -> WriterSessionState | None:
        """Load state from DB and return as WriterSessionState Pydantic model."""
        # Check in-memory cache first
        if session_id in self._cache:
            return self._cache[session_id]

        session = await self._get_session(session_id, db)
        if session is None:
            return None

        state = WriterSessionState.from_session(session)
        self._cache[session_id] = state
        return state

    async def save(self, state: WriterSessionState, db: AsyncSession | None = None) -> None:
        """Persist WriterSessionState to DB."""
        self._cache[state.session_id] = state

        if db is not None:
            await self._save_in_transaction(db, state)
            return
        await self._ensure_initialized()
        await self._write_coordinator.run(lambda write_db: self._save_in_transaction(write_db, state))

    async def _save_in_transaction(self, db: AsyncSession, state: WriterSessionState) -> None:
        session = await db.get(WriterSession, state.session_id)
        if session is None:
            session = WriterSession(id=state.session_id)
            db.add(session)

        updates = state.to_session_updates()
        existing_runtime_state = session.runtime_state if isinstance(session.runtime_state, dict) else {}
        next_runtime_state = updates.get("runtime_state") if isinstance(updates.get("runtime_state"), dict) else {}
        if existing_runtime_state:
            updates["runtime_state"] = {**existing_runtime_state, **next_runtime_state}
            if (
                isinstance(existing_runtime_state.get("manual_compaction"), dict)
                and session.context_summary
                and updates.get("context_summary") != session.context_summary
            ):
                updates["context_summary"] = session.context_summary
        for key, value in updates.items():
            if hasattr(session, key):
                setattr(session, key, value)

    async def delete(self, session_id: str, db: AsyncSession | None = None) -> None:
        """Delete session from DB and clear cache."""
        self._cache.pop(session_id, None)

        if db is not None:
            await self._delete_in_transaction(db, session_id)
            return
        await self._ensure_initialized()
        await self._write_coordinator.run(lambda write_db: self._delete_in_transaction(write_db, session_id))

    async def _delete_in_transaction(self, db: AsyncSession, session_id: str) -> None:
        session = await db.get(WriterSession, session_id)
        if session is not None:
            await db.delete(session)

    async def create(
        self,
        session_id: str,
        work_root: str = "",
        db: AsyncSession | None = None,
    ) -> WriterSessionState:
        """Create a new session in DB and return as WriterSessionState."""
        state = WriterSessionState(
            session_id=session_id,
            work_root=work_root,
        )

        if db is not None:
            await self._create_in_transaction(db, state)
        else:
            await self._ensure_initialized()
            await self._write_coordinator.run(lambda write_db: self._create_in_transaction(write_db, state))

        self._cache[session_id] = state
        return state

    async def _create_in_transaction(self, db: AsyncSession, state: WriterSessionState) -> None:
        session = WriterSession(
            id=state.session_id,
            work_root=state.work_root,
            phase="idle",
            status="active",
            loop_position="execute",
            task_complexity="simple",
            turn_count=0,
            error_count=0,
            runtime_state=state._runtime_state_dict(),
        )
        db.add(session)

    async def list_sessions(self, db: AsyncSession | None = None) -> list[WriterSessionState]:
        """List all sessions from DB."""
        own_db = db is None
        if own_db:
            db = await self._get_db()
        try:
            result = await db.execute(
                select(WriterSession).order_by(WriterSession.updated_at.desc())
            )
            sessions = result.scalars().all()
            return [WriterSessionState.from_session(s) for s in sessions]
        finally:
            if own_db and db:
                await db.close()

    # --- Internal helpers ---

    async def _get_session(self, session_id: str, db: AsyncSession | None = None) -> WriterSession | None:
        """Get a WriterSession DB row."""
        own_db = db is None
        if own_db:
            db = await self._get_db()
        try:
            return await db.get(WriterSession, session_id)
        finally:
            if own_db and db:
                await db.close()

    async def _get_db(self) -> AsyncSession:
        """Get a DB session from the factory."""
        await self._ensure_initialized()
        if self._db_factory is not None:
            return self._db_factory()
        from app.database import async_session
        return async_session()

    async def _ensure_initialized(self) -> None:
        if self._initialized or self._engine is None:
            return
        import app.models  # noqa: F401
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if self._engine.url.get_backend_name().startswith("sqlite"):
                await _migrate_sqlite_schema(conn)
        self._initialized = True
