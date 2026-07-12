"""Persistent Core project records and their workspace instruction files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from lamtools_core.session import SessionRecord

from .core_db import CoreProject, CoreThreadSnapshot
from .core_session_store import delete_session_records, session_record_from_snapshot, session_snapshot
from .sqlite_write import SQLiteWriteCoordinator


@dataclass(frozen=True)
class CoreProjectRecord:
    id: str
    name: str
    work_root: str
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "work_root": self.work_root,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class ActiveProjectSessionsError(RuntimeError):
    pass


class CoreProjectStore:
    def __init__(self, session_factory: async_sessionmaker, write_coordinator: SQLiteWriteCoordinator) -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator

    async def create(self, work_root: Path | str, name: str | None = None) -> tuple[CoreProjectRecord, bool]:
        root = _normalize_work_root(work_root)
        root.mkdir(parents=True, exist_ok=True)
        normalized_root = str(root)

        async def write(db: Any) -> tuple[CoreProjectRecord, bool]:
            project, _, created = await _create_project_with_initial_session(
                db,
                root=root,
                normalized_root=normalized_root,
                name=name,
            )
            return project, created

        return await self.write_coordinator.run(write)

    async def create_with_initial_session(
        self,
        work_root: Path | str,
        name: str | None = None,
    ) -> tuple[CoreProjectRecord, SessionRecord, bool]:
        root = _normalize_work_root(work_root)
        root.mkdir(parents=True, exist_ok=True)
        normalized_root = str(root)

        async def write(db: Any) -> tuple[CoreProjectRecord, SessionRecord, bool]:
            return await _create_project_with_initial_session(
                db,
                root=root,
                normalized_root=normalized_root,
                name=name,
            )

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
        return await self._delete_with_sessions(project_id)

    async def list_sessions(self, project_id: str) -> list[SessionRecord]:
        async with self.session_factory() as db:
            return await _project_sessions(db, project_id)

    async def delete_with_sessions(self, project_id: str) -> bool:
        return await self._delete_with_sessions(project_id)

    async def _delete_with_sessions(self, project_id: str) -> bool:
        async def write(db: Any) -> bool:
            return await _delete_project_with_sessions(db, project_id)

        return bool(await self.write_coordinator.run(write))

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


async def _create_project_with_initial_session(
    db: Any,
    *,
    root: Path,
    normalized_root: str,
    name: str | None,
) -> tuple[CoreProjectRecord, SessionRecord, bool]:
    project = await db.scalar(select(CoreProject).where(CoreProject.work_root == normalized_root))
    created = project is None
    if project is None:
        project = CoreProject(
            id=uuid4().hex,
            name=str(name or "").strip() or _default_project_name(root),
            work_root=normalized_root,
        )
        db.add(project)
        await db.flush()

    sessions = await _project_sessions(db, project.id)
    if sessions:
        return _record(project), sessions[0], created

    session = SessionRecord(
        id=uuid4().hex,
        member_id="core",
        title=project.name,
        status="idle",
        metadata={"project_id": project.id, "work_root": normalized_root},
    )
    db.add(
        CoreThreadSnapshot(
            thread_id=session.id,
            snapshot_seq=0,
            snapshot_json=session_snapshot(session),
            updated_at=session.updated_at,
        )
    )
    await db.flush()
    return _record(project), session, created


async def _delete_project_with_sessions(db: Any, project_id: str) -> bool:
    project = await db.get(CoreProject, project_id)
    if project is None:
        return False
    sessions = await _project_sessions(db, project_id)
    if any(session.status.lower() in {"running", "waiting", "interrupting"} for session in sessions):
        raise ActiveProjectSessionsError("Stop the active session before deleting the project")
    await delete_session_records(db, [session.id for session in sessions])
    await db.delete(project)
    return True


async def _project_sessions(db: Any, project_id: str) -> list[SessionRecord]:
    rows = (
        await db.execute(select(CoreThreadSnapshot).order_by(CoreThreadSnapshot.updated_at.desc()))
    ).scalars().all()
    sessions = [session_record_from_snapshot(row) for row in rows]
    return [session for session in sessions if session.metadata.get("project_id") == project_id]


__all__ = ["ActiveProjectSessionsError", "CoreProjectRecord", "CoreProjectStore"]
