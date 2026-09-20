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

from copy import deepcopy
from datetime import datetime
import hashlib
from typing import Any
import uuid

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from lamtools_core.app.core_db import CoreMemory
from lamtools_core.mem import (
    MemoryEntry,
    MemoryHit,
    MemoryQuery,
    MemoryRecallResult,
    MemoryScope,
    MemoryStoreProtocol,
)

__all__ = ["SqlAlchemyMemoryStore", "InMemoryMemoryStore"]


# ── row ⇄ entry conversion ───────────────────────────────────────


def _uses_legacy_public_key(scope: MemoryScope) -> bool:
    """Whether a compatibility row may keep its historical physical id."""

    return bool(
        scope.compatibility_fallback
        and not scope.work_root
        and scope.project_id is None
        and scope.library_id is None
    )


def _storage_id(memory_id: str, scope: MemoryScope) -> str:
    """Return the internal row key for a public id/scope pair.

    ``MemoryEntry.id`` is a public identifier and is therefore allowed to
    repeat in independent scopes.  Existing databases used it as the SQL
    primary key, so new scoped rows use a deterministic bounded hash while
    empty local-legacy rows retain the old key for compatibility.
    """

    clean_id = str(memory_id or "").strip()
    if _uses_legacy_public_key(scope):
        return clean_id
    digest = hashlib.sha256(f"{scope.key}\x1f{clean_id}".encode("utf-8")).hexdigest()
    # CoreMemory.id is VARCHAR(64); retain 240 bits of the scope/id digest.
    return f"m2_{digest[:60]}"


def _storage_candidates(memory_id: str, scope: MemoryScope) -> list[str]:
    primary = _storage_id(memory_id, scope)
    candidates = [primary]
    # Rows written before scoped physical keys were introduced used the public
    # id even when their envelope already carried a scope marker.  Probe that
    # key only as a compatibility fallback; callers still must pass the exact
    # scope before a row can be returned or updated.
    if primary != str(memory_id or "").strip():
        candidates.append(str(memory_id or "").strip())
    return [item for item in candidates if item]


def _entry_from_row(row: CoreMemory) -> MemoryEntry:
    raw_metadata = dict(row.metadata_json or {})
    # Rows created before the scoped contract have no marker and intentionally
    # decode to an explicit local-legacy scope.  New fields live in the JSON
    # envelope so opening old databases does not require a destructive table
    # rebuild or a second memory store.
    scope_marker = raw_metadata.get("__memory_scope__")
    scope = (
        MemoryScope.from_dict(scope_marker)
        if isinstance(scope_marker, dict)
        else MemoryScope.local_legacy(row.work_root or raw_metadata.get("work_root") or "")
    )
    public_id = str(raw_metadata.get("__memory_id__") or row.id)
    status = str(raw_metadata.get("__memory_status__") or "active")
    if status not in {"candidate", "active", "superseded", "forgotten", "suppressed", "invalid"}:
        status = "active"
    origin = str(raw_metadata.get("__memory_origin__") or "inferred")
    if origin not in {"explicit", "observed", "inferred", "legacy", "teaching_hint"}:
        origin = "inferred"
    return MemoryEntry(
        id=public_id,
        kind=str(row.kind),
        content=str(row.content),
        domain=str(row.domain or ""),
        source=str(row.source or ""),
        layer=str(row.layer or "warm"),  # type: ignore[arg-type]
        confidence=float(row.confidence or 0.0),
        metadata={
            key: value
            for key, value in raw_metadata.items()
            if not key.startswith("__memory_")
        },
        score=float(row.score or 0.0),
        created_at=row.created_at or datetime.now(),
        accessed_at=row.accessed_at or datetime.now(),
        access_count=int(row.access_count or 0),
        scope=scope,
        status=status,  # type: ignore[arg-type]
        version=max(1, int(raw_metadata.get("__memory_version__") or 1)),
        origin=origin,  # type: ignore[arg-type]
        source_metadata=dict(raw_metadata.get("__memory_source_metadata__") or {}),
        source_refs=list(raw_metadata.get("__memory_source_refs__") or []),
        locked=bool(raw_metadata.get("__memory_locked__", False)),
    )


