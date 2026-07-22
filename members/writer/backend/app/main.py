from pathlib import Path
from app.config import settings
from app.http_app import create_writer_http_app

_data = Path(settings.data_dir)
_config_db = str(_data / "lamtools.db")
_core_db = str(_data / "writer_core.db")


def _ensure_writer_config():
    """Ensure the shared config DB has at least one provider/model configured."""
    import sqlite3
    try:
        db = sqlite3.connect(_config_db)
        db.execute(
            "INSERT OR IGNORE INTO llm_providers (id, name, api_type, base_url, api_key, is_default) "
            "VALUES ('writer-default', 'Writer Default', ?, ?, ?, 1)",
            (settings.llm_api_type, settings.llm_base_url, settings.llm_api_key),
        )
        db.execute(
            "INSERT OR IGNORE INTO llm_models (id, provider_id, model_id, display_name, context_window, "
            "max_output_tokens, thinking_supported, thinking_budget, temperature, is_default) "
            "VALUES (?, 'writer-default', ?, ?, ?, ?, ?, ?, ?, 1)",
            (
                f"model-{settings.llm_model}",
                settings.llm_model,
                settings.llm_model,
                settings.llm_context_window,
                settings.llm_max_tokens,
                1,
                settings.llm_thinking_budget,
                settings.llm_temperature,
            ),
        )
        db.commit()
        db.close()
    except Exception:
        pass  # DB may not exist yet; create_core_agent_http_app will handle table creation


_ensure_writer_config()
app = create_writer_http_app(
    model_id=settings.llm_model,
    config_db=_config_db,
    core_db=_core_db,
    data_dir=settings.data_dir,
    work_root=settings.writer_work_root or None,
    cors_origins=settings.cors_origins,
    thinking_enabled=settings.llm_thinking_enabled,
    thinking_budget=settings.llm_thinking_budget,
    max_tokens=settings.llm_max_tokens or None,
    temperature=settings.llm_temperature,
)