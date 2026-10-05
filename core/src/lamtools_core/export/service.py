from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from lamtools_core.app.core_db import (
    CoreArrangeJob,
    CoreArrangeOccurrence,
    CoreArrangeSignal,
    CoreAppEvent,
    CoreAttachment,
    CoreCheckpoint,
    CoreCheckpointAttachmentRef,
    CoreCheckpointBlob,
    CoreCheckpointBlobRef,
    CoreCheckpointV2,
    CoreCheckpointV2Materialized,
    CoreCheckpointV2SessionHistory,
    CoreCheckpointV2SessionMessages,
    CoreGoal,
    CoreHistoryEntry,
    CoreHandoffContext,
    CoreProject,
    CoreRestoreOperation,
    CoreRuntimeSession,
    CoreThreadSnapshot,
    CoreThreadSnapshotItem,
    CoreWorkspaceManifest,
)
from lamtools_core.attachment.files import safe_filename

from .handoff import sanitize_handoff_context
from .models import FullArchiveFile, ContextHandoffExport, FullConversationExport, TranscriptEntry, TranscriptExport, export_time


class ConversationExportService:
    """Build exports from facts, never from a checkpoint conversation blob."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        *,
        handoff_context_store: Any | None = None,
        handoff_context_provider: Any | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.handoff_context_store = handoff_context_store
        self.handoff_context_provider = handoff_context_provider

    async def transcript(self, thread_id: str) -> TranscriptExport:
        async with self.session_factory() as db:
            rows = list((await db.execute(
                select(CoreHistoryEntry).where(CoreHistoryEntry.thread_id == thread_id).order_by(CoreHistoryEntry.seq.asc())
            )).scalars())
            if not rows:
                runtime = await db.get(CoreRuntimeSession, thread_id)
                raw = runtime.history_json if runtime is not None else []
                messages = [(None, item) for item in raw] if isinstance(raw, list) else []
            else:
                messages = [(row.created_at, row.message_json) for row in rows]
        entries: list[TranscriptEntry] = []
        previous: tuple[str, str] | None = None
        for timestamp, message in messages:
            if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
                continue
            text = _visible_text(message.get("content"))
            if not text:
                continue
            role = str(message["role"])
            # Repeated assistant deltas occasionally leak into legacy history;
            # suppress only exact adjacent duplicates, preserving real repeats.
            if previous == (role, text):
                continue
            previous = (role, text)
            entries.append(TranscriptEntry(export_time(timestamp), role, text))
        return TranscriptExport("lamtools.transcript", 1, _now(), thread_id, tuple(entries))

    async def full(self, thread_id: str) -> FullConversationExport:
        async with self.session_factory() as db:
            owned_ids = await _session_family_ids(db, thread_id)
            snapshot_rows = list((await db.execute(
                select(CoreThreadSnapshot)
                .where(CoreThreadSnapshot.thread_id.in_(owned_ids))
                .order_by(CoreThreadSnapshot.thread_id.asc())
            )).scalars())
            snapshot = next((row for row in snapshot_rows if row.thread_id == thread_id), None)
            snapshot_items = list((await db.execute(
                select(CoreThreadSnapshotItem)
                .where(CoreThreadSnapshotItem.thread_id.in_(owned_ids))
                .order_by(CoreThreadSnapshotItem.thread_id.asc(), CoreThreadSnapshotItem.seq.asc(), CoreThreadSnapshotItem.item_id.asc())
            )).scalars())
            events = list((await db.execute(
                select(CoreAppEvent)
                .where(CoreAppEvent.thread_id.in_(owned_ids))
                .order_by(CoreAppEvent.thread_id.asc(), CoreAppEvent.seq.asc())
            )).scalars())
            history = list((await db.execute(
                select(CoreHistoryEntry)
                .where(CoreHistoryEntry.thread_id.in_(owned_ids))
                .order_by(CoreHistoryEntry.thread_id.asc(), CoreHistoryEntry.seq.asc())
            )).scalars())
            runtimes = list((await db.execute(
                select(CoreRuntimeSession)
                .where(CoreRuntimeSession.thread_id.in_(owned_ids))
                .order_by(CoreRuntimeSession.thread_id.asc())
            )).scalars())
            runtime = next((row for row in runtimes if row.thread_id == thread_id), None)

            checkpoint_filter = or_(
                CoreCheckpointV2.session_id.in_(owned_ids),
                CoreCheckpointV2.root_session_id.in_(owned_ids),
            )
            checkpoints = list((await db.execute(
                select(CoreCheckpointV2).where(checkpoint_filter).order_by(CoreCheckpointV2.created_at.asc(), CoreCheckpointV2.id.asc())
            )).scalars())
            legacy = list((await db.execute(
                select(CoreCheckpoint)
                .where(or_(CoreCheckpoint.session_id.in_(owned_ids), CoreCheckpoint.root_session_id.in_(owned_ids)))
                .order_by(CoreCheckpoint.created_at.asc(), CoreCheckpoint.id.asc())
            )).scalars())
            checkpoint_ids = {row.id for row in checkpoints} | {row.id for row in legacy}
            checkpoint_dicts_by_id = {
                row.id: _model_dict(row)
                for row in checkpoints
            }
            for row in legacy:
                # V2 is authoritative when present, but an archive must also
                # carry a legacy-only row if migration was partial.
                checkpoint_dicts_by_id.setdefault(row.id, _legacy_checkpoint(row))
            v2_checkpoint_ids = {row.id for row in checkpoints}
            legacy_checkpoint_payloads = [
                {"checkpoint_id": row.id, "conversation_json": dict(row.conversation_json or {})}
                for row in legacy
                if row.id not in v2_checkpoint_ids and isinstance(row.conversation_json, dict)
            ]
            checkpoint_dicts = [
                checkpoint_dicts_by_id[row.id]
                for row in sorted(
                    [*checkpoints, *[row for row in legacy if row.id not in v2_checkpoint_ids]],
                    key=lambda item: (item.created_at, item.id),
                )
            ]

            checkpoint_materialized = list((await db.execute(
                select(CoreCheckpointV2Materialized)
                .where(CoreCheckpointV2Materialized.checkpoint_id.in_(checkpoint_ids))
                .order_by(CoreCheckpointV2Materialized.checkpoint_id.asc())
            )).scalars())
            checkpoint_session_messages = list((await db.execute(
                select(CoreCheckpointV2SessionMessages)
                .where(CoreCheckpointV2SessionMessages.checkpoint_id.in_(checkpoint_ids))
                .order_by(CoreCheckpointV2SessionMessages.checkpoint_id.asc())
            )).scalars())
            checkpoint_session_history = list((await db.execute(
                select(CoreCheckpointV2SessionHistory)
                .where(CoreCheckpointV2SessionHistory.checkpoint_id.in_(checkpoint_ids))
                .order_by(CoreCheckpointV2SessionHistory.checkpoint_id.asc())
            )).scalars())
            checkpoint_attachment_refs = list((await db.execute(
                select(CoreCheckpointAttachmentRef)
                .where(CoreCheckpointAttachmentRef.checkpoint_id.in_(checkpoint_ids))
                .order_by(CoreCheckpointAttachmentRef.checkpoint_id.asc(), CoreCheckpointAttachmentRef.attachment_id.asc())
            )).scalars())
            checkpoint_blob_refs = list((await db.execute(
                select(CoreCheckpointBlobRef)
                .where(CoreCheckpointBlobRef.checkpoint_id.in_(checkpoint_ids))
                .order_by(CoreCheckpointBlobRef.checkpoint_id.asc(), CoreCheckpointBlobRef.blob_hash.asc())
            )).scalars())

            referenced_attachment_ids = {row.attachment_id for row in checkpoint_attachment_refs}
            attachments = list((await db.execute(
                select(CoreAttachment)
                .where(or_(
                    CoreAttachment.session_id.in_(owned_ids),
                    CoreAttachment.id.in_(referenced_attachment_ids),
                ))
                .order_by(CoreAttachment.created_at.asc(), CoreAttachment.id.asc())
            )).scalars())

            manifest_ids = {
                str(row.workspace_manifest_id or "")
                for row in checkpoints
                if str(row.workspace_manifest_id or "")
            }
            manifest_ids.update(
                str(row.manifest_hash or "")
                for row in legacy
                if str(row.manifest_hash or "")
            )
            manifests = list((await db.execute(
                select(CoreWorkspaceManifest)
                .where(CoreWorkspaceManifest.hash.in_(manifest_ids))
                .order_by(CoreWorkspaceManifest.hash.asc())
            )).scalars()) if manifest_ids else []
            manifest_blob_sizes = _manifest_blob_sizes(manifests)
            blob_hashes = {row.blob_hash for row in checkpoint_blob_refs} | set(manifest_blob_sizes)
            blob_rows = list((await db.execute(
                select(CoreCheckpointBlob)
                .where(CoreCheckpointBlob.hash.in_(blob_hashes))
                .order_by(CoreCheckpointBlob.hash.asc())
            )).scalars()) if blob_hashes else []

            handoff_rows = list((await db.execute(
                select(CoreHandoffContext)
                .where(CoreHandoffContext.thread_id.in_(owned_ids))
                .order_by(CoreHandoffContext.thread_id.asc())
            )).scalars())
            goals = list((await db.execute(
                select(CoreGoal)
                .where(CoreGoal.thread_id.in_(owned_ids))
                .order_by(CoreGoal.created_at.asc(), CoreGoal.id.asc())
            )).scalars())
            work_roots = _session_work_roots(snapshot_rows)
            arrange_jobs = list((await db.execute(
                select(CoreArrangeJob)
                .where(or_(
                    CoreArrangeJob.thread_id.in_(owned_ids),
                    CoreArrangeJob.source_thread_id.in_(owned_ids),
                ))
                .order_by(CoreArrangeJob.created_at.asc(), CoreArrangeJob.id.asc())
            )).scalars())
            arrange_job_ids = {row.id for row in arrange_jobs}
            arrange_occurrences = list((await db.execute(
                select(CoreArrangeOccurrence)
                .where(CoreArrangeOccurrence.job_id.in_(arrange_job_ids))
                .order_by(CoreArrangeOccurrence.created_at.asc(), CoreArrangeOccurrence.id.asc())
            )).scalars()) if arrange_job_ids else []
            signal_ids = {row.signal_id for row in arrange_occurrences if row.signal_id}
            arrange_signals = list((await db.execute(
                select(CoreArrangeSignal)
                .where(CoreArrangeSignal.event_id.in_(signal_ids))
                .order_by(CoreArrangeSignal.occurred_at.asc(), CoreArrangeSignal.event_id.asc())
            )).scalars()) if signal_ids else []
            restore_operations = list((await db.execute(
                select(CoreRestoreOperation)
                .where(or_(
                    CoreRestoreOperation.root_session_id.in_(owned_ids),
                    CoreRestoreOperation.target_checkpoint_id.in_(checkpoint_ids),
                    CoreRestoreOperation.undo_checkpoint_id.in_(checkpoint_ids),
                    CoreRestoreOperation.derived_checkpoint_id.in_(checkpoint_ids),
                ))
                .order_by(CoreRestoreOperation.created_at.asc(), CoreRestoreOperation.id.asc())
            )).scalars())
            projects = list((await db.execute(
                select(CoreProject)
                .where(CoreProject.work_root.in_(work_roots))
                .order_by(CoreProject.created_at.asc(), CoreProject.id.asc())
            )).scalars()) if work_roots else []
        raw_history = [dict(row.message_json or {}) for row in history]
        if not raw_history and runtime is not None and isinstance(runtime.history_json, list):
            raw_history = [dict(item) for item in runtime.history_json if isinstance(item, dict)]

        attachment_dicts: list[dict[str, Any]] = []
        archive_files: list[FullArchiveFile] = []
        for row in attachments:
            archive_path = _attachment_archive_path(row.id, row.filename)
            attachment = _model_dict(row, omit={"storage_path"})
            # The host filesystem path is neither portable nor useful during
            # import.  Replace it with the member path inside this archive.
            attachment["storage_path"] = archive_path
            attachment["archive_path"] = archive_path
            source_path = Path(row.storage_path)
            if source_path.is_file():
                try:
                    content = source_path.read_bytes()
                except OSError:
                    content = None
                if content is not None:
                    archive_files.append(FullArchiveFile(archive_path, content))
                    attachment["file_present"] = True
                    attachment["file_size"] = len(content)
                else:
                    attachment["file_present"] = False
            else:
                # Keep the logical record so an importer can report the
                # missing file instead of silently dropping the attachment.
                attachment["file_present"] = False
            attachment_dicts.append(attachment)

        workspace_blob_dicts, workspace_files = _workspace_blob_exports(
            blob_rows,
            manifest_blob_sizes=manifest_blob_sizes,
        )
        handoff_context_dicts = [
            {
                "thread_id": row.thread_id,
                "context": sanitize_handoff_context(row.context_json),
            }
            for row in handoff_rows
            if isinstance(row.context_json, dict)
        ]
        handoff_row = next((row for row in handoff_rows if row.thread_id == thread_id), None)
        handoff = None
        if handoff_row is not None and isinstance(handoff_row.context_json, dict):
            handoff = sanitize_handoff_context(handoff_row.context_json)
        return FullConversationExport(
            "lamtools.full-conversation", 1, _now(), thread_id,
            session={
                "thread_id": thread_id,
                "snapshot": _model_dict(snapshot) if snapshot is not None else {},
            },
            snapshots=tuple(_model_dict(row) for row in snapshot_rows),
            snapshot_items=tuple(_model_dict(row) for row in snapshot_items),
            events=tuple(_model_dict(row) for row in events),
            history=tuple(raw_history),
            runtime={"root": _model_dict(runtime) if runtime is not None else {}, "subagents": [_model_dict(row) for row in runtimes if row.thread_id != thread_id]},
            handoff_contexts=tuple(handoff_context_dicts),
            checkpoints=tuple(checkpoint_dicts),
            legacy_checkpoints=tuple(_legacy_checkpoint(row) for row in legacy),
            legacy_checkpoint_payloads=tuple(legacy_checkpoint_payloads),
            checkpoint_materialized=tuple(_model_dict(row) for row in checkpoint_materialized),
            checkpoint_session_messages=tuple(_model_dict(row) for row in checkpoint_session_messages),
            checkpoint_session_history=tuple(_model_dict(row) for row in checkpoint_session_history),
            checkpoint_attachment_refs=tuple(_model_dict(row) for row in checkpoint_attachment_refs),
            checkpoint_blob_refs=tuple(_model_dict(row) for row in checkpoint_blob_refs),
            workspace_manifests=tuple(_model_dict(row) for row in manifests),
            checkpoint_blobs=tuple(workspace_blob_dicts),
            attachments=tuple(attachment_dicts),
            goals=tuple(_model_dict(row) for row in goals),
            arrange_jobs=tuple(_model_dict(row) for row in arrange_jobs),
            arrange_occurrences=tuple(_model_dict(row) for row in arrange_occurrences),
            arrange_signals=tuple(_model_dict(row) for row in arrange_signals),
            restore_operations=tuple(_model_dict(row) for row in restore_operations),
            projects=tuple(_model_dict(row) for row in projects),
            handoff=handoff,
            archive_files=tuple([*archive_files, *workspace_files]),
        )

    async def handoff(self, thread_id: str, *, context: dict[str, Any] | None = None) -> ContextHandoffExport:
        """Return the last real model-boundary context for *thread_id*.

        The service intentionally does not rebuild a prompt from history,
        memory, or project files.  Those inputs are assembled by the normal
        Agent path and captured by Kernel before model I/O.  ``context`` is
        accepted only as an explicit fixture/provider seam for callers that
        already prepared the semantic payload.
        """
        captured = context
        if captured is None:
            getter = self.handoff_context_provider
            if getter is None and self.handoff_context_store is not None:
                getter = getattr(self.handoff_context_store, "get", None)
            if callable(getter):
                captured = getter(thread_id)
                if hasattr(captured, "__await__"):
                    captured = await captured
        if not isinstance(captured, dict):
            raise LookupError(
                f"No captured model context is available for session {thread_id}; "
                "run the session once before exporting Handoff"
            )
        payload = sanitize_handoff_context(captured)
        raw_context = payload.get("context")
        if not isinstance(raw_context, list):
            raise LookupError(f"Captured model context is invalid for session {thread_id}")
        return ContextHandoffExport(tuple(item for item in raw_context if isinstance(item, dict)))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _model_dict(row: Any, *, omit: set[str] | None = None) -> dict[str, Any]:
    if row is None:
        return {}
    omitted = omit or set()
    return {column.name: getattr(row, column.name) for column in row.__table__.columns if column.name not in omitted}


def _legacy_checkpoint(row: CoreCheckpoint) -> dict[str, Any]:
    """Export legacy checkpoint identity without copying its old blob."""
    return {
        "id": row.id,
        "session_id": row.session_id,
        "root_session_id": row.root_session_id,
        "graph_id": row.graph_id,
        "parent_checkpoint_id": row.parent_checkpoint_id,
        "edge_kind": row.edge_kind,
        "turn_id": row.turn_id,
        "actor_kind": row.actor_kind,
        "reason": row.reason,
        "label": row.label,
        "manifest_hash": row.manifest_hash,
        "status": row.status,
        "created_at": export_time(row.created_at),
        # The archive is V2-first and deliberately never embeds the legacy
        # conversation blob.  This flag lets an importer/report show whether
        # the source database had not yet cleared it.
        "conversation_json_present": bool(row.conversation_json),
    }


def _visible_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for part in content:
        if isinstance(part, str):
            chunks.append(part)
        elif isinstance(part, dict):
            value = part.get("text") or part.get("content")
            if isinstance(value, str):
                chunks.append(value)
    return "".join(chunks).strip()


async def _session_family_ids(db: Any, thread_id: str) -> set[str]:
    root = thread_id.split(":sub:", 1)[0]
    columns = (
        CoreRuntimeSession.thread_id,
        CoreAppEvent.thread_id,
        CoreHistoryEntry.thread_id,
        CoreThreadSnapshot.thread_id,
        CoreThreadSnapshotItem.thread_id,
        CoreHandoffContext.thread_id,
        CoreAttachment.session_id,
        CoreGoal.thread_id,
        CoreArrangeJob.thread_id,
        CoreArrangeJob.source_thread_id,
        CoreCheckpoint.session_id,
        CoreCheckpoint.root_session_id,
        CoreCheckpointV2.session_id,
        CoreCheckpointV2.root_session_id,
    )
    owned = {root, thread_id}
    for column in columns:
        rows = list((await db.execute(select(column))).all())
        owned.update(
            str(value)
            for (value,) in rows
            if value is not None
            and (str(value) == root or str(value).startswith(root + ":sub:"))
        )
    return owned


def _session_work_roots(rows: list[CoreThreadSnapshot]) -> set[str]:
    roots: set[str] = set()
    for row in rows:
        state = row.snapshot_json if isinstance(row.snapshot_json, dict) else {}
        session = state.get("session") if isinstance(state.get("session"), dict) else {}
        value = session.get("metadata", {}).get("work_root") if isinstance(session.get("metadata"), dict) else ""
        if isinstance(value, str) and value:
            roots.add(value)
    return roots


def _manifest_blob_sizes(rows: list[CoreWorkspaceManifest]) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for row in rows:
        entries = row.entries_json if isinstance(row.entries_json, dict) else {}
        for entry in entries.values():
            if not isinstance(entry, dict):
                continue
            blob_hash = str(entry.get("hash") or "")
            if not blob_hash:
                continue
            try:
                sizes.setdefault(blob_hash, max(0, int(entry.get("size") or 0)))
            except (TypeError, ValueError):
                sizes.setdefault(blob_hash, 0)
    return sizes


def _workspace_blob_exports(
    rows: list[CoreCheckpointBlob],
    *,
    manifest_blob_sizes: dict[str, int],
) -> tuple[list[dict[str, Any]], list[FullArchiveFile]]:
    """Make workspace checkpoint blobs portable and report missing blobs."""
    by_hash = {str(row.hash): row for row in rows}
    exports: list[dict[str, Any]] = []
    files: list[FullArchiveFile] = []
    for blob_hash in sorted(set(manifest_blob_sizes) | set(by_hash)):
        archive_path = f"workspace/blobs/{safe_filename(blob_hash)}"
        row = by_hash.get(blob_hash)
        if row is None:
            exports.append({
                "hash": blob_hash,
                "size": manifest_blob_sizes.get(blob_hash, 0),
                "storage_path": archive_path,
                "archive_path": archive_path,
                "file_present": False,
                "record_present": False,
            })
            continue
        item = _model_dict(row, omit={"storage_path"})
        item["storage_path"] = archive_path
        item["archive_path"] = archive_path
        source_path = Path(row.storage_path)
        if source_path.is_file():
            try:
                content = source_path.read_bytes()
            except OSError:
                content = None
            if content is not None:
                files.append(FullArchiveFile(archive_path, content))
                item["file_present"] = True
                item["file_size"] = len(content)
            else:
                item["file_present"] = False
        else:
            item["file_present"] = False
        exports.append(item)
    return exports, files


def _attachment_archive_path(attachment_id: str, filename: str) -> str:
    """Return a safe, deterministic member name for an attachment file."""
    return f"attachments/{safe_filename(str(attachment_id))}/{safe_filename(filename)}"
