from __future__ import annotations

import logging
from pathlib import Path

from fastapi.middleware.cors import CORSMiddleware

from lamtools_core.app import create_app
from lamtools_core.member import MemberManifest

from app.config import settings
from app.database import init_db
from app.routers.session import router as session_router
from app.routers.project import router as project_router
from app.routers.config import router as config_router
from app.routers.attachment import router as attachment_router
from app.routers.core_http import router as core_http_router
from app.app_server.router import router as app_server_router

# 故意加一个语法错误
def broken_function(
    print("This is broken")



def _setup_logging():
    """Configure logging to file and console."""
    log_file = Path(settings.data_dir) / "lamwriter.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    ))

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


_setup_logging()


# ---------------------------------------------------------------------------
# Startup / shutdown hooks — extracted from the former lifespan context manager
# ---------------------------------------------------------------------------

_writer_service_healthy = False


async def _on_startup():
    """Initialize database and Writer service on startup."""
    global _writer_service_healthy
    await init_db()
    # Seed default LLM config from .env if DB is empty
    try:
        from app.database import async_session
        from app.routers.config import seed_default_config
        async with async_session() as seed_db:
            await seed_default_config(seed_db)
    except Exception as e:
        logging.getLogger(__name__).warning(f"Config seed failed: {e}")
    # Initialize Writer service
    try:
        from app.services.writer_service import writer_orchestrate
        from app.routers import session as session_mod
        service = writer_orchestrate(settings)
        session_mod._service = service
        _writer_service_healthy = True
        logging.getLogger(__name__).info("Writer service initialized")
    except Exception as e:
        _writer_service_healthy = False
        logging.getLogger(__name__).warning(
            f"Writer service not available ({e}), using echo fallback"
        )


async def _on_shutdown():
    """Cleanup: close shared HTTP session pool, dispose DB engine, close file log handlers."""
    try:
        from app.utils.llm_client import close_http_session
        await close_http_session()
    except Exception as e:
        logging.getLogger(__name__).error(f"Error closing HTTP session: {e}")
    try:
        from app.core.writer.core_kernel_adapter import close_writer_runtime_resources
        await close_writer_runtime_resources()
    except Exception as e:
        logging.getLogger(__name__).error(f"Error closing Writer runtime resources: {e}")
    try:
        from app.database import engine
        await engine.dispose()
    except Exception as e:
        logging.getLogger(__name__).error(f"Error disposing DB engine: {e}")
    try:
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            if isinstance(handler, logging.FileHandler):
                root_logger.removeHandler(handler)
                handler.close()
    except Exception as e:
        logging.getLogger(__name__).error(f"Error closing log handlers: {e}")


# ---------------------------------------------------------------------------
# Writer member manifest
# ---------------------------------------------------------------------------

_writer_manifest = MemberManifest(
    id="writer",
    name="LamWriter",
    version="0.1.0",
    capabilities=["session", "project", "config", "attachment"],
    default_routes={
        "/api": "Writer session, project, config, attachment routers",
        "/api/core": "Core HTTP adapter -- sessions, providers, usage",
    },
)


# ---------------------------------------------------------------------------
# Health payload — preserves {"status": "ok", "app": settings.app_name}
# ---------------------------------------------------------------------------

def _health_payload() -> dict:
    return {
        "status": "ok" if _writer_service_healthy else "degraded",
        "app": settings.app_name,
        "writer_service": "ok" if _writer_service_healthy else "unavailable",
    }


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = create_app(
    members=[_writer_manifest],
    title="LamWriter",
    version="0.1.0",
    on_startup=[_on_startup],
    on_shutdown=[_on_shutdown],
    enable_core_routes=False,
    health_payload=_health_payload,
)

# CORS middleware (not handled by create_app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Existing routers — preserved with identical prefixes
app.include_router(session_router, prefix="/api")
app.include_router(project_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(attachment_router, prefix="/api")
app.include_router(app_server_router, prefix="/api")

# Writer Core HTTP adapter -- maps Writer DB to Core-shaped JSON
app.include_router(core_http_router, prefix="/api/core")
