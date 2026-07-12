from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lamtools_core.config.shared_database import (
    AppSetting,
    LLMModel,
    LLMProvider,
    init_shared_config_schema,
)


@pytest.mark.asyncio
async def test_core_initializes_shared_config_schema_without_member_base(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'shared.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await init_shared_config_schema(engine)

        async with engine.connect() as conn:
            result = await conn.execute(text("select name from sqlite_master where type='table'"))
            tables = {str(row[0]) for row in result.fetchall()}

        async with session_factory() as db:
            provider = LLMProvider(
                name="Shared Provider",
                api_type="openai",
                base_url="https://shared.example/v1",
                api_key="secret",
            )
            db.add(provider)
            await db.flush()
            db.add(
                LLMModel(
                    provider_id=provider.id,
                    model_id="shared-model",
                    display_name="Shared Model",
                )
            )
            db.add(AppSetting(namespace="lamtools.modelRouting", value={"routes": {}}))
            await db.commit()

        assert {"llm_providers", "llm_models", "app_settings"} <= tables
    finally:
        await engine.dispose()
