from __future__ import annotations

import sys
from pathlib import Path

import pytest

from lamtools_core.config import root as root_module
from lamtools_core.config.root import default_projects_root, ensure_projects_root


def test_env_override_takes_priority(monkeypatch, tmp_path):
    custom = tmp_path / "custom-projects"
    monkeypatch.setenv("LAMTOOLS_PROJECTS_ROOT", str(custom))
    assert default_projects_root() == custom.resolve()


def test_dev_mode_resolves_under_repo_root(monkeypatch):
    monkeypatch.delenv("LAMTOOLS_PROJECTS_ROOT", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    resolved = default_projects_root()
    # In dev mode lam_projects sits at the repository root (parent of core/),
    # never inside core/ itself.
    assert resolved.name == "lam_projects"
    assert resolved.parent.name != "core"


def test_ensure_projects_root_creates_directory(monkeypatch, tmp_path):
    target = tmp_path / "lam_projects"
    monkeypatch.setenv("LAMTOOLS_PROJECTS_ROOT", str(target))
    assert not target.exists()
    result = ensure_projects_root()
    assert result == target.resolve()
    assert target.is_dir()


def test_ensure_projects_root_idempotent(monkeypatch, tmp_path):
    target = tmp_path / "lam_projects"
    monkeypatch.setenv("LAMTOOLS_PROJECTS_ROOT", str(target))
    ensure_projects_root()
    result = ensure_projects_root()
    assert result.is_dir()
