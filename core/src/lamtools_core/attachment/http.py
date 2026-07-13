from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .service import AttachmentService


def create_attachment_router(service_dependency: Callable[..., Any]) -> APIRouter:
    """Create the shared HTTP surface used by Core and member applications."""
    router = APIRouter()

    @router.post("/sessions/{session_id}/attachments")
    async def upload_attachment(
        session_id: str,
        file: UploadFile = File(...),
        service: AttachmentService = Depends(service_dependency),
    ):
        try:
            return await service.create(session_id, file.filename or "attachment", await file.read(), file.content_type)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/sessions/{session_id}/attachments")
    async def list_attachments(session_id: str, service: AttachmentService = Depends(service_dependency)):
        try:
            return await service.list(session_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/attachments/{attachment_id}")
    async def get_attachment(attachment_id: str, service: AttachmentService = Depends(service_dependency)):
        try:
            return await service.get_response(attachment_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/attachments/{attachment_id}/preview")
    async def preview_attachment(attachment_id: str, service: AttachmentService = Depends(service_dependency)):
        try:
            return await service.preview(attachment_id)
        except (LookupError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/attachments/{attachment_id}/download")
    async def download_attachment(attachment_id: str, service: AttachmentService = Depends(service_dependency)):
        try:
            record = await service.get(attachment_id)
            path = Path(record.storage_path)
            if not path.exists():
                raise FileNotFoundError("Attachment file not found")
            return FileResponse(path, media_type=record.mime_type, filename=record.filename)
        except (LookupError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/attachments/{attachment_id}/open")
    async def open_attachment(attachment_id: str, service: AttachmentService = Depends(service_dependency)):
        try:
            return await service.open(attachment_id)
        except (LookupError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


__all__ = ["create_attachment_router"]
