from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _gen_uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now()


class SharedConfigBase(DeclarativeBase):
    pass


class LLMProvider(SharedConfigBase):
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_gen_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    api_type: Mapped[str] = mapped_column(String(50), default="openai")
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    api_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict[str, Any] | None] = mapped_column("extra", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class LLMModel(SharedConfigBase):
    __tablename__ = "llm_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_gen_uuid)
    provider_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("llm_providers.id"),
        nullable=False,
    )
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    context_window: Mapped[int] = mapped_column(Integer, default=128000)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=16384)
    thinking_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    thinking_budget: Mapped[int] = mapped_column(Integer, default=10000)
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict[str, Any] | None] = mapped_column("extra", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class AppSetting(SharedConfigBase):
    __tablename__ = "app_settings"

    namespace: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


async def init_shared_config_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SharedConfigBase.metadata.create_all)


__all__ = [
    "AppSetting",
    "LLMModel",
    "LLMProvider",
    "SharedConfigBase",
    "init_shared_config_schema",
]
