"""LamTools Core application factory — assembles members into a FastAPI app."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..member import MemberManifest, MemberRegistry
from .security import allowed_origins, is_allowed_origin


@asynccontextmanager
async def _lifespan(
    app: FastAPI,
    startup_hooks: list[Callable],
    shutdown_hooks: list[Callable],
) -> AsyncIterator[None]:
    # --- Startup ---
    for hook in startup_hooks:
        result = hook()
        if asyncio.iscoroutine(result):
            await result
    yield
    # --- Shutdown ---
    for hook in shutdown_hooks:
        result = hook()
        if asyncio.iscoroutine(result):
            await result


def create_app(
    *,
    members: list[MemberManifest] | None = None,
    member_routers: dict[str, APIRouter] | None = None,
    title: str = "LamTools Core",
    version: str = "0.1.0",
    on_startup: list[Callable] | None = None,
    on_shutdown: list[Callable] | None = None,
    enable_core_routes: bool = False,
    health_payload: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
    frontend_dir: Path | str | None = None,
) -> FastAPI:
    """Create and configure the LamTools Core FastAPI application.

    Args:
        members: List of member manifests to register.
        member_routers: Mapping of member id -> APIRouter to mount.
        title: Application title.
        version: Application version.
        on_startup: Additional startup hooks.
        on_shutdown: Additional shutdown hooks.
        enable_core_routes: When True, mount the core HTTP router at
            ``/api/core`` with session, event, provider, and usage routes.
        health_payload: Custom payload for /api/health endpoint. Can be a
            dict (returned directly) or a callable (called per request).
            If not provided, returns {"status": "ok"}.
        frontend_dir: When provided, mount the directory as the SPA frontend
            root.  ``/assets/`` is served via ``StaticFiles`` and every other
            unmatched path falls back to ``index.html`` so that client-side
            routing (Vue Router history mode) works correctly.  API routes
            always take precedence over the catch-all.

    Returns:
        Configured FastAPI application instance.
    """
    registry = MemberRegistry()

    # Register all members
    for manifest in members or []:
        registry.register(manifest)

    # Collect hooks
    startup_hooks = list(on_startup or [])
    for manifest in registry:
        if "startup" in manifest.hooks:
            startup_hooks.append(manifest.hooks["startup"])

    shutdown_hooks = list(on_shutdown or [])
    for manifest in registry:
        if "shutdown" in manifest.hooks:
            shutdown_hooks.append(manifest.hooks["shutdown"])

    app = FastAPI(
        title=title,
        version=version,
        lifespan=lambda app: _lifespan(app, startup_hooks, shutdown_hooks),
    )

    # Explicit origin allow-list: the backend is bound to loopback, so any
    # browser page carrying an Origin header must be one of our own (dev vite
    # servers or the Tauri WebView).  Requests without an Origin (CLI / Python
    # clients) are trusted as local callers.  A wildcard + credentials combo
    # would let any web page read responses and drive the local agent.
    origins = allowed_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _check_request_origin(request: Request, call_next: Callable) -> Any:
        # Origin is only present on browser-style (cross-site) requests;
        # non-browser clients omit it and stay trusted.
        origin = request.headers.get("origin")
        if origin is not None and not is_allowed_origin(origin):
            return JSONResponse(status_code=403, content={"detail": "origin not allowed"})
        response = await call_next(request)
        # Security headers (audit 03 S3): the SPA is served inline and file
        # responses use guessable content-types — nosniff + frame/referrer
        # policies shrink the sniffing / clickjacking surface.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response

    # --- Core routes ---
    if health_payload is not None:
        _hp = health_payload

        @app.get("/api/health")
        async def health() -> dict[str, Any]:
            return _hp() if callable(_hp) else _hp
    else:

        @app.get("/api/health")
        async def health() -> dict[str, str]:
            return {"status": "ok"}

    @app.get("/api/members")
    async def list_members() -> list[dict[str, Any]]:
        return [m.to_dict() for m in registry]

    # --- Mount member routers ---
    routers = member_routers or {}
    for member_id, router in routers.items():
        prefix = f"/api/{member_id}"
        app.include_router(router, prefix=prefix)

    # --- Mount core routes (optional) ---
    if enable_core_routes:
        from ..http import create_core_router

        core_router = create_core_router()
        app.include_router(core_router, prefix="/api/core")

    # Store registry on app state for external access
    app.state.member_registry = registry

    # --- Serve frontend SPA (desktop / packaged mode) ---
    # Only mount static assets here.  The SPA fallback catch-all must be
    # registered *after* every API route, so the caller is responsible for
    # calling ``add_spa_fallback(app, frontend_dir)`` at the very end.
    if frontend_dir is not None:
        _mount_frontend_assets(app, Path(frontend_dir))

    app.state._frontend_dir = str(Path(frontend_dir)) if frontend_dir else None

    return app


def add_spa_fallback(app: FastAPI, frontend_dir: Path | str) -> None:
    """Register the SPA catch-all route — call *after* all API routes.

    Every unmatched GET request returns ``index.html`` (or ``index-core.html``)
    so that Vue Router (history mode) can handle client-side navigation.
    """
    resolved = Path(frontend_dir).resolve()
    index_path = resolved / "index.html"
    if not index_path.is_file():
        index_path = resolved / "index-core.html"
    if not index_path.is_file():
        raise FileNotFoundError(
            f"Neither index.html nor index-core.html found in {resolved}"
        )
    _index_html = index_path.read_text(encoding="utf-8")

    @app.get("/{filename:path}", include_in_schema=False, response_model=None)
    async def _spa_fallback(filename: str) -> HTMLResponse | FileResponse:
        # Try to serve as a static file first (non-/assets files like favicon).
        # ``filename`` is client-controlled, so containment-check it against the
        # frontend root — a raw ``resolved / filename`` join allows ``..`` /
        # ``%2e%2e`` segments to escape and read arbitrary local files.
        candidate = (resolved / filename).resolve()
        if candidate == resolved or candidate.is_relative_to(resolved):
            if candidate.is_file():
                return FileResponse(str(candidate))
        return HTMLResponse(content=_index_html)


def _mount_frontend_assets(app: FastAPI, frontend_path: Path) -> None:
    """Mount frontend static assets (JS, CSS, images) and the root route."""
    resolved = frontend_path.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"Frontend directory not found: {resolved}")

    index_path = resolved / "index.html"
    if not index_path.is_file():
        index_path = resolved / "index-core.html"
    if not index_path.is_file():
        raise FileNotFoundError(f"No index page found in frontend directory: {resolved}")

    _index_html = index_path.read_text(encoding="utf-8")

    # -- Static assets (JS / CSS / images / fonts) -----------------
    assets_dir = resolved / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend_assets")

    # -- Root ------------------------------------------------------
    @app.get("/", include_in_schema=False)
    async def _serve_root() -> HTMLResponse:
        return HTMLResponse(content=_index_html)


__all__ = ["add_spa_fallback", "create_app"]
