"""Minimal backend entry point for LamCore packaged app.

This module is the PyInstaller entry point.  It only starts the FastAPI
server -- no Edge launcher, no port management, no idle detection.
The Tauri shell handles all of that.

Environment variables (set by the Tauri shell):
    LAMCORE_PORT              – port to listen on (default 5172)
    LAMTOOLS_HOME             – portable user-home (app dir's .lam/) — keeps
                                every data file beside the app (green mode)
    LAMTOOLS_CORE_DB          – path to core.db
    LAMTOOLS_CORE_DATA_DIR    – user data directory (exact override)
    LAMTOOLS_FRONTEND_DIR     – optional: serve built SPA from here

Models/providers/settings are jsonc-only (no config DB, no LAMTOOLS_LLM_CONFIG_DB).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s [%(name)s] %(message)s",
)
_log = logging.getLogger("lamcore.backend")


def _default_data_dir(
    *,
    platform: str | None = None,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the native per-user data directory when no shell override exists."""
    current_platform = platform or sys.platform
    current_environ = os.environ if environ is None else environ
    current_home = Path.home() if home is None else home
    if current_platform.startswith("linux"):
        xdg_data_home = current_environ.get("XDG_DATA_HOME", "").strip()
        root = Path(xdg_data_home) if xdg_data_home else current_home / ".local" / "share"
        return root / "LamTools"
    appdata = current_environ.get("APPDATA", "").strip()
    return (Path(appdata) if appdata else current_home) / "LamCore"


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
    # PyInstaller windows mode: sys.stdout/stderr may be None — redirect to devnull
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    port = int(os.environ.get("LAMCORE_PORT", "5172"))
    host = os.environ.get("LAMCORE_HOST", "127.0.0.1")

    # --- data directory ------------------------------------------------
    # Windows green/portable mode sets LAMTOOLS_HOME to the app-side .lam.
    # Linux desktop builds pass their XDG-backed Tauri app-data directory.
    # LAMTOOLS_CORE_DATA_DIR remains the exact override for both platforms.
    data_dir_env = os.environ.get("LAMTOOLS_CORE_DATA_DIR")
    lam_home_env = os.environ.get("LAMTOOLS_HOME")
    if data_dir_env:
        data_dir = Path(data_dir_env)
    elif lam_home_env:
        data_dir = Path(lam_home_env)
    else:
        data_dir = _default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    core_db = Path(
        os.environ.get("LAMTOOLS_CORE_DB")
        or (data_dir / "core.db")
    )

    # --- unified config directory defaults -------------------------------
    # Seed .lam/core/config/ with built-in default files (loadtools.jsonc,
    # access_tools.jsonc, hooks.json, AGENTS.md, load_context.jsonc,
    # memory.md, subagent/) on first run. Idempotent — existing user edits
    # are never overwritten.
    from lamtools_core.config.defaults import ensure_default_config_files

    ensure_default_config_files()

    os.environ.setdefault("LAMTOOLS_CORE_DB", str(core_db))
    os.environ.setdefault("LAMTOOLS_CORE_DATA_DIR", str(data_dir))

    _log.info("core_db=%s  data_dir=%s", core_db, data_dir)

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
