import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.app_server.ledger import list_events_after
from app.app_server.snapshot import load_snapshot
from app.config import Settings
from app.database import Base
from app.models.attachment import WriterAttachment
from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.models.transcript import WriterTranscriptBlock, WriterTranscriptTurn
import app.services.app_projection_sink as app_projection_sink_module
import app.services.writer_service as writer_service_module
from app.core.writer.agent_runtime import AgentCall, SubAgentDefinition
from app.services.writer_service import writer_orchestrate
from lamtools_core.event import CoreEvent
from lamtools_core.kernel import KernelResult
from lamtools_core.runtime import RuntimeState


async def _app_events(db, session_id: str):
    return await list_events_after(db, thread_id=session_id, after_seq=0)


async def _transcript_blocks(db, session_id: str) -> list[WriterTranscriptBlock]:
    result = await db.execute(
        select(WriterTranscriptBlock)
        .join(WriterTranscriptTurn, WriterTranscriptBlock.turn_id == WriterTranscriptTurn.id)
        .where(WriterTranscriptTurn.session_id == session_id)
        .order_by(WriterTranscriptBlock.event_sequence.asc(), WriterTranscriptBlock.id.asc())
    )
    return list(result.scalars().all())


def test_writer_state_store_uses_service_database_url(monkeypatch, tmp_path):
    observed_urls: list[str] = []

    def _recording_create_async_engine(url, *args, **kwargs):
        observed_urls.append(str(url))
        return create_async_engine(url, *args, **kwargs)

    monkeypatch.setattr(writer_service_module, "create_async_engine", _recording_create_async_engine)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'service.db'}",
        llm_api_key="test",
    )

    writer_orchestrate(settings)

    assert observed_urls == [settings.database_url]


