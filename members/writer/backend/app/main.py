from pathlib import Path
from app.config import settings
from app.http_app import create_writer_http_app

_data = Path(settings.data_dir)
_config_db = _data / "lamtools.db"
_core_db = _data / "writer_core.db"


def _ensure_config_db():
    """Create shared config DB tables if they don't exist."""
    from lamtools_core.config.shared_database import SharedConfigBase
    from sqlalchemy import create_engine
    engine = create_engine(f"sqlite:///{_config_db}")
    SharedConfigBase.metadata.create_all(engine)
    engine.dispose()


def _seed_writer_config():
    """Ensure at least one provider/model is configured."""
    import sqlite3
    try:
        db = sqlite3.connect(str(_config_db))
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
        pass


_ensure_config_db()
_seed_writer_config()

app = create_writer_http_app(
    model_id=settings.llm_model,
    config_db=str(_config_db),
    core_db=str(_core_db),
    data_dir=settings.data_dir,
    work_root=settings.writer_work_root or None,
    cors_origins=settings.cors_origins,
    thinking_enabled=settings.llm_thinking_enabled,
    thinking_budget=settings.llm_thinking_budget,
    max_tokens=settings.llm_max_tokens or None,
    temperature=settings.llm_temperature,
)