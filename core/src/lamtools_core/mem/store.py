"""SQLite + in-memory implementations of :class:`MemoryStoreProtocol`.

These stores hold *short-term* memory: structured, searchable, decayable
entries produced during dreaming. Long-term memory lives in ``MEMORY.md`` and
is loaded verbatim into the system prompt by ``ProjectContextLoader``; the
store here is used for de-duplication during dreaming, not for prompt
injection.

Construction follows the same pattern as ``SqlAlchemyRuntimeStateStore`` /
``SqlAlchemyGoalStore``: a ``(session_factory, write_coordinator)`` pair, with
all writes serialised through ``SQLiteWriteCoordinator.run`` to avoid SQLite
write-lock contention with live session writes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from lamtools_core.app.core_db import CoreMemory
from lamtools_core.mem import (
    MemoryEntry,
    MemoryHit,
    MemoryQuery,
    MemoryRecallResult,
    MemoryStoreProtocol,
)

__all__ = ["SqlAlchemyMemoryStore", "InMemoryMemoryStore"]


# ── row ⇄ entry conversion ───────────────────────────────────────


def _entry_from_row(row: CoreMemory) -> MemoryEntry:
    return MemoryEntry(
        id=str(row.id),
        kind=str(row.kind),
        content=str(row.content),
        domain=str(row.domain or ""),
        source=str(row.source or ""),
        layer=str(row.layer or "warm"),  # type: ignore[arg-type]
        confidence=float(row.confidence or 0.0),
        metadata=dict(row.metadata_json or {}),
        score=float(row.score or 0.0),
        created_at=row.created_at or datetime.now(),
        accessed_at=row.accessed_at or datetime.now(),
        access_count=int(row.access_count or 0),
    )


def _row_values(entry: MemoryEntry, *, work_root: str = "", thread_id: str = "") -> dict[str, Any]:
    return {
        "id": entry.id,
        "thread_id": thread_id or entry.metadata.get("thread_id", ""),
        "work_root": work_root or entry.metadata.get("work_root", ""),
        "kind": entry.kind,
        "content": entry.content,
        "domain": entry.domain,
        "source": entry.source,
        "layer": entry.layer,
        "confidence": entry.confidence,
        "metadata_json": dict(entry.metadata),
        "score": entry.score,
        "created_at": entry.created_at,
        "accessed_at": entry.accessed_at,
        "access_count": entry.access_count,
    }


# ── SQLite store ─────────────────────────────────────────────────


class SqlAlchemyMemoryStore(MemoryStoreProtocol):
    """SQLAlchemy-backed short-term memory store.

    Implements ``add`` / ``get`` / ``delete`` / ``search`` from
    :class:`MemoryStoreProtocol`. ``search`` uses LIKE over ``content`` plus
    optional ``kind`` / ``domain`` / ``layer`` / ``confidence`` filters — no
    FTS5 dependency for the first cut.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker,
        write_coordinator: Any,
    ) -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator

    async def add(self, entry: MemoryEntry) -> None:
        if not entry.id:
            entry.id = uuid.uuid4().hex
        async def write(db):
            existing = await db.get(CoreMemory, entry.id)
            if existing is not None:
                # Upsert: merge into existing row rather than failing.
                for key, value in _row_values(entry).items():
                    setattr(existing, key, value)
            else:
                db.add(CoreMemory(**_row_values(entry)))
            await db.flush()

        await self.write_coordinator.run(write)

    async def get(self, entry_id: str) -> MemoryEntry | None:
        async with self.session_factory() as db:
            row = await db.get(CoreMemory, entry_id)
        return _entry_from_row(row) if row is not None else None

    async def delete(self, entry_id: str) -> None:
        async def write(db):
            await db.execute(delete(CoreMemory).where(CoreMemory.id == entry_id))

        await self.write_coordinator.run(write)

    async def search(self, query: MemoryQuery) -> MemoryRecallResult:
        statement = select(CoreMemory)
        if query.kinds:
            statement = statement.where(CoreMemory.kind.in_(query.kinds))
        if query.domains:
            statement = statement.where(CoreMemory.domain.in_(query.domains))
        if query.layers:
            statement = statement.where(CoreMemory.layer.in_(query.layers))
        if query.min_confidence > 0:
            statement = statement.where(CoreMemory.confidence >= query.min_confidence)

        # Content matching: split the query into whitespace terms and AND
        # them with LIKE %term% over content. This is intentionally simple —
        # good enough for de-duplication lookups during dreaming. FTS5 can
        # replace this later without touching the protocol.
        terms = [t for t in (query.query or "").split() if t]
        if terms:
            conditions = [CoreMemory.content.ilike(f"%{term}%") for term in terms]
            statement = statement.where(or_(*conditions))

        statement = statement.order_by(
            CoreMemory.confidence.desc(),
            CoreMemory.accessed_at.desc(),
        ).limit(max(1, query.limit))

        async with self.session_factory() as db:
            rows = (await db.execute(statement)).scalars().all()

        hits: list[MemoryHit] = []
        for row in rows:
            entry = _entry_from_row(row)
            # Lightweight relevance score: fraction of query terms present.
            score = _text_relevance(entry.content, query.query)
            hits.append(MemoryHit(entry=entry, score=score, source=entry.source or "store"))
        return MemoryRecallResult(query=query.query, hits=hits, total=len(hits))

    async def list_for_work_root(self, work_root: str) -> list[MemoryEntry]:
        """Return all memories scoped to a project root (used by dreaming)."""
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(CoreMemory)
                    .where(CoreMemory.work_root == work_root)
                    .order_by(CoreMemory.confidence.desc(), CoreMemory.created_at.desc())
                )
            ).scalars().all()
        return [_entry_from_row(row) for row in rows]

    async def touch(self, entry_id: str) -> None:
        """Bump access timestamp/count for a memory (decay bookkeeping)."""
        async def write(db):
            row = await db.get(CoreMemory, entry_id)
            if row is not None:
                row.accessed_at = datetime.now()
                row.access_count = int(row.access_count or 0) + 1

        await self.write_coordinator.run(write)


