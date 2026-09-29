"""SQLite-backed Artifact V2 facts and immutable content revisions."""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

_logger = logging.getLogger(__name__)

from lamtools_core.app.core_db import (
    CoreArtifact,
    CoreArtifactAlias,
    CoreArtifactRevision,
    CoreCheckpointArtifactRef,
    CoreCheckpointBlob,
    CoreDbMetadata,
    CoreProject,
)
from lamtools_core.app.sqlite_write import SQLiteWriteCoordinator

from .registry import ATTACHMENT_PREFIX, WORKSPACE_PREFIX, ArtifactRecord, kind_from_mime

ELIGIBLE_OUTPUT_KINDS = {"file_change", "image"}
EXCLUDED_KINDS = {
    "command_output", "file_read", "web_fetch", "web_fetch_content",
    "web_search", "web_search_result", "test_evidence", "verification",
}

_MARKDOWN_LINK_PATH = re.compile(r"\[[^\]\r\n]*\]\(<?([^)>\r\n]+)>?\)")
_INLINE_CODE_PATH = re.compile(r"`([^`\r\n]+)`")
_WINDOWS_ABSOLUTE_PATH = re.compile(
    r"(?<![\w])([A-Za-z]:[\\/][^\r\n<>|?*\"]+?\.[A-Za-z0-9]{1,16})"
    r"(?=$|[\s)\]};,，。；])"
)
_LINE_SUFFIX = re.compile(r":\d+(?::\d+)?$")


