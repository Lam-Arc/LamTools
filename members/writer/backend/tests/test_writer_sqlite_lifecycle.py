from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.models  # noqa: F401
from app.app_server.persistence import writer_persistence_host
from app.app_server.member_adapter import WriterLiveMemberAdapter
from app.app_server.operations import (
    handle_session_checkpoint_create_operation,
    handle_session_checkpoint_restore_operation,
    handle_session_commit_review_decide_operation,
    handle_session_create_operation,
    handle_session_rollback_turn_operation,
)
import app.app_server.operations as operations_module
from app.app_server.runtime import WriterRuntimeLifecycle
from app.config import Settings
from app.database import Base, create_writer_engine, writer_write, writer_write_coordinator
from app.models.app_server import WriterAppEvent
from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptBlock, WriterTranscriptTurn
from app.core.writer.git import WriterGitCheckpoint, WriterGitSnapshot
import app.services.checkpoint_service as checkpoint_service_module
import app.services.commit_review_service as commit_review_service_module
import app.services.session_rollback_service as rollback_service_module
from app.services.app_projection_sink import AppProjectionSink
from app.services.runtime_fact_recorder import RuntimeFactRecorder
from app.services.runtime_approved_tool import execute_approved_tool
import app.services.writer_service as writer_service_module
from app.services.writer_service import writer_orchestrate
from lamtools_core.app import CoreLiveContext, CoreLiveOperationHost, OperationCatalog
from lamtools_core.event import CoreEvent, RunItemEvent
from lamtools_core.llm import LLMResponse, LLMToolCall
from lamtools_core.tool.approval_continuation import resolve_waiting_decision
from lamtools_core.tool import ToolResult
from lamtools_core.runtime import RuntimeTaskRegistry, default_runtime_task_registry


class _CommittedEventHub:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
        self.event_ids: list[str] = []

    async def publish(self, event) -> None:
        async with self._session_factory() as db:
            persisted = await db.get(WriterAppEvent, event.event_id)
        assert persisted is not None
        self.event_ids.append(event.event_id)


def _run_item(*, thread_id: str, event_id: str, item_id: str) -> RunItemEvent:
    return RunItemEvent(
        kind="message",
        thread_id=thread_id,
        event_id=event_id,
        turn_id="turn-1",
        item_id=item_id,
        payload={"type": "agentMessage", "delta": event_id},
    )


class _WaitingRuntime:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run_accepted_turn(self, **_runtime_start) -> None:
        self.started.set()
        await self.release.wait()

    async def continue_resolved_approval(self, **_continuation) -> None:
        return None


class _BlockingGit:
    def __init__(self, blocked_method: str) -> None:
        self.blocked_method = blocked_method
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls: dict[str, int] = {}

    async def _block(self, method: str) -> None:
        self.calls[method] = self.calls.get(method, 0) + 1
        if method == self.blocked_method:
            self.started.set()
            await self.release.wait()

    async def init_repo(self, _work_root: str) -> bool:
        await self._block("init_repo")
        return True

    async def is_repo(self, _work_root: str) -> bool:
        await self._block("is_repo")
        return True

    async def status_snapshot(self, work_root: str) -> WriterGitSnapshot:
        await self._block("status_snapshot")
        return WriterGitSnapshot(work_root=work_root, is_git_repo=True, branch="main", head="head-1")

    async def checkpoint_all_to_branch(self, _work_root: str, _branch: str, **kwargs) -> WriterGitCheckpoint:
        await self._block("checkpoint_all_to_branch")
        return WriterGitCheckpoint(
            label=str(kwargs.get("label") or "checkpoint"),
            reason=str(kwargs.get("reason") or ""),
            branch="main",
            head="head-1",
            commit="checkpoint-1",
            base_head="head-1",
            storage="checkpoint_branch",
        )

    async def checkpoint_all(self, _work_root: str, **kwargs) -> WriterGitCheckpoint:
        await self._block("checkpoint_all")
        return WriterGitCheckpoint(
            label=str(kwargs.get("label") or "commit"),
            reason=str(kwargs.get("reason") or ""),
            branch="main",
            head="commit-1",
            commit="commit-1",
            base_head="head-1",
        )

    async def commit_paths(self, _work_root: str, _paths: list[str], **kwargs) -> WriterGitCheckpoint:
        await self._block("commit_paths")
        return WriterGitCheckpoint(
            label="commit",
            reason=str(kwargs.get("message") or ""),
            branch="main",
            head="commit-1",
            commit="commit-1",
            base_head="head-1",
        )

    async def restore_checkpoint(self, _work_root: str, _commit: str) -> bool:
        await self._block("restore_checkpoint")
        return True


