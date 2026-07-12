from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .shared_database import LLMModel, LLMProvider


def provider_response(provider: LLMProvider) -> dict[str, Any]:
    api_key = provider.api_key or ""
    return {
        "id": provider.id,
        "name": provider.name,
        "api_type": provider.api_type,
        "base_url": provider.base_url,
        "api_key": "********" if api_key else "",
        "is_default": bool(provider.is_default),
        "extra": provider.extra,
        "created_at": provider.created_at,
        "updated_at": provider.updated_at,
        "has_api_key": bool(api_key),
    }


def model_response(model: LLMModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "provider_id": model.provider_id,
        "model_id": model.model_id,
        "display_name": model.display_name,
        "context_window": model.context_window,
        "max_output_tokens": model.max_output_tokens,
        "thinking_supported": bool(model.thinking_supported),
        "thinking_budget": model.thinking_budget,
        "temperature": model.temperature,
        "is_default": bool(model.is_default),
        "extra": model.extra,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
    }


async def list_provider_configs(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(LLMProvider)
        .order_by(LLMProvider.name.asc())
        .offset(offset)
        .limit(limit)
    )
    return [provider_response(provider) for provider in result.scalars().all()]


async def list_model_configs(
    db: AsyncSession,
    *,
    provider_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    stmt = select(LLMModel).order_by(LLMModel.display_name.asc(), LLMModel.model_id.asc())
    if provider_id:
        stmt = stmt.where(LLMModel.provider_id == provider_id)
    result = await db.execute(stmt.offset(offset).limit(limit))
    return [model_response(model) for model in result.scalars().all()]


__all__ = [
    "list_model_configs",
    "list_provider_configs",
    "model_response",
    "provider_response",
]
