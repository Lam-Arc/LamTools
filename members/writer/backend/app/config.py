from __future__ import annotations

import os
import platform
import sqlite3
from pathlib import Path

from pydantic_settings import BaseSettings


SHARED_CONFIG_TABLES = ("llm_models", "llm_providers")
SHARED_SETTING_NAMESPACES = {"lamwriter.modelRouting"}
SHARED_SETTING_PREFIXES = ("core.", "lamtools.")


def _default_project_data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def _legacy_appdata_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "LamWriter"


def _migrate_legacy_database(target_dir: Path, legacy_dir: Path | None = None) -> bool:
    legacy_dir = legacy_dir or _legacy_appdata_dir()
    source = legacy_dir / "lamwriter.db"
    target = target_dir / "lamwriter.db"
    if target.exists() or not source.exists():
        return False
    target_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_conn, sqlite3.connect(target) as target_conn:
        source_conn.backup(target_conn)
    _strip_shared_config_from_writer_db(target)
    return True


def _strip_shared_config_from_writer_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        for table in SHARED_CONFIG_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        if _sqlite_table_exists(conn, "app_settings"):
            for namespace in SHARED_SETTING_NAMESPACES:
                conn.execute("DELETE FROM app_settings WHERE namespace = ?", (namespace,))
            for prefix in SHARED_SETTING_PREFIXES:
                conn.execute("DELETE FROM app_settings WHERE namespace LIKE ?", (f"{prefix}%",))
        conn.commit()


def _sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


class Settings(BaseSettings):
    # --- App ---
    app_name: str = "LamWriter"
    debug: bool = False

    # --- Server ---
    host: str = "127.0.0.1"
    port: int = 6173

    # --- Database ---
    database_url: str = ""  # Computed in model_post_init

    # --- Data directory ---
    data_dir: str = ""  # Computed in model_post_init

    # --- LLM ---
    llm_base_url: str = "https://maas-coding-api.cn-huabei-1.xf-yun.com/v2"
    llm_api_key: str = ""
    llm_model: str = "astron-code-latest"
    llm_max_tokens: int = 16384
    llm_thinking_enabled: bool = True
    llm_thinking_budget: int = 10000
    llm_context_window: int = 200000
    llm_temperature: float = 0.7
    llm_api_type: str = "openai"  # "openai" or "anthropic"

    # --- Writer ---
    writer_work_root: str = ""  # Default: user home
    writer_auto_approve_read: bool = True
    writer_auto_approve_glob: bool = True
    writer_auto_approve_grep: bool = True

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:6174", "http://127.0.0.1:6174"]

    # --- LamTools 成员服务 ---
    sage_service_url: str = "http://localhost:6175"

    model_config = {"env_file": ".env", "env_prefix": "LAMWRITER_"}

    def model_post_init(self, __context) -> None:
        explicit_database_url = bool(self.database_url)

        # Data directory
        if not self.data_dir:
            self.data_dir = str(_default_project_data_dir())
        data_dir = Path(self.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        if not explicit_database_url:
            _migrate_legacy_database(data_dir)

        # Database URL
        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{data_dir / 'lamwriter.db'}"

        # Writer work root: session-specific dir under data, not home
        if not self.writer_work_root:
            self.writer_work_root = str(data_dir / "workspace")


settings = Settings()
