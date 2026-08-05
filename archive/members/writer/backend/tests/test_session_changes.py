import subprocess
import tempfile
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.core.writer.git import WriterGitManager
from app.models.session import WriterSession
from app.routers.session import (
    CommitReviewCreate,
    CommitReviewDecision,
    SessionCheckpointCreate,
    SessionCheckpointRestoreRequest,
    SessionUndoFileRequest,
    create_session_checkpoint,
    decide_commit_review,
    get_session_changes,
    list_session_checkpoints,
    request_commit_review,
    restore_session_checkpoint,
    undo_session_changes,
    undo_session_file_change,
)
from app.app_server.operations import handle_session_change_file_open_operation


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _git_stdout(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


@pytest.mark.asyncio
async def test_session_change_file_open_uses_default_app_for_work_root_file():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        work_root = root / "workspace"
        work_root.mkdir()
        target = work_root / "README.md"
        target.write_text("changed\n", encoding="utf-8")

        engine = create_async_engine(f"sqlite+aiosqlite:///{root / 'test.db'}", future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        opened: list[Path] = []

        async with session_factory() as db:
            db.add(
                WriterSession(
                    id="session-open-file",
                    title="Open file test",
                    work_root=str(work_root),
                )
            )
            await db.commit()

        outcome = await handle_session_change_file_open_operation(
            request_id=1,
            params={"session_id": "session-open-file", "path": "README.md"},
            session_factory=session_factory,
            opener=lambda path: opened.append(path),
        )

        assert outcome.response["result"]["status"] == "opened"
        assert outcome.response["result"]["path"] == "README.md"
        assert opened == [target.resolve()]
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_change_file_open_rejects_paths_outside_work_root():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        work_root = root / "workspace"
        work_root.mkdir()
        outside = root / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")

        engine = create_async_engine(f"sqlite+aiosqlite:///{root / 'test.db'}", future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            db.add(
                WriterSession(
                    id="session-open-outside-file",
                    title="Open outside file test",
                    work_root=str(work_root),
                )
            )
            await db.commit()

        outcome = await handle_session_change_file_open_operation(
            request_id=1,
            params={"session_id": "session-open-outside-file", "path": "../outside.txt"},
            session_factory=session_factory,
            opener=lambda path: None,
        )

        assert "error" in outcome.response
        assert "inside work_root" in outcome.response["error"]["message"]
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_changes_undo_restores_tracked_and_removes_untracked_files():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        work_root = root / "workspace"
        work_root.mkdir()

        _git(work_root, "init")
        _git(work_root, "config", "user.email", "writer@example.test")
        _git(work_root, "config", "user.name", "Writer Test")
        (work_root / "README.md").write_text("baseline\n", encoding="utf-8")
        (work_root / "user_original.txt").write_text("keep me\n", encoding="utf-8")
        _git(work_root, "add", ".")
        _git(work_root, "commit", "-m", "test: baseline")

        (work_root / "README.md").write_text("changed by writer\n", encoding="utf-8")
        (work_root / "writer_created_for_undo.txt").write_text("new file\n", encoding="utf-8")
        nested = work_root / "notes" / "draft.txt"
        nested.parent.mkdir()
        nested.write_text("nested new file\n", encoding="utf-8")

        engine = create_async_engine(f"sqlite+aiosqlite:///{root / 'test.db'}", future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            db.add(
                WriterSession(
                    id="session-undo",
                    title="Undo test",
                    work_root=str(work_root),
                )
            )
            await db.commit()

            changes = await get_session_changes("session-undo", db)
            changed_paths = {item.path for item in changes.files}
            assert "README.md" in changed_paths
            assert "writer_created_for_undo.txt" in changed_paths
            assert "notes/draft.txt" in changed_paths

            result = await undo_session_changes("session-undo", db)
            assert result.status == "undone"
            assert set(result.paths) == {
                "README.md",
                "writer_created_for_undo.txt",
                "notes/draft.txt",
            }

        assert (work_root / "README.md").read_text(encoding="utf-8") == "baseline\n"
        assert (work_root / "user_original.txt").read_text(encoding="utf-8") == "keep me\n"
        assert not (work_root / "writer_created_for_undo.txt").exists()
        assert not nested.exists()
        assert not nested.parent.exists()

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=work_root,
            check=True,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert status.stdout == ""

        await engine.dispose()


@pytest.mark.asyncio
async def test_session_changes_undo_single_file_keeps_other_review_changes():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        work_root = root / "workspace"
        work_root.mkdir()

        _git(work_root, "init")
        _git(work_root, "config", "user.email", "writer@example.test")
        _git(work_root, "config", "user.name", "Writer Test")
        (work_root / "README.md").write_text("baseline\n", encoding="utf-8")
        (work_root / "notes.txt").write_text("notes\n", encoding="utf-8")
        _git(work_root, "add", ".")
        _git(work_root, "commit", "-m", "test: baseline")

        (work_root / "README.md").write_text("changed by writer\n", encoding="utf-8")
        (work_root / "notes.txt").write_text("changed notes\n", encoding="utf-8")
        (work_root / "scratch.txt").write_text("new file\n", encoding="utf-8")

        engine = create_async_engine(f"sqlite+aiosqlite:///{root / 'test.db'}", future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            db.add(
                WriterSession(
                    id="session-undo-file",
                    title="Undo file test",
                    work_root=str(work_root),
                )
            )
            await db.commit()

            result = await undo_session_file_change(
                "session-undo-file",
                SessionUndoFileRequest(path="README.md"),
                db,
            )
            assert result.status == "undone"
            assert result.paths == ["README.md"]

            changes = await get_session_changes("session-undo-file", db)
            changed_paths = {item.path for item in changes.files}
            assert "README.md" not in changed_paths
            assert "notes.txt" in changed_paths
            assert "scratch.txt" in changed_paths

        assert (work_root / "README.md").read_text(encoding="utf-8") == "baseline\n"
        assert (work_root / "notes.txt").read_text(encoding="utf-8") == "changed notes\n"
        assert (work_root / "scratch.txt").exists()

        await engine.dispose()


@pytest.mark.asyncio
async def test_git_init_uses_child_work_root_not_parent_repo():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _git(root, "init")
        _git(root, "config", "user.email", "writer@example.test")
        _git(root, "config", "user.name", "Writer Test")
        (root / "parent.txt").write_text("parent\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-m", "test: parent")

        work_root = root / "workspace"
        work_root.mkdir()
        manager = WriterGitManager()

        assert await manager.init_repo(str(work_root))
        assert (work_root / ".git").exists()
        assert Path(_git_stdout(root, "rev-parse", "--show-toplevel")).resolve() == root.resolve()
        assert Path(_git_stdout(work_root, "rev-parse", "--show-toplevel")).resolve() == work_root.resolve()
        assert await manager.is_repo(str(work_root))


@pytest.mark.asyncio
async def test_git_worktree_created_inside_writer_dir_and_excluded_from_main_status():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        work_root = root / "workspace"
        work_root.mkdir()

        _git(work_root, "init")
        _git(work_root, "config", "user.email", "writer@example.test")
        _git(work_root, "config", "user.name", "Writer Test")
        (work_root / "README.md").write_text("baseline\n", encoding="utf-8")
        _git(work_root, "add", ".")
        _git(work_root, "commit", "-m", "test: baseline")

        manager = WriterGitManager()
        worktree_path = work_root / ".writer" / "worktrees" / "worker-test"
        created = await manager.create_worktree(
            str(work_root),
            branch="writer/agent/worker/test",
            path=str(worktree_path),
        )

        try:
            assert created
            assert await manager.is_repo(str(worktree_path))
            (worktree_path / "worker.txt").write_text("worker change\n", encoding="utf-8")
            assert "worker.txt" in _git_stdout(worktree_path, "status", "--porcelain")
            assert _git_stdout(work_root, "status", "--porcelain") == ""
        finally:
            await manager.run(str(work_root), ["worktree", "remove", "--force", str(worktree_path)])


@pytest.mark.asyncio
async def test_agent_branch_can_be_listed_diffed_merged_and_abandoned():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        work_root = root / "workspace"
        work_root.mkdir()

        _git(work_root, "init")
        _git(work_root, "config", "user.email", "writer@example.test")
        _git(work_root, "config", "user.name", "Writer Test")
        (work_root / "README.md").write_text("baseline\n", encoding="utf-8")
        _git(work_root, "add", ".")
        _git(work_root, "commit", "-m", "test: baseline")

        manager = WriterGitManager()
        worktree_path = work_root / ".writer" / "worktrees" / "worker-merge"
        branch = "writer/agent/worker/merge-test"
        assert await manager.create_worktree(str(work_root), branch=branch, path=str(worktree_path))
        (worktree_path / "worker.txt").write_text("worker change\n", encoding="utf-8")
        _git(worktree_path, "add", ".")
        _git(worktree_path, "commit", "-m", "test: worker change")

        listed = await manager.list_agent_branches(str(work_root))
        assert [item.branch for item in listed] == [branch]
        assert Path(listed[0].worktree).resolve() == worktree_path.resolve()
        assert "worker.txt" in listed[0].files

        diff = await manager.branch_diff(str(work_root), branch)
        assert diff is not None
        assert "worker.txt" in diff

        target = await manager.current_branch(str(work_root))
        assert target is not None
        merged = await manager.merge_branch(str(work_root), target, branch)
        assert merged is not None
        assert merged.success
        assert (work_root / "worker.txt").read_text(encoding="utf-8") == "worker change\n"

        assert await manager.abandon_agent_branch(str(work_root), branch)
        assert await manager.list_agent_branches(str(work_root)) == []


@pytest.mark.asyncio
async def test_commit_review_approval_creates_formal_commit():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        work_root = root / "workspace"
        work_root.mkdir()

        _git(work_root, "init")
        _git(work_root, "config", "user.email", "writer@example.test")
        _git(work_root, "config", "user.name", "Writer Test")
        (work_root / "README.md").write_text("baseline\n", encoding="utf-8")
        _git(work_root, "add", ".")
        _git(work_root, "commit", "-m", "test: baseline")
        (work_root / "README.md").write_text("accepted change\n", encoding="utf-8")

        engine = create_async_engine(f"sqlite+aiosqlite:///{root / 'test.db'}", future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            db.add(WriterSession(id="session-review", title="Review test", work_root=str(work_root)))
            await db.commit()

            review = await request_commit_review(
                "session-review",
                CommitReviewCreate(
                    title="README 更新",
                    summary="更新 README 的验收内容",
                    how_to_review="确认 README 内容符合预期",
                    self_check="已查看改动",
                    commit_message="test: accept readme update",
                ),
                db,
            )
            assert review.status == "pending"
            assert [item.path for item in review.files] == ["README.md"]

            approved = await decide_commit_review(
                "session-review",
                CommitReviewDecision(action="approve", commit_message="test: accept readme update"),
                db,
            )
            assert approved.status == "approved"
            assert approved.commit

        assert _git_stdout(work_root, "log", "-1", "--pretty=%s") == "test: accept readme update"
        assert _git_stdout(work_root, "status", "--porcelain") == ""
        await engine.dispose()


@pytest.mark.asyncio
async def test_checkpoint_create_list_and_restore():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        work_root = root / "workspace"
        work_root.mkdir()

        _git(work_root, "init")
        _git(work_root, "config", "user.email", "writer@example.test")
        _git(work_root, "config", "user.name", "Writer Test")
        (work_root / "note.txt").write_text("base\n", encoding="utf-8")
        _git(work_root, "add", ".")
        _git(work_root, "commit", "-m", "test: baseline")
        (work_root / "note.txt").write_text("checkpoint version\n", encoding="utf-8")

        engine = create_async_engine(f"sqlite+aiosqlite:///{root / 'test.db'}", future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as db:
            db.add(WriterSession(id="session-checkpoint", title="Checkpoint test", work_root=str(work_root)))
            await db.commit()

            checkpoint = await create_session_checkpoint(
                "session-checkpoint",
                SessionCheckpointCreate(reason="测试检查点"),
                db,
            )
            assert checkpoint.commit

            checkpoints = await list_session_checkpoints("session-checkpoint", db)
            assert checkpoints[0].commit == checkpoint.commit

            (work_root / "note.txt").write_text("broken version\n", encoding="utf-8")
            restored = await restore_session_checkpoint(
                "session-checkpoint",
                SessionCheckpointRestoreRequest(commit=checkpoint.commit),
                db,
            )
            assert restored.status == "undone"

        assert (work_root / "note.txt").read_text(encoding="utf-8") == "checkpoint version\n"
        await engine.dispose()


@pytest.mark.asyncio
async def test_checkpoint_is_stored_on_internal_branch_without_committing_user_branch():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        work_root = root / "workspace"
        work_root.mkdir()

        _git(work_root, "init")
        _git(work_root, "config", "user.email", "writer@example.test")
        _git(work_root, "config", "user.name", "Writer Test")
        (work_root / "note.txt").write_text("base\n", encoding="utf-8")
        _git(work_root, "add", ".")
        _git(work_root, "commit", "-m", "test: baseline")
        user_branch = _git_stdout(work_root, "branch", "--show-current")
        user_head = _git_stdout(work_root, "rev-parse", "HEAD")

        (work_root / "note.txt").write_text("checkpoint version\n", encoding="utf-8")
        (work_root / "created.txt").write_text("new file\n", encoding="utf-8")

        engine = create_async_engine(f"sqlite+aiosqlite:///{root / 'test.db'}", future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            async with session_factory() as db:
                db.add(WriterSession(id="session-checkpoint-isolated", title="Checkpoint test", work_root=str(work_root)))
                await db.commit()

                checkpoint = await create_session_checkpoint(
                    "session-checkpoint-isolated",
                    SessionCheckpointCreate(reason="内部检查点"),
                    db,
                )
                assert checkpoint.commit
                assert checkpoint.branch == "writer/checkpoint/session-checkpoint-isolated"

                session = await db.get(WriterSession, "session-checkpoint-isolated")
                assert session is not None
                assert session.branch is None

            assert _git_stdout(work_root, "branch", "--show-current") == user_branch
            assert _git_stdout(work_root, "rev-parse", "HEAD") == user_head
            assert "note.txt" in _git_stdout(work_root, "status", "--porcelain")
            assert "created.txt" in _git_stdout(work_root, "status", "--porcelain")
            assert _git_stdout(work_root, "rev-parse", "writer/checkpoint/session-checkpoint-isolated") == checkpoint.commit
            graph = await WriterGitManager().version_graph(str(work_root))
            assert graph is not None
            assert "writer/checkpoint/session-checkpoint-isolated" not in {lane.branch for lane in graph.lanes}

            (work_root / "note.txt").write_text("broken\n", encoding="utf-8")
            (work_root / "created.txt").unlink()

            async with session_factory() as db:
                restored = await restore_session_checkpoint(
                    "session-checkpoint-isolated",
                    SessionCheckpointRestoreRequest(commit=checkpoint.commit),
                    db,
                )
                assert restored.status == "undone"

            assert _git_stdout(work_root, "branch", "--show-current") == user_branch
            assert _git_stdout(work_root, "rev-parse", "HEAD") == user_head
            assert (work_root / "note.txt").read_text(encoding="utf-8") == "checkpoint version\n"
            assert (work_root / "created.txt").read_text(encoding="utf-8") == "new file\n"
        finally:
            await engine.dispose()
