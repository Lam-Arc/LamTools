from app.config import settings
from app.http_app import create_sage_http_app


app = create_sage_http_app(
    model_id=settings.model_id,
    config_db=settings.config_db or None,
    core_db=settings.core_db or None,
    data_dir=settings.data_dir or None,
    work_root=settings.work_root or None,
    cors_origins=settings.cors_origins,
    thinking_enabled=settings.thinking_enabled,
    thinking_budget=settings.thinking_budget,
    max_tokens=settings.max_tokens or None,
    temperature=settings.temperature,
)
