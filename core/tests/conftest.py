"""Shared pytest fixtures for LamTools Core."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_config_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every config root at a temp location and return the unified
    config directory (``.lam/core/config``).

    Autouse: LAMTOOLS_CORE_CONFIG_ROOT pins the unified config dir and
    LAMTOOLS_HOME pins the legacy ``{lam_home}/config`` fallback for *every*
    test. Without this, anything writing a global-scope config (model
    migration, sub-agent guide, AGENTS.md, …) would leak into the developer's
    real ``~/.lam`` or repo ``.lam/core`` directories.
    """
    lam = tmp_path / "lam"
    monkeypatch.setenv("LAMTOOLS_CORE_CONFIG_ROOT", str(lam / "core"))
    monkeypatch.setenv("LAMTOOLS_HOME", str(lam))
    return lam / "core" / "config"
