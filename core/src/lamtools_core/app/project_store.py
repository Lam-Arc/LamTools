"""Persistent Core project records and their workspace instruction files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from .core_db import CoreProject
from .sqlite_write import SQLiteWriteCoordinator


@dataclass(frozen=True)
class CoreProjectRecord:
    id: str
    name: str
    work_root: str
    created_at: datetime
    updated_at: datetime


class CoreProjectStore:
    def __init__(self, session_factory: async_sessionmaker, write_coordinator: SQLiteWriteCoordinator) -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator

    async def create(self, work_root: Path | str, name: str | None = None) -> tuple[CoreProjectRecord, bool]:
        root = _normalize_work_root(work_root)
        root.mkdir(parents=True, exist_ok=True)
        normalized_root = str(root)

        async def write(db: Any) -> tuple[CoreProjectRecord, bool]:
            existing = await db.scalar(select(CoreProject).where(CoreProject.work_root == normalized_root))
            if existing is not None:
                return _record(existing), False

            project = CoreProject(
                id=uuid4().hex,
                name=str(name or "").strip() or _default_project_name(root),
                work_root=normalized_root,
            )
            db.add(project)
            await db.flush()
            return _record(project), True

        return await self.write_coordinator.run(write)

    async def list(self) -> list[CoreProjectRecord]:
        async with self.session_factory() as db:
            rows = (
                await db.execute(select(CoreProject).order_by(CoreProject.created_at.asc(), CoreProject.id.asc()))
            ).scalars().all()
        return [_record(row) for row in rows]

    async def get(self, project_id: str) -> CoreProjectRecord | None:
        async with self.session_factory() as db:
            project = await db.get(CoreProject, project_id)
        return _record(project) if project is not None else None

    async def rename(self, project_id: str, name: str) -> CoreProjectRecord | None:
        async def write(db: Any) -> CoreProjectRecord | None:
            project = await db.get(CoreProject, project_id)
            if project is None:
                return None
            project.name = str(name).strip()
            await db.flush()
            return _record(project)

        return await self.write_coordinator.run(write)

    async def delete(self, project_id: str) -> bool:
        async def write(db: Any) -> bool:
            project = await db.get(CoreProject, project_id)
            if project is None:
                return False
            await db.delete(project)
            return True

        return await self.write_coordinator.run(write)

    async def read_agents_md(self, project_id: str) -> dict[str, str | bool] | None:
        project = await self.get(project_id)
        if project is None:
            return None
        path = Path(project.work_root) / "AGENTS.md"
        if not path.exists():
            return {"content": "", "exists": False}
        return {"content": path.read_text(encoding="utf-8"), "exists": True}

    async def write_agents_md(self, project_id: str, content: str) -> dict[str, str | bool] | None:
        project = await self.get(project_id)
        if project is None:
            return None
        path = Path(project.work_root) / "AGENTS.md"
        path.write_text(content, encoding="utf-8")
        return {"content": content, "exists": True}


def _normalize_work_root(work_root: Path | str) -> Path:
    return Path(work_root).expanduser().resolve()


def _default_project_name(work_root: Path) -> str:
    return work_root.name or work_root.anchor


def _record(project: CoreProject) -> CoreProjectRecord:
    return CoreProjectRecord(
        id=project.id,
        name=project.name,
        work_root=project.work_root,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


__all__ = ["CoreProjectRecord", "CoreProjectStore"]
