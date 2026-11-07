"""Minimal backend entry point for the Sunday packaged app.

This module is the PyInstaller entry point.  It only starts the FastAPI
server -- no Edge launcher, no port management, no idle detection.
The Tauri shell handles all of that.

Environment variables (set by the Tauri shell):
    SUNDAY_CORE_PORT          – port to listen on (default 5172);
                                LAMCORE_PORT is still read for old shells
    SUNDAY_CORE_HOST          – bind host (default 127.0.0.1);
                                LAMCORE_HOST is still read for old shells
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
_log = logging.getLogger("sunday.backend")


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
        # LamTools is the shared family namespace (plugin/hook roots use it
        # too), so it is deliberately not renamed.
        return root / "LamTools"
    appdata = current_environ.get("APPDATA", "").strip()
    return (Path(appdata) if appdata else current_home) / "Sunday"


def _legacy_data_dir(
    *,
    platform: str | None = None,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path | None:
    """Return the pre-migration data directory, if it can exist.

    The old app used ``APPDATA/LamCore`` on Windows and ``~/LamCore`` on macOS,
    so the name deliberately does not say "Windows".
    """
    current_platform = platform or sys.platform
    if current_platform.startswith("linux"):
        return None
    current_environ = os.environ if environ is None else environ
    current_home = Path.home() if home is None else home
    appdata = current_environ.get("APPDATA", "").strip()
    return (Path(appdata) if appdata else current_home) / "LamCore"


def _migrate_legacy_data_dir(
    target: Path,
    *,
    platform: str | None = None,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> bool:
    """Move the old Windows data directory into place exactly once.

    user:“迁移”+(旧版独立后端把状态写在 LamCore 目录，升级后要原样搬走。)
    A destination that already holds state always wins. An empty destination is
    treated as an unfinished attempt (startup may have created it after a failed
    move) and is replaced on the next run.
    """
    legacy = _legacy_data_dir(platform=platform, environ=environ, home=home)
    if legacy is None or not legacy.is_dir():
        return False
    if target.exists():
        try:
            if any(target.iterdir()):
                # 静默放弃会让用户以为旧会话还在，却看到一片空白：必须留下日志。
                _log.info(
                    "legacy data directory %s left in place: %s already holds data",
                    legacy,
                    target,
                )
                return False
            target.rmdir()
        except OSError as error:
            _log.warning("legacy data migration skipped (%s): %s", target, error)
            return False
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        legacy.rename(target)
    except OSError as error:
        # A stale process holding a file must not stop startup; the next run
        # will retry.
        _log.warning("legacy data migration deferred (%s -> %s): %s", legacy, target, error)
        return False
    _log.info("migrated legacy data directory %s -> %s", legacy, target)
    return True


def _env_setting(name: str, legacy_name: str, default: str) -> str:
    """Read the current variable, then its pre-migration spelling."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    return os.environ.get(legacy_name, "").strip() or default


# ---------------------------------------------------------------------------
# Maintenance entry
# ---------------------------------------------------------------------------

def _arg_value(argv: list[str], name: str, default: str = "") -> str:
    for index, value in enumerate(argv):
        if value == name and index + 1 < len(argv):
            return argv[index + 1]
        if value.startswith(name + "="):
            return value.split("=", 1)[1]
    return default


def _maintenance_core_db(argv: list[str]) -> Path:
    """Resolve the database without touching the desktop's normal startup path."""
    explicit = _arg_value(argv, "--core-db") or os.environ.get("LAMTOOLS_CORE_DB", "").strip()
    if explicit:
        return Path(explicit)
    data_dir = (
        os.environ.get("LAMTOOLS_CORE_DATA_DIR", "").strip()
        or os.environ.get("LAMTOOLS_HOME", "").strip()
    )
    return (Path(data_dir) if data_dir else _default_data_dir()) / "core.db"


