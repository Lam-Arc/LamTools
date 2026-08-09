"""Tests for the unified config directory seeding (config/defaults.py)."""

from __future__ import annotations

from pathlib import Path

from lamtools_core.config.defaults import (
    bundled_resources_dir,
    ensure_default_config_files,
)
from lamtools_core.config.root import core_config_dir


def test_ensure_default_config_files_creates_every_default(tmp_path, isolated_config_root):
    created = ensure_default_config_files()

    assert set(created) == {
        isolated_config_root / "hooks.json",
        isolated_config_root / "AGENTS.md",
        isolated_config_root / "load_context.jsonc",
        isolated_config_root / "memory.md",
        isolated_config_root / "subagent" / "guide.md",
        isolated_config_root / "subagent" / "settings.json",
    } | _bundled_copied(isolated_config_root)
    assert core_config_dir() == isolated_config_root
    for name in ("hooks.json", "AGENTS.md", "load_context.jsonc", "memory.md"):
        assert (isolated_config_root / name).is_file()
    assert (isolated_config_root / "subagent" / "guide.md").is_file()
    assert (isolated_config_root / "subagent" / "settings.json").is_file()
    assert (isolated_config_root / "models").is_dir()
    # Bundled resources are copied when present (dev checkout has them).
    if (bundled_resources_dir() / "loadtools.jsonc").is_file():
        assert (isolated_config_root / "loadtools.jsonc").is_file()
        assert (isolated_config_root / "access_tools.jsonc").is_file()


def _bundled_copied(config_dir: Path) -> set[Path]:
    copied: set[Path] = set()
    for name in ("loadtools.jsonc", "access_tools.jsonc"):
        if (bundled_resources_dir() / name).is_file():
            copied.add(config_dir / name)
    return copied


def test_ensure_default_config_files_is_idempotent(tmp_path, isolated_config_root):
    ensure_default_config_files()
    first = ensure_default_config_files()

    assert first == []
    # User edits survive a second run.
    agents = isolated_config_root / "AGENTS.md"
    agents.write_text("# My custom global instructions\n", encoding="utf-8")
    assert ensure_default_config_files() == []
    assert agents.read_text(encoding="utf-8") == "# My custom global instructions\n"


def test_ensure_default_config_files_never_overwrites_existing(tmp_path, isolated_config_root):
    # A pre-existing (legacy-install) file must not be clobbered.
    target = isolated_config_root / "AGENTS.md"
    target.parent.mkdir(parents=True)
    target.write_text("# keep me\n", encoding="utf-8")

    ensure_default_config_files()

    assert target.read_text(encoding="utf-8") == "# keep me\n"


def test_legacy_user_config_dir_still_serves_as_read_fallback(tmp_path, isolated_config_root):
    # The legacy {lam_home}/config/AGENTS.md keeps working for existing
    # installs until the unified file appears.
    from lamtools_core.config.agents_md import read_global_agents_md, write_global_agents_md

    legacy = tmp_path / "lam" / "config" / "AGENTS.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# legacy global\n", encoding="utf-8")

    result = read_global_agents_md()
    assert result["exists"] is True
    assert "# legacy global" in str(result["content"])

    # Writes always land in the unified directory.
    write_global_agents_md("# new location\n")
    assert (isolated_config_root / "AGENTS.md").read_text(encoding="utf-8") == "# new location\n"