@pytest.mark.asyncio
async def test_writer_engine_configures_sqlite_wal_busy_timeout_and_normal_sync(tmp_path):
    engine = create_writer_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-pragmas.db'}")

    try:
        async with engine.connect() as conn:
            journal_mode = (await conn.execute(text("PRAGMA journal_mode"))).scalar_one()
            busy_timeout = (await conn.execute(text("PRAGMA busy_timeout"))).scalar_one()
            synchronous = (await conn.execute(text("PRAGMA synchronous"))).scalar_one()

        assert str(journal_mode).lower() == "wal"
        assert busy_timeout == 5000
        assert synchronous == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_app_projection_sink_propagates_persistence_failure(tmp_path):
    engine = create_writer_engine(f"sqlite+aiosqlite:///{tmp_path / 'projection-error.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    coordinator = writer_write_coordinator(session_factory)

    async def fail_persistence(_db, _events):
        raise RuntimeError("projection write failed")

    projection = AppProjectionSink(
        session_factory=session_factory,
        write_coordinator=coordinator,
        persist_run_items=fail_persistence,
    )
    try:
        with pytest.raises(RuntimeError, match="projection write failed"):
            await projection.publish(
                [_run_item(thread_id="thread-error", event_id="event-error", item_id="item-error")],
                session_id="thread-error",
                source_event_id="source-error",
            )
    finally:
        await projection.close()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_name", "payload", "expected_status", "expected_reason"),
    [
        ("runtime.done", {"message": "done"}, "completed", "completed"),
        ("runtime.failed", {"error": "model failed"}, "failed", "runtime_error"),
    ],
)
async def test_persisted_core_terminal_event_derives_writer_terminal_fields(
    tmp_path,
    event_name,
    payload,
    expected_status,
    expected_reason,
):
    engine = create_writer_engine(f"sqlite+aiosqlite:///{tmp_path / f'{expected_status}.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    coordinator = writer_write_coordinator(session_factory)
    projection = AppProjectionSink(
        session_factory=session_factory,
        write_coordinator=coordinator,
        hub=_CommittedEventHub(session_factory),
    )
    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-terminal", title="Terminal", status="active", phase="executing"))
            db.add(WriterTranscriptTurn(
                id="turn-terminal",
                session_id="thread-terminal",
                sequence=1,
                user_text="hello",
                status_cache="running",
            ))
            await db.commit()

            recorder = RuntimeFactRecorder(
                db=db,
                session_id="thread-terminal",
                turn=await db.get(WriterTranscriptTurn, "turn-terminal"),
                app_projection_sink=projection,
                write_coordinator=coordinator,
            )
            await recorder.record_core_event(CoreEvent(
                name=event_name,
                category="lifecycle" if event_name == "runtime.done" else "error",
                payload=payload,
                session_id="thread-terminal",
                run_id="turn-terminal",
            ))

        async with session_factory() as db:
            session = await db.get(WriterSession, "thread-terminal")
            turn = await db.get(WriterTranscriptTurn, "turn-terminal")
            assert session.status == expected_status
            assert session.phase == expected_status
            assert turn.status_cache == expected_status
            assert turn.terminal_at is not None
            assert turn.terminal_reason == expected_reason
            if expected_status == "failed":
                assert turn.error == "model failed"
    finally:
        await projection.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_host_and_runtime_projection_share_one_writer_coordinator_with_continuous_sequences(tmp_path):
    engine = create_writer_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-concurrent.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    coordinator = writer_write_coordinator(session_factory)
    persistence = writer_persistence_host(session_factory)
    hub = _CommittedEventHub(session_factory)
    projection = AppProjectionSink(
        session_factory=session_factory,
        write_coordinator=coordinator,
        hub=hub,
    )

    async def append_core(index: int) -> None:
        async def write(db) -> None:
            await persistence.append_run_item(
                db,
                _run_item(
                    thread_id="thread-1",
                    event_id=f"core-{index}",
                    item_id=f"core-item-{index}",
                ),
            )

        await persistence.write(write)

    async def append_projection(index: int) -> None:
        await projection.publish(
            [
                _run_item(
                    thread_id="thread-1",
                    event_id=f"projection-{index}",
                    item_id=f"projection-item-{index}",
                )
            ],
            session_id="thread-1",
            source_event_id=f"source-{index}",
        )

    try:
        assert persistence.write_coordinator is coordinator
        await asyncio.gather(
            *(append_core(index) for index in range(50)),
            *(append_projection(index) for index in range(50)),
        )

        async with session_factory() as db:
            rows = list(
                (
                    await db.execute(
                        select(WriterAppEvent)
                        .where(WriterAppEvent.thread_id == "thread-1")
                        .order_by(WriterAppEvent.seq)
                    )
                ).scalars()
            )

        assert [row.seq for row in rows] == list(range(1, 101))
        assert len(hub.event_ids) == 50
    finally:
        await projection.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_writer_write_coordinator_isolated_by_database_path(tmp_path):
    first_engine = create_writer_engine(f"sqlite+aiosqlite:///{tmp_path / 'first.db'}")
    second_engine = create_writer_engine(f"sqlite+aiosqlite:///{tmp_path / 'second.db'}")
    first_factory = async_sessionmaker(first_engine, expire_on_commit=False)
    second_factory = async_sessionmaker(second_engine, expire_on_commit=False)
    first_entered = asyncio.Event()
    allow_first = asyncio.Event()
    second_completed = asyncio.Event()

    async def hold_first(_db) -> None:
        first_entered.set()
        await allow_first.wait()

    async def finish_second(_db) -> None:
        second_completed.set()

    first_task = asyncio.create_task(writer_write(hold_first, session_factory=first_factory))
    try:
        await asyncio.wait_for(first_entered.wait(), timeout=0.5)
        await asyncio.wait_for(writer_write(finish_second, session_factory=second_factory), timeout=0.5)
        assert second_completed.is_set()
    finally:
        allow_first.set()
        await first_task
        await first_engine.dispose()
        await second_engine.dispose()


@pytest.mark.asyncio
async def test_cancel_terminal_and_queue_start_share_the_writer_lifecycle_transaction_path(tmp_path):
    engine = create_writer_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-cancel-queue.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    persistence = writer_persistence_host(session_factory)
    runtime = _WaitingRuntime()
    registry = RuntimeTaskRegistry()
    lifecycle = WriterRuntimeLifecycle(session_factory=session_factory, runtime_task_registry=registry)
    context = CoreLiveContext(
        operations=OperationCatalog(),
        host=CoreLiveOperationHost(
            session_factory=session_factory,
            persistence=persistence,
            runtime_task_registry=registry,
            member_hooks=WriterLiveMemberAdapter(session_factory=session_factory, runtime=runtime),
        ),
    )

    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-1", title="Lifecycle"))
            await db.commit()

        started = await context.host.execute(
            "turn.start",
            request_id=1,
            params={
                "thread_id": "thread-1",
                "client_message_id": "start-1",
                "input": [{"type": "text", "text": "first"}],
            },
            context=context,
        )
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        await asyncio.wait_for(runtime.started.wait(), timeout=0.5)

        cancelled, queued, terminal = await asyncio.gather(
            context.host.execute(
                "turn.cancel",
                request_id=2,
                params={"thread_id": "thread-1", "turn_id": turn_id},
                context=context,
            ),
            context.host.execute(
                "queue.create",
                request_id=3,
                params={
                    "thread_id": "thread-1",
                    "client_message_id": "queue-1",
                    "input": [{"type": "text", "text": "next"}],
                },
                context=context,
            ),
            context.host.execute(
                "queue.create",
                request_id=4,
                params={
                    "thread_id": "thread-1",
                    "client_message_id": "queue-2",
                    "input": [{"type": "text", "text": "later"}],
                },
                context=context,
            ),
        )
        assert cancelled.response["result"]["events"]
        assert queued.response["result"]["queue_item"]["status"] == "queued"
        assert terminal.response["result"]["queue_item"]["status"] == "queued"

        async with session_factory() as db:
            rows = list(
                (
                    await db.execute(
                        select(WriterAppEvent)
                        .where(WriterAppEvent.thread_id == "thread-1")
                        .order_by(WriterAppEvent.seq)
                    )
                ).scalars()
            )
        assert [row.seq for row in rows] == list(range(1, len(rows) + 1))
    finally:
        runtime.release.set()
        registry.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_writer_runtime_propagates_member_exception_to_core(tmp_path):
    engine = create_writer_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-runtime-error.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def fail_run_turn(**_kwargs):
        raise RuntimeError("model transport failed")

    lifecycle = WriterRuntimeLifecycle(
        session_factory=session_factory,
        service_provider=lambda: {"run_turn": fail_run_turn},
    )
    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-error", title="Error"))
            await db.commit()
        with pytest.raises(RuntimeError, match="model transport failed"):
            await lifecycle.run_accepted_turn(
                thread_id="thread-error",
                turn_id="turn-error",
                user_message_id="message-error",
                text="fail",
            )
    finally:
        await engine.dispose()


def test_agent_lifecycle_modules_have_no_direct_commit():
    app_root = Path(__file__).parents[1] / "app"
    lifecycle_files = [
        app_root / "services" / "writer_service.py",
        app_root / "services" / "runtime_runner.py",
        app_root / "services" / "runtime_approved_tool.py",
        app_root / "services" / "runtime_finalization_sink.py",
        app_root / "services" / "checkpoint_service.py",
        app_root / "services" / "commit_review_service.py",
        app_root / "services" / "session_management.py",
        app_root / "services" / "session_fork_service.py",
        app_root / "services" / "session_rollback_service.py",
        app_root / "app_server" / "runtime.py",
        app_root / "app_server" / "operations.py",
    ]
    offenders = [
        str(path.relative_to(app_root))
        for path in lifecycle_files
        if ".commit(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


@pytest.mark.asyncio
async def test_approved_tool_execution_does_not_hold_writer_write_lock(tmp_path):
    engine = create_writer_engine(f"sqlite+aiosqlite:///{tmp_path / 'approved-tool-lock.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    coordinator = writer_write_coordinator(session_factory)
    started = asyncio.Event()
    release = asyncio.Event()
    tool_executions = 0

    async def seed(db):
        db.add(WriterSession(id="thread-tool", title="Tool", work_root=str(tmp_path)))

    await coordinator.run(seed)

    async def blocking_handler(_call):
        nonlocal tool_executions
        tool_executions += 1
        started.set()
        await release.wait()
        return ToolResult(call_id="call-tool", name="run_command", status="ok", content="ok")

    tool_task = asyncio.create_task(execute_approved_tool(
        {"id": "call-tool", "name": "run_command", "arguments": {"command": "echo ok"}},
        work_root=str(tmp_path),
        handler=blocking_handler,
    ))
    try:
        await asyncio.wait_for(started.wait(), timeout=0.5)

        async def concurrent_write(db):
            session = await db.get(WriterSession, "thread-tool")
            session.title = "queue/cancel completed"

        await asyncio.wait_for(coordinator.run(concurrent_write), timeout=0.5)
        release.set()
        execution = await tool_task
        async with session_factory() as db:
            session = await db.get(WriterSession, "thread-tool")
        assert session.title == "queue/cancel completed"
        assert execution.completed
        assert tool_executions == 1
    finally:
        release.set()
        if not tool_task.done():
            await tool_task
        await engine.dispose()


async def _assert_concurrent_writer_write_completes(coordinator, git: _BlockingGit, operation_task) -> None:
    try:
        await asyncio.wait_for(git.started.wait(), timeout=2.0)

        async def concurrent_write(db):
            session = await db.get(WriterSession, "concurrent-write")
            session.title = "completed while git blocked"

        await asyncio.wait_for(coordinator.run(concurrent_write), timeout=0.5)
    finally:
        git.release.set()
        await operation_task


@pytest.mark.asyncio
async def test_checkpoint_create_does_not_hold_writer_write_lock(monkeypatch, tmp_path):
    engine = create_writer_engine(f"sqlite+aiosqlite:///{tmp_path / 'checkpoint-create-lock.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    coordinator = writer_write_coordinator(session_factory)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await coordinator.run(lambda db: _seed_git_session(db, "checkpoint-create", tmp_path))
    git = _BlockingGit("checkpoint_all_to_branch")
    monkeypatch.setattr(checkpoint_service_module, "_default_git_manager", git)
    task = asyncio.create_task(handle_session_checkpoint_create_operation(
        request_id=1,
        params={"session_id": "checkpoint-create", "reason": "manual"},
        session_factory=session_factory,
    ))
    try:
        await _assert_concurrent_writer_write_completes(coordinator, git, task)
        assert git.calls["checkpoint_all_to_branch"] == 1
    finally:
        git.release.set()
        if not task.done():
            await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_checkpoint_restore_does_not_hold_writer_write_lock(monkeypatch, tmp_path):
    engine = create_writer_engine(f"sqlite+aiosqlite:///{tmp_path / 'checkpoint-restore-lock.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    coordinator = writer_write_coordinator(session_factory)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await coordinator.run(lambda db: _seed_git_session(db, "checkpoint-restore", tmp_path, checkpoint=True))
    git = _BlockingGit("restore_checkpoint")
    monkeypatch.setattr(checkpoint_service_module, "_default_git_manager", git)
    task = asyncio.create_task(handle_session_checkpoint_restore_operation(
        request_id=2,
        params={"session_id": "checkpoint-restore", "commit": "checkpoint-1"},
        session_factory=session_factory,
    ))
    try:
        await _assert_concurrent_writer_write_completes(coordinator, git, task)
        assert git.calls["restore_checkpoint"] == 1
    finally:
        git.release.set()
        if not task.done():
            await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_commit_review_approve_does_not_hold_writer_write_lock(monkeypatch, tmp_path):
    engine = create_writer_engine(f"sqlite+aiosqlite:///{tmp_path / 'review-lock.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    coordinator = writer_write_coordinator(session_factory)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await coordinator.run(lambda db: _seed_review_session(db, tmp_path))
    git = _BlockingGit("checkpoint_all")
    monkeypatch.setattr(commit_review_service_module, "_default_git_manager", git)
    task = asyncio.create_task(handle_session_commit_review_decide_operation(
        request_id=3,
        params={"session_id": "review-session", "action": "approve"},
        session_factory=session_factory,
    ))
    try:
        await _assert_concurrent_writer_write_completes(coordinator, git, task)
        assert git.calls["checkpoint_all"] == 1
    finally:
        git.release.set()
        if not task.done():
            await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_session_rollback_does_not_hold_writer_write_lock(monkeypatch, tmp_path):
    engine = create_writer_engine(f"sqlite+aiosqlite:///{tmp_path / 'rollback-lock.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    coordinator = writer_write_coordinator(session_factory)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await coordinator.run(lambda db: _seed_rollback_session(db, tmp_path))
    git = _BlockingGit("restore_checkpoint")
    monkeypatch.setattr(rollback_service_module, "_git_manager", git)
    task = asyncio.create_task(handle_session_rollback_turn_operation(
        request_id=4,
        params={"session_id": "rollback-session", "turn_id": "rollback-turn"},
        session_factory=session_factory,
    ))
    try:
        await _assert_concurrent_writer_write_completes(coordinator, git, task)
        assert git.calls["restore_checkpoint"] == 1
    finally:
        git.release.set()
        if not task.done():
            await task
        await engine.dispose()


@pytest.mark.asyncio
async def test_waiting_decision_is_core_owned(tmp_path):
    del tmp_path
    resolved = resolve_waiting_decision("guide", "continue safely")
    assert resolved.action == "guide"
    assert resolved.guidance_text == "continue safely"


@pytest.mark.asyncio
async def test_blocked_writer_run_with_fifty_queue_cancel_projection_writes_is_consistent(tmp_path):
    engine = create_writer_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-50-way.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    coordinator = writer_write_coordinator(session_factory)
    persistence = writer_persistence_host(session_factory)
    projection = AppProjectionSink(
        session_factory=session_factory, write_coordinator=coordinator, hub=_CommittedEventHub(session_factory),
    )
    runtime = _WaitingRuntime()
    registry = RuntimeTaskRegistry()
    context = CoreLiveContext(
        operations=OperationCatalog(),
        host=CoreLiveOperationHost(
            session_factory=session_factory, persistence=persistence,
            runtime_task_registry=registry,
            member_hooks=WriterLiveMemberAdapter(session_factory=session_factory, runtime=runtime),
        ),
    )
    await coordinator.run(lambda db: _add_session(db, "thread-50"))
    started = await context.host.execute(
        "turn.start", request_id=1,
        params={"thread_id": "thread-50", "client_message_id": "start-50", "input": [{"type": "text", "text": "main"}]},
        context=context,
    )
    turn_id = started.response["result"]["runtime_start"]["turn_id"]
    await asyncio.wait_for(runtime.started.wait(), timeout=0.5)

    async def queue(index: int):
        return await context.host.execute(
            "queue.create", request_id=100 + index,
            params={"thread_id": "thread-50", "client_message_id": f"queue-{index}", "input": [{"type": "text", "text": f"q{index}"}]},
            context=context,
        )

    async def cancel(index: int):
        return await context.host.execute(
            "turn.cancel", request_id=200 + index,
            params={"thread_id": "thread-50", "turn_id": turn_id}, context=context,
        )

    async def project(index: int):
        return await projection.publish(
            [_run_item(thread_id="thread-50", event_id=f"projection-50-{index}", item_id=f"projection-item-50-{index}")],
            session_id="thread-50", source_event_id=f"projection-source-50-{index}",
        )

    try:
        await asyncio.gather(
            *(queue(index) for index in range(20)),
            *(cancel(index) for index in range(10)),
            *(project(index) for index in range(20)),
        )
        async with session_factory() as db:
            rows = list((await db.execute(
                select(WriterAppEvent).where(WriterAppEvent.thread_id == "thread-50").order_by(WriterAppEvent.seq)
            )).scalars())
            turns = list((await db.execute(
                select(WriterTranscriptTurn).where(WriterTranscriptTurn.session_id == "thread-50")
            )).scalars())
        assert [row.seq for row in rows] == list(range(1, len(rows) + 1))
        assert len(turns) == 1 and turns[0].user_text == "main"
    finally:
        runtime.release.set()
        registry.clear()
        await projection.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_writer_runtime_terminal_and_concurrent_steer_writes_are_consistent(monkeypatch, tmp_path):
    class _DeterministicLLMClient:
        def __init__(self) -> None:
            self._responses = [
                LLMResponse(
                    content="",
                    tool_calls=[
                        LLMToolCall(
                            id="run-terminal-command",
                            name="run_tests",
                            arguments={
                                "command": (
                                    "py -3.14 -c \"from pathlib import Path; import time; "
                                    "Path('terminal.started').write_text('started', encoding='utf-8'); "
                                    "time.sleep(0.75); print('terminal-ok')\""
                                )
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                LLMResponse(content="terminal command completed", finish_reason="stop"),
            ]

        async def complete(self, _request):
            return self._responses.pop(0)

        async def stream(self, _request):
            raise NotImplementedError

    async def _resolve_llm_config(_db, _route, model_id=None):
        del model_id
        return {"provider": "test", "model": "test-model"}

    def _build_llm_client(_resolved, thinking_enabled=None, thinking_budget=None):
        del thinking_enabled, thinking_budget
        return _DeterministicLLMClient()

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _build_llm_client)

    work_root = tmp_path / "workspace"
    work_root.mkdir()
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'writer-real-runtime.db'}"
    settings = Settings(data_dir=str(tmp_path / "data"), database_url=database_url, llm_api_key="test")
    engine = create_writer_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    thread_id = "thread-real-runtime"
    registry = default_runtime_task_registry()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    services = writer_orchestrate(settings, config_session_factory=session_factory)
    lifecycle = WriterRuntimeLifecycle(
        session_factory=session_factory,
        service_provider=lambda: services,
        runtime_task_registry=registry,
    )
    context = CoreLiveContext(
        operations=OperationCatalog(),
        host=CoreLiveOperationHost(
            session_factory=session_factory,
            persistence=writer_persistence_host(session_factory),
            runtime_task_registry=registry,
            member_hooks=WriterLiveMemberAdapter(session_factory=session_factory, runtime=lifecycle),
        ),
    )

    try:
        async with session_factory() as db:
            db.add(WriterSession(id=thread_id, title="Real runtime", work_root=str(work_root)))
            await db.commit()

        started = await context.host.execute(
            "turn.start",
            request_id=1,
            params={
                "thread_id": thread_id,
                "client_message_id": "real-runtime-start",
                "input": [{"type": "text", "text": "run the terminal command"}],
            },
            context=context,
        )
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        runtime_task = registry.task(thread_id, run_id=turn_id)
        assert runtime_task is not None

        terminal_started = work_root / "terminal.started"
        for _ in range(500):
            if terminal_started.exists():
                break
            if runtime_task.done():
                await runtime_task
            await asyncio.sleep(0.02)
        assert terminal_started.read_text(encoding="utf-8") == "started"

        steer_results = await asyncio.gather(
            *(
                context.host.execute(
                    "turn.steer",
                    request_id=100 + index,
                    params={
                        "thread_id": thread_id,
                        "turn_id": turn_id,
                        "client_message_id": f"steer-{index}",
                        "input": [{"type": "text", "text": f"guidance {index}"}],
                    },
                    context=context,
                )
                for index in range(12)
            )
        )
        assert all(result.response["result"]["applied"] is True for result in steer_results)

        await asyncio.wait_for(runtime_task, timeout=5)

        async with session_factory() as db:
            events = list(
                (
                    await db.execute(
                        select(WriterAppEvent)
                        .where(WriterAppEvent.thread_id == thread_id)
                        .order_by(WriterAppEvent.seq)
                    )
                ).scalars()
            )
            session = await db.get(WriterSession, thread_id)
            turn = await db.get(WriterTranscriptTurn, turn_id)
            messages = list(
                (
                    await db.execute(
                        select(WriterMessage)
                        .where(WriterMessage.session_id == thread_id)
                        .order_by(WriterMessage.created_at)
                    )
                ).scalars()
            )
            blocks = list(
                (
                    await db.execute(
                        select(WriterTranscriptBlock).where(WriterTranscriptBlock.turn_id == turn_id)
                    )
                ).scalars()
            )

        terminal_events = [
            event
            for event in events
            if event.turn_id == turn_id
            and event.item_id == f"{turn_id}:terminal"
            and event.payload_json.get("status") == "completed"
        ]
        command_blocks = [
            block
            for block in blocks
            if block.type == "tool_result" and block.tool_name == "run_tests"
        ]

        assert [event.seq for event in events] == list(range(1, len(events) + 1))
        assert len(terminal_events) == 1
        assert len(command_blocks) == 1
        assert command_blocks[0].status == "completed"
        assert {
            block.tool_name
            for block in blocks
            if block.type in {"tool_call", "tool_result"}
        } == {"run_tests"}
        assert session is not None and session.status == "completed" and session.phase == "completed"
        assert turn is not None and turn.status_cache == "completed" and turn.terminal_reason == "completed"
        assert [message.role for message in messages] == ["user", "assistant"]
        assert messages[-1].content == "terminal command completed"
    finally:
        registry.release_run(thread_id, run_id=registry.active_run_id(thread_id) or "")
        registry.get_cancel_event(thread_id).clear()
        await engine.dispose()


async def _add_session(db, session_id: str) -> None:
    db.add(WriterSession(id=session_id, title="Concurrent"))


async def _seed_concurrent_session(db) -> None:
    db.add(WriterSession(id="concurrent-write", title="waiting"))


async def _seed_git_session(db, session_id: str, work_root: Path, *, checkpoint: bool = False) -> None:
    runtime_state = {}
    if checkpoint:
        runtime_state = {
            "git_state": {
                "checkpoints": [
                    {
                        "label": "checkpoint",
                        "commit": "checkpoint-1",
                        "head": "head-1",
                        "base_head": "head-1",
                        "storage": "checkpoint_branch",
                    }
                ]
            }
        }
    db.add_all([
        WriterSession(id=session_id, title="Git", work_root=str(work_root), runtime_state=runtime_state),
        WriterSession(id="concurrent-write", title="waiting"),
    ])


async def _seed_review_session(db, work_root: Path) -> None:
    db.add_all([
        WriterSession(
            id="review-session",
            title="Review",
            work_root=str(work_root),
            runtime_state={
                "pending_commit_review": {
                    "id": "review-1",
                    "status": "pending",
                    "head": "head-1",
                    "dirty_hashes": {},
                    "files": [],
                    "commit_message": "test: review",
                }
            },
        ),
        WriterSession(id="concurrent-write", title="waiting"),
    ])


async def _seed_rollback_session(db, work_root: Path) -> None:
    db.add_all([
        WriterSession(
            id="rollback-session",
            title="Rollback",
            work_root=str(work_root),
            runtime_state={
                "git_state": {
                    "checkpoints": [
                        {
                            "commit": "checkpoint-1",
                            "turn_id": "rollback-turn",
                            "stage": "before_turn",
                        }
                    ]
                }
            },
        ),
        WriterTranscriptTurn(
            id="rollback-turn",
            session_id="rollback-session",
            sequence=1,
            user_text="change",
            status_cache="completed",
        ),
        WriterSession(id="concurrent-write", title="waiting"),
    ])


@pytest.mark.asyncio
async def test_replayed_runtime_fact_keeps_transcript_event_and_snapshot_idempotent(tmp_path):
    engine = create_writer_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-retry.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    coordinator = writer_write_coordinator(session_factory)
    projection = AppProjectionSink(
        session_factory=session_factory,
        write_coordinator=coordinator,
        hub=_CommittedEventHub(session_factory),
    )
    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-1", title="Retry"))
            db.add(WriterTranscriptTurn(id="turn-1", session_id="thread-1", sequence=1, user_text="hello"))
            await db.commit()

            recorder = RuntimeFactRecorder(
                db=db,
                session_id="thread-1",
                turn=await db.get(WriterTranscriptTurn, "turn-1"),
                app_projection_sink=projection,
                write_coordinator=coordinator,
            )
            await recorder.start_runtime_producer()
            fact = CoreEvent(
                name="runtime.reply_delta",
                category="progress",
                payload={"turn_id": "turn-1", "part_id": "reply-1", "content": "hello"},
                session_id="thread-1",
                run_id="turn-1",
                sequence=1,
            )
            await recorder.record_core_event(fact)
            await recorder.record_core_event(fact)

        async with session_factory() as db:
            block = await db.get(WriterTranscriptBlock, "reply-1")
            events = list(
                (
                    await db.execute(
                        select(WriterAppEvent).where(WriterAppEvent.thread_id == "thread-1")
                    )
                ).scalars()
            )

        assert block is not None and block.content == "hello"
        assert len(events) == 1
    finally:
        await projection.close()
        await engine.dispose()
