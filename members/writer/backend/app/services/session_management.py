from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.writer.core_kernel_adapter import schedule_writer_startup_prewarm
from app.models.project import WriterProject
from app.models.session import WriterSession
from app.routers.path_utils import ensure_work_root
from app.services.session_deletion import delete_writer_session_records
from app.services.session_projection import session_response_projected

def normalize_session_mode(mode: str | None) -> str:
    value = (mode or "EXECUTE").strip()
    if not value:
        return "EXECUTE"
    return value.upper()


async def create_writer_session(
    db: AsyncSession,
    *,
    title: str = "New Session",
    work_root: str = "",
    mode: str = "EXECUTE",
    project_id: str | None = None,
    schedule_prewarm=schedule_writer_startup_prewarm,
) -> dict:
    normalized_root = ensure_work_root(work_root)
    effective_project_id = project_id

    if effective_project_id:
        project = await db.get(WriterProject, effective_project_id)
        if project is None:
            raise HTTPException(status_code=400, detail="Project not found")
        if not normalized_root:
            normalized_root = ensure_work_root(project.work_root)
    elif normalized_root:
        from app.services.project_management import ensure_writer_project

        project = await ensure_writer_project(db, work_root=normalized_root)
        await db.flush()
        effective_project_id = project.id

    session = WriterSession(
        title=title,
        work_root=normalized_root,
        mode=normalize_session_mode(mode),
        project_id=effective_project_id,
    )
    db.add(session)
    await db.flush()
    schedule_prewarm(session.work_root)
    return await session_response_projected(db, session)


async def resolve_writer_session_work_root(
    db: AsyncSession,
    *,
    work_root: str,
    project_id: str | None,
) -> str:
    normalized_root = ensure_work_root(work_root)
    if project_id and not normalized_root:
        project = await db.get(WriterProject, project_id)
        if project is None:
            raise HTTPException(status_code=400, detail="Project not found")
        normalized_root = ensure_work_root(project.work_root)
    return normalized_root


async def get_writer_session_response(
    db: AsyncSession,
    session_id: str,
    *,
    schedule_prewarm=schedule_writer_startup_prewarm,
) -> dict:
    session = await db.get(WriterSession, session_id)
    if session is None:
        raise LookupError("Session not found")
    schedule_prewarm(session.work_root)
    return await session_response_projected(db, session)


async def update_writer_session(
    db: AsyncSession,
    session_id: str,
    update_data: dict,
) -> dict:
    session = await db.get(WriterSession, session_id)
    if session is None:
        raise LookupError("Session not found")

    normalized_update = {key: value for key, value in update_data.items() if value is not None}
    if "project_id" in normalized_update:
        raise ValueError("Use the project session endpoint for project-owned sessions")
    if "mode" in normalized_update:
        normalized_update["mode"] = normalize_session_mode(normalized_update["mode"])
    if "work_root" in normalized_update:
        normalized_update["work_root"] = ensure_work_root(normalized_update["work_root"])
    if "project_id" in normalized_update and normalized_update["project_id"]:
        project = await db.get(WriterProject, normalized_update["project_id"])
        if project is None:
            raise ValueError("Project not found")
        if "work_root" not in normalized_update or not normalized_update.get("work_root"):
            normalized_update["work_root"] = ensure_work_root(project.work_root)
    for key, value in normalized_update.items():
        setattr(session, key, value)

    await db.flush()
    return await session_response_projected(db, session)


async def delete_writer_session(db: AsyncSession, session_id: str) -> None:
    await delete_writer_session_records(db, session_id)


__all__ = [
    "create_writer_session",
    "delete_writer_session",
    "get_writer_session_response",
    "normalize_session_mode",
    "resolve_writer_session_work_root",
    "update_writer_session",
]
