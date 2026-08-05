from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "LamSage"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 6170
    model_id: str = "xopkimik26"
    config_db: str = ""
    core_db: str = ""
    data_dir: str = ""
    work_root: str = ""
    thinking_enabled: bool = True
    thinking_budget: int = 10000
    max_tokens: int = 0
    temperature: float = 0.2
    cors_origins: list[str] = ["http://localhost:6171", "http://127.0.0.1:6171"]

    model_config = {"env_file": ".env", "env_prefix": "LAMSAGE_"}

    def model_post_init(self, __context) -> None:
        sage_root = Path(__file__).resolve().parents[2]
        repo_root = sage_root.parents[1]
        if not self.data_dir:
            self.data_dir = str(sage_root / "data")
        if not self.config_db:
            self.config_db = os.environ.get("LAMTOOLS_LLM_CONFIG_DB", str(repo_root / "data" / "lamtools.db"))
        if not self.core_db:
            self.core_db = str(Path(self.data_dir) / "sage.db")
        if not self.work_root:
            self.work_root = os.environ.get("LAMTOOLS_CORE_WORK_ROOT", str(repo_root))


settings = Settings()