# ── In-memory store (fallback / testing) ─────────────────────────


class InMemoryMemoryStore(MemoryStoreProtocol):
    """Dict-backed store used when no database is configured.

    Matches :class:`InMemoryRuntimeStateStore`'s role: a no-dependency
    fallback so the agent still functions without SQLite.
    """

    def __init__(self) -> None:
        self._entries: dict[str, MemoryEntry] = {}

    async def add(self, entry: MemoryEntry) -> None:
        if not entry.id:
            entry.id = uuid.uuid4().hex
        self._entries[entry.id] = entry

    async def get(self, entry_id: str) -> MemoryEntry | None:
        return self._entries.get(entry_id)

    async def delete(self, entry_id: str) -> None:
        self._entries.pop(entry_id, None)

    async def search(self, query: MemoryQuery) -> MemoryRecallResult:
        candidates = list(self._entries.values())
        if query.kinds:
            candidates = [e for e in candidates if e.kind in query.kinds]
        if query.domains:
            candidates = [e for e in candidates if e.domain in query.domains]
        if query.layers:
            candidates = [e for e in candidates if e.layer in query.layers]
        if query.min_confidence > 0:
            candidates = [e for e in candidates if e.confidence >= query.min_confidence]

        terms = [t for t in (query.query or "").split() if t]
        if terms:
            ql = query.query.lower()
            candidates = [e for e in candidates if any(t.lower() in e.content.lower() for t in terms) or ql == ""]

        candidates.sort(key=lambda e: (e.confidence, e.accessed_at), reverse=True)
        candidates = candidates[: max(1, query.limit)]

        hits = [
            MemoryHit(entry=e, score=_text_relevance(e.content, query.query), source=e.source or "memory")
            for e in candidates
        ]
        return MemoryRecallResult(query=query.query, hits=hits, total=len(hits))

    async def list_for_work_root(self, work_root: str) -> list[MemoryEntry]:
        return [e for e in self._entries.values() if e.metadata.get("work_root") == work_root]

    async def touch(self, entry_id: str) -> None:
        entry = self._entries.get(entry_id)
        if entry is not None:
            entry.accessed_at = datetime.now()
            entry.access_count += 1


# ── helpers ──────────────────────────────────────────────────────


def _text_relevance(content: str, query: str) -> float:
    """Crude 0..1 relevance: fraction of query terms present in content."""
    if not query or not content:
        return 0.0
    terms = [t for t in query.split() if t]
    if not terms:
        return 0.0
    lowered = content.lower()
    present = sum(1 for t in terms if t.lower() in lowered)
    return present / len(terms)
