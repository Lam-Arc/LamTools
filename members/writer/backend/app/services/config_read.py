from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.llm_config_service import resolve_llm_config
from app.utils.llm_adapter_profiles import load_adapter_profiles
from lamtools_core.config import (
    list_model_configs,
    list_provider_configs,
    model_response,
    provider_response,
)


async def resolved_config_response(db: AsyncSession, task_type: str = "default") -> dict[str, Any] | None:
    resolved = await resolve_llm_config(db, task_type)
    if resolved is None:
        return None
    return {
        "provider": provider_response(resolved.provider),
        "model": model_response(resolved.model),
        "task_type": resolved.task_type,
        "matched_rule": resolved.matched_rule,
    }


def list_adapter_profile_configs() -> list[dict[str, Any]]:
    profiles = []
    for profile in load_adapter_profiles().values():
        raw_patterns = profile.get("match_base_url") or []
        if isinstance(raw_patterns, str):
            raw_patterns = [raw_patterns]
        profiles.append({
            "id": str(profile.get("id") or ""),
            "label": str(profile.get("label") or profile.get("id") or ""),
            "protocol": str(profile.get("protocol") or ""),
            "match_base_url": [str(item) for item in raw_patterns],
            "endpoint": str(profile.get("endpoint")) if profile.get("endpoint") else None,
        })
    return sorted(profiles, key=lambda item: item["id"])


__all__ = [
    "list_adapter_profile_configs",
    "list_model_configs",
    "list_provider_configs",
    "model_response",
    "provider_response",
    "resolved_config_response",
]
