from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lamtools_core.config.migrate_models import migrate_models_from_db
from lamtools_core.config.model_store import ModelStore


def _make_config_db(db_path: Path) -> str:
    """Create a minimal shared config DB with one provider and two models."""
    con = sqlite3.connect(str(db_path))
    con.executescript(
        """
        CREATE TABLE llm_providers (
            id TEXT PRIMARY KEY, name TEXT, api_type TEXT, base_url TEXT,
            api_key TEXT, is_default INTEGER, extra TEXT,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE llm_models (
            id TEXT PRIMARY KEY, provider_id TEXT, model_id TEXT, display_name TEXT,
            context_window INTEGER, max_output_tokens INTEGER,
            thinking_supported INTEGER, thinking_budget INTEGER, temperature REAL,
            is_default INTEGER, extra TEXT,
            created_at TEXT, updated_at TEXT
        );
        INSERT INTO llm_providers VALUES (
            'prov-1', '讯飞 MaaS', 'openai', 'https://example.com/v2',
            'sk-test', 0, '{"adapter_profile_id":"xfyun-coding-plan"}',
            '2026-01-01', '2026-01-01'
        );
        INSERT INTO llm_models VALUES (
            'm-1', 'prov-1', 'xopglm52', 'GLM-5.2', 500000, 32768,
            1, 10000, 0.7, 0, 'null', '2026-01-01', '2026-01-01'
        );
        INSERT INTO llm_models VALUES (
            'm-2', 'prov-1', 'xopkimik26', 'Kimi-K2.6', 256000, 32768,
            1, 10000, 0.7, 1, 'null', '2026-01-02', '2026-01-02'
        );
        """
    )
    con.commit()
    con.close()
    return str(db_path)


@pytest.mark.asyncio
async def test_migrate_exports_db_models_to_jsonc(tmp_path, isolated_config_root):
    db_path = tmp_path / "lamtools.db"
    _make_config_db(db_path)

    store = ModelStore()
    # No jsonc files yet → migration should export both rows.
    count, paths = migrate_models_from_db(db_path, model_store=store, scope="global")

    assert count == 2
    assert len(paths) == 2
    # Files land under the unified config dir models/.
    global_dir = isolated_config_root / "models"
    assert (global_dir / "xopglm52.jsonc").is_file()
    assert (global_dir / "xopkimik26.jsonc").is_file()


def test_migrate_preserves_provider_name_and_default_flag(tmp_path, isolated_config_root):
    db_path = tmp_path / "lamtools.db"
    _make_config_db(db_path)

    store = ModelStore()
    migrate_models_from_db(db_path, model_store=store, scope="global")

    # Reload via a fresh store to read the exported files.
    store2 = ModelStore()
    glm = store2.get_sync("xopglm52", work_root=None)
    kimi = store2.get_sync("xopkimik26", work_root=None)

    assert glm is not None and kimi is not None
    assert glm.provider == "讯飞 MaaS"
    assert glm.context_window == 500000
    assert glm.adapter_profile_id == ""  # model extra was 'null', not a profile
    assert kimi.is_default is True
    assert glm.is_default is False
    assert store2.default_model_id_sync(work_root=None) == "xopkimik26"


def test_migrate_skips_when_modelstore_already_populated(tmp_path, isolated_config_root):
    db_path = tmp_path / "lamtools.db"
    _make_config_db(db_path)

    # Pre-populate with one model so the store is non-empty.
    global_dir = isolated_config_root / "models"
    global_dir.mkdir(parents=True, exist_ok=True)
    (global_dir / "existing.jsonc").write_text(
        '{"model_id":"existing","display_name":"Existing","provider":"P",'
        '"context_window":128000,"max_output_tokens":32768,"temperature":0.7,'
        '"thinking":{"supported":false,"budget":0},"capability":"text"}',
        encoding="utf-8",
    )

    store = ModelStore()
    count, paths = migrate_models_from_db(db_path, model_store=store, scope="global")

    # Should not export because the store already has a model.
    assert count == 0
    assert paths == []
    assert not (global_dir / "xopglm52.jsonc").exists()


def test_migrate_force_overrides_existing_store(tmp_path, isolated_config_root):
    db_path = tmp_path / "lamtools.db"
    _make_config_db(db_path)
    global_dir = isolated_config_root / "models"
    global_dir.mkdir(parents=True, exist_ok=True)
    (global_dir / "existing.jsonc").write_text(
        '{"model_id":"existing","display_name":"Existing","provider":"P",'
        '"context_window":128000,"max_output_tokens":32768,"temperature":0.7,'
        '"thinking":{"supported":false,"budget":0},"capability":"text"}',
        encoding="utf-8",
    )

    store = ModelStore()
    count, _paths = migrate_models_from_db(db_path, model_store=store, scope="global", force=True)

    assert count == 2  # force exports even though the store is non-empty


def test_migrate_handles_missing_db(tmp_path, isolated_config_root):
    store = ModelStore()
    count, paths = migrate_models_from_db(tmp_path / "nonexistent.db", model_store=store, scope="global")
    assert count == 0
    assert paths == []
