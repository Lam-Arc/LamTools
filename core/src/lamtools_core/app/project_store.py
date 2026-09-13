"""Persistent Core project records and their workspace instruction files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from lamtools_core.session import SessionRecord

from .core_db import CoreDbMetadata, CoreProject, CoreThreadSnapshot
from .core_session_store import delete_session_records, session_record_from_snapshot, session_snapshot
from .project_visuals import (
    DEFAULT_PROJECT_COLOR_KEY,
    DEFAULT_PROJECT_ICON_KEY,
    validate_project_color_key,
    validate_project_icon_key,
)
from .sqlite_write import SQLiteWriteCoordinator
from .runtime_permissions import with_session_runtime_preferences


@dataclass(frozen=True)
class CoreProjectRecord:
    id: str
    name: str
    work_root: str
    created_at: datetime
    updated_at: datetime
    icon_key: str = DEFAULT_PROJECT_ICON_KEY
    color_key: str = DEFAULT_PROJECT_COLOR_KEY
    workspace_id: str = ""
    revision: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "work_root": self.work_root,
            "icon_key": self.icon_key,
            "color_key": self.color_key,
            "workspace_id": self.workspace_id,
            "revision": self.revision,
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
    def __init__(
        self,
        session_factory: async_sessionmaker,
        write_coordinator: SQLiteWriteCoordinator,
        *,
        session_visible: Callable[[str, dict[str, Any]], bool] | None = None,
        project_roots: list[Path | str] | None = None,
        project_roots_file: Path | str | None = None,
        workspace_id: str = "",
        sync_journal: Any | None = None,
        sync_publisher: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.write_coordinator = write_coordinator
        self._session_visible = session_visible or (lambda _session_id, _metadata: True)
        self._project_roots_file = Path(project_roots_file).expanduser() if project_roots_file else None
        self._project_roots = self._load_project_roots(project_roots)
        self.workspace_id = str(workspace_id or "").strip()
        self._sync_journal = sync_journal
        self._sync_publisher = sync_publisher

    def project_roots(self) -> list[str]:
        return [str(root) for root in self._project_roots]

    def set_project_roots(self, roots: list[Path | str]) -> list[str]:
        normalized: list[Path] = []
        for value in roots:
            root = normalize_workspace_root(value)
            if root not in normalized:
                normalized.append(root)
        self._project_roots = normalized
        if self._project_roots_file is not None:
            self._project_roots_file.parent.mkdir(parents=True, exist_ok=True)
            self._project_roots_file.write_text(
                json.dumps(self.project_roots(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return self.project_roots()

    def _load_project_roots(self, configured: list[Path | str] | None) -> list[Path]:
        values: list[Path | str] | None = None
        if self._project_roots_file is not None and self._project_roots_file.is_file():
            try:
                raw = json.loads(self._project_roots_file.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    values = [item for item in raw if isinstance(item, str)]
            except (OSError, ValueError):
                values = None
        if values is None:
            values = configured
        normalized: list[Path] = []
        for value in values or []:
            try:
                root = normalize_workspace_root(value)
            except ValueError:
                continue
            if root not in normalized:
                normalized.append(root)
        return normalized

    def set_session_visibility(self, session_visible: Callable[[str, dict[str, Any]], bool]) -> None:
        """Attach the host's live plugin-session gate after database startup."""
        self._session_visible = session_visible

    def set_sync_publisher(self, publisher: Callable[[dict[str, Any]], Awaitable[None]] | None) -> None:
        """Attach the live global broadcaster after the app hub is created."""
        self._sync_publisher = publisher

    async def _publish_sync_changes(self, change_ids: list[str]) -> None:
        if self._sync_journal is None or self._sync_publisher is None:
            return
        for change_id in change_ids:
            change = await self._sync_journal.get_change(change_id)
            if change is not None:
                await self._sync_publisher({"method": "sync/change", "params": change})

    def _is_session_visible(self, session: SessionRecord) -> bool:
        try:
            return bool(self._session_visible(session.id, session.metadata))
        except Exception:  # noqa: BLE001 — keep unavailable plugin resources out of chat UI
            return not bool(str(session.metadata.get("owner_plugin") or "").strip())

    async def create(
        self,
        work_root: Path | str,
        name: str | None = None,
        *,
        icon_key: str = DEFAULT_PROJECT_ICON_KEY,
        color_key: str = DEFAULT_PROJECT_COLOR_KEY,
    ) -> tuple[CoreProjectRecord, bool]:
        name = _normalize_project_name(name)
        icon_key = validate_project_icon_key(icon_key)
        color_key = validate_project_color_key(color_key)
        root = normalize_workspace_root(work_root)
        root = ensure_workspace_root(root)
        normalized_root = str(root)

        change_ids: list[str] = []

        async def write(db: Any) -> tuple[CoreProjectRecord, bool]:
            change_ids.clear()
            project, _, created = await _create_project_with_initial_session(
                db,
                root=root,
                normalized_root=normalized_root,
                name=name,
                icon_key=icon_key,
                color_key=color_key,
                sync_journal=self._sync_journal,
                change_ids=change_ids,
            )
            return project, created

        result = await self.write_coordinator.run(write)
        await self._publish_sync_changes(change_ids)
        return result

    async def ensure_fallback_project(
        self,
        work_root: Path | str,
        *,
        name: str = "MyProject",
        reconcile_once: bool = False,
    ) -> tuple[CoreProjectRecord, int]:
        """Ensure the fallback project and bind every orphaned session to it."""
        root = normalize_workspace_root(work_root)
        root = ensure_workspace_root(root)
        normalized_root = str(root)
        project_name = _normalize_project_name(name) or "MyProject"
        maintenance_key = (
            "fallback_project_v1:"
            + hashlib.sha256(normalized_root.casefold().encode("utf-8")).hexdigest()
        )
        change_ids: list[str] = []

        async def write(db: Any) -> tuple[CoreProjectRecord, int]:
            change_ids.clear()
            project = await db.scalar(select(CoreProject).where(CoreProject.work_root == normalized_root))
            if project is None:
                project = CoreProject(
                    id=uuid4().hex,
                    workspace_id=self.workspace_id,
                    name=project_name,
                    work_root=normalized_root,
                    icon_key=DEFAULT_PROJECT_ICON_KEY,
                    color_key=DEFAULT_PROJECT_COLOR_KEY,
                )
                db.add(project)
                await db.flush()
                if self._sync_journal is not None:
                    change = self._sync_journal.append(
                        db,
                        entity_type="project",
                        operation="upsert",
                        entity_id=project.id,
                        revision=int(getattr(project, "revision", 1) or 1),
                        entity=_project_entity(project),
                    )
                    change_ids.append(change.change_id)

            migrated = 0
            maintenance_done = (
                reconcile_once
                and await db.get(CoreDbMetadata, maintenance_key) is not None
            )
            if not maintenance_done:
                project_roots = set((await db.execute(select(CoreProject.work_root))).scalars().all())
                rows = (
                    await db.execute(select(CoreThreadSnapshot).order_by(CoreThreadSnapshot.updated_at.asc()))
                ).scalars().all()
                for row in rows:
                    session = session_record_from_snapshot(row)
                    current_root = str(session.metadata.get("work_root") or "").strip()
                    if current_root in project_roots:
                        continue
                    session.metadata = with_session_runtime_preferences({
                        **session.metadata,
                        "work_root": normalized_root,
                    })
                    state = dict(row.snapshot_json or {})
                    session_state = dict(state.get("session") or {})
                    session_state["metadata"] = session.metadata
                    state["session"] = session_state
                    revision = int(getattr(row, "revision", 0) or state.get("revision") or 0) + 1
                    state["revision"] = revision
                    row.snapshot_json = state
                    flag_modified(row, "snapshot_json")
                    if hasattr(row, "revision"):
                        row.revision = revision
                    migrated += 1
                    if self._sync_journal is not None:
                        change = self._sync_journal.append(
                            db,
                            entity_type="thread",
                            operation="upsert",
                            entity_id=session.id,
                            thread_id=session.id,
                            revision=revision,
                            entity=_thread_entity(session, state, project.id),
                        )
                        change_ids.append(change.change_id)
                if reconcile_once:
                    db.add(CoreDbMetadata(
                        key=maintenance_key,
                        value="complete",
                        updated_at=datetime.now(),
                    ))
            await db.flush()
            return _record(project), migrated

        result = await self.write_coordinator.run(write)
        await self._publish_sync_changes(change_ids)
        return result

    async def create_with_initial_session(
        self,
        work_root: Path | str,
        name: str | None = None,
        *,
        icon_key: str = DEFAULT_PROJECT_ICON_KEY,
        color_key: str = DEFAULT_PROJECT_COLOR_KEY,
    ) -> tuple[CoreProjectRecord, SessionRecord, bool]:
        name = _normalize_project_name(name)
        icon_key = validate_project_icon_key(icon_key)
        color_key = validate_project_color_key(color_key)
        root = normalize_workspace_root(work_root)
        root = ensure_workspace_root(root)
        normalized_root = str(root)

        change_ids: list[str] = []

        async def write(db: Any) -> tuple[CoreProjectRecord, SessionRecord, bool]:
            change_ids.clear()
            return await _create_project_with_initial_session(
                db,
                root=root,
                normalized_root=normalized_root,
                name=name,
                icon_key=icon_key,
                color_key=color_key,
                sync_journal=self._sync_journal,
                change_ids=change_ids,
            )

        result = await self.write_coordinator.run(write)
        await self._publish_sync_changes(change_ids)
        return result

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

    async def rename(
        self,
        project_id: str,
        name: str,
        *,
        expected_revision: int | None = None,
    ) -> CoreProjectRecord | None:
        return await self.update(
            project_id,
            name=name,
            expected_revision=expected_revision,
        )

    async def update(
        self,
        project_id: str,
        *,
        name: str | None = None,
        icon_key: str | None = None,
        color_key: str | None = None,
        expected_revision: int | None = None,
    ) -> CoreProjectRecord | None:
        if name is None and icon_key is None and color_key is None:
            raise ValueError("At least one project field is required")
        normalized_name = _normalize_project_name(name, required=True) if name is not None else None
        normalized_icon_key = validate_project_icon_key(icon_key) if icon_key is not None else None
        normalized_color_key = validate_project_color_key(color_key) if color_key is not None else None

        change_ids: list[str] = []

        async def write(db: Any) -> CoreProjectRecord | None:
            change_ids.clear()
            project = await db.get(CoreProject, project_id)
            if project is None:
                return None
            current_revision = max(1, int(getattr(project, "revision", 1) or 1))
            if expected_revision is not None and int(expected_revision) != current_revision:
                raise ValueError(
                    f"REVISION_CONFLICT: expected {int(expected_revision)}, current {current_revision}"
                )
            if normalized_name is not None:
                project.name = normalized_name
            if normalized_icon_key is not None:
                project.icon_key = normalized_icon_key
            if normalized_color_key is not None:
                project.color_key = normalized_color_key
            project.revision = current_revision + 1
            await db.flush()
            if self._sync_journal is not None:
                change = self._sync_journal.append(
                    db,
                    entity_type="project",
                    operation="upsert",
                    entity_id=project.id,
                    revision=int(project.revision or 0),
                    entity=_project_entity(project),
                )
                change_ids.append(change.change_id)
            return _record(project)

        result = await self.write_coordinator.run(write)
        await self._publish_sync_changes(change_ids)
        return result

    async def create_session(self, project_id: str, *, title: str = "New Session") -> SessionRecord:
        """Create a session only after resolving its persisted project in the write transaction."""
        session_title = str(title).strip() or "New Session"

        change_ids: list[str] = []

        async def write(db: Any) -> SessionRecord:
            change_ids.clear()
            project = await db.get(CoreProject, project_id)
            if project is None:
                raise LookupError("Project not found")
            return await _create_project_session(
                db,
                project,
                title=session_title,
                sync_journal=self._sync_journal,
                change_ids=change_ids,
            )

        result = await self.write_coordinator.run(write)
        await self._publish_sync_changes(change_ids)
        return result

    async def ensure_session(
        self,
        work_root: Path | str,
        session_id: str,
        *,
        title: str,
    ) -> tuple[CoreProjectRecord, SessionRecord, bool]:
        """Bind a caller-owned session id to its workspace without creating a spare session."""
        root = normalize_workspace_root(work_root)
        root = ensure_workspace_root(root)
        normalized_root = str(root)
        session_title = str(title).strip() or session_id

        change_ids: list[str] = []

        async def write(db: Any) -> tuple[CoreProjectRecord, SessionRecord, bool]:
            change_ids.clear()
            project = await db.scalar(select(CoreProject).where(CoreProject.work_root == normalized_root))
            created = project is None
            if project is None:
                project = CoreProject(
                    id=uuid4().hex,
                    workspace_id=self.workspace_id,
                    name=_default_project_name(root),
                    work_root=normalized_root,
                    icon_key=DEFAULT_PROJECT_ICON_KEY,
                    color_key=DEFAULT_PROJECT_COLOR_KEY,
                )
                db.add(project)
                await db.flush()
                if self._sync_journal is not None:
                    change = self._sync_journal.append(
                        db,
                        entity_type="project",
                        operation="upsert",
                        entity_id=project.id,
                        entity=_project_entity(project),
                    )
                    change_ids.append(change.change_id)

            row = await db.get(CoreThreadSnapshot, session_id)
            session_created = row is None
            if row is None:
                session = SessionRecord(
                    id=session_id,
                    member_id="core",
                    title=session_title,
                    status="idle",
                    metadata=with_session_runtime_preferences({"work_root": project.work_root}),
                )
                state = session_snapshot(session)
                db.add(
                    CoreThreadSnapshot(
                        thread_id=session.id,
                        snapshot_seq=0,
                        revision=0,
                        snapshot_json=state,
                        updated_at=session.updated_at,
                    )
                )
            else:
                current_revision = await _session_revision(db, session_id)
                session = session_record_from_snapshot(row)
                if not session.title or session.title in {session.id, "New Session"}:
                    session.title = session_title
                session.metadata = {
                    **session.metadata,
                    "work_root": project.work_root,
                }
                session.metadata = with_session_runtime_preferences(session.metadata)
                state = dict(row.snapshot_json or {})
                state["session"] = {
                    "member_id": session.member_id,
                    "title": session.title,
                    "metadata": session.metadata,
                    "created_at": session.created_at.isoformat(),
                }
                state["revision"] = current_revision + 1
                row.snapshot_json = state
                if hasattr(row, "revision"):
                    row.revision = current_revision + 1
                row.updated_at = session.updated_at
            if self._sync_journal is not None and (session_created or created):
                change = self._sync_journal.append(
                    db,
                    entity_type="thread",
                    operation="upsert",
                    entity_id=session.id,
                    thread_id=session.id,
                    entity=_thread_entity(session, state, project.id),
                )
                change_ids.append(change.change_id)
            await db.flush()
            return _record(project), session, created

        result = await self.write_coordinator.run(write)
        await self._publish_sync_changes(change_ids)
        return result

    async def delete(self, project_id: str, *, expected_revision: int | None = None) -> bool:
        return await self._delete_with_sessions(project_id, expected_revision=expected_revision)

    async def list_sessions(self, project_id: str) -> list[SessionRecord]:
        async with self.session_factory() as db:
            project = await db.get(CoreProject, project_id)
            if project is None:
                return []
            sessions = await _project_sessions(db, project.work_root)
        return [session for session in sessions if self._is_session_visible(session)]

    async def delete_with_sessions(self, project_id: str, *, expected_revision: int | None = None) -> bool:
        return await self._delete_with_sessions(project_id, expected_revision=expected_revision)

    async def _delete_with_sessions(self, project_id: str, *, expected_revision: int | None = None) -> bool:
        change_ids: list[str] = []

        async def write(db: Any) -> bool:
            change_ids.clear()
            return await _delete_project_with_sessions(
                db,
                project_id,
                expected_revision=expected_revision,
                sync_journal=self._sync_journal,
                change_ids=change_ids,
            )

        result = bool(await self.write_coordinator.run(write))
        await self._publish_sync_changes(change_ids)
        return result

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
        icon_key=validate_project_icon_key(
            getattr(project, "icon_key", DEFAULT_PROJECT_ICON_KEY) or DEFAULT_PROJECT_ICON_KEY
        ),
        color_key=validate_project_color_key(
            getattr(project, "color_key", DEFAULT_PROJECT_COLOR_KEY) or DEFAULT_PROJECT_COLOR_KEY
        ),
        workspace_id=str(getattr(project, "workspace_id", "") or ""),
        revision=max(1, int(getattr(project, "revision", 1) or 1)),
    )


