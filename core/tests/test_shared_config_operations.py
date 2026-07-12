from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lamtools_core.config import build_shared_config_operation_catalog, init_shared_config_schema


async def _session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'shared-config-ops.db'}")
    await init_shared_config_schema(engine)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_shared_config_operations_create_list_update_and_delete_provider_model(tmp_path):
    engine, session_factory = await _session_factory(tmp_path)
    try:
        catalog = build_shared_config_operation_catalog(session_factory)

        created_provider = await catalog.execute(
            "config.provider.create",
            {
                "name": "Provider",
                "api_type": "openai",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-secret-value",
            },
        )
        provider = created_provider.payload["provider"]
        assert provider["api_key"] == "********"
        assert "sk-secret-value" not in str(provider)

        listed_providers = await catalog.execute("config.providers.list")
        assert [item["id"] for item in listed_providers.payload["providers"]] == [provider["id"]]

        updated_provider = await catalog.execute(
            "config.provider.update",
            {"provider_id": provider["id"], "name": "Updated Provider", "api_key": "********"},
        )
        assert updated_provider.payload["provider"]["name"] == "Updated Provider"
        assert updated_provider.payload["provider"]["api_key"] == "********"

        created_model = await catalog.execute(
            "config.model.create",
            {
                "provider_id": provider["id"],
                "model_id": "model-a",
                "display_name": "Model A",
                "thinking_supported": True,
            },
        )
        model = created_model.payload["model"]
        assert model["thinking_supported"] is True

        zero_model = await catalog.execute(
            "config.model.create",
            {
                "provider_id": provider["id"],
                "model_id": "model-zero",
                "thinking_budget": 0,
                "temperature": 0,
            },
        )
        assert zero_model.payload["model"]["thinking_budget"] == 0
        assert zero_model.payload["model"]["temperature"] == 0

        listed_models = await catalog.execute("config.models.list", {"provider_id": provider["id"]})
        assert {item["id"] for item in listed_models.payload["models"]} == {
            model["id"],
            zero_model.payload["model"]["id"],
        }

        updated_model = await catalog.execute(
            "config.model.update",
            {"model_record_id": model["id"], "display_name": "Model A2", "temperature": 0.3},
        )
        assert updated_model.payload["model"]["display_name"] == "Model A2"

        deleted_model = await catalog.execute("config.model.delete", {"model_record_id": model["id"]})
        assert deleted_model.payload == {"ok": True}

        deleted_provider = await catalog.execute("config.provider.delete", {"provider_id": provider["id"]})
        assert deleted_provider.payload == {"ok": True}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_shared_config_operations_return_validation_errors(tmp_path):
    engine, session_factory = await _session_factory(tmp_path)
    try:
        catalog = build_shared_config_operation_catalog(session_factory)

        provider = await catalog.execute("config.provider.create", {})
        model = await catalog.execute("config.model.update", {})

        assert provider.status == "error"
        assert provider.payload["error"] == "name, base_url and api_key are required"
        assert model.status == "error"
        assert model.payload["error"] == "model_record_id is required"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_shared_config_operations_retry_sqlite_locked_writes():
    attempts = 0

    @asynccontextmanager
    async def dummy_session_factory():
        yield object()

    async def flaky_create_provider(db, payload):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OperationalError("INSERT INTO llm_providers", {}, Exception("database is locked"))
        return {"id": "provider-retry", "name": payload["name"]}

    catalog = build_shared_config_operation_catalog(
        dummy_session_factory,
        sqlite_lock_retry_delays=(0, 0),
        create_provider=flaky_create_provider,
    )

    result = await catalog.execute(
        "config.provider.create",
        {
            "name": "Retry Provider",
            "base_url": "https://api.retry.test/v1",
            "api_key": "sk-retry",
        },
    )

    assert attempts == 3
    assert result.payload["provider"]["id"] == "provider-retry"
