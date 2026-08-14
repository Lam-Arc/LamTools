from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from lamtools_core.app.core_db import CoreAttachment
from .service import AttachmentRecord, AttachmentService, AttachmentSession, attachment_to_dict

# session_id becomes a directory name under data_dir/attachments, so it must
# be a plain identifier — no path separators, no ``..`` (audit 11 S2: the raw
# join allowed writing outside the storage root).
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class _CoreAttachmentRepository:
    def __init__(self, session_factory: Callable[[], Any], data_dir: Path) -> None:
        self.session_factory = session_factory
        self.data_dir = data_dir

    async def session(self, session_id: str) -> AttachmentSession:
        value = str(session_id or "")
        # ``..`` alone would resolve one level up from the storage root.
        if not _SESSION_ID_RE.match(value) or ".." in value:
            raise LookupError("Invalid attachment session id")
        return AttachmentSession(id=value, storage_root=self.data_dir / "attachments" / value)

    async def create(self, record: AttachmentRecord) -> AttachmentRecord:
        row = CoreAttachment(
            id=record.id,
            session_id=record.session_id,
            filename=record.filename,
            mime_type=record.mime_type,
            size=record.size,
            storage_path=record.storage_path,
            preview_type=record.preview_type,
            metadata_json=record.metadata,
        )
        async with self.session_factory() as db:
            db.add(row)
            await db.commit()
            await db.refresh(row)
        return _record(row)

    async def list(self, session_id: str) -> list[AttachmentRecord]:
        async with self.session_factory() as db:
            rows = (
                await db.execute(
                    select(CoreAttachment)
                    .where(CoreAttachment.session_id == session_id)
                    .order_by(CoreAttachment.created_at)
                )
            ).scalars().all()
        return [_record(row) for row in rows]

    async def get(self, attachment_id: str) -> AttachmentRecord | None:
        async with self.session_factory() as db:
            row = await db.get(CoreAttachment, attachment_id)
        return _record(row) if row is not None else None


class CoreAttachmentStore(AttachmentService):
    """Core database adapter kept as the public standalone attachment service."""

    def __init__(self, session_factory: Callable[[], Any], data_dir: Path) -> None:
        super().__init__(_CoreAttachmentRepository(session_factory, data_dir))

    @staticmethod
    def to_dict(record: AttachmentRecord) -> dict[str, Any]:
        return attachment_to_dict(record)


def _record(row: CoreAttachment) -> AttachmentRecord:
    return AttachmentRecord(
        id=row.id,
        session_id=row.session_id,
        filename=row.filename,
        mime_type=row.mime_type,
        size=row.size,
        storage_path=row.storage_path,
        preview_type=row.preview_type,
        metadata=row.metadata_json or {},
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


__all__ = ["CoreAttachmentStore"]
