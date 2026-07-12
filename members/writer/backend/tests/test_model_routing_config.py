from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.app_setting import AppSetting
from app.models.llm_config import LLMModel, LLMProvider
from app.services.llm_config_service import (
    MODEL_ROUTING_NAMESPACE,
    ensure_model_routing_state,
    resolve_llm_config,
    set_route_model,
)
from lamtools_core.config.shared_database import init_shared_config_schema


@pytest.mark.asyncio
async def test_model_routing_state_initializes_and_preserves_sub_agent_model(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await init_shared_config_schema(engine)

        async with session_factory() as db:
            provider = LLMProvider(
                name="Test",
                api_type="openai",
                base_url="https://example.test/v1",
                api_key="test-key",
                is_default=True,
            )
            db.add(provider)
            await db.flush()
            main_model = LLMModel(
                provider_id=provider.id,
                model_id="main-model",
                display_name="Main",
                is_default=True,
            )
            agent_model = LLMModel(
                provider_id=provider.id,
                model_id="agent-model",
                display_name="Agent",
            )
            db.add_all([main_model, agent_model])
            await db.flush()

            state = await ensure_model_routing_state(db, default_model_id=main_model.id)
            assert "default_model_id" not in state
            assert state["routes"]["writer"] == {
                "mode": "model",
                "model_id": main_model.id,
            }
            assert state["routes"]["sub_agent"]["mode"] == "follow_default"

            await set_route_model(db, "sub_agent", agent_model.id)
            await set_route_model(db, "writer", main_model.id)
            await db.commit()

            setting = await db.get(AppSetting, MODEL_ROUTING_NAMESPACE)
            assert setting is not None
            assert "default_model_id" not in setting.value
            assert setting.value["routes"]["writer"] == {
                "mode": "model",
                "model_id": main_model.id,
            }
            assert setting.value["routes"]["sub_agent"] == {
                "mode": "model",
                "model_id": agent_model.id,
            }

            resolved_writer = await resolve_llm_config(db, "writer")
            resolved_agent = await resolve_llm_config(db, "sub_agent")
            assert resolved_writer is not None
            assert resolved_writer.model.model_id == "main-model"
            assert resolved_agent is not None
            assert resolved_agent.model.model_id == "agent-model"
            assert resolved_agent.matched_rule is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sub_agent_named_route_overrides_general_sub_agent_route(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await init_shared_config_schema(engine)

        async with session_factory() as db:
            provider = LLMProvider(
                name="Test",
                api_type="openai",
                base_url="https://example.test/v1",
                api_key="test-key",
                is_default=True,
            )
            db.add(provider)
            await db.flush()
            main_model = LLMModel(provider_id=provider.id, model_id="main-model", display_name="Main", is_default=True)
            general_model = LLMModel(provider_id=provider.id, model_id="general-sub-model", display_name="General")
            worker_model = LLMModel(provider_id=provider.id, model_id="worker-model", display_name="Worker")
            db.add_all([main_model, general_model, worker_model])
            await db.flush()

            await ensure_model_routing_state(db, default_model_id=main_model.id)
            await set_route_model(db, "sub_agent", general_model.id)
            await set_route_model(db, "sub_agent:worker", worker_model.id)
            await db.commit()

            resolved_worker = await resolve_llm_config(db, "sub_agent:worker")
            resolved_reviewer = await resolve_llm_config(db, "sub_agent:reviewer")

            assert resolved_worker is not None
            assert resolved_worker.model.model_id == "worker-model"
            assert resolved_reviewer is not None
            assert resolved_reviewer.model.model_id == "general-sub-model"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_direct_model_override_accepts_model_identifier(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await init_shared_config_schema(engine)

        async with session_factory() as db:
            provider = LLMProvider(
                name="Test",
                api_type="openai",
                base_url="https://example.test/v1",
                api_key="test-key",
                is_default=True,
            )
            db.add(provider)
            await db.flush()
            main_model = LLMModel(provider_id=provider.id, model_id="main-model", display_name="Main", is_default=True)
            named_model = LLMModel(provider_id=provider.id, model_id="fast-sub-model", display_name="Fast")
            db.add_all([main_model, named_model])
            await db.flush()
            await ensure_model_routing_state(db, default_model_id=main_model.id)
            await db.commit()

            resolved = await resolve_llm_config(db, "sub_agent:explorer", model_id="fast-sub-model")

            assert resolved is not None
            assert resolved.model.id == named_model.id
            assert resolved.model.model_id == "fast-sub-model"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_direct_model_override_rejects_unknown_model_instead_of_routing_elsewhere(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await init_shared_config_schema(engine)
        async with session_factory() as db:
            with pytest.raises(ValueError, match="Model not found"):
                await resolve_llm_config(db, "sub_agent", model_id="missing-model")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_default_model_id_migrates_to_writer_route(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await init_shared_config_schema(engine)

        async with session_factory() as db:
            provider = LLMProvider(
                name="Test",
                api_type="openai",
                base_url="https://example.test/v1",
                api_key="test-key",
            )
            db.add(provider)
            await db.flush()
            main_model = LLMModel(provider_id=provider.id, model_id="main-model", display_name="Main")
            db.add(main_model)
            await db.flush()
            db.add(AppSetting(
                namespace=MODEL_ROUTING_NAMESPACE,
                value={"version": 1, "default_model_id": main_model.id, "routes": {}},
            ))

            state = await ensure_model_routing_state(db)
            await db.commit()

            assert "default_model_id" not in state
            assert state["routes"]["writer"] == {
                "mode": "model",
                "model_id": main_model.id,
            }
            resolved = await resolve_llm_config(db, "sub_agent:reviewer")
            assert resolved is not None
            assert resolved.model.id == main_model.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_model_routing_setting_is_the_only_runtime_route_source(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await init_shared_config_schema(engine)

        async with session_factory() as db:
            provider = LLMProvider(
                name="Test",
                api_type="openai",
                base_url="https://example.test/v1",
                api_key="test-key",
            )
            db.add(provider)
            await db.flush()
            writer_model = LLMModel(provider_id=provider.id, model_id="writer-model", display_name="Writer")
            db.add(writer_model)
            await db.flush()
            db.add(AppSetting(
                namespace=MODEL_ROUTING_NAMESPACE,
                value={
                    "version": 1,
                    "routes": {
                        "writer": {"mode": "model", "model_id": writer_model.id},
                        "sub_agent": {"mode": "follow_default", "model_id": None},
                    },
                },
            ))

            resolved = await resolve_llm_config(db, "sub_agent:reviewer")
            await db.commit()

            assert resolved is not None
            assert resolved.model.model_id == "writer-model"
    finally:
        await engine.dispose()
