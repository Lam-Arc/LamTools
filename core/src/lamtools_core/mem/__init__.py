"""Memory protocol types and interfaces.

The memory package is deliberately small, but it is a security boundary.  A
memory row is never just a string: it carries the trusted principal and
resource scope that authorised the write, the source/origin of the claim, and
an explicit lifecycle status.  ``MEMORY.md`` remains a compatibility export;
the structured row is the authoritative representation used by the service.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping, Protocol, runtime_checkable

from lamtools_core.prompt import PromptPart, estimate_tokens

MemoryLayer = Literal["hot", "warm", "cold", "permanent"]
MemoryStatus = Literal[
    "candidate",
    "active",
    "superseded",
    "forgotten",
    "suppressed",
    "invalid",
]
MemoryOrigin = Literal["explicit", "observed", "inferred", "legacy", "teaching_hint"]


@dataclass(frozen=True, slots=True)
class MemoryScope:
    """Trusted boundary for a memory record.

    ``user_id`` and ``environment_id`` are always part of the identity.  A
    project and/or Study library may further narrow it; ``work_root`` is kept
    solely as a compatibility discriminator for pre-v2 project memories.
    Scope values must come from host/runtime metadata.  Model or user payloads
    must not be used to construct a scope at an authorization boundary.
    """

    user_id: str = "local-user"
    environment_id: str = "local-environment"
    project_id: str | None = None
    library_id: str | None = None
    # These optional fields align the Python contract with the Study/domain
    # contract.  They do not widen a query: matching is exact unless the
    # MemoryService is explicitly given a list of authorised child scopes.
    kind: Literal["global", "mode", "resource"] = "global"
    mode: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    work_root: str = ""
    compatibility_fallback: bool = False

    def __post_init__(self) -> None:
        for name in ("user_id", "environment_id", "project_id", "library_id", "mode", "resource_type", "resource_id", "work_root"):
            value = getattr(self, name)
            if value is not None and any(ord(char) < 32 for char in str(value)):
                raise ValueError(f"Memory scope {name} contains a control character")
        if self.kind not in {"global", "mode", "resource"}:
            raise ValueError("Memory scope kind must be global, mode, or resource")
        if self.kind == "global" and any(value is not None for value in (self.mode, self.resource_type, self.resource_id)):
            raise ValueError("global memory scope cannot carry mode or resource fields")
        if self.kind == "mode" and (not self.mode or self.resource_type is not None or self.resource_id is not None):
            raise ValueError("mode memory scope requires only mode")
        if self.kind == "resource" and (not self.mode or not self.resource_type or not self.resource_id):
            raise ValueError("resource memory scope requires mode, resource_type, and resource_id")

    @classmethod
    def local_legacy(cls, work_root: str | None = None) -> "MemoryScope":
        """Return an explicit compatibility scope for old local callers.

        A non-empty work root is included in the key, so two legacy projects
        cannot deduplicate against one another.  It is intentionally *not* a
        Study scope; projectless Study callers must provide a library scope or
        use the local Study compatibility identity at their host boundary.
        """

        return cls(work_root=str(work_root or "").strip(), compatibility_fallback=True)

    @classmethod
    def for_project(
        cls,
        user_id: str,
        environment_id: str,
        project_id: str,
        *,
        work_root: str | None = None,
        mode: str | None = None,
    ) -> "MemoryScope":
        return cls(
            user_id=str(user_id).strip(),
            environment_id=str(environment_id).strip(),
            project_id=str(project_id).strip(),
            kind="resource" if mode else "global",
            mode=mode,
            resource_type="project" if mode else None,
            resource_id=str(project_id).strip() if mode else None,
            work_root=str(work_root or "").strip(),
        )

    @classmethod
    def for_study(
        cls,
        user_id: str,
        environment_id: str,
        library_id: str,
        *,
        resource_type: str | None = None,
        resource_id: str | None = None,
        mode: str = "study",
    ) -> "MemoryScope":
        if resource_type or resource_id:
            if not resource_type or not resource_id:
                raise ValueError("Study resource scope requires both resource_type and resource_id")
            return cls(
                user_id=str(user_id).strip(),
                environment_id=str(environment_id).strip(),
                library_id=str(library_id).strip(),
                kind="resource",
                mode=str(mode).strip() or "study",
                resource_type=str(resource_type).strip(),
                resource_id=str(resource_id).strip(),
            )
        return cls(
            user_id=str(user_id).strip(),
            environment_id=str(environment_id).strip(),
            library_id=str(library_id).strip(),
            kind="mode",
            mode=str(mode).strip() or "study",
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "MemoryScope":
        """Decode a stored scope, falling back only for legacy rows."""

        if not isinstance(value, Mapping):
            return cls.local_legacy()
        return cls(
            user_id=str(value.get("user_id") or value.get("userId") or "local-user"),
            environment_id=str(value.get("environment_id") or value.get("environmentId") or value.get("env_id") or "local-environment"),
            project_id=_optional_text(value.get("project_id", value.get("projectId"))),
            library_id=_optional_text(value.get("library_id", value.get("libraryId"))),
            kind=str(value.get("kind") or "global"),  # type: ignore[arg-type]
            mode=_optional_text(value.get("mode")),
            resource_type=_optional_text(value.get("resource_type", value.get("resourceType"))),
            resource_id=_optional_text(value.get("resource_id", value.get("resourceId"))),
            work_root=str(value.get("work_root") or value.get("workRoot") or ""),
            compatibility_fallback=bool(value.get("compatibility_fallback", value.get("compatibilityFallback", False))),
        )

    @property
    def env_id(self) -> str:
        return self.environment_id

    @property
    def work_environment_id(self) -> str:
        return self.environment_id

    @property
    def key(self) -> str:
        """Stable, non-ambiguous key suitable for cache and dedupe keys."""

        fields = (
            self.user_id,
            self.environment_id,
            self.project_id or "",
            self.library_id or "",
            self.kind,
            self.mode or "",
            self.resource_type or "",
            self.resource_id or "",
            self.work_root,
        )
        return "\x1f".join(fields)

    @property
    def scope_key(self) -> str:
        return self.key

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "environment_id": self.environment_id,
            "project_id": self.project_id,
            "library_id": self.library_id,
            "kind": self.kind,
            "mode": self.mode,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "work_root": self.work_root,
            "compatibility_fallback": self.compatibility_fallback,
        }

    def matches(self, other: "MemoryScope") -> bool:
        return self.key == other.key


def _optional_text(value: Any) -> str | None:
    value = str(value).strip() if value is not None else ""
    return value or None


@dataclass
class MemoryEntry:
    id: str
    kind: str
    content: str
    domain: str = ""
    source: str = ""
    layer: MemoryLayer = "warm"
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    accessed_at: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    scope: MemoryScope = field(default_factory=MemoryScope.local_legacy)
    status: MemoryStatus = "active"
    version: int = 1
    origin: MemoryOrigin = "inferred"
    source_metadata: dict[str, Any] = field(default_factory=dict)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    locked: bool = False

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "content": self.content,
            "domain": self.domain,
            "source": self.source,
            "layer": self.layer,
            "confidence": self.confidence,
            "score": self.score,
            "created_at": self.created_at.isoformat(),
            "accessed_at": self.accessed_at.isoformat(),
            "access_count": self.access_count,
            "scope": self.scope.to_dict(),
            "status": self.status,
            "version": self.version,
            "origin": self.origin,
            "locked": self.locked,
        }
        if self.metadata:
            d["metadata"] = self.metadata
        if self.source_metadata:
            d["source_metadata"] = self.source_metadata
        if self.source_refs:
            d["source_refs"] = self.source_refs
        return d

    @property
    def revision(self) -> int:
        """Alias used by the v2 contract; ``version`` is the storage name."""

        return self.version


@dataclass
class MemoryQuery:
    query: str
    kinds: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    layers: list[MemoryLayer] = field(default_factory=list)
    limit: int = 10
    min_score: float = 0.0
    min_confidence: float = 0.0
    metadata_filter: dict[str, Any] = field(default_factory=dict)
    scope: MemoryScope | None = None
    work_root: str | None = None
    statuses: list[MemoryStatus] = field(default_factory=lambda: ["active"])
    include_candidates: bool = False
    include_teaching_hints: bool = False

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"query": self.query, "limit": self.limit}
        if self.kinds:
            d["kinds"] = self.kinds
        if self.domains:
            d["domains"] = self.domains
        if self.layers:
            d["layers"] = self.layers
        if self.min_score > 0:
            d["min_score"] = self.min_score
        if self.min_confidence > 0:
            d["min_confidence"] = self.min_confidence
        if self.metadata_filter:
            d["metadata_filter"] = self.metadata_filter
        if self.scope is not None:
            d["scope"] = self.scope.to_dict()
        if self.work_root is not None:
            d["work_root"] = self.work_root
        if self.statuses != ["active"]:
            d["statuses"] = list(self.statuses)
        if self.include_candidates:
            d["include_candidates"] = True
        if self.include_teaching_hints:
            d["include_teaching_hints"] = True
        return d


@dataclass
class MemoryHit:
    entry: MemoryEntry
    score: float = 0.0
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry": self.entry.to_dict(),
            "score": self.score,
            "source": self.source,
        }


@dataclass
class MemoryRecallResult:
    query: str
    hits: list[MemoryHit] = field(default_factory=list)
    total: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "hits": [h.to_dict() for h in self.hits],
            "total": self.total,
        }


@runtime_checkable
class MemoryStoreProtocol(Protocol):
    async def add(self, entry: MemoryEntry) -> None: ...
    async def get(
        self,
        entry_id: str,
        *,
        scope: MemoryScope | None = None,
        include_inactive: bool = True,
    ) -> MemoryEntry | None: ...
    async def delete(self, entry_id: str, *, scope: MemoryScope | None = None) -> None: ...
    async def search(self, query: MemoryQuery) -> MemoryRecallResult: ...


@runtime_checkable
class MemoryAdapterProtocol(Protocol):
    async def recall(self, query: MemoryQuery) -> MemoryRecallResult: ...


@runtime_checkable
class MemoryBudgetProtocol(Protocol):
    def fit(self, result: MemoryRecallResult, max_tokens: int) -> MemoryRecallResult: ...


MemoryStore = MemoryStoreProtocol
MemoryAdapter = MemoryAdapterProtocol
MemoryBudget = MemoryBudgetProtocol


class SimpleMemoryBudget:
    """Dependency-free memory budgeter using approximate token counts."""

    def fit(self, result: MemoryRecallResult, max_tokens: int) -> MemoryRecallResult:
        if max_tokens <= 0:
            return MemoryRecallResult(query=result.query, hits=[], total=result.total)

        kept: list[MemoryHit] = []
        remaining = max_tokens
        for hit in result.hits:
            cost = estimate_tokens(hit.entry.content)
            if cost <= remaining:
                kept.append(hit)
                remaining -= cost
        return MemoryRecallResult(query=result.query, hits=kept, total=result.total)


def format_hits_as_text(hits: list[MemoryHit]) -> str:
    """Format memory hits as neutral text lines for prompt assembly."""
    lines: list[str] = []
    for hit in hits:
        entry = hit.entry
        prefix_parts = [entry.kind]
        if entry.domain:
            prefix_parts.append(entry.domain)
        prefix = " / ".join(prefix_parts)
        lines.append(f"[{prefix}] {entry.content}")
    return "\n".join(lines)


def hits_to_prompt_parts(
    hits: list[MemoryHit],
    *,
    key_prefix: str = "memory",
    priority: int = 60,
    role: str = "system",
) -> list[PromptPart]:
    """Convert memory hits to generic PromptPart objects."""
    parts: list[PromptPart] = []
    for index, hit in enumerate(hits):
        entry = hit.entry
        parts.append(PromptPart(
            key=f"{key_prefix}:{entry.id or index}",
            kind="memory",
            content=entry.content,
            role=role,  # type: ignore[arg-type]
            priority=priority,
            metadata={
                "memory_id": entry.id,
                "kind": entry.kind,
                "domain": entry.domain,
                "layer": entry.layer,
                "score": hit.score,
                "source": hit.source,
            },
        ))
    return parts


def format_session_memory_summary(summary: dict[str, Any]) -> str:
    """Format lightweight session memory stats for prompt context."""
    indexed_outputs = int(summary.get("indexed_tool_outputs") or 0)
    recent_errors = summary.get("recent_error_signatures") or []
    if not isinstance(recent_errors, list):
        recent_errors = [recent_errors]
    return f"[Session Memory] {indexed_outputs} indexed outputs, recent errors: {recent_errors}"


__all__ = [
    "MemoryLayer",
    "MemoryStatus",
    "MemoryOrigin",
    "MemoryScope",
    "MemoryEntry",
    "MemoryQuery",
    "MemoryHit",
    "MemoryRecallResult",
    "MemoryStore",
    "MemoryStoreProtocol",
    "MemoryAdapter",
    "MemoryAdapterProtocol",
    "MemoryBudget",
    "MemoryBudgetProtocol",
    "SimpleMemoryBudget",
    "format_hits_as_text",
    "hits_to_prompt_parts",
    "format_session_memory_summary",
]

# Imported last to keep the lightweight protocol types importable by the
# persistence adapters without creating a circular import during startup.
from .service import (  # noqa: E402  (intentional late import)
    MemoryAuditEvent,
    MemoryAuthorizationError,
    MemoryConflictError,
    MemoryService,
)

__all__ += [
    "MemoryAuditEvent",
    "MemoryAuthorizationError",
    "MemoryConflictError",
    "MemoryService",
]