@pytest.mark.asyncio
async def test_run_turn_persists_message():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = Settings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            llm_api_key="test",
        )

        engine = create_async_engine(settings.database_url, future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async def _fake_resolve_llm_config(db, route):
            return {"provider": "test", "model": "test-model"}

        def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
            return object()

        async def _fake_run_core_kernel(**kwargs):
            from lamtools_core.kernel import KernelResult
            return KernelResult(
                session_id=kwargs["session_id"],
                run_id="run-test",
                decision="done",
                message="已收到。",
                metadata={"core_events": [], "steps_count": 1, "tool_results_summary": [], "verification_summaries": []},
            )

        _orig_resolve = writer_service_module.resolve_llm_config
        _orig_build = writer_service_module.build_llm_client
        _orig_run = writer_service_module.run_core_kernel

        writer_service_module.resolve_llm_config = _fake_resolve_llm_config
        writer_service_module.build_llm_client = _fake_build_llm_client
        writer_service_module.run_core_kernel = _fake_run_core_kernel

        try:
            services = writer_orchestrate(settings)
            run_turn = services["run_turn"]

            async with session_factory() as db:
                session = WriterSession(
                    id="session-1",
                    title="test",
                    work_root=str(tmp_path / "workspace"),
                )
                db.add(session)
                await db.commit()

                await run_turn(db, "session-1", "hello")

                result = await db.execute(
                    select(WriterMessage).where(WriterMessage.session_id == "session-1")
                )
                messages = result.scalars().all()
                assert len(messages) == 2
                assert messages[0].role == "user"
                assert messages[0].content == "hello"
                assert messages[1].role == "assistant"
        finally:
            writer_service_module.resolve_llm_config = _orig_resolve
            writer_service_module.build_llm_client = _orig_build
            writer_service_module.run_core_kernel = _orig_run

        await engine.dispose()


@pytest.mark.asyncio
async def test_run_turn_sends_current_image_attachment_as_multimodal_content(monkeypatch, tmp_path):
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'image-attachment.db'}",
        llm_api_key="test",
    )

    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    captured: dict[str, object] = {}

    async def _fake_resolve_llm_config(db, route, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        captured.update(kwargs)
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-image",
            decision="done",
            message="我看到了截图。",
            metadata={"core_events": [], "steps_count": 1, "tool_results_summary": [], "verification_summaries": []},
        )

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    image_path = tmp_path / "screenshot.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nimage-bytes")

    try:
        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]

        async with session_factory() as db:
            session = WriterSession(
                id="session-image-attachment",
                title="test",
                work_root=str(tmp_path / "workspace"),
            )
            db.add(session)
            db.add(
                WriterAttachment(
                    id="att-image",
                    session_id=session.id,
                    filename="screenshot.png",
                    mime_type="image/png",
                    size=image_path.stat().st_size,
                    storage_path=str(image_path),
                    preview_type="image",
                )
            )
            await db.commit()

            await run_turn(db, session.id, "请看这张截图", attachment_ids=["att-image"])

        assert str(image_path) not in str(captured["goal"])
        user_content = captured["user_content"]
        assert isinstance(user_content, list)
        assert user_content[0] == {"type": "text", "text": str(captured["goal"])}
        assert user_content[1]["type"] == "image_url"
        assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert user_content[1]["image_url"]["detail"] == "auto"
        assert str(image_path) not in str(user_content)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_turn_keeps_internal_checkpoints_for_do_not_commit_task(monkeypatch, tmp_path):
    checkpoint_reasons: list[str] = []

    async def _fake_resolve_llm_config(db, route, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-do-not-commit",
            decision="done",
            message="done",
            metadata={"core_events": [], "steps_count": 0, "tool_results_summary": [], "verification_summaries": []},
        )

    async def _fake_checkpoint_if_dirty(self, *, session_id, work_root, reason, turn_id=None, stage=None):
        del session_id, work_root
        checkpoint_reasons.append(reason)
        return {"commit": "internal-checkpoint"}

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)
    monkeypatch.setattr(
        writer_service_module.WriterCheckpointService,
        "create_checkpoint_if_dirty",
        _fake_checkpoint_if_dirty,
    )

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'do-not-commit.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]
        session_id = "session-do-not-commit"

        async with session_factory() as db:
            db.add(WriterSession(
                id=session_id,
                title="test",
                work_root=str(tmp_path / "workspace"),
            ))
            await db.commit()

            await run_turn(db, session_id, "write the report, but do not commit anything")

        assert checkpoint_reasons == ["本轮开始前自动存档", "本轮完成自动存档"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_turn_binds_post_run_checkpoint_to_app_server_turn(monkeypatch, tmp_path):
    checkpoint_calls: list[dict[str, str | None]] = []

    async def _fake_resolve_llm_config(db, route, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-bound-checkpoint",
            decision="done",
            message="done",
            metadata={"core_events": [], "steps_count": 0, "tool_results_summary": [], "verification_summaries": []},
        )

    async def _fake_checkpoint_if_dirty(self, *, session_id, work_root, reason, turn_id=None, stage=None):
        del session_id, work_root
        checkpoint_calls.append({"reason": reason, "turn_id": turn_id, "stage": stage})
        return {"commit": "internal-checkpoint"}

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)
    monkeypatch.setattr(
        writer_service_module.WriterCheckpointService,
        "create_checkpoint_if_dirty",
        _fake_checkpoint_if_dirty,
    )

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'bound-checkpoint.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]
        session_id = "session-bound-checkpoint"

        async with session_factory() as db:
            db.add(WriterSession(id=session_id, title="test", work_root=str(tmp_path / "workspace")))
            db.add(WriterMessage(id="user-bound", session_id=session_id, role="user", content="hello"))
            db.add(
                WriterTranscriptTurn(
                    id="turn-bound",
                    session_id=session_id,
                    sequence=1,
                    user_text="hello",
                    user_message_id="user-bound",
                    status_cache="running",
                )
            )
            await db.commit()

            await run_turn(
                db,
                session_id,
                "hello",
                user_message_id="user-bound",
                transcript_turn_id="turn-bound",
            )

        assert checkpoint_calls[-1] == {
            "reason": "本轮完成自动存档",
            "turn_id": "turn-bound",
            "stage": "after_turn",
        }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sub_agent_model_factory_uses_generic_route_and_explicit_model(monkeypatch, tmp_path):
    resolved_calls: list[dict[str, str | None]] = []

    async def _fake_resolve_llm_config(db, route, model_id=None):
        resolved_calls.append({"route": route, "model_id": model_id})
        model_key = model_id or route
        return SimpleNamespace(
            provider=SimpleNamespace(id=f"provider:{model_key}"),
            model=SimpleNamespace(id=f"model:{model_key}", model_id=model_key),
            task_type=route,
        )

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return SimpleNamespace(model_id=resolved.model.model_id)

    async def _fake_run_core_kernel(**kwargs):
        factory = kwargs["sub_agent_llm_client_factory"]
        await factory(
            SubAgentDefinition(
                name="worker",
                description="Worker",
                role="sub",
                developer_instructions="",
                tools=(),
            ),
            AgentCall(
                name="sub",
                task="delegate",
                options={"agent": "worker", "model": "glm5.2-xfyun-maas"},
            ),
        )
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-sub-agent-route",
            decision="done",
            message="done",
            metadata={"core_events": [], "steps_count": 0, "tool_results_summary": [], "verification_summaries": []},
        )

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'sub-agent-route.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]
        session_id = "session-sub-agent-route"

        async with session_factory() as db:
            db.add(WriterSession(id=session_id, title="test", work_root=str(tmp_path / "workspace")))
            await db.commit()

            await run_turn(db, session_id, "delegate work")

        assert {"route": "sub_agent", "model_id": "glm5.2-xfyun-maas"} in resolved_calls
        assert all(call["route"] != "sub_agent:worker" for call in resolved_calls)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_env_var_on_saves_core_kernel_reply_and_events(monkeypatch):
    """Experimental service path saves the actual reply and publishes core events."""

    async def _fake_resolve_llm_config(db, route):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-service-test",
            decision="done",
            message="我已经整理好了。",
            metadata={
                "core_events": [
                    {
                        "run_id": "run-service-test",
                        "event_name": "runtime.started",
                        "category": "lifecycle",
                        "summary": "Run started",
                    },
                    {
                        "run_id": "run-service-test",
                        "event_name": "runtime.reply",
                        "category": "message",
                        "summary": "我已经整理好了。",
                    },
                    {
                        "run_id": "run-service-test",
                        "event_name": "runtime.done",
                        "category": "lifecycle",
                        "summary": "Run completed",
                    },
                ],
                "steps_count": 1,
                "tool_results_summary": [],
                "verification_summaries": [],
            },
        )

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = Settings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            llm_api_key="test",
        )

        engine = create_async_engine(settings.database_url, future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]

        async with session_factory() as db:
            session = WriterSession(
                id="session-core-kernel-success-test",
                title="test",
                work_root=str(tmp_path / "workspace"),
            )
            db.add(session)
            await db.commit()

            await run_turn(db, "session-core-kernel-success-test", "整理一下")

            result = await db.execute(
                select(WriterMessage)
                .where(WriterMessage.session_id == "session-core-kernel-success-test")
                .order_by(WriterMessage.created_at)
            )
            messages = result.scalars().all()
            assert [m.role for m in messages] == ["user", "assistant"]
            assert messages[1].content == "我已经整理好了。"
            assert messages[1].parts["core_kernel_summary"]["decision"] == "done"
            assert messages[1].parts["core_kernel_summary"]["message"] == "我已经整理好了。"

            refreshed = await db.get(WriterSession, "session-core-kernel-success-test")
            assert refreshed is not None
            assert refreshed.status == "completed"
            turn = (
                await db.execute(
                    select(WriterTranscriptTurn).where(
                        WriterTranscriptTurn.session_id == "session-core-kernel-success-test"
                    )
                )
            ).scalar_one()
            assert turn.status_cache == "completed"

        async with session_factory() as db:
            app_events = await _app_events(db, "session-core-kernel-success-test")
            snapshot = await load_snapshot(db, "session-core-kernel-success-test")
        assert any(
            event.method == "core/runItem"
            and event.payload.get("kind") == "status"
            and event.payload.get("status") == "completed"
            for event in app_events
        )
        assert snapshot["core"]["status"] == "completed"
        assert all(not event.method.startswith("core_kernel.") for event in app_events)

        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_core_kernel_reply_is_still_persisted(monkeypatch, tmp_path):
    """A failed run can keep visible text without marking it final."""

    async def _fake_resolve_llm_config(db, route, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        await kwargs["live_event_callback"](CoreEvent(
            name="runtime.failed",
            category="error",
            payload={
                "error": "artifact_scan: No project files found",
                "message": "你好！有什么我可以帮你的吗？",
            },
            session_id=kwargs["session_id"],
            run_id="run-failed-visible-reply",
        ))
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-failed-visible-reply",
            decision="failed",
            message="你好！有什么我可以帮你的吗？",
            error="artifact_scan: No project files found",
            metadata={
                "core_events": [],
                "steps_count": 1,
                "tool_results_summary": [],
                "verification_summaries": [{"passed": False, "summary": "No project files found"}],
            },
        )

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]
        session_id = "session-failed-visible-reply"

        async with session_factory() as db:
            db.add(WriterSession(
                id=session_id,
                title="test",
                work_root=str(tmp_path / "workspace"),
            ))
            await db.commit()

            await run_turn(db, session_id, "请你回复你好")

            result = await db.execute(
                select(WriterMessage)
                .where(WriterMessage.session_id == session_id)
                .order_by(WriterMessage.created_at)
            )
            messages = result.scalars().all()
            assert [m.role for m in messages] == ["user", "assistant"]
            assert messages[1].content == "你好！有什么我可以帮你的吗？"
            assert messages[1].parts["core_kernel_summary"]["decision"] == "failed"
            assert "final_answer" not in messages[1].parts
            assert "final_answer" not in messages[1].parts["core_kernel_summary"]
            assert messages[1].parts["failure_summary"] == messages[1].content

            refreshed = await db.get(WriterSession, session_id)
            assert refreshed is not None
            assert refreshed.status == "failed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_kernel_exception_is_recorded_and_propagated(monkeypatch, tmp_path):

    async def _fake_resolve_llm_config(db, route, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        raise RuntimeError("model transport closed")

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]
        session_id = "session-exception-visible-error"

        async with session_factory() as db:
            db.add(WriterSession(
                id=session_id,
                title="test",
                work_root=str(tmp_path / "workspace"),
            ))
            await db.commit()

            with pytest.raises(RuntimeError, match="model transport closed"):
                await run_turn(db, session_id, "hello")

            result = await db.execute(
                select(WriterMessage)
                .where(WriterMessage.session_id == session_id)
                .order_by(WriterMessage.created_at)
            )
            messages = result.scalars().all()
            assert [m.role for m in messages] == ["user"]

            refreshed = await db.get(WriterSession, session_id)
            assert refreshed is not None
            assert refreshed.status == "active"
            assert refreshed.phase == "executing"
            turn = (
                await db.execute(select(WriterTranscriptTurn).where(WriterTranscriptTurn.session_id == session_id))
            ).scalar_one()
            assert turn.error is None
            assert turn.terminal_at is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_kernel_done_with_delivery_but_empty_reply_gets_visible_summary(monkeypatch):
    """A completed delivery must not render as an empty assistant message."""

    async def _fake_resolve_llm_config(db, route):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-empty-delivery-test",
            decision="done",
            message="",
            state=RuntimeState(
                session_id=kwargs["session_id"],
                metadata={"written_files": ["kbtool.py", "notes/index.md"]},
            ),
            metadata={
                "core_events": [],
                "steps_count": 2,
                "tool_results_summary": [],
                "verification_summaries": [{"summary": "测试通过"}],
            },
        )

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = Settings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            llm_api_key="test",
        )

        engine = create_async_engine(settings.database_url, future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]

        async with session_factory() as db:
            session = WriterSession(
                id="session-empty-delivery-test",
                title="test",
                work_root=str(tmp_path / "workspace"),
            )
            db.add(session)
            await db.commit()

            await run_turn(db, "session-empty-delivery-test", "做一个工具")

            result = await db.execute(
                select(WriterMessage)
                .where(WriterMessage.session_id == "session-empty-delivery-test")
                .order_by(WriterMessage.created_at)
            )
            messages = result.scalars().all()
            assert [m.role for m in messages] == ["user", "assistant"]
            assert "模型没有返回最终正文" in messages[1].content
            assert "kbtool.py" in messages[1].content
            assert messages[1].parts["core_kernel_summary"]["message"] == messages[1].content

        await engine.dispose()