@dataclass(frozen=True)
class ArtifactRevisionRecord:
    revision_id: str
    artifact_id: str
    ordinal: int
    sha256: str
    size: int
    mime_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    project_id: str = ""
    thread_id: str = ""
    turn_id: str = ""
    item_id: str = ""
    tool_name: str = ""
    source_event_id: str = ""
    restored_from_revision_id: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ArtifactStore:
    """Durable artifact repository sharing Core's runtime SQLite database."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        blob_root: str | Path,
        write_coordinator: SQLiteWriteCoordinator | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator or SQLiteWriteCoordinator(session_factory)
        self.blob_root = Path(blob_root).resolve()
        self.blob_root.mkdir(parents=True, exist_ok=True)

    async def migrate_legacy(self, *, project_id: str, work_root: str | Path) -> int:
        root = Path(work_root).resolve()
        marker_key = f"artifact_v2_legacy_migrated:{project_id}"
        async with self.session_factory() as db:
            if await db.get(CoreDbMetadata, marker_key) is not None:
                return 0
        manifest_root = root / ".lam" / "artifact"
        imported = 0
        for manifest in sorted(manifest_root.glob("*.json")) if manifest_root.is_dir() else []:
            try:
                raw = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(raw, dict):
                continue
            legacy = ArtifactRecord.from_dict({"artifact_id": manifest.stem, **raw})
            record = await self.register(
                project_id=project_id,
                work_root=root,
                path=legacy.path,
                kind=legacy.kind,
                mime_type=legacy.mime_type,
                name=legacy.name,
                source=legacy.source,
                role="input" if legacy.source == "user_upload" else "deliverable",
                prompt=legacy.prompt,
                parent_ids=legacy.parent_ids,
                preferred_id=legacy.artifact_id,
                deleted=legacy.deleted,
                provenance={"legacy_manifest": str(manifest)},
                snapshot_if_available=True,
                reactivate=False,
            )
            await self.add_alias(legacy.artifact_id, record.artifact_id)
            imported += 1
        async def mark(db: Any) -> None:
            if await db.get(CoreDbMetadata, marker_key) is None:
                db.add(CoreDbMetadata(key=marker_key, value=datetime.now().isoformat(), updated_at=datetime.now()))
        await self.write_coordinator.run(mark)
        return imported

    async def register(
        self,
        *,
        project_id: str,
        work_root: str | Path,
        path: str,
        kind: str,
        mime_type: str = "",
        name: str = "",
        source: str = "agent_generated",
        role: str = "deliverable",
        prompt: str = "",
        parent_ids: list[str] | None = None,
        preferred_id: str = "",
        deleted: bool = False,
        provenance: dict[str, Any] | None = None,
        content: bytes | None = None,
        snapshot_if_available: bool = True,
        force_revision: bool = False,
        restored_from_revision_id: str = "",
        reactivate: bool = True,
    ) -> ArtifactRecord:
        root = Path(work_root).resolve()
        normalized, canonical_path, local_path = _normalize_path(root, path)
        if not mime_type:
            mime_type = mimetypes.guess_type(name or canonical_path)[0] or ""
        if content is None and snapshot_if_available and local_path is not None and local_path.is_file():
            content = local_path.read_bytes()
        now = datetime.now()
        provenance = dict(provenance or {})
        source_event_id = str(provenance.get("event_id") or "")

        async def write(db: Any) -> ArtifactRecord:
            row = (await db.execute(select(CoreArtifact).where(
                CoreArtifact.project_id == project_id,
                CoreArtifact.normalized_path == normalized,
            ))).scalar_one_or_none()
            if row is None:
                row = CoreArtifact(
                    id=preferred_id or uuid.uuid4().hex,
                    project_id=project_id,
                    work_root=str(root),
                    normalized_path=normalized,
                    kind=kind_from_mime(mime_type) if kind == "file_change" else (kind or "file"),
                    mime_type=mime_type,
                    name=name or Path(canonical_path.removeprefix(WORKSPACE_PREFIX)).name,
                    path=canonical_path,
                    source=source,
                    role=role,
                    prompt=prompt,
                    parent_ids_json=list(parent_ids or []),
                    provenance_json=provenance,
                    deleted=deleted,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
                await db.flush()
            else:
                row.kind = kind_from_mime(mime_type) if kind == "file_change" else (kind or row.kind)
                row.mime_type = mime_type or row.mime_type
                row.name = name or row.name
                row.source = source or row.source
                row.role = role or row.role
                row.prompt = prompt or row.prompt
                if reactivate:
                    row.deleted = False
                row.updated_at = now
                if provenance:
                    row.provenance_json = {**dict(row.provenance_json or {}), **provenance}

            for parent_id in list(parent_ids or []):
                parent = await db.get(CoreArtifact, parent_id)
                if parent is not None and row.id not in list(parent.children_ids_json or []):
                    parent.children_ids_json = [*list(parent.children_ids_json or []), row.id]

            if source_event_id:
                existing_event = (await db.execute(select(CoreArtifactRevision).where(
                    CoreArtifactRevision.artifact_id == row.id,
                    CoreArtifactRevision.source_event_id == source_event_id,
                ))).scalar_one_or_none()
                if existing_event is not None:
                    return _artifact_record(row)

            if content is not None:
                digest = hashlib.sha256(content).hexdigest()
                latest = await db.get(CoreArtifactRevision, row.latest_revision_id) if row.latest_revision_id else None
                if force_revision or latest is None or latest.blob_hash != digest:
                    blob = await db.get(CoreCheckpointBlob, digest)
                    if blob is None:
                        blob_path = _write_blob(self.blob_root, digest, content)
                        db.add(CoreCheckpointBlob(hash=digest, size=len(content), storage_path=str(blob_path)))
                    revision_id = uuid.uuid4().hex
                    revision = CoreArtifactRevision(
                        id=revision_id,
                        artifact_id=row.id,
                        ordinal=int(row.revision_count or 0) + 1,
                        blob_hash=digest,
                        size=len(content),
                        mime_type=mime_type or row.mime_type,
                        metadata_json={k: v for k, v in provenance.items() if k != "content"},
                        project_id=project_id,
                        thread_id=str(provenance.get("thread_id") or ""),
                        turn_id=str(provenance.get("turn_id") or ""),
                        item_id=str(provenance.get("item_id") or ""),
                        tool_name=str(provenance.get("tool_name") or ""),
                        source_event_id=source_event_id or f"internal:{uuid.uuid4().hex}",
                        restored_from_revision_id=restored_from_revision_id,
                        created_at=now,
                    )
                    db.add(revision)
                    row.latest_revision_id = revision_id
                    row.revision_count = revision.ordinal
                    row.thread_id = revision.thread_id or row.thread_id
                    row.turn_id = revision.turn_id or row.turn_id
                    row.item_id = revision.item_id or row.item_id
                    row.tool_name = revision.tool_name or row.tool_name
            await db.flush()
            return _artifact_record(row)

        return await self.write_coordinator.run(write)

    async def ingest_run_item(
        self,
        item: Any,
        *,
        project_id: str = "",
        work_root: str | Path,
    ) -> Any:
        item_kind = str(getattr(item, "kind", "") or "")
        if item_kind == "message":
            return await self._ingest_final_message_paths(
                item,
                project_id=project_id,
                work_root=work_root,
            )
        if item_kind != "tool_result":
            return item
        if not project_id:
            async with self.session_factory() as db:
                project = (await db.execute(select(CoreProject).where(
                    CoreProject.work_root == str(Path(work_root).resolve())
                ))).scalar_one_or_none()
                project_id = str(project.id) if project is not None else ""
        if not project_id:
            return item
        tool_name = str(getattr(item, "payload", {}).get("tool_name") or "")
        canonical: list[dict[str, Any]] = []
        for raw in list(getattr(item, "artifacts", []) or []):
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind") or "")
            if kind in EXCLUDED_KINDS or kind not in ELIGIBLE_OUTPUT_KINDS:
                canonical.append(raw)
                continue
            metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
            path = str(raw.get("uri") or raw.get("path") or metadata.get("path") or "")
            if not path:
                canonical.append(raw)
                continue
            if _workspace_candidate(Path(work_root).resolve(), path) is None:
                # An approved out-of-workspace file is not a project artifact:
                # revisions and rollback write back through the workspace, so
                # there is nothing to version here.  Keep the tool's own entry
                # (the file card still renders) instead of failing the turn.
                _logger.info("[artifact] skipped out-of-workspace path %s", path)
                canonical.append(raw)
                continue
            record = await self.register(
                project_id=project_id,
                work_root=work_root,
                path=path,
                kind=kind,
                mime_type=str(metadata.get("mime_type") or ""),
                name=Path(path).name,
                source=str(raw.get("source") or "agent_generated"),
                role=str(raw.get("role") or metadata.get("role") or "deliverable"),
                prompt=str(metadata.get("prompt") or ""),
                parent_ids=[str(value) for value in (raw.get("parent_ids") or metadata.get("parent_ids") or [])],
                provenance={
                    "event_id": str(getattr(item, "event_id", "") or ""),
                    "thread_id": str(getattr(item, "thread_id", "") or ""),
                    "turn_id": str(getattr(item, "turn_id", "") or ""),
                    "item_id": str(getattr(item, "item_id", "") or ""),
                    "tool_name": tool_name,
                    "tool_metadata": metadata,
                },
            )
            projected = {k: v for k, v in raw.items() if k != "content"}
            historical_id = str(raw.get("artifact_id") or raw.get("id") or "")
            if historical_id and historical_id != record.artifact_id:
                await self.add_alias(historical_id, record.artifact_id)
            projected["artifact_id"] = record.artifact_id
            projected["revision_id"] = record.latest_revision_id
            projected["path"] = record.path
            canonical.append(projected)
        item.artifacts = canonical
        return item

    async def _ingest_final_message_paths(
        self,
        item: Any,
        *,
        project_id: str,
        work_root: str | Path,
    ) -> Any:
        """Attach existing workspace files named in a completed agent answer.

        Tool artifacts remain the primary source of provenance. This fallback
        covers deliverables produced indirectly by shell commands, Office
        applications, or helper programs that cannot emit ToolArtifact data.
        """

        payload = getattr(item, "payload", {})
        metadata = getattr(item, "metadata", {})
        if (
            getattr(item, "status", "") != "completed"
            or not isinstance(payload, dict)
            or str(payload.get("type") or "") != "agentMessage"
            or payload.get("sub_agent_terminal") is True
            or (isinstance(metadata, dict) and isinstance(metadata.get("sub_agent"), dict))
        ):
            return item
        content = str(payload.get("content") or "").strip()
        if not content:
            return item

        root = Path(work_root).resolve()
        if not project_id:
            async with self.session_factory() as db:
                project = (await db.execute(select(CoreProject).where(
                    CoreProject.work_root == str(root)
                ))).scalar_one_or_none()
                project_id = str(project.id) if project is not None else ""
        if not project_id:
            return item

        canonical = list(getattr(item, "artifacts", []) or [])
        existing_paths = {
            str(raw.get("path") or raw.get("uri") or "")
            for raw in canonical
            if isinstance(raw, dict)
        }
        for candidate in _existing_workspace_paths(content, root):
            relative = candidate.relative_to(root).as_posix()
            workspace_path = f"{WORKSPACE_PREFIX}{relative}"
            if relative in existing_paths or workspace_path in existing_paths:
                continue
            mime_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            record = await self.register(
                project_id=project_id,
                work_root=root,
                path=relative,
                kind="file_change",
                mime_type=mime_type,
                name=candidate.name,
                source="agent_generated",
                role="deliverable",
                provenance={
                    "event_id": str(getattr(item, "event_id", "") or ""),
                    "thread_id": str(getattr(item, "thread_id", "") or ""),
                    "turn_id": str(getattr(item, "turn_id", "") or ""),
                    "item_id": str(getattr(item, "item_id", "") or ""),
                    "tool_name": "agent_final_response",
                    "discovered_from": "final_response_path",
                },
            )
            canonical.append({
                "artifact_id": record.artifact_id,
                "revision_id": record.latest_revision_id,
                "kind": "file_change",
                "name": record.name,
                "path": record.path,
                "uri": relative,
                "mime_type": record.mime_type,
                "role": "deliverable",
                "source": "agent_generated",
                "metadata": {
                    "mime_type": record.mime_type,
                    "role": "deliverable",
                    "path": record.path,
                    "discovered_from": "final_response_path",
                },
            })
            existing_paths.update({relative, workspace_path})
        item.artifacts = canonical
        return item

    async def get(self, artifact_id_or_alias: str) -> ArtifactRecord | None:
        async with self.session_factory() as db:
            row = await db.get(CoreArtifact, artifact_id_or_alias)
            if row is None:
                alias = await db.get(CoreArtifactAlias, artifact_id_or_alias)
                row = await db.get(CoreArtifact, alias.artifact_id) if alias is not None else None
            return _artifact_record(row) if row is not None else None

    async def list(self, project_id: str, *, include_deleted: bool = False) -> list[ArtifactRecord]:
        async with self.session_factory() as db:
            query = select(CoreArtifact).where(CoreArtifact.project_id == project_id)
            if not include_deleted:
                query = query.where(CoreArtifact.deleted.is_(False))
            rows = list((await db.execute(query.order_by(CoreArtifact.created_at, CoreArtifact.id))).scalars())
            return [_artifact_record(row) for row in rows]

    async def revisions(self, artifact_id: str) -> list[ArtifactRevisionRecord]:
        record = await self.get(artifact_id)
        if record is None:
            return []
        async with self.session_factory() as db:
            rows = list((await db.execute(select(CoreArtifactRevision).where(
                CoreArtifactRevision.artifact_id == record.artifact_id
            ).order_by(CoreArtifactRevision.ordinal))).scalars())
            return [_revision_record(row) for row in rows]

    async def revision(self, artifact_id: str, revision_id: str = "") -> ArtifactRevisionRecord | None:
        record = await self.get(artifact_id)
        if record is None:
            return None
        target = revision_id or record.latest_revision_id
        async with self.session_factory() as db:
            row = await db.get(CoreArtifactRevision, target)
            if row is None or row.artifact_id != record.artifact_id:
                return None
            return _revision_record(row)

    async def revision_path(self, artifact_id: str, revision_id: str = "") -> Path | None:
        revision = await self.revision(artifact_id, revision_id)
        if revision is None:
            return None
        async with self.session_factory() as db:
            blob = await db.get(CoreCheckpointBlob, revision.sha256)
            return Path(blob.storage_path) if blob is not None else None

    async def soft_remove(
        self,
        artifact_ids: list[str],
        *,
        deleted: bool = True,
        project_id: str = "",
    ) -> int:
        async def write(db: Any) -> int:
            changed = 0
            for artifact_id in artifact_ids:
                row = await db.get(CoreArtifact, artifact_id)
                if row is None:
                    alias = await db.get(CoreArtifactAlias, artifact_id)
                    row = await db.get(CoreArtifact, alias.artifact_id) if alias is not None else None
                if (
                    row is not None
                    and (not project_id or row.project_id == project_id)
                    and bool(row.deleted) != deleted
                ):
                    row.deleted = deleted
                    row.updated_at = datetime.now()
                    changed += 1
            return changed
        return await self.write_coordinator.run(write)

    async def restore_revision(
        self,
        artifact_id: str,
        revision_id: str,
        *,
        project_id: str = "",
    ) -> ArtifactRecord:
        record = await self.get(artifact_id)
        if record is not None and project_id and record.project_id != project_id:
            record = None
        revision = await self.revision(artifact_id, revision_id)
        blob_path = await self.revision_path(artifact_id, revision_id)
        if record is None or revision is None or blob_path is None or not blob_path.is_file():
            raise LookupError("Artifact revision not found")
        content = blob_path.read_bytes()
        if record.path.startswith(WORKSPACE_PREFIX):
            destination = _safe_workspace_path(Path(record.work_root), record.path.removeprefix(WORKSPACE_PREFIX))
            destination.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(destination, content)
        return await self.register(
            project_id=record.project_id,
            work_root=record.work_root,
            path=record.path,
            kind=record.kind,
            mime_type=record.mime_type,
            name=record.name,
            source=record.source,
            role=record.role,
            prompt=record.prompt,
            content=content,
            force_revision=True,
            restored_from_revision_id=revision_id,
            provenance={"tool_name": "artifact.restore_revision"},
        )

    async def capture_checkpoint(self, checkpoint_id: str, work_root: str | Path) -> None:
        normalized_root = os.path.normcase(str(Path(work_root).resolve()))
        async def write(db: Any) -> None:
            rows = list((await db.execute(select(CoreArtifact).where(
                CoreArtifact.work_root == str(Path(work_root).resolve()),
                CoreArtifact.deleted.is_(False),
                CoreArtifact.latest_revision_id != "",
            ))).scalars())
            for row in rows:
                if os.path.normcase(row.work_root) != normalized_root:
                    continue
                if await db.get(CoreCheckpointArtifactRef, (checkpoint_id, row.id)) is None:
                    db.add(CoreCheckpointArtifactRef(
                        checkpoint_id=checkpoint_id,
                        artifact_id=row.id,
                        revision_id=row.latest_revision_id,
                    ))
        await self.write_coordinator.run(write)

    async def restore_checkpoint(
        self,
        checkpoint_id: str,
        *,
        work_root: str | Path | None = None,
    ) -> list[str]:
        async with self.session_factory() as db:
            refs = list((await db.execute(select(CoreCheckpointArtifactRef).where(
                CoreCheckpointArtifactRef.checkpoint_id == checkpoint_id
            ))).scalars())
        referenced_ids = {ref.artifact_id for ref in refs}
        if work_root is not None:
            resolved_root = str(Path(work_root).resolve())

            async def remove_post_checkpoint_artifacts(db: Any) -> None:
                rows = list((await db.execute(select(CoreArtifact).where(
                    CoreArtifact.work_root == resolved_root,
                    CoreArtifact.deleted.is_(False),
                ))).scalars())
                now = datetime.now()
                for row in rows:
                    if row.id not in referenced_ids:
                        row.deleted = True
                        row.updated_at = now

            await self.write_coordinator.run(remove_post_checkpoint_artifacts)
        restored: list[str] = []
        for ref in refs:
            await self.restore_revision(ref.artifact_id, ref.revision_id)
            restored.append(ref.artifact_id)
        return restored

    async def add_alias(self, alias: str, artifact_id: str) -> None:
        if not alias:
            return
        async def write(db: Any) -> None:
            if await db.get(CoreArtifactAlias, alias) is None:
                db.add(CoreArtifactAlias(alias=alias, artifact_id=artifact_id))
        await self.write_coordinator.run(write)


def _workspace_candidate(work_root: Path, value: str) -> Path | None:
    """Resolve a stored path against the project root, or ``None`` when it lands outside.

    Tool results name files relative to the workspace, but for a file the
    operator allowed outside it (``relative_workspace_uri`` falls back to an
    absolute path) the name is absolute.  Artifact records only mean something
    inside the project — revisions, blobs and rollback all write back through
    the workspace — so callers that ingest run items skip those instead of
    failing the turn that produced them.
    """

    rel = str(value or "").strip().removeprefix(WORKSPACE_PREFIX).replace("\\", "/")
    if not rel:
        return None
    candidate = Path(rel)
    if candidate.is_absolute():
        candidate = candidate.resolve()
    else:
        candidate = (work_root / candidate).resolve()
    try:
        candidate.relative_to(work_root)
    except ValueError:
        return None
    return candidate


def _normalize_path(work_root: Path, value: str) -> tuple[str, str, Path | None]:
    raw = str(value or "").strip()
    if raw.startswith(ATTACHMENT_PREFIX):
        attachment_id = raw.removeprefix(ATTACHMENT_PREFIX).strip()
        return f"attachment:{attachment_id}", f"{ATTACHMENT_PREFIX}{attachment_id}", None
    candidate = _workspace_candidate(work_root, raw)
    if candidate is None:
        raise ValueError("Artifact path escapes project")
    normalized_rel = candidate.relative_to(work_root).as_posix()
    return f"workspace:{normalized_rel.casefold()}", f"{WORKSPACE_PREFIX}{normalized_rel}", candidate


def _safe_workspace_path(root: Path, relative: str) -> Path:
    candidate = (root.resolve() / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("Artifact path escapes project") from exc
    return candidate


def _write_blob(root: Path, digest: str, content: bytes) -> Path:
    target = root / digest[:2] / digest
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f"{digest}.", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass
    return target


def _atomic_write(path: Path, content: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def _artifact_record(row: CoreArtifact) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=row.id,
        kind=row.kind,
        mime_type=row.mime_type,
        name=row.name,
        path=row.path,
        source=row.source,
        prompt=row.prompt,
        parent_ids=list(row.parent_ids_json or []),
        children_ids=list(row.children_ids_json or []),
        created_at=row.created_at.isoformat(),
        deleted=bool(row.deleted),
        role=row.role,
        latest_revision_id=row.latest_revision_id,
        revision_count=int(row.revision_count or 0),
        project_id=row.project_id,
        work_root=row.work_root,
        thread_id=row.thread_id,
        turn_id=row.turn_id,
        item_id=row.item_id,
        tool_name=row.tool_name,
        provenance=dict(row.provenance_json or {}),
        availability="available" if row.latest_revision_id else "metadata_only",
    )


def _revision_record(row: CoreArtifactRevision) -> ArtifactRevisionRecord:
    return ArtifactRevisionRecord(
        revision_id=row.id,
        artifact_id=row.artifact_id,
        ordinal=row.ordinal,
        sha256=row.blob_hash,
        size=row.size,
        mime_type=row.mime_type,
        metadata=dict(row.metadata_json or {}),
        project_id=row.project_id,
        thread_id=row.thread_id,
        turn_id=row.turn_id,
        item_id=row.item_id,
        tool_name=row.tool_name,
        source_event_id=row.source_event_id,
        restored_from_revision_id=row.restored_from_revision_id,
        created_at=row.created_at.isoformat(),
    )


__all__ = ["ArtifactRevisionRecord", "ArtifactStore", "ELIGIBLE_OUTPUT_KINDS", "EXCLUDED_KINDS"]


def _existing_workspace_paths(content: str, root: Path) -> list[Path]:
    """Return de-duplicated regular files explicitly named by an agent."""

    raw_candidates = [
        *(match.group(1) for match in _MARKDOWN_LINK_PATH.finditer(content)),
        *(match.group(1) for match in _INLINE_CODE_PATH.finditer(content)),
        *(match.group(1) for match in _WINDOWS_ABSOLUTE_PATH.finditer(content)),
    ]
    resolved: list[Path] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        value = str(raw).strip().strip("<>\"'").rstrip(".,;，。；")
        if not value or value.startswith(("http://", "https://", "data:", "attachment://")):
            continue
        if value.startswith(WORKSPACE_PREFIX):
            value = value.removeprefix(WORKSPACE_PREFIX)
        value = value.replace("%20", " ")
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if not candidate.is_file() and _LINE_SUFFIX.search(str(candidate)):
            candidate = Path(_LINE_SUFFIX.sub("", str(candidate))).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        resolved.append(candidate)
    return resolved
