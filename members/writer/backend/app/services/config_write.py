from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_config import LLMModel, LLMProvider
from app.services.config_read import model_response, provider_response
from app.services.llm_config_service import ensure_model_routing_state, set_route_model
from lamtools_core.config import (
    create_model_config,
    create_provider_config,
    delete_model_config as core_delete_model_config,
    delete_provider_config,
    update_model_config,
    update_provider_config,
)


async def delete_model_config(db: AsyncSession, model_id: str) -> None:
    await core_delete_model_config(db, model_id, commit=False)
    await ensure_model_routing_state(db)
    await db.commit()


async def import_env_provider_model_config(db: AsyncSession) -> dict[str, Any]:
    from app.config import settings

    if not settings.llm_api_key:
        raise ValueError("No LLM API key configured in environment")

    provider_result = await db.execute(
        select(LLMProvider)
        .where(LLMProvider.base_url == settings.llm_base_url, LLMProvider.api_key == settings.llm_api_key)
        .limit(1)
    )
    provider = provider_result.scalar_one_or_none()
    if provider is None:
        provider = LLMProvider(
            name="Default from environment",
            api_type=settings.llm_api_type,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            is_default=False,
        )
        db.add(provider)
        await db.flush()
    else:
        provider.name = "Default from environment"
        provider.api_type = settings.llm_api_type
        provider.is_default = False

    model_result = await db.execute(
        select(LLMModel)
        .where(LLMModel.provider_id == provider.id, LLMModel.model_id == settings.llm_model)
        .limit(1)
    )
    model = model_result.scalar_one_or_none()
    if model is None:
        model = LLMModel(
            provider_id=provider.id,
            model_id=settings.llm_model,
            display_name=settings.llm_model,
            context_window=settings.llm_context_window,
            max_output_tokens=settings.llm_max_tokens,
            thinking_supported=settings.llm_thinking_enabled,
            thinking_budget=settings.llm_thinking_budget,
            temperature=settings.llm_temperature,
            is_default=False,
        )
        db.add(model)
        await db.flush()
    else:
        model.display_name = model.display_name or settings.llm_model
        model.context_window = settings.llm_context_window
        model.max_output_tokens = settings.llm_max_tokens
        model.thinking_supported = settings.llm_thinking_enabled
        model.thinking_budget = settings.llm_thinking_budget
        model.temperature = settings.llm_temperature

    await set_route_model(db, "writer", model.id)
    await db.commit()
    await db.refresh(provider)
    await db.refresh(model)
    return {
        "provider": provider_response(provider),
        "model": model_response(model),
        "route_updated": True,
    }


__all__ = [
    "create_model_config",
    "create_provider_config",
    "delete_model_config",
    "delete_provider_config",
    "import_env_provider_model_config",
    "update_model_config",
    "update_provider_config",
]
