"""Tests for the dedicated imagegen.jsonc store + settings RPC routing."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from lamtools_core.config.imagegen_store import (
    imagegen_config_path,
    load_imagegen_config,
    save_imagegen_config,
)
from lamtools_core.config.operations import build_config_operation_catalog
from lamtools_core.app.operation_catalog import OperationRequest


def test_imagegen_config_path_points_at_unified_config_dir(isolated_config_root: Path) -> None:
    assert imagegen_config_path() == isolated_config_root / "imagegen.jsonc"


def test_load_missing_file_returns_empty_dict(isolated_config_root: Path) -> None:
    assert load_imagegen_config() == {}
    assert not imagegen_config_path().exists()


def test_save_and_load_round_trip(isolated_config_root: Path) -> None:
    save_imagegen_config({"enabled": True, "api_url": "https://img.test/v1", "api_key": "sk-img", "model": "img-model"})
    assert load_imagegen_config() == {
        "enabled": True,
        "api_url": "https://img.test/v1",
        "api_key": "sk-img",
        "model": "img-model",
    }
    assert json.loads(imagegen_config_path().read_text(encoding="utf-8"))["api_key"] == "sk-img"


def test_load_tolerates_jsonc_comments(isolated_config_root: Path) -> None:
    path = isolated_config_root / "imagegen.jsonc"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{\n  "enabled": true, // enabled flag\n  "api_url": "https://img.test/v1",\n}\n', encoding="utf-8")
    assert load_imagegen_config() == {"enabled": True, "api_url": "https://img.test/v1"}


@pytest.mark.asyncio
async def test_settings_rpc_routes_core_imagegen_to_imagegen_jsonc(isolated_config_root: Path) -> None:
    """settings.get/update with namespace core.imagegen must read/write the
    dedicated imagegen.jsonc — never settings.jsonc."""
    catalog = build_config_operation_catalog()

    result = await catalog.execute(
        "settings.update",
        {"namespace": "core.imagegen", "value": {"enabled": True, "model": "img-1"}},
        metadata={},
    )
    assert result.status == "ok"
    assert result.payload["value"] == {"enabled": True, "model": "img-1"}

    # Dedicated file was written; settings.jsonc untouched.
    assert (isolated_config_root / "imagegen.jsonc").is_file()
    assert not (isolated_config_root / "settings.jsonc").exists()

    # Merge semantics keep existing keys.
    await catalog.execute(
        "settings.update",
        {"namespace": "core.imagegen", "value": {"api_url": "https://img.test/v1"}},
        metadata={},
    )
    fetched = await catalog.execute("settings.get", {"namespace": "core.imagegen"}, metadata={})
    assert fetched.payload["value"] == {
        "enabled": True,
        "model": "img-1",
        "api_url": "https://img.test/v1",
    }


@pytest.mark.asyncio
async def test_settings_rpc_other_namespaces_still_use_settings_jsonc(isolated_config_root: Path) -> None:
    catalog = build_config_operation_catalog()
    await catalog.execute("settings.update", {"namespace": "core.dreaming", "value": {"enabled": True}}, metadata={})
    assert (isolated_config_root / "settings.jsonc").is_file()
    assert not (isolated_config_root / "imagegen.jsonc").exists()
