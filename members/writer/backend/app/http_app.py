from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lamtools_core.app.http_agent_app import create_core_agent_http_app
from lamtools_core.app import OperationRequest, OperationResult
from lamtools_core.app.core_session_store import CoreDbSessionStore

from .member.kit import kit
from .member.manifest import manifest
from .member.spec import build_writer_agent_spec


def default_writer_plugin_root() -> Path:
    return Path(__file__).resolve().parents[2] / "plugin"


def _register_overlay(app: FastAPI) -> None:
    try:
        catalog = app.state.operations
    except AttributeError:
        return
    if catalog is None:
        return

    def _db():
        return app.state["core_db"]

    async def session_list(request: OperationRequest) -> OperationResult:
        store = CoreDbSessionStore(_db)
        sessions = await store.list(member_id="writer")
        return OperationResult(name="session.list", payload={
            "sessions": [{
                "id": s.id, "title": s.title, "status": s.status,
                "created_at": s.created_at.isoformat() if hasattr(s, "created_at") else "",
            } for s in sessions]
        })

    async def session_get(request: OperationRequest) -> OperationResult:
        sid = str(request.payload.get("session_id") or request.payload.get("sessionId") or request.payload.get("id") or "")
        store = CoreDbSessionStore(_db)
        s = await store.get(sid)
        if s is None:
            return OperationResult(name="session.get", status="error", payload={"error": "Not found"})
        return OperationResult(name="session.get", payload={"session": {
            "id": s.id, "title": s.title, "status": s.status,
        }})

    async def session_delete(request: OperationRequest) -> OperationResult:
        sid = str(request.payload.get("session_id") or request.payload.get("sessionId") or request.payload.get("id") or "")
        store = CoreDbSessionStore(_db)
        await store.delete(sid)
        return OperationResult(name="session.delete", payload={"deleted": sid})

    for name, handler in [
        ("session.list", session_list),
        ("session.get", session_get),
        ("session.delete", session_delete),
    ]:
        if not catalog.has(name):
            catalog.register(name, handler)


def create_writer_http_app(
    *,
    model_id: str = "",
    config_db: Path | str | None = None,
    core_db: Path | str | None = None,
    data_dir: Path | str | None = None,
    work_root: Path | str | None = None,
    plugin_roots: tuple[Path | str, ...] | None = None,
    cors_origins: list[str] | None = None,
    thinking_enabled: bool = True,
    thinking_budget: int = 10000,
    max_tokens: int | None = None,
    temperature: float = 0.7,
) -> FastAPI:
    app = create_core_agent_http_app(
        agent_spec=build_writer_agent_spec(default_model=model_id),
        member_kit=kit,
        members=[manifest],
        model_id=model_id,
        config_db=config_db,
        core_db=core_db,
        data_dir=data_dir,
        work_root=work_root,
        plugin_roots=plugin_roots if plugin_roots is not None else (default_writer_plugin_root(),),
        thinking_enabled=thinking_enabled,
        thinking_budget=thinking_budget,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    @app.on_event("startup")
    async def _register():
        import asyncio
        for i in range(20):
            try:
                ops = app.state.operations
                if ops is not None:
                    break
            except AttributeError:
                pass
            await asyncio.sleep(0.5)
        _register_overlay(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["http://localhost:6174", "http://127.0.0.1:6174"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


__all__ = ["create_writer_http_app", "default_writer_plugin_root"]