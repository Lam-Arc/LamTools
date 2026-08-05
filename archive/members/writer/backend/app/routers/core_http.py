"""Writer-specific Core HTTP adapter router.

Maps Writer DB models to neutral Core-shaped JSON records under /api/core.
Does NOT use the generic in-memory Core skeleton -- all data comes from
the appropriate SQLite database for each domain.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import execute_writer_write, get_db, get_writer_write
from app.models.session import WriterSession
from app.models.llm_config import LLMProvider, LLMModel
from app.shared_config_database import get_shared_config_db
from app.routers.path_utils import ensure_work_root
from app.core.writer.core_kernel_adapter import schedule_writer_startup_prewarm
from app.services.llm_config_service import resolve_llm_config
from app.services.session_management import create_writer_session
from app.services.session_lifecycle import merge_lifecycle_with_transcript_status, project_session_lifecycle
from app.services.transcript_service import latest_turn_status

router = APIRouter()


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class CoreSessionCreate(BaseModel):
    title: str = "New Session"
    work_root: str = ""
    mode: str = "EXECUTE"
    project_id: str | None = None


class CoreSessionUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    metadata: dict[str, Any] | None = None
    mode: str | None = None
    phase: str | None = None


# ---------------------------------------------------------------------------
# Mapping helpers -- Writer DB row -> Core-shaped dict
# ---------------------------------------------------------------------------

def _session_to_core(s: WriterSession) -> dict[str, Any]:
    """Map a WriterSession row to Core session shape."""
    metadata: dict[str, Any] = dict(s.metadata_ or {})
    lifecycle = project_session_lifecycle(s)
    # Preserve useful Writer fields in metadata/details
    metadata["work_root"] = s.work_root or ""
    metadata.setdefault("branch", s.branch or "")
    metadata.setdefault("phase", s.phase or "idle")
    metadata.setdefault("mode", s.mode or "EXECUTE")
    metadata.setdefault("loop_position", s.loop_position or "execute")
    metadata["lifecycle"] = lifecycle

    return {
        "id": s.id,
        "member_id": "writer",
        "title": s.title,
        "status": lifecycle["state"],
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        "metadata": metadata,
    }


async def _session_to_core_projected(db: AsyncSession, s: WriterSession) -> dict[str, Any]:
    result = _session_to_core(s)
    status = await latest_turn_status(db, s.id)
    lifecycle = merge_lifecycle_with_transcript_status(result.get("metadata", {}).get("lifecycle") or {}, status)
    result["status"] = lifecycle["state"]
    result["metadata"] = {
        **(result.get("metadata") or {}),
        "lifecycle": lifecycle,
    }
    return result


def _safe_api_key_ref(provider_id: str, key: str) -> str:
    """Build a safe reference string for the API key -- never expose raw key or substrings."""
    if not key:
        return ""
    return f"provider:{provider_id}:api_key"


def _provider_to_core(p: LLMProvider, default_model_id: str | None = None) -> dict[str, Any]:
    """Map an LLMProvider row to Core provider shape -- api_key never exposed."""
    return {
        "id": p.id,
        "kind": p.api_type,
        "name": p.name,
        "base_url": p.base_url,
        "api_key_ref": _safe_api_key_ref(p.id, p.api_key),
        "default_model": default_model_id or "",
        "models": [],
        "metadata": dict(p.extra or {}),
        "enabled": True,
    }


# ---------------------------------------------------------------------------
# Session routes
# ---------------------------------------------------------------------------

@router.get("/sessions")
async def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WriterSession)
        .order_by(WriterSession.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return [await _session_to_core_projected(db, s) for s in result.scalars().all()]


@router.post("/sessions", status_code=201)
async def create_session(
    body: CoreSessionCreate,
    db: AsyncSession = Depends(get_db),
    write_transaction: Any = Depends(get_writer_write),
):
    if body.project_id is not None:
        raise HTTPException(status_code=422, detail="Use the project session endpoint for project-owned sessions")

    async def write(write_db):
        created = await create_writer_session(
            write_db,
            title=body.title,
            work_root=ensure_work_root(body.work_root),
            mode=body.mode,
        )
        session = await write_db.get(WriterSession, created["id"])
        assert session is not None
        return await _session_to_core_projected(write_db, session)
    result = await execute_writer_write(db, write, write_transaction)
    schedule_writer_startup_prewarm(result.get("work_root") or "")
    return result


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(WriterSession).where(WriterSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    schedule_writer_startup_prewarm(session.work_root)
    return await _session_to_core_projected(db, session)


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: str,
    body: CoreSessionUpdate,
    db: AsyncSession = Depends(get_db),
    write_transaction: Any = Depends(get_writer_write),
):
    async def write(write_db):
        session = await write_db.get(WriterSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if body.title is not None:
            session.title = body.title
        if body.status is not None:
            session.status = body.status
        if body.mode is not None:
            session.mode = body.mode
        if body.phase is not None:
            session.phase = body.phase
        if body.metadata is not None:
            metadata = dict(body.metadata)
            if session.project_id:
                metadata.pop("work_root", None)
            elif "work_root" in metadata:
                raise HTTPException(status_code=422, detail="Use the project session endpoint for project-owned sessions")
            session.metadata_ = {**dict(session.metadata_ or {}), **metadata}
        await write_db.flush()
        return await _session_to_core_projected(write_db, session)
    return await execute_writer_write(db, write, write_transaction)


# ---------------------------------------------------------------------------
# Provider routes
# ---------------------------------------------------------------------------

@router.get("/providers")
async def list_providers(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    config_db: AsyncSession = Depends(get_shared_config_db),
):
    result = await config_db.execute(
        select(LLMProvider)
        .order_by(LLMProvider.name.asc())
        .offset(offset)
        .limit(limit)
    )
    providers = result.scalars().all()
    writer_config = await resolve_llm_config(config_db, "writer")

    out = []
    for p in providers:
        default_model_id = (
            writer_config.model.model_id
            if writer_config is not None and writer_config.provider.id == p.id
            else None
        )

        # Collect all model IDs for this provider
        models_result = await config_db.execute(
            select(LLMModel.model_id)
            .where(LLMModel.provider_id == p.id)
        )
        model_ids = [row[0] for row in models_result.all()]

        core_dict = _provider_to_core(p, default_model_id)
        core_dict["models"] = model_ids
        out.append(core_dict)

    return out


@router.get("/providers/default")
async def get_default_provider(
    kind: str | None = Query(None),
    config_db: AsyncSession = Depends(get_shared_config_db),
):
    """Return the Writer primary provider, optionally filtered by kind (api_type)."""
    writer_config = await resolve_llm_config(config_db, "writer")
    provider = writer_config.provider if writer_config is not None else None
    default_model_id = writer_config.model.model_id if writer_config is not None else None
    if provider is not None and kind is not None and provider.api_type != kind:
        provider = None
        default_model_id = None

    if provider is None:
        stmt2 = select(LLMProvider).order_by(LLMProvider.name.asc()).limit(1)
        if kind is not None:
            stmt2 = stmt2.where(LLMProvider.api_type == kind)
        result2 = await config_db.execute(stmt2)
        provider = result2.scalar_one_or_none()

    if provider is None:
        raise HTTPException(status_code=404, detail="No provider found")

    if default_model_id is None:
        model_result = await config_db.execute(
            select(LLMModel)
            .where(LLMModel.provider_id == provider.id)
            .order_by(LLMModel.display_name.asc(), LLMModel.model_id.asc())
            .limit(1)
        )
        model = model_result.scalar_one_or_none()
        default_model_id = model.model_id if model else None

    # Collect all model IDs
    models_result = await config_db.execute(
        select(LLMModel.model_id)
        .where(LLMModel.provider_id == provider.id)
    )
    model_ids = [row[0] for row in models_result.all()]

    core_dict = _provider_to_core(provider, default_model_id)
    core_dict["models"] = model_ids
    return core_dict


# ---------------------------------------------------------------------------
# Usage routes -- stable Core-compatible fallback.
# ---------------------------------------------------------------------------

@router.get("/usage")
async def list_usage(
    session_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return []


@router.get("/usage/total")
async def get_usage_total(
    member_id: str | None = Query(None),
    currency: str = Query("USD"),
    session_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return {
        "total_cost": 0.0,
        "currency": currency,
        "member_id": member_id or "",
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
