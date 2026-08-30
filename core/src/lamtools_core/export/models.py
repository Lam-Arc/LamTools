from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .handoff import HANDOFF_SCHEMA


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ExportEnvelope:
    schema: str
    version: int
    exported_at: str
    thread_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TranscriptEntry:
    timestamp: str
    role: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class TranscriptExport(ExportEnvelope):
    entries: tuple[TranscriptEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {**super().to_dict(), "entries": [entry.to_dict() for entry in self.entries]}


@dataclass(frozen=True)
class ContextHandoffExport:
    """The only public Handoff envelope.

    Keep this shape intentionally boring: another Agent must be able to read
    the file without knowing LamTools' database or runtime identifiers.
    """

    context: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    schema: str = HANDOFF_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "context": [dict(item) for item in self.context]}


@dataclass(frozen=True)
class FullArchiveFile:
    """A binary member carried by a Full Archive ZIP.

    The bytes are kept out of the JSON manifests; ``to_dict`` only exposes
    the portable archive path and size.  This keeps the logical export
    inspectable while allowing the ZIP serializer to add the real file.
    """

    path: str
    content: bytes = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size": len(self.content)}


@dataclass(frozen=True)
class FullConversationExport(ExportEnvelope):
    session: dict[str, Any] = field(default_factory=dict)
    snapshots: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    snapshot_items: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    events: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    history: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    runtime: dict[str, Any] = field(default_factory=dict)
    handoff_contexts: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    checkpoints: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    legacy_checkpoints: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    legacy_checkpoint_payloads: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    checkpoint_materialized: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    checkpoint_session_messages: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    checkpoint_session_history: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    checkpoint_attachment_refs: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    checkpoint_blob_refs: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    workspace_manifests: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    checkpoint_blobs: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    attachments: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    goals: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    memories: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    arrange_jobs: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    arrange_occurrences: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    arrange_signals: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    restore_operations: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    projects: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    handoff: dict[str, Any] | None = None
    archive_files: tuple[FullArchiveFile, ...] = field(default_factory=tuple, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            **super().to_dict(),
            "session": self.session,
            "snapshots": list(self.snapshots),
            "snapshot_items": list(self.snapshot_items),
            "events": list(self.events),
            "history": list(self.history),
            "runtime": self.runtime,
            "handoff_contexts": list(self.handoff_contexts),
            "checkpoints": list(self.checkpoints),
            "legacy_checkpoints": list(self.legacy_checkpoints),
            "legacy_checkpoint_payloads": list(self.legacy_checkpoint_payloads),
            "checkpoint_materialized": list(self.checkpoint_materialized),
            "checkpoint_session_messages": list(self.checkpoint_session_messages),
            "checkpoint_session_history": list(self.checkpoint_session_history),
            "checkpoint_attachment_refs": list(self.checkpoint_attachment_refs),
            "checkpoint_blob_refs": list(self.checkpoint_blob_refs),
            "workspace_manifests": list(self.workspace_manifests),
            "checkpoint_blobs": list(self.checkpoint_blobs),
            "attachments": list(self.attachments),
            "goals": list(self.goals),
            "memories": list(self.memories),
            "arrange_jobs": list(self.arrange_jobs),
            "arrange_occurrences": list(self.arrange_occurrences),
            "arrange_signals": list(self.arrange_signals),
            "restore_operations": list(self.restore_operations),
            "projects": list(self.projects),
            "handoff": self.handoff,
            "archive_files": [item.to_dict() for item in self.archive_files],
        }


def export_time(value: datetime | None) -> str:
    if value is None:
        return _now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
