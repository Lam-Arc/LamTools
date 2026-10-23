"""Approval continuations rebuild the toolbox with the same settings."""

from __future__ import annotations

import json
from pathlib import Path

from lamtools_core.app.default_agent import (
    _effective_imagegen_config,
    _resolve_imagegen_config,
)


def test_approval_rebuild_reads_imagegen_plugin_config(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "imagegen.jsonc").write_text(
        json.dumps(
            {
                "enabled": True,
                "api_url": "http://127.0.0.1:1",
                "api_key": "test-key",
                "model": "test-model",
            }
        ),
        encoding="utf-8",
    )
    config = _resolve_imagegen_config(tmp_path)
    assert config is not None
    assert config["enabled"] is True
    assert config["api_url"] == "http://127.0.0.1:1"


def test_explicit_imagegen_config_wins(tmp_path: Path) -> None:
    explicit = {"enabled": True, "api_url": "explicit"}
    assert _effective_imagegen_config(explicit, {"data_dir": str(tmp_path)}) is explicit


def test_missing_imagegen_config_falls_back_to_saved_config(tmp_path: Path) -> None:
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "imagegen.jsonc").write_text(
        json.dumps({"enabled": True, "api_url": "saved"}),
        encoding="utf-8",
    )
    config = _effective_imagegen_config(None, {"data_dir": str(tmp_path)})
    assert config is not None
    assert config["api_url"] == "saved"


def test_approval_rebuild_without_data_dir_returns_none() -> None:
    assert _resolve_imagegen_config(None) is None


def test_approval_rebuild_without_config_returns_empty() -> None:
    assert _resolve_imagegen_config(Path("__missing_data_dir__")) == {}