async def _create_project_with_initial_session(
    db: Any,
    *,
    root: Path,
    normalized_root: str,
    name: str | None,
    icon_key: str,
    color_key: str,
    sync_journal: Any | None = None,
    change_ids: list[str] | None = None,
) -> tuple[CoreProjectRecord, SessionRecord, bool]:
    project = await db.scalar(select(CoreProject).where(CoreProject.work_root == normalized_root))
    created = project is None
    if project is None:
        project = CoreProject(
            id=uuid4().hex,
            workspace_id=str(getattr(sync_journal, "workspace_id", "") or ""),
            name=name or _default_project_name(root),
            work_root=normalized_root,
            icon_key=icon_key,
            color_key=color_key,
        )
        db.add(project)
        await db.flush()
        if sync_journal is not None:
            change = sync_journal.append(
                db,
                entity_type="project",
                operation="upsert",
                entity_id=project.id,
                revision=int(getattr(project, "revision", 1) or 1),
                entity=_project_entity(project),
            )
            if change_ids is not None:
                change_ids.append(change.change_id)

    sessions = await _project_sessions(db, project.work_root)
    if sessions:
        return _record(project), sessions[0], created

    session = await _create_project_session(
        db,
        project,
        title=project.name,
        sync_journal=sync_journal,
        change_ids=change_ids,
    )
    return _record(project), session, created


