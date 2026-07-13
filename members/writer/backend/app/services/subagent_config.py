from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.runtime_capabilities import runtime_controls


def _definition_response(definition: Any, *, enabled: bool) -> dict[str, Any]:
    return {
        "name": definition.name,
        "description": definition.description,
        "role": definition.role,
        "developer_instructions": definition.developer_instructions,
        "tools": list(definition.tools),
        "model": definition.model,
        "aliases": list(definition.aliases),
        "source": definition.source,
        "enabled": enabled,
    }


async def upsert_project_subagent_config(
    db: AsyncSession,
    *,
    name: str,
    payload: dict[str, Any],
    work_root: str | None = None,
) -> dict[str, Any]:
    from app.config import settings
    from app.core.writer.agent_runtime import (
        SubAgentDefinition,
        validate_project_sub_agent_name,
        write_project_sub_agent_definition,
    )

    effective_work_root = Path(work_root or settings.writer_work_root).resolve()
    safe_name = validate_project_sub_agent_name(name)
    body_name = validate_project_sub_agent_name(str(payload.get("name") or name))
    if body_name != safe_name:
        raise ValueError("Path name and body name must match")

    definition = write_project_sub_agent_definition(
        effective_work_root,
        SubAgentDefinition(
            name=safe_name,
            description=str(payload.get("description") or ""),
            role=str(payload.get("role") or safe_name),
            developer_instructions=str(payload.get("developer_instructions") or ""),
            tools=tuple(str(item) for item in payload.get("tools", []) if str(item).strip()),
            model=str(payload.get("model") or ""),
            aliases=tuple(str(item) for item in payload.get("aliases", []) if str(item).strip()),
            source="project",
        ),
    )

    controls = await runtime_controls(db)
    enabled = bool(controls["agents"].get(f"sub:{definition.name}", True))
    return _definition_response(definition, enabled=enabled)


def delete_project_subagent_config(
    *,
    name: str,
    work_root: str | None = None,
) -> bool:
    from app.config import settings
    from app.core.writer.agent_runtime import delete_project_sub_agent_definition, validate_project_sub_agent_name

    effective_work_root = Path(work_root or settings.writer_work_root).resolve()
    safe_name = validate_project_sub_agent_name(name)
    return delete_project_sub_agent_definition(effective_work_root, safe_name)


__all__ = [
    "delete_project_subagent_config",
    "upsert_project_subagent_config",
]
