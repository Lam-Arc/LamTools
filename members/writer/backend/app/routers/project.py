from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import execute_writer_write, get_db, get_writer_write
from app.models.project import WriterProject
from app.core.writer.git import WriterGitManager
from app.services.project_management import (
    create_writer_project_response,
    delete_writer_project,
    get_writer_project_response,
    list_project_session_summaries,
    list_writer_project_responses,
    read_project_agents_md,
    update_writer_project,
    write_project_agents_md,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_git_manager = WriterGitManager()


# --- Request/Response Schemas ---

class ProjectCreate(BaseModel):
    work_root: str = ""
    name: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    work_root: str | None = None
    agents_md: str | None = None
    config: dict | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    work_root: str
    agents_md: str | None
    config: dict | None
    created_at: datetime
    updated_at: datetime


class AgentsMdUpdate(BaseModel):
    content: str


class AgentsMdResponse(BaseModel):
    content: str


class SessionSummary(BaseModel):
    id: str
    title: str
    phase: str
    mode: str
    status: str
    created_at: datetime
    updated_at: datetime


# --- Project CRUD ---

@router.post("/projects", response_model=ProjectResponse)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    write_transaction=Depends(get_writer_write),
):
    project = await execute_writer_write(
        db,
        lambda write_db: create_writer_project_response(
            write_db,
            work_root=body.work_root,
            name=body.name,
            git_manager=None,
        ),
        write_transaction,
    )
    if project.get("work_root"):
        try:
            await _git_manager.init_repo(str(project["work_root"]))
        except Exception:
            logger.debug("Unexpected error during project Git init", exc_info=True)
    return ProjectResponse(**project)


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return [
        ProjectResponse(**project)
        for project in await list_writer_project_responses(db, limit=limit, offset=offset)
    ]


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return ProjectResponse(**await get_writer_project_response(db, project_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str, body: ProjectUpdate, db: AsyncSession = Depends(get_db),
    write_transaction=Depends(get_writer_write),
):
    try:
        return ProjectResponse(**await execute_writer_write(
            db,
            lambda write_db: update_writer_project(write_db, project_id, body.model_dump(exclude_unset=True)),
            write_transaction,
        ))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str, db: AsyncSession = Depends(get_db), write_transaction=Depends(get_writer_write)
):
    try:
        await execute_writer_write(db, lambda write_db: delete_writer_project(write_db, project_id), write_transaction)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


# --- AGENTS.md Read/Write ---

@router.get("/projects/{project_id}/agents-md", response_model=AgentsMdResponse)
async def read_agents_md(project_id: str, db: AsyncSession = Depends(get_db)):
    try:
        return AgentsMdResponse(**await read_project_agents_md(db, project_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/projects/{project_id}/agents-md", response_model=AgentsMdResponse)
async def write_agents_md(
    project_id: str, body: AgentsMdUpdate, db: AsyncSession = Depends(get_db),
    write_transaction=Depends(get_writer_write),
):
    try:
        return AgentsMdResponse(**await execute_writer_write(
            db,
            lambda write_db: write_project_agents_md(write_db, project_id, body.content),
            write_transaction,
        ))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- Project Sessions ---

@router.get("/projects/{project_id}/sessions", response_model=list[SessionSummary])
async def list_project_sessions(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    try:
        return [
            SessionSummary(**session)
            for session in await list_project_session_summaries(
                db,
                project_id,
                limit=limit,
                offset=offset,
            )
        ]
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
