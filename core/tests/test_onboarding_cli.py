"""Tests for the onboarding CLI entry points (app_settings core.onboarding).

Covers:
- show: no marker → not completed; provider_configured reflects llm_providers.
- complete: writes the completed marker; show then reports completed.
- reset: clears the marker; show reports not completed again.
- provider detection: only non-empty api_key counts as configured.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3

from lamtools_core.cli import cmd_onboarding_complete, cmd_onboarding_reset, cmd_onboarding_show

_SCHEMA = """
create table app_settings (
    namespace varchar(100) primary key,
    value json,
    updated_at datetime
);
create table llm_providers (
    id varchar(36) primary key,
    name varchar(100) not null,
    api_type varchar(50),
    base_url varchar(1024) not null,
    api_key varchar(1024) not null,
    is_default boolean,
    extra json,
    created_at datetime,
    updated_at datetime
);
"""


def _make_db(tmp_path) -> str:
    path = tmp_path / "config.db"
    con = sqlite3.connect(path)
    con.executescript(_SCHEMA)
    con.commit()
    con.close()
    return str(path)


def _run(cmd, path, capsys) -> str:
    args = argparse.Namespace(config_db=path)
    code = asyncio.run(cmd(args))
    assert code == 0
    return capsys.readouterr().out


def _seed_provider(path: str, *, api_key: str) -> None:
    con = sqlite3.connect(path)
    con.execute(
        "insert into llm_providers(id, name, base_url, api_key) values(?, ?, ?, ?)",
        ("p1", "OpenAI", "https://api.openai.com/v1", api_key),
    )
    con.commit()
    con.close()


def test_show_reports_not_completed_without_marker(tmp_path, capsys):
    out = _run(cmd_onboarding_show, _make_db(tmp_path), capsys)
    assert "completed: no" in out
    assert "provider_configured: no" in out


def test_complete_then_show_reports_completed(tmp_path, capsys):
    path = _make_db(tmp_path)
    _run(cmd_onboarding_complete, path, capsys)
    out = _run(cmd_onboarding_show, path, capsys)
    assert "completed: yes" in out
    assert "completed_at:" in out

    con = sqlite3.connect(path)
    row = con.execute("select value from app_settings where namespace='core.onboarding'").fetchone()
    con.close()
    assert json.loads(row[0])["completed"] is True


def test_reset_clears_marker(tmp_path, capsys):
    path = _make_db(tmp_path)
    _run(cmd_onboarding_complete, path, capsys)
    _run(cmd_onboarding_reset, path, capsys)
    out = _run(cmd_onboarding_show, path, capsys)
    assert "completed: no" in out


def test_show_reports_provider_configured(tmp_path, capsys):
    path = _make_db(tmp_path)
    _seed_provider(path, api_key="sk-test")
    out = _run(cmd_onboarding_show, path, capsys)
    assert "provider_configured: yes" in out


def test_show_ignores_provider_without_key(tmp_path, capsys):
    path = _make_db(tmp_path)
    _seed_provider(path, api_key="")
    out = _run(cmd_onboarding_show, path, capsys)
    assert "provider_configured: no" in out
