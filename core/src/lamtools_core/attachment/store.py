from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from lamtools_core.app.core_db import CoreAttachment
from .files import detect_mime, open_with_default_app, preview_type, read_text_preview, safe_filename, unique_path


class CoreAttachmentStore:
    def __init__(self, session_factory: Callable[[], Any], data_dir: Path) -> None:
        self.session_factory = session_factory
        self.data_dir = data_dir

    async def create(self, session_id: str, filename: str, content: bytes, mime_type: str | None) -> dict[str, Any]:
        safe_name = safe_filename(filename)
        root = self.data_dir / "attachments" / session_id
        root.mkdir(parents=True, exist_ok=True)
        target = unique_path(root / safe_name)
        target.write_bytes(content)
        detected = detect_mime(safe_name, mime_type)
        row = CoreAttachment(id=uuid.uuid4().hex, session_id=session_id, filename=safe_name, mime_type=detected, size=len(content), storage_path=str(target), preview_type=preview_type(safe_name, detected), metadata_json={})
        async with self.session_factory() as db:
            db.add(row)
            await db.commit()
            await db.refresh(row)
        return self.to_dict(row)

    async def list(self, session_id: str) -> list[dict[str, Any]]:
        async with self.session_factory() as db:
            rows = (await db.execute(select(CoreAttachment).where(CoreAttachment.session_id == session_id).order_by(CoreAttachment.created_at))).scalars().all()
        return [self.to_dict(row) for row in rows]

    async def get(self, attachment_id: str) -> CoreAttachment:
        async with self.session_factory() as db:
            row = await db.get(CoreAttachment, attachment_id)
        if row is None:
            raise LookupError("Attachment not found")
        return row

    async def preview(self, attachment_id: str) -> dict[str, Any]:
        row = await self.get(attachment_id)
        path = Path(row.storage_path)
        if not path.exists():
            raise FileNotFoundError("Attachment file not found")
        return {"id": row.id, "filename": row.filename, "preview_type": row.preview_type, "mime_type": row.mime_type, "text": read_text_preview(path) if row.preview_type == "text" else None}

    async def open(self, attachment_id: str) -> dict[str, str]:
        row = await self.get(attachment_id)
        path = Path(row.storage_path)
        if not path.exists():
            raise FileNotFoundError("Attachment file not found")
        open_with_default_app(path)
        return {"status": "opened", "id": row.id}

    @staticmethod
    def to_dict(row: CoreAttachment) -> dict[str, Any]:
        return {"id": row.id, "session_id": row.session_id, "source": "user_upload", "filename": row.filename, "label": row.filename, "mime_type": row.mime_type, "size": row.size, "preview_type": row.preview_type, "metadata": row.metadata_json or {}, "created_at": row.created_at.isoformat() if row.created_at else ""}


__all__ = ["CoreAttachmentStore"]
