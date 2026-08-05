"""Minimal backend entry point for LamCore packaged app.

This module is the PyInstaller entry point.  It only starts the FastAPI
server -- no Edge launcher, no port management, no idle detection.
The Tauri shell handles all of that.

Environment variables (set by the Tauri shell):
    LAMCORE_PORT              – port to listen on (default 5172)
    LAMTOOLS_HOME             – portable user-home (app dir's .lam/) — keeps
                                every data file beside the app (green mode)
    LAMTOOLS_LLM_CONFIG_DB    – path to config.db
    LAMTOOLS_CORE_DB          – path to core.db
    LAMTOOLS_CORE_DATA_DIR    – user data directory (exact override)
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
# Config DB schema bootstrap
# ---------------------------------------------------------------------------

def _ensure_config_db(config_db: Path) -> None:
    """Create the shared config DB schema (no built-in default rows).

    A blank ``default`` provider/model was never a real API — it only masked
    the unconfigured state and crashed startup when missing. Now nothing is
    seeded: the desktop app boots unconfigured (http_agent_app falls back to a
    placeholder) and the UI creates real providers/models.
    """
    from lamtools_core.config.shared_database import SharedConfigBase
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{config_db}")
    SharedConfigBase.metadata.create_all(engine)
    engine.dispose()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        _run()
    except BaseException:
        # A fatal startup/request error must land in the log file (not only in
        # the PyInstaller fatal-error dialog) so it can be diagnosed remotely.
        try:
            logging.getLogger().exception("Fatal error in LamCore backend")
        except BaseException:
            pass
        raise


def _run() -> None:
    import sys

    # PyInstaller windows mode: sys.stdout/stderr may be None — redirect to devnull
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    port = int(os.environ.get("LAMCORE_PORT", "5172"))
    host = os.environ.get("LAMCORE_HOST", "127.0.0.1")

    # --- data directory & DB seeding ----------------------------------------
    # Green/portable mode: LAMTOOLS_HOME (set by the Tauri shell to the app
    # directory's .lam/) keeps config.db/core.db/workspace/logs beside the app,
    # so nothing is written outside the install root. LAMTOOLS_CORE_DATA_DIR is
    # an exact override; otherwise fall back to %APPDATA%\LamCore.
    data_dir_env = os.environ.get("LAMTOOLS_CORE_DATA_DIR")
    lam_home_env = os.environ.get("LAMTOOLS_HOME")
    if data_dir_env:
        data_dir = Path(data_dir_env)
    elif lam_home_env:
        data_dir = Path(lam_home_env)
    else:
        data_dir = Path(os.environ.get("APPDATA", "") or Path.home()) / "LamCore"
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