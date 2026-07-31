from __future__ import annotations

from pathlib import Path

import pytest

from lamtools_core.app.core_db import CoreProject, CoreThreadSnapshot, open_core_app_db
from lamtools_core.config.migrate_projects import migrate_projects
from lamtools_core.config.root import default_projects_root
from lamtools_core.session import SessionRecord


async def _add_project(db, *, work_root: str, name: str, session_id: str | None = None) -> None:
    """Insert a project row (and optionally a bound session snapshot) directly."""
    from uuid import uuid4

    project = CoreProject(id=uuid4().hex, name=name, work_root=work_root)
    async with db.session_factory() as session:
        session.add(project)
        if session_id is not None:
            record = SessionRecord(
                id=session_id,
                member_id="core",
                title=name,
                status="idle",
                metadata={"work_root": work_root},
            )
            from lamtools_core.app.core_session_store import session_snapshot

            session.add(
                CoreThreadSnapshot(
                    thread_id=record.id,
                    snapshot_seq=0,
                    snapshot_json=session_snapshot(record),
                    updated_at=record.updated_at,
                )
            )
        await session.commit()


async def _project_rows(db):
    from sqlalchemy import select

    async with db.session_factory() as session:
        rows = (await session.execute(select(CoreProject).order_by(CoreProject.name))).scalars().all()
        return [(r.id, r.name, r.work_root) for r in rows]


async def _snapshot_work_roots(db):
    from sqlalchemy import select

    async with db.session_factory() as session:
        rows = (await session.execute(select(CoreThreadSnapshot))).scalars().all()
        result = []
        for row in rows:
            meta = (row.snapshot_json or {}).get("session", {}).get("metadata", {})
            result.append((row.thread_id, meta.get("work_root")))
        return result


async def test_dry_run_does_not_modify_db_or_filesystem(tmp_path, monkeypatch):
    monkeypatch.setenv("LAMTOOLS_PROJECTS_ROOT", str(tmp_path / "lam_projects"))
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        src = tmp_path / "real-proj"
        src.mkdir()
        await _add_project(db, work_root=str(src), name="real-proj")

        report = await migrate_projects(db, apply=False)

        assert report.applied is False
        assert len(report.actions) == 1
        assert report.actions[0].action == "moved"
        # Nothing changed yet.
        assert src.is_dir()
        rows = await _project_rows(db)
        assert rows[0][2] == str(src)
    finally:
        await db.close()


async def test_apply_moves_real_project_and_rewrites_session(tmp_path, monkeypatch):
    monkeypatch.setenv("LAMTOOLS_PROJECTS_ROOT", str(tmp_path / "lam_projects"))
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        src = tmp_path / "real-proj"
        src.mkdir()
        (src / "AGENTS.md").write_text("hello", encoding="utf-8")
        await _add_project(
            db, work_root=str(src), name="real-proj", session_id="sess-1"
        )

        report = await migrate_projects(db, apply=True)

        assert report.applied is True
        action = report.actions[0]
        assert action.action == "moved"
        # Old folder is gone, new folder exists with contents.
        assert not src.exists()
        new_root = Path(action.new_work_root)
        assert new_root.is_dir()
        assert (new_root / "AGENTS.md").read_text(encoding="utf-8") == "hello"
        # DB row updated.
        rows = await _project_rows(db)
        assert rows[0][2] == str(new_root)
        # Session snapshot metadata updated.
        snaps = await _snapshot_work_roots(db)
        assert snaps == [("sess-1", str(new_root))]
    finally:
        await db.close()


async def test_temp_residue_is_deleted(tmp_path, monkeypatch):
    monkeypatch.setenv("LAMTOOLS_PROJECTS_ROOT", str(tmp_path / "lam_projects"))
    # Force tempfile.gettempdir to our fake temp for the residue check.
    import lamtools_core.config.migrate_projects as mp

    monkeypatch.setattr(mp.tempfile, "gettempdir", lambda: str(tmp_path / "fake-temp"))
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        missing = tmp_path / "fake-temp" / "wf_retest_123"
        # Note: directory deliberately NOT created.
        await _add_project(
            db, work_root=str(missing), name="wf_retest_123", session_id="sess-residue"
        )

        report = await migrate_projects(db, apply=True)

        assert report.applied is True
        action = report.actions[0]
        assert action.action == "deleted"
        # Project row gone.
        rows = await _project_rows(db)
        assert rows == []
        # Session snapshot gone too.
        snaps = await _snapshot_work_roots(db)
        assert snaps == []
    finally:
        await db.close()


async def test_protected_repo_path_skips_move_but_updates_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LAMTOOLS_PROJECTS_ROOT", str(tmp_path / "lam_projects"))
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        # Point a project at the repo root (protected) — the migrate module's
        # _repo_root() resolves to the real repo root, so use that.
        from lamtools_core.config.migrate_projects import _repo_root

        repo = _repo_root()
        await _add_project(db, work_root=str(repo), name="LamTools")

        report = await migrate_projects(db, apply=True)

        action = report.actions[0]
        assert action.action == "skipped"
        # Repo folder untouched.
        assert repo.is_dir()
        # DB path rewritten to lam_projects.
        rows = await _project_rows(db)
        assert rows[0][2] == action.new_work_root
        assert "lam_projects" in action.new_work_root
    finally:
        await db.close()


async def test_missing_non_temp_source_updates_db_only(tmp_path, monkeypatch):
    monkeypatch.setenv("LAMTOOLS_PROJECTS_ROOT", str(tmp_path / "lam_projects"))
    # Point the system temp dir elsewhere so the missing source is NOT treated as
    # temp residue (pytest's tmp_path lives under the real temp dir on Windows).
    import lamtools_core.config.migrate_projects as mp

    monkeypatch.setattr(mp.tempfile, "gettempdir", lambda: str(tmp_path / "fake-temp"))
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        missing = tmp_path / "elsewhere" / "gone"
        # Not under the (faked) temp dir, and does not exist.
        await _add_project(db, work_root=str(missing), name="gone")

        report = await migrate_projects(db, apply=True)

        action = report.actions[0]
        assert action.action == "skipped"
        rows = await _project_rows(db)
        assert rows[0][2] == action.new_work_root
    finally:
        await db.close()


async def test_name_collision_gets_suffix(tmp_path, monkeypatch):
    monkeypatch.setenv("LAMTOOLS_PROJECTS_ROOT", str(tmp_path / "lam_projects"))
    db = await open_core_app_db(tmp_path / "core.db")
    try:
        src1 = tmp_path / "proj-a"
        src1.mkdir()
        src2 = tmp_path / "proj-b"
        src2.mkdir()
        await _add_project(db, work_root=str(src1), name="same-name")
        await _add_project(db, work_root=str(src2), name="same-name")

        report = await migrate_projects(db, apply=True)

        targets = [a.new_work_root for a in report.actions]
        assert len(set(targets)) == 2  # unique paths
        assert any("same-name" in t for t in targets)
        assert any("same-name_2" in t for t in targets)
    finally:
        await db.close()