async def _create_project_session(
    db: Any,
    project: CoreProject,
    *,
    title: str,
    sync_journal: Any | None = None,
    change_ids: list[str] | None = None,
) -> SessionRecord:
    session = SessionRecord(
        id=uuid4().hex,
        member_id="core",
        title=title,
        status="idle",
        metadata=with_session_runtime_preferences({"work_root": project.work_root}),
    )
    state = session_snapshot(session)
    db.add(
            CoreThreadSnapshot(
                thread_id=session.id,
                snapshot_seq=0,
                revision=0,
                snapshot_json=state,
            updated_at=session.updated_at,
        )
    )
    if sync_journal is not None:
        change = sync_journal.append(
            db,
        entity_type="thread",
        operation="upsert",
        entity_id=session.id,
        thread_id=session.id,
        revision=int(state.get("revision") or 0),
        entity=_thread_entity(session, state, project.id),
        )
        if change_ids is not None:
            change_ids.append(change.change_id)
    await db.flush()
    return session


async def _delete_project_with_sessions(
    db: Any,
    project_id: str,
    *,
    expected_revision: int | None = None,
    sync_journal: Any | None = None,
    change_ids: list[str] | None = None,
) -> bool:
    project = await db.get(CoreProject, project_id)
    if project is None:
        return False
    current_project_revision = max(1, int(getattr(project, "revision", 1) or 1))
    if expected_revision is not None and int(expected_revision) != current_project_revision:
        raise ValueError(
            f"REVISION_CONFLICT: expected {int(expected_revision)}, current {current_project_revision}"
        )
    sessions = await _project_sessions(db, project.work_root)
    if any(session.status.lower() in {"running", "waiting", "interrupting"} for session in sessions):
        raise ActiveProjectSessionsError("Stop the active session before deleting the project")
    if sync_journal is not None:
        change = sync_journal.append(
            db,
        entity_type="project",
        operation="delete",
        entity_id=project.id,
        revision=int(getattr(project, "revision", 1) or 1) + 1,
        entity={"id": project.id, "deleted": True},
        )
        if change_ids is not None:
            change_ids.append(change.change_id)
        for session in sessions:
            change = sync_journal.append(
                db,
                entity_type="thread",
                operation="delete",
                entity_id=session.id,
                thread_id=session.id,
                revision=int((await _session_revision(db, session.id)) or 0) + 1,
                entity={"id": session.id, "deleted": True},
            )
            if change_ids is not None:
                change_ids.append(change.change_id)
    await delete_session_records(db, [session.id for session in sessions])
    await db.delete(project)
    return True


