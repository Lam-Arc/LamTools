"""Migrate existing project workspaces into the default lam_projects/ directory.

Each historical ``core_projects`` row is moved to ``lam_projects/<name>/`` and the
database references (project row, session snapshots, arrange jobs) are rewritten to
point at the new ``work_root``.

Safety rules (the migration never destroys the repo or unrelated data):

* If the source ``work_root`` is the repository root or its ``core/`` directory, the
  folder is left in place — only the DB row is updated to a fresh path under
  ``lam_projects/``.
* If the source ``work_root`` no longer exists *and* lives under the system temp
  directory, the project row (and its sessions) are deleted as stale residue.
* Otherwise the folder is physically moved with :func:`shutil.move`.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from .root import default_projects_root


@dataclass(frozen=True)
class MigrationAction:
    """The planned/applied outcome for a single project row."""

    project_id: str
    name: str
    action: str  # "moved" | "skipped" | "deleted" | "unchanged"
    old_work_root: str
    new_work_root: str = ""
    reason: str = ""


@dataclass
class MigrationReport:
    actions: list[MigrationAction] = field(default_factory=list)
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "actions": [a.__dict__ for a in self.actions],
        }


def _repo_root() -> Path:
    # config/migrate_projects.py → config → src/lamtools_core → core → repo root
    return Path(__file__).resolve().parents[4]


def _is_protected_path(work_root: Path) -> bool:
    """True for the repository root or its core/ directory (never move these)."""
    repo = _repo_root()
    try:
        resolved = work_root.resolve()
    except OSError:
        return False
    return resolved == repo or resolved == (repo / "core")


def _is_temp_residue(work_root: Path) -> bool:
    """True when a missing work_root lives under the system temp directory."""
    if work_root.exists():
        return False
    try:
        temp_base = Path(tempfile.gettempdir()).resolve()
        resolved = work_root.resolve()
    except OSError:
        return False
    try:
        resolved.relative_to(temp_base)
    except ValueError:
        return False
    return True


def _unique_target(base: Path, name: str, taken: set[str]) -> Path:
    """Return a non-conflicting target directory under ``base`` for ``name``."""
    candidate = base / name
    suffix = 2
    while str(candidate) in taken or candidate.exists():
        candidate = base / f"{name}_{suffix}"
        suffix += 1
    taken.add(str(candidate))
    return candidate


async def plan_project_migration(session: Any) -> list[MigrationAction]:
    """Compute the planned actions for every project row without touching the DB."""
    from lamtools_core.app.core_db import CoreProject

    rows = (
        await session.execute(select(CoreProject).order_by(CoreProject.created_at.asc()))
    ).scalars().all()

    target_root = default_projects_root()
    taken: set[str] = set()
    actions: list[MigrationAction] = []
    for row in rows:
        old = Path(row.work_root)
        if _is_protected_path(old):
            target = _unique_target(target_root, row.name or old.name, taken)
            actions.append(MigrationAction(
                project_id=row.id,
                name=row.name,
                action="skipped",
                old_work_root=str(old),
                new_work_root=str(target),
                reason="protected repo path; folder left in place, DB path updated",
            ))
        elif _is_temp_residue(old):
            actions.append(MigrationAction(
                project_id=row.id,
                name=row.name,
                action="deleted",
                old_work_root=str(old),
                reason="stale temp residue; directory missing",
            ))
        elif not old.exists():
            target = _unique_target(target_root, row.name or old.name, taken)
            actions.append(MigrationAction(
                project_id=row.id,
                name=row.name,
                action="skipped",
                old_work_root=str(old),
                new_work_root=str(target),
                reason="source directory missing; DB path updated",
            ))
        else:
            target = _unique_target(target_root, row.name or old.name, taken)
            actions.append(MigrationAction(
                project_id=row.id,
                name=row.name,
                action="moved",
                old_work_root=str(old),
                new_work_root=str(target),
            ))
    return actions


def _apply_filesystem_action(action: MigrationAction) -> None:
    """Perform the filesystem side of a planned action."""
    if action.action == "moved":
        target = Path(action.new_work_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(action.old_work_root), str(target))
    # "skipped" / "deleted" / "unchanged" need no filesystem work here.


async def _rewrite_db_references(session: Any, old_root: str, new_root: str) -> None:
    """Update work_root in session snapshots and arrange jobs after a move."""
    from sqlalchemy.orm.attributes import flag_modified

    from lamtools_core.app.core_db import CoreArrangeJob, CoreThreadSnapshot

    await session.execute(
        update(CoreArrangeJob)
        .where(CoreArrangeJob.work_root == old_root)
        .values(work_root=new_root)
    )
    # Session snapshots store work_root inside a JSON blob; filter in Python so the
    # migration is portable across SQLite JSON path support levels.
    rows = (
        await session.execute(select(CoreThreadSnapshot))
    ).scalars().all()
    for snap in rows:
        state = dict(snap.snapshot_json or {})
        sess_state = state.get("session") if isinstance(state.get("session"), dict) else None
        if not sess_state:
            continue
        metadata = sess_state.get("metadata") if isinstance(sess_state.get("metadata"), dict) else {}
        if metadata.get("work_root") != old_root:
            continue
        metadata["work_root"] = new_root
        sess_state["metadata"] = metadata
        state["session"] = sess_state
        snap.snapshot_json = state
        flag_modified(snap, "snapshot_json")


async def apply_project_migration(session: Any, actions: list[MigrationAction]) -> MigrationReport:
    """Execute the planned actions: move folders and rewrite DB references."""
    from lamtools_core.app.core_db import CoreProject, CoreThreadSnapshot
    from lamtools_core.app.core_session_store import delete_session_records, session_record_from_snapshot

    target_root = default_projects_root()
    target_root.mkdir(parents=True, exist_ok=True)

    applied: list[MigrationAction] = []
    for action in actions:
        if action.action == "deleted":
            project = await session.get(CoreProject, action.project_id)
            if project is not None:
                rows = (
                    await session.execute(
                        select(CoreThreadSnapshot).order_by(CoreThreadSnapshot.updated_at.desc())
                    )
                ).scalars().all()
                sessions = [session_record_from_snapshot(row) for row in rows]
                owned = [s for s in sessions if s.metadata.get("work_root") == project.work_root]
                await delete_session_records(session, [s.id for s in owned])
                await session.delete(project)
            applied.append(action)
            continue

        _apply_filesystem_action(action)

        project = await session.get(CoreProject, action.project_id)
        if project is not None:
            old_root = project.work_root
            project.work_root = action.new_work_root
            await session.flush()
            await _rewrite_db_references(session, old_root, action.new_work_root)
        applied.append(action)

    await session.commit()
    return MigrationReport(actions=applied, applied=True)


async def migrate_projects(db: Any, *, apply: bool = False) -> MigrationReport:
    """Plan (and optionally apply) migration of all projects into lam_projects/."""
    async with db.session_factory() as session:
        actions = await plan_project_migration(session)
        if not apply:
            return MigrationReport(actions=actions, applied=False)
        return await apply_project_migration(session, actions)
