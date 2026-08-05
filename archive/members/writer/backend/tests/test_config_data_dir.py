from __future__ import annotations

import sqlite3

import app.config as config_module
from app.config import Settings
from app.config import _default_project_data_dir, _migrate_legacy_database


def _table_names(path) -> set[str]:
    with sqlite3.connect(path) as conn:
        return {
            str(row[0])
            for row in conn.execute("select name from sqlite_master where type='table'").fetchall()
        }


def test_default_project_data_dir_points_to_writer_data():
    data_dir = _default_project_data_dir()

    assert data_dir.name == "data"
    assert data_dir.parent.name == "writer"


def test_migrate_legacy_database_copies_runtime_tables_but_strips_shared_config(tmp_path):
    legacy = tmp_path / "legacy" / "LamWriter"
    target = tmp_path / "target"
    legacy.mkdir(parents=True)
    target.mkdir()
    legacy_db = legacy / "lamwriter.db"
    with sqlite3.connect(legacy_db) as conn:
        conn.executescript(
            """
            create table writer_sessions (id text primary key, title text);
            insert into writer_sessions (id, title) values ('session-1', 'Legacy session');

            create table llm_providers (
                id text primary key,
                name text,
                api_type text,
                base_url text,
                api_key text,
                is_default integer,
                extra text,
                created_at text,
                updated_at text
            );
            create table llm_models (
                id text primary key,
                provider_id text,
                model_id text,
                display_name text,
                context_window integer,
                max_output_tokens integer,
                thinking_supported integer,
                thinking_budget integer,
                temperature real,
                is_default integer,
                extra text,
                created_at text,
                updated_at text
            );
            insert into llm_providers values (
                'provider-1', 'Legacy Provider', 'openai', 'https://legacy.example/v1',
                'sk-legacy', 0, null, '2026-01-01', '2026-01-01'
            );
            insert into llm_models values (
                'model-1', 'provider-1', 'legacy-model', 'Legacy Model',
                128000, 4096, 1, 10000, 0.7, 0, null, '2026-01-01', '2026-01-01'
            );

            create table app_settings (namespace text primary key, value text, updated_at text);
            insert into app_settings values ('lamwriter.modelRouting', '{"routes":{}}', '2026-01-01');
            insert into app_settings values ('core.runtimeControls', '{"tools":{}}', '2026-01-01');
            insert into app_settings values ('writer.runtimeControls', '{"tools":{"write_file":true}}', '2026-01-01');
            insert into app_settings values ('lamwriter.runtimeControls', '{"tools":{"write_file":true}}', '2026-01-01');
            """
        )

    copied = _migrate_legacy_database(target, legacy)

    assert copied is True
    target_db = target / "lamwriter.db"
    assert "writer_sessions" in _table_names(target_db)
    assert "llm_providers" not in _table_names(target_db)
    assert "llm_models" not in _table_names(target_db)
    with sqlite3.connect(target_db) as conn:
        writer_session = conn.execute("select title from writer_sessions where id='session-1'").fetchone()
        settings = {
            str(row[0])
            for row in conn.execute("select namespace from app_settings order by namespace").fetchall()
        }
    assert writer_session == ("Legacy session",)
    assert settings == {"lamwriter.runtimeControls", "writer.runtimeControls"}


def test_migrate_legacy_database_does_not_overwrite_existing_db(tmp_path):
    legacy = tmp_path / "legacy" / "LamWriter"
    target = tmp_path / "target"
    legacy.mkdir(parents=True)
    target.mkdir()
    (legacy / "lamwriter.db").write_bytes(b"old-db")
    (target / "lamwriter.db").write_bytes(b"new-db")

    copied = _migrate_legacy_database(target, legacy)

    assert copied is False
    assert (target / "lamwriter.db").read_bytes() == b"new-db"


def test_explicit_data_dir_wins_over_project_default(tmp_path):
    explicit = tmp_path / "explicit"

    settings = Settings(data_dir=str(explicit), _env_file=None)

    assert settings.data_dir == str(explicit)
    assert settings.database_url.endswith("lamwriter.db")
    assert explicit.exists()


def test_explicit_database_url_skips_default_db_migration(tmp_path, monkeypatch):
    calls = []

    def fake_migrate(target_dir):
        calls.append(target_dir)
        return True

    monkeypatch.setattr(config_module, "_migrate_legacy_database", fake_migrate)

    Settings(
        data_dir=str(tmp_path / "data"),
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'custom.db'}",
        _env_file=None,
    )

    assert calls == []
