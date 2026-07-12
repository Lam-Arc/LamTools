from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.llm_config import LLMModel, LLMProvider
from app.utils.llm_client import LLMClient


MODEL_ROUTING_NAMESPACE = "lamwriter.modelRouting"
MODEL_ROUTING_VERSION = 1

DEFAULT_ROUTE_TASK_TYPES = [
    "writer",
    "sub_agent",
]
EXECUTION_ROUTE_TASK_TYPES = {"writer"}
AGENT_ROUTE_TASK_TYPES = {"sub_agent"}


@dataclass(frozen=True)
class ResolvedLLMConfig:
    provider: LLMProvider
    model: LLMModel
    task_type: str
    matched_rule: bool


async def _model_exists(db: AsyncSession, model_id: str | None) -> LLMModel | None:
    if not model_id:
        return None
    model = await db.get(LLMModel, model_id)
    if model is not None:
        return model
    result = await db.execute(
        select(LLMModel)
        .where(LLMModel.model_id == model_id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _fallback_model(db: AsyncSession) -> LLMModel | None:
    # Legacy fallback only. New runtime routing is driven by routes["writer"],
    # not by an API-level "default model" flag.
    setting = await db.get(AppSetting, MODEL_ROUTING_NAMESPACE)
    raw = setting.value if setting is not None and isinstance(setting.value, dict) else {}
    routes = raw.get("routes") if isinstance(raw.get("routes"), dict) else {}
    writer_entry = routes.get("writer") if isinstance(routes.get("writer"), dict) else {}
    writer_route = str(writer_entry.get("model_id") or "")
    model = await _model_exists(db, writer_route)
    if model is not None:
        return model
    first_model_result = await db.execute(
        select(LLMModel).order_by(LLMModel.created_at.asc()).limit(1)
    )
    return first_model_result.scalar_one_or_none()


def _route_entry(mode: str, model_id: str | None = None) -> dict[str, str | None]:
    if mode == "model" and model_id:
        return {"mode": "model", "model_id": model_id}
    return {"mode": "follow_default", "model_id": None}


async def _initial_model_routing_state(db: AsyncSession, default_model: LLMModel) -> dict:
    writer_model_id = default_model.id
    if await _model_exists(db, writer_model_id) is None:
        writer_model_id = default_model.id

    routes: dict[str, dict[str, str | None]] = {
        "writer": _route_entry("model", writer_model_id),
    }
    for task_type in AGENT_ROUTE_TASK_TYPES:
        routes[task_type] = _route_entry("follow_default")

    return {
        "version": MODEL_ROUTING_VERSION,
        "routes": routes,
    }


async def ensure_model_routing_state(
    db: AsyncSession,
    *,
    default_model_id: str | None = None,
) -> dict:
    """Ensure the normalized model-routing setting exists and is valid."""
    fallback = await _model_exists(db, default_model_id) or await _fallback_model(db)
    if fallback is None:
        return {"version": MODEL_ROUTING_VERSION, "routes": {}}

    setting = await db.get(AppSetting, MODEL_ROUTING_NAMESPACE)
    raw = setting.value if setting is not None and isinstance(setting.value, dict) else None
    if raw is None:
        value = await _initial_model_routing_state(db, fallback)
    else:
        raw_routes = raw.get("routes") if isinstance(raw.get("routes"), dict) else {}
        legacy_default_model_id = str(raw.get("default_model_id") or default_model_id or fallback.id)
        writer_entry = raw_routes.get("writer") if isinstance(raw_routes.get("writer"), dict) else {}
        writer_model_id = str(writer_entry.get("model_id") or legacy_default_model_id)
        if await _model_exists(db, writer_model_id) is None:
            writer_model_id = fallback.id
        value = {
            "version": MODEL_ROUTING_VERSION,
            "routes": raw_routes,
        }
        routes = dict(value["routes"])
        routes["writer"] = _route_entry("model", writer_model_id)
        for task_type in AGENT_ROUTE_TASK_TYPES:
            entry = routes.get(task_type) if isinstance(routes.get(task_type), dict) else {}
            mode = str(entry.get("mode") or "follow_default")
            model_id = str(entry.get("model_id") or "")
            if mode == "model" and await _model_exists(db, model_id) is not None:
                routes[task_type] = _route_entry("model", model_id)
            else:
                routes[task_type] = _route_entry("follow_default")
        value["routes"] = routes

    if setting is None:
        setting = AppSetting(namespace=MODEL_ROUTING_NAMESPACE, value=value)
        db.add(setting)
    else:
        setting.value = value
    return value


async def _set_writer_model(db: AsyncSession, model_id: str) -> dict:
    model = await _model_exists(db, model_id)
    if model is None:
        raise ValueError("Model not found")
    value = await ensure_model_routing_state(db, default_model_id=model.id)
    value.setdefault("routes", {})["writer"] = _route_entry("model", model.id)
    setting = await db.get(AppSetting, MODEL_ROUTING_NAMESPACE)
    if setting is None:
        setting = AppSetting(namespace=MODEL_ROUTING_NAMESPACE, value=value)
        db.add(setting)
    else:
        setting.value = value
    return value


async def set_route_model(db: AsyncSession, task_type: str, model_id: str | None) -> dict:
    normalized = (task_type or "writer").strip() or "writer"
    if normalized in EXECUTION_ROUTE_TASK_TYPES:
        if not model_id:
            value = await ensure_model_routing_state(db)
        else:
            value = await _set_writer_model(db, model_id)
        return value

    value = await ensure_model_routing_state(db)
    routes = value.setdefault("routes", {})
    if not model_id:
        routes[normalized] = _route_entry("follow_default")
    else:
        model = await _model_exists(db, model_id)
        if model is None:
            raise ValueError("Model not found")
        routes[normalized] = _route_entry("model", model.id)
    setting = await db.get(AppSetting, MODEL_ROUTING_NAMESPACE)
    if setting is None:
        setting = AppSetting(namespace=MODEL_ROUTING_NAMESPACE, value=value)
        db.add(setting)
    else:
        setting.value = value
    return value


async def resolve_llm_config(db: AsyncSession, task_type: str = "default", *, model_id: str | None = None) -> ResolvedLLMConfig | None:
    """Resolve provider/model from DB only.

    .env is intentionally not used here. Startup seed may copy .env into DB
    when DB has no providers, but runtime resolution is DB-first and DB-only.

    When `model_id` is provided, it bypasses routing rules and resolves the
    specified model directly, enabling per-request model switching.
    """
    normalized = (task_type or "writer").strip() or "writer"

    # ── Direct model override (per-request switching) ──
    if model_id:
        model = await _model_exists(db, model_id)
        if model is None:
            raise ValueError("Model not found")
        provider = await db.get(LLMProvider, model.provider_id)
        if provider is None:
            raise ValueError("Model provider not found")
        return ResolvedLLMConfig(
            provider=provider,
            model=model,
            task_type=normalized,
            matched_rule=False,
        )

    routing_state = await ensure_model_routing_state(db)
    routes = routing_state.get("routes") if isinstance(routing_state.get("routes"), dict) else {}
    writer_entry = routes.get("writer") if isinstance(routes.get("writer"), dict) else {}
    writer_model_id = str(writer_entry.get("model_id") or "")
    resolved_model_id = writer_model_id
    route_candidates = [normalized]
    if normalized.startswith("sub_agent:"):
        route_candidates.append("sub_agent")
    if normalized not in EXECUTION_ROUTE_TASK_TYPES:
        entry: dict = {}
        for route_candidate in route_candidates:
            candidate_entry = routes.get(route_candidate) if isinstance(routes.get(route_candidate), dict) else {}
            if str(candidate_entry.get("mode") or "") == "model":
                entry = candidate_entry
                break
        if str(entry.get("mode") or "") == "model":
            route_model_id = str(entry.get("model_id") or "")
            if await _model_exists(db, route_model_id) is not None:
                resolved_model_id = route_model_id
    model = await _model_exists(db, resolved_model_id)
    if model is not None:
        provider = await db.get(LLMProvider, model.provider_id)
        if provider is not None:
            return ResolvedLLMConfig(
                provider=provider,
                model=model,
                task_type=normalized,
                matched_rule=normalized not in EXECUTION_ROUTE_TASK_TYPES and model.id != writer_model_id,
            )

    return None


def build_llm_client(
    resolved: ResolvedLLMConfig,
    thinking_enabled: bool | None = None,
    thinking_budget: int | None = None,
) -> LLMClient:
    return LLMClient(
        base_url=resolved.provider.base_url,
        api_key=resolved.provider.api_key,
        model_id=resolved.model.model_id,
        api_type=resolved.provider.api_type,
        thinking_enabled=thinking_enabled if thinking_enabled is not None else resolved.model.thinking_supported,
        thinking_budget=thinking_budget if thinking_budget is not None else resolved.model.thinking_budget,
        max_tokens=resolved.model.max_output_tokens,
        temperature=resolved.model.temperature,
        context_window=resolved.model.context_window,
        provider_extra=resolved.provider.extra,
        model_extra=resolved.model.extra,
    )


async def ensure_writer_routing(db: AsyncSession, provider_id: str, model_id: str) -> None:
    await ensure_model_routing_state(db, default_model_id=model_id)
