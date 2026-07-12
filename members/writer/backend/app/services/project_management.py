from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from lamtools_core.app.project_store import (
    ActiveProjectSessionsError,
    ensure_workspace_root,
    normalize_workspace_root,
    read_workspace_agents_md,
    workspace_name,
    write_workspace_agents_md,
)

from app.models.project import WriterProject
from app.models.session import WriterSession
from app.services.session_deletion import delete_writer_session_records
from app.services.session_management import create_writer_session

def project_name_from_work_root(work_root: str) -> str:
    return workspace_name(work_root)


async def ensure_writer_project(
    db: AsyncSession,
    *,
    work_root: str,
    name: str | None = None,
) -> WriterProject:
    try:
        normalized_root = str(ensure_workspace_root(work_root))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not normalized_root:
        raise HTTPException(status_code=400, detail="Project work_root is required")

    existing = await db.execute(select(WriterProject).where(WriterProject.work_root == normalized_root))
    existing_projects = existing.scalars().all()
    if existing_projects:
        if len(existing_projects) == 1:
            return existing_projects[0]
        return await merge_duplicate_projects(db, normalized_root, existing_projects)

    project = WriterProject(
        name=str(name or '').strip() or project_name_from_work_root(normalized_root),
        work_root=normalized_root,
    )
    project.agents_md = str(read_workspace_agents_md(normalized_root)["content"])
    db.add(project)
    return project


async def merge_duplicate_projects(
    db: AsyncSession,
    work_root: str,
    projects: list[WriterProject],
) -> WriterProject:
    canonical = min(projects, key=lambda project: (project.created_at, project.id))
    canonical.work_root = work_root

    duplicate_ids = [p.id for p in projects if p.id != canonical.id]
    for duplicate in projects:
        if duplicate.id == canonical.id:
            continue
        if not canonical.agents_md and duplicate.agents_md:
            canonical.agents_md = duplicate.agents_md
        if not canonical.config and duplicate.config:
            canonical.config = duplicate.config

    if duplicate_ids:
        await db.execute(
            sql_update(WriterSession)
            .where(WriterSession.project_id.in_(duplicate_ids))
            .values(project_id=canonical.id, work_root=work_root)
        )
        for duplicate in projects:
            if duplicate.id != canonical.id:
                await db.delete(duplicate)

    return canonical


async def dedupe_writer_projects(db: AsyncSession) -> None:
    result = await db.execute(select(WriterProject).where(WriterProject.work_root != ""))
    by_root: dict[str, list[WriterProject]] = {}
    for project in result.scalars().all():
        by_root.setdefault(project.work_root, []).append(project)

    for work_root, projects in by_root.items():
        if len(projects) <= 1:
            continue
        await merge_duplicate_projects(db, work_root, projects)


def project_response(project: WriterProject) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "work_root": project.work_root,
        "agents_md": project.agents_md,
        "config": project.config,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


async def create_writer_project_response(
    db: AsyncSession,
    *,
    work_root: str,
    name: str | None = None,
) -> dict[str, Any]:
    project = await ensure_writer_project(db, work_root=work_root, name=name)
    await db.flush()
    await db.refresh(project)
    return project_response(project)


async def list_writer_project_responses(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    await dedupe_writer_projects(db)
    await db.flush()
    result = await db.execute(
        select(WriterProject)
        .order_by(WriterProject.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return [project_response(project) for project in result.scalars().all()]


async def get_writer_project_response(db: AsyncSession, project_id: str) -> dict[str, Any]:
    project = await db.get(WriterProject, project_id)
    if project is None:
        raise LookupError("Project not found")
    return project_response(project)


async def update_writer_project(
    db: AsyncSession,
    project_id: str,
    update_data: dict[str, Any],
) -> dict[str, Any]:
    project = await db.get(WriterProject, project_id)
    if project is None:
        raise LookupError("Project not found")

    normalized_update = {key: value for key, value in update_data.items() if value is not None}
    if "work_root" in normalized_update:
        raw_root = str(normalized_update["work_root"]).strip()
        try:
            normalized_update["work_root"] = str(ensure_workspace_root(raw_root)) if raw_root else ""
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if normalized_update["work_root"] and "name" not in normalized_update:
            normalized_update["name"] = project_name_from_work_root(normalized_update["work_root"])
    for key, value in normalized_update.items():
        if hasattr(project, key):
            setattr(project, key, value)

    await db.flush()
    await db.refresh(project)
    return project_response(project)


async def delete_writer_project(db: AsyncSession, project_id: str) -> None:
    project = await db.get(WriterProject, project_id)
    if project is None:
        raise LookupError("Project not found")
    sessions = (
        await db.execute(select(WriterSession).where(WriterSession.project_id == project_id))
    ).scalars().all()
    if any(session.status.lower() in {"running", "waiting", "interrupting"} for session in sessions):
        raise ActiveProjectSessionsError("Stop the active session before deleting the project")
    for session in sessions:
        await delete_writer_session_records(db, session.id)
    await db.delete(project)
    await db.flush()


async def create_writer_project_session(
    db: AsyncSession,
    project_id: str,
    *,
    title: str = "New Session",
    mode: str = "EXECUTE",
) -> dict[str, Any]:
    project = await db.get(WriterProject, project_id)
    if project is None:
        raise LookupError("Project not found")
    return await create_writer_session(
        db,
        title=title,
        work_root=project.work_root,
        mode=mode,
        project_id=project.id,
    )


async def read_project_agents_md(db: AsyncSession, project_id: str) -> dict[str, str | bool]:
    project = await db.get(WriterProject, project_id)
    if project is None:
        raise LookupError("Project not found")
    if not project.work_root:
        raise ValueError("Project has no work_root set")

    result = read_workspace_agents_md(project.work_root)
    return result


async def write_project_agents_md(db: AsyncSession, project_id: str, content: str) -> dict[str, str | bool]:
    project = await db.get(WriterProject, project_id)
    if project is None:
        raise LookupError("Project not found")
    if not project.work_root:
        raise ValueError("Project has no work_root set")

    result = write_workspace_agents_md(project.work_root, content)
    project.agents_md = content
    await db.flush()
    return result


def project_session_summary(session: WriterSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "title": session.title,
        "phase": session.phase,
        "mode": session.mode,
        "status": session.status,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


async def list_project_session_summaries(
    db: AsyncSession,
    project_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    project = await db.get(WriterProject, project_id)
    if project is None:
        raise LookupError("Project not found")

    result = await db.execute(
        select(WriterSession)
        .where(WriterSession.project_id == project_id)
        .order_by(WriterSession.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return [project_session_summary(session) for session in result.scalars().all()]


__all__ = [
    "create_writer_project_response",
    "create_writer_project_session",
    "dedupe_writer_projects",
    "delete_writer_project",
    "ensure_writer_project",
    "get_writer_project_response",
    "list_project_session_summaries",
    "list_writer_project_responses",
    "merge_duplicate_projects",
    "project_response",
    "project_session_summary",
    "project_name_from_work_root",
    "read_project_agents_md",
    "update_writer_project",
    "write_project_agents_md",
]
