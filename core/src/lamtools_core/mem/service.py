"""Authoritative scoped memory service.

``MemoryStore`` is a persistence primitive.  This module owns the policy that
turns it into a safe long-term memory API: trusted scope checks, explicit vs
inferred origin, versioned correction/forget operations, source suppression,
and bounded scoped reads.  The service intentionally has no model/network
dependency, so callers can keep those waits outside database write
transactions.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Iterable, Mapping
import uuid

from . import (
    MemoryEntry,
    MemoryQuery,
    MemoryRecallResult,
    MemoryScope,
    MemoryStoreProtocol,
)

__all__ = [
    "MemoryAuthorizationError",
    "MemoryConflictError",
    "MemoryAuditEvent",
    "MemoryService",
]


class MemoryAuthorizationError(PermissionError):
    """Raised when a caller attempts a cross-scope memory operation."""


class MemoryConflictError(RuntimeError):
    """Raised when an expected memory version no longer matches."""


@dataclass(frozen=True, slots=True)
class MemoryAuditEvent:
    """Small immutable audit record returned by correction/forget operations."""

    id: str
    memory_id: str
    scope_key: str
    action: str
    version: int
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""
    reason: str = ""
    previous_content_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "memory_id": self.memory_id,
            "scope_key": self.scope_key,
            "action": self.action,
            "version": self.version,
            "at": self.at.isoformat(),
            "source": self.source,
            "reason": self.reason,
            "previous_content_digest": self.previous_content_digest,
        }


def _clean_content(value: Any) -> str:
    content = str(value or "").strip()
    if not content:
        raise ValueError("memory content is required")
    if len(content) > 16_000:
        raise ValueError("memory content is too long")
    return content


def _source_id(source: Any, source_refs: Iterable[Mapping[str, Any]] | None = None) -> str:
    value = str(source or "").strip()
    if value:
        return value
    for ref in source_refs or ():
        if isinstance(ref, Mapping):
            value = str(ref.get("id") or ref.get("source_id") or ref.get("sourceId") or "").strip()
            if value:
                return value
    return ""


def _canonical_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    session_id: str = "",
    thread_id: str = "",
    source_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result = deepcopy(dict(metadata or {}))
    canonical = str(thread_id or session_id or result.get("thread_id") or result.get("session_id") or "").strip()
    if canonical:
        # Both keys are retained for old readers, but they always agree.
        result["thread_id"] = canonical
        result["session_id"] = canonical
    if source_refs:
        result["source_refs"] = deepcopy(source_refs)
    return result


def _scope_or_raise(scope: MemoryScope | None) -> MemoryScope:
    if not isinstance(scope, MemoryScope):
        raise MemoryAuthorizationError("A trusted MemoryScope is required")
    if not scope.user_id.strip() or not scope.environment_id.strip():
        raise MemoryAuthorizationError("MemoryScope principal is incomplete")
    return scope


class MemoryService:
    """Policy façade over one shared ``MemoryStoreProtocol`` instance.

    The service is intentionally usable with the existing in-memory and
    SQLAlchemy stores.  It never accepts a scope from an arbitrary model
    result; the host must pass the trusted runtime scope explicitly.
    """

    def __init__(
        self,
        store: MemoryStoreProtocol,
        *,
        default_limit: int = 8,
        max_limit: int = 50,
    ) -> None:
        self.store = store
        self.default_limit = max(1, int(default_limit))
        self.max_limit = max(self.default_limit, int(max_limit))
        self._cache: dict[tuple[Any, ...], MemoryRecallResult] = {}
        self._audit: list[MemoryAuditEvent] = []

    async def query(
        self,
        scope: MemoryScope,
        query: str = "",
        *,
        kinds: list[str] | None = None,
        domains: list[str] | None = None,
        limit: int | None = None,
        min_confidence: float = 0.0,
        authorized_scopes: Iterable[MemoryScope] | None = None,
        include_candidates: bool = False,
        include_teaching_hints: bool = False,
        work_root: str | None = None,
    ) -> MemoryRecallResult:
        """Read only active entries inside the exact authorized scope(s).

        ``authorized_scopes`` is host-derived (for example a Study library
        plus one node), never model-provided.  If omitted, only ``scope`` is
        read.  Cache entries contain the full scope key and are invalidated on
        every mutating operation.
        """

        principal = _scope_or_raise(scope)
        target_scopes = [principal]
        for candidate in authorized_scopes or ():
            candidate = _scope_or_raise(candidate)
            if candidate.key not in {item.key for item in target_scopes}:
                target_scopes.append(candidate)
        clean_limit = self._limit(limit)
        cache_key = (
            tuple(item.key for item in target_scopes),
            str(query or ""),
            tuple(kinds or ()),
            tuple(domains or ()),
            clean_limit,
            float(min_confidence),
            bool(include_candidates),
            bool(include_teaching_hints),
            str(work_root) if work_root is not None else None,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return deepcopy(cached)

        hits = []
        for target in target_scopes:
            result = await self.store.search(
                MemoryQuery(
                    query=str(query or ""),
                    kinds=list(kinds or []),
                    domains=list(domains or []),
                    limit=clean_limit,
                    min_confidence=float(min_confidence),
                    scope=target,
                    work_root=work_root,
                    statuses=["active"],
                    include_candidates=False,
                    include_teaching_hints=include_teaching_hints,
                )
            )
            hits.extend(result.hits)
        # A candidate/teaching read is explicit and still cannot return
        # forgotten/suppressed rows.  The store status filter above remains
        # active; candidate reads use a second bounded query only when asked.
        if include_candidates:
            for target in target_scopes:
                result = await self.store.search(
                    MemoryQuery(
                        query=str(query or ""),
                        kinds=list(kinds or []),
                        domains=list(domains or []),
                        limit=clean_limit,
                        min_confidence=float(min_confidence),
                        scope=target,
                        work_root=work_root,
                        statuses=["candidate"],
                        include_candidates=True,
                        include_teaching_hints=include_teaching_hints,
                    )
                )
                hits.extend(result.hits)
        hits.sort(key=lambda item: (item.entry.confidence, item.entry.accessed_at), reverse=True)
        result = MemoryRecallResult(query=str(query or ""), hits=hits[:clean_limit], total=min(len(hits), clean_limit))
        self._cache[cache_key] = deepcopy(result)
        return result

    async def read(self, scope: MemoryScope, memory_id: str, *, include_inactive: bool = False) -> MemoryEntry | None:
        principal = _scope_or_raise(scope)
        getter = getattr(self.store, "get", None)
        if not callable(getter):
            return None
        entry = await getter(str(memory_id or ""), scope=principal, include_inactive=include_inactive)
        if entry is None or (not include_inactive and entry.status != "active"):
            return None
        if entry.status in {"forgotten", "suppressed", "superseded", "invalid"} and not include_inactive:
            return None
        return entry

    async def remember_explicit(
        self,
        scope: MemoryScope,
        content: str,
        *,
        kind: str = "preference",
        domain: str = "",
        source: str = "",
        source_metadata: Mapping[str, Any] | None = None,
        source_refs: Iterable[Mapping[str, Any]] | None = None,
        metadata: Mapping[str, Any] | None = None,
        session_id: str = "",
        thread_id: str = "",
        memory_id: str = "",
        locked: bool = True,
        replace_id: str = "",
    ) -> MemoryEntry:
        """Persist a user-authorized claim synchronously.

        Exact duplicate explicit claims are updated in place (with a version
        bump) so repeated “remember this” commands are idempotent.  A caller
        must provide ``replace_id`` to supersede a conflicting claim; no
        inferred or cross-scope row is silently replaced.
        """

        principal = _scope_or_raise(scope)
        text = _clean_content(content)
        kind = str(kind or "preference").strip().lower() or "preference"
        refs = [dict(item) for item in (source_refs or ()) if isinstance(item, Mapping)]
        source_id = _source_id(source, refs)
        if await self._source_is_suppressed(principal, source_id):
            raise MemoryAuthorizationError("Memory source is suppressed")
        existing = await self._find_exact(principal, text, kind)
        if existing is not None:
            existing.content = text
            existing.version = max(1, int(existing.version or 1)) + 1
            existing.status = "active"
            existing.origin = "explicit"
            existing.locked = bool(locked)
            existing.source = source_id or existing.source
            existing.source_metadata = deepcopy(dict(source_metadata or existing.source_metadata))
            existing.source_refs = refs or existing.source_refs
            existing.metadata = _canonical_metadata(
                {**existing.metadata, **dict(metadata or {})},
                session_id=session_id,
                thread_id=thread_id,
                source_refs=existing.source_refs,
            )
            await self.store.add(existing)
            self._record_audit(existing, "remember", source=source_id)
            self._invalidate(principal)
            return existing

        if replace_id:
            old = await self._get_scoped(principal, replace_id, include_inactive=False)
            if old is None:
                raise MemoryAuthorizationError("Memory to replace is not available")
            old.status = "superseded"
            old.version += 1
            old.metadata["superseded_by"] = memory_id or "pending"
            await self.store.add(old)

        entry = MemoryEntry(
            id=str(memory_id or "").strip() or f"memory_{uuid.uuid4().hex}",
            kind=kind,
            content=text,
            domain=str(domain or "").strip(),
            source=source_id,
            layer="permanent",
            confidence=1.0,
            metadata=_canonical_metadata(metadata, session_id=session_id, thread_id=thread_id, source_refs=refs),
            scope=principal,
            status="active",
            version=1,
            origin="explicit",
            source_metadata=deepcopy(dict(source_metadata or {})),
            source_refs=refs,
            locked=bool(locked),
        )
        await self.store.add(entry)
        self._record_audit(entry, "remember", source=source_id)
        self._invalidate(principal)
        return entry

    async def remember_teaching_hint(
        self,
        scope: MemoryScope,
        content: str,
        *,
        source: str = "",
        source_metadata: Mapping[str, Any] | None = None,
        source_refs: Iterable[Mapping[str, Any]] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> MemoryEntry:
        """Store knowledge-level teaching guidance, not personal memory."""

        entry = await self.remember_explicit(
            scope,
            content,
            kind="teaching_hint",
            source=source,
            source_metadata=source_metadata,
            source_refs=source_refs,
            metadata=metadata,
            locked=False,
        )
        entry.origin = "teaching_hint"
        await self.store.add(entry)
        self._invalidate(scope)
        return entry

    async def submit_signal(
        self,
        scope: MemoryScope,
        *,
        event_id: str,
        content: str,
        kind: str = "observation",
        source: str = "",
        source_refs: Iterable[Mapping[str, Any]] | None = None,
        source_metadata: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> MemoryEntry:
        """Persist an observed event as a candidate for batch Dreaming."""

        principal = _scope_or_raise(scope)
        text = _clean_content(content)
        normalized_kind = str(kind or "observation").strip().lower() or "observation"
        if normalized_kind in {"ability", "global_ability", "mastery", "score", "grade", "exam_result"}:
            # A single mark/mistake cannot become a durable ability label.
            normalized_kind = "observation"
        refs = [dict(item) for item in (source_refs or ()) if isinstance(item, Mapping)]
        if event_id:
            refs.append({"id": str(event_id), "type": "event"})
        source_id = _source_id(source, refs) or f"event#{event_id}"
        if await self._source_is_suppressed(principal, source_id) or await self._source_is_suppressed(principal, str(event_id)):
            # Return a non-active tombstone rather than allowing replay to
            # create a new candidate after an explicit forget.
            return MemoryEntry(
                id=f"suppressed_{hashlib.sha256((principal.key + source_id).encode()).hexdigest()[:24]}",
                kind=normalized_kind,
                content=text,
                source=source_id,
                scope=principal,
                status="suppressed",
                origin="observed",
            )
        entry = MemoryEntry(
            id=f"candidate_{hashlib.sha256((principal.key + str(event_id)).encode()).hexdigest()[:32]}",
            kind=normalized_kind,
            content=text,
            source=source_id,
            layer="hot",
            confidence=0.0,
            metadata={**_canonical_metadata(metadata, source_refs=refs), "event_id": str(event_id)},
            scope=principal,
            status="candidate",
            origin="observed",
            source_metadata=deepcopy(dict(source_metadata or {})),
            source_refs=refs,
            locked=False,
        )
        await self.store.add(entry)
        self._invalidate(principal)
        return entry

    async def correct(
        self,
        scope: MemoryScope,
        memory_id: str,
        content: str,
        *,
        expected_version: int | None = None,
        source: str = "",
        source_metadata: Mapping[str, Any] | None = None,
        source_refs: Iterable[Mapping[str, Any]] | None = None,
        reason: str = "user correction",
    ) -> MemoryEntry:
        principal = _scope_or_raise(scope)
        entry = await self._get_scoped(principal, memory_id, include_inactive=False)
        if entry is None:
            raise MemoryAuthorizationError("Memory is not available in this scope")
        if expected_version is not None and int(expected_version) != entry.version:
            raise MemoryConflictError(f"Memory version conflict: {memory_id}")
        previous = entry.content
        entry.content = _clean_content(content)
        entry.version = max(1, int(entry.version or 1)) + 1
        entry.status = "active"
        entry.origin = "explicit"
        entry.locked = True
        if source:
            entry.source = str(source).strip()
        if source_metadata is not None:
            entry.source_metadata = deepcopy(dict(source_metadata))
        if source_refs is not None:
            entry.source_refs = [dict(item) for item in source_refs if isinstance(item, Mapping)]
        entry.metadata["corrected_at"] = datetime.now(timezone.utc).isoformat()
        entry.metadata["correction_reason"] = str(reason or "user correction")
        entry.metadata.setdefault("audit", []).append({
            "action": "correct",
            "version": entry.version,
            "previous_content_digest": _digest(previous),
            "at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        })
        await self.store.add(entry)
        self._record_audit(entry, "correct", source=entry.source, reason=reason, previous=previous)
        self._invalidate(principal)
        return entry

    async def forget(
        self,
        scope: MemoryScope,
        memory_id: str | None = None,
        *,
        content: str | None = None,
        source: str = "",
        reason: str = "user forget",
    ) -> int:
        """Forget rows and leave a suppression marker against source replay."""

        principal = _scope_or_raise(scope)
        selected: list[MemoryEntry] = []
        if memory_id:
            entry = await self._get_scoped(principal, memory_id, include_inactive=False)
            if entry is not None:
                selected.append(entry)
        elif content:
            result = await self.query(principal, content, limit=self.max_limit, include_teaching_hints=True)
            selected.extend(hit.entry for hit in result.hits if hit.entry.content.casefold() == str(content).strip().casefold())
        elif source:
            all_rows = await self._all_scope_rows(principal)
            selected.extend(item for item in all_rows if item.source == str(source).strip())
        source_ids: set[str] = {str(source or "").strip()} if source else set()
        for entry in selected:
            if entry.status in {"forgotten", "suppressed"}:
                continue
            source_ids.add(entry.source)
            entry.status = "forgotten"
            entry.version = max(1, int(entry.version or 1)) + 1
            entry.metadata["forgotten_at"] = datetime.now(timezone.utc).isoformat()
            entry.metadata["forget_reason"] = str(reason or "user forget")
            entry.metadata.setdefault("audit", []).append({
                "action": "forget",
                "version": entry.version,
                "at": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
            })
            await self.store.add(entry)
            self._record_audit(entry, "forget", source=entry.source, reason=reason, previous=entry.content)
        for source_id in source_ids:
            if source_id:
                await self._suppress_source(principal, source_id, reason=reason)
        # Keep the old project-file export from re-injecting a forgotten fact.
        # Study scopes have no project file and intentionally skip this path.
        if principal.work_root and not principal.library_id:
            try:
                from .memory_file import suppress_memory_md_entries

                for entry in selected:
                    suppress_memory_md_entries(
                        Path(principal.work_root) / "MEMORY.md",
                        source=entry.source,
                        content=entry.content,
                    )
            except (OSError, ValueError):
                # Structured forget remains authoritative if the compatibility
                # export is unavailable or malformed.
                pass
        self._invalidate(principal)
        return len(selected)

    async def suppress(self, scope: MemoryScope, source: str, *, reason: str = "user suppression") -> int:
        principal = _scope_or_raise(scope)
        changed = await self._suppress_source(principal, source, reason=reason)
        self._invalidate(principal)
        return changed

    async def audit(self, scope: MemoryScope, memory_id: str | None = None) -> list[MemoryAuditEvent]:
        principal = _scope_or_raise(scope)
        events = [item for item in self._audit if item.scope_key == principal.key]
        if memory_id:
            events = [item for item in events if item.memory_id == memory_id]
        return list(events)

    # Compatibility aliases used by early callers and the v2 contract.
    remember = remember_explicit
    recall = query
    correct_memory = correct
    forget_memory = forget

    async def _find_exact(self, scope: MemoryScope, content: str, kind: str) -> MemoryEntry | None:
        result = await self.store.search(
            MemoryQuery(
                query="",
                kinds=[kind],
                limit=self.max_limit,
                scope=scope,
                statuses=["active"],
                include_teaching_hints=True,
            )
        )
        target = content.casefold()
        for hit in result.hits:
            if hit.entry.content.casefold() == target:
                return hit.entry
        return None

    async def _get_scoped(self, scope: MemoryScope, memory_id: str, *, include_inactive: bool) -> MemoryEntry | None:
        getter = getattr(self.store, "get", None)
        if not callable(getter):
            return None
        return await getter(str(memory_id or ""), scope=scope, include_inactive=include_inactive)

    async def _all_scope_rows(self, scope: MemoryScope) -> list[MemoryEntry]:
        listing = getattr(self.store, "list_for_scope", None)
        if callable(listing):
            return list(await listing(scope))
        result = await self.store.search(
            MemoryQuery(
                query="",
                limit=self.max_limit * 100,
                scope=scope,
                statuses=["active", "candidate", "superseded", "forgotten", "suppressed", "invalid"],  # type: ignore[arg-type]
                include_candidates=True,
                include_teaching_hints=True,
            )
        )
        return [hit.entry for hit in result.hits]

    async def _source_is_suppressed(self, scope: MemoryScope, source: str) -> bool:
        if not source:
            return False
        checker = getattr(self.store, "is_source_suppressed", None)
        if callable(checker):
            return bool(await checker(scope, source))
        return False

    async def _suppress_source(self, scope: MemoryScope, source: str, *, reason: str) -> int:
        source = str(source or "").strip()
        if not source:
            return 0
        suppressor = getattr(self.store, "suppress_source", None)
        if callable(suppressor):
            changed = int(await suppressor(scope, source, reason=reason))
        else:
            changed = 0
        # Persist a tombstone when there was no existing row.  This is what
        # prevents a replayed candidate from resurrecting a forgotten source.
        if not await self._source_is_suppressed(scope, source):
            tombstone = MemoryEntry(
                id=f"suppression_{hashlib.sha256((scope.key + source).encode()).hexdigest()[:32]}",
                kind="suppression",
                content="",
                source=source,
                scope=scope,
                status="suppressed",
                version=1,
                origin="explicit",
                metadata={"suppression_reason": reason},
                locked=True,
            )
            await self.store.add(tombstone)
            changed += 1
        return changed

    def _record_audit(
        self,
        entry: MemoryEntry,
        action: str,
        *,
        source: str = "",
        reason: str = "",
        previous: str = "",
    ) -> None:
        self._audit.append(
            MemoryAuditEvent(
                id=f"memory_audit_{uuid.uuid4().hex}",
                memory_id=entry.id,
                scope_key=entry.scope.key,
                action=action,
                version=entry.version,
                source=source,
                reason=reason,
                previous_content_digest=_digest(previous),
            )
        )

    def _invalidate(self, scope: MemoryScope) -> None:
        key = scope.key
        self._cache = {
            cache_key: value
            for cache_key, value in self._cache.items()
            if key not in cache_key[0]
        }

    def _limit(self, value: int | None) -> int:
        if value is None:
            return self.default_limit
        return min(self.max_limit, max(1, int(value)))


def _digest(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest() if value else ""