@pytest.mark.asyncio
async def test_live_reasoning_deltas_are_scoped_per_part(monkeypatch, tmp_path):
    """Live reasoning deltas from separate model calls must not share one cursor."""

    async def _fake_resolve_llm_config(db, route, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        callback = kwargs["live_event_callback"]
        session_id = kwargs["session_id"]
        for response_index, part_id, content in (
            (0, "run-reasoning:response-0:reasoning", "first reasoning"),
            (1, "run-reasoning:response-1:reasoning", "second reasoning"),
        ):
            await callback(CoreEvent(
                name="runtime.part",
                category="message",
                payload={
                    "part_type": "reasoning",
                    "status": "running",
                    "content": content,
                    "part_id": part_id,
                    "response_index": response_index,
                },
                session_id=session_id,
                run_id="run-reasoning",
            ))
        return KernelResult(
            session_id=session_id,
            run_id="run-reasoning",
            decision="done",
            message="Final answer.",
            metadata={
                "core_events": [],
                "response_blocks": [],
                "steps_count": 0,
                "tool_results_summary": [],
                "verification_summaries": [],
            },
        )

    _orig_resolve = writer_service_module.resolve_llm_config
    _orig_build = writer_service_module.build_llm_client
    _orig_run = writer_service_module.run_core_kernel
    writer_service_module.resolve_llm_config = _fake_resolve_llm_config
    writer_service_module.build_llm_client = _fake_build_llm_client
    writer_service_module.run_core_kernel = _fake_run_core_kernel

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]
        session_id = "session-live-reasoning-scope"

        async with session_factory() as db:
            db.add(WriterSession(
                id=session_id,
                title="test",
                work_root=str(tmp_path / "workspace"),
            ))
            await db.commit()
            await run_turn(db, session_id, "run")

        async with session_factory() as db:
            snapshot = await load_snapshot(db, session_id)
        reasoning_items = sorted(
            [
                item
                for item in (snapshot.get("core", {}).get("items") or {}).values()
                if item.get("kind") == "thinking"
                and isinstance(item.get("payload"), dict)
                and item["payload"].get("type") == "reasoning"
            ],
            key=lambda item: item["item_id"],
        )
        assert [item.get("content") for item in reasoning_items] == ["first reasoning", "second reasoning"]
        assert [item.get("item_id") for item in reasoning_items] == [
            "run-reasoning:response-0:reasoning",
            "run-reasoning:response-1:reasoning",
        ]
    finally:
        writer_service_module.resolve_llm_config = _orig_resolve
        writer_service_module.build_llm_client = _orig_build
        writer_service_module.run_core_kernel = _orig_run
        await engine.dispose()


