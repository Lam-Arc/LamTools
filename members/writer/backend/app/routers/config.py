from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, computed_field, field_serializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.llm_config import LLMProvider, LLMModel
from app.shared_config_database import get_shared_config_db
from app.services.app_settings import get_app_setting_value, update_app_setting_value
from app.services.config_read import (
    list_adapter_profile_configs,
    list_model_configs,
    list_provider_configs,
    resolved_config_response,
)
from app.services.config_write import (
    create_model_config,
    create_provider_config,
    delete_model_config,
    delete_provider_config,
    import_env_provider_model_config,
    update_model_config,
    update_provider_config,
)
from app.services.llm_config_service import (
    MODEL_ROUTING_NAMESPACE,
    ensure_model_routing_state,
    ensure_writer_routing,
    set_route_model,
)
from app.services.runtime_capabilities import runtime_capabilities_response
from app.services.subagent_config import delete_project_subagent_config, upsert_project_subagent_config

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Provider Schemas ---

class ProviderCreate(BaseModel):
    name: str
    api_type: str = "openai"
    base_url: str
    api_key: str
    is_default: bool = False
    extra: dict | None = None


class ProviderUpdate(BaseModel):
    name: str | None = None
    api_type: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    is_default: bool | None = None
    extra: dict | None = None


class ProviderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    api_type: str
    base_url: str
    api_key: str
    is_default: bool
    extra: dict | None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    @field_serializer("api_key")
    def mask_api_key(self, value: str) -> str:
        if not value:
            return ""
        if len(value) <= 8:
            return "********"
        return f"{value[:4]}...{value[-4:]}"


# --- Model Schemas ---

class ModelCreate(BaseModel):
    provider_id: str
    model_id: str
    display_name: str = ""
    context_window: int = 128000
    max_output_tokens: int = 16384
    thinking_supported: bool = False
    thinking_budget: int = 10000
    temperature: float = 0.7
    is_default: bool = False
    extra: dict | None = None


class ModelUpdate(BaseModel):
    provider_id: str | None = None
    model_id: str | None = None
    display_name: str | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    thinking_supported: bool | None = None
    thinking_budget: int | None = None
    temperature: float | None = None
    is_default: bool | None = None
    extra: dict | None = None


class ModelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider_id: str
    model_id: str
    display_name: str
    context_window: int
    max_output_tokens: int
    thinking_supported: bool
    thinking_budget: int
    temperature: float
    is_default: bool
    extra: dict | None
    created_at: datetime
    updated_at: datetime


class ResolvedConfig(BaseModel):
    """Resolved provider + model for a given task type."""
    provider: ProviderResponse
    model: ModelResponse
    task_type: str
    matched_rule: bool  # True when a non-writer route selected its own model.


class ImportEnvResponse(BaseModel):
    provider: ProviderResponse
    model: ModelResponse
    route_updated: bool


class AgentCapabilityResponse(BaseModel):
    name: str
    description: str
    aliases: list[str]
    modes: list[str]
    capabilities: list[str]
    can_parallel: bool
    can_call_agents: bool
    max_depth: int
    enabled: bool


class SubAgentDefinitionResponse(BaseModel):
    name: str
    description: str
    role: str
    developer_instructions: str = ""
    tools: list[str]
    model: str
    aliases: list[str]
    source: str
    enabled: bool


class SubAgentDefinitionUpsert(BaseModel):
    name: str
    description: str = ""
    role: str = ""
    developer_instructions: str = ""
    tools: list[str] = []
    model: str = ""
    aliases: list[str] = []


class ToolCapabilityResponse(BaseModel):
    name: str
    description: str
    permission: str
    permission_group: str = "regular"
    approval_policy: str = "auto_allow"
    enabled: bool


class RuntimeCapabilitiesResponse(BaseModel):
    agents: list[AgentCapabilityResponse]
    subagents: list[SubAgentDefinitionResponse] = []
    tools: list[ToolCapabilityResponse]
    command_policies: dict[str, str]


class AdapterProfileResponse(BaseModel):
    id: str
    label: str = ""
    protocol: str = ""
    match_base_url: list[str] = []
    endpoint: str | None = None


class SettingResponse(BaseModel):
    namespace: str
    value: dict
    updated_at: datetime | None = None


class SettingUpdate(BaseModel):
    value: dict


# --- Provider CRUD ---

@router.post("/config/providers", response_model=ProviderResponse)
async def create_provider(body: ProviderCreate, db: AsyncSession = Depends(get_shared_config_db)):
    return ProviderResponse(**await create_provider_config(db, body.model_dump()))


@router.get("/config/providers", response_model=list[ProviderResponse])
async def list_providers(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_shared_config_db),
):
    return [ProviderResponse(**row) for row in await list_provider_configs(db, limit=limit, offset=offset)]


