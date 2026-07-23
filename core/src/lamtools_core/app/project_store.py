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


def normalize_workspace_root(work_root: Path | str) -> Path:
    raw = str(work_root).strip()
    if not raw:
        raise ValueError("work_root is required")
    root = Path(raw).expanduser().resolve()
    if root.exists() and not root.is_dir():
        raise ValueError("work_root must point to a directory")
    return root


def ensure_workspace_root(work_root: Path | str) -> Path:
    root = normalize_workspace_root(work_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def workspace_name(work_root: Path | str) -> str:
    root = normalize_workspace_root(work_root)
    return root.name or root.anchor


def read_workspace_agents_md(work_root: Path | str) -> dict[str, str | bool]:
    path = normalize_workspace_root(work_root) / "AGENTS.md"
    if not path.exists():
        return {"content": "", "exists": False}
    return {"content": path.read_text(encoding="utf-8"), "exists": True}


def write_workspace_agents_md(work_root: Path | str, content: str) -> dict[str, str | bool]:
    path = ensure_workspace_root(work_root) / "AGENTS.md"
    path.write_text(content, encoding="utf-8")
    return {"content": content, "exists": True}


class CoreProjectStore:
    def __init__(self, session_factory: async_sessionmaker, write_coordinator: SQLiteWriteCoordinator) -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator

    async def create(self, work_root: Path | str, name: str | None = None) -> tuple[CoreProjectRecord, bool]:
        name = _normalize_project_name(name)
        root = ensure_workspace_root(work_root)
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
        name = _normalize_project_name(name)
        root = ensure_workspace_root(work_root)
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
        name = _normalize_project_name(name, required=True)

        async def write(db: Any) -> CoreProjectRecord | None:
            project = await db.get(CoreProject, project_id)
            if project is None:
                return None
            project.name = name
            await db.flush()
            return _record(project)

        return await self.write_coordinator.run(write)

    async def create_session(self, project_id: str, *, title: str = "New Session") -> SessionRecord:
        """Create a session only after resolving its persisted project in the write transaction."""
        session_title = str(title).strip() or "New Session"

        async def write(db: Any) -> SessionRecord:
            project = await db.get(CoreProject, project_id)
            if project is None:
                raise LookupError("Project not found")
            return await _create_project_session(db, project, title=session_title)

        return await self.write_coordinator.run(write)

    async def ensure_session(
        self,
        work_root: Path | str,
        session_id: str,
        *,
        title: str,
    ) -> tuple[CoreProjectRecord, SessionRecord, bool]:
        """Bind a caller-owned session id to its workspace without creating a spare session."""
        root = ensure_workspace_root(work_root)
        normalized_root = str(root)
        session_title = str(title).strip() or session_id

        async def write(db: Any) -> tuple[CoreProjectRecord, SessionRecord, bool]:
            project = await db.scalar(select(CoreProject).where(CoreProject.work_root == normalized_root))
            created = project is None
            if project is None:
                project = CoreProject(
                    id=uuid4().hex,
                    name=_default_project_name(root),
                    work_root=normalized_root,
                )
                db.add(project)
                await db.flush()

            row = await db.get(CoreThreadSnapshot, session_id)
            if row is None:
                session = SessionRecord(
                    id=session_id,
                    member_id="core",
                    title=session_title,
                    status="idle",
                    metadata={"work_root": project.work_root},
                )
                db.add(
                    CoreThreadSnapshot(
                        thread_id=session.id,
                        snapshot_seq=0,
                        snapshot_json=session_snapshot(session),
                        updated_at=session.updated_at,
                    )
                )
            else:
                session = session_record_from_snapshot(row)
                if not session.title or session.title in {session.id, "New Session"}:
                    session.title = session_title
                session.metadata = {
                    **session.metadata,
                    "work_root": project.work_root,
                }
                state = dict(row.snapshot_json or {})
                state["session"] = {
                    "member_id": session.member_id,
                    "title": session.title,
                    "metadata": session.metadata,
                    "created_at": session.created_at.isoformat(),
                }
                row.snapshot_json = state
                row.updated_at = session.updated_at
            await db.flush()
            return _record(project), session, created

        return await self.write_coordinator.run(write)

    async def delete(self, project_id: str) -> bool:
        return await self._delete_with_sessions(project_id)

    async def list_sessions(self, project_id: str) -> list[SessionRecord]:
        async with self.session_factory() as db:
            project = await db.get(CoreProject, project_id)
            if project is None:
                return []
            return await _project_sessions(db, project.work_root)

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
        return read_workspace_agents_md(project.work_root)

    async def write_agents_md(self, project_id: str, content: str) -> dict[str, str | bool] | None:
        project = await self.get(project_id)
        if project is None:
            return None
        return write_workspace_agents_md(project.work_root, content)


def _default_project_name(work_root: Path) -> str:
    return workspace_name(work_root)


def _normalize_project_name(name: str | None, *, required: bool = False) -> str | None:
    if name is None:
        if required:
            raise ValueError("Project name is required")
        return None
    normalized = str(name).strip()
    if not normalized:
        if required:
            raise ValueError("Project name is required")
        return None
    return normalized


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
            name=name or _default_project_name(root),
            work_root=normalized_root,
        )
        db.add(project)
        await db.flush()

    sessions = await _project_sessions(db, project.work_root)
    if sessions:
        return _record(project), sessions[0], created

    session = await _create_project_session(db, project, title=project.name)
    return _record(project), session, created


async def _create_project_session(db: Any, project: CoreProject, *, title: str) -> SessionRecord:
    session = SessionRecord(
        id=uuid4().hex,
        member_id="core",
        title=title,
        status="idle",
        metadata={"work_root": project.work_root},
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
    return session


async def _delete_project_with_sessions(db: Any, project_id: str) -> bool:
    project = await db.get(CoreProject, project_id)
    if project is None:
        return False
    sessions = await _project_sessions(db, project.work_root)
    if any(session.status.lower() in {"running", "waiting", "interrupting"} for session in sessions):
        raise ActiveProjectSessionsError("Stop the active session before deleting the project")
    await delete_session_records(db, [session.id for session in sessions])
    await db.delete(project)
    return True


async def _project_sessions(db: Any, work_root: str) -> list[SessionRecord]:
    rows = (
        await db.execute(select(CoreThreadSnapshot).order_by(CoreThreadSnapshot.updated_at.desc()))
    ).scalars().all()
    sessions = [session_record_from_snapshot(row) for row in rows]
    owned = [session for session in sessions if session.metadata.get("work_root") == work_root]
    return sorted(owned, key=lambda session: (session.created_at, session.id))


__all__ = [
    "ActiveProjectSessionsError",
    "CoreProjectRecord",
    "CoreProjectStore",
    "ensure_workspace_root",
    "normalize_workspace_root",
    "read_workspace_agents_md",
    "workspace_name",
    "write_workspace_agents_md",
]
