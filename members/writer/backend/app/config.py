from __future__ import annotations

import os
import platform
from pathlib import Path

from pydantic_settings import BaseSettings


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
        # Data directory
        if not self.data_dir:
            # 优先使用环境变量指定的路径（便携模式）
            env_data_dir = os.environ.get("LAMWRITER_DATA_DIR")
            if env_data_dir:
                self.data_dir = env_data_dir
            else:
                # 原来的逻辑（兼容旧版本）
                if platform.system() == "Windows":
                    base = Path(os.environ.get("APPDATA", Path.home()))
                elif platform.system() == "Darwin":
                    base = Path.home() / "Library" / "Application Support"
                else:
                    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
                self.data_dir = str(base / "LamWriter")
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)

        # Database URL
        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{Path(self.data_dir) / 'lamwriter.db'}"

        # Writer work root: session-specific dir under data, not home
        if not self.writer_work_root:
            self.writer_work_root = str(Path(self.data_dir) / "workspace")


settings = Settings()
