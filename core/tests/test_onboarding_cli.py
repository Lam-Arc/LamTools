"""Tests for the onboarding CLI entry points (settings.jsonc core.onboarding).

Covers:
- show: no marker → not completed; provider_configured reflects provider jsonc.
- complete: writes the completed marker; show then reports completed.
- reset: clears the marker; show reports not completed again.
- provider detection: only non-empty api_key counts as configured.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from lamtools_core.cli import cmd_onboarding_complete, cmd_onboarding_reset, cmd_onboarding_show


def _seed_provider(config_root: Path, *, api_key: str) -> None:
    provider_dir = config_root / "providers"
    provider_dir.mkdir(parents=True, exist_ok=True)
    (provider_dir / "openai.jsonc").write_text(
        '{\n'
        '  "id": "openai",\n'
        '  "name": "OpenAI",\n'
        '  "api_type": "openai",\n'
        '  "base_url": "https://api.openai.com/v1",\n'
        f'  "api_key": "{api_key}"\n'
        '}\n',
        encoding="utf-8",
    )


def _run(cmd, capsys) -> str:
    code = asyncio.run(cmd(argparse_namespace()))
    assert code == 0
    return capsys.readouterr().out


def argparse_namespace():
    import argparse

    return argparse.Namespace()


def test_show_reports_not_completed_without_marker(capsys):
    out = _run(cmd_onboarding_show, capsys)
    assert "completed: no" in out
    assert "provider_configured: no" in out


def test_complete_then_show_reports_completed(isolated_config_root: Path, capsys):
    _run(cmd_onboarding_complete, capsys)
    out = _run(cmd_onboarding_show, capsys)
    assert "completed: yes" in out
    assert "completed_at:" in out

    settings_path = isolated_config_root / "settings.jsonc"
    assert settings_path.is_file()
    value = json.loads(settings_path.read_text(encoding="utf-8"))["core"]["onboarding"]
    assert value["completed"] is True


def test_reset_clears_marker(capsys):
    _run(cmd_onboarding_complete, capsys)
    _run(cmd_onboarding_reset, capsys)
    out = _run(cmd_onboarding_show, capsys)
    assert "completed: no" in out


def test_show_reports_provider_configured(isolated_config_root: Path, capsys):
    _seed_provider(isolated_config_root, api_key="sk-test")
    out = _run(cmd_onboarding_show, capsys)
    assert "provider_configured: yes" in out


def test_show_ignores_provider_without_key(isolated_config_root: Path, capsys):
    _seed_provider(isolated_config_root, api_key="")
    out = _run(cmd_onboarding_show, capsys)
    assert "provider_configured: no" in out
