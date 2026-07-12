from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .read import model_response, provider_response
from .shared_database import LLMModel, LLMProvider


async def create_provider_config(db: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data)
    payload["is_default"] = False
    provider = LLMProvider(**payload)
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return provider_response(provider)


async def update_provider_config(
    db: AsyncSession,
    provider_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    provider = await db.get(LLMProvider, provider_id)
    if provider is None:
        raise LookupError("Provider not found")

    update_data = dict(data)
    update_data.pop("is_default", None)
    if "api_key" in update_data and update_data["api_key"] in {"", "********"}:
        update_data.pop("api_key")
    for key, value in update_data.items():
        setattr(provider, key, value)

    await db.commit()
    await db.refresh(provider)
    return provider_response(provider)


async def delete_provider_config(db: AsyncSession, provider_id: str) -> None:
    provider = await db.get(LLMProvider, provider_id)
    if provider is None:
        raise LookupError("Provider not found")
    result = await db.execute(select(LLMModel).where(LLMModel.provider_id == provider_id))
    for model in result.scalars().all():
        await db.delete(model)
    await db.delete(provider)
    await db.commit()


async def create_model_config(db: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    provider_id = str(data.get("provider_id") or "")
    if not provider_id or await db.get(LLMProvider, provider_id) is None:
        raise LookupError("Provider not found")
    payload = dict(data)
    payload["is_default"] = False
    model = LLMModel(**payload)
    db.add(model)
    await db.flush()
    await db.commit()
    await db.refresh(model)
    return model_response(model)


async def update_model_config(db: AsyncSession, model_id: str, data: dict[str, Any]) -> dict[str, Any]:
    model = await db.get(LLMModel, model_id)
    if model is None:
        raise LookupError("Model not found")

    provider_id = data.get("provider_id")
    if provider_id and provider_id != model.provider_id:
        provider = await db.get(LLMProvider, str(provider_id))
        if provider is None:
            raise ValueError("Provider not found")

    update_data = dict(data)
    update_data.pop("is_default", None)
    for key, value in update_data.items():
        setattr(model, key, value)

    await db.commit()
    await db.refresh(model)
    return model_response(model)


async def delete_model_config(db: AsyncSession, model_id: str, *, commit: bool = True) -> None:
    model = await db.get(LLMModel, model_id)
    if model is None:
        raise LookupError("Model not found")
    await db.delete(model)
    await db.flush()
    if commit:
        await db.commit()


__all__ = [
    "create_model_config",
    "create_provider_config",
    "delete_model_config",
    "delete_provider_config",
    "update_model_config",
    "update_provider_config",
]