def _project_entity(project: CoreProject) -> dict[str, Any]:
    return {
        "id": project.id,
        "workspace_id": str(getattr(project, "workspace_id", "") or ""),
        "name": project.name,
        "path": project.work_root,
        "work_root": project.work_root,
        "icon_key": validate_project_icon_key(
            getattr(project, "icon_key", DEFAULT_PROJECT_ICON_KEY) or DEFAULT_PROJECT_ICON_KEY
        ),
        "color_key": validate_project_color_key(
            getattr(project, "color_key", DEFAULT_PROJECT_COLOR_KEY) or DEFAULT_PROJECT_COLOR_KEY
        ),
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "revision": max(1, int(getattr(project, "revision", 1) or 1)),
        "deleted": False,
    }


def _thread_entity(session: SessionRecord, state: dict[str, Any], project_id: str) -> dict[str, Any]:
    return {
        "id": session.id,
        "project_id": project_id,
        "title": session.title,
        "status": session.status,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "metadata": dict(session.metadata),
        "snapshot": state,
        "revision": int(state.get("revision") or 0),
        "deleted": False,
    }


async def _project_sessions(db: Any, work_root: str) -> list[SessionRecord]:
    rows = (
        await db.execute(select(CoreThreadSnapshot).order_by(CoreThreadSnapshot.updated_at.desc()))
    ).scalars().all()
    sessions = [session_record_from_snapshot(row) for row in rows]
    owned = [session for session in sessions if session.metadata.get("work_root") == work_root]
    return sorted(owned, key=lambda session: (session.created_at, session.id))


async def _session_revision(db: Any, session_id: str) -> int:
    row = await db.get(CoreThreadSnapshot, session_id)
    if row is None:
        return 0
    value = getattr(row, "revision", None)
    if value is None:
        state = row.snapshot_json if isinstance(getattr(row, "snapshot_json", None), dict) else {}
        value = state.get("revision", 0)
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


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
