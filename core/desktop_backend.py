"""Minimal backend entry point for LamCore packaged app.

This module is the PyInstaller entry point.  It only starts the FastAPI
server -- no Edge launcher, no port management, no idle detection.
The Tauri shell handles all of that.

Environment variables (set by the Tauri shell):
    LAMCORE_PORT              – port to listen on (default 5172)
    LAMTOOLS_LLM_CONFIG_DB    – path to config.db
    LAMTOOLS_CORE_DB          – path to core.db
    LAMTOOLS_CORE_DATA_DIR    – user data directory
    LAMTOOLS_CORE_WORK_ROOT   – workspace root
    LAMTOOLS_FRONTEND_DIR     – optional: serve built SPA from here
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s [%(name)s] %(message)s",
)
_log = logging.getLogger("lamcore.backend")


# ---------------------------------------------------------------------------
# Config DB first-run seeding
# ---------------------------------------------------------------------------

def _ensure_config_db(config_db: Path) -> None:
    """Create the shared config DB and seed a default provider/model if empty."""
    from lamtools_core.config.shared_database import SharedConfigBase
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{config_db}")
    SharedConfigBase.metadata.create_all(engine)

    with engine.connect() as conn:
        provider_count = conn.execute(
            text("SELECT COUNT(*) FROM llm_providers")
        ).scalar()
        model_count = conn.execute(
            text("SELECT COUNT(*) FROM llm_models WHERE id='default-model' OR model_id='default-model'")
        ).scalar()
        need_seed = not provider_count or not model_count
        if need_seed:
            if not provider_count:
                conn.execute(
                    text(
                    "INSERT INTO llm_providers "
                    "(id, name, api_type, base_url, api_key, is_default, created_at, updated_at) "
                    "VALUES ('default', 'Default Provider', 'openai', '', '', 1, "
                    "datetime('now'), datetime('now'))"
                )
            )
            conn.execute(
                text(
                    "INSERT OR IGNORE INTO llm_models "
                    "(id, provider_id, model_id, display_name, "
                    "context_window, max_output_tokens, thinking_supported, thinking_budget, "
                    "temperature, is_default, created_at, updated_at) "
                    "VALUES ('default-model', 'default', '', 'Default Model', "
                    "128000, 16384, 1, 10000, 0.7, 1, datetime('now'), datetime('now'))"
                )
            )
            conn.commit()
    engine.dispose()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import sys

    # PyInstaller windows mode: sys.stdout/stderr may be None — redirect to devnull
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    port = int(os.environ.get("LAMCORE_PORT", "5172"))
    host = os.environ.get("LAMCORE_HOST", "127.0.0.1")

    # --- data directory & DB seeding ----------------------------------------
    data_dir = Path(
        os.environ.get("LAMTOOLS_CORE_DATA_DIR")
        or os.environ.get("APPDATA", "")
        or Path.home()
    ).joinpath("LamCore")
    data_dir.mkdir(parents=True, exist_ok=True)

    config_db = Path(
        os.environ.get("LAMTOOLS_LLM_CONFIG_DB")
        or (data_dir / "config.db")
    )
    core_db = Path(
        os.environ.get("LAMTOOLS_CORE_DB")
        or (data_dir / "core.db")
    )
    work_root = Path(
        os.environ.get("LAMTOOLS_CORE_WORK_ROOT")
        or (data_dir / "workspace")
    )
    work_root.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("LAMTOOLS_LLM_CONFIG_DB", str(config_db))
    os.environ.setdefault("LAMTOOLS_CORE_DB", str(core_db))
    os.environ.setdefault("LAMTOOLS_CORE_DATA_DIR", str(data_dir))
    os.environ.setdefault("LAMTOOLS_CORE_WORK_ROOT", str(work_root))

    _log.info("config_db=%s  core_db=%s  data_dir=%s", config_db, core_db, data_dir)
    _log.info("env LAMTOOLS_LLM_CONFIG_DB=%s", os.environ.get("LAMTOOLS_LLM_CONFIG_DB"))

    _ensure_config_db(config_db)

    # --- attach file logger now that data_dir is known ---
    log_file = data_dir / "backend.log"
    file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
    logging.getLogger().addHandler(file_handler)
    _log.info("Log file: %s", log_file)

    # --- frontend (optional) ------------------------------------------------
    frontend_dir = os.environ.get("LAMTOOLS_FRONTEND_DIR")
    if not frontend_dir:
        # PyInstaller: check sys._MEIPASS/frontend
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidate = Path(meipass) / "frontend"
            if candidate.is_dir():
                frontend_dir = str(candidate)

    # --- FastAPI app --------------------------------------------------------
    from lamtools_core.app.http_agent_app import create_default_core_agent_http_app

    app = create_default_core_agent_http_app()
    if frontend_dir:
        from lamtools_core.app.factory import add_spa_fallback
        add_spa_fallback(app, Path(frontend_dir))

    _log.info("Starting LamCore backend on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()