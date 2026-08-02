"""One-way migration of model definitions from the shared config DB to jsonc.

When the file-backed :class:`~lamtools_core.config.model_store.ModelStore` is
empty (no project/global/built-in model files) but the legacy SQLite
``llm_models`` table still holds rows, this module exports those rows to
per-model jsonc files under ``~/.lam/config/models/`` so the new file-based
loader becomes the source of truth.

Provider connection info (base_url, api_key, api_type) is **not** migrated —
it stays in the DB and is looked up at request time. Each exported model
references its provider by name.

The DB ``llm_models`` table is **not** dropped after export; it is simply no
longer read once jsonc files exist (graceful, reversible).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from lamtools_core.config.model_store import ModelConfig, ModelStore

_logger = logging.getLogger(__name__)


def _connect(config_db: Path) -> sqlite3.Connection:
    raw_path = str(config_db.resolve()).replace("\\", "/")
    from urllib.parse import quote

    uri = f"file:{quote(raw_path, safe=':/')}?mode=ro"
    con = sqlite3.connect(uri, timeout=5.0, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _read_db_models(config_db: Path) -> list[dict[str, Any]]:
    """Read all model rows joined with their provider name. Returns [] if missing."""
    if not config_db.exists():
        return []
    con = _connect(config_db)
    try:
        rows = con.execute(
            """
            select m.model_id, m.display_name, m.context_window, m.max_output_tokens,
                   m.thinking_supported, m.thinking_budget, m.temperature, m.extra,
                   m.is_default, p.name as provider_name
            from llm_models m join llm_providers p on p.id=m.provider_id
            order by m.created_at asc
            """
        ).fetchall()
    except sqlite3.OperationalError:
        # Table missing or DB unreadable — nothing to migrate.
        return []
    finally:
        con.close()
    result: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["model_id"] = str(data.get("model_id") or "").strip()
        if data["model_id"]:
            result.append(data)
    return result


def _db_row_to_model_config(row: dict[str, Any]) -> ModelConfig:
    """Translate a DB model row into a ModelConfig (capability left blank)."""
    import json

    extra_raw = row.get("extra")
    extra: dict[str, Any] = {}
    if isinstance(extra_raw, str) and extra_raw.strip():
        try:
            parsed = json.loads(extra_raw)
            if isinstance(parsed, dict):
                extra = parsed
        except (json.JSONDecodeError, TypeError):
            extra = {}
    adapter_profile_id = ""
    if isinstance(extra.get("adapter_profile_id"), str):
        adapter_profile_id = str(extra["adapter_profile_id"])
    return ModelConfig(
        model_id=str(row.get("model_id") or ""),
        display_name=str(row.get("display_name") or ""),
        provider=str(row.get("provider_name") or ""),
        context_window=int(row.get("context_window") or 0),
        max_output_tokens=int(row.get("max_output_tokens") or 4096),
        temperature=float(row.get("temperature") or 0.2),
        thinking_supported=bool(row.get("thinking_supported")),
        thinking_budget=int(row.get("thinking_budget") or 10000),
        adapter_profile_id=adapter_profile_id,
        # capability deliberately blank → resolved via the builtin capability table.
        capability="",
        is_default=bool(row.get("is_default")),
    )


def migrate_models_from_db(
    config_db: Path,
    *,
    model_store: ModelStore | None = None,
    work_root: str | None = None,
    scope: str = "global",
    force: bool = False,
) -> tuple[int, list[Path]]:
    """Export DB model rows to jsonc when the ModelStore is empty.

    Returns ``(exported_count, written_paths)``. When ``force`` is False and the
    ModelStore already contains models, no export happens (returns ``(0, [])`).
    """
    store = model_store or ModelStore()
    if not force and store.list_sync(work_root=work_root):
        return 0, []
    rows = _read_db_models(config_db)
    if not rows:
        return 0, []
    written: list[Path] = []
    for row in rows:
        model = _db_row_to_model_config(row)
        try:
            path = store.write(model, scope=scope, work_root=work_root)
            written.append(path)
        except OSError as exc:
            _logger.warning("failed to export model %s: %s", model.model_id, exc)
    _logger.info("migrated %d models from %s to jsonc", len(written), config_db)
    return len(written), written


__all__ = ["migrate_models_from_db"]
