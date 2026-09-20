"""Contracts for files required by the staged Linux Tauri build."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TAURI_ROOT = ROOT / "core" / "desktop" / "src-tauri"


def test_every_configured_tauri_icon_exists_in_the_checkout() -> None:
    config = json.loads((TAURI_ROOT / "tauri.conf.json").read_text(encoding="utf-8"))
    icons = config["bundle"]["icon"]

    assert icons
    missing = [icon for icon in icons if not (TAURI_ROOT / icon).is_file()]
    assert missing == []