def _run_compact_sync_journal(argv: list[str]) -> int | None:
    """One-shot sync-journal compaction for the update process.

    user:“在这一次的更新中，自动把之前的数据库进行一遍去重和缩小”+(安装完成后、
    应用启动前，由更新脚本调用本入口；桌面必须已经退出，压缩结果写成 JSON 报告。)
    """
    if "--compact-sync-journal" not in argv:
        return None
    import json

    from lamtools_core.sync_journal_maintenance import (
        SyncCompactionError,
        compact_sync_journal,
        write_report,
    )

    db_path = _maintenance_core_db(argv)
    report_path = _arg_value(argv, "--report") or str(
        db_path.parent / "db-compaction-report.json"
    )
    try:
        report = compact_sync_journal(
            db_path,
            apply=True,
            keep_per_entity=int(_arg_value(argv, "--keep-runtime-per-entity", "1") or 1),
            vacuum="--no-vacuum" not in argv,
            backup="--no-backup" not in argv,
            backup_dir=_arg_value(argv, "--backup-dir") or None,
        )
        write_report(report, report_path)
        return 0 if report.ok else 1
    except SyncCompactionError as error:
        _log.error("sync journal compaction refused: %s", error)
        try:
            Path(report_path).write_text(
                json.dumps({"status": "refused", "error": str(error)}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
        return 2
    except BaseException as error:  # noqa: BLE001 - the report is the only channel here
        _log.exception("sync journal compaction failed")
        try:
            Path(report_path).write_text(
                json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
        return 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    maintenance_exit = _run_compact_sync_journal(sys.argv[1:])
    if maintenance_exit is not None:
        raise SystemExit(maintenance_exit)
    try:
        _run()
    except BaseException:
        # A fatal startup/request error must land in the log file (not only in
        # the PyInstaller fatal-error dialog) so it can be diagnosed remotely.
        try:
            logging.getLogger().exception("Fatal error in Sunday backend")
        except BaseException:
            pass
        raise


def _run() -> None:
    # PyInstaller windows mode: sys.stdout/stderr may be None — redirect to devnull
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    # --- data directory ----------------------------------------------
    # 这段只用标准库，必须在第一个 lamtools_core 导入之前算好：
    # 启动覆盖的根清单与账本路径都以它为单一来源（收尾方案步骤 4）。
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
        _migrate_legacy_data_dir(data_dir)
        # If the move was blocked (an old process holds the tree) and the new
        # directory does not exist yet, keep using the legacy tree for this run
        # instead of starting with empty settings.
        legacy_data_dir = _legacy_data_dir()
        if (
            legacy_data_dir is not None
            and legacy_data_dir.is_dir()
            and not data_dir.exists()
        ):
            data_dir = legacy_data_dir

    # Module overrides must be installed before the first lamtools_core import.
    # lamtools_boot is standard-library only for exactly this reason.
    from lamtools_boot.overrides import apply_boot_overrides, default_plugin_roots

    # user:“boot 与运行时同一份根与账本”+显式传参，不做第二套默认推导。
    apply_boot_overrides(
        roots=default_plugin_roots(dict(os.environ)),
        state_path=data_dir / "plugin-system.jsonc",
    )
    data_dir.mkdir(parents=True, exist_ok=True)

    port = int(_env_setting("SUNDAY_CORE_PORT", "LAMCORE_PORT", "5172"))
    host = _env_setting("SUNDAY_CORE_HOST", "LAMCORE_HOST", "127.0.0.1")
    from lamtools_core.app.api_access import CoreApiAccessPolicy

    # The packaged sidecar is internal; LAN access belongs to a separate
    # explicitly configured CLI listener or the authenticated Rust gateway.
    access_policy = CoreApiAccessPolicy()
    host = access_policy.validate_bind_host(host)

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
    # Console and file share one millisecond-stamped format so step timings can
    # be subtracted across lines (see lamtools_core.logging_setup).
    from lamtools_core.logging_setup import attach_backend_file_logger, backend_log_formatter

    _formatter = backend_log_formatter()
    for _handler in logging.getLogger().handlers:
        _handler.setFormatter(_formatter)
    log_file = attach_backend_file_logger(data_dir)
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

    # The factory owns the SPA fallback when a frontend directory is supplied:
    # it also registers the directory for the import map and injects the map
    # merged with plugin overrides. Adding a bare fallback here would shadow
    # that injected page.
    # user:“前端模块替换”+(打包后端返回页面时同样按启用插件注入 import map)
    app = create_default_core_agent_http_app(
        access_policy=access_policy,
        frontend_dir=frontend_dir or None,
    )

    _log.info("Starting Sunday backend on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info", proxy_headers=False)


if __name__ == "__main__":
    main()
