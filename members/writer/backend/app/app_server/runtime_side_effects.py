from __future__ import annotations

from hashlib import sha1
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_server import WriterArtifact
from lamtools_core.event import RunItemEvent

async def persist_run_item_side_effects(db: AsyncSession, event: RunItemEvent) -> None:
    await _persist_run_item_artifacts(db, event)


def _artifact_id(thread_id: str, turn_id: str, item_id: str, artifact: dict[str, Any]) -> str:
    existing = artifact.get("artifact_id") or artifact.get("id")
    if existing:
        return str(existing)
    seed = "|".join(
        [
            thread_id,
            turn_id,
            item_id,
            str(artifact.get("artifact_type") or artifact.get("kind") or "file"),
            str(artifact.get("path") or artifact.get("file_path") or artifact.get("name") or ""),
        ]
    )
    return f"artifact-{sha1(seed.encode('utf-8', errors='ignore')).hexdigest()[:16]}"


async def _persist_run_item_artifacts(db: AsyncSession, event: RunItemEvent) -> None:
    artifacts = event.artifacts or ([event.payload] if event.kind == "artifact" and event.payload else [])
    for artifact in artifacts:
        await _persist_writer_artifact(
            db,
            thread_id=event.thread_id,
            turn_id=event.turn_id,
            item_id=event.item_id,
            payload=artifact,
        )


async def _persist_writer_artifact(
    db: AsyncSession,
    *,
    thread_id: str,
    turn_id: str,
    item_id: str,
    payload: dict[str, Any],
) -> None:
    if not isinstance(payload, dict):
        return
    artifact_id = str(
        payload.get("artifact_id")
        or payload.get("id")
        or _artifact_id(thread_id, turn_id, item_id, payload)
    )
    payload["artifact_id"] = artifact_id
    if not artifact_id or await db.get(WriterArtifact, artifact_id) is not None:
        return
    db.add(
        WriterArtifact(
            artifact_id=artifact_id,
            thread_id=str(payload.get("thread_id") or thread_id),
            turn_id=str(payload.get("turn_id") or turn_id),
            item_id=str(payload.get("item_id") or item_id),
            kind=str(payload.get("kind") or payload.get("artifact_type") or "file"),
            name=str(payload.get("name") or Path(str(payload.get("path") or "")).name or "artifact"),
            path=str(payload.get("path") or payload.get("file_path") or ""),
            mime_type=payload.get("mime_type") or payload.get("mimeType"),
            size_bytes=payload.get("size_bytes") or payload.get("sizeBytes"),
            content_hash=payload.get("content_hash") or payload.get("contentHash"),
            metadata_=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        )
    )


__all__ = ["persist_run_item_side_effects"]