@pytest.mark.asyncio
async def test_core_app_projection_is_persisted_before_stream_returns(monkeypatch, tmp_path):
    observed_counts: list[int] = []
    session_factory_holder: dict[str, async_sessionmaker] = {}

    async def _fake_resolve_llm_config(db, route, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        callback = kwargs["live_event_callback"]
        session_id = kwargs["session_id"]
        await callback(CoreEvent(
            name="runtime.part",
            category="message",
            payload={
                "part_type": "reasoning",
                "status": "running",
                "content": "durable reasoning",
                "part_id": "durable-reasoning-part",
            },
            session_id=session_id,
            run_id="run-durable-events",
        ))
        async with session_factory_holder["factory"]() as check_db:
            observed_counts.append(len(await _app_events(check_db, session_id)))
        return KernelResult(
            session_id=session_id,
            run_id="run-durable-events",
            decision="done",
            message="Done.",
            metadata={
                "core_events": [],
                "steps_count": 0,
                "tool_results_summary": [],
                "verification_summaries": [],
            },
        )

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
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
        session_id = "session-durable-runtime-events"

        async with session_factory() as db:
            db.add(WriterSession(
                id=session_id,
                title="test",
                work_root=str(tmp_path / "workspace"),
            ))
            await db.commit()
            await run_turn(db, session_id, "run")

        assert observed_counts == [1]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_app_projection_failure_propagates_without_writer_terminal_fallback(monkeypatch, tmp_path):
    async def _fake_resolve_llm_config(db, route, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        callback = kwargs["live_event_callback"]
        session_id = kwargs["session_id"]
        await callback(CoreEvent(
            name="runtime.part",
            category="message",
            payload={
                "part_type": "tool_result",
                "status": "completed",
                "content": "large display projection payload",
                "part_id": "projection-result",
            },
            session_id=session_id,
            run_id="run-projection-failure",
        ))
        return KernelResult(
            session_id=session_id,
            run_id="run-projection-failure",
            decision="done",
            message="Done.",
            metadata={
                "core_events": [],
                "steps_count": 0,
                "tool_results_summary": [],
                "verification_summaries": [],
            },
        )

    async def _failing_projection(db, events):
        raise RuntimeError("projection database transaction failed")

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)
    monkeypatch.setattr(app_projection_sink_module, "persist_run_item_events_as_app_events", _failing_projection)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'projection-failure.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]
        session_id = "session-projection-failure"

        async with session_factory() as db:
            db.add(WriterSession(
                id=session_id,
                title="test",
                work_root=str(tmp_path / "workspace"),
            ))
            await db.commit()

            with pytest.raises(RuntimeError, match="projection database transaction failed"):
                await run_turn(db, session_id, "run")

            refreshed = await db.get(WriterSession, session_id)
            assert refreshed.status == "active"
            assert refreshed.phase == "executing"

            blocks = await _transcript_blocks(db, session_id)
            assert not any(block.type == "tool_result" for block in blocks)
            turn = (
                await db.execute(select(WriterTranscriptTurn).where(WriterTranscriptTurn.session_id == session_id))
            ).scalar_one()
            assert turn.terminal_at is None
            assert turn.error is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_final_answer_without_core_terminal_event_does_not_own_lifecycle(monkeypatch, tmp_path):
    async def _fake_resolve_llm_config(db, route, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-answer-without-terminal",
            decision="done",
            message="Final answer survives.",
            metadata={
                "core_events": [],
                "steps_count": 0,
                "tool_results_summary": [],
                "verification_summaries": [],
            },
        )

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'answer-without-terminal.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]
        session_id = "session-answer-without-terminal"
        async with session_factory() as db:
            db.add(WriterSession(id=session_id, title="test", work_root=str(tmp_path / "workspace")))
            await db.commit()

            await run_turn(db, session_id, "run")

            messages = list((await db.execute(
                select(WriterMessage)
                .where(WriterMessage.session_id == session_id)
                .order_by(WriterMessage.created_at)
            )).scalars())
            assert [message.role for message in messages] == ["user", "assistant"]
            assert messages[-1].content == "Final answer survives."

            session = await db.get(WriterSession, session_id)
            assert session.status == "active"
            assert session.phase == "executing"
            turn = (
                await db.execute(select(WriterTranscriptTurn).where(WriterTranscriptTurn.session_id == session_id))
            ).scalar_one()
            assert turn.status_cache == "running"
            assert turn.terminal_at is None
            assert turn.terminal_reason is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_session_resume_marks_running_then_persists_terminal_event(monkeypatch, tmp_path):
    observed_statuses: list[tuple[str, str]] = []
    session_factory_holder: dict[str, async_sessionmaker] = {}

    async def _fake_resolve_llm_config(db, route, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        session_id = kwargs["session_id"]
        async with session_factory_holder["factory"]() as check_db:
            refreshed = await check_db.get(WriterSession, session_id)
            observed_statuses.append((refreshed.status, refreshed.phase))
        await kwargs["live_event_callback"](CoreEvent(
            name="runtime.failed",
            category="error",
            payload={"error": "Max steps reached", "message": "我发现了一个语法错误，准备修复。"},
            session_id=session_id,
            run_id="run-failed-resume",
        ))
        return KernelResult(
            session_id=session_id,
            run_id="run-failed-resume",
            decision="failed",
            message="我发现了一个语法错误，准备修复。",
            error="Max steps reached",
            metadata={
                "core_events": [],
                "steps_count": 0,
                "tool_results_summary": [],
                "verification_summaries": [],
            },
        )

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
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
        session_id = "session-failed-resume"

        async with session_factory() as db:
            db.add(WriterSession(
                id=session_id,
                title="test",
                status="failed",
                phase="failed",
                work_root=str(tmp_path / "workspace"),
            ))
            await db.commit()

            await run_turn(db, session_id, "继续")

            messages = (
                await db.execute(
                    select(WriterMessage)
                    .where(WriterMessage.session_id == session_id)
                    .order_by(WriterMessage.created_at)
                )
            ).scalars().all()
            assert [m.role for m in messages] == ["user", "assistant"]
            assert messages[1].content == "我发现了一个语法错误，准备修复。"
            assert messages[1].parts["core_kernel_summary"]["decision"] == "failed"

            refreshed = await db.get(WriterSession, session_id)
            assert refreshed.status == "failed"
            assert refreshed.phase == "failed"

            app_events = await _app_events(db, session_id)
            failed_turns = [
                event
                for event in app_events
                if event.method == "core/runItem"
                and event.payload.get("kind") == "status"
                and event.payload.get("status") == "failed"
            ]
            assert len(failed_turns) == 1
            assert "Max steps reached" in str(
                (failed_turns[0].payload.get("payload") or {}).get("message") or ""
            )

        assert observed_statuses == [("active", "executing")]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_core_kernel_result_persists_failed_session(monkeypatch, tmp_path):
    async def _fake_resolve_llm_config(db, route, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        await kwargs["live_event_callback"](CoreEvent(
            name="runtime.failed",
            category="error",
            payload={"error": "cancelled"},
            session_id=kwargs["session_id"],
            run_id="run-cancelled",
        ))
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-cancelled",
            decision="failed",
            message="",
            error="cancelled",
            metadata={
                "core_events": [],
                "steps_count": 0,
                "tool_results_summary": [],
                "verification_summaries": [],
            },
        )

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]
        session_id = "session-cancelled-result"

        async with session_factory() as db:
            db.add(WriterSession(
                id=session_id,
                title="test",
                status="active",
                phase="executing",
                work_root=str(tmp_path / "workspace"),
            ))
            await db.commit()

            await run_turn(db, session_id, "停止")

            refreshed = await db.get(WriterSession, session_id)
            assert refreshed.status == "failed"
            assert refreshed.phase == "failed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_continue_after_failed_session_with_stale_core_state_starts_new_run(monkeypatch, tmp_path):
    observed_state: list[RuntimeState | None] = []

    async def _fake_resolve_llm_config(db, route, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        state_store = kwargs["state_store"]
        before = await state_store.get(kwargs["session_id"])
        observed_state.append(before)
        fresh_state = RuntimeState(
            session_id=kwargs["session_id"],
            run_id="fresh-run-after-continue",
            status="completed",
            loop_state="done",
            turn_count=(before.turn_count if before else 0) + 1,
            metadata=dict(before.metadata if before else {}),
        )
        await state_store.save(fresh_state)
        await kwargs["live_event_callback"](CoreEvent(
            name="runtime.done",
            category="lifecycle",
            payload={"message": "继续后的任务已完成。"},
            session_id=kwargs["session_id"],
            run_id="fresh-run-after-continue",
        ))
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="fresh-run-after-continue",
            decision="done",
            message="继续后的任务已完成。",
            state=fresh_state,
            metadata={
                "core_events": [],
                "steps_count": 0,
                "tool_results_summary": [],
                "verification_summaries": [],
            },
        )

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]
        session_id = "session-stale-core-state-continue"

        async with session_factory() as db:
            stale_state = {
                "_core_runtime_state": {
                    "session_id": session_id,
                    "run_id": "stale-run",
                    "status": "running",
                    "loop_state": "continue",
                    "turn_count": 48,
                    "metadata": {"max_steps_reached": True},
                }
            }
            db.add(WriterSession(
                id=session_id,
                title="test",
                status="failed",
                phase="failed",
                runtime_state={"session_memory": stale_state},
                work_root=str(tmp_path / "workspace"),
            ))
            await db.commit()

            await run_turn(db, session_id, "继续")

            assert observed_state
            assert observed_state[0] is not None
            assert observed_state[0].run_id == "stale-run"
            assert observed_state[0].metadata.get("max_steps_reached") is True

            refreshed = await db.get(WriterSession, session_id)
            assert refreshed.status == "completed"
            assert refreshed.phase == "completed"

            state_memory = refreshed.runtime_state["session_memory"]["_core_runtime_state"]
            assert state_memory["run_id"] == "fresh-run-after-continue"
            assert state_memory["turn_count"] == 49
            assert state_memory["metadata"]["max_steps_reached"] is True

    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_env_var_on_core_kernel_wait_publishes_writer_wait_event(monkeypatch):
    """Core wait decision is visible through the existing Writer wait event."""

    async def _fake_resolve_llm_config(db, route):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-wait-test",
            decision="wait",
            message="请确认要修改哪一章。",
            metadata={
                "core_events": [
                    {
                        "run_id": "run-wait-test",
                        "event_name": "runtime.waiting",
                        "category": "lifecycle",
                        "summary": "Run waiting for user input",
                    },
                ],
                "steps_count": 1,
                "tool_results_summary": [],
                "verification_summaries": [],
            },
        )

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = Settings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            llm_api_key="test",
        )

        engine = create_async_engine(settings.database_url, future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]

        async with session_factory() as db:
            session = WriterSession(
                id="session-core-kernel-wait-test",
                title="test",
                work_root=str(tmp_path / "workspace"),
            )
            db.add(session)
            await db.commit()

            await run_turn(db, "session-core-kernel-wait-test", "继续修改")

            result = await db.execute(
                select(WriterMessage)
                .where(WriterMessage.session_id == "session-core-kernel-wait-test")
                .order_by(WriterMessage.created_at)
            )
            messages = result.scalars().all()
            assert [m.role for m in messages] == ["user", "assistant"]
            assert messages[1].content == "请确认要修改哪一章。"
            assert messages[1].parts["core_kernel_summary"]["decision"] == "wait"

            refreshed = await db.get(WriterSession, "session-core-kernel-wait-test")
            assert refreshed is not None
            assert refreshed.status == "waiting"

        async with session_factory() as db:
            snapshot = await load_snapshot(db, "session-core-kernel-wait-test")
            app_events = await _app_events(db, "session-core-kernel-wait-test")
        assert snapshot["core"]["status"] == "waiting"
        assert any(
            event.method == "core/runItem" and event.payload.get("kind") == "approval_request"
            for event in app_events
        )
        assert snapshot["core"]["requests"]
        assert all(not event.method.startswith("core_kernel.") for event in app_events)

        await engine.dispose()


