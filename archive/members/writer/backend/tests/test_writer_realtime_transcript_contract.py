import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.database import Base
from app.models.session import WriterSession
from app.services.transcript_service import project_transcript
import app.services.writer_service as writer_service_module
from app.services.writer_service import writer_orchestrate
from lamtools_core.event import CoreEvent
from lamtools_core.kernel import KernelResult


def _install_replay_kernel(monkeypatch, replay):
    async def _resolve_llm_config(db, route, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", replay)


def _kernel_result(session_id: str, run_id: str, *, decision: str = "wait") -> KernelResult:
    return KernelResult(
        session_id=session_id,
        run_id=run_id,
        decision=decision,
        message="waiting for more runtime work",
        metadata={
            "core_events": [],
            "response_blocks": [],
            "steps_count": 0,
            "tool_results_summary": [],
            "verification_summaries": [],
        },
    )


def _all_blocks(snapshot):
    if not snapshot["turns"]:
        return []
    return [
        block
        for call in snapshot["turns"][0]["model_calls"]
        for block in call["blocks"]
    ]


async def _project(session_factory, session_id: str):
    async with session_factory() as db:
        return await project_transcript(db, session_id)


@pytest.mark.asyncio
async def test_runtime_reply_delta_updates_model_text_before_finish(monkeypatch, tmp_path):
    observations = []
    session_factory_holder = {}

    async def _replay_reply_delta(**kwargs):
        callback = kwargs["live_event_callback"]
        session_id = kwargs["session_id"]
        run_id = "run-reply-delta-contract"

        await callback(CoreEvent(
            name="runtime.reply_delta",
            category="message",
            payload={"content": "first visible chunk", "response_index": 0},
            session_id=session_id,
            run_id=run_id,
        ))
        observations.append(await _project(session_factory_holder["factory"], session_id))

        await callback(CoreEvent(
            name="runtime.reply_delta",
            category="message",
            payload={"content": "first visible chunk plus second chunk", "response_index": 0},
            session_id=session_id,
            run_id=run_id,
        ))
        observations.append(await _project(session_factory_holder["factory"], session_id))

        return _kernel_result(session_id, run_id)

    _install_replay_kernel(monkeypatch, _replay_reply_delta)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'reply-delta.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session_factory_holder["factory"] = session_factory
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]
        session_id = "session-reply-delta-contract"

        async with session_factory() as db:
            db.add(WriterSession(
                id=session_id,
                title="reply delta contract",
                work_root=str(tmp_path / "workspace"),
            ))
            await db.commit()

            await run_turn(db, session_id, "stream text", thinking_enabled=True, thinking_budget=6000)

        first_blocks = [block for block in _all_blocks(observations[0]) if block["type"] == "model_text"]
        second_blocks = [block for block in _all_blocks(observations[1]) if block["type"] == "model_text"]
        first_call = observations[0]["turns"][0]["model_calls"][0]

        assert [block["content"] for block in first_blocks] == ["first visible chunk"]
        assert [block["content"] for block in second_blocks] == ["first visible chunk plus second chunk"]
        assert second_blocks[0]["block_id"] == first_blocks[0]["block_id"]
        assert first_call["provider"] == "test"
        assert first_call["model"] == "test-model"
        assert first_call["metadata"]["model_context"]["thinking_enabled"] is True
        assert first_call["metadata"]["model_context"]["thinking_budget"] == 6000
        assert observations[1]["revision"] > observations[0]["revision"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_tool_result_part_updates_same_projected_block_and_revision(monkeypatch, tmp_path):
    observations = []
    session_factory_holder = {}

    async def _replay_tool_progress(**kwargs):
        callback = kwargs["live_event_callback"]
        session_id = kwargs["session_id"]
        run_id = "run-tool-progress-contract"

        await callback(CoreEvent(
            name="runtime.tool.started",
            category="tool",
            payload={
                "tool_call_id": "cmd-stream",
                "tool_name": "run_command",
                "tool_args": {"command": "npm test"},
                "response_index": 0,
            },
            session_id=session_id,
            run_id=run_id,
        ))
        observations.append(await _project(session_factory_holder["factory"], session_id))

        await callback(CoreEvent(
            name="runtime.part",
            category="tool",
            payload={
                "part_id": "cmd-stream:result",
                "part_type": "tool_result",
                "status": "running",
                "content": "stdout line 1",
                "tool_call_id": "cmd-stream",
                "tool_name": "run_command",
                "response_index": 0,
            },
            session_id=session_id,
            run_id=run_id,
        ))
        observations.append(await _project(session_factory_holder["factory"], session_id))

        await callback(CoreEvent(
            name="runtime.part",
            category="tool",
            payload={
                "part_id": "cmd-stream:result",
                "part_type": "tool_result",
                "status": "running",
                "content": "stdout line 1\nstdout line 2",
                "tool_call_id": "cmd-stream",
                "tool_name": "run_command",
                "response_index": 0,
            },
            session_id=session_id,
            run_id=run_id,
        ))
        observations.append(await _project(session_factory_holder["factory"], session_id))

        return _kernel_result(session_id, run_id)

    _install_replay_kernel(monkeypatch, _replay_tool_progress)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'tool-progress.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session_factory_holder["factory"] = session_factory
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]
        session_id = "session-tool-progress-contract"

        async with session_factory() as db:
            db.add(WriterSession(
                id=session_id,
                title="tool progress contract",
                work_root=str(tmp_path / "workspace"),
            ))
            await db.commit()

            await run_turn(db, session_id, "run command")

        started_blocks = _all_blocks(observations[0])
        first_result_blocks = [block for block in _all_blocks(observations[1]) if block["type"] == "tool_result"]
        second_result_blocks = [block for block in _all_blocks(observations[2]) if block["type"] == "tool_result"]

        assert any(block["type"] == "tool_call" and block["status"] == "running" for block in started_blocks)
        assert [block["content"] for block in first_result_blocks] == ["stdout line 1"]
        assert [block["content"] for block in second_result_blocks] == ["stdout line 1\nstdout line 2"]
        assert second_result_blocks[0]["block_id"] == first_result_blocks[0]["block_id"]
        assert observations[1]["revision"] > observations[0]["revision"]
        assert observations[2]["revision"] > observations[1]["revision"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reused_provider_tool_call_ids_do_not_overwrite_prior_turns(monkeypatch, tmp_path):
    calls = 0

    async def _replay_reused_tool_id(**kwargs):
        nonlocal calls
        calls += 1
        callback = kwargs["live_event_callback"]
        session_id = kwargs["session_id"]
        run_id = f"run-reused-tool-{calls}"

        await callback(CoreEvent(
            name="runtime.tool.started",
            category="tool",
            payload={
                "call_id": "functions.write_file:0",
                "tool_name": "write_file",
                "tool_args": {"path": f"file-{calls}.md"},
                "response_index": 0,
            },
            session_id=session_id,
            run_id=run_id,
        ))
        await callback(CoreEvent(
            name="runtime.tool.finished",
            category="tool",
            payload={
                "call_id": "functions.write_file:0",
                "tool_name": "write_file",
                "status": "ok",
                "content": f"wrote file {calls}",
                "response_index": 0,
            },
            session_id=session_id,
            run_id=run_id,
        ))
        return KernelResult(
            session_id=session_id,
            run_id=run_id,
            decision="done",
            message=f"done {calls}",
            metadata={
                "core_events": [],
                "response_blocks": [],
                "steps_count": 0,
                "tool_results_summary": [],
                "verification_summaries": [],
            },
        )

    _install_replay_kernel(monkeypatch, _replay_reused_tool_id)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'reused-tool-id.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]
        session_id = "session-reused-tool-id"

        async with session_factory() as db:
            db.add(WriterSession(
                id=session_id,
                title="reused tool id",
                work_root=str(tmp_path / "workspace"),
            ))
            await db.commit()

            await run_turn(db, session_id, "first task")
            await run_turn(db, session_id, "second task")

            snapshot = await project_transcript(db, session_id)

        assert len(snapshot["turns"]) == 2
        first_blocks = [
            block
            for call in snapshot["turns"][0]["model_calls"]
            for block in call["blocks"]
            if block["type"] == "tool_call"
        ]
        second_blocks = [
            block
            for call in snapshot["turns"][1]["model_calls"]
            for block in call["blocks"]
            if block["type"] == "tool_call"
        ]

        assert [block["tool"]["name"] for block in first_blocks] == ["write_file"]
        assert [block["tool"]["name"] for block in second_blocks] == ["write_file"]
        assert first_blocks[0]["block_id"] != second_blocks[0]["block_id"]
    finally:
        await engine.dispose()