def _canonical_thread_id(metadata: dict[str, Any], fallback: str = "") -> str:
    """Normalize old ``session_id`` rows and new ``thread_id`` rows."""

    value = str(metadata.get("thread_id") or metadata.get("session_id") or fallback or "")
    if value:
        metadata.setdefault("thread_id", value)
        metadata.setdefault("session_id", value)
    return value


def _row_metadata(entry: MemoryEntry) -> dict[str, Any]:
    metadata = deepcopy(entry.metadata)
    metadata["__memory_id__"] = str(entry.id)
    metadata["__memory_scope__"] = entry.scope.to_dict()
    metadata["__memory_status__"] = entry.status
    metadata["__memory_version__"] = max(1, int(entry.version or 1))
    metadata["__memory_origin__"] = entry.origin
    metadata["__memory_source_metadata__"] = deepcopy(entry.source_metadata)
    metadata["__memory_source_refs__"] = deepcopy(entry.source_refs)
    metadata["__memory_locked__"] = bool(entry.locked)
    _canonical_thread_id(metadata)
    if entry.scope.work_root:
        metadata.setdefault("work_root", entry.scope.work_root)
    return metadata


def _row_values(
    entry: MemoryEntry,
    *,
    storage_id: str = "",
    work_root: str = "",
    thread_id: str = "",
) -> dict[str, Any]:
    metadata = _row_metadata(entry)
    canonical_thread_id = _canonical_thread_id(metadata, thread_id)
    canonical_work_root = work_root or entry.scope.work_root or str(metadata.get("work_root") or "")
    return {
        "id": storage_id or _storage_id(entry.id, entry.scope),
        "thread_id": canonical_thread_id,
        "work_root": canonical_work_root,
        "kind": entry.kind,
        "content": entry.content,
        "domain": entry.domain,
        "source": entry.source,
        "layer": entry.layer,
        "confidence": entry.confidence,
        "metadata_json": metadata,
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
        public_id = str(entry.id).strip()
        async def write(db):
            storage_id = _storage_id(public_id, entry.scope)
            existing = None
            existing_storage_id = storage_id
            for candidate in _storage_candidates(public_id, entry.scope):
                existing = await db.get(CoreMemory, candidate)
                if existing is not None:
                    existing_storage_id = candidate
                    break
            if existing is not None:
                # Never merge a public id across scopes.  The scoped physical
                # key normally makes this impossible; this check also protects
                # legacy rows and detects a corrupted/malicious envelope.
                current = _entry_from_row(existing)
                if (
                    existing_storage_id != storage_id
                    and current.id == public_id
                    and not current.scope.matches(entry.scope)
                ):
                    # A pre-v2 row from another scope still occupies the old
                    # public physical key.  Keep it intact and create this
                    # scope's independent hashed row instead.
                    existing = None
                elif current.id != public_id or not current.scope.matches(entry.scope):
                    raise PermissionError("Memory id belongs to another scope")
                if existing is not None:
                    for key, value in _row_values(entry, storage_id=existing_storage_id).items():
                        setattr(existing, key, value)
            if existing is None:
                db.add(CoreMemory(**_row_values(entry, storage_id=storage_id)))
            await db.flush()

        await self.write_coordinator.run(write)

    async def get(
        self,
        entry_id: str,
        *,
        scope: MemoryScope | None = None,
        include_inactive: bool = True,
    ) -> MemoryEntry | None:
        async with self.session_factory() as db:
            row = None
            if scope is not None:
                for candidate in _storage_candidates(entry_id, scope):
                    row = await db.get(CoreMemory, candidate)
                    if row is not None:
                        break
            else:
                rows = (await db.execute(select(CoreMemory))).scalars().all()
                matches = [
                    candidate
                    for candidate in rows
                    if _entry_from_row(candidate).id == str(entry_id or "").strip()
                ]
                # An unscoped public id is ambiguous once two scopes use it;
                # returning no row is safer than leaking one.
                row = matches[0] if len(matches) == 1 else None
        if row is None:
            return None
        entry = _entry_from_row(row)
        if scope is not None and not entry.scope.matches(scope):
            return None
        if entry.id != str(entry_id or "").strip():
            return None
        if not include_inactive and entry.status != "active":
            return None
        return entry

    async def delete(self, entry_id: str, *, scope: MemoryScope | None = None) -> None:
        async def write(db):
            if scope is not None:
                for candidate in _storage_candidates(entry_id, scope):
                    row = await db.get(CoreMemory, candidate)
                    if row is None:
                        continue
                    entry = _entry_from_row(row)
                    if entry.id == str(entry_id or "").strip() and entry.scope.matches(scope):
                        await db.execute(delete(CoreMemory).where(CoreMemory.id == candidate))
                    return
                return
            rows = (await db.execute(select(CoreMemory))).scalars().all()
            matches = [row for row in rows if _entry_from_row(row).id == str(entry_id or "").strip()]
            if len(matches) == 1:
                await db.execute(delete(CoreMemory).where(CoreMemory.id == matches[0].id))

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
        # them with LIKE %term% over content — every term must be present,
        # so a dreaming dedupe lookup cannot false-positive on a single
        # shared word (audit 11: the implementation was OR, silently
        # widening recall). This is intentionally simple — good enough for
        # de-duplication lookups during dreaming. FTS5 can replace this
        # later without touching the protocol.
        terms = [t for t in (query.query or "").split() if t]
        if terms:
            conditions = [CoreMemory.content.ilike(f"%{term}%") for term in terms]
            statement = statement.where(and_(*conditions))

        # Scope/status are carried in the backwards-compatible JSON envelope.
        # Do not apply the result limit at SQL level: a broad legacy query may
        # contain rows from other scopes before Python applies the exact
        # authorization filter.
        if query.work_root is not None:
            statement = statement.where(CoreMemory.work_root == str(query.work_root))
        elif query.scope is not None and query.scope.work_root:
            statement = statement.where(CoreMemory.work_root == query.scope.work_root)
        statement = statement.order_by(
            CoreMemory.confidence.desc(),
            CoreMemory.accessed_at.desc(),
        )

        async with self.session_factory() as db:
            rows = (await db.execute(statement)).scalars().all()

        hits: list[MemoryHit] = []
        for row in rows:
            entry = _entry_from_row(row)
            if not _entry_matches_query(entry, query):
                continue
            # Lightweight relevance score: fraction of query terms present.
            score = _text_relevance(entry.content, query.query)
            hits.append(MemoryHit(entry=entry, score=score, source=entry.source or "store"))
            if len(hits) >= max(1, query.limit):
                break
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
        return [
            entry
            for row in rows
            if (entry := _entry_from_row(row)).scope.work_root == work_root
            or str(entry.metadata.get("work_root") or "") == work_root
        ]

    async def list_for_scope(
        self,
        scope: MemoryScope,
        *,
        statuses: list[str] | None = None,
    ) -> list[MemoryEntry]:
        """Return rows in one exact scope, including inactive rows for audit."""

        query = MemoryQuery(
            query="",
            limit=10_000,
            scope=scope,
            statuses=list(statuses or ["active", "candidate", "superseded", "forgotten", "suppressed", "invalid"]),  # type: ignore[arg-type]
            include_candidates=True,
            include_teaching_hints=True,
        )
        result = await self.search(query)
        return [hit.entry for hit in result.hits]

    async def is_source_suppressed(self, scope: MemoryScope, source: str) -> bool:
        source = str(source or "").strip()
        if not source:
            return False
        entries = await self.list_for_scope(scope)
        return any(
            entry.status in {"forgotten", "suppressed"}
            and (
                entry.source == source
                or source in {str(item.get("id") or item.get("source_id") or "") for item in entry.source_refs if isinstance(item, dict)}
                or source in {str(item) for item in entry.metadata.get("source_refs", []) if item}
            )
            for entry in entries
        )

    async def suppress_source(self, scope: MemoryScope, source: str, *, reason: str = "") -> int:
        source = str(source or "").strip()
        if not source:
            return 0
        entries = await self.list_for_scope(scope)
        changed = 0
        for entry in entries:
            if entry.status in {"forgotten", "suppressed"}:
                continue
            refs = {str(item.get("id") or item.get("source_id") or "") for item in entry.source_refs if isinstance(item, dict)}
            refs.update(str(item) for item in entry.metadata.get("source_refs", []) if item)
            if entry.source != source and source not in refs:
                continue
            entry.status = "suppressed"
            entry.version += 1
            entry.metadata["suppression_reason"] = reason
            await self.add(entry)
            changed += 1
        return changed

    async def touch(self, entry_id: str, *, scope: MemoryScope | None = None) -> None:
        """Bump access timestamp/count for a memory (decay bookkeeping)."""
        async def write(db):
            row = None
            if scope is not None:
                for candidate in _storage_candidates(entry_id, scope):
                    row = await db.get(CoreMemory, candidate)
                    if row is not None:
                        break
            else:
                rows = (await db.execute(select(CoreMemory))).scalars().all()
                matches = [item for item in rows if _entry_from_row(item).id == str(entry_id or "").strip()]
                row = matches[0] if len(matches) == 1 else None
            if row is not None and _entry_from_row(row).id == str(entry_id or "").strip() and (
                scope is None or _entry_from_row(row).scope.matches(scope)
            ):
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
        self._suppressed_sources: dict[str, set[str]] = {}

    async def add(self, entry: MemoryEntry) -> None:
        if not entry.id:
            entry.id = uuid.uuid4().hex
        public_id = str(entry.id).strip()
        # Keep the in-memory fallback's ownership semantics aligned with the
        # SQL store: callers may continue editing their object after a write
        # without mutating the authoritative row behind the service cache.
        storage_id = _storage_id(public_id, entry.scope)
        existing_storage_id = storage_id
        existing = None
        for candidate in _storage_candidates(public_id, entry.scope):
            existing = self._entries.get(candidate)
            if existing is not None:
                existing_storage_id = candidate
                break
        if existing is not None and (
            existing.id != public_id or not existing.scope.matches(entry.scope)
        ):
            if existing_storage_id != storage_id and existing.id == public_id:
                existing = None
            else:
                raise PermissionError("Memory id belongs to another scope")
        self._entries[existing_storage_id if existing is not None else storage_id] = deepcopy(entry)

    async def get(
        self,
        entry_id: str,
        *,
        scope: MemoryScope | None = None,
        include_inactive: bool = True,
    ) -> MemoryEntry | None:
        entry = None
        if scope is not None:
            for candidate in _storage_candidates(entry_id, scope):
                entry = self._entries.get(candidate)
                if entry is not None:
                    break
        else:
            matches = [item for item in self._entries.values() if item.id == str(entry_id or "").strip()]
            entry = matches[0] if len(matches) == 1 else None
        if entry is None:
            return None
        if entry.id != str(entry_id or "").strip():
            return None
        if scope is not None and not entry.scope.matches(scope):
            return None
        if not include_inactive and entry.status != "active":
            return None
        return deepcopy(entry)

    async def delete(self, entry_id: str, *, scope: MemoryScope | None = None) -> None:
        if scope is not None:
            for candidate in _storage_candidates(entry_id, scope):
                entry = self._entries.get(candidate)
                if entry is not None:
                    if entry.id == str(entry_id or "").strip() and entry.scope.matches(scope):
                        self._entries.pop(candidate, None)
                    return
            return
        matches = [key for key, item in self._entries.items() if item.id == str(entry_id or "").strip()]
        if len(matches) == 1:
            self._entries.pop(matches[0], None)

    async def search(self, query: MemoryQuery) -> MemoryRecallResult:
        candidates = [deepcopy(entry) for entry in self._entries.values()]
        if query.kinds:
            candidates = [e for e in candidates if e.kind in query.kinds]
        if query.domains:
            candidates = [e for e in candidates if e.domain in query.domains]
        if query.layers:
            candidates = [e for e in candidates if e.layer in query.layers]
        if query.min_confidence > 0:
            candidates = [e for e in candidates if e.confidence >= query.min_confidence]
        candidates = [e for e in candidates if _entry_matches_query(e, query)]

        terms = [t for t in (query.query or "").split() if t]
        if terms:
            candidates = [e for e in candidates if all(t.lower() in e.content.lower() for t in terms)]

        candidates.sort(key=lambda e: (e.confidence, e.accessed_at), reverse=True)
        candidates = candidates[: max(1, query.limit)]

        hits = [
            MemoryHit(entry=e, score=_text_relevance(e.content, query.query), source=e.source or "memory")
            for e in candidates
        ]
        return MemoryRecallResult(query=query.query, hits=hits, total=len(hits))

    async def list_for_work_root(self, work_root: str) -> list[MemoryEntry]:
        return [
            deepcopy(e)
            for e in self._entries.values()
            if e.scope.work_root == work_root or e.metadata.get("work_root") == work_root
        ]

    async def list_for_scope(
        self,
        scope: MemoryScope,
        *,
        statuses: list[str] | None = None,
    ) -> list[MemoryEntry]:
        allowed = set(statuses or ["active", "candidate", "superseded", "forgotten", "suppressed", "invalid"])
        return [deepcopy(e) for e in self._entries.values() if e.scope.matches(scope) and e.status in allowed]

    async def is_source_suppressed(self, scope: MemoryScope, source: str) -> bool:
        source = str(source or "").strip()
        if source in self._suppressed_sources.get(scope.key, set()):
            return True
        return any(
            e.status in {"forgotten", "suppressed"}
            and (
                e.source == source
                or source in {str(item.get("id") or item.get("source_id") or "") for item in e.source_refs if isinstance(item, dict)}
            )
            for e in self._entries.values()
            if e.scope.matches(scope)
        )

    async def suppress_source(self, scope: MemoryScope, source: str, *, reason: str = "") -> int:
        source = str(source or "").strip()
        if not source:
            return 0
        self._suppressed_sources.setdefault(scope.key, set()).add(source)
        changed = 0
        for entry in list(self._entries.values()):
            if not entry.scope.matches(scope) or entry.status in {"forgotten", "suppressed"}:
                continue
            refs = {str(item.get("id") or item.get("source_id") or "") for item in entry.source_refs if isinstance(item, dict)}
            if entry.source != source and source not in refs:
                continue
            entry.status = "suppressed"
            entry.version += 1
            entry.metadata["suppression_reason"] = reason
            changed += 1
        return changed

    async def touch(self, entry_id: str, *, scope: MemoryScope | None = None) -> None:
        if scope is not None:
            entry = None
            for candidate in _storage_candidates(entry_id, scope):
                entry = self._entries.get(candidate)
                if entry is not None:
                    break
            if entry is not None and (
                entry.id != str(entry_id or "").strip() or not entry.scope.matches(scope)
            ):
                entry = None
        else:
            matches = [item for item in self._entries.values() if item.id == str(entry_id or "").strip()]
            entry = matches[0] if len(matches) == 1 else None
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


def _entry_matches_query(entry: MemoryEntry, query: MemoryQuery) -> bool:
    if query.scope is not None and not entry.scope.matches(query.scope):
        # Legacy rows may only have a work_root field.  A query explicitly
        # carrying that same compatibility root can still read them.
        if not (
            query.scope.compatibility_fallback
            and query.scope.work_root
            and (
                entry.scope.work_root == query.scope.work_root
                or str(entry.metadata.get("work_root") or "") == query.scope.work_root
            )
        ):
            return False
    if query.work_root is not None and not (
        entry.scope.work_root == str(query.work_root)
        or str(entry.metadata.get("work_root") or "") == str(query.work_root)
    ):
        return False
    statuses = set(query.statuses)
    if statuses and entry.status not in statuses:
        return False
    if not query.include_candidates and entry.status == "candidate":
        return False
    if not query.include_teaching_hints and (
        entry.kind == "teaching_hint" or entry.origin == "teaching_hint"
    ):
        return False
    for key, expected in query.metadata_filter.items():
        if entry.metadata.get(key) != expected:
            return False
    return True