@router.get("/config/providers/{provider_id}", response_model=ProviderResponse)
async def get_provider(provider_id: str, db: AsyncSession = Depends(get_shared_config_db)):
    provider = await db.get(LLMProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


@router.patch("/config/providers/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: str, body: ProviderUpdate, db: AsyncSession = Depends(get_shared_config_db)
):
    try:
        return ProviderResponse(**await update_provider_config(db, provider_id, body.model_dump(exclude_unset=True)))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/config/providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: str, db: AsyncSession = Depends(get_shared_config_db)):
    try:
        await delete_provider_config(db, provider_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/config/import-env", response_model=ImportEnvResponse)
async def import_env_config(db: AsyncSession = Depends(get_shared_config_db)):
    """Import current process LLM settings into DB and route Writer to it."""
    try:
        imported = await import_env_provider_model_config(db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ImportEnvResponse(
        provider=ProviderResponse(**imported["provider"]),
        model=ModelResponse(**imported["model"]),
        route_updated=bool(imported["route_updated"]),
    )


@router.get("/config/runtime-capabilities", response_model=RuntimeCapabilitiesResponse)
async def get_runtime_capabilities(
    work_root: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    shared_db: AsyncSession = Depends(get_shared_config_db),
):
    """Expose registered Writer agents and tools for settings UI."""
    return RuntimeCapabilitiesResponse(
        **await runtime_capabilities_response(db, work_root=work_root, shared_db=shared_db)
    )


@router.put("/config/subagents/{name}", response_model=SubAgentDefinitionResponse)
async def upsert_project_sub_agent_definition(
    name: str,
    body: SubAgentDefinitionUpsert,
    work_root: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Create or update a project-scoped subagent definition."""
    try:
        return SubAgentDefinitionResponse(
            **await upsert_project_subagent_config(
                db,
                name=name,
                payload=body.model_dump(),
                work_root=work_root,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/config/subagents/{name}", status_code=204)
async def delete_project_sub_agent_definition_route(
    name: str,
    work_root: str | None = Query(None),
):
    """Delete only project-scoped Writer subagent definitions."""
    try:
        removed = delete_project_subagent_config(name=name, work_root=work_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Project subagent definition not found")


@router.get("/config/adapter-profiles", response_model=list[AdapterProfileResponse])
async def list_adapter_profiles():
    """Expose built-in and user LLM adapter profiles for custom URL setup."""
    return [AdapterProfileResponse(**row) for row in list_adapter_profile_configs()]


@router.get("/config/settings/{namespace}", response_model=SettingResponse)
async def get_app_setting(
    namespace: str,
    db: AsyncSession = Depends(get_db),
    shared_db: AsyncSession = Depends(get_shared_config_db),
):
    return SettingResponse(**await get_app_setting_value(db, namespace, shared_db=shared_db))


@router.put("/config/settings/{namespace}", response_model=SettingResponse)
async def put_app_setting(
    namespace: str,
    body: SettingUpdate,
    db: AsyncSession = Depends(get_db),
    shared_db: AsyncSession = Depends(get_shared_config_db),
):
    try:
        return SettingResponse(
            **await update_app_setting_value(db, namespace, body.value, shared_db=shared_db)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- Model CRUD ---

@router.post("/config/models", response_model=ModelResponse)
async def create_model(body: ModelCreate, db: AsyncSession = Depends(get_shared_config_db)):
    try:
        return ModelResponse(**await create_model_config(db, body.model_dump()))
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/config/models", response_model=list[ModelResponse])
async def list_models(
    provider_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_shared_config_db),
):
    return [
        ModelResponse(**row)
        for row in await list_model_configs(db, provider_id=provider_id, limit=limit, offset=offset)
    ]


@router.get("/config/models/{model_id}", response_model=ModelResponse)
async def get_model(model_id: str, db: AsyncSession = Depends(get_shared_config_db)):
    model = await db.get(LLMModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.patch("/config/models/{model_id}", response_model=ModelResponse)
async def update_model(
    model_id: str, body: ModelUpdate, db: AsyncSession = Depends(get_shared_config_db)
):
    try:
        return ModelResponse(**await update_model_config(db, model_id, body.model_dump(exclude_unset=True)))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/config/models/{model_id}", status_code=204)
async def delete_model(model_id: str, db: AsyncSession = Depends(get_shared_config_db)):
    try:
        await delete_model_config(db, model_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --- Config Resolution ---

@router.get("/config/resolved", response_model=ResolvedConfig)
async def resolve_config(
    task_type: str = Query("default"),
    db: AsyncSession = Depends(get_shared_config_db),
):
    """Resolve provider + model from DB.

    .env is only used by startup seed when DB has no provider.
    """
    resolved = await resolved_config_response(db, task_type)
    if resolved is None:
        raise HTTPException(status_code=404, detail="No LLM config in DB")
    return ResolvedConfig(
        provider=ProviderResponse(**resolved["provider"]),
        model=ModelResponse(**resolved["model"]),
        task_type=str(resolved["task_type"]),
        matched_rule=bool(resolved["matched_rule"]),
    )


# --- Auto-Seed ---

async def seed_default_config(db: AsyncSession) -> None:
    """Seed default provider + model from .env settings if DB is empty.

    Called during app startup to ensure at least one provider/model exists.
    """
    # Check if any providers exist
    result = await db.execute(select(LLMProvider).limit(1))
    existing_provider = result.scalar_one_or_none()
    if existing_provider is not None:
        first_model_result = await db.execute(
            select(LLMModel).order_by(LLMModel.created_at.asc()).limit(1)
        )
        model = first_model_result.scalar_one_or_none()
        if model is not None:
            await ensure_writer_routing(db, model.provider_id, model.id)
            await db.commit()
        return  # Already has DB provider/model config

    from app.config import settings
    if not settings.llm_api_key:
        logger.info("No LLM API key configured, skipping config seed")
        return

    provider = LLMProvider(
        name="Default from .env",
        api_type=settings.llm_api_type,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        is_default=False,
    )
    db.add(provider)
    await db.flush()

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

    await ensure_writer_routing(db, provider.id, model.id)

    await db.commit()
    logger.info(f"Seeded default LLM config: provider={provider.name}, model={model.model_id}")
