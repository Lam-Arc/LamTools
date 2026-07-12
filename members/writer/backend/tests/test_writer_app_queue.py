import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.app_server.hub import hub
from app.app_server.member_adapter import WriterLiveMemberAdapter
from app.app_server.persistence import _PERSISTENCE_HOST
from app.database import Base
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptTurn
from lamtools_core.app import CoreLiveContext, CoreLiveOperationHost, OperationCatalog
from lamtools_core.event import RunItemEvent
from lamtools_core.runtime import RuntimeTaskRegistry


class QueueRuntime:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run_accepted_turn(self, **_runtime_start):
        self.started.set()
        await self.release.wait()

    async def continue_resolved_approval(self, **_continuation):
        return None


def writer_context(session_factory, runtime, registry):
    return CoreLiveContext(
        operations=OperationCatalog(),
        host=CoreLiveOperationHost(
            session_factory=session_factory,
            persistence=_PERSISTENCE_HOST,
            hub=hub,
            runtime_task_registry=registry,
            member_hooks=WriterLiveMemberAdapter(session_factory=session_factory, runtime=runtime),
        ),
    )


@pytest.mark.asyncio
async def test_writer_queue_prepares_skill_input_but_core_owns_guidance(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-queue.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    skill_dir = tmp_path / ".codex" / "skills" / "reviewer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: reviewer\ndescription: Review code\n---\nREVIEW BODY\n",
        encoding="utf-8",
    )
    runtime = QueueRuntime()
    registry = RuntimeTaskRegistry()
    context = writer_context(session_factory, runtime, registry)
    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-1", title="Queue", work_root=str(tmp_path)))
            await db.commit()
        started = await context.host.execute(
            "turn.start",
            request_id=1,
            params={
                "thread_id": "thread-1",
                "client_message_id": "start-1",
                "input": [{"type": "text", "text": "start"}],
            },
            context=context,
        )
        await asyncio.wait_for(runtime.started.wait(), timeout=0.5)
        turn_id = started.response["result"]["runtime_start"]["turn_id"]
        queued = await context.host.execute(
            "queue.create",
            request_id=2,
            params={
                "thread_id": "thread-1",
                "client_message_id": "queue-1",
                "input": [{"type": "skill", "name": "reviewer", "source_text": "/reviewer"}],
            },
            context=context,
        )
        queue_item = queued.response["result"]["queue_item"]
        assert queue_item["input"] == [{"type": "text", "text": "/reviewer"}]
        assert "REVIEW BODY" in queue_item["runtime_input"][0]["text"]

        guided = await context.host.execute(
            "queue.guide",
            request_id=3,
            params={
                "thread_id": "thread-1",
                "turn_id": turn_id,
                "queue_item_id": queue_item["queue_item_id"],
                "client_message_id": "guide-1",
            },
            context=context,
        )
        assert guided.response["result"]["applied"] is True
        assert guided.response["result"]["snapshot"]["queue"] == []
        assert "REVIEW BODY" in registry.consume_guidance("thread-1", run_id=turn_id)[0]
    finally:
        runtime.release.set()
        registry.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_writer_queue_create_is_idempotent_through_core_host(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-queue-dedupe.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    runtime = QueueRuntime()
    registry = RuntimeTaskRegistry()
    context = writer_context(session_factory, runtime, registry)
    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-1", title="Queue"))
            await db.commit()
        params = {
            "thread_id": "thread-1",
            "client_message_id": "queue-1",
            "input": [{"type": "text", "text": "next"}],
        }
        first = await context.host.execute("queue.create", request_id=1, params=params, context=context)
        second = await context.host.execute("queue.create", request_id=2, params=params, context=context)
        assert first.response["result"]["events"][0]["event_id"] == second.response["result"]["events"][0]["event_id"]
        assert len(second.response["result"]["snapshot"]["queue"]) == 1
    finally:
        registry.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_writer_queue_update_persists_prepared_visible_and_runtime_input(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-queue-update.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    skill_dir = tmp_path / ".codex" / "skills" / "reviewer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: reviewer\ndescription: Review code\n---\nREVIEW BODY\n",
        encoding="utf-8",
    )
    runtime = QueueRuntime()
    registry = RuntimeTaskRegistry()
    context = writer_context(session_factory, runtime, registry)
    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-1", title="Queue", work_root=str(tmp_path)))
            await db.commit()
        created = await context.host.execute(
            "queue.create",
            request_id=1,
            params={
                "thread_id": "thread-1",
                "client_message_id": "queue-1",
                "input": [{"type": "text", "text": "plain"}],
            },
            context=context,
        )
        queue_item_id = created.response["result"]["queue_item"]["queue_item_id"]
        updated = await context.host.execute(
            "queue.update",
            request_id=2,
            params={
                "thread_id": "thread-1",
                "queue_item_id": queue_item_id,
                "input": [{"type": "skill", "name": "reviewer", "source_text": "/reviewer"}],
            },
            context=context,
        )
        item = updated.response["result"]["snapshot"]["queue"][0]
        assert item["input"] == [{"type": "text", "text": "/reviewer"}]
        assert "REVIEW BODY" in item["runtime_input"][0]["text"]
    finally:
        registry.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_dispatches_writer_next_turn_after_runtime_completion(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer-next-turn.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    skill_dir = tmp_path / ".codex" / "skills" / "reviewer"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\nname: reviewer\ndescription: Review code\n---\nDURABLE REVIEW BODY\n",
        encoding="utf-8",
    )
    registry = RuntimeTaskRegistry()

    class CompletingRuntime:
        def __init__(self):
            self.starts = []
            self.first_started = asyncio.Event()
            self.release_first = asyncio.Event()
            self.second_started = asyncio.Event()

        async def run_accepted_turn(self, **runtime_start):
            self.starts.append(runtime_start)
            if len(self.starts) == 1:
                self.first_started.set()
                await self.release_first.wait()
            else:
                self.second_started.set()

            async def write(db):
                await _PERSISTENCE_HOST.append_run_item(
                    db,
                    RunItemEvent(
                        kind="status",
                        thread_id=runtime_start["thread_id"],
                        event_id=f"{runtime_start['turn_id']}:completed-test",
                        run_id=runtime_start["turn_id"],
                        turn_id=runtime_start["turn_id"],
                        item_id=f"{runtime_start['turn_id']}:completed-test",
                        status="completed",
                        payload={"type": "turn", "status": "completed"},
                    ),
                )

            await _PERSISTENCE_HOST.write(write)

        async def continue_resolved_approval(self, **_continuation):
            return None

    runtime = CompletingRuntime()
    context = writer_context(session_factory, runtime, registry)
    try:
        async with session_factory() as db:
            db.add(WriterSession(id="thread-1", title="Queue", work_root=str(tmp_path)))
            await db.commit()
        await context.host.execute(
            "turn.start",
            request_id=1,
            params={
                "thread_id": "thread-1",
                "client_message_id": "start-1",
                "input": [{"type": "text", "text": "first"}],
            },
            context=context,
        )
        await asyncio.wait_for(runtime.first_started.wait(), timeout=0.5)
        await context.host.execute(
            "queue.create",
            request_id=2,
            params={
                "thread_id": "thread-1",
                "client_message_id": "queue-1",
                "input": [{"type": "skill", "name": "reviewer", "source_text": "/reviewer"}],
            },
            context=context,
        )
        skill_file.unlink()
        runtime.release_first.set()
        await asyncio.wait_for(runtime.second_started.wait(), timeout=1)

        async with session_factory() as db:
            turns = list((await db.execute(select(WriterTranscriptTurn))).scalars())
            snapshot = await _PERSISTENCE_HOST.load(db, "thread-1")
        assert len(turns) == 2
        assert "DURABLE REVIEW BODY" in runtime.starts[1]["text"]
        assert snapshot["queue"] == []
    finally:
        runtime.release_first.set()
        registry.clear()
        await engine.dispose()
