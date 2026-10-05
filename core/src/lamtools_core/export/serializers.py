from __future__ import annotations

import json
from datetime import date, datetime
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from .models import ContextHandoffExport, FullConversationExport, TranscriptExport


def to_json(value: Any) -> str:
    payload = value.to_dict() if hasattr(value, "to_dict") else value
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def to_jsonl(rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> str:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n"
        for row in rows
    )


def transcript_to_text(export: TranscriptExport) -> str:
    return "\n\n".join(entry.text for entry in export.entries) + ("\n" if export.entries else "")


def transcript_to_markdown(export: TranscriptExport) -> str:
    blocks = []
    for entry in export.entries:
        blocks.append(f"## {entry.role} · {entry.timestamp}\n\n{entry.text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def transcript_to_jsonl(export: TranscriptExport) -> str:
    """Serialize one transcript entry per JSONL line."""
    return to_jsonl([entry.to_dict() for entry in export.entries])


def handoff_to_json(export: ContextHandoffExport) -> str:
    """Serialize the fixed single-object Handoff envelope."""
    return to_json(export) + "\n"


def full_to_jsonl(export: FullConversationExport) -> dict[str, str]:
    return {
        "manifest.json": to_json({
            "schema": export.schema,
            "version": export.version,
            "exported_at": export.exported_at,
        "thread_id": export.thread_id,
        "files": [item.to_dict() for item in export.archive_files],
        "missing_attachment_files": [
                item.get("archive_path")
                for item in export.attachments
                if item.get("file_present") is False
            ],
        "missing_workspace_files": [
            item.get("archive_path")
            for item in export.checkpoint_blobs
            if item.get("file_present") is False
        ],
        }),
        "session.json": to_json(export.session),
        "snapshots.jsonl": to_jsonl(list(export.snapshots)),
        "snapshot-items.jsonl": to_jsonl(list(export.snapshot_items)),
        "events.jsonl": to_jsonl(list(export.events)),
        "history.jsonl": to_jsonl(list(export.history)),
        "runtime.json": to_json(export.runtime),
        "handoff-contexts.jsonl": to_jsonl(list(export.handoff_contexts)),
        "checkpoints.jsonl": to_jsonl(list(export.checkpoints)),
        "legacy-checkpoints.jsonl": to_jsonl(list(export.legacy_checkpoints)),
        "legacy-checkpoint-payloads.jsonl": to_jsonl(list(export.legacy_checkpoint_payloads)),
        "checkpoint-materialized.jsonl": to_jsonl(list(export.checkpoint_materialized)),
        "checkpoint-session-messages.jsonl": to_jsonl(list(export.checkpoint_session_messages)),
        "checkpoint-session-history.jsonl": to_jsonl(list(export.checkpoint_session_history)),
        "checkpoint-attachment-refs.jsonl": to_jsonl(list(export.checkpoint_attachment_refs)),
        "checkpoint-blob-refs.jsonl": to_jsonl(list(export.checkpoint_blob_refs)),
        "workspace-manifests.jsonl": to_jsonl(list(export.workspace_manifests)),
        "checkpoint-blobs.jsonl": to_jsonl(list(export.checkpoint_blobs)),
        "attachments.jsonl": to_jsonl(list(export.attachments)),
        "goals.jsonl": to_jsonl(list(export.goals)),
        "arrange-jobs.jsonl": to_jsonl(list(export.arrange_jobs)),
        "arrange-occurrences.jsonl": to_jsonl(list(export.arrange_occurrences)),
        "arrange-signals.jsonl": to_jsonl(list(export.arrange_signals)),
        "restore-operations.jsonl": to_jsonl(list(export.restore_operations)),
        "projects.jsonl": to_jsonl(list(export.projects)),
        **({"handoff.json": to_json(export.handoff)} if export.handoff is not None else {}),
    }


def full_to_zip(export: FullConversationExport) -> bytes:
    """Serialize a full export, including portable attachment file members."""
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in full_to_jsonl(export).items():
            archive.writestr(name, content)
        for item in export.archive_files:
            _validate_zip_member(item.path)
            archive.writestr(item.path, item.content)
    return buffer.getvalue()


def _validate_zip_member(path: str) -> None:
    member = PurePosixPath(path)
    if member.is_absolute() or ".." in member.parts or not member.parts:
        raise ValueError(f"Unsafe Full Archive member path: {path}")