@pytest.mark.asyncio
async def test_permission_approval_request_persists_waiting_request(monkeypatch, tmp_path):
    """A command approval request is a durable waiting gate, not a tool error."""

    async def _fake_resolve_llm_config(db, route):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel(**kwargs):
        callback = kwargs["live_event_callback"]
        await callback(CoreEvent(
            name="runtime.part",
            category="tool",
            payload={
                "part_type": "tool_call",
                "status": "waiting",
                "tool_name": "run_command",
                "part_id": "part-cmd-danger",
                "tool_args": {"command": "del README.md"},
                "response_index": 0,
                "metadata": {"requires_approval": True},
            },
            session_id=kwargs["session_id"],
            run_id="run-approval-test",
        ))
        await callback(CoreEvent(
            name="runtime.approval_request",
            category="decision",
            payload={
                "request_kind": "permission",
                "tool_call_id": "cmd-danger",
                "tool_name": "run_command",
                "arguments": {"command": "del README.md"},
                "message": "需要授权后才能执行命令：del README.md",
                "response_index": 0,
                "metadata": {
                    "permission_group": "dangerous",
                    "approval_policy": "ask_user",
                },
                "options": [
                    {"id": "approve", "label": "批准执行", "response": "approve"},
                    {"id": "deny", "label": "拒绝执行", "response": "deny"},
                ],
            },
            session_id=kwargs["session_id"],
            run_id="run-approval-test",
        ))
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-approval-test",
            decision="wait",
            message="需要授权后才能执行命令：del README.md",
            metadata={
                "core_events": [],
                "steps_count": 1,
                "tool_results_summary": [],
                "verification_summaries": [],
            },
        )

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    from app.services.transcript_service import project_transcript

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'approval.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]
        session_id = "session-approval-waiting-test"

        async with session_factory() as db:
            db.add(WriterSession(
                id=session_id,
                title="approval",
                work_root=str(tmp_path / "workspace"),
            ))
            await db.commit()

            await run_turn(db, session_id, "删掉 README")

            projected = await project_transcript(db, session_id)
            assert projected["status"] == "waiting"
            turn = projected["turns"][0]
            assert turn["status"] == "waiting"
            all_blocks = [
                block
                for call in turn["model_calls"]
                for block in call["blocks"]
            ]
            assert len([block for block in all_blocks if block["type"] == "waiting_request"]) == 1
            blocks = turn["model_calls"][0]["blocks"]
            waiting_blocks = [block for block in blocks if block["type"] == "waiting_request"]
            assert waiting_blocks
            waiting = waiting_blocks[0]
            assert waiting["status"] == "waiting"
            assert waiting["waiting_request"]["kind"] == "permission"
            assert waiting["waiting_request"]["tool_call_id"] == "cmd-danger"
            assert waiting["waiting_request"]["tool_name"] == "run_command"
            assert waiting["waiting_request"]["args"]["command"] == "del README.md"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_waiting_request_denial_closes_gate_and_fails_turn(tmp_path):
    from app.models.transcript import WriterTranscriptBlock
    from app.services.transcript_service import create_turn, derive_turn_status, ensure_model_call, upsert_block

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'deny-approval.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        create_approval_coordinator = services["create_approval_coordinator"]
        session_id = "session-deny-waiting-test"

        async with session_factory() as db:
            db.add(WriterSession(
                id=session_id,
                title="deny",
                work_root=str(tmp_path / "workspace"),
            ))
            await db.commit()
            turn = await create_turn(db, session_id=session_id, user_text="删文件", user_message_id=None)
            turn_id = turn.id
            call = await ensure_model_call(db, turn=turn, run_id="run-deny:response-0")
            await upsert_block(
                db,
                turn=turn,
                block_id="cmd-danger:waiting",
                model_call_id=call.id,
                block_type="waiting_request",
                sequence=1,
                event_sequence=1,
                status="waiting",
                content="需要授权",
                request_kind="permission",
                tool_name="run_command",
                tool_call_id="cmd-danger",
                tool_args_json={"command": "del README.md"},
            )
            session = await db.get(WriterSession, session_id)
            session.runtime_state = {"session_memory": {"_core_runtime_state": {
                "session_id": session_id, "run_id": turn.id, "status": "waiting",
                "loop_state": "wait", "turn_count": 1,
                "metadata": {"pending_approval": {
                    "request_id": "cmd-danger",
                    "tool_call": {"id": "cmd-danger", "name": "run_command", "arguments": {"command": "del README.md"}},
                }},
            }}}
            await db.commit()

            coordinator = await create_approval_coordinator(session_id)
            result = await coordinator.respond(
                thread_id=session_id,
                request_id="cmd-danger",
                decision="deny",
                guidance="deny",
            )
            await db.commit()

            waiting = await db.get(WriterTranscriptBlock, "cmd-danger:waiting")
            assert result["decision"] == "deny"
            assert waiting is not None
            assert waiting.completed_at is not None
            assert waiting.response_json["action"] == "deny"
            turn = await db.get(WriterTranscriptTurn, turn_id)
            assert await derive_turn_status(db, turn) == "failed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_waiting_request_approval_executes_tool_and_continues_turn(monkeypatch, tmp_path):
    from app.services.transcript_service import create_turn, ensure_model_call, project_transcript, upsert_block
    from lamtools_core.llm import LLMResponse

    class _FinalLLMClient:
        async def complete(self, request):
            return LLMResponse(content="命令已执行，任务完成。", finish_reason="stop")

        async def stream(self, request):
            raise NotImplementedError

    async def _fake_resolve_llm_config(db, route, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return _FinalLLMClient()

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'approve-approval.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        create_approval_coordinator = services["create_approval_coordinator"]
        session_id = "session-approve-waiting-test"
        work_root = tmp_path / "workspace"
        work_root.mkdir()

        async with session_factory() as db:
            db.add(WriterSession(
                id=session_id,
                title="approve",
                work_root=str(work_root),
            ))
            await db.commit()
            turn = await create_turn(db, session_id=session_id, user_text="运行命令", user_message_id=None)
            call = await ensure_model_call(db, turn=turn, run_id="run-approve:response-0")
            await upsert_block(
                db,
                turn=turn,
                block_id="cmd-approve:waiting",
                model_call_id=call.id,
                block_type="waiting_request",
                sequence=1,
                event_sequence=1,
                status="waiting",
                content="需要授权",
                request_kind="permission",
                tool_name="run_command",
                tool_call_id="cmd-approve",
                tool_args_json={"command": "cmd /c echo approved"},
            )
            session = await db.get(WriterSession, session_id)
            session.runtime_state = {"session_memory": {"_core_runtime_state": {
                "session_id": session_id, "run_id": turn.id, "status": "waiting",
                "loop_state": "wait", "turn_count": 1,
                "metadata": {"pending_approval": {
                    "request_id": "cmd-approve",
                    "tool_call": {"id": "cmd-approve", "name": "run_command", "arguments": {"command": "cmd /c echo approved"}},
                }},
            }}}
            await db.commit()

            coordinator = await create_approval_coordinator(session_id)
            result = await coordinator.respond(
                thread_id=session_id,
                request_id="cmd-approve",
                decision="approve",
                guidance="approve",
            )
            await db.commit()

            projected = await project_transcript(db, session_id)
            blocks = [
                block
                for call_item in projected["turns"][0]["model_calls"]
                for block in call_item["blocks"]
            ]
            assert result["decision"] == "approve"
            assert projected["status"] == "idle"
            assert projected["turns"][0]["status"] == "completed"
            assert any(block["type"] == "tool_result" and "approved" in block["content"] for block in blocks)
            assert projected["turns"][0]["final_reply_block_id"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_waiting_request_guidance_continues_without_executing_waiting_tool(monkeypatch, tmp_path):
    from app.services.transcript_service import create_turn, ensure_model_call, upsert_block
    from app.models.transcript import WriterTranscriptBlock
    from lamtools_core.llm import LLMResponse

    captured: dict[str, str] = {}

    class _GuidanceLLMClient:
        async def complete(self, request):
            captured["user_message"] = "\n".join(str(message.content) for message in request.messages)
            return LLMResponse(content="已按引导继续。", finish_reason="stop")

        async def stream(self, request):
            raise NotImplementedError

    async def _fake_resolve_llm_config(db, route, model_id=None):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return _GuidanceLLMClient()

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)

    settings = Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'guide-approval.db'}",
        llm_api_key="test",
    )
    engine = create_async_engine(settings.database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        create_approval_coordinator = services["create_approval_coordinator"]
        session_id = "session-guide-waiting-test"
        work_root = tmp_path / "workspace"
        work_root.mkdir()
        target = work_root / "README.md"
        target.write_text("keep me", encoding="utf-8")

        async with session_factory() as db:
            db.add(WriterSession(
                id=session_id,
                title="guide",
                work_root=str(work_root),
            ))
            await db.commit()
            turn = await create_turn(db, session_id=session_id, user_text="删除 README.md", user_message_id=None)
            call = await ensure_model_call(db, turn=turn, run_id="run-guide:response-0")
            await upsert_block(
                db,
                turn=turn,
                block_id="cmd-guide:waiting",
                model_call_id=call.id,
                block_type="waiting_request",
                sequence=1,
                event_sequence=1,
                status="waiting",
                content="需要授权",
                request_kind="permission",
                tool_name="run_command",
                tool_call_id="cmd-guide",
                tool_args_json={"command": "del README.md"},
            )
            session = await db.get(WriterSession, session_id)
            session.runtime_state = {"session_memory": {"_core_runtime_state": {
                "session_id": session_id, "run_id": turn.id, "status": "waiting",
                "loop_state": "wait", "turn_count": 1,
                "metadata": {"pending_approval": {
                    "request_id": "cmd-guide",
                    "tool_call": {"id": "cmd-guide", "name": "run_command", "arguments": {"command": "del README.md"}},
                }},
            }}}
            await db.commit()

            coordinator = await create_approval_coordinator(session_id)
            result = await coordinator.respond(
                thread_id=session_id,
                request_id="cmd-guide",
                decision="guide",
                guidance="不要删除，改为重命名。",
            )
            await db.commit()

            waiting = await db.get(WriterTranscriptBlock, "cmd-guide:waiting")
            assert result["decision"] == "guide"
            assert target.exists()
            assert waiting is not None
            assert waiting.completed_at is not None
            assert waiting.response_json["action"] == "guide"
            assert "不要删除，改为重命名。" in captured["user_message"]
            assert "不要默认执行刚才等待审批的工具" in captured["user_message"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_env_var_on_service_core_kernel_writes_file(monkeypatch):
    """Service path runs the real Core loop and writes inside session work_root."""
    from lamtools_core.llm import LLMResponse, LLMToolCall

    class _FakeLLMClient:
        def __init__(self) -> None:
            self._responses = [
                LLMResponse(
                    content="",
                    tool_calls=[
                        LLMToolCall(
                            id="call-write-1",
                            name="write_file",
                            arguments={"path": "draft.md", "content": "# Draft\n\nCore write path works."},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                LLMResponse(content="草稿已经写好了。", finish_reason="stop"),
            ]

        async def complete(self, request):
            return self._responses.pop(0)

        async def stream(self, request):
            raise NotImplementedError

    async def _fake_resolve_llm_config(db, route):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return _FakeLLMClient()

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        work_root = tmp_path / "workspace"
        settings = Settings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            llm_api_key="test",
        )

        engine = create_async_engine(settings.database_url, future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]

        async with session_factory() as db:
            session = WriterSession(
                id="session-core-kernel-write-test",
                title="test",
                work_root=str(work_root),
            )
            db.add(session)
            await db.commit()

            await run_turn(db, "session-core-kernel-write-test", "写一个草稿文件")

            assert (work_root / "draft.md").read_text(encoding="utf-8") == "# Draft\n\nCore write path works."

            result = await db.execute(
                select(WriterMessage)
                .where(WriterMessage.session_id == "session-core-kernel-write-test")
                .order_by(WriterMessage.created_at)
            )
            messages = result.scalars().all()
            assert [m.role for m in messages] == ["user", "assistant"]
            assert messages[1].content == "草稿已经写好了。"
            summary = messages[1].parts["core_kernel_summary"]
            assert summary["decision"] == "done"
            assert summary["message"] == "草稿已经写好了。"
            assert any(
                item.get("tool_name") == "write_file"
                for item in summary.get("tool_results_summary", [])
            )

            refreshed = await db.get(WriterSession, "session-core-kernel-write-test")
            assert refreshed is not None
            assert refreshed.status == "completed"

        async with session_factory() as db:
            snapshot = await load_snapshot(db, "session-core-kernel-write-test")
            app_events = await _app_events(db, "session-core-kernel-write-test")
        assert any(
            isinstance(item.get("payload"), dict)
            and item["payload"].get("type") == "dynamicToolCall"
            and item["payload"].get("tool_name") == "write_file"
            for item in (snapshot.get("core", {}).get("items") or {}).values()
        )
        assert any(
            item.get("last_kind") == "tool_result" and item.get("status") == "completed"
            for item in (snapshot.get("core", {}).get("items") or {}).values()
        )
        assert any(event.method == "core/runItem" and event.payload.get("kind") == "tool_call" for event in app_events)
        assert any(event.method == "core/runItem" and event.payload.get("kind") == "tool_result" for event in app_events)
        assert all(not event.method.startswith("core_kernel.") for event in app_events)

        await engine.dispose()

@pytest.mark.asyncio
async def test_env_var_on_service_core_kernel_writes_and_runs_tests(monkeypatch):
    """Service path writes a test file, runs pytest, and stores test exit code."""
    from lamtools_core.llm import LLMResponse, LLMToolCall

    class _FakeLLMClient:
        def __init__(self) -> None:
            self._responses = [
                LLMResponse(
                    content="",
                    tool_calls=[
                        LLMToolCall(
                            id="call-write-test-1",
                            name="write_file",
                            arguments={
                                "path": "test_core_service.py",
                                "content": "def test_core_service():\n    assert 2 + 2 == 4\n",
                            },
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                LLMResponse(
                    content="",
                    tool_calls=[
                        LLMToolCall(
                            id="call-run-tests-1",
                            name="run_tests",
                            arguments={"command": "py -m pytest test_core_service.py"},
                        )
                    ],
                    finish_reason="tool_calls",
                ),
                LLMResponse(content="测试通过，文件已完成。", finish_reason="stop"),
            ]

        async def complete(self, request):
            return self._responses.pop(0)

        async def stream(self, request):
            raise NotImplementedError

    async def _fake_resolve_llm_config(db, route):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return _FakeLLMClient()

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        work_root = tmp_path / "workspace"
        settings = Settings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            llm_api_key="test",
        )

        engine = create_async_engine(settings.database_url, future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]

        async with session_factory() as db:
            session = WriterSession(
                id="session-core-kernel-test-run-test",
                title="test",
                work_root=str(work_root),
            )
            db.add(session)
            await db.commit()

            await run_turn(db, "session-core-kernel-test-run-test", "写测试并运行")

            assert (work_root / "test_core_service.py").read_text(encoding="utf-8") == (
                "def test_core_service():\n    assert 2 + 2 == 4\n"
            )

            result = await db.execute(
                select(WriterMessage)
                .where(WriterMessage.session_id == "session-core-kernel-test-run-test")
                .order_by(WriterMessage.created_at)
            )
            messages = result.scalars().all()
            assert [m.role for m in messages] == ["user", "assistant"]
            assert messages[1].content == "测试通过，文件已完成。"
            summary = messages[1].parts["core_kernel_summary"]
            assert summary["decision"] == "done"
            run_tests_summary = [
                item
                for item in summary.get("tool_results_summary", [])
                if item.get("tool_name") == "run_tests"
            ]
            assert run_tests_summary
            assert run_tests_summary[0]["exit_code"] == 0

            refreshed = await db.get(WriterSession, "session-core-kernel-test-run-test")
            assert refreshed is not None
            assert refreshed.status == "completed"

        await engine.dispose()


@pytest.mark.asyncio
async def test_core_kernel_path_produces_observable_metadata():
    """Core kernel path produces observable metadata via summarize_kernel_result.

    This test directly exercises run_core_kernel + summarize_kernel_result
    with a fake LLM client to verify the metadata structure that the service
    layer would receive and forward as events.
    """
    from lamtools_core.kernel import summarize_kernel_result
    from lamtools_core.llm import LLMClient, LLMRequest, LLMResponse
    from app.core.writer.core_kernel_adapter import run_core_kernel

    class _FakeLLMClient:
        """Deterministic fake LLMClient for testing."""
        def __init__(self) -> None:
            self._responses: list[LLMResponse] = []

        def add_response(self, response: LLMResponse) -> None:
            self._responses.append(response)

        async def complete(self, request: LLMRequest) -> LLMResponse:
            if not self._responses:
                return LLMResponse(content="done", finish_reason="stop")
            return self._responses.pop(0)

        async def stream(self, request: LLMRequest):
            raise NotImplementedError

    llm = _FakeLLMClient()
    llm.add_response(LLMResponse(content="Task completed.", finish_reason="stop"))

    result = await run_core_kernel(
        goal="Say hello",
        session_id="test-metadata-obs",
        llm_client=llm,
    )

    summary = summarize_kernel_result(result)

    assert "decision" in summary
    assert "message" in summary
    assert "steps_count" in summary
    assert "core_events" in summary
    assert "tool_results_summary" in summary
    assert "verification_summaries" in summary

    assert summary["decision"] == "done"
    assert summary["message"] == "Task completed."
    assert summary["steps_count"] >= 1
    assert isinstance(summary["core_events"], list)
    assert len(summary["core_events"]) >= 1

    for evt in summary["core_events"]:
        assert "event_name" in evt
        assert "category" in evt
        assert "summary" in evt

    event_names = [evt["event_name"] for evt in summary["core_events"]]
    assert "runtime.started" in event_names
    assert "runtime.done" in event_names


@pytest.mark.asyncio
async def test_core_kernel_service_path_with_prior_history(monkeypatch):
    """Service path: when DB has prior user/assistant messages, Core LLM
    request includes them and does NOT duplicate the current user message.

    This test:
    1. Sends a first message (gets an assistant reply).
    2. Sends a second message.
    3. Verifies the run_core_kernel call receives history with the first
       user+assistant turn, and the current (second) user message is NOT
       duplicated in history.
    """
    from lamtools_core.llm import LLMResponse, LLMToolCall
    from lamtools_core.kernel import KernelResult

    captured_calls: list[dict] = []

    async def _fake_run_core_kernel(**kwargs):
        captured_calls.append(kwargs)
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-history-test",
            decision="done",
            message="基于之前的上下文，这是回复。",
            metadata={
                "core_events": [],
                "steps_count": 1,
                "tool_results_summary": [],
                "verification_summaries": [],
            },
        )

    async def _fake_resolve_llm_config(db, route):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = Settings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            llm_api_key="test",
        )

        engine = create_async_engine(settings.database_url, future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]

        async with session_factory() as db:
            session = WriterSession(
                id="session-history-test",
                title="test",
                work_root=str(tmp_path / "workspace"),
            )
            db.add(session)
            await db.commit()

            await run_turn(db, "session-history-test", "第一个问题")
            result = await db.execute(
                select(WriterMessage)
                .where(WriterMessage.session_id == "session-history-test")
                .order_by(WriterMessage.created_at)
            )
            messages_after_first = result.scalars().all()
            assert len(messages_after_first) == 2
            assert messages_after_first[0].role == "user"
            assert messages_after_first[0].content == "第一个问题"
            assert messages_after_first[1].role == "assistant"

            captured_calls.clear()

            await run_turn(db, "session-history-test", "第二个问题")

            assert len(captured_calls) == 1
            call_kwargs = captured_calls[0]
            history = call_kwargs.get("history", [])

            assert len(history) >= 2
            assert history[-2]["role"] == "user"
            assert history[-2]["content"] == "第一个问题"
            assert history[-1]["role"] == "assistant"
            assert history[-1]["content"] == "基于之前的上下文，这是回复。"

            history_user_contents = [
                h["content"] for h in history if h["role"] == "user"
            ]
            assert "第二个问题" not in history_user_contents

            assert call_kwargs["goal"] == "第二个问题"
            assert call_kwargs["state_store"] is not None
            assert hasattr(call_kwargs["state_store"], "get")
            assert hasattr(call_kwargs["state_store"], "save")

        await engine.dispose()


@pytest.mark.asyncio
async def test_core_kernel_service_path_filters_tool_internal_from_history(monkeypatch):
    """Service path: tool/internal messages are excluded from history passed to Core."""
    from lamtools_core.kernel import KernelResult

    captured_calls: list[dict] = []

    async def _fake_run_core_kernel(**kwargs):
        captured_calls.append(kwargs)
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-filter-test",
            decision="done",
            message="回复",
            metadata={
                "core_events": [],
                "steps_count": 1,
                "tool_results_summary": [],
                "verification_summaries": [],
            },
        )

    async def _fake_resolve_llm_config(db, route):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = Settings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            llm_api_key="test",
        )

        engine = create_async_engine(settings.database_url, future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]

        async with session_factory() as db:
            session = WriterSession(
                id="session-filter-test",
                title="test",
                work_root=str(tmp_path / "workspace"),
            )
            db.add(session)
            await db.commit()

            tool_msg = WriterMessage(
                id="msg-tool-1",
                session_id="session-filter-test",
                role="tool",
                content="Tool output here",
            )
            internal_msg = WriterMessage(
                id="msg-internal-1",
                session_id="session-filter-test",
                role="internal",
                content="Internal reasoning",
            )
            user_msg = WriterMessage(
                id="msg-user-1",
                session_id="session-filter-test",
                role="user",
                content="Earlier question",
            )
            assistant_msg = WriterMessage(
                id="msg-assistant-1",
                session_id="session-filter-test",
                role="assistant",
                content="Earlier answer",
            )
            db.add(tool_msg)
            db.add(internal_msg)
            db.add(user_msg)
            db.add(assistant_msg)
            await db.commit()

            captured_calls.clear()
            await run_turn(db, "session-filter-test", "新问题")

            assert len(captured_calls) == 1
            history = captured_calls[0].get("history", [])

            roles = [h["role"] for h in history]
            assert "tool" not in roles
            assert "internal" not in roles

            user_contents = [h["content"] for h in history if h["role"] == "user"]
            assert "Earlier question" in user_contents
            assert "新问题" not in user_contents

        await engine.dispose()


@pytest.mark.asyncio
async def test_core_kernel_wait_question_fallback_priority(monkeypatch):
    """等待问题优先级：summary.message → summary.error → summary.decision。

    当 message 为空时 fallback 到 error，再 fallback 到 decision。
    """
    from lamtools_core.kernel import KernelResult

    async def _fake_resolve_llm_config(db, route):
        return {"provider": "test", "model": "test-model"}

    def _fake_build_llm_client(resolved, thinking_enabled=None, thinking_budget=None):
        return object()

    async def _fake_run_core_kernel_no_msg(**kwargs):
        return KernelResult(
            session_id=kwargs["session_id"],
            run_id="run-wait-nomsg",
            decision="wait",
            message="",
            metadata={
                "core_events": [],
                "steps_count": 0,
                "tool_results_summary": [],
                "verification_summaries": [],
            },
        )

    monkeypatch.setattr(writer_service_module, "resolve_llm_config", _fake_resolve_llm_config)
    monkeypatch.setattr(writer_service_module, "build_llm_client", _fake_build_llm_client)
    monkeypatch.setattr(writer_service_module, "run_core_kernel", _fake_run_core_kernel_no_msg)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = Settings(
            data_dir=str(tmp_path / "data"),
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
            llm_api_key="test",
        )

        engine = create_async_engine(settings.database_url, future=True)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        services = writer_orchestrate(settings)
        run_turn = services["run_turn"]

        async with session_factory() as db:
            session = WriterSession(
                id="session-wait-fallback-test",
                title="test",
                work_root=str(tmp_path / "workspace"),
            )
            db.add(session)
            await db.commit()

            await run_turn(db, "session-wait-fallback-test", "继续")

        async with session_factory() as db:
            blocks = await _transcript_blocks(db, "session-wait-fallback-test")
        wait_blocks = [block for block in blocks if block.type == "waiting_request"]
        assert wait_blocks == []

        await engine.dispose()
