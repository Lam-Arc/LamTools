from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.attachment_service import writer_attachment_service
from lamtools_core.attachment import AttachmentService, create_attachment_router


def _service(db: AsyncSession = Depends(get_db)) -> AttachmentService:
    return writer_attachment_service(db)


router = create_attachment_router(_service)


__all__ = ["router"]
